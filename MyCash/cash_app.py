# -*- coding: utf-8 -*-
"""
금융정보 Flask 서브앱 (cash_app.py).

병합작업·업종분류 페이지를 제공하고,
bank_after와 card_after를 병합해 cash_after를 생성한다.
"""
from flask import Flask, render_template, jsonify, request, make_response
import logging

import math
import pandas as pd
from pathlib import Path
import sys
import io
import os
from datetime import datetime, timedelta

# ----- UTF-8 인코딩 (Windows 콘솔용) -----
if sys.platform == 'win32':
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except (OSError, AttributeError):
        pass  # 콘솔 UTF-8 래핑 실패 시 무시(통합 서버에서 app.py가 이미 설정)

app = Flask(__name__)
logger = logging.getLogger(__name__)

# JSON 인코딩 설정 (한글 지원)
app.json.ensure_ascii = False
app.config['JSON_AS_ASCII'] = False

@app.after_request
def _set_json_charset(response):
    if response.content_type and response.content_type.startswith('application/json'):
        response.headers['Content-Type'] = 'application/json; charset=utf-8'
    return response

# ----- 경로·출력 컬럼 상수 (모듈 로드 시 한 번 계산) -----
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.normpath(os.path.join(SCRIPT_DIR, '..'))
# category_table: MyRisk/data (카테고리 정의 + 업종분류, category_table_io)
# 업종분류: lib/category_table_io.py가 category_table.json만 읽어 매칭 제공
# 금융정보는 bank_after+card_after만 사용. .source/Cash 미사용.
try:
    from lib.path_config import (
        get_category_table_json_path,
        get_cash_after_path,
        get_bank_after_path,
        get_card_after_path,
    )
    CATEGORY_TABLE_PATH = get_category_table_json_path()
    CASH_AFTER_PATH = get_cash_after_path()
    BANK_AFTER_PATH = Path(get_bank_after_path())
    CARD_AFTER_PATH = Path(get_card_after_path())
except ImportError:
    _data = Path(PROJECT_ROOT) / 'data'
    CATEGORY_TABLE_PATH = str(_data / 'category_table.json')
    CASH_AFTER_PATH = os.path.join(_data, 'cash_after.json')
    BANK_AFTER_PATH = _data / 'bank_after.json'
    CARD_AFTER_PATH = _data / 'card_after.json'
# 금융정보(MyCash): card·cash 테이블 연동만 하지 않음. 은행/카드 데이터 불러와 병합(cash_after 생성)은 진행.
MYCASH_ONLY_NO_BANK_CARD_LINK = False
# 금융정보 병합작업전/전처리후: 은행거래·신용카드 after 파일 (MYCASH_ONLY_NO_BANK_CARD_LINK 시 미사용) — data/ 사용

try:
    from lib.data_json_io import safe_read_data_json, safe_write_data_json
except ImportError:
    safe_read_data_json = None
    safe_write_data_json = None

# 전처리전(은행거래) 출력 컬럼 · 계좌번호 1.0, 기타거래 2.0 (index.html LEFT_WIDTHS) — bank_after의 기타거래 출력
BANK_AFTER_DISPLAY_COLUMNS = ['은행명', '계좌번호', '거래일', '거래시간', '입금액', '출금액', '취소', '기타거래', '카테고리']
# 전처리후(신용카드) 출력 컬럼 · 카드번호 1.0, 가맹점명 2.0 (index.html RIGHT_WIDTHS) — card_after의 가맹점명 출력
CARD_AFTER_DISPLAY_COLUMNS = ['카드사', '카드번호', '이용일', '이용시간', '입금액', '출금액', '취소', '가맹점명', '카테고리']
# 업종분류조회(cash_after) 테이블 출력 11컬럼 · 계좌번호 1.0, 기타거래 2.0 (index.html QUERY_WIDTHS)
CATEGORY_QUERY_DISPLAY_COLUMNS = ['금융사', '계좌번호', '거래일', '거래시간', '입금액', '출금액', '취소', '기타거래', '키워드', '카테고리', '사업자번호']
# 업종분류 적용후(cash_after) 테이블 출력 · 기타거래 뒤 키워드·계정과목(카테고리), 위험도키워드·위험도분류·위험도
CATEGORY_APPLIED_DISPLAY_COLUMNS = ['금융사', '계좌번호', '거래일', '거래시간', '입금액', '출금액', '취소', '기타거래', '키워드', '카테고리', '사업자번호', '폐업', '출처', '위험도키워드', '위험도분류', '위험도', '대체구분']
# cash_after 생성 시 저장 컬럼. 폐업 = '폐업' 또는 ''. 출처 = '은행거래'|'신용카드'(요약용)
CASH_AFTER_CREATION_COLUMNS = ['금융사', '계좌번호', '거래일', '거래시간', '입금액', '출금액', '취소', '기타거래', '키워드', '카테고리', '사업자번호', '폐업', '출처', '위험도키워드', '위험도분류', '위험도', '대체구분']
# 은행거래 판별용 금융사명 집합 — cash_after 집계에서 카드/은행 구분 기준으로 사용
BANK_NAMES: frozenset = frozenset({
    '국민은행', 'KB국민은행', '한국주택은행', '국민', '국민 은행',
    '신한은행', '신한',
    '하나은행', '하나',
})
# 병합 오류 메시지 (bank/card의 LAST_CLASSIFY_ERROR와 동일하게 실패 시 설정)
LAST_MERGE_ERROR = None
# category_table.json 단일 테이블(구분 없음, category_table_io로 읽기/쓰기)
from lib.category_table_io import (
    load_category_table, normalize_category_df, CATEGORY_TABLE_COLUMNS,
    CATEGORY_TABLE_EXTENDED_COLUMNS,
    get_category_table as _io_get_category_table,
    apply_category_action,
    _to_str_no_decimal,
)
from lib.category_constants import (
    get_template_constants,
    CLASS_APPLICANT, CLASS_NIGHT, CLASS_INDUSTRY, CLASS_RISK,
)

# ----- 데코레이터·JSON/데이터 유틸 (공통 모듈 사용) -----
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
from lib.shared_app_utils import (
    make_ensure_working_directory,
    json_safe as _json_safe,
    format_bytes,
    df_memory_bytes,
    BANK_FILTER_ALIASES,
    safe_취소 as _safe_취소,
    time_to_seconds as _time_to_seconds,
)
try:
    from lib.after_cache import AfterCache
except ImportError:
    AfterCache = None
ensure_working_directory = make_ensure_working_directory(SCRIPT_DIR)

# ----- 파일·캐시 로드 (전처리후, cash_after, bank_after, card_after. 원본 .source/Cash 미사용) -----
def load_processed_file():
    """금융정보는 cash_after만 사용. cash_before 미사용으로 항상 빈 DataFrame 반환."""
    return pd.DataFrame()

# cash_after 캐시 (lib.after_cache 공통)
_cash_after_cache_obj = AfterCache() if AfterCache else None

def _read_cash_after_raw(path):
    """cash_after 파일 읽기 + 컬럼·위험도 정규화 (캐시용)."""
    try:
        if safe_read_data_json and str(path).endswith('.json'):
            df = safe_read_data_json(str(path), default_empty=True)
        else:
            df = pd.read_excel(str(path), engine='openpyxl')
        if df is None or df.empty:
            return pd.DataFrame()
        df = df.copy()
        if '위험지표' in df.columns and '위험도키워드' not in df.columns:
            df = df.rename(columns={'위험지표': '위험도키워드'})
        if '업종키워드' in df.columns and '위험도키워드' not in df.columns:
            df = df.rename(columns={'업종키워드': '위험도키워드'})
        if '업종분류' in df.columns and '위험도분류' not in df.columns:
            df = df.rename(columns={'업종분류': '위험도분류'})
        if '위험도' in df.columns:
            def _norm_위험도(v):
                if v is None or v == '' or (isinstance(v, float) and pd.isna(v)):
                    return 0.1
                try:
                    f = float(v)
                    return max(0.1, f) if f >= 0 else 0.1
                except (TypeError, ValueError):
                    return 0.1
            df['위험도'] = df['위험도'].apply(_norm_위험도)
        if '은행명' not in df.columns and '금융사' in df.columns:
            df['은행명'] = df['금융사'].fillna('').astype(str).str.strip()
        return df
    except (OSError, ValueError, TypeError) as e:
        return pd.DataFrame()

def load_category_file():
    """업종분류 적용 파일 로드 (MyRisk/data/cash_after.json). 캐시 있으면 재사용, 재생성 시에만 파일 재읽기."""
    if _cash_after_cache_obj is None:
        try:
            return _read_cash_after_raw(CASH_AFTER_PATH)
        except (OSError, ValueError, TypeError) as e:
            return pd.DataFrame()
    try:
        return _cash_after_cache_obj.get(CASH_AFTER_PATH, _read_cash_after_raw)
    except (OSError, ValueError, TypeError) as e:
        return pd.DataFrame()

def load_bank_after_file():
    """전처리전(은행거래)용: MyBank/bank_after 로드. 출력용 컬럼만 정규화하여 반환."""
    try:
        path = BANK_AFTER_PATH
        if not path.exists():
            return pd.DataFrame()
        if safe_read_data_json and str(path).endswith('.json'):
            df = safe_read_data_json(str(path), default_empty=True)
        else:
            df = pd.read_excel(str(path), engine='openpyxl')
        if df is None:
            df = pd.DataFrame()
        if df.empty:
            return df
        # 구분 → 취소. 출력은 기타거래 컬럼(bank_after 기타거래)
        if '구분' in df.columns and '취소' not in df.columns:
            df = df.rename(columns={'구분': '취소'})
        if '기타거래' not in df.columns:
            if '가맹점명' in df.columns:
                df['기타거래'] = df['가맹점명'].fillna('').astype(str).str.strip()
            elif '내용' in df.columns:
                df['기타거래'] = df['내용'].fillna('').astype(str).str.strip()
            elif '거래점' in df.columns:
                df['기타거래'] = df['거래점'].fillna('').astype(str).str.strip()
            else:
                df['기타거래'] = ''
        for c in BANK_AFTER_DISPLAY_COLUMNS:
            if c not in df.columns:
                df[c] = '' if c != '입금액' and c != '출금액' else 0
        return df[BANK_AFTER_DISPLAY_COLUMNS].copy()
    except (OSError, ValueError, TypeError) as e:
        return pd.DataFrame()

def load_card_after_file():
    """전처리후(신용카드)용: MyCard/card_after 로드. 출력용 컬럼만 정규화하여 반환."""
    try:
        path = CARD_AFTER_PATH
        if not path.exists():
            return pd.DataFrame()
        if safe_read_data_json and str(path).endswith('.json'):
            df = safe_read_data_json(str(path), default_empty=True)
        else:
            df = pd.read_excel(str(path), engine='openpyxl')
        if df is None:
            df = pd.DataFrame()
        if df.empty:
            return df
        # 출력은 가맹점명(card_after 가맹점명). 가맹점명 없으면 빈 컬럼 추가
        if '가맹점명' not in df.columns:
            df['가맹점명'] = ''
        for c in CARD_AFTER_DISPLAY_COLUMNS:
            if c not in df.columns:
                df[c] = '' if c not in ('입금액', '출금액') else 0
        return df[CARD_AFTER_DISPLAY_COLUMNS].copy()
    except (OSError, ValueError, TypeError) as e:
        return pd.DataFrame()

def _safe_keyword(val):
    """키워드 값을 cash_after에 저장할 때 항상 문자열로 반환 (NaN/None → '')."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ''
    return str(val).strip()


def _str_strip(val):
    """값을 문자열로 정규화 (NaN/None → '', 그 외 strip). 위험지표 등에 사용."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ''
    return str(val).strip()


def _safe_폐업(val):
    """card_after 폐업 값을 cash_after에 저장할 때 '폐업'만 유지, 그 외·결측은 ''."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ''
    s = str(val).strip()
    return '폐업' if s == '폐업' else ''


def _safe_사업자번호(val):
    """사업자번호/사업자번호를 cash_after에 저장할 때 문자열로 반환 (NaN/float → 적절히 변환)."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ''
    s = str(val).strip()
    if s in ('', 'nan', 'None'):
        return ''
    if s.endswith('.0'):
        s = s[:-2]
    return s


# ----- cash_after 병합: DataFrame 변환·업종분류·위험도 적용·저장 -----
def _dataframe_to_cash_after_creation(df_bank, df_card):
    """은행거래(bank_after) + 신용카드(card_after)를 병합하여 cash_after 생성용 DataFrame 반환. 키워드는 bank/card에서 반드시 복사."""
    rows = []
    def add_bank():
        if df_bank is None or df_bank.empty:
            return
        kw_col = '키워드' if '키워드' in df_bank.columns else None
        col_code = '위험도키워드' if '위험도키워드' in df_bank.columns else ('업종키워드' if '업종키워드' in df_bank.columns else None)
        for _, r in df_bank.iterrows():
            kw = _safe_keyword(r.get(kw_col) if kw_col else r.get('키워드', ''))
            rows.append({
                '금융사': r.get('은행명', '') or '',
                '계좌번호': r.get('계좌번호', '') or '',
                '거래일': r.get('거래일', '') or '',
                '거래시간': r.get('거래시간', '') or '',
                '입금액': r.get('입금액', 0) or 0,
                '출금액': r.get('출금액', 0) or 0,
                '취소': _safe_취소(r.get('취소')),  # 폐업은 취소에 넣지 않음(폐업 컬럼에만 저장)
                '기타거래': (r.get('기타거래') or '').strip() or '',  # bank: bank_after 기타거래만 (없으면 "")
                '키워드': kw,
                '카테고리': r.get('카테고리', '') or '',
                '사업자번호': '',
                '폐업': '',  # 폐업은 폐업만 저장, 은행은 해당 없음
                '출처': '은행거래',
                '위험도키워드': _str_strip(r.get(col_code) or r.get('업종키워드')) if col_code else '',
                '위험도분류': '',
                '위험도': '',
                '대체구분': '',
            })
    def add_card():
        if df_card is None or df_card.empty:
            return
        kw_col = '키워드' if '키워드' in df_card.columns else None
        col_c = '위험도키워드' if '위험도키워드' in df_card.columns else ('업종키워드' if '업종키워드' in df_card.columns else None)
        for _, r in df_card.iterrows():
            kw = _safe_keyword(r.get(kw_col) if kw_col else r.get('키워드', ''))
            rows.append({
                '금융사': r.get('카드사', '') or '',
                '계좌번호': r.get('카드번호', '') or '',
                '거래일': r.get('이용일', '') or '',
                '거래시간': r.get('이용시간', '') or '',
                '입금액': r.get('입금액', 0) or 0,
                '출금액': r.get('출금액', 0) or 0,
                '취소': _safe_취소(r.get('취소')),  # 폐업은 취소에 넣지 않음(폐업 컬럼에만 저장)
                '기타거래': (r.get('가맹점명') or '').strip() or '',  # card: 가맹점명만 (없으면 "")
                '키워드': kw,
                '카테고리': r.get('카테고리', '') or '',
                '사업자번호': _safe_사업자번호(r.get('사업자번호')),
                '폐업': _safe_폐업(r.get('폐업')),  # 폐업만 유지, 그 외 ''
                '출처': '신용카드',
                '위험도키워드': _str_strip(r.get(col_c) or r.get('업종키워드')) if col_c else '',
                '위험도분류': '',
                '위험도': '',
                '대체구분': '',
            })
    add_bank()
    add_card()
    if not rows:
        return pd.DataFrame(columns=CASH_AFTER_CREATION_COLUMNS)
    out = pd.DataFrame(rows)
    for c in CASH_AFTER_CREATION_COLUMNS:
        if c not in out.columns:
            out[c] = '' if c not in ('입금액', '출금액') else 0
    # 키워드 컬럼이 반드시 문자열로 채워지도록 보장 (NaN/결측 없음)
    out['키워드'] = out['키워드'].fillna('').astype(str).str.strip()
    return out[CASH_AFTER_CREATION_COLUMNS].copy()


def _apply_업종분류_from_category_table(df):
    """cash_after DataFrame에 대해: category_table 기반(category_table_io)으로 위험도키워드→위험도분류·위험도 매칭. in-place 수정."""
    code_col = '위험도키워드' if '위험도키워드' in df.columns else ('업종키워드' if '업종키워드' in df.columns else '위험지표')
    분류_col = '위험도분류' if '위험도분류' in df.columns else '업종분류'
    if df is None or df.empty or code_col not in df.columns:
        return
    try:
        from lib.category_table_io import get_risk_class_map_for_apply
        code_to_업종분류, code_to_위험도 = get_risk_class_map_for_apply()
        n_keys = len(code_to_업종분류) if code_to_업종분류 else 0
        _log_cash_after("업종분류 맵 로드 완료 (%d개 키), 행별 매칭 시작 (%d행)" % (n_keys, len(df)))
        if not code_to_업종분류:
            return
        # 위험도 컬럼이 병합 시 ''로 채워져 str dtype이면, 0/float 대입 시 오류 나므로 미리 float로 통일
        if '위험도' in df.columns:
            df['위험도'] = pd.to_numeric(df['위험도'], errors='coerce').fillna(0).astype(float)
        # 5~10호는 코드 매핑으로 설정하지 않음. apply_risk_indicators에서 거래 텍스트 키워드 매칭으로만 분류하고, 매칭된 키워드를 위험도키워드에 저장.
        CLASS_5_10 = ('투기성지표', '사기파산지표', '가상자산지표', '자산은닉지표', '과소비지표', '사행성지표')
        codes = df[code_col].fillna('').astype(str).str.strip()
        for i in df.index:
            c = codes.at[i] if i in codes.index else ''
            if c:
                업종분류_val = code_to_업종분류.get(c, '')
                if 업종분류_val in CLASS_5_10:
                    continue  # 5~10호는 키워드 매칭으로만 적용(apply_risk_indicators에서 위험도키워드=매칭된 키워드)
                위험도_str = code_to_위험도.get(c, '')
                try:
                    위험도_val = float(위험도_str) if 위험도_str else (5 if 업종분류_val else 0)
                except (ValueError, TypeError):
                    위험도_val = 5 if 업종분류_val else 0
                df.at[i, 분류_col] = 업종분류_val
                df.at[i, '위험도'] = 위험도_val
            else:
                df.at[i, '위험도'] = 0
        _log_cash_after("업종분류 행별 매칭 완료")
    except Exception as e:
        # 업종분류 매칭 실패 시에도 cash_after 병합은 계속 진행
        _log_cash_after("업종분류 매칭 예외(무시): %s" % e)


def _log_cash_after(msg):
    """cash_after 생성 단계를 로그에 출력."""
    logger.info("[cash_after] %s", msg)


def _min_risk_value(v):
    """위험도 값을 최소 0.1 이상으로 보정한다."""
    if v is None or v == '' or (isinstance(v, float) and pd.isna(v)):
        return 0.1
    try:
        return max(0.1, float(v))
    except (TypeError, ValueError):
        return 0.1


def _format_risk_guidelines_py(d):
    """RISK_GUIDELINES 딕셔너리를 Python 소스 문자열로 변환한다 (인쇄용 보고서 삽입 목적)."""
    lines = ["{"]
    for k, v in d.items():
        name = str(v.get("name", ""))
        w = v.get("weight", 0)
        th = v.get("threshold", 0)
        lines.append('    "{}": {{"name": "{}", "weight": {}, "threshold": {}}},'.format(
            str(k), name.replace('"', '\\"'), w, th))
    lines.append("}")
    return "\n".join(lines)


def _format_current_status_py(lst):
    """current_status 리스트를 Python 소스 문자열로 변환한다 (인쇄용 보고서 삽입 목적)."""
    lines = ["["]
    for item in lst:
        iid = str(item.get("id", ""))
        cnt = item.get("count", 0)
        amt = item.get("amount", 0)
        lines.append('    {{"id": "{}", "count": {}, "amount": {}}},'.format(
            iid.replace('"', '\\"'), cnt, amt))
    lines.append("]")
    return "\n".join(lines)


def _normalize_cash_columns(df):
    """은행명/카드사 → 금융사, 카드번호 → 계좌번호, 이용일 → 거래일 등 cash_after 컬럼명을 표준화한다."""
    if '금융사' not in df.columns:
        if '은행명' in df.columns:
            df['금융사'] = df['은행명'].fillna('')
        elif '카드사' in df.columns:
            df['금융사'] = df['카드사'].fillna('')
        else:
            df['금융사'] = ''
    if '계좌번호' not in df.columns and '카드번호' in df.columns:
        df['계좌번호'] = df['카드번호'].fillna('').astype(str)
    if '거래일' not in df.columns and '이용일' in df.columns:
        df['거래일'] = df['이용일'].fillna('')
    if '거래시간' not in df.columns and '이용시간' in df.columns:
        df['거래시간'] = df['이용시간'].fillna('')
    if '기타거래' not in df.columns and '가맹점명' in df.columns:
        df['기타거래'] = df['가맹점명'].fillna('')
    if '대체구분' not in df.columns:
        df['대체구분'] = ''
    else:
        df['대체구분'] = df['대체구분'].fillna('').astype(str)
    return df


def _load_bank_after_for_merge():
    """cash_after 병합용: MyBank/bank_after.json 전체 컬럼 로드. 키워드 컬럼이 반드시 있도록 보장하고 NaN은 ''로 채움."""
    try:
        if not BANK_AFTER_PATH.exists():
            _log_cash_after("bank_after 파일 없음 (경로: %s)" % BANK_AFTER_PATH)
            return pd.DataFrame()
        if safe_read_data_json and str(BANK_AFTER_PATH).endswith('.json'):
            df = safe_read_data_json(str(BANK_AFTER_PATH), default_empty=True)
        else:
            df = pd.read_excel(str(BANK_AFTER_PATH), engine='openpyxl')
        if df is None:
            df = pd.DataFrame()
        if df.empty:
            _log_cash_after("bank_after 로드 완료: 0건")
            return df
        _log_cash_after("bank_after 로드 완료: %d건" % len(df))
        if '구분' in df.columns and '취소' not in df.columns:
            df = df.rename(columns={'구분': '취소'})
        if '가맹점명' not in df.columns:
            if '내용' in df.columns:
                df['가맹점명'] = df['내용'].fillna('')
            elif '거래점' in df.columns:
                df['가맹점명'] = df['거래점'].fillna('')
            else:
                df['가맹점명'] = ''
        if '키워드' not in df.columns:
            df['키워드'] = ''
        df['키워드'] = df['키워드'].fillna('').astype(str).str.strip()
        return df
    except Exception as e:
        return pd.DataFrame()

def merge_bank_card_to_cash_after():
    """bank_after + card_after를 병합하여 cash_after.json 생성.
    병합작업에서는 bank_after·card_after를 다시 만들지 않고, 이미 있는 JSON만 읽어 사용한다.
    bank만 있으면 bank_after만, card만 있으면 card_after만 사용하여 병합한다. 없으면 해당 쪽은 빈 DataFrame으로 처리.
    없으면 해당 파일만 빈 JSON으로 생성(있는 것만 생성). 둘 다 없거나 비어 있어도 에러가 아니며, 빈 cash_after.json 저장 후 성공 반환.
    금융정보(MyCash)에는 전처리·계정과목분류·후처리 없음. 은행/카드 after의 키워드·카테고리를 그대로 사용하고,
    업종분류(category_table 기반)·위험도만 추가 적용. .bak 생성하지 않음. 실패 시 LAST_MERGE_ERROR 설정."""
    global LAST_MERGE_ERROR
    LAST_MERGE_ERROR = None
    try:
        _log_cash_after("========== cash_after 생성 시작 ==========")
        if _cash_after_cache_obj is not None:
            _cash_after_cache_obj.invalidate()
        _log_cash_after("캐시 초기화 완료")
        # 금융정보(은행+카드) 병합조회 테이블(cash_after.json) 초기화 후 병합 시작
        if safe_write_data_json and CASH_AFTER_PATH.endswith('.json'):
            try:
                safe_write_data_json(CASH_AFTER_PATH, pd.DataFrame())
                _log_cash_after("cash_after.json 초기화 완료(0건), 병합작업 시작")
            except Exception as ex:
                _log_cash_after("cash_after.json 초기화 쓰기 무시: %s" % ex)
        if not BANK_AFTER_PATH.exists() and safe_write_data_json and str(BANK_AFTER_PATH).endswith('.json'):
            try:
                safe_write_data_json(str(BANK_AFTER_PATH), pd.DataFrame())
                _log_cash_after("bank_after 없음 → 빈 JSON 생성: %s" % BANK_AFTER_PATH)
            except Exception as ex:
                _log_cash_after("bank_after 빈 JSON 생성 무시: %s" % ex)
        _log_cash_after("(1/6) bank_after 로드 중: %s" % BANK_AFTER_PATH)
        df_bank = _load_bank_after_for_merge()
        df_card_raw = pd.DataFrame()
        if not CARD_AFTER_PATH.exists() and safe_write_data_json and str(CARD_AFTER_PATH).endswith('.json'):
            try:
                safe_write_data_json(str(CARD_AFTER_PATH), pd.DataFrame())
                _log_cash_after("card_after 없음 → 빈 JSON 생성: %s" % CARD_AFTER_PATH)
            except Exception as ex:
                _log_cash_after("card_after 빈 JSON 생성 무시: %s" % ex)
        _log_cash_after("(2/6) card_after 로드 중: %s" % CARD_AFTER_PATH)
        if CARD_AFTER_PATH.exists():
            try:
                if safe_read_data_json and str(CARD_AFTER_PATH).endswith('.json'):
                    df_card_raw = safe_read_data_json(str(CARD_AFTER_PATH), default_empty=True)
                else:
                    df_card_raw = pd.read_excel(str(CARD_AFTER_PATH), engine='openpyxl')
                if df_card_raw is None:
                    df_card_raw = pd.DataFrame()
                df_card_raw.columns = df_card_raw.columns.astype(str).str.strip()
                # cash_after 기타거래 = card_after의 가맹점명(가맹점). 키워드 컬럼은 별도 유지.
                if '기타거래' not in df_card_raw.columns and '가맹점명' in df_card_raw.columns:
                    df_card_raw['기타거래'] = df_card_raw['가맹점명'].fillna('').astype(str).str.strip()
                if '키워드' not in df_card_raw.columns:
                    df_card_raw['키워드'] = ''
                df_card_raw['키워드'] = df_card_raw['키워드'].fillna('').astype(str).str.strip()
                if '폐업' not in df_card_raw.columns:
                    df_card_raw['폐업'] = ''
                else:
                    df_card_raw['폐업'] = df_card_raw['폐업'].fillna('').astype(str).str.strip()
                if '사업자번호' not in df_card_raw.columns:
                    if '사업자등록번호' in df_card_raw.columns:
                        df_card_raw['사업자번호'] = df_card_raw['사업자등록번호'].fillna('').astype(str).str.strip()
                    else:
                        df_card_raw['사업자번호'] = ''
                else:
                    df_card_raw['사업자번호'] = df_card_raw['사업자번호'].fillna('').astype(str).str.strip()
            except Exception as ex:
                _log_cash_after("card_after 로드 예외: %s" % ex)
        if not df_card_raw.empty:
            _log_cash_after("card_after 로드 완료: %d건" % len(df_card_raw))
        else:
            _log_cash_after("card_after 없음 또는 0건")
        _log_cash_after("(3/6) bank+card DataFrame 병합 중")
        df = _dataframe_to_cash_after_creation(df_bank, df_card_raw if not df_card_raw.empty else None)
        _log_cash_after("병합 완료: %d건" % len(df))
        _log_cash_after("(4/6) category_table 기반 업종분류·위험도 매칭 적용 중")
        _apply_업종분류_from_category_table(df)
        _log_cash_after("업종분류 매칭 완료")
        _log_cash_after("(5/6) 위험도 지표 1~10호 적용 중")
        try:
            if SCRIPT_DIR not in sys.path:
                sys.path.insert(0, SCRIPT_DIR)
            from risk_indicators import apply_risk_indicators
            apply_risk_indicators(df, category_table_path=CATEGORY_TABLE_PATH)
            _log_cash_after("위험도 지표 1~10호 적용 완료")
        except Exception as e:
            _log_cash_after("위험도 지표 적용 예외: %s" % e)
        # 저장 전 위험도 최소 0.1 보장
        if '위험도' in df.columns:
            _log_cash_after("위험도 최소 0.1 보정 적용 중 (%d행)" % len(df))
            df['위험도'] = df['위험도'].apply(_min_risk_value)
            _log_cash_after("위험도 최소 0.1 보정 완료")
        out_path = Path(CASH_AFTER_PATH)
        _log_cash_after("(6/6) 파일 저장 중: %s" % out_path)
        if safe_write_data_json and CASH_AFTER_PATH.endswith('.json'):
            if not safe_write_data_json(CASH_AFTER_PATH, df):
                err = 'cash_after 파일 쓰기 실패'
                LAST_MERGE_ERROR = err
                _log_cash_after("실패: cash_after.json 쓰기 실패")
                _log_cash_after("========== cash_after 생성 종료 (실패: 파일 쓰기) ==========")
                return (False, err, 0)
            _log_cash_after("cash_after.json 저장 완료 (%d건)" % len(df))
        else:
            _log_cash_after("Excel 저장 모드로 저장 중")
            df.to_excel(str(CASH_AFTER_PATH), index=False, engine='openpyxl')
        _log_cash_after("캐시 초기화 중 (_cash_after_cache_obj 비우기)")
        if _cash_after_cache_obj is not None:
            _cash_after_cache_obj.invalidate()
        _log_cash_after("캐시 초기화 완료")
        _log_cash_after("========== cash_after 생성 종료 (성공): %d건 ==========" % len(df))
        return (True, None, len(df))
    except Exception as e:
        err = str(e)
        LAST_MERGE_ERROR = err
        _log_cash_after("오류: 병합 생성 실패 - %s" % e)
        _log_cash_after("========== cash_after 생성 종료 (예외) ==========")
        return (False, err, 0)


# ----- 페이지 라우트: 전처리(/)·업종분류(/category)·분석·도움말 -----
@app.route('/')
def index():
    """금융정보 병합작업 페이지. 전처리전(은행)·전처리후(신용카드)·카테고리 조회·금융정보 병합조회(은행+카드)·그래프. cash_after는 진입 시 삭제하지 않음."""
    # 좌측 카테고리 조회: category_table.json (분류, 키워드, 카테고리). 금융정보에서는 분류=심야구분/업종분류/위험도분류만 출력.
    CATEGORY_QUERY_분류_MYCASH = (CLASS_NIGHT, CLASS_INDUSTRY, CLASS_RISK)
    category_table_data = []
    try:
        df = load_category_table(CATEGORY_TABLE_PATH, default_empty=True)
        if df is not None and hasattr(df, 'to_dict'):
            if not df.empty and '분류' in df.columns:
                분류_col = df['분류'].fillna('').astype(str).str.strip()
                df = df[분류_col.isin(CATEGORY_QUERY_분류_MYCASH)].copy()
            if not df.empty:
                category_table_data = df.fillna('').to_dict('records')
            # empty DataFrame → []
        elif isinstance(df, list):
            category_table_data = [r for r in df if str(r.get('분류', '')).strip() in CATEGORY_QUERY_분류_MYCASH]
    except (ImportError, OSError, ValueError, TypeError):
        pass
    resp = make_response(render_template(
        'index.html',
        category_table_data=category_table_data,
        **get_template_constants('cash'),
    ))
    # 전처리 페이지 캐시 방지: 네비게이션 갱신이 바로 반영되도록
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['Expires'] = '0'
    return resp

@app.route('/favicon.ico')
def favicon():
    return '', 204

# ----- API: 전처리·업종분류 데이터 (bank_after, card_after, category-applied, risk-class) -----
@app.route('/api/clear-cache', methods=['POST'])
@ensure_working_directory
def clear_cache_cash():
    """선택한 캐시만 초기화. body: { \"after\": bool } (cash_after만 해당)."""
    try:
        data = request.get_json(force=True, silent=True) or {}
        clear_after = data.get('after', False)
        if clear_after:
            if _cash_after_cache_obj is not None:
                _cash_after_cache_obj.invalidate()
            p = Path(CASH_AFTER_PATH)
            try:
                if p.exists():
                    p.unlink()
            except OSError:
                pass
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/cache-info')
def get_cache_info():
    """캐시 이름·크기·총메모리 (금융정보 병합정보 헤더 표시용)."""
    try:
        caches = []
        total = 0
        if _cash_after_cache_obj is not None and _cash_after_cache_obj.current is not None:
            b = df_memory_bytes(_cash_after_cache_obj.current)
            total += b
            caches.append({'name': 'cash_after', 'size_bytes': b})
        for c in caches:
            c['size_human'] = format_bytes(c['size_bytes'])
        return jsonify({
            'app': 'MyCash',
            'caches': caches,
            'total_bytes': total,
            'total_human': format_bytes(total),
        })
    except Exception as e:
        # 캐시 정보 수집 중 예외 시 에러 필드 포함해 200 반환
        return jsonify({'app': 'MyCash', 'caches': [], 'total_bytes': 0, 'total_human': '0 B', 'error': str(e)})

@app.route('/api/bank-after-data')
@ensure_working_directory
def get_bank_after_data():
    """전처리전(은행거래): bank_after 로드."""
    try:
        df = load_bank_after_file()
        category_file_exists = Path(CASH_AFTER_PATH).exists()
        if df.empty:
            return jsonify({
                'message': 'bank_after가 없거나 비어 있습니다. 은행거래 전처리를 먼저 실행하세요.',
                'count': 0,
                'deposit_amount': 0,
                'withdraw_amount': 0,
                'data': [],
                'file_exists': category_file_exists
            }), 200
        bank_filter = (request.args.get('bank') or '').strip()
        date_filter = (request.args.get('date') or '').strip()
        account_filter = (request.args.get('account') or '').strip()
        if bank_filter and '은행명' in df.columns:
            allowed = set(BANK_FILTER_ALIASES.get(bank_filter, [bank_filter]))
            s = df['은행명'].fillna('').astype(str).str.strip()
            df = df[s.isin(allowed)].copy()
        if date_filter and '거래일' in df.columns:
            d = date_filter.replace('-', '').replace('/', '')
            if len(d) > 8:
                d = d[:8]
            s = df['거래일'].astype(str).str.replace(r'[\s\-/.]', '', regex=True)
            df = df[s.str.startswith(d, na=False)]
        if account_filter and '계좌번호' in df.columns:
            df = df[df['계좌번호'].fillna('').astype(str).str.strip() == account_filter]
        count = len(df)
        deposit_amount = df['입금액'].sum() if not df.empty else 0
        withdraw_amount = df['출금액'].sum() if not df.empty else 0
        df = df.where(pd.notna(df), None)
        data = df.to_dict('records')
        data = _json_safe(data)
        response = jsonify({
            'count': count,
            'deposit_amount': int(deposit_amount),
            'withdraw_amount': int(withdraw_amount),
            'data': data,
            'file_exists': category_file_exists
        })

        return response
    except Exception as e:
        return jsonify({
            'error': str(e),
            'count': 0,
            'deposit_amount': 0,
            'withdraw_amount': 0,
            'data': [],
            'file_exists': Path(CASH_AFTER_PATH).exists()
        }), 500

@app.route('/api/processed-data')
@ensure_working_directory
def get_processed_data():
    """전처리후(신용카드): card_after 로드."""
    try:
        df = load_card_after_file()
        category_file_exists = Path(CASH_AFTER_PATH).exists()
        if df.empty:
            return jsonify({
                'message': 'card_after가 없거나 비어 있습니다. 신용카드 전처리를 먼저 실행하세요.',
                'count': 0,
                'deposit_amount': 0,
                'withdraw_amount': 0,
                'data': [],
                'file_exists': category_file_exists
            }), 200
        bank_filter = (request.args.get('bank') or '').strip()
        date_filter = (request.args.get('date') or '').strip()
        account_filter = (request.args.get('account') or '').strip()
        if bank_filter and '카드사' in df.columns:
            df = df[df['카드사'].fillna('').astype(str).str.strip() == bank_filter]
        if date_filter and '이용일' in df.columns:
            d = date_filter.replace('-', '').replace('/', '')[:6]
            df = df[df['이용일'].astype(str).str.replace(r'[\s\-/.]', '', regex=True).str.startswith(d)]
        if account_filter and '카드번호' in df.columns:
            df = df[df['카드번호'].fillna('').astype(str).str.strip() == account_filter]
        total = len(df)
        deposit_amount = df['입금액'].sum() if not df.empty else 0
        withdraw_amount = df['출금액'].sum() if not df.empty else 0
        df = df.where(pd.notna(df), None)
        limit = request.args.get('limit', type=int)
        offset = request.args.get('offset', type=int) or 0
        if limit and limit > 0:
            df_slice = df.iloc[offset:offset + limit]
        else:
            df_slice = df.iloc[offset:]
        data = df_slice.to_dict('records')
        data = _json_safe(data)
        response = jsonify({
            'total': total,
            'count': len(data),
            'deposit_amount': int(deposit_amount),
            'withdraw_amount': int(withdraw_amount),
            'data': data,
            'file_exists': category_file_exists
        })

        return response
    except Exception as e:
        return jsonify({
            'error': str(e),
            'count': 0,
            'deposit_amount': 0,
            'withdraw_amount': 0,
            'data': [],
            'file_exists': Path(CASH_AFTER_PATH).exists()
        }), 500



@app.route('/api/simya-ranges')
@ensure_working_directory
def get_simya_ranges():
    """category_table.json에서 분류=심야구분인 행의 키워드(시작/종료) 반환. 거래시간 필터 '심야구분' 옵션용. 00:00:00은 클라이언트에서 제외."""
    try:
        df = load_category_table(CATEGORY_TABLE_PATH, default_empty=True)
        if df is None or df.empty or '분류' not in df.columns:
            return jsonify({'ranges': []})
        simya = df[df['분류'].fillna('').astype(str).str.strip() == CLASS_NIGHT].copy()
        ranges = []
        for _, row in simya.iterrows():
            kw = str(row.get('키워드', '') or '').strip()
            if not kw or '/' not in kw:
                continue
            parts = kw.split('/', 1)
            start_s, end_s = parts[0].strip(), parts[1].strip()
            start_sec = _time_to_seconds(start_s)
            end_sec = _time_to_seconds(end_s)
            if start_sec is not None and end_sec is not None:
                ranges.append({'start': start_s if ':' in start_s else f'{start_s[0:2]}:{start_s[2:4]}:{start_s[4:6]}', 'end': end_s if ':' in end_s else f'{end_s[0:2]}:{end_s[2:4]}:{end_s[4:6]}'})
        return jsonify({'ranges': ranges})
    except Exception as e:
        return jsonify({'ranges': [], 'error': str(e)})


@app.route('/api/category-applied-data')
@ensure_working_directory
def get_category_applied_data():
    """업종분류 적용된 데이터 반환 (필터링 지원). cash_after 존재하면 사용만, 없으면 생성하지 않음. 생성은 /api/generate-category(생성 필터)에서 백업 후 수행."""
    try:
        cash_after_path = Path(CASH_AFTER_PATH).resolve()
        category_file_exists = cash_after_path.exists() and cash_after_path.stat().st_size > 0
        
        try:
            df = load_category_file()
        except Exception as e:
            df = pd.DataFrame()
        
        if df.empty:
            response = jsonify({
                'count': 0,
                'deposit_amount': 0,
                'withdraw_amount': 0,
                'data': [],
                'file_exists': category_file_exists
            })
    
            return response
        
        df = _normalize_cash_columns(df)
        if '취소' not in df.columns:
            df['취소'] = ''
        # 취소 컬럼 정규화: nan/NaN/'nan' → '', '취소된 거래' 포함 시 '취소'로 통일 (화면 nan 표시·취소된 거래 미표시 방지)
        if '취소' in df.columns:
            df['취소'] = df['취소'].apply(lambda v: _safe_취소(v))
        if '사업자번호' not in df.columns and '사업자등록번호' in df.columns:
            df['사업자번호'] = df['사업자등록번호'].fillna('').astype(str)
        if '키워드' not in df.columns:
            df['키워드'] = ''
        # 폐업: 화면에는 '폐업' 또는 빈 값만 표시. 예전에 저장된 '은행거래'/'신용카드'는 표시 시 제거
        if '폐업' in df.columns:
            g = df['폐업'].fillna('').astype(str).str.strip()
            df = df.copy()
            df.loc[g.isin(('은행거래', '신용카드')), '폐업'] = ''
        
        bank_filter = (request.args.get('bank') or '').strip()
        date_filter = request.args.get('date', '')
        account_filter = (request.args.get('account') or '').strip()
        
        if bank_filter == '은행거래' and '출처' in df.columns:
            df = df[df['출처'].fillna('').astype(str).str.strip() == '은행거래']
        elif bank_filter == '신용카드' and '출처' in df.columns:
            df = df[df['출처'].fillna('').astype(str).str.strip() == '신용카드']
        elif bank_filter and '금융사' in df.columns:
            df = df[df['금융사'].fillna('').astype(str).str.strip() == bank_filter]
        if account_filter and '계좌번호' in df.columns:
            df = df[df['계좌번호'].fillna('').astype(str).str.strip() == account_filter]
        if date_filter and '거래일' in df.columns:
            try:
                d = date_filter.replace('-', '').replace('/', '')[:8]
                s = df['거래일'].astype(str).str.replace(r'[\s\-/.]', '', regex=True)
                df = df[s.str.startswith(d, na=False)]
            except (TypeError, ValueError, KeyError):
                pass  # 날짜 필터 실패 시 필터 없이 진행
        period = request.args.get('period', '').strip()
        df = _filter_df_by_period(df, period, '거래일')

        # 위험도 최소값 필터 (금융정보 종합분석: 위험도 0.1 이상만, min_risk 쿼리로 지정)
        exclude_daechae = request.args.get('exclude_daechae', '').strip()
        if exclude_daechae == '1' and '대체구분' in df.columns:
            df = df[df['대체구분'].fillna('').astype(str).str.strip() == '']

        min_risk = request.args.get('min_risk', '')
        if min_risk != '' and '위험도' in df.columns:
            try:
                threshold = float(min_risk)
                df = df[df['위험도'].fillna(0).astype(float) >= threshold]
            except (TypeError, ValueError):
                pass
        
        # 행 정렬: 거래일(내림) → 거래시간(내림) → 금융사(오름차순 가나다). 테이블·그래프 모두 동일 순서.
        try:
            df = df.copy()
            sort_cols = []
            ascending = []
            if '거래일' in df.columns:
                df['_sort_거래일'] = pd.to_datetime(df['거래일'], errors='coerce')
                sort_cols.append('_sort_거래일')
                ascending.append(False)
            if '거래시간' in df.columns:
                # HH:MM:SS 등 → 숫자만 6자리 문자열로 (빈값은 '000000') → 내림차순이면 늦은 시간이 먼저
                t = df['거래시간'].fillna('').astype(str).str.replace(r'[^\d]', '', regex=True)
                df['_sort_거래시간'] = t.apply(lambda s: s.ljust(6, '0') if len(s) < 6 else s[:6])
                sort_cols.append('_sort_거래시간')
                ascending.append(False)
            if '금융사' in df.columns:
                df['_sort_금융사'] = df['금융사'].fillna('').astype(str).str.strip()
                sort_cols.append('_sort_금융사')
                ascending.append(True)
            if sort_cols:
                df = df.sort_values(by=sort_cols, ascending=ascending, na_position='last')
            df = df.drop(columns=[c for c in ['_sort_거래일', '_sort_거래시간', '_sort_금융사'] if c in df.columns], errors='ignore')
        except Exception:
            df = df.drop(columns=[c for c in ['_sort_거래일', '_sort_거래시간', '_sort_금융사'] if c in df.columns], errors='ignore')
            pass  # 정렬 실패 시 원본 순서 유지
        # 업종분류 적용후 테이블 출력 (폐업, 위험도키워드, 위험도분류, 위험도 포함)
        for c in CATEGORY_APPLIED_DISPLAY_COLUMNS:
            if c not in df.columns:
                df[c] = '' if c not in ('입금액', '출금액') else 0
        df = df[CATEGORY_APPLIED_DISPLAY_COLUMNS].copy()
        # 집계: 전체 + (은행)/(카드) 구분 (병합후 상단합계용)
        total = len(df)
        deposit_amount = df['입금액'].sum() if not df.empty and '입금액' in df.columns else 0
        withdraw_amount = df['출금액'].sum() if not df.empty and '출금액' in df.columns else 0
        bank_count = card_count = 0
        bank_deposit_amount = bank_withdraw_amount = card_deposit_amount = card_withdraw_amount = 0
        if not df.empty and '출처' in df.columns:
            src = df['출처'].fillna('').astype(str).str.strip()
            bank_mask = src == '은행거래'
            card_mask = src == '신용카드'
            if bank_mask.sum() == 0 and card_mask.sum() == 0 and '금융사' in df.columns:
                gu = df['금융사'].fillna('').astype(str).str.strip()
                bank_mask = gu.isin(BANK_NAMES)
                card_mask = ~bank_mask & (gu != '')
            bank_count = int(bank_mask.sum())
            card_count = int(card_mask.sum())
            if bank_count:
                bank_deposit_amount = int(df.loc[bank_mask, '입금액'].sum() if '입금액' in df.columns else 0)
                bank_withdraw_amount = int(df.loc[bank_mask, '출금액'].sum() if '출금액' in df.columns else 0)
            if card_count:
                card_deposit_amount = int(df.loc[card_mask, '입금액'].sum() if '입금액' in df.columns else 0)
                card_withdraw_amount = int(df.loc[card_mask, '출금액'].sum() if '출금액' in df.columns else 0)
        # 선택: columns 파라미터로 필요한 컬럼만 반환 (페이로드 축소로 로딩 단축)
        cols_param = request.args.get('columns', '').strip()
        if cols_param:
            want = [c.strip() for c in cols_param.split(',') if c.strip() and c.strip() in df.columns]
            if want:
                df = df[want].copy()
        # 필수 컬럼 확인 (data에 입금/출금 포함 시)
        required_columns = ['입금액', '출금액']
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns and not df.empty:
            for col in missing_columns:
                df[col] = 0
        
        df = df.where(pd.notna(df), None)
        # 페이지네이션: limit/offset (limit 생략 또는 0이면 전체 반환)
        limit = request.args.get('limit', type=int)
        offset = request.args.get('offset', type=int) or 0
        if limit and limit > 0:
            df_slice = df.iloc[offset:offset + limit]
        else:
            df_slice = df.iloc[offset:]
        data = df_slice.to_dict('records')
        for rec, orig_idx in zip(data, df_slice.index):
            rec['_idx'] = int(orig_idx)
        data = _json_safe(data)
        response = jsonify({
            'total': total,
            'count': len(data),
            'deposit_amount': int(deposit_amount),
            'withdraw_amount': int(withdraw_amount),
            'bank_count': bank_count,
            'bank_deposit_amount': bank_deposit_amount,
            'bank_withdraw_amount': bank_withdraw_amount,
            'card_count': card_count,
            'card_deposit_amount': card_deposit_amount,
            'card_withdraw_amount': card_withdraw_amount,
            'data': data,
            'file_exists': category_file_exists
        })

        return response
    except Exception as e:
        category_file_exists = Path(CASH_AFTER_PATH).exists()
        return jsonify({
            'error': str(e),
            'count': 0,
            'deposit_amount': 0,
            'withdraw_amount': 0,
            'data': [],
            'file_exists': category_file_exists
        }), 500

# 카테고리 페이지 라우트
@app.route('/category')
def category():
    """카테고리 페이지"""
    return render_template('category.html', **get_template_constants('cash'))

# 카테고리: MyRisk/data/category_table.json 단일 테이블(구분 없음)
@app.route('/api/category')
@ensure_working_directory
def get_category_table():
    """category_table.json 전체 반환. 병합작업·업종분류 페이지 카테고리 조회 테이블(전체/입력/수정/삭제)용."""
    path = str(Path(CATEGORY_TABLE_PATH))
    try:
        df, file_existed = _io_get_category_table(path)
        if df is None or df.empty:
            data = []
        else:
            for c in CATEGORY_TABLE_EXTENDED_COLUMNS:
                if c not in df.columns:
                    df[c] = ''
            data = df[CATEGORY_TABLE_EXTENDED_COLUMNS].fillna('').to_dict('records')
            for r in data:
                r['위험지표'] = _to_str_no_decimal(r.get('위험지표'))
        response = jsonify({
            'data': data,
            'columns': CATEGORY_TABLE_EXTENDED_COLUMNS,
            'count': len(data),
            'file_exists': file_existed
        })

        return response
    except Exception as e:
        response = jsonify({
            'error': str(e),
            'data': [],
            'file_exists': Path(CATEGORY_TABLE_PATH).exists()
        })

        return response, 500

# table은 캐시를 사용하지 않는다. category_table 매 요청 시 파일에서 읽음.

@app.route('/api/risk-class-table')
@ensure_working_directory
def get_risk_class_table():
    """업종분류 조회용: category_table 기반 업종분류 데이터 반환. 캐시 없이 매 요청 시 읽음."""
    try:
        from lib.category_table_io import get_risk_class_table_data
        data = get_risk_class_table_data()
        response = jsonify({
            'data': data,
            'columns': ['업종분류', '위험도', '위험지표', '키워드'],
            'count': len(data),
        })

        return response
    except Exception as e:
        response = jsonify({
            'error': str(e),
            'data': [],
        })

        return response, 500

@app.route('/api/category', methods=['POST'])
@ensure_working_directory
def save_category_table():
    """category_table.json 전체 갱신 (구분 없음)"""
    path = str(Path(CATEGORY_TABLE_PATH))
    try:
        data = request.json or {}
        action = data.get('action', 'add')
        success, error_msg, count = apply_category_action(path, action, data)
        if not success:
            return jsonify({'success': False, 'error': error_msg}), 400
        xlsx_warn = None
        try:
            from lib.category_table_io import export_category_table_to_xlsx
            ok, _, err = export_category_table_to_xlsx(path)
            if not ok:
                xlsx_warn = err
                logger.warning("category_table → xlsx 내보내기 실패: %s", err)
        except Exception as _xe:
            xlsx_warn = str(_xe)
            logger.warning("category_table → xlsx 내보내기 예외: %s", _xe)
        try:
            from lib.path_config import delete_all_after_files
            delete_all_after_files()
        except Exception:
            pass
        msg = '카테고리 테이블이 업데이트되었습니다.'
        if xlsx_warn:
            msg += f' (xlsx 내보내기 실패: {xlsx_warn})'
        response = jsonify({
            'success': True,
            'message': msg,
            'count': count
        })

        return response
    except Exception as e:
        response = jsonify({
            'success': False,
            'error': str(e)
        })

        return response, 500

def _filter_df_by_period(df, period, date_col='거래일'):
    """기간(개월) 필터: period가 6,12,24,36,48이면 최근 N개월. 시작월 1일~종료월 말일(30/31일) 적용. 빈값/0이면 필터 없음."""
    if not period or str(period).strip() == '':
        return df
    try:
        n_months = int(period)
        if n_months <= 0:
            return df
    except (TypeError, ValueError):
        return df
    if df.empty or date_col not in df.columns:
        return df
    try:
        df = df.copy()
        df['_dt'] = pd.to_datetime(df[date_col], errors='coerce')
        df = df[df['_dt'].notna()]
        if df.empty:
            return df
        max_date = df['_dt'].max()
        from pandas.tseries.offsets import DateOffset
        from calendar import monthrange
        # 시작월 1일, 종료월 마지막 날(30 또는 31일)
        start_date = (max_date - DateOffset(months=n_months)).replace(day=1)
        _, last_day = monthrange(max_date.year, max_date.month)
        end_date = max_date.replace(day=last_day)
        df = df.loc[(df['_dt'] >= start_date) & (df['_dt'] <= end_date)].drop(columns=['_dt'])
    except Exception:
        df = df.drop(columns=['_dt'], errors='ignore')
    return df


# 분석 페이지 라우트
# ----- 페이지: 금융정보 종합분석·인쇄 -----
@app.route('/analysis/basic')
def analysis_basic():
    """기본 기능 분석 페이지"""
    return render_template('analysis_basic.html')

@app.route('/analysis/print')
@ensure_working_directory
def print_analysis():
    """금융정보 종합분석 인쇄용 페이지 (출력일, 금융사/전체, 전체 합계, 위험도 테이블, 세부내역 테이블, 위험도 원그래프, 종합의견)."""
    try:
        bank_filter = (request.args.get('bank') or '').strip()
        df = load_category_file()
        if df.empty:
            return "데이터가 없습니다. cash_after를 생성한 뒤 다시 시도하세요.", 400

        # 컬럼 정규화 (get_category_applied_data와 동일)
        df = _normalize_cash_columns(df)

        if bank_filter == '은행거래' and '출처' in df.columns:
            df = df[df['출처'].fillna('').astype(str).str.strip() == '은행거래']
        elif bank_filter == '신용카드' and '출처' in df.columns:
            df = df[df['출처'].fillna('').astype(str).str.strip() == '신용카드']
        elif bank_filter and '금융사' in df.columns:
            df = df[df['금융사'].fillna('').astype(str).str.strip() == bank_filter]
        period = (request.args.get('period') or '').strip()
        df = _filter_df_by_period(df, period, '거래일')

        # 위험도 0.1 이상만 (종합분석과 동일)
        if '위험도' in df.columns:
            try:
                risk = df['위험도'].fillna(0).astype(float)
                df = df.loc[risk >= 0.1]
            except (TypeError, ValueError):
                pass

        total_count = len(df)
        total_deposit = int(df['입금액'].sum()) if not df.empty and '입금액' in df.columns else 0
        total_withdraw = int(df['출금액'].sum()) if not df.empty and '출금액' in df.columns else 0
        # 출처(은행거래/신용카드) 컬럼 기준 집계. 없으면 금융사 이름으로 은행/카드 구분
        if not df.empty and '출처' in df.columns:
            src_trim = df['출처'].fillna('').astype(str).str.strip()
            bank_mask = src_trim == '은행거래'
            card_mask = src_trim == '신용카드'
            print_bank_count = int(bank_mask.sum())
            print_card_count = int(card_mask.sum())
            print_bank_withdraw = int(df.loc[bank_mask, '출금액'].sum()) if '출금액' in df.columns else 0
            print_card_withdraw = int(df.loc[card_mask, '출금액'].sum()) if '출금액' in df.columns else 0
        else:
            print_bank_count = print_card_count = 0
            print_bank_withdraw = print_card_withdraw = 0
        if (print_bank_count == 0 and print_card_count == 0) and not df.empty and total_count > 0 and '금융사' in df.columns:
            gu = df['금융사'].fillna('').astype(str).str.strip()
            print_bank_count = int(gu.isin(BANK_NAMES).sum())
            print_card_count = total_count - print_bank_count
            print_bank_withdraw = int(df.loc[gu.isin(BANK_NAMES), '출금액'].sum()) if '출금액' in df.columns else 0
            print_card_withdraw = total_withdraw - print_bank_withdraw

        # 대체거래 제외 후 위험도분류별 집계 (1호~10호)
        df_full = df.copy()
        df_for_risk = df.copy()
        print_daechae_excluded = 0
        if '대체구분' in df_for_risk.columns:
            _dc_print = df_for_risk['대체구분'].fillna('').astype(str).str.strip()
            print_daechae_excluded = int((_dc_print != '').sum())
            df_for_risk = df_for_risk[_dc_print == '']
        risk_classification_rows, _tspan = _build_risk_classification_rows_from_df(df_for_risk)
        RISK_ORDER_PRINT = ['분류제외지표', '심야폐업지표', '자료소명지표', '비정형지표', '투기성지표', '사기파산지표', '가상자산지표', '자산은닉지표', '과소비지표', '사행성지표']
        RISK_DISPLAY_PRINT = ['1호(업종분류제외)', '2호(심야폐업지표)', '3호(자료소명지표)', '4호(비정형지표)', '5호(투기성지표)', '6호(사기파산지표)', '7호(가상자산지표)', '8호(자산은닉지표)', '9호(과소비지표)', '10호(사행성지표)']

        # 세부내역: 대체거래 제외 데이터 기준, 위험도 내림 → 거래일 내림, 인쇄용 8행
        risk_detail_rows = []
        risk_detail_total_count = 0
        risk_detail_deposit_sum = 0
        risk_detail_withdraw_sum = 0
        df = df_for_risk
        if not df.empty:
            for c in ['금융사', '거래일', '기타거래', '입금액', '출금액']:
                if c not in df.columns:
                    df[c] = 0 if c in ('입금액', '출금액') else ''
            if '위험도분류' not in df.columns:
                df['위험도분류'] = ''
            try:
                df_sorted = df.sort_values(
                    by=['위험도', '거래일'] if '거래일' in df.columns else ['위험도'],
                    ascending=[False, False],
                    na_position='last'
                )
            except Exception as e:
                df_sorted = df
            risk_detail_total_count = len(df_sorted)
            risk_detail_deposit_sum = int(df_sorted['입금액'].sum()) if '입금액' in df_sorted.columns else 0
            risk_detail_withdraw_sum = int(df_sorted['출금액'].sum()) if '출금액' in df_sorted.columns else 0
            df_slice = df_sorted.head(8)
            for _, row in df_slice.iterrows():
                raw_cls = str(row.get('위험도분류', '')).strip() or '분류제외지표'
                try:
                    idx = RISK_ORDER_PRINT.index(raw_cls)
                    cls_display = RISK_DISPLAY_PRINT[idx]
                except ValueError:
                    cls_display = raw_cls
                risk_detail_rows.append({
                    '금융사': str(row.get('금융사', '')),
                    '거래일': str(row.get('거래일', '')),
                    '기타거래': str(row.get('기타거래', '')),
                    '위험도분류_display': cls_display,
                    '출금액': int(row.get('출금액', 0) or 0)
                })

        # 원그래프용: 1호~10호 고정 순서, 각 호 출금액(0원이면 0%로 행 출력), 범례 행: 위험도분류, %, 합계금액
        pie_total = sum(r['withdraw'] for r in risk_classification_rows)
        colors = ['#1976d2', '#2e7d32', '#ed6c02', '#c62828', '#6a1b9a', '#00838f', '#558b2f', '#ad1457', '#283593', '#1565c0']
        cx, cy, r = 100, 100, 80
        risk_pie_slices = []
        cum = 0
        for i, row in enumerate(risk_classification_rows):
            value = int(row.get('withdraw', 0) or 0)
            pct = (value / pie_total * 100) if pie_total and pie_total > 0 else 0.0
            a1 = cum * 3.6 - 90
            a2 = (cum + pct) * 3.6 - 90
            cum += pct
            rad1, rad2 = math.radians(a1), math.radians(a2)
            x1 = cx + r * math.cos(rad1)
            y1 = cy + r * math.sin(rad1)
            x2 = cx + r * math.cos(rad2)
            y2 = cy + r * math.sin(rad2)
            large = 1 if pct > 50 else 0
            try:
                path_d = 'M %g %g L %g %g A %g %g 0 %d 1 %g %g Z' % (float(cx), float(cy), float(x1), float(y1), float(r), float(r), int(large), float(x2), float(y2))
            except (TypeError, ValueError):
                path_d = ''
            risk_pie_slices.append({
                'path_d': path_d,
                'color': colors[i % len(colors)],
                'label': row['classification'],
                'value': value,
                'pct': round(float(pct), 1)
            })

        # 리포트 작성: 대체거래 제외 기준 R 산출
        current_status = [
            {"id": "%d호" % (i + 1), "count": r["count"], "amount": r["withdraw"], "deposit": r.get("deposit", 0), "dates": r.get("dates", [])}
            for i, r in enumerate(risk_classification_rows)
        ]
        risk_guidelines_py = "risk_guidelines = " + _format_risk_guidelines_py(RISK_GUIDELINES_FIXED)
        current_status_py = "current_status = " + _format_current_status_py(current_status)
        risk_report = _calculate_risk_report(RISK_GUIDELINES_FIXED, current_status, _tspan)
        # 전체(대체거래 포함) R도 참고용으로 산출
        risk_full_report = None
        if print_daechae_excluded > 0:
            rows_full, _tspan_full = _build_risk_classification_rows_from_df(df_full)
            status_full = [{"id": "%d호" % (i + 1), "count": r["count"], "amount": r["withdraw"], "deposit": r.get("deposit", 0), "dates": r.get("dates", [])} for i, r in enumerate(rows_full)]
            risk_full_report = _calculate_risk_report(RISK_GUIDELINES_FIXED, status_full, _tspan_full)

        opinion_ctx = _get_opinion_context(bank_filter=bank_filter or None, period=period or None)
        # 인쇄용은 현재 필터/집계값(print_* 등)만 사용. 단일 dict로 합쳐 중복 키 오류 방지
        template_ctx = dict(opinion_ctx)
        for k in ('total_count', 'bank_count', 'bank_withdraw', 'card_count', 'card_withdraw', 'risk_classification_rows'):
            template_ctx.pop(k, None)
        # 카테고리 파일: 분류 "신청인", 키워드 "이메일/연락처", 카테고리 "신청인(이름)" → 우선 사용
        applicant_name = (request.args.get('applicant_name') or request.args.get('applicant') or '').strip()
        contact = (request.args.get('contact') or request.args.get('phone') or '').strip()
        email = (request.args.get('email') or '').strip()
        try:
            df_cat = load_category_table(CATEGORY_TABLE_PATH, default_empty=True)
            if df_cat is not None and not df_cat.empty and '분류' in df_cat.columns:
                신청인_rows = df_cat[df_cat['분류'].fillna('').astype(str).str.strip() == CLASS_APPLICANT]
                if not 신청인_rows.empty:
                    r = 신청인_rows.iloc[0]
                    if not applicant_name and '카테고리' in r:
                        applicant_name = str(r['카테고리']).strip() if pd.notna(r['카테고리']) else ''
                    kw = str(r.get('키워드', '')).strip() if pd.notna(r.get('키워드')) else ''
                    if kw and ('@' in kw or '/' in kw):
                        parts = [p.strip() for p in kw.split('/') if p.strip()]
                        for p in parts:
                            if '@' in p and not email:
                                email = p
                            elif not contact and (p.replace('-', '').replace(' ', '').isdigit() or len(p) >= 9):
                                contact = p
        except Exception:
            pass
        template_ctx.update({
            'report_date': datetime.now().strftime('%Y-%m-%d'),
            'bank_filter': bank_filter or '전체',
            'applicant_name': applicant_name,
            'contact': contact,
            'email': email,
            'total_count': total_count,
            'total_deposit': total_deposit,
            'total_withdraw': total_withdraw,
            'bank_count': print_bank_count,
            'bank_withdraw': print_bank_withdraw,
            'card_count': print_card_count,
            'card_withdraw': print_card_withdraw,
            'risk_classification_rows': risk_classification_rows,
            'risk_detail_rows': risk_detail_rows,
            'risk_detail_total_count': risk_detail_total_count,
            'risk_detail_deposit_sum': risk_detail_deposit_sum,
            'risk_detail_withdraw_sum': risk_detail_withdraw_sum,
            'risk_pie_slices': risk_pie_slices,
            'risk_guidelines_py': risk_guidelines_py,
            'current_status_py': current_status_py,
            'risk_report': risk_report,
            'risk_full_report': risk_full_report,
            'daechae_excluded_count': print_daechae_excluded,
            'risk_total_count': len(df_for_risk),
            'risk_total_deposit': int(df_for_risk['입금액'].sum()) if '입금액' in df_for_risk.columns else 0,
            'risk_total_withdraw': int(df_for_risk['출금액'].sum()) if '출금액' in df_for_risk.columns else 0,
        })

        major_summary = []
        try:
            ct_df = load_category_table(CATEGORY_TABLE_PATH, default_empty=True)
            if ct_df is not None and not ct_df.empty and '분류' in ct_df.columns:
                acct_ct = ct_df[ct_df['분류'] == '계정과목']
                if not acct_ct.empty and '카테고리' in acct_ct.columns:
                    major_map = {}
                    risk_col = '위험도' if '위험도' in acct_ct.columns else None
                    for _, r in acct_ct.iterrows():
                        cat = str(r.get('카테고리', '')).strip()
                        maj = str(r.get(risk_col, '')) if risk_col else ''
                        if cat and cat not in major_map:
                            major_map[cat] = maj
                    if major_map and '카테고리' in df_for_risk.columns:
                        df_for_risk_tmp = df_for_risk.copy()
                        df_for_risk_tmp['_대분류'] = df_for_risk_tmp['카테고리'].map(major_map).fillna('Ⅶ. 미분류')
                        ms = df_for_risk_tmp.groupby('_대분류').agg({'입금액': 'sum', '출금액': 'sum'}).reset_index()
                        ms = ms.rename(columns={'_대분류': '대분류'})
                        ms['건수'] = df_for_risk_tmp.groupby('_대분류').size().values
                        roman_order = {'Ⅰ': 1, 'Ⅱ': 2, 'Ⅲ': 3, 'Ⅳ': 4, 'Ⅴ': 5, 'Ⅵ': 6, 'Ⅶ': 7}
                        ms['_sort'] = ms['대분류'].apply(lambda x: roman_order.get(x[0] if x else '', 99))
                        ms = ms.sort_values('_sort').drop(columns=['_sort'])
                        major_summary = ms.to_dict('records')
        except Exception:
            pass
        template_ctx['major_summary'] = major_summary

        return render_template('print_analysis.html', **template_ctx)
    except Exception as e:
        return "오류 발생: " + str(e), 500

# 금융정보 위험도 분석 리포트용 가이드라인 (1~10호). 프롬프트·산출 공통.
RISK_GUIDELINES_FIXED = {
    "1호": {"name": "분류제외지표", "weight": 0.1, "threshold": 1000000},
    "2호": {"name": "심야폐업지표", "weight": 0.5, "threshold": 0},
    "3호": {"name": "자료소명지표", "weight": 1.0, "threshold": 1000000},
    "4호": {"name": "비정형지표", "weight": 1.5, "threshold": 500000},
    "5호": {"name": "투기성지표", "weight": 2.0, "threshold": 500000},
    "6호": {"name": "사기파산지표", "weight": 2.5, "threshold": 500000},
    "7호": {"name": "가상자산지표", "weight": 3.0, "threshold": 500000},
    "8호": {"name": "자산은닉지표", "weight": 3.5, "threshold": 500000},
    "9호": {"name": "과소비지표", "weight": 4.0, "threshold": 500000},
    "10호": {"name": "사행성지표", "weight": 5.0, "threshold": 100000},
}

# 항목별 특화 소명 전략 (일률적 문구 대신 항목 성격에 맞는 구체적 소명 가이드)
SUGGESTION_TEMPLATES = {
    "분류제외지표": "일상적 생활비 지출로서 특별한 소명이 불필요하나, 금액이 큰 건에 대해서는 용도를 간략히 기재",
    "심야폐업지표": "심야 거래의 불가피한 사유(교대근무·긴급 의료 등) 또는 폐업 사업자 거래의 경위(기존 거래처 잔여 결제 등) 소명",
    "자료소명지표": "고액 출금의 구체적 용도(생활비·의료비·교육비 등) 및 자금 흐름 증빙(영수증·계약서) 제시",
    "비정형지표": "반복 출금의 합리적 사유(정기 납부금·할부금 등), 입금 없이 출금만 발생한 경위 소명",
    "투기성지표": "투자 목적·손실 규모·생계자금과의 구분 소명, 투자 원금 출처 및 현재 보유 자산 현황 제시",
    "사기파산지표": "대부업·P2P 거래의 불가피성(기존 채무 상환 등), 카드깡 의혹 해소를 위한 실거래 증빙 제시",
    "가상자산지표": "거래소 계좌 출금 경위, 투자 원금 규모, 현재 보유 여부, 매도 대금 사용처 소명",
    "자산은닉지표": "해외 송금 목적(유학비·가족 부양 등), 수취인과의 관계, 송금 내역서 제출로 자산은닉 아님을 소명",
    "과소비지표": "생활 필수품/비필수 구분, 가계 구성원 공동 사용 여부, 구매 시점 이후 재발 방지 노력 소명",
    "사행성지표": "발생 빈도·금액 규모 인정, 중독 치료 이력 또는 재발 방지 대책(자기 배제 등) 구체적 소명",
}

# 면책 불허가 사유 매핑 (채무자 회생 및 파산에 관한 법률 제564조)
LEGAL_REFERENCES = {
    "분류제외지표": "",
    "심야폐업지표": "",
    "자료소명지표": "제564조 제3호(허위 재산목록 제출 의심 시 소명 대상)",
    "비정형지표": "제564조 제3호(불성실 재산 보고 의심 시 소명 대상)",
    "투기성지표": "제564조 제1호(재산 감소의 주된 원인이 투기인 경우 면책 불허가 사유)",
    "사기파산지표": "제564조 제2호(허위 채권자목록 제출), 제6호(사기파산 유죄 확정 시 면책 불허가)",
    "가상자산지표": "제564조 제1호(투기로 인한 재산 감소 시 면책 불허가 사유에 해당 가능)",
    "자산은닉지표": "제564조 제4호(면책 신청 전 1년 이내 재산 은닉·손괴 시 면책 불허가)",
    "과소비지표": "제564조 제1호(낭비로 인한 재산 감소 시 면책 불허가 사유)",
    "사행성지표": "제564조 제1호(도박 등 사행행위로 인한 재산 감소 시 면책 불허가 사유)",
}

def _get_risk_grade(score):
    """점수 기준 위험등급 반환. 50 미만 안전, 50~100 보통, 100~150 주의, 150 이상 심각."""
    if score >= 150:
        return "심각"
    elif score >= 100:
        return "주의"
    elif score >= 50:
        return "보통"
    else:
        return "안전"


def _get_risk_grade_item(score):
    """1. 위험도 분석 결과 테이블용 항목별 위험등급. 10 미만 안전, 10~20 보통, 20~30 주의, 30 이상 심각. 텍스트로 반환."""
    if score >= 30:
        return "심각 (Critical)"
    elif score >= 20:
        return "주의 (Caution)"
    elif score >= 10:
        return "보통 (Normal)"
    else:
        return "안전 (Safe)"

def _compute_temporal_proximity(dates, total_span_days, alpha=0.3, beta=0.2):
    """시계열 근접성 계수 T.
    거래일이 좁은 기간에 집중되거나 분석 기간 후반부에 몰릴수록 T > 1.0.
    T = 1 + α×C(집중도) + β×P(최근성).  범위: 1.00 ~ 1.50.
    dates: list[datetime], total_span_days: 전체 분석 기간(일).
    """
    if len(dates) < 2 or total_span_days <= 0:
        return 1.0
    sorted_d = sorted(dates)
    active_span = (sorted_d[-1] - sorted_d[0]).days
    C = max(0.0, min(1.0, 1.0 - active_span / total_span_days))
    cutoff = sorted_d[-1] - timedelta(days=max(1, int(total_span_days * 0.25)))
    recent_count = sum(1 for d in sorted_d if d >= cutoff)
    P = recent_count / len(dates)
    T = 1.0 + alpha * C + beta * P
    return round(min(T, 1.5), 3)


def _compute_symmetry_factor(deposit, withdraw):
    """입출금 대칭성 계수(S) 산출.
    S = 1 − (입금 / 출금). 출금 대비 입금(회수) 비율이 높을수록 S가 낮아져 R을 감소시킨다.
    - S = 0.0: 입금 = 출금 (완전 회수, 위험 최저)
    - S = 1.0: 입금 = 0 (전액 유출, 위험 최고) → R 변동 없음
    - 5호(투기성)·7호(가상자산)·8호(자산은닉) 등 입금 회수가 의미 있는 지표에만 적용.
    Returns: S (0.3 ~ 1.0). 하한 0.3은 완전 회수 시에도 최소 위험도를 유지."""
    if withdraw <= 0:
        return 1.0
    if deposit <= 0:
        return 1.0
    ratio = deposit / withdraw
    s = 1.0 - ratio
    return round(max(s, 0.3), 4)


# S 계수를 적용할 위험도 지표 (입금 회수가 의미 있는 지표만)
SYMMETRY_APPLICABLE = {'투기성지표', '가상자산지표', '자산은닉지표'}


def _compute_threshold_factor(a_total, f, threshold, gamma=0.1, delta=0.05, count_threshold=10):
    """동적 임계 계수(Θ) 산출.
    - 금액 미달: 선형 감점 (a_total / threshold)
    - 금액 기본 구간 (threshold ~ threshold×3): 1.0
    - 금액 초과 (>threshold×3): 누진 가중 1 + γ × log₂(a_total/threshold), 상한 2.0
    - 건수 가중: f >= count_threshold 이면 추가 가중, 상한 1.3
    Returns: Θ (0.0 ~ 2.6)"""
    if threshold <= 0:
        return 1.0
    # 금액 기반 factor
    if a_total <= 0:
        return 0.0
    if a_total < threshold:
        amount_factor = a_total / threshold
    elif a_total <= threshold * 3:
        amount_factor = 1.0
    else:
        amount_factor = 1.0 + gamma * math.log2(a_total / threshold)
        amount_factor = min(amount_factor, 2.0)
    # 건수 기반 factor
    if f >= count_threshold:
        count_factor = 1.0 + delta * (f / count_threshold - 1)
        count_factor = min(count_factor, 1.3)
    else:
        count_factor = 1.0
    return round(amount_factor * count_factor, 4)


def _calculate_risk_report(guidelines, current_status, total_span_days=0):
    """R = w × log₁₀(1 + f × avg_a) × T × Θ × S.
    T: 시계열 근접성 계수, Θ: 동적 임계 계수, S: 입출금 대칭성 계수.
    total_span_days: 전체 분석 기간(일). T 산출에 사용."""
    results = []
    total_r = 0.0
    total_count = 0
    total_amount_raw = 0
    for item in current_status:
        ref = guidelines.get(item["id"], {"name": item["id"], "weight": 0.1, "threshold": 0})
        w = ref["weight"]
        f = item["count"]
        a_total = int(item["amount"]) if item["amount"] is not None else 0
        deposit = int(item.get("deposit", 0) or 0)
        avg_a = a_total / f if f > 0 else 0
        threshold = ref.get("threshold", 0)
        dates = item.get("dates", [])
        T = _compute_temporal_proximity(dates, total_span_days) if dates and total_span_days > 0 else 1.0
        Theta = _compute_threshold_factor(a_total, f, threshold)
        name = ref["name"]
        S = _compute_symmetry_factor(deposit, a_total) if name in SYMMETRY_APPLICABLE else 1.0
        base_score = w * math.log10(1 + (f * avg_a)) if (f * avg_a) >= 0 else 0
        risk_score = base_score * T * Theta * S
        total_r += risk_score
        total_count += f
        total_amount_raw += a_total
        row_score = round(risk_score, 2)
        results.append({
            "항목": name,
            "가중치": w,
            "건수": f,
            "금액": "{:,}원".format(a_total),
            "T": T,
            "Θ": Theta,
            "S": S,
            "점수": row_score,
            "종합R": row_score,
            "위험등급": _get_risk_grade_item(row_score),
            "법조항": LEGAL_REFERENCES.get(name, ""),
        })
    total_score = round(total_r, 2)
    if total_score >= 150:
        grade_label, grade_desc = "심각 (Critical)", "상세 사유서 필수 작성."
    elif total_score >= 100:
        grade_label, grade_desc = "주의 (Caution)", "소명 자료 준비 필수. 과소비·사행성 의심 항목에 대한 소명 필요."
    elif total_score >= 50:
        grade_label, grade_desc = "보통 (Normal)", "일부 특이 지출 소명 필요. 한도 초과 항목만 선별적 소명."
    else:
        grade_label, grade_desc = "안전 (Safe)", "면책 허가 가능성 높음. 자동 생성 보고서로 충분."
    sorted_results = sorted(results, key=lambda x: x["점수"], reverse=True)
    suggestion_items = []
    for r in sorted_results[:5]:
        if r["점수"] <= 0:
            continue
        name = r["항목"]
        suggestion_items.append({
            "항목": name,
            "점수": r["점수"],
            "소명전략": SUGGESTION_TEMPLATES.get(name, "해당 항목 지출 내역 및 사유 소명"),
            "법조항": LEGAL_REFERENCES.get(name, ""),
            "소명서초안": _generate_draft_explanation(name, r["건수"], r["금액"]),
        })
    checklist_default = [
        "금융거래내역서(은행·카드사 발급)",
        "위험도 항목별 지출 용도 설명서",
        "소명서(법원 제출용, 항목별 소명 전략 참고)",
        "필요 시 추가 증빙(영수증·계약서 등)",
        "재발 방지 서약서(사행성·과소비 해당 시)",
    ]
    return {
        "analysis_data": results,
        "total_score": total_score,
        "total_count": total_count,
        "total_amount": "{:,}원".format(total_amount_raw),
        "grade_label": grade_label,
        "grade_desc": grade_desc,
        "suggestion_items": suggestion_items,
        "checklist_items": checklist_default,
    }


def _generate_draft_explanation(item_name, count, amount_str):
    """항목별 소명서 초안 문구 자동 생성."""
    templates = {
        "투기성지표": "위 거래는 {amount} 규모의 투자 관련 거래 {count}건으로, 생계 자금과 구분되는 여유 자금으로 이루어진 것입니다. 현재 해당 투자는 중단하였으며, 향후 투기적 거래를 자제할 것을 서약합니다.",
        "사기파산지표": "위 거래 {count}건({amount})은 기존 채무 상환을 위해 불가피하게 발생한 것으로, 사기적 의도는 없었습니다. 해당 거래의 상대방 및 거래 경위를 증빙 자료로 첨부합니다.",
        "가상자산지표": "위 가상자산 관련 거래 {count}건({amount})은 투자 목적이었으며, 현재 보유 자산은 없습니다(또는 잔여 보유분은 재산목록에 신고하였습니다). 향후 가상자산 거래를 중단할 것을 서약합니다.",
        "자산은닉지표": "위 해외 송금 등 {count}건({amount})은 가족 부양비(또는 유학 경비 등) 목적으로, 자산 은닉의 의도는 없었습니다. 송금 내역서 및 수취인 관계 증빙을 첨부합니다.",
        "과소비지표": "위 지출 {count}건({amount})은 가계 운영상 발생한 것으로, 일부 불필요한 지출이 포함되어 있음을 인정합니다. 파산 신청 이후 해당 유형의 지출을 중단하였으며, 재발 방지 계획을 첨부합니다.",
        "사행성지표": "위 거래 {count}건({amount})은 일시적으로 발생한 것으로, 현재는 해당 행위를 완전히 중단하였습니다. 자기 배제 프로그램 등록 등 재발 방지 조치를 취하였으며, 관련 증빙을 첨부합니다.",
        "심야폐업지표": "위 심야·폐업 관련 거래 {count}건({amount})은 교대 근무(또는 긴급 상황) 등으로 인해 발생한 것이며, 의도적 비정상 거래가 아닙니다.",
        "자료소명지표": "위 고액 출금 {count}건({amount})은 생활비·의료비·교육비 등 필수 지출 목적이었으며, 관련 영수증 및 계약서를 증빙으로 첨부합니다.",
        "비정형지표": "위 반복 출금 {count}건({amount})은 정기 납부금(보험료·할부금 등) 성격의 거래이며, 비정상적 자금 유출이 아닙니다.",
    }
    tmpl = templates.get(item_name, "위 거래 {count}건({amount})에 대해 구체적 용도 및 사유를 소명합니다.")
    return tmpl.format(count=count, amount=amount_str)

def _get_opinion_context(bank_filter=None, period=None, **_kw):
    """cash_after(은행+카드 병합)에서 종합의견용 통계 생성. 출처 컬럼으로 은행/카드 구분."""
    def _fmt(n):
        return '{:,}'.format(int(n)) if n is not None else '0'
    ctx = {
        'bank_count': 0, 'bank_deposit': 0, 'bank_withdraw': 0, 'bank_net': 0,
        'card_count': 0, 'card_deposit': 0, 'card_withdraw': 0, 'card_net': 0,
        'total_count': 0, 'bank_by_name': [], 'card_by_name': [], 'bank_top_categories': [], 'card_top_categories': [],
        'bank_deposit_fmt': '0', 'bank_withdraw_fmt': '0', 'bank_net_fmt': '0',
        'card_deposit_fmt': '0', 'card_withdraw_fmt': '0', 'card_net_fmt': '0',
        'card_ratio': '',
        'review_start_date': '', 'review_end_date': '',
        'filter_institution': '',
    }
    try:
        df_all = load_category_file()
        if df_all is None or df_all.empty:
            return ctx
        if '출처' not in df_all.columns:
            df_all['출처'] = ''
        if bank_filter:
            if bank_filter == '은행거래' and '출처' in df_all.columns:
                df_all = df_all[df_all['출처'].fillna('').astype(str).str.strip() == '은행거래']
                ctx['filter_institution'] = bank_filter
            elif bank_filter == '신용카드' and '출처' in df_all.columns:
                df_all = df_all[df_all['출처'].fillna('').astype(str).str.strip() == '신용카드']
                ctx['filter_institution'] = bank_filter
            else:
                if '금융사' not in df_all.columns:
                    if '은행명' in df_all.columns:
                        df_all['금융사'] = df_all['은행명'].fillna('')
                    elif '카드사' in df_all.columns:
                        df_all['금융사'] = df_all['카드사'].fillna('')
                if '금융사' in df_all.columns:
                    df_all = df_all[df_all['금융사'].fillna('').astype(str).str.strip() == bank_filter]
                    ctx['filter_institution'] = bank_filter
            if df_all.empty:
                return ctx
        df_bank = df_all[df_all['출처'].fillna('').astype(str).str.strip() == '은행거래'].copy()
        df_card = df_all[df_all['출처'].fillna('').astype(str).str.strip() == '신용카드'].copy()
        if period and str(period).strip():
            try:
                n_months = int(period)
                if n_months > 0:
                    from pandas.tseries.offsets import DateOffset
                    from calendar import monthrange
                    max_date = None
                    if not df_all.empty and '거래일' in df_all.columns:
                        d = pd.to_datetime(df_all['거래일'], errors='coerce')
                        d = d[d.notna()]
                        if not d.empty:
                            max_date = d.max()
                    if max_date is None:
                        max_date = pd.Timestamp.now()
                    start_date = (max_date - DateOffset(months=n_months)).replace(day=1)
                    _, last_day = monthrange(max_date.year, max_date.month)
                    end_date = max_date.replace(day=last_day)
                    ctx['review_start_date'] = start_date.strftime('%Y-%m-%d')
                    ctx['review_end_date'] = end_date.strftime('%Y-%m-%d')
                    df_all = _filter_df_by_period(df_all, period, '거래일')
                    df_bank = _filter_df_by_period(df_bank, period, '거래일')
                    df_card = _filter_df_by_period(df_card, period, '거래일')
            except (TypeError, ValueError):
                pass
        # 대체거래 분석 (항상 전체 데이터 기준)
        try:
            _add_substitute_transaction_analysis(ctx, df_all.copy())
        except Exception:
            pass
        # 대체거래가 있으면 은행/카드별 실질(제외) 금액도 계산
        _has_daechae = ctx.get('daechae_total_count', 0) > 0
        if _has_daechae and '대체구분' in df_all.columns:
            _dc = df_all['대체구분'].fillna('').astype(str).str.strip()
            df_bank_net = df_bank[~df_bank.index.isin(df_all[_dc != ''].index)]
            df_card_net = df_card[~df_card.index.isin(df_all[_dc != ''].index)]
            ctx['bank_net_count'] = len(df_bank_net)
            ctx['bank_net_deposit_val'] = int(df_bank_net['입금액'].sum()) if '입금액' in df_bank_net.columns else 0
            ctx['bank_net_withdraw_val'] = int(df_bank_net['출금액'].sum()) if '출금액' in df_bank_net.columns else 0
            ctx['bank_net_deposit_fmt2'] = _fmt(ctx['bank_net_deposit_val'])
            ctx['bank_net_withdraw_fmt2'] = _fmt(ctx['bank_net_withdraw_val'])
            ctx['bank_net_balance_fmt'] = _fmt(ctx['bank_net_deposit_val'] - ctx['bank_net_withdraw_val'])
            ctx['card_net_count'] = len(df_card_net)
            ctx['card_net_deposit_val'] = int(df_card_net['입금액'].sum()) if '입금액' in df_card_net.columns else 0
            ctx['card_net_withdraw_val'] = int(df_card_net['출금액'].sum()) if '출금액' in df_card_net.columns else 0
            ctx['card_net_deposit_fmt2'] = _fmt(ctx['card_net_deposit_val'])
            ctx['card_net_withdraw_fmt2'] = _fmt(ctx['card_net_withdraw_val'])
            ctx['card_net_balance_fmt'] = _fmt(ctx['card_net_deposit_val'] - ctx['card_net_withdraw_val'])
        if not df_bank.empty:
            ctx['bank_count'] = len(df_bank)
            ctx['bank_deposit'] = int(df_bank['입금액'].sum()) if '입금액' in df_bank.columns else 0
            ctx['bank_withdraw'] = int(df_bank['출금액'].sum()) if '출금액' in df_bank.columns else 0
            ctx['bank_net'] = ctx['bank_deposit'] - ctx['bank_withdraw']
            ctx['bank_deposit_fmt'] = _fmt(ctx['bank_deposit'])
            ctx['bank_withdraw_fmt'] = _fmt(ctx['bank_withdraw'])
            ctx['bank_net_fmt'] = _fmt(ctx['bank_net'])
            if '금융사' in df_bank.columns:
                grp = df_bank.groupby('금융사').agg({'입금액': 'sum', '출금액': 'sum'}).reset_index()
                grp['_total'] = grp['입금액'] + grp['출금액']
                grp = grp.sort_values('_total', ascending=False)
                ctx['bank_by_name'] = [{'name': r['금융사'], 'deposit': int(r['입금액']), 'withdraw': int(r['출금액']), 'total_fmt': _fmt(int(r['입금액']) + int(r['출금액'])), 'is_억': (int(r['입금액']) + int(r['출금액'])) >= 100000000} for _, r in grp.iterrows()]
            if '카테고리' in df_bank.columns:
                cat_col = df_bank['카테고리'].fillna('').astype(str).str.strip().replace('', '(빈값)')
                grp = df_bank.assign(_cat=cat_col).groupby('_cat').agg({'입금액': 'sum', '출금액': 'sum'}).reset_index()
                grp = grp.rename(columns={'_cat': '카테고리'})
                grp['_total'] = grp['입금액'] + grp['출금액']
                grp = grp.sort_values('_total', ascending=False)
                ctx['bank_top_categories'] = [{'카테고리': r['카테고리'], '입금액': int(r['입금액']), '출금액': int(r['출금액']), '입금액_fmt': _fmt(r['입금액']), '출금액_fmt': _fmt(r['출금액'])} for _, r in grp.head(10).iterrows()]
        if not df_card.empty:
            ctx['card_count'] = len(df_card)
            ctx['card_deposit'] = int(df_card['입금액'].sum()) if '입금액' in df_card.columns else 0
            ctx['card_withdraw'] = int(df_card['출금액'].sum()) if '출금액' in df_card.columns else 0
            ctx['card_net'] = ctx['card_deposit'] - ctx['card_withdraw']
            ctx['card_deposit_fmt'] = _fmt(ctx['card_deposit'])
            ctx['card_withdraw_fmt'] = _fmt(ctx['card_withdraw'])
            ctx['card_net_fmt'] = _fmt(ctx['card_net'])
            if ctx['card_deposit'] and ctx['card_deposit'] > 0:
                ctx['card_ratio'] = '%.1f' % (ctx['card_withdraw'] / ctx['card_deposit'])
            if '금융사' in df_card.columns:
                grp = df_card.groupby('금융사').agg({'입금액': 'sum', '출금액': 'sum'}).reset_index()
                grp = grp.sort_values('출금액', ascending=False)
                ctx['card_by_name'] = [{'name': r['금융사'], 'deposit': int(r['입금액']), 'withdraw': int(r['출금액']), 'withdraw_fmt': _fmt(int(r['출금액'] / 10000)) + '만' if r['출금액'] >= 10000 else _fmt(r['출금액'])} for _, r in grp.iterrows()]
            if '카테고리' in df_card.columns:
                cat_col = df_card['카테고리'].fillna('').astype(str).str.strip().replace('', '(빈값)')
                grp = df_card.assign(_cat=cat_col).groupby('_cat').agg({'입금액': 'sum', '출금액': 'sum'}).reset_index()
                grp = grp.rename(columns={'_cat': '카테고리'})
                grp = grp.sort_values('출금액', ascending=False)
                ctx['card_top_categories'] = [{'카테고리': r['카테고리'], '입금액': int(r['입금액']), '출금액': int(r['출금액']), '입금액_fmt': _fmt(r['입금액']), '출금액_fmt': _fmt(int(r['출금액'] / 10000)) + '만' if r['출금액'] >= 10000 else _fmt(r['출금액'])} for _, r in grp.head(10).iterrows()]
        ctx['total_count'] = ctx['bank_count'] + ctx['card_count']
        if not ctx.get('review_start_date') or not ctx.get('review_end_date'):
            date_vals = []
            if not df_all.empty and '거래일' in df_all.columns:
                d = pd.to_datetime(df_all['거래일'], errors='coerce')
                date_vals.extend(d[d.notna()].tolist())
            if date_vals:
                from calendar import monthrange
                min_dt = min(date_vals)
                max_dt = max(date_vals)
                start_dt = min_dt.replace(day=1) if hasattr(min_dt, 'replace') else min_dt
                _, last_day = monthrange(max_dt.year, max_dt.month)
                end_dt = max_dt.replace(day=last_day) if hasattr(max_dt, 'replace') else max_dt
                ctx['review_start_date'] = start_dt.strftime('%Y-%m-%d') if hasattr(start_dt, 'strftime') else str(start_dt)[:10]
                ctx['review_end_date'] = end_dt.strftime('%Y-%m-%d') if hasattr(end_dt, 'strftime') else str(end_dt)[:10]
    except Exception:
        pass
    # ── 은행 입출금 비율·패턴 분석 ──
    if ctx['bank_deposit'] > 0 and ctx['bank_withdraw'] > 0:
        ctx['bank_ratio'] = '%.1f' % (ctx['bank_withdraw'] / ctx['bank_deposit'])
        diff_pct = abs(ctx['bank_deposit'] - ctx['bank_withdraw']) / max(ctx['bank_deposit'], ctx['bank_withdraw']) * 100
        if diff_pct < 10:
            ctx['bank_balance_comment'] = '입출금 총액이 거의 균형을 이루고 있어, 수입과 지출 간 현저한 괴리는 확인되지 아니한다.'
        elif ctx['bank_deposit'] > ctx['bank_withdraw']:
            ctx['bank_balance_comment'] = '입금액이 출금액 대비 약 %s%% 초과하여, 순유입 자금이 존재한다. 해당 유입의 성격(급여·대출·이체 등)에 관한 확인이 가능하다.' % ('{:.0f}'.format(diff_pct))
        else:
            ctx['bank_balance_comment'] = '출금액이 입금액 대비 약 %s%% 초과하여, 자금 유출 추세가 관찰된다. 주요 출금 항목의 경위 확인이 필요하다.' % ('{:.0f}'.format(diff_pct))
    else:
        ctx['bank_balance_comment'] = ''

    # ── 카드 입출금 비율·패턴 분석 ──
    if ctx['card_count'] > 0:
        cd = ctx['card_deposit']
        cw = ctx['card_withdraw']
        if cd > 0 and cw > 0:
            if cw > cd:
                ctx['card_balance_comment'] = '출금액(결제)이 입금액(환불 등) 대비 약 %.1f배로, 카드 결제가 주된 지출 수단으로 활용되고 있다.' % (cw / cd)
            elif cd > cw:
                diff_pct = (cd - cw) / cd * 100
                ctx['card_balance_comment'] = '입금액(환불 등)이 출금액 대비 약 %s%% 초과하여, 상당 규모의 환불·취소 거래가 포함되어 있다.' % ('{:.0f}'.format(diff_pct))
            else:
                ctx['card_balance_comment'] = '입금액과 출금액이 동일하여 결제와 환불이 균형을 이루고 있다.'
        elif cw > 0:
            ctx['card_balance_comment'] = '환불 없이 결제만 존재하여, 카드 이용 지출이 전액 소비로 확인된다.'
        elif cd > 0:
            ctx['card_balance_comment'] = '결제 없이 환불만 존재하는 특이 패턴이다.'
        else:
            ctx['card_balance_comment'] = ''
    else:
        ctx['card_balance_comment'] = ''

    # ── 은행 카테고리 집중도 ──
    if ctx['bank_withdraw'] > 0 and ctx.get('bank_top_categories'):
        btop3 = ctx['bank_top_categories'][:3]
        btop3_sum = sum(c['입금액'] + c['출금액'] for c in btop3)
        btotal = ctx['bank_deposit'] + ctx['bank_withdraw']
        ctx['bank_top3_pct'] = '%.0f' % (btop3_sum / btotal * 100) if btotal > 0 else '0'

    # ── 카드 카테고리 집중도 ──
    if ctx['card_withdraw'] > 0 and ctx.get('card_top_categories'):
        top3 = ctx['card_top_categories'][:3]
        top3_sum = sum(c['출금액'] for c in top3)
        if ctx['card_withdraw'] > 0:
            top3_pct = top3_sum / ctx['card_withdraw'] * 100
            ctx['card_top3_pct'] = '%.0f' % top3_pct
        else:
            ctx['card_top3_pct'] = '0'

    # ── 은행+카드 병합 총액 ──
    total_deposit = ctx['bank_deposit'] + ctx['card_deposit']
    total_withdraw = ctx['bank_withdraw'] + ctx['card_withdraw']
    ctx['total_deposit_fmt'] = _fmt(total_deposit)
    ctx['total_withdraw_fmt'] = _fmt(total_withdraw)
    ctx['total_net_fmt'] = _fmt(total_deposit - total_withdraw)
    ctx['total_has_amount'] = (total_deposit + total_withdraw) > 0

    # ── cash_after 위험도 요약 (대체거래 제외한 실질 거래 기준) ──
    try:
        df_cash = df_all.copy() if ('df_all' in dir() and df_all is not None and not df_all.empty) else None
        if df_cash is not None and not df_cash.empty and '위험도분류' in df_cash.columns:
            if '대체구분' in df_cash.columns:
                df_cash = df_cash[df_cash['대체구분'].fillna('').astype(str).str.strip() == '']
            risk_rows, _tspan_op = _build_risk_classification_rows_from_df(df_cash)
            current_status = [
                {"id": "%d호" % (i + 1), "count": r["count"], "amount": r["withdraw"], "deposit": r.get("deposit", 0), "dates": r.get("dates", [])}
                for i, r in enumerate(risk_rows)
            ]
            risk_report = _calculate_risk_report(RISK_GUIDELINES_FIXED, current_status, _tspan_op)
            ctx['risk_total_score'] = risk_report.get('total_score', 0)
            ctx['risk_grade_label'] = risk_report.get('grade_label', '')
            ctx['risk_grade_desc'] = risk_report.get('grade_desc', '')
            high_risk_count = sum(r['count'] for r in risk_rows[4:])
            ctx['high_risk_count'] = high_risk_count
            ctx['high_risk_names'] = [r['classification'] for r in risk_rows[4:] if r['count'] > 0]
            ctx['risk_classification_rows'] = risk_rows
            notable = [dict(r) for r in risk_rows[1:] if r['count'] > 0]
            notable.sort(key=lambda r: r.get('risk', 0), reverse=True)
            risk_condition_map = _get_risk_condition_map()
            for r in notable[:5]:
                r['condition'] = risk_condition_map.get(r['classification'], '')
                # 호수 / 위험도(분류명) 분리: "9호(과소비지표)" -> classification_ho="9호", classification_name="과소비지표"
                cls = r.get('classification', '')
                if '(' in cls and cls.rstrip().endswith(')'):
                    r['classification_ho'] = cls.split('(')[0].strip()
                    r['classification_name'] = cls.split('(', 1)[1][:-1].strip()
                else:
                    r['classification_ho'] = cls
                    r['classification_name'] = ''
            ctx['risk_notable_items'] = notable[:5]
            ctx['risk_2호_count'] = risk_rows[1]['count'] if len(risk_rows) > 1 else 0
            ctx['risk_2호_withdraw'] = risk_rows[1]['withdraw'] if len(risk_rows) > 1 else 0
            ctx['risk_suggestion_items'] = risk_report.get('suggestion_items', [])
            ctx['risk_report'] = risk_report
    except Exception:
        pass

    # ── 1) 월별 추이 분석 ──
    try:
        _add_monthly_trend(ctx, df_all if 'df_all' in dir() else pd.DataFrame())
    except Exception:
        pass

    # ── 2) 소득 대비 지출 비율 (정기 입금 추정) ──
    try:
        _add_income_ratio(ctx, df_bank if 'df_bank' in dir() else pd.DataFrame())
    except Exception:
        pass

    # ── 3) 현금서비스/카드론 탐지 ──
    try:
        _add_cash_advance_detection(ctx, df_card if 'df_card' in dir() else pd.DataFrame())
    except Exception:
        pass

    # ── 6·7항 누락 사유 (금융사 필터별 설명) ──
    ctx['omit_section6_reason'] = ''
    ctx['omit_section7_reason'] = ''
    bank_count = ctx.get('bank_count', 0) or 0
    card_count = ctx.get('card_count', 0) or 0
    if not (ctx.get('income_expense_comment') or '').strip():
        if bank_count == 0:
            ctx['omit_section6_reason'] = '소득 대비 지출 비율은 은행 입금(정기 입금) 데이터를 기준으로 추정 월 입금(소득?)을 산출합니다. 본 조회는 신용카드만 포함하므로 해당 항목을 산출하지 않습니다.'
        else:
            ctx['omit_section6_reason'] = '은행 입금 데이터에서 정기적으로 반복되는 입금 패턴이 없어 추정 월 입금(소득?)을 산출할 수 없습니다.'
    if not (ctx.get('cash_advance_comment') or '').strip():
        if card_count == 0:
            ctx['omit_section7_reason'] = '현금서비스·카드론 이용 현황은 신용카드 데이터를 기준으로 산출합니다. 본 조회는 은행거래만 포함하므로 해당 항목을 산출하지 않습니다.'
        else:
            ctx['omit_section7_reason'] = '신용카드 데이터에서 현금서비스·카드론으로 추정되는 거래가 없어 본 항목을 생략하였습니다.'

    # ── 4) 정기/비정기 거래 구분 ──
    try:
        _add_regular_transaction_analysis(ctx, df_all if 'df_all' in dir() else pd.DataFrame())
    except Exception:
        pass

    # ── 5) 고위험 거래 상세 내역 (5호 이상) ──
    try:
        _add_high_risk_details(ctx, df_cash if 'df_cash' in dir() and df_cash is not None else pd.DataFrame())
    except Exception:
        pass

    # ── 6) 전반기/후반기 비교 (기간별 변화 분석) ──
    try:
        _add_period_comparison(ctx, df_all if 'df_all' in dir() else pd.DataFrame())
    except Exception:
        pass

    # ── 7) 대체거래 분석 (위에서 미수행 시 보충) ──
    if ctx.get('daechae_total_count', 0) == 0:
        try:
            _add_substitute_transaction_analysis(ctx, df_all if 'df_all' in dir() else pd.DataFrame())
        except Exception:
            pass

    return ctx


def _add_monthly_trend(ctx, df):
    """월별 입출금 추이 분석 → ctx에 trend_comment, monthly_data 추가."""
    if df is None or df.empty or '거래일' not in df.columns:
        ctx['monthly_trend_comment'] = ''
        ctx['monthly_data'] = []
        return
    df = df.copy()
    df['거래일'] = pd.to_datetime(df['거래일'], errors='coerce')
    df = df[df['거래일'].notna()]
    if df.empty:
        ctx['monthly_trend_comment'] = ''
        ctx['monthly_data'] = []
        return
    df['거래월'] = df['거래일'].dt.to_period('M').astype(str)
    monthly = df.groupby('거래월').agg({'입금액': 'sum', '출금액': 'sum'}).reset_index()
    monthly = monthly.sort_values('거래월')
    ctx['monthly_data'] = [{'month': r['거래월'], 'deposit': int(r['입금액']), 'withdraw': int(r['출금액'])} for _, r in monthly.iterrows()]
    if len(monthly) >= 4:
        half = len(monthly) // 2
        first_avg = monthly.iloc[:half]['출금액'].mean()
        second_avg = monthly.iloc[half:]['출금액'].mean()
        if first_avg > 0:
            change_pct = (second_avg - first_avg) / first_avg * 100
            if change_pct < -10:
                ctx['monthly_trend_comment'] = '후반기 월평균 출금이 전반기 대비 약 %.0f%% 감소하여, 지출 개선 추세가 관찰된다.' % abs(change_pct)
            elif change_pct > 10:
                ctx['monthly_trend_comment'] = '후반기 월평균 출금이 전반기 대비 약 %.0f%% 증가하여, 지출 확대 추세가 관찰된다.' % change_pct
            else:
                ctx['monthly_trend_comment'] = '검토 기간 내 월평균 출금이 비교적 안정적으로 유지되고 있다.'
        else:
            ctx['monthly_trend_comment'] = ''
    else:
        ctx['monthly_trend_comment'] = '검토 기간이 4개월 미만이어서 추이 분석이 제한적이다.' if len(monthly) > 0 else ''


def _add_income_ratio(ctx, df_bank):
    """정기 입금(급여 추정) 대비 지출 비율 → ctx에 추가."""
    ctx['estimated_monthly_income'] = 0
    ctx['income_expense_ratio'] = ''
    ctx['income_expense_comment'] = ''
    if df_bank is None or df_bank.empty:
        return
    if '거래일' not in df_bank.columns or '입금액' not in df_bank.columns:
        return
    df = df_bank.copy()
    df['거래일'] = pd.to_datetime(df['거래일'], errors='coerce')
    df = df[df['거래일'].notna()]
    if df.empty:
        return
    df['거래월'] = df['거래일'].dt.to_period('M').astype(str)
    n_months = df['거래월'].nunique()
    if n_months < 1:
        return
    content_col = '내용' if '내용' in df.columns else ('키워드' if '키워드' in df.columns else None)
    if content_col is None:
        return
    deposits = df[df['입금액'] > 0].copy()
    if deposits.empty:
        return
    monthly_by_content = deposits.groupby([content_col, '거래월'])['입금액'].sum().reset_index()
    content_month_count = monthly_by_content.groupby(content_col)['거래월'].count().reset_index()
    content_month_count.columns = [content_col, 'month_count']
    threshold = max(2, n_months * 0.5)
    regular = content_month_count[content_month_count['month_count'] >= threshold]
    if regular.empty:
        return
    regular_names = set(regular[content_col].tolist())
    regular_deposits = deposits[deposits[content_col].isin(regular_names)]
    total_regular = regular_deposits['입금액'].sum()
    est_monthly = int(total_regular / n_months)
    ctx['estimated_monthly_income'] = est_monthly
    if est_monthly > 0:
        monthly_withdraw = int(ctx.get('bank_withdraw', 0) + ctx.get('card_withdraw', 0)) / max(n_months, 1)
        ratio = monthly_withdraw / est_monthly * 100
        ctx['income_expense_ratio'] = '%.1f' % ratio
        if ratio > 120:
            ctx['income_expense_comment'] = '추정 월 입금(소득?) 약 {:,}원 대비 월평균 지출이 약 {:.0f}%로, 소득 초과 지출이 관찰된다.'.format(est_monthly, ratio)
        elif ratio > 90:
            ctx['income_expense_comment'] = '추정 월 입금(소득?) 약 {:,}원 대비 월평균 지출이 약 {:.0f}%로, 소득 대부분이 지출로 소진되고 있다.'.format(est_monthly, ratio)
        else:
            ctx['income_expense_comment'] = '추정 월 입금(소득?) 약 {:,}원 대비 월평균 지출이 약 {:.0f}%로, 수입 범위 내 지출이 이루어지고 있다.'.format(est_monthly, ratio)


def _add_cash_advance_detection(ctx, df_card):
    """현금서비스/카드론 패턴 탐지 → ctx에 추가."""
    ctx['cash_advance_count'] = 0
    ctx['cash_advance_amount'] = 0
    ctx['cash_advance_comment'] = ''
    if df_card is None or df_card.empty:
        return
    keywords = ['현금서비스', '카드론', 'CA이용', 'CA출금', '단기카드대출', '장기카드대출', '카드대출', '현금인출', 'CASH', 'cash advance']
    search_cols = [c for c in ['내용', '키워드', '적요', '카테고리', '기타거래'] if c in df_card.columns]
    if not search_cols:
        return
    mask = pd.Series(False, index=df_card.index)
    for col in search_cols:
        col_text = df_card[col].fillna('').astype(str).str.lower()
        for kw in keywords:
            mask = mask | col_text.str.contains(kw.lower(), na=False)
    if mask.any():
        matched = df_card[mask]
        ctx['cash_advance_count'] = len(matched)
        amt_col = '출금액' if '출금액' in matched.columns else '입금액'
        ctx['cash_advance_amount'] = int(matched[amt_col].sum()) if amt_col in matched.columns else 0
        ctx['cash_advance_comment'] = '현금서비스·카드론 이용으로 추정되는 거래가 {}건(약 {:,}원) 탐지되었다. 채무 상환을 위한 추가 차입 여부에 대한 소명이 권고된다.'.format(
            ctx['cash_advance_count'], ctx['cash_advance_amount'])


def _add_regular_transaction_analysis(ctx, df):
    """정기/비정기 거래 구분 → ctx에 추가."""
    ctx['regular_count'] = 0
    ctx['regular_amount'] = 0
    ctx['irregular_count'] = 0
    ctx['irregular_amount'] = 0
    ctx['regular_comment'] = ''
    if df is None or df.empty or '거래일' not in df.columns:
        return
    df = df.copy()
    df['거래일'] = pd.to_datetime(df['거래일'], errors='coerce')
    df = df[df['거래일'].notna()]
    if df.empty:
        return
    df['거래월'] = df['거래일'].dt.to_period('M').astype(str)
    n_months = df['거래월'].nunique()
    if n_months < 2:
        return
    content_col = '내용' if '내용' in df.columns else ('키워드' if '키워드' in df.columns else None)
    if content_col is None:
        return
    month_count = df.groupby(content_col)['거래월'].nunique().reset_index()
    month_count.columns = [content_col, 'months']
    threshold = max(2, n_months * 0.5)
    regular_names = set(month_count[month_count['months'] >= threshold][content_col].tolist())
    mask_regular = df[content_col].isin(regular_names)
    reg = df[mask_regular]
    irr = df[~mask_regular]
    ctx['regular_count'] = len(reg)
    ctx['regular_amount'] = int(reg['출금액'].sum()) if '출금액' in reg.columns else 0
    ctx['irregular_count'] = len(irr)
    ctx['irregular_amount'] = int(irr['출금액'].sum()) if '출금액' in irr.columns else 0
    total = ctx['regular_count'] + ctx['irregular_count']
    if total > 0:
        reg_pct = ctx['regular_count'] / total * 100
        ctx['regular_comment'] = '전체 거래 중 정기성 거래가 약 {:.0f}%({:,}건), 비정기 거래가 약 {:.0f}%({:,}건)로 구성되어 있다.'.format(
            reg_pct, ctx['regular_count'], 100 - reg_pct, ctx['irregular_count'])


def _add_high_risk_details(ctx, df_cash):
    """5호 이상 고위험 거래 개별 내역 → ctx에 추가."""
    ctx['high_risk_details'] = []
    if df_cash is None or df_cash.empty or '위험도분류' not in df_cash.columns:
        return
    high_classes = {'투기성지표', '사기파산지표', '가상자산지표', '자산은닉지표', '과소비지표', '사행성지표'}
    mask = df_cash['위험도분류'].fillna('').astype(str).str.strip().isin(high_classes)
    if not mask.any():
        return
    high = df_cash[mask].copy()
    if '출금액' in high.columns:
        high = high.sort_values('출금액', ascending=False)
    details = []
    for _, row in high.head(20).iterrows():
        date_str = str(row.get('거래일', ''))[:10] if pd.notna(row.get('거래일')) else ''
        content = str(row.get('내용', '')) if pd.notna(row.get('내용')) else ''
        classification = str(row.get('위험도분류', '')) if pd.notna(row.get('위험도분류')) else ''
        deposit = int(row.get('입금액', 0)) if pd.notna(row.get('입금액')) else 0
        withdraw = int(row.get('출금액', 0)) if pd.notna(row.get('출금액')) else 0
        bank = str(row.get('금융사', row.get('은행명', ''))) if pd.notna(row.get('금융사', row.get('은행명'))) else ''
        kw = str(row.get('위험도키워드', '')) if pd.notna(row.get('위험도키워드')) else ''
        details.append({
            'date': date_str, 'content': content, 'classification': classification,
            'deposit': deposit, 'deposit_fmt': '{:,}'.format(deposit),
            'withdraw': withdraw, 'withdraw_fmt': '{:,}'.format(withdraw),
            'bank': bank, 'keyword': kw,
        })
    ctx['high_risk_details'] = details


def _add_period_comparison(ctx, df):
    """전반기/후반기 비교 분석 → ctx에 추가."""
    ctx['period_comparison'] = {}
    ctx['period_comment'] = ''
    if df is None or df.empty or '거래일' not in df.columns:
        return
    df = df.copy()
    df['거래일'] = pd.to_datetime(df['거래일'], errors='coerce')
    df = df[df['거래일'].notna()]
    if df.empty or len(df) < 10:
        return
    mid_date = df['거래일'].min() + (df['거래일'].max() - df['거래일'].min()) / 2
    first_half = df[df['거래일'] < mid_date]
    second_half = df[df['거래일'] >= mid_date]
    if first_half.empty or second_half.empty:
        return
    f_dep = int(first_half['입금액'].sum()) if '입금액' in first_half.columns else 0
    f_wit = int(first_half['출금액'].sum()) if '출금액' in first_half.columns else 0
    s_dep = int(second_half['입금액'].sum()) if '입금액' in second_half.columns else 0
    s_wit = int(second_half['출금액'].sum()) if '출금액' in second_half.columns else 0
    ctx['period_comparison'] = {
        'first_deposit': f_dep, 'first_withdraw': f_wit, 'first_count': len(first_half),
        'second_deposit': s_dep, 'second_withdraw': s_wit, 'second_count': len(second_half),
        'mid_date': mid_date.strftime('%Y-%m-%d'),
    }
    if f_wit > 0:
        change = (s_wit - f_wit) / f_wit * 100
        if change < -15:
            ctx['period_comment'] = '후반기 출금이 전반기 대비 약 {:.0f}% 감소하여, 지출 감축 노력이 확인된다. 이는 면책 심사에서 긍정적으로 평가될 수 있다.'.format(abs(change))
        elif change > 15:
            ctx['period_comment'] = '후반기 출금이 전반기 대비 약 {:.0f}% 증가하여, 지출 확대 추세가 관찰된다. 증가 사유에 대한 소명이 권고된다.'.format(change)
        else:
            ctx['period_comment'] = '전반기와 후반기 지출 수준이 유사하여 안정적 지출 패턴이 유지되고 있다.'


def _add_substitute_transaction_analysis(ctx, df):
    """대체거래 분석 → ctx에 daechae_* 키 추가."""
    ctx['daechae_total_count'] = 0
    ctx['daechae_bank_count'] = 0
    ctx['daechae_card_count'] = 0
    ctx['daechae_cancel_count'] = 0
    ctx['daechae_bank_amount'] = 0
    ctx['daechae_card_amount'] = 0
    ctx['daechae_cancel_amount'] = 0
    ctx['daechae_bank_deposit'] = 0
    ctx['daechae_bank_withdraw'] = 0
    ctx['daechae_card_deposit'] = 0
    ctx['daechae_card_withdraw'] = 0
    ctx['daechae_cancel_deposit'] = 0
    ctx['daechae_cancel_withdraw'] = 0
    ctx['daechae_total_deposit'] = 0
    ctx['daechae_total_withdraw'] = 0
    ctx['daechae_total_amount'] = 0
    ctx['daechae_ratio_pct'] = '0'
    ctx['daechae_net_deposit'] = 0
    ctx['daechae_net_withdraw'] = 0
    ctx['daechae_net_deposit_fmt'] = '0'
    ctx['daechae_net_withdraw_fmt'] = '0'
    ctx['daechae_comment'] = ''
    if df is None or df.empty or '대체구분' not in df.columns:
        return
    dc = df['대체구분'].fillna('').astype(str).str.strip()
    df_dc = df[dc != ''].copy()
    if df_dc.empty:
        return
    dc_vals = df_dc['대체구분'].fillna('').astype(str).str.strip()

    def _dep(mask):
        return int(df_dc.loc[mask, '입금액'].sum()) if '입금액' in df_dc.columns else 0

    def _wit(mask):
        return int(df_dc.loc[mask, '출금액'].sum()) if '출금액' in df_dc.columns else 0

    bank_mask = dc_vals == '은행대체'
    card_mask = dc_vals == '카드대체'
    cancel_mask = dc_vals == '취소거래'

    ctx['daechae_bank_count'] = int(bank_mask.sum())
    ctx['daechae_card_count'] = int(card_mask.sum())
    ctx['daechae_cancel_count'] = int(cancel_mask.sum())
    ctx['daechae_total_count'] = ctx['daechae_bank_count'] + ctx['daechae_card_count'] + ctx['daechae_cancel_count']

    ctx['daechae_bank_deposit'] = _dep(bank_mask)
    ctx['daechae_bank_withdraw'] = _wit(bank_mask)
    ctx['daechae_bank_amount'] = ctx['daechae_bank_deposit'] + ctx['daechae_bank_withdraw']
    ctx['daechae_card_deposit'] = _dep(card_mask)
    ctx['daechae_card_withdraw'] = _wit(card_mask)
    ctx['daechae_card_amount'] = ctx['daechae_card_deposit'] + ctx['daechae_card_withdraw']
    ctx['daechae_cancel_deposit'] = _dep(cancel_mask)
    ctx['daechae_cancel_withdraw'] = _wit(cancel_mask)
    ctx['daechae_cancel_amount'] = ctx['daechae_cancel_deposit'] + ctx['daechae_cancel_withdraw']
    ctx['daechae_total_deposit'] = ctx['daechae_bank_deposit'] + ctx['daechae_card_deposit'] + ctx['daechae_cancel_deposit']
    ctx['daechae_total_withdraw'] = ctx['daechae_bank_withdraw'] + ctx['daechae_card_withdraw'] + ctx['daechae_cancel_withdraw']
    ctx['daechae_total_amount'] = ctx['daechae_total_deposit'] + ctx['daechae_total_withdraw']

    total_dep = int(df['입금액'].sum()) if '입금액' in df.columns else 0
    total_wit = int(df['출금액'].sum()) if '출금액' in df.columns else 0
    grand_total = total_dep + total_wit

    parts = []
    if ctx['daechae_bank_count'] > 0:
        parts.append('은행대체 {}건({:,}원)'.format(ctx['daechae_bank_count'], ctx['daechae_bank_amount']))
    if ctx['daechae_card_count'] > 0:
        parts.append('카드대체 {}건({:,}원)'.format(ctx['daechae_card_count'], ctx['daechae_card_amount']))
    if ctx['daechae_cancel_count'] > 0:
        parts.append('취소거래 {}건({:,}원)'.format(ctx['daechae_cancel_count'], ctx['daechae_cancel_amount']))

    comment = '대체거래(동일 금액의 계좌 간 이체·환불 등)로 분류된 거래가 총 {}건, 합계 {:,}원으로 확인된다. '.format(
        ctx['daechae_total_count'], ctx['daechae_total_amount'])
    if parts:
        comment += '세부 유형별로 ' + ', '.join(parts) + '이다. '

    if grand_total > 0:
        ratio = ctx['daechae_total_amount'] / grand_total * 100
        ctx['daechae_ratio_pct'] = '{:.1f}'.format(ratio)
        if ratio >= 30:
            comment += '대체거래 비중이 전체 거래금액의 약 {:.1f}%로 상당히 높아, 동일인 계좌 간 자금 이동이 활발한 것으로 판단된다. 이러한 대체거래는 실질적 소득·지출이 아닌 단순 자금 이동에 해당하므로, 면책 심사 시 이를 제외한 실질 입출금액 기준으로 평가하는 것이 타당하다.'.format(ratio)
        elif ratio >= 10:
            comment += '대체거래 비중이 전체 거래금액의 약 {:.1f}%로 일정 비중을 차지하며, 계좌 간 자금 이동이 관찰된다. 실질적 소비 지출과 단순 이체를 구분하여 면책 심사에 반영하는 것이 권고된다.'.format(ratio)
        else:
            comment += '대체거래 비중은 전체 거래금액의 약 {:.1f}%로 미미한 수준이다.'.format(ratio)
    else:
        ctx['daechae_ratio_pct'] = '0'

    if ctx['daechae_cancel_count'] > 0:
        comment += ' 취소거래 {}건({:,}원)은 결제 취소·환불 등에 해당하며, 실질 소비로 보기 어렵다.'.format(
            ctx['daechae_cancel_count'], ctx['daechae_cancel_amount'])

    ctx['daechae_comment'] = comment.strip()

    net_dep = total_dep - int(df_dc.loc[dc_vals != '', '입금액'].sum()) if '입금액' in df.columns else total_dep
    net_wit = total_wit - int(df_dc.loc[dc_vals != '', '출금액'].sum()) if '출금액' in df.columns else total_wit
    ctx['daechae_net_deposit'] = net_dep
    ctx['daechae_net_withdraw'] = net_wit
    ctx['daechae_net_deposit_fmt'] = '{:,}'.format(net_dep)
    ctx['daechae_net_withdraw_fmt'] = '{:,}'.format(net_wit)


@app.route('/analysis/opinion')
@ensure_working_directory
def analysis_opinion_fragment():
    """금융정보 검토 종합의견 프래그먼트 (종합분석 페이지 iframe용). 은행/카드 기본분석 데이터 연동."""
    bank_filter = (request.args.get('bank') or '').strip() or None
    period = (request.args.get('period') or '').strip() or None
    opinion_ctx = _get_opinion_context(bank_filter=bank_filter, period=period)
    return render_template('opinion_fragment.html', **opinion_ctx)


def _get_risk_condition_map():
    """category_table.json을 참조하여 1~10호 위험도분류별 한도금액·횟수 조건 문자열 반환. { '1호(업종분류제외)': '...', ... }"""
    RISK_DISPLAY_PRINT = ['1호(업종분류제외)', '2호(심야폐업지표)', '3호(자료소명지표)', '4호(비정형지표)', '5호(투기성지표)', '6호(사기파산지표)', '7호(가상자산지표)', '8호(자산은닉지표)', '9호(과소비지표)', '10호(사행성지표)']
    RISK_ORDER_PRINT = ['분류제외지표', '심야폐업지표', '자료소명지표', '비정형지표', '투기성지표', '사기파산지표', '가상자산지표', '자산은닉지표', '과소비지표', '사행성지표']
    out = {d: '' for d in RISK_DISPLAY_PRINT}
    try:
        from risk_indicators import _load_위험도분류_keywords
        _, min_out_by_cat = _load_위험도분류_keywords(category_table_path=CATEGORY_TABLE_PATH)
        out[RISK_DISPLAY_PRINT[0]] = '금액제한 없음'
        simya_min = min_out_by_cat.get('심야폐업지표', 100000)
        out[RISK_DISPLAY_PRINT[1]] = '폐업: 금액 무관 / 심야: 출금 {:,.0f}원 이상'.format(simya_min) if simya_min > 0 else '폐업: 금액 무관 / 심야: 출금 10만원 이상'
        min_out_3 = min_out_by_cat.get('자료소명지표', 0)
        out[RISK_DISPLAY_PRINT[2]] = '출금 {:,.0f}원 이상'.format(min_out_3) if min_out_3 > 0 else '출금 500만원 이상'
        min_out_4 = min_out_by_cat.get('비정형지표', 0)
        out[RISK_DISPLAY_PRINT[3]] = '출금 {:,.0f}원 이상, 동일 키워드 3회 이상'.format(min_out_4) if min_out_4 > 0 else '출금 100만원 이상, 동일 키워드 3회 이상'
        for i, cat in enumerate(RISK_ORDER_PRINT[4:], start=4):
            min_out = min_out_by_cat.get(cat, 0)
            out[RISK_DISPLAY_PRINT[i]] = '출금만 {:,.0f}원 이상'.format(min_out) if min_out > 0 else '출금만 해당 금액 이상'
    except Exception:
        out[RISK_DISPLAY_PRINT[0]] = '금액제한 없음'
        out[RISK_DISPLAY_PRINT[1]] = '폐업: 금액 무관 / 심야: 출금 10만원 이상'
        out[RISK_DISPLAY_PRINT[2]] = '출금 500만원 이상'
        out[RISK_DISPLAY_PRINT[3]] = '출금 100만원 이상, 동일 키워드 3회 이상'
        for i in range(4, 8):
            out[RISK_DISPLAY_PRINT[i]] = '출금만 50만원 이상'
        out[RISK_DISPLAY_PRINT[8]] = '출금만 30만원 이상'
        out[RISK_DISPLAY_PRINT[9]] = '출금만 10만원 이상'
    return out


def _build_risk_classification_rows_from_df(df):
    """df(위험도 0.1 이상 필터 적용된 cash_after)로 1~10호 위험도분류별 집계 행 리스트 반환.
    각 행에 'dates'(해당 호 거래일 datetime 리스트)와 전체 분석 기간 'total_span_days'를 함께 반환."""
    RISK_ORDER_PRINT = ['분류제외지표', '심야폐업지표', '자료소명지표', '비정형지표', '투기성지표', '사기파산지표', '가상자산지표', '자산은닉지표', '과소비지표', '사행성지표']
    RISK_DISPLAY_PRINT = ['1호(업종분류제외)', '2호(심야폐업지표)', '3호(자료소명지표)', '4호(비정형지표)', '5호(투기성지표)', '6호(사기파산지표)', '7호(가상자산지표)', '8호(자산은닉지표)', '9호(과소비지표)', '10호(사행성지표)']
    RISK_DEFAULT_VAL = [0.1, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0]
    rows = []
    total_span_days = 0
    if not df.empty and '위험도분류' in df.columns:
        col = '위험도분류'
        valid_set = set(RISK_ORDER_PRINT)
        raw_to_key = lambda x: (x.strip() if x and str(x).strip() and x.strip() in valid_set else '분류제외지표')
        df_key = df[col].fillna('').astype(str).apply(raw_to_key)
        grp = df.groupby(df_key).agg({'입금액': 'sum', '출금액': 'sum', '위험도': 'min'}).reset_index()
        grp = grp.rename(columns={col: 'classification', '입금액': 'deposit', '출금액': 'withdraw', '위험도': 'risk'})
        by_cls = {r['classification']: r for _, r in grp.iterrows()}
        # 호별 거래일(datetime) 수집
        has_date = '거래일' in df.columns
        date_series = None
        if has_date:
            date_series = pd.to_datetime(df['거래일'], errors='coerce')
            valid_dates = date_series.dropna()
            if not valid_dates.empty:
                total_span_days = max(1, (valid_dates.max() - valid_dates.min()).days)
        for i, cls in enumerate(RISK_ORDER_PRINT):
            r = by_cls.get(cls, {})
            rv = r.get('risk')
            risk_val = float(rv) if pd.notna(rv) and rv != '' else RISK_DEFAULT_VAL[i]
            cls_mask = df_key == cls
            cls_dates = []
            if has_date and date_series is not None:
                cls_dt = date_series[cls_mask].dropna()
                cls_dates = [d.to_pydatetime() for d in cls_dt]
            rows.append({
                'classification': RISK_DISPLAY_PRINT[i],
                'risk': round(risk_val, 1),
                'count': int(cls_mask.sum()) if cls in by_cls else 0,
                'deposit': int(r.get('deposit', 0)),
                'withdraw': int(r.get('withdraw', 0)),
                'dates': cls_dates,
            })
    else:
        rows = [{'classification': RISK_DISPLAY_PRINT[i], 'risk': round(RISK_DEFAULT_VAL[i], 1), 'count': 0, 'deposit': 0, 'withdraw': 0, 'dates': []} for i in range(10)]
    return rows, total_span_days


@app.route('/analysis/risk-report')
@ensure_working_directory
def analysis_risk_report():
    """금융정보 위험도 분석 리포트 (종합분석 페이지 우측 iframe용). 금융정보 위험도 테이블 기반 R 산출·리포트."""
    try:
        bank_filter = (request.args.get('bank') or '').strip()
        df = load_category_file()
        if df.empty:
            return "<p>데이터가 없습니다. cash_after를 생성한 뒤 다시 시도하세요.</p>", 200
        if '금융사' not in df.columns:
            if '은행명' in df.columns:
                df['금융사'] = df['은행명'].fillna('')
            elif '카드사' in df.columns:
                df['금융사'] = df['카드사'].fillna('')
            else:
                df['금융사'] = ''
        if bank_filter == '은행거래' and '출처' in df.columns:
            df = df[df['출처'].fillna('').astype(str).str.strip() == '은행거래']
        elif bank_filter == '신용카드' and '출처' in df.columns:
            df = df[df['출처'].fillna('').astype(str).str.strip() == '신용카드']
        elif bank_filter and '금융사' in df.columns:
            df = df[df['금융사'].fillna('').astype(str).str.strip() == bank_filter]
        period = (request.args.get('period') or '').strip()
        df = _filter_df_by_period(df, period, '거래일')
        if '위험도' in df.columns:
            try:
                risk = df['위험도'].fillna(0).astype(float)
                df = df.loc[risk >= 0.1]
            except (TypeError, ValueError):
                pass
        # 대체거래 분석 (전체 데이터 기준)
        daechae_ctx = {}
        _add_substitute_transaction_analysis(daechae_ctx, pd.DataFrame())
        try:
            _add_substitute_transaction_analysis(daechae_ctx, df.copy())
        except Exception:
            pass
        # 대체거래 제외 후 실질 위험도 산출
        df_net = df.copy()
        daechae_excluded_count = 0
        if '대체구분' in df_net.columns:
            _dc = df_net['대체구분'].fillna('').astype(str).str.strip()
            daechae_excluded_count = int((_dc != '').sum())
            df_net = df_net[_dc == '']
        risk_classification_rows, _tspan_rr = _build_risk_classification_rows_from_df(df_net)
        current_status = [
            {"id": "%d호" % (i + 1), "count": r["count"], "amount": r["withdraw"], "deposit": r.get("deposit", 0), "dates": r.get("dates", [])}
            for i, r in enumerate(risk_classification_rows)
        ]
        risk_report = _calculate_risk_report(RISK_GUIDELINES_FIXED, current_status, _tspan_rr)
        # 전체(대체거래 포함) R도 참고용으로 산출
        risk_full_report = None
        if daechae_excluded_count > 0:
            rows_full, _tspan_rr_f = _build_risk_classification_rows_from_df(df)
            status_full = [{"id": "%d호" % (i + 1), "count": r["count"], "amount": r["withdraw"], "deposit": r.get("deposit", 0), "dates": r.get("dates", [])} for i, r in enumerate(rows_full)]
            risk_full_report = _calculate_risk_report(RISK_GUIDELINES_FIXED, status_full, _tspan_rr_f)
        return render_template('risk_report_page.html',
            risk_report=risk_report,
            risk_full_report=risk_full_report,
            daechae_excluded_count=daechae_excluded_count,
            filter_institution=bank_filter or '',
            **daechae_ctx)
    except Exception as e:
        return "<p>오류: " + str(e) + "</p>", 200

# 분석 API 라우트
@app.route('/api/analysis/summary')
@ensure_working_directory
def get_analysis_summary():
    """전체 통계 요약 (cash_after 기준). 합계건수=전체 행 수(은행거래+신용카드), 은행거래=은행거래 행 수, 신용카드=신용카드 행 수, 입금합계/출금합계=전체 합계, 순잔액=입금합계−출금합계."""
    try:
        df = load_category_file()
        if df.empty:
            return jsonify({
                'total_deposit': 0,
                'total_withdraw': 0,
                'net_balance': 0,
                'total_count': 0,
                'deposit_count': 0,
                'withdraw_count': 0
            })
        bank_filter = request.args.get('bank', '')
        if bank_filter == '은행거래' and '출처' in df.columns:
            df = df[df['출처'].fillna('').astype(str).str.strip() == '은행거래']
        elif bank_filter == '신용카드' and '출처' in df.columns:
            df = df[df['출처'].fillna('').astype(str).str.strip() == '신용카드']
        elif bank_filter and '금융사' in df.columns:
            df = df[df['금융사'].fillna('').astype(str).str.strip() == bank_filter]
        elif bank_filter and '은행명' in df.columns:
            df = df[df['은행명'] == bank_filter]
        period = request.args.get('period', '').strip()
        df = _filter_df_by_period(df, period, '거래일' if '거래일' in df.columns else '이용일')
        exclude_daechae = request.args.get('exclude_daechae', '').strip()
        if exclude_daechae == '1' and '대체구분' in df.columns:
            df = df[df['대체구분'].fillna('').astype(str).str.strip() == '']

        # 검토기간 내 전체 건수·금액 (종합의견과 동일한 기준: 위험도 필터 없음)
        total_deposit = int(df['입금액'].sum()) if '입금액' in df.columns else 0
        total_withdraw = int(df['출금액'].sum()) if '출금액' in df.columns else 0
        net_balance = total_deposit - total_withdraw
        total_count = len(df)
        # 출처(은행거래/신용카드) 컬럼 기준 집계. 없으면 금융사 이름으로 은행/카드 구분
        if '출처' in df.columns:
            src_trim = df['출처'].fillna('').astype(str).str.strip()
            bank_mask = src_trim == '은행거래'
            card_mask = src_trim == '신용카드'
            bank_count = int(bank_mask.sum())
            card_count = int(card_mask.sum())
            bank_withdraw = int(df.loc[bank_mask, '출금액'].sum()) if '출금액' in df.columns else 0
            card_withdraw = int(df.loc[card_mask, '출금액'].sum()) if '출금액' in df.columns else 0
        else:
            bank_count = card_count = 0
            bank_withdraw = card_withdraw = 0
        if (bank_count == 0 and card_count == 0) and total_count > 0 and '금융사' in df.columns:
            gu = df['금융사'].fillna('').astype(str).str.strip()
            bank_count = int(gu.isin(BANK_NAMES).sum())
            card_count = total_count - bank_count
            bank_withdraw = int(df.loc[gu.isin(BANK_NAMES), '출금액'].sum()) if '출금액' in df.columns else 0
            card_withdraw = total_withdraw - bank_withdraw
        deposit_count = bank_count
        withdraw_count = card_count

        response = jsonify({
            'total_deposit': total_deposit,
            'total_withdraw': total_withdraw,
            'net_balance': net_balance,
            'total_count': total_count,
            'deposit_count': deposit_count,
            'withdraw_count': withdraw_count,
            'bank_count': bank_count,
            'bank_withdraw': bank_withdraw,
            'card_count': card_count,
            'card_withdraw': card_withdraw
        })

        return response
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/analysis/by-category')
@ensure_working_directory
def get_analysis_by_category():
    """적요별 분석 (카테고리 파일 사용)"""
    try:
        df = load_category_file()
        if df.empty:
            return jsonify({'data': []})
        
        # 은행(금융사) 필터
        bank_filter = request.args.get('bank', '')
        if bank_filter == '은행거래' and '출처' in df.columns:
            df = df[df['출처'].fillna('').astype(str).str.strip() == '은행거래']
        elif bank_filter == '신용카드' and '출처' in df.columns:
            df = df[df['출처'].fillna('').astype(str).str.strip() == '신용카드']
        elif bank_filter and '금융사' in df.columns:
            allowed = set(BANK_FILTER_ALIASES.get(bank_filter, [bank_filter]))
            df = df[df['금융사'].fillna('').astype(str).str.strip().isin(allowed)]
        
        # 카테고리분류를 입출금으로 매핑
        if '카테고리분류' in df.columns and '입출금' not in df.columns:
            df['입출금'] = df['카테고리분류']
        
        # 카테고리 필터 (여러 필터 지원)
        classification_filter = request.args.get('입출금', '')
        transaction_type_filter = request.args.get('거래유형', '')
        
        # 기존 방식 지원 (하위 호환성)
        category_type = request.args.get('category_type', '')
        category_value = request.args.get('category_value', '')
        if category_type and category_value:
            if category_type in df.columns:
                df = df[df[category_type] == category_value]
        
        # 새로운 방식 (여러 필터 동시 적용)
        if classification_filter and '입출금' in df.columns:
            df = df[df['입출금'] == classification_filter]
        if transaction_type_filter and '거래유형' in df.columns:
            df = df[df['거래유형'] == transaction_type_filter]
        
        # 적요별 입금/출금 집계 (입출금, 거래유형, 카테고리 정보도 포함)
        agg_dict = {
            '입금액': 'sum',
            '출금액': 'sum'
        }
        
        # 입출금, 거래유형, 카테고리, 금융사 등 있으면 첫 번째 값 사용 (대표값)
        for col in ('입출금', '거래유형', '카테고리', '금융사', '내용', '거래점'):
            if col in df.columns:
                agg_dict[col] = 'first'
        
        # cash_after 기준 컬럼: 적요(없음) → 기타거래로 집계
        group_col = '기타거래' if '기타거래' in df.columns else ('적요' if '적요' in df.columns else None)
        if group_col is None:
            return jsonify({'data': []})
        category_stats = df.groupby(group_col).agg(agg_dict).reset_index()
        
        # 차액 계산
        category_stats['차액'] = category_stats['입금액'] - category_stats['출금액']
        
        # 정렬: 차액 절대값 큰 순, 절대값 같으면 차액 큰 순, 차액 같으면 입금액 많은 순
        category_stats['차액_절대값'] = category_stats['차액'].abs()
        category_stats = category_stats.sort_values(['차액_절대값', '차액', '입금액'], ascending=[False, False, False])
        category_stats = category_stats.drop('차액_절대값', axis=1)
        
        # 데이터 포맷팅
        data = []
        def _row_str(row, col, default='(빈값)'):
            v = row.get(col)
            return str(v) if v is not None and pd.notna(v) and str(v) != '' else default

        for _, row in category_stats.iterrows():
            item = {
                'category': _row_str(row, group_col),
                'deposit': int(row['입금액']) if pd.notna(row.get('입금액')) else 0,
                'withdraw': int(row['출금액']) if pd.notna(row.get('출금액')) else 0,
                'balance': int(row['차액']) if pd.notna(row.get('차액')) else 0,
                'classification': _row_str(row, '입출금'),
                'transactionType': _row_str(row, '거래유형'),
                'transactionTarget': _row_str(row, '카테고리'),
                'bank': _row_str(row, '금융사'),
                'content': _row_str(row, '내용', default=''),
                'transactionPoint': _row_str(row, '거래점', default=''),
            }
            data.append(item)
        
        response = jsonify({'data': data})

        return response
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/analysis/by-category-group')
@ensure_working_directory
def get_analysis_by_category_group():
    """카테고리 기준 분석 (입출금/거래유형/카테고리 기준 집계)"""
    try:
        df = load_category_file()
        if df.empty:
            return jsonify({'data': []})
        
        # 카테고리분류를 입출금으로 매핑
        if '카테고리분류' in df.columns and '입출금' not in df.columns:
            df['입출금'] = df['카테고리분류']
        
        # 은행 필터
        bank_filter = request.args.get('bank', '')
        _bcol = '금융사' if '금융사' in df.columns else ('은행명' if '은행명' in df.columns else None)
        if bank_filter and _bcol:
            df = df[df[_bcol] == bank_filter]
        
        # 카테고리 필터 (입출금/거래유형/카테고리)
        입출금_filter = request.args.get('입출금', '')
        거래유형_filter = request.args.get('거래유형', '')
        카테고리_filter = request.args.get('카테고리', '')
        if 입출금_filter and '입출금' in df.columns:
            df = df[df['입출금'] == 입출금_filter]
        if 거래유형_filter and '거래유형' in df.columns:
            df = df[df['거래유형'] == 거래유형_filter]
        if 카테고리_filter and '카테고리' in df.columns:
            df = df[df['카테고리'] == 카테고리_filter]
        groupby_columns = []
        if '입출금' in df.columns:
            groupby_columns.append('입출금')
        if '거래유형' in df.columns:
            groupby_columns.append('거래유형')
        if '카테고리' in df.columns:
            groupby_columns.append('카테고리')
        
        if not groupby_columns:
            return jsonify({'data': []})
        
        # 집계 (은행명도 포함하여 집계)
        category_stats = df.groupby(groupby_columns + ['은행명']).agg({
            '입금액': 'sum',
            '출금액': 'sum'
        }).reset_index()
        
        # 차액 계산
        category_stats['차액'] = category_stats['입금액'] - category_stats['출금액']
        category_stats['총거래액'] = category_stats['입금액'] + category_stats['출금액']
        
        # 카테고리 그룹별로 다시 집계 (은행명은 가장 많은 거래가 있는 은행명 사용)
        category_final = []
        for category_group, group_df in category_stats.groupby(groupby_columns):
            # 가장 많은 거래액이 있는 은행명 선택
            main_bank_row = group_df.loc[group_df['총거래액'].idxmax()]
            main_bank = main_bank_row['은행명']
            
            # 카테고리 그룹별 합계
            total_deposit = group_df['입금액'].sum()
            total_withdraw = group_df['출금액'].sum()
            total_balance = total_deposit - total_withdraw
            
            item = {
                'deposit': int(total_deposit) if pd.notna(total_deposit) else 0,
                'withdraw': int(total_withdraw) if pd.notna(total_withdraw) else 0,
                'balance': int(total_balance) if pd.notna(total_balance) else 0,
                '은행명': str(main_bank) if pd.notna(main_bank) and main_bank != '' else '(빈값)'
            }
            
            # 각 카테고리 컬럼 추가
            if isinstance(category_group, tuple):
                for i, col in enumerate(groupby_columns):
                    value = category_group[i] if i < len(category_group) else None
                    if pd.notna(value) and value != '':
                        item[col] = str(value)
                    else:
                        item[col] = '(빈값)'
            else:
                if '입출금' in groupby_columns:
                    item['입출금'] = str(category_group) if pd.notna(category_group) and category_group != '' else '(빈값)'
                elif '거래유형' in groupby_columns:
                    item['거래유형'] = str(category_group) if pd.notna(category_group) and category_group != '' else '(빈값)'
                elif '카테고리' in groupby_columns:
                    item['카테고리'] = str(category_group) if pd.notna(category_group) and category_group != '' else '(빈값)'
            
            category_final.append(item)
        
        # 정렬: 차액 절대값 큰 순, 절대값 같으면 차액 큰 순, 차액 같으면 입금액 많은 순
        category_final_df = pd.DataFrame(category_final)
        category_final_df['차액_절대값'] = category_final_df['balance'].abs()
        category_final_df = category_final_df.sort_values(['차액_절대값', 'balance', 'deposit'], ascending=[False, False, False])
        category_final_df = category_final_df.drop('차액_절대값', axis=1)
        
        # 데이터 포맷팅
        data = category_final_df.to_dict('records')
        
        response = jsonify({'data': data})

        return response
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/analysis/by-month')
@ensure_working_directory
def get_analysis_by_month():
    """월별 추이 분석 (카테고리 파일 사용)"""
    try:
        df = load_category_file()
        if df.empty:
            return jsonify({'months': [], 'deposit': [], 'withdraw': [], 'min_date': None, 'max_date': None})
        
        # 전체 데이터의 최소/최대 날짜 계산 (필터 적용 전)
        df_all = df.copy()
        df_all['거래일'] = pd.to_datetime(df_all['거래일'], errors='coerce')
        df_all = df_all[df_all['거래일'].notna()]
        min_date = df_all['거래일'].min()
        max_date = df_all['거래일'].max()
        
        # 은행 필터
        bank_filter = request.args.get('bank', '')
        _bcol = '금융사' if '금융사' in df.columns else ('은행명' if '은행명' in df.columns else None)
        if bank_filter and _bcol:
            df = df[df[_bcol] == bank_filter]
        
        # 카테고리분류를 입출금으로 매핑
        if '카테고리분류' in df.columns and '입출금' not in df.columns:
            df['입출금'] = df['카테고리분류']
        
        # 카테고리 필터 (여러 필터 지원)
        classification_filter = request.args.get('입출금', '')
        transaction_type_filter = request.args.get('거래유형', '')
        
        # 기존 방식 지원 (하위 호환성)
        category_type = request.args.get('category_type', '')
        category_value = request.args.get('category_value', '')
        if category_type and category_value:
            if category_type in df.columns:
                df = df[df[category_type] == category_value]
        
        # 새로운 방식 (여러 필터 동시 적용)
        if classification_filter and '입출금' in df.columns:
            df = df[df['입출금'] == classification_filter]
        if transaction_type_filter and '거래유형' in df.columns:
            df = df[df['거래유형'] == transaction_type_filter]
        
        df['거래일'] = pd.to_datetime(df['거래일'], errors='coerce')
        df = df[df['거래일'].notna()]
        df['거래월'] = df['거래일'].dt.to_period('M').astype(str)
        
        # 전체 기간의 모든 월 생성 (최소일부터 최대일까지)
        if pd.notna(min_date) and pd.notna(max_date):
            date_range = pd.period_range(start=min_date.to_period('M'), end=max_date.to_period('M'), freq='M')
            all_months = [str(period) for period in date_range]
        else:
            all_months = sorted(df['거래월'].unique().tolist())
        
        # 월별 집계
        monthly_stats = df.groupby('거래월').agg({
            '입금액': 'sum',
            '출금액': 'sum'
        }).reset_index()
        
        # 모든 월에 대해 데이터 생성 (없는 월은 0)
        deposit_dict = dict(zip(monthly_stats['거래월'], monthly_stats['입금액']))
        withdraw_dict = dict(zip(monthly_stats['거래월'], monthly_stats['출금액']))
        
        deposit = [int(deposit_dict.get(month, 0)) if pd.notna(deposit_dict.get(month, 0)) else 0 for month in all_months]
        withdraw = [int(withdraw_dict.get(month, 0)) if pd.notna(withdraw_dict.get(month, 0)) else 0 for month in all_months]
        
        response = jsonify({
            'months': all_months,
            'deposit': deposit,
            'withdraw': withdraw,
            'min_date': str(min_date) if pd.notna(min_date) else None,
            'max_date': str(max_date) if pd.notna(max_date) else None
        })

        return response
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/analysis/by-category-monthly')
@ensure_working_directory
def get_analysis_by_category_monthly():
    """카테고리별 월별 입출금 추이 분석"""
    try:
        df = load_category_file()
        if df.empty:
            return jsonify({'months': [], 'categories': []})
        
        # 카테고리분류를 입출금으로 매핑
        if '카테고리분류' in df.columns and '입출금' not in df.columns:
            df['입출금'] = df['카테고리분류']
        
        # 은행 필터
        bank_filter = request.args.get('bank', '')
        _bcol = '금융사' if '금융사' in df.columns else ('은행명' if '은행명' in df.columns else None)
        if bank_filter and _bcol:
            df = df[df[_bcol] == bank_filter]
        
        # 카테고리 필터 (입출금/거래유형/카테고리)
        입출금_filter = request.args.get('입출금', '')
        거래유형_filter = request.args.get('거래유형', '')
        카테고리_filter = request.args.get('카테고리', '')
        if 입출금_filter and '입출금' in df.columns:
            df = df[df['입출금'] == 입출금_filter]
        if 거래유형_filter and '거래유형' in df.columns:
            df = df[df['거래유형'] == 거래유형_filter]
        if 카테고리_filter and '카테고리' in df.columns:
            df = df[df['카테고리'] == 카테고리_filter]
        df['거래일'] = pd.to_datetime(df['거래일'], errors='coerce')
        df = df[df['거래일'].notna()]
        df['거래월'] = df['거래일'].dt.to_period('M').astype(str)
        groupby_columns = []
        if '입출금' in df.columns:
            groupby_columns.append('입출금')
        if '거래유형' in df.columns:
            groupby_columns.append('거래유형')
        if '카테고리' in df.columns:
            groupby_columns.append('카테고리')
        
        if not groupby_columns:
            return jsonify({'months': [], 'categories': []})
        
        # 카테고리별 월별 집계
        monthly_by_category = df.groupby(groupby_columns + ['거래월']).agg({
            '입금액': 'sum',
            '출금액': 'sum'
        }).reset_index()
        
        # 모든 월 목록 추출
        all_months = sorted(df['거래월'].unique().tolist())
        
        # 카테고리별 데이터 구성
        categories_data = []
        for category_group, group_df in monthly_by_category.groupby(groupby_columns):
            # 카테고리 라벨 생성 (거래유형/카테고리 포함)
            category_label_parts = []
            if isinstance(category_group, tuple):
                # 튜플인 경우 (여러 컬럼으로 그룹화된 경우)
                for i, col in enumerate(groupby_columns):
                    # 입출금은 제외하고 거래유형/카테고리 포함
                    if col in ['거래유형', '카테고리']:
                        value = category_group[i] if i < len(category_group) else None
                        if pd.notna(value) and value != '':
                            category_label_parts.append(str(value))
            else:
                # 단일 값인 경우 (거래유형/카테고리 중 하나)
                if pd.notna(category_group) and category_group != '':
                    category_label_parts.append(str(category_group))
            
            category_label = '_'.join(category_label_parts) if category_label_parts else '(빈값)'
            
            # 월별 데이터 매핑
            monthly_deposit = {}
            monthly_withdraw = {}
            for _, row in group_df.iterrows():
                month = row['거래월']
                monthly_deposit[month] = int(row['입금액']) if pd.notna(row['입금액']) else 0
                monthly_withdraw[month] = int(row['출금액']) if pd.notna(row['출금액']) else 0
            
            # 모든 월에 대해 데이터 생성 (없는 월은 0)
            deposit_data = [monthly_deposit.get(month, 0) for month in all_months]
            withdraw_data = [monthly_withdraw.get(month, 0) for month in all_months]
            
            # 총 입금액, 출금액, 차액 계산 (차액 절대값 기준 정렬용)
            total_deposit = sum(deposit_data)
            total_withdraw = sum(withdraw_data)
            total_balance = total_deposit - total_withdraw
            abs_balance = abs(total_balance)
            
            categories_data.append({
                'label': category_label,
                'deposit': deposit_data,
                'withdraw': withdraw_data,
                'total_deposit': total_deposit,
                'total_withdraw': total_withdraw,
                'total_balance': total_balance,
                'abs_balance': abs_balance
            })
        
        # 차액(절대값) 기준으로 정렬하고 상위 10개만 선택
        categories_data.sort(key=lambda x: x['abs_balance'], reverse=True)
        categories_data = categories_data[:10]
        
        response = jsonify({
            'months': all_months,
            'categories': categories_data
        })

        return response
    except Exception as e:
        return jsonify({'error': str(e), 'months': [], 'categories': []}), 500

@app.route('/api/analysis/by-content')
@ensure_working_directory
def get_analysis_by_content():
    """기타거래별 분석 (cash_after 기준)"""
    try:
        df = load_category_file()
        if df.empty:
            return jsonify({'deposit': [], 'withdraw': []})
        
        content_col = '기타거래' if '기타거래' in df.columns else '내용'
        deposit_by_content = df.groupby(content_col)['입금액'].sum().sort_values(ascending=False)
        deposit_data = [{'content': idx if idx else '(빈값)', 'amount': int(val)} for idx, val in deposit_by_content.items() if val > 0]
        
        withdraw_by_content = df.groupby(content_col)['출금액'].sum().sort_values(ascending=False)
        withdraw_data = [{'content': idx if idx else '(빈값)', 'amount': int(val)} for idx, val in withdraw_by_content.items() if val > 0]
        
        response = jsonify({
            'deposit': deposit_data,
            'withdraw': withdraw_data
        })

        return response
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/analysis/by-division')
@ensure_working_directory
def get_analysis_by_division():
    """폐업별 분석 (cash_after 기준)"""
    try:
        df = load_category_file()
        if df.empty:
            return jsonify({'data': []})
        
        if '폐업' not in df.columns:
            return jsonify({'data': []})
        division_stats = df.groupby('폐업').agg({
            '입금액': 'sum',
            '출금액': 'sum',
            '거래일': 'count'
        }).reset_index()
        division_stats.columns = ['division', 'deposit', 'withdraw', 'count']
        division_stats = division_stats.fillna('')
        division_stats['deposit'] = division_stats['deposit'].astype(int)
        division_stats['withdraw'] = division_stats['withdraw'].astype(int)
        
        data = division_stats.to_dict('records')
        response = jsonify({'data': data})

        return response
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/analysis/by-bank')
@ensure_working_directory
def get_analysis_by_bank():
    """은행/계좌별 분석 (카테고리 파일 사용)"""
    try:
        df = load_category_file()
        if df.empty:
            return jsonify({'bank': [], 'account': []})
        
        # 은행별 통계
        _bcol = '금융사' if '금융사' in df.columns else '은행명'
        bank_stats = df.groupby(_bcol).agg({
            '입금액': 'sum',
            '출금액': 'sum'
        }).reset_index()
        bank_data = [{
            'bank': row[_bcol],
            'deposit': int(row['입금액']),
            'withdraw': int(row['출금액'])
        } for _, row in bank_stats.iterrows()]
        
        # 계좌별 통계
        account_stats = df.groupby([_bcol, '계좌번호']).agg({
            '입금액': 'sum',
            '출금액': 'sum'
        }).reset_index()
        account_data = [{
            'bank': row[_bcol],
            'account': row['계좌번호'],
            'deposit': int(row['입금액']),
            'withdraw': int(row['출금액'])
        } for _, row in account_stats.iterrows()]
        
        response = jsonify({
            'bank': bank_data,
            'account': account_data
        })

        return response
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/analysis/transactions-by-content')
@ensure_working_directory
def get_transactions_by_content():
    """거래처(기타거래)별 거래 내역 (cash_after 기준)"""
    try:
        df = load_category_file()
        if df.empty:
            return jsonify({'data': []})
        
        type_filter = request.args.get('type', 'deposit')
        try:
            limit = min(max(int(request.args.get('limit', 10)), 1), 100)
        except (ValueError, TypeError):
            limit = 10
        
        content_col = '기타거래' if '기타거래' in df.columns else '내용'
        bank_col = '금융사' if '금융사' in df.columns else '은행명'
        amt_col = '입금액' if type_filter == 'deposit' else '출금액'
        
        top_contents = df[df[amt_col] > 0].groupby(content_col)[amt_col].sum().sort_values(ascending=False).head(limit)
        top_content_list = top_contents.index.tolist()
        
        transactions = df[(df[content_col].isin(top_content_list)) & (df[amt_col] > 0)].copy()
        transactions = transactions.sort_values(amt_col, ascending=False)
        transactions = transactions.where(pd.notna(transactions), None)
        
        out_cols = [c for c in ['거래일', bank_col, amt_col, '카테고리', content_col] if c in transactions.columns]
        data = transactions[out_cols].to_dict('records') if out_cols else []
        data = _json_safe(data)
        response = jsonify({'data': data})

        return response
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/analysis/transactions')
@ensure_working_directory
def get_analysis_transactions():
    """적요별 상세 거래 내역 반환 (카테고리 파일 사용)"""
    try:
        df = load_category_file()
        if df.empty:
            return jsonify({'data': [], 'deposit_total': 0, 'withdraw_total': 0, 'balance': 0, 'deposit_count': 0, 'withdraw_count': 0})
        
        transaction_type = request.args.get('type', 'deposit') # 'deposit' or 'withdraw'
        category_filter = request.args.get('category', '')  # 적요 필터
        content_filter = request.args.get('content', '')  # 거래처 필터 (하위 호환성)
        bank_filter = request.args.get('bank', '')
        
        content_col = '기타거래' if '기타거래' in df.columns else ('적요' if '적요' in df.columns else '내용')
        bank_col = '금융사' if '금융사' in df.columns else '은행명'
        
        if category_filter:
            filtered_df = df[df[content_col] == category_filter].copy()
        elif content_filter:
            filtered_df = df[df[content_col] == content_filter].copy()
        else:
            return jsonify({'data': [], 'deposit_total': 0, 'withdraw_total': 0, 'balance': 0, 'deposit_count': 0, 'withdraw_count': 0})
        
        if bank_filter and bank_col in filtered_df.columns:
            filtered_df = filtered_df[filtered_df[bank_col] == bank_filter].copy()
        
        # 카테고리 필터
        category_type = request.args.get('category_type', '')
        category_value = request.args.get('category_value', '')
        if category_type and category_value:
            if category_type in filtered_df.columns:
                filtered_df = filtered_df[filtered_df[category_type] == category_value].copy()
        
        # 적요별 입금/출금 합계 및 건수 계산
        deposit_total = filtered_df['입금액'].sum() if not filtered_df.empty else 0
        withdraw_total = filtered_df['출금액'].sum() if not filtered_df.empty else 0
        balance = deposit_total - withdraw_total
        deposit_count = len(filtered_df[filtered_df['입금액'] > 0]) if not filtered_df.empty else 0
        withdraw_count = len(filtered_df[filtered_df['출금액'] > 0]) if not filtered_df.empty else 0
        
        if transaction_type == 'detail':
            detail_cols = ['거래일', bank_col, '입금액', '출금액']
            if content_col in filtered_df.columns:
                detail_cols.append(content_col)
            available_cols = [c for c in detail_cols if c in filtered_df.columns]
            result_df = filtered_df[available_cols].copy() if available_cols else filtered_df.copy()
        elif transaction_type == 'deposit':
            filtered_df = filtered_df[filtered_df['입금액'] > 0]
            out_cols = [c for c in ['거래일', bank_col, '입금액', '카테고리', content_col] if c in filtered_df.columns]
            result_df = filtered_df[out_cols].copy() if out_cols else filtered_df.copy()
            if '입금액' in result_df.columns:
                result_df.rename(columns={'입금액': '금액'}, inplace=True)
        elif transaction_type == 'withdraw':
            filtered_df = filtered_df[filtered_df['출금액'] > 0]
            out_cols = [c for c in ['거래일', bank_col, '출금액', '카테고리', content_col] if c in filtered_df.columns]
            result_df = filtered_df[out_cols].copy() if out_cols else filtered_df.copy()
            if '출금액' in result_df.columns:
                result_df.rename(columns={'출금액': '금액'}, inplace=True)
        else: # balance - 차액 상위순일 때는 입금과 출금 모두 표시
            bal_cols = [c for c in ['거래일', bank_col, '카테고리', content_col] if c in filtered_df.columns]
            deposit_df = filtered_df[filtered_df['입금액'] > 0].copy()
            withdraw_df = filtered_df[filtered_df['출금액'] > 0].copy()

            dep_out = [c for c in bal_cols if c in deposit_df.columns] + ['입금액']
            deposit_result = deposit_df[[c for c in dep_out if c in deposit_df.columns]].copy()
            deposit_result.rename(columns={'입금액': '금액'}, inplace=True)
            deposit_result['거래유형'] = '입금'

            wit_out = [c for c in bal_cols if c in withdraw_df.columns] + ['출금액']
            withdraw_result = withdraw_df[[c for c in wit_out if c in withdraw_df.columns]].copy()
            withdraw_result.rename(columns={'출금액': '금액'}, inplace=True)
            withdraw_result['거래유형'] = '출금'

            result_df = pd.concat([deposit_result, withdraw_result], ignore_index=True)
        
        # 거래일 순으로 정렬
        result_df = result_df.sort_values('거래일')
        
        result_df = result_df.where(pd.notna(result_df), None)
        data = result_df.to_dict('records')
        data = _json_safe(data)
        response = jsonify({
            'data': data,
            'deposit_total': int(deposit_total),
            'withdraw_total': int(withdraw_total),
            'balance': int(balance),
            'deposit_count': int(deposit_count),
            'withdraw_count': int(withdraw_count)
        })

        return response
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/analysis/content-by-category')
@ensure_working_directory
def get_content_by_category():
    """카테고리별 기타거래 목록 반환 (cash_after 기준)"""
    try:
        df = load_category_file()
        if df.empty:
            return jsonify({'data': []})
        
        category_filter = request.args.get('category', '')
        if not category_filter:
            return jsonify({'data': []})
        
        content_col = '기타거래' if '기타거래' in df.columns else ('적요' if '적요' in df.columns else '내용')
        filtered_df = df[(df[content_col] == category_filter) & (df['입금액'] > 0)].copy()
        
        if filtered_df.empty:
            return jsonify({'data': []})
        
        content_stats = filtered_df.groupby(content_col)['입금액'].sum().sort_values(ascending=False).reset_index()
        
        data = []
        for _, row in content_stats.iterrows():
            val = row[content_col]
            data.append({
                'content': val if pd.notna(val) and val != '' else '(빈값)',
                'amount': int(row['입금액']) if pd.notna(row['입금액']) else 0
            })
        
        response = jsonify({'data': data})

        return response
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/analysis/cash-after-date-range')
@ensure_working_directory
def get_cash_after_date_range():
    """cash_after 전체의 최소/최대 거래일 반환. 월별 입출금 추이 그래프 x축(시작일~종료일)용."""
    try:
        df = load_category_file()
        if df.empty:
            return jsonify({'min_date': None, 'max_date': None})
        if '거래일' not in df.columns:
            return jsonify({'min_date': None, 'max_date': None})
        df = df.copy()
        df['거래일'] = pd.to_datetime(df['거래일'], errors='coerce')
        df = df[df['거래일'].notna()]
        if df.empty:
            return jsonify({'min_date': None, 'max_date': None})
        min_date = df['거래일'].min()
        max_date = df['거래일'].max()
        response = jsonify({
            'min_date': min_date.strftime('%Y-%m-%d') if pd.notna(min_date) else None,
            'max_date': max_date.strftime('%Y-%m-%d') if pd.notna(max_date) else None
        })

        return response
    except Exception as e:
        return jsonify({'error': str(e), 'min_date': None, 'max_date': None}), 500


@app.route('/api/analysis/date-range')
@ensure_working_directory
def get_date_range():
    """cash_after 데이터의 최소/최대 거래일 반환"""
    try:
        df = load_category_file()
        if df.empty:
            return jsonify({'min_date': None, 'max_date': None})
        
        if '거래일' not in df.columns:
            return jsonify({'min_date': None, 'max_date': None})
        
        # 거래일을 날짜 형식으로 변환
        df['거래일'] = pd.to_datetime(df['거래일'], errors='coerce')
        df = df[df['거래일'].notna()]
        
        if df.empty:
            return jsonify({'min_date': None, 'max_date': None})
        
        min_date = df['거래일'].min()
        max_date = df['거래일'].max()
        
        response = jsonify({
            'min_date': min_date.strftime('%Y-%m-%d') if pd.notna(min_date) else None,
            'max_date': max_date.strftime('%Y-%m-%d') if pd.notna(max_date) else None
        })

        return response
    except Exception as e:
        return jsonify({'error': str(e), 'min_date': None, 'max_date': None}), 500

# ----- API: cash_after 생성 (병합) -----
@app.route('/api/save-match-type', methods=['POST'])
@ensure_working_directory
def save_match_type():
    """cash_after.json 행의 대체구분 필드를 일괄 갱신 + bank_after/card_after에도 반영. body: {updates: [{idx, value}, ...]}"""
    try:
        body = request.get_json(force=True)
        updates = body.get('updates', [])
        if not updates:
            return jsonify({'success': True, 'updated': 0})
        cash_path = Path(CASH_AFTER_PATH).resolve()
        if not cash_path.exists():
            return jsonify({'success': False, 'error': 'cash_after.json 없음'}), 404
        import json as _json
        with open(str(cash_path), 'r', encoding='utf-8') as f:
            records = _json.load(f)
        changed = 0
        bank_updates = []
        card_updates = []
        for u in updates:
            idx = u.get('idx')
            val = u.get('value', '')
            if idx is not None and 0 <= idx < len(records):
                records[idx]['대체구분'] = val
                changed += 1
                row = records[idx]
                source = str(row.get('출처', '')).strip()
                if source == '은행거래':
                    bank_updates.append({'거래일': row.get('거래일', ''), '거래시간': row.get('거래시간', ''), '금융사': row.get('금융사', ''), '입금액': row.get('입금액', 0), '출금액': row.get('출금액', 0), '대체구분': val})
                elif source == '신용카드':
                    card_updates.append({'거래일': row.get('거래일', ''), '거래시간': row.get('거래시간', ''), '금융사': row.get('금융사', ''), '입금액': row.get('입금액', 0), '출금액': row.get('출금액', 0), '대체구분': val})
        import tempfile as _tmpf
        _dir = str(cash_path.parent)
        _fd, _tmp = _tmpf.mkstemp(dir=_dir, suffix='.tmp')
        try:
            with os.fdopen(_fd, 'w', encoding='utf-8') as f:
                _json.dump(records, f, ensure_ascii=False, indent=2)
            os.replace(_tmp, str(cash_path))
        except BaseException:
            try:
                os.unlink(_tmp)
            except OSError:
                pass
            raise
        if _cash_after_cache_obj is not None:
            _cash_after_cache_obj.invalidate()
        _sync_daechae_to_source(bank_updates, card_updates)
        return jsonify({'success': True, 'updated': changed})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


def _sync_daechae_to_source(bank_updates, card_updates):
    """bank_after.json / card_after.json에 대체구분을 동기화."""
    import json as _json

    def _normalize(v):
        try:
            return str(int(float(v))) if v not in (None, '', 'nan') else '0'
        except (ValueError, TypeError):
            return '0'

    def _apply(path, updates, date_col, time_col, inst_col):
        if not updates or not Path(path).exists():
            return
        with open(str(path), 'r', encoding='utf-8') as f:
            recs = _json.load(f)
        for u in updates:
            d, t, inst = str(u['거래일']).strip(), str(u['거래시간']).strip(), str(u['금융사']).strip()
            dep, wit = _normalize(u['입금액']), _normalize(u['출금액'])
            val = u['대체구분']
            for r in recs:
                rd = str(r.get(date_col, '')).strip()
                rt = str(r.get(time_col, '')).strip()
                ri = str(r.get(inst_col, '')).strip()
                rdep = _normalize(r.get('입금액', 0))
                rwit = _normalize(r.get('출금액', 0))
                if rd == d and rt == t and ri == inst and rdep == dep and rwit == wit:
                    r['대체구분'] = val
        import tempfile as _tmpf
        _dir = os.path.dirname(os.path.abspath(str(path)))
        _fd, _tmp = _tmpf.mkstemp(dir=_dir, suffix='.tmp')
        try:
            with os.fdopen(_fd, 'w', encoding='utf-8') as f:
                _json.dump(recs, f, ensure_ascii=False, indent=2)
            os.replace(_tmp, str(path))
        except BaseException:
            try:
                os.unlink(_tmp)
            except OSError:
                pass
            raise

    try:
        _apply(BANK_AFTER_PATH, bank_updates, '거래일', '거래시간', '은행명')
    except Exception:
        pass
    try:
        _apply(CARD_AFTER_PATH, card_updates, '이용일', '이용시간', '카드사')
    except Exception:
        pass


@app.route('/api/generate-category', methods=['POST'])
@ensure_working_directory
def generate_category():
    """cash_after 생성: bank_after + card_after 병합 후 category_table 기반 업종분류·위험도 적용. 임시 파일 쓰고 원자적 교체."""
    try:
        _log_cash_after("API /api/generate-category 호출됨")
        ok, err_msg, count = merge_bank_card_to_cash_after()
        if not ok:
            return jsonify({
                'success': False,
                'error': err_msg or '카테고리 분류 중 오류가 발생했습니다.'
            }), 500
        # 병합 성공 시 파일 재읽기 없이 건수로 즉시 응답 (대용량 시 응답 지연 방지)
        return jsonify({
            'success': True,
            'message': f'카테고리 생성 완료: {count}건',
            'count': count
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/help')
def help():
    """금융정보 도움말 페이지"""
    return render_template('help.html')

if __name__ == '__main__':
    # 현재 디렉토리를 스크립트 위치로 변경
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)
    
    app.run(debug=True, port=5001, host='127.0.0.1')
