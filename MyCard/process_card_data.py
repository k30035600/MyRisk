# -*- coding: utf-8 -*-
"""
신용카드 전처리·분류·저장 (process_card_data.py)

[역할]
- .source/Card 엑셀 → 전처리 → card_before 저장.
- card_before → 계정과목 분류·후처리 → card_after 저장 (card_app에서 호출).

[주요 함수]
- integrate_card_excel(): .source/Card xls/xlsx 읽기·전처리(category_table '전처리'). card_before.json 저장.
- classify_and_save(input_df=None): input_df 없으면 card_before 있으면 로드, 없으면 integrate_card_excel로 df 확보 → 분류·후처리 → card_after.json 저장.
- apply_category_from_merchant(): 가맹점명 기반 계정과목 분류. card_app._create_card_after()에서 before 읽기·후처리·after 저장 시 사용.

[source 읽기·before/after 생성 조건] (은행 process_bank_data와 동일)
- before·after 모두 있음 → source 읽지 않음, 기존 JSON 사용.
- before 없음 → source 읽기 → before·after 생성.
- before만 있음(after 없음) → source 읽지 않음, before 파일에서 로드 후 after만 생성.

[카테고리 규칙]
- 전처리/후처리: 가맹점명·카드사 등 텍스트 치환. 계정과목: 가맹점명 키워드 매칭으로 카테고리 부여.
- 원본: .xls, .xlsx만 취급.
"""
import numpy as np
import pandas as pd
import os
import re
import sys
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.normpath(os.path.join(_SCRIPT_DIR, '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from lib.shared_app_utils import safe_str, clean_amount, setup_win32_utf8
from lib.category_table_io import normalize_주식회사_for_match, safe_write_category_table, load_category_table, normalize_category_df, CATEGORY_TABLE_COLUMNS
from lib.path_config import get_data_dir, get_card_after_path, get_category_table_json_path, get_source_card_dir
from lib.data_json_io import safe_write_data_json, safe_read_data_json
from lib.category_table_defaults import get_default_rules
from lib.category_constants import (
    DEFAULT_CATEGORY, UNCLASSIFIED, UNCLASSIFIED_DEPOSIT, UNCLASSIFIED_WITHDRAWAL,
    CARD_DEFAULT_DEPOSIT, CARD_DEFAULT_WITHDRAWAL, CARD_CASH_PROCESSING,
    CLASS_PRE, CLASS_POST, CLASS_ACCOUNT, DIRECTION_CANCELLED, RISK_CODE_PRIORITY,
)

setup_win32_utf8()

SOURCE_DATA_DIR = os.path.dirname(get_source_card_dir())
SOURCE_CARD_DIR = get_source_card_dir()
CARD_BEFORE_FILE = os.path.join(get_data_dir(), 'card_before.json')
CARD_AFTER_FILE = get_card_after_path()
CATEGORY_TABLE_FILE = get_category_table_json_path()
def _card_before_exists():
    """card_before.json이 존재하고 유효한 데이터가 있으면 True. 없거나 비어 있으면 False. (은행 _bank_before_exists와 동일 조건: size<=2면 빈 JSON으로 간주)"""
    if not CARD_BEFORE_FILE or not os.path.isfile(CARD_BEFORE_FILE):
        return False
    if os.path.getsize(CARD_BEFORE_FILE) <= 2:
        return False
    try:
        df = safe_read_data_json(CARD_BEFORE_FILE, default_empty=True)
        return df is not None and not df.empty
    except Exception:
        return False


# 전처리 오류 메시지 (은행 LAST_INTEGRATE_ERROR와 동일, card_app 등에서 참조 가능)
LAST_INTEGRATE_ERROR = None
# 분류·저장 오류 메시지 (은행 LAST_CLASSIFY_ERROR와 동일)
LAST_CLASSIFY_ERROR = None
# card_before.xlsx 컬럼 (추출 시 이용금액 사용 → 저장 전 입금액/출금액/취소로 변환)
_EXTRACT_COLUMNS = [
    '카드사', '카드번호', '이용일', '이용시간', '이용금액', '가맹점명', '사업자번호', '폐업', '취소여부'
]
CARD_BEFORE_COLUMNS = [
    '카드사', '카드번호', '이용일', '이용시간', '입금액', '출금액', '취소', '가맹점명', '사업자번호', '폐업'
]
EXCEL_EXTENSIONS = ('*.xls', '*.xlsx')
SEARCH_COLUMNS = ['적요', '내용', '거래점', '송금메모', '가맹점명']
# .source 헤더명 → card_before.xlsx 표준 컬럼 (카테고리는 category_table 신용카드 규칙으로 분류)
# 헤더 행에서 인덱스를 취득하고, 다음 헤더 행이 나올 때까지 해당 인덱스로 매핑
HEADER_TO_STANDARD = {
    '카드사': ['카드사', '카드명'],
    '카드번호': ['카드번호'],
    '이용일': ['이용일', '이용일자', '승인일', '승인일자', '거래일', '거래일자', '매출일', '매출일자', '확정일', '확정일자'],
    '이용시간': ['이용시간', '승인시간', '거래시간', '승인시각', '이용시각'],
    '이용금액': ['이용금액', '승인금액', '매출금액', '거래금액'],
    '취소여부': ['취소여부', '취소'],
    '가맹점명': ['가맹점명', '이용처', '승인가맹점'],
    '사업자번호': ['사업자번호', '가맹점사업자번호', '가맹점 사업자번호', '사업자등록번호'],
    # 할부 컬럼은 사용하지 않음. 구분은 과세유형 '폐업'일 때만 '폐업' 저장 (아래 과세유형_헤더키워드로 처리)
}
과세유형_헤더키워드 = '과세유형'
# 금액 컬럼으로 간주할 헤더 키워드 (포함 시 숫자로 변환)
AMOUNT_COLUMN_KEYWORDS = ('금액', '입금', '출금', '잔액')

def normalize_brackets(text):
    """괄호 쌍 정규화: (( → (, )) → (, 불균형 시 보정."""
    if not text:
        return text
    text = text.replace('((', '(')
    text = text.replace('))', ')')
    open_count = text.count('(')
    close_count = text.count(')')
    if open_count > close_count:
        text = text + ')' * (open_count - close_count)
    elif close_count > open_count:
        text = '(' * (close_count - open_count) + text
    return text


def remove_numbers(text):
    """문자열에서 숫자 제거."""
    if not text:
        return text
    return re.sub(r'\d+', '', text)


def _business_number_digits(value):
    """사업자번호 셀 값에서 숫자만 추출(10자리). Excel 숫자형(1234567890.0)·9자리(앞 0 제거) 보정."""
    if pd.isna(value) or value == '':
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        n = int(float(value))
        if n < 0 or n >= 10 ** 10:
            return None
        return str(n).zfill(10) if n < 10 ** 9 else str(n)
    s = str(value).strip()
    digits = re.sub(r'\D', '', s)
    if len(digits) == 8:
        return digits.zfill(10)
    if len(digits) == 9:
        return digits.zfill(10)
    if len(digits) == 10:
        return digits
    return None


def _normalize_business_number(value):
    """사업자번호를 000-00-00000 형식으로만 정규화. card_before에는 이 형식만 저장(신한 숫자형·9자리 보정)."""
    digits = _business_number_digits(value)
    if digits is None:
        return ''
    return f'{digits[:3]}-{digits[3:5]}-{digits[5:]}'


def _normalize_구분(val):
    """구분(할부)을 숫자(int) 또는 일시불('')로 정규화. 0/일시불 → '', 3/6/12 등 → int. '3개월' 등에서 숫자만 추출."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ''
    s = str(val).strip()
    if s in ('', '0', '일시불'):
        return ''
    try:
        n = int(float(val))
        return '' if n == 0 else n
    except (TypeError, ValueError):
        pass
    m = re.match(r'^(\d+)', s)
    if m:
        n = int(m.group(1))
        return '' if n == 0 else n
    return ''


def _card_excel_files(source_dir):
    """Source 루트 폴더에서만 .xls, .xlsx 파일 목록 수집."""
    out = []
    if not source_dir.exists():
        return out
    for ext in EXCEL_EXTENSIONS:
        out.extend(source_dir.glob(ext))
    return sorted(set(out), key=lambda p: (str(p), p.name))


def _amount_columns_to_numeric(df):
    """컬럼명에 금액·입금·출금·잔액이 포함된 컬럼을 숫자형으로 변환."""
    for col in df.columns:
        if any(kw in str(col) for kw in AMOUNT_COLUMN_KEYWORDS):
            df[col] = df[col].map(clean_amount)
    return df


def _card_company_from_filename(file_name):
    """파일명에서 카드사명 취득. 첫 '_' 앞 부분 또는 확장자 제거한 이름."""
    stem = Path(file_name).stem.strip()
    if not stem:
        return ''
    if '_' in stem:
        return stem.split('_')[0].strip()
    return stem


def _normalize_header_string(s):
    """헤더 문자열 정규화 (공백·BOM·줄바꿈 통일)."""
    if pd.isna(s) or s == '':
        return ''
    sh = str(s).strip().strip('\ufeff\ufffe').replace('\n', ' ').replace('\r', ' ')
    return re.sub(r'\s+', ' ', sh).strip()


def _map_source_header_to_standard(source_header):
    """Source 엑셀 헤더명 → card_before 표준 컬럼 (카테고리는 category_table 신용카드 규칙으로 채움)."""
    sh = _normalize_header_string(source_header)
    if not sh:
        return None
    sh_compact = sh.replace(' ', '')
    for std_col, keywords in HEADER_TO_STANDARD.items():
        for kw in keywords:
            kw_c = kw.replace(' ', '')
            if kw_c in sh_compact or sh_compact in kw_c or kw in sh or sh in kw:
                return std_col
    return None


# .source에서 헤더로 쓰이는 문자열 집합 (헤더인 행 판별용)
_HEADER_LIKE_STRINGS = None


def _get_header_like_strings():
    """HEADER_TO_STANDARD 키워드 + 표준 컬럼명 + 과세유형(헤더 행 판별용)."""
    global _HEADER_LIKE_STRINGS
    if _HEADER_LIKE_STRINGS is not None:
        return _HEADER_LIKE_STRINGS
    s = set(_EXTRACT_COLUMNS) | set(CARD_BEFORE_COLUMNS)
    for keywords in HEADER_TO_STANDARD.values():
        for kw in keywords:
            s.add(str(kw).strip())
    s.add(과세유형_헤더키워드)  # 신한카드 등 '과세유형' 있는 행을 헤더로 인식
    _HEADER_LIKE_STRINGS = s
    return s


def _looks_like_header_row(row, columns):
    """행이 헤더 행인지 판별. columns: 검사할 컬럼 인덱스/키 iterable (source_columns 또는 range(num_cols))."""
    header_set = _get_header_like_strings()
    match_count = 0
    non_empty = 0
    for c in columns:
        val = row.get(c, row.get(str(c)))
        if pd.isna(val) or str(val).strip() == '':
            continue
        non_empty += 1
        cell = str(val).strip()
        if cell in header_set:
            match_count += 1
        else:
            for kw in header_set:
                if kw in cell or cell in kw:
                    match_count += 1
                    break
    if non_empty == 0:
        return False
    return match_count >= 2 and match_count >= non_empty * 0.5


def _build_mapping_from_header_row(row):
    """헤더 행에서 컬럼 인덱스 → 표준 컬럼 매핑 구함. 과세유형 컬럼 인덱스도 반환(폐업→구분 저장용)."""
    idx_to_std = {}
    idx_과세유형 = None
    for i in row.index:
        try:
            col_idx = int(i)
        except (TypeError, ValueError):
            continue
        val = row.get(i, row.get(str(i)))
        raw = _normalize_header_string(val)
        # 전각/공백 제거 후 '과세유형' 포함 여부로 컬럼 인덱스 저장 (신한카드 등)
        if raw:
            raw_compact = _normalize_fullwidth(raw).replace(' ', '')
            if 과세유형_헤더키워드 in raw_compact:
                idx_과세유형 = col_idx
        std_col = _map_source_header_to_standard(val)
        if std_col:
            idx_to_std[col_idx] = std_col
    return (idx_to_std, idx_과세유형)


def _row_as_dict(row_tuple, num_cols):
    """itertuples() 결과를 row.get(i)/row.index 호환 dict로 변환. header=None이면 _0,_1,_2,… (0-based)."""
    d = {}
    for i in range(num_cols):
        v = getattr(row_tuple, '_' + str(i), None)
        if v is None:
            v = getattr(row_tuple, '_' + str(i + 1), None)
        d[i] = v
    d['index'] = list(range(num_cols))

    class RowLike:
        __slots__ = ('_d', 'index')

        def get(self, i, default=None):
            return self._d.get(i, self._d.get(str(i), default))

    r = RowLike()
    r._d = d
    r.index = d['index']
    return r


def _row_from_mapping(row, idx_to_std, card_company_from_file, idx_과세유형=None):
    """인덱스 매핑으로 한 행을 추출용 컬럼 dict로 변환. 카드사는 파일명에서. 구분은 할부 미사용, 과세유형 '폐업'일 때만 '폐업' 저장."""
    new_row = {col: '' for col in _EXTRACT_COLUMNS}
    for i in sorted(idx_to_std.keys()):
        std_col = idx_to_std[i]
        if new_row[std_col]:
            continue
        val = row.get(i, row.get(str(i)))
        if pd.notna(val) and str(val).strip() != '':
            if std_col == '이용일' and not _is_date_like_value(val):
                # 신한카드: 데이터 행 맨 앞 순번 컬럼(1,2,3…)인 경우 인접 컬럼(거래일) 사용
                alt = row.get(i + 1, row.get(str(i + 1)))
                if pd.notna(alt) and str(alt).strip() != '' and _is_date_like_value(alt):
                    new_row['이용일'] = str(alt).strip()
                continue
            new_row[std_col] = str(val).strip()
    if idx_과세유형 is not None:
        v = row.get(idx_과세유형, row.get(str(idx_과세유형)))
        if pd.notna(v):
            v_norm = _normalize_fullwidth(str(v).strip())
            if v_norm == '폐업' or '폐업' in v_norm:
                new_row['폐업'] = '폐업'
    if card_company_from_file:
        new_row['카드사'] = card_company_from_file
    return _normalize_row_values(new_row)


def _normalize_fullwidth(val):
    """전각(Fullwidth) 문자 → 반각(Halfwidth) 변환 (예: ＳＫＴ５３２２ → SKT5322)."""
    if pd.isna(val) or val == '':
        return val
    return unicodedata.normalize('NFKC', str(val).strip())

def _normalize_row_values(new_row):
    """표준 행의 이용금액·사업자번호·폐업·이용일 값을 정규화."""
    for col in ['카드사', '카드번호', '가맹점명']:
        if new_row.get(col):
            new_row[col] = _normalize_fullwidth(new_row[col])
    for col in _EXTRACT_COLUMNS:
        if col == '이용금액' and new_row.get(col) and str(new_row[col]).replace(',', '').replace('-', '').strip():
            try:
                new_row[col] = clean_amount(new_row[col])
            except (TypeError, ValueError):
                pass
        elif col == '사업자번호' and new_row.get(col):
            new_row[col] = _normalize_business_number(new_row[col])
        elif col == '폐업':
            # 폐업은 과세유형 '폐업'일 때만 '폐업'. 할부 컬럼은 사용하지 않으므로 그 외는 공백 유지
            if str(new_row.get(col, '')).strip() != '폐업':
                new_row[col] = ''
        elif col == '이용일' and new_row.get(col):
            date_part, time_part = _split_datetime_value(new_row[col])
            new_row[col] = _normalize_date_value(date_part) if date_part else _normalize_date_value(new_row[col])
            if time_part and not (new_row.get('이용시간') and str(new_row.get('이용시간', '')).strip()):
                new_row['이용시간'] = _normalize_time_value(time_part)
    return new_row


def _normalize_date_value(val):
    """이용일 값을 YYYY-MM-DD 형식으로 정규화."""
    if pd.isna(val) or val == '' or (isinstance(val, str) and not str(val).strip()):
        return str(val).strip() if val else ''
    try:
        if hasattr(val, 'strftime'):
            return val.strftime('%Y-%m-%d')
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            n = int(float(val))
            if n >= 1000:
                base = datetime(1899, 12, 30)
                return (base + timedelta(days=n)).strftime('%Y-%m-%d')
            return str(val).strip()
        s = str(val).strip()
        if re.match(r'^\d{4}-\d{2}-\d{2}', s):
            return s[:10]
        if '/' in s or '-' in s or ('.' in s and re.match(r'^\d{4}\.\d', s)):
            parts = re.split(r'[/\-.]', s)
            if len(parts) >= 3:
                a, b, c = [x.zfill(2) for x in parts[:3]]
                if len(a) == 2:
                    y = int(a)
                    year = (2000 + y) if y < 50 else (1900 + y)
                    return f'{year}-{b}-{c}'
                return f'{a}-{b}-{c}' if len(a) == 4 else s
        return s
    except (TypeError, ValueError):
        return str(val).strip()


def _split_datetime_value(val):
    """이용일 컬럼에 'yy/mm/dd'만 있거나 'yy/mm/dd hh:mm:ss' 등이 섞인 경우 날짜/시간 분리.
    반환: (date_str, time_str). 시간이 없으면 time_str은 ''."""
    if pd.isna(val) or val == '' or (isinstance(val, str) and not str(val).strip()):
        return ('', '')
    s = str(val).strip()
    if not s:
        return ('', '')
    # 공백 또는 T로 구분된 날짜+시간 패턴
    if ' ' in s:
        parts = s.split(None, 1)
        if len(parts) == 2 and re.search(r'\d{1,2}:\d{1,2}', parts[1]):
            return (parts[0].strip(), parts[1].strip())
    if 'T' in s and re.search(r'\d{1,2}:\d{1,2}', s):
        idx = s.index('T')
        return (s[:idx].strip(), s[idx + 1:].strip())
    return (s, '')


def _normalize_time_value(val):
    """시간 문자열을 hh:mm 또는 hh:mm:ss 형식으로 정규화."""
    if pd.isna(val) or val == '' or (isinstance(val, str) and not str(val).strip()):
        return ''
    s = str(val).strip()
    m = re.match(r'^(\d{1,2}):(\d{1,2})(?::(\d{1,2}))?', s)
    if m:
        h, mi = m.group(1).zfill(2), m.group(2).zfill(2)
        sec = m.group(3)
        if sec is not None:
            return f'{h}:{mi}:{sec.zfill(2)}'
        return f'{h}:{mi}:00'
    return s


def _is_date_like_value(val):
    """이용일로 쓸 만한 값인지 판별. 0/1 같은 코드·순번은 False."""
    if pd.isna(val) or val == '':
        return False
    s = str(val).strip()
    if not s:
        return False
    if hasattr(val, 'strftime'):
        return True
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        n = int(float(val))
        if n < 1000:  # Excel serial이 아닌 작은 숫자(코드/순번)
            return False
        return True
    # 문자열: 슬래시·하이픈 포함이면 날짜 형식 (25/12/09, 2025-12-09 등)
    if '/' in s or '-' in s:
        return True
    # 현대카드 등 yyyy.mm.dd 형식 (1.0 같은 순번 제외)
    if '.' in s and re.match(r'^\d{4}\.\d', s):
        return True
    if s.isdigit() and int(s) < 1000:
        return False
    return True


def _row_to_standard_columns(row, source_columns):
    """.source 한 행(Series)을 추출용 컬럼 dict로 변환."""
    new_row = {col: '' for col in _EXTRACT_COLUMNS}
    for src_col in source_columns:
        std_col = _map_source_header_to_standard(src_col)
        if std_col is None:
            continue
        val = row.get(src_col, row.get(str(src_col)))
        if pd.notna(val) and str(val).strip() != '':
            if not new_row[std_col]:
                # 이용일은 날짜 형태인 값만 채움 (0/1/71 등은 매출일·이용일자 등이 덮어쓰도록 건너뜀)
                if std_col == '이용일' and not _is_date_like_value(val):
                    continue
                new_row[std_col] = str(val).strip()
    return _normalize_row_values(new_row)


def _extract_rows_from_sheet(df, card_company_from_file):
    """시트 DataFrame에서 추출용 행 리스트 추출 (이용금액 포함)."""
    rows = []
    num_cols = len(df.columns)
    idx_to_std = None
    idx_과세유형 = None
    for row_tuple in df.itertuples(index=False):
        row = _row_as_dict(row_tuple, num_cols)
        if all(pd.isna(row.get(i, None)) or str(row.get(i, '')).strip() == '' for i in range(num_cols)):
            continue
        if idx_to_std is None:
            idx_to_std, idx_과세유형 = _build_mapping_from_header_row(row)
            continue
        if _looks_like_header_row(row, range(num_cols)):
            new_map, new_과세 = _build_mapping_from_header_row(row)
            for idx, std_col in list(idx_to_std.items()):
                if idx not in new_map:
                    new_map[idx] = std_col
            idx_to_std = new_map
            idx_과세유형 = new_과세 if new_과세 is not None else idx_과세유형
            continue
        new_row = _row_from_mapping(row, idx_to_std, card_company_from_file, idx_과세유형)
        if all(not v or (isinstance(v, str) and not str(v).strip()) for v in new_row.values()):
            continue
        card_no = new_row.get('카드번호', '')
        if not card_no or (isinstance(card_no, str) and not str(card_no).strip()):
            continue
        rows.append(new_row)
    return rows


def _load_prepost_rules(category_path=None):
    """category_table.json에서 전처리/후처리 규칙만 로드 (data 폴더). 반환: (전처리_list, 후처리_list), 각 항목은 {'키워드': str, '카테고리': str}."""
    path = Path(category_path or os.path.join(PROJECT_ROOT, 'data', 'category_table.json'))
    if not path.exists():
        return [], []
    try:
        full = load_category_table(str(path), default_empty=True)
        if full is None or full.empty:
            return [], []
        full = normalize_category_df(full).fillna('')
        full.columns = [str(c).strip() for c in full.columns]
        if '분류' not in full.columns or '키워드' not in full.columns or '카테고리' not in full.columns:
            return [], []
        전처리 = []
        후처리 = []
        for _, row in full.iterrows():
            분류 = str(row.get('분류', '')).strip()
            키워드 = str(row.get('키워드', '')).strip()
            카테고리 = str(row.get('카테고리', '')).strip()
            if not 키워드:
                continue
            if 분류 == CLASS_PRE:
                전처리.append({'키워드': 키워드, '카테고리': 카테고리})
            elif 분류 == CLASS_POST:
                후처리.append({'키워드': 키워드, '카테고리': 카테고리})
        # 긴 키워드 먼저 적용 (부분 치환 방지)
        전처리.sort(key=lambda x: len(x['키워드']), reverse=True)
        후처리.sort(key=lambda x: len(x['키워드']), reverse=True)
        return 전처리, 후처리
    except (OSError, ValueError, KeyError, TypeError) as e:
        print(f"전처리/후처리 규칙 로드 실패: {e}", flush=True)
        return [], []


def _apply_rules_to_columns(df, columns_to_apply, rule_list):
    """지정 규칙 리스트만 컬럼에 적용 (전처리 또는 후처리). 키워드가 등장하는 부분을 카테고리로 치환(셀 전체가 키워드여도 치환)."""
    if df is None or df.empty or not columns_to_apply or not rule_list:
        return df
    df = df.copy()
    for col in columns_to_apply:
        if col not in df.columns:
            continue
        df[col] = df[col].fillna('').astype(str).apply(lambda v: safe_str(v))
    for col in columns_to_apply:
        if col not in df.columns:
            continue
        for rule in rule_list:
            kw = rule['키워드']
            cat = rule['카테고리']
            if not kw:
                continue
            kw_norm = normalize_주식회사_for_match(kw)
            if not kw_norm:
                continue
            df[col] = df[col].fillna('').astype(str).str.replace(kw_norm, cat, regex=False)
    return df


def _apply_전처리_only_to_columns(df, columns_to_apply, preloaded_rules=None):
    """card_before 저장 전 전처리만 적용 (가맹점명·카드사 등)."""
    if preloaded_rules is not None:
        전처리 = preloaded_rules
    else:
        전처리, _ = _load_prepost_rules()
    return _apply_rules_to_columns(df, columns_to_apply, 전처리 or [])


def _apply_후처리_only_to_columns(df, columns_to_apply, preloaded_rules=None):
    """card_after 생성 전 후처리만 적용 (가맹점명·카드사 등)."""
    if preloaded_rules is not None:
        후처리 = preloaded_rules
    else:
        _, 후처리 = _load_prepost_rules()
    return _apply_rules_to_columns(df, columns_to_apply, 후처리 or [])


def _postprocess_combined_df(df):
    """통합 DataFrame 후처리: 가맹점명 채우기. 구분은 할부 미사용, '폐업'만 유지."""
    if df.empty:
        return df
    required = ['카드사', '카드번호', '이용일', '이용금액', '가맹점명']
    if all(c in df.columns for c in required):
        empty_merchant = (df['가맹점명'].fillna('').astype(str).str.strip() == '')
        has_card = (
            df['카드사'].notna() & (df['카드사'].astype(str).str.strip() != '') &
            df['카드번호'].notna() & (df['카드번호'].astype(str).str.strip() != '') &
            df['이용일'].notna() & (df['이용일'].astype(str).str.strip() != '') &
            df['이용금액'].notna() & empty_merchant
        )
        df.loc[has_card, '가맹점명'] = df.loc[has_card, '카드사']
        sh_mask = (
            df['카드사'].fillna('').astype(str).str.strip().str.contains('신한', na=False) &
            (df['가맹점명'].fillna('').astype(str).str.strip() == '신한카드')
        )
        df.loc[sh_mask, '가맹점명'] = '신한카드_카드론'
    # 폐업: 할부 미사용. 과세유형 '폐업'만 '폐업' 유지, 그 외는 모두 공백
    if '폐업' in df.columns:
        df['폐업'] = df['폐업'].apply(
            lambda v: '폐업' if v is not None and str(v).strip() == '폐업' else ''
        )
    return df


def integrate_card_excel(output_file=None, base_dir=None, skip_write=False):
    """MyRisk/.source/Card 의 카드 엑셀(xls, xlsx)을 읽어 전처리 후 data/card_before.json 생성.

    은행(integrate_bank_transactions)과 동일: 저장 경로는 항상 CARD_BEFORE_FILE, 데이터 유무와 관계없이 저장.
    - 테이블 헤더: 카드사, 카드번호, 이용일, 이용시간, 입금액, 출금액, 취소, 가맹점명, 사업자번호, 폐업
    - skip_write=True 이면 파일 쓰지 않고 DataFrame만 반환 (카드 앱 전처리전 조회용).
    - output_file, base_dir: 은행과 동일하게 미사용. 항상 data/card_before.json에 저장.
    """
    global LAST_INTEGRATE_ERROR
    LAST_INTEGRATE_ERROR = None
    source_dir = Path(SOURCE_CARD_DIR)
    read_errors = []

    all_rows = []
    for file_path in _card_excel_files(source_dir):
        name = file_path.name
        suf = file_path.suffix.lower()
        card_company_from_file = _card_company_from_filename(name)
        try:
            engine = 'xlrd' if suf == '.xls' else 'openpyxl'
            xls = pd.ExcelFile(file_path, engine=engine)
            for sheet_name in xls.sheet_names:
                try:
                    df = pd.read_excel(file_path, sheet_name=sheet_name, header=None, engine=engine)
                    if df is not None and not df.empty:
                        all_rows.extend(_extract_rows_from_sheet(df, card_company_from_file))
                except Exception as e:
                    read_errors.append(f"{name} 시트 '{sheet_name}': {e}")
                    print(f"오류: {name} 시트 '{sheet_name}' 읽기 실패 - {e}")
        except Exception as e:
            read_errors.append(f"{name}: {e}")
            print(f"오류: {name} 처리 실패 - {e}")

    card_files = _card_excel_files(source_dir)
    if not card_files:
        if source_dir.exists():
            all_xls = list(source_dir.glob('*.xls')) + list(source_dir.glob('*.xlsx'))
            if all_xls:
                LAST_INTEGRATE_ERROR = "파일을 읽었으나 추출된 데이터가 없습니다. 시트 구조·헤더를 확인하세요."
            else:
                LAST_INTEGRATE_ERROR = ".source/Card 폴더에 .xls, .xlsx 파일이 없습니다."
        else:
            LAST_INTEGRATE_ERROR = ".source/Card 폴더를 찾을 수 없습니다."
    elif not all_rows and read_errors:
        LAST_INTEGRATE_ERROR = ' | '.join(read_errors[:5]) + (' ...' if len(read_errors) > 5 else '')
    elif not all_rows:
        LAST_INTEGRATE_ERROR = "파일을 읽었으나 데이터 행이 없거나 시트 구조가 맞지 않습니다."

    extract_df = pd.DataFrame(all_rows, columns=_EXTRACT_COLUMNS) if all_rows else pd.DataFrame(columns=_EXTRACT_COLUMNS)
    extract_df = _postprocess_combined_df(extract_df)

    # 이용금액 → 입금액/출금액/취소 변환 (card_before 저장용)
    # - 취소여부 "Y"/"취소" → 취소, 입금액=절대값, 출금액=0
    # - 신한카드(취소여부 컬럼 없음) + 이용금액 음수 → 취소로 간주
    # - 그 외 음수 → 포인트/할인(입금): 취소 없음, 입금액=절대값, 출금액=0
    if extract_df.empty:
        combined_df = pd.DataFrame(columns=CARD_BEFORE_COLUMNS)
    else:
        if '이용금액' in extract_df.columns:
            amt = pd.to_numeric(extract_df['이용금액'], errors='coerce').fillna(0)
            has_cancel_col = '취소여부' in extract_df.columns
            if has_cancel_col:
                cancel_flag = extract_df['취소여부'].astype(str).str.strip()
                is_cancel_by_flag = (cancel_flag.str.upper() == 'Y') | (cancel_flag == DIRECTION_CANCELLED)
            else:
                is_cancel_by_flag = pd.Series(False, index=extract_df.index)
            # 신한카드: 취소여부 없을 때만 음수면 취소
            is_cancel_shinhan = ~has_cancel_col & (amt < 0)
            is_cancel = is_cancel_by_flag | is_cancel_shinhan
            # 입금액: 취소면 절대값, 취소 아닌데 음수면 포인트/할인 절대값, 나머지 0
            extract_df['취소'] = np.where(is_cancel, DIRECTION_CANCELLED, '')
            # 취소 컬럼은 문자만: 0/NaN이 들어가지 않도록 문자열로 통일 (Excel에 0으로 보이는 것 방지)
            extract_df['취소'] = extract_df['취소'].astype(str).replace('nan', '').replace('0', '')
            extract_df['입금액'] = np.where(is_cancel, amt.abs(), np.where(amt < 0, amt.abs(), 0))
            extract_df['출금액'] = np.where(is_cancel, 0, np.where(amt > 0, amt, 0))
            extract_df = extract_df.drop(columns=['이용금액'], errors='ignore')
            extract_df = extract_df.drop(columns=['취소여부'], errors='ignore')
        else:
            if '입금액' not in extract_df.columns:
                extract_df['입금액'] = 0
            if '출금액' not in extract_df.columns:
                extract_df['출금액'] = 0
            if '취소' not in extract_df.columns:
                extract_df['취소'] = ''
        combined_df = extract_df[[c for c in CARD_BEFORE_COLUMNS if c in extract_df.columns]].reindex(columns=CARD_BEFORE_COLUMNS).copy()

        # 이용시간 없으면 00:00:00으로 채움
        if '이용시간' in combined_df.columns:
            def _fill_이용시간(v):
                if v is None or (isinstance(v, float) and pd.isna(v)): return '00:00:00'
                s = str(v).strip()
                return '00:00:00' if not s else s
            combined_df['이용시간'] = combined_df['이용시간'].apply(_fill_이용시간)

        # 가맹점명 "신한카드_카드론": 출금액(상환)을 입금액으로 옮기고 출금액 0
        if '가맹점명' in combined_df.columns and '입금액' in combined_df.columns and '출금액' in combined_df.columns:
            cardron = (combined_df['가맹점명'].fillna('').astype(str).str.strip() == '신한카드_카드론')
            if cardron.any():
                combined_df.loc[cardron, '입금액'] = combined_df.loc[cardron, '출금액']
                combined_df.loc[cardron, '출금액'] = 0

        # 전처리: before.xlsx 저장 전에 수행 (가맹점명·카드사 치환)
        try:
            combined_df = _apply_전처리_only_to_columns(combined_df, ['가맹점명', '카드사'])
        except Exception as e:
            # 전처리 규칙 적용 실패 시 원본으로 저장
            print(f"경고: 전처리 적용 중 오류(무시하고 저장) - {e}")
        # card_before.xlsx 저장 시 입금액은 절대값으로 보장
        if '입금액' in combined_df.columns:
            combined_df['입금액'] = pd.to_numeric(combined_df['입금액'], errors='coerce').fillna(0).abs()

    # 은행과 동일: 저장 경로는 항상 CARD_BEFORE_FILE. 데이터 유무와 관계없이 저장 (skip_write면 저장 생략)
    if not skip_write:
        try:
            out_path = Path(CARD_BEFORE_FILE).resolve()
            out_path.parent.mkdir(parents=True, exist_ok=True)
            if safe_write_data_json(str(out_path), combined_df):
                print(f"저장: {out_path}", flush=True)
        except Exception as e:
            print(f"오류: {CARD_BEFORE_FILE} 저장 실패 - {e}", file=sys.stderr, flush=True)
    return combined_df


def _apply_카드사_사업자번호_기본값(df):
    """신한카드/하나카드 이면서 사업자번호 없으면 기본값 저장 (card_after용)."""
    if df.empty or '카드사' not in df.columns or '사업자번호' not in df.columns:
        return
    empty_biz = (df['사업자번호'].fillna('').astype(str).str.strip() == '')
    shinhan = df['카드사'].fillna('').astype(str).str.strip().str.contains('신한', case=False, na=False)
    hana = df['카드사'].fillna('').astype(str).str.strip().str.contains('하나', case=False, na=False)
    if (empty_biz & shinhan).any():
        df.loc[empty_biz & shinhan, '사업자번호'] = '202-81-48079'
    if (empty_biz & hana).any():
        df.loc[empty_biz & hana, '사업자번호'] = '104-86-56659'


def _fill_time_card(v):
    """이용시간 값이 비어 있으면 '00:00:00' 반환 (card_after 저장용)."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return '00:00:00'
    s = str(v).strip()
    return '00:00:00' if not s else s


def _normalize_cancel_value_card(v, empty_means_cancel_only=False):
    """취소 컬럼 값 정규화: 0/nan → '', '취소' 포함 시 '취소'."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ''
    s = str(v).strip()
    if s in ('', '0', '0.0', 'nan'):
        return ''
    if empty_means_cancel_only:
        return DIRECTION_CANCELLED if s else ''
    return DIRECTION_CANCELLED if DIRECTION_CANCELLED in s else s


def classify_and_save(input_df=None):
    """card_before → 계정과목 분류·후처리 → card_after.json 저장. 은행 classify_and_save와 동일하게 한 모듈에서 처리.

    input_df 없으면: card_before 있으면 로드, 없으면 integrate_card_excel()로 확보 후 분류·저장. (은행과 동일 조건)
    Returns: (success: bool, error: Optional[str], count: int). 실패 시 LAST_CLASSIFY_ERROR에 오류 메시지 설정.
    """
    global LAST_CLASSIFY_ERROR
    LAST_CLASSIFY_ERROR = None
    try:
        if input_df is not None and not input_df.empty:
            df_card = input_df.copy()
        else:
            if _card_before_exists():
                try:
                    df_card = safe_read_data_json(CARD_BEFORE_FILE, default_empty=True)
                except Exception:
                    df_card = None
            else:
                df_card = None
            if df_card is None or df_card.empty:
                df_card = integrate_card_excel(skip_write=False)
            if df_card is None or df_card.empty:
                err = 'card_after를 만들 수 없습니다. MyRisk/.source/Card에 .xls/.xlsx 파일을 넣은 뒤 다시 시도하세요.'
                LAST_CLASSIFY_ERROR = err
                return (False, err, 0)

        df_card.columns = [str(c).strip() for c in df_card.columns]
        if not df_card.empty and '할부' in df_card.columns and '폐업' not in df_card.columns:
            df_card = df_card.rename(columns={'할부': '폐업'})

        out_dir = os.path.dirname(CARD_AFTER_FILE)
        if out_dir and not os.path.exists(out_dir):
            os.makedirs(out_dir, exist_ok=True)
        had_category_file = Path(CATEGORY_TABLE_FILE).exists() if CATEGORY_TABLE_FILE else False

        # 가맹점명 보정: 공란이면 카드사, 신한카드→신한카드_카드론
        if not df_card.empty and all(c in df_card.columns for c in ['카드사', '카드번호', '가맹점명']):
            has_amt = ('입금액' in df_card.columns and df_card['입금액'].notna().any()) or ('출금액' in df_card.columns and df_card['출금액'].notna().any())
            if has_amt:
                has_card = (
                    (df_card['카드사'].fillna('').astype(str).str.strip() != '') &
                    (df_card['카드번호'].fillna('').astype(str).str.strip() != '') &
                    (df_card['가맹점명'].fillna('').astype(str).str.strip() == '')
                )
                df_card.loc[has_card, '가맹점명'] = df_card.loc[has_card, '카드사']
            sh_merchant = (
                df_card['카드사'].fillna('').astype(str).str.strip().str.contains('신한', na=False) &
                (df_card['가맹점명'].fillna('').astype(str).str.strip() == '신한카드')
            )
            if sh_merchant.any():
                df_card.loc[sh_merchant, '가맹점명'] = '신한카드_카드론'

        _apply_카드사_사업자번호_기본값(df_card)

        if '카테고리' not in df_card.columns:
            df_card['카테고리'] = ''
        if '입금액' in df_card.columns:
            입금 = pd.to_numeric(df_card['입금액'], errors='coerce').fillna(0) > 0
            if 입금.any():
                df_card.loc[입금, '카테고리'] = CARD_CASH_PROCESSING

        if had_category_file and CATEGORY_TABLE_FILE:
            try:
                full = load_category_table(CATEGORY_TABLE_FILE, default_empty=True)
                if full is not None and not full.empty:
                    df_cat = normalize_category_df(full)
                    if not df_cat.empty:
                        df_card = apply_category_from_merchant(df_card, df_cat)
                        # 카드거래: 신청인본인 구분 없음 (적용하지 않음)
            except Exception as _e:
                print(f"[WARN] 카테고리 로드/적용 실패 (원본으로 저장): {_e}", flush=True)

        df_card = _apply_후처리_only_to_columns(df_card, ['가맹점명', '카드사'])

        if '카테고리' not in df_card.columns:
            df_card['카테고리'] = ''
        else:
            df_card['카테고리'] = df_card['카테고리'].fillna('').astype(str).str.strip()
        _입금 = pd.to_numeric(df_card['입금액'].fillna(0).astype(str).str.replace(',', ''), errors='coerce').fillna(0) if '입금액' in df_card.columns else pd.Series(0, index=df_card.index)
        _출금 = pd.to_numeric(df_card['출금액'].fillna(0).astype(str).str.replace(',', ''), errors='coerce').fillna(0) if '출금액' in df_card.columns else pd.Series(0, index=df_card.index)
        _is_deposit = (_입금 > 0) & (_출금 == 0)
        # 키워드 매칭된 미분류 → 미분류입금/미분류출금
        _미분류_mask = df_card['카테고리'].isin([UNCLASSIFIED, UNCLASSIFIED_WITHDRAWAL, UNCLASSIFIED_DEPOSIT])
        if _미분류_mask.any():
            df_card.loc[_미분류_mask & _is_deposit, '카테고리'] = UNCLASSIFIED_DEPOSIT
            df_card.loc[_미분류_mask & ~_is_deposit, '카테고리'] = UNCLASSIFIED_WITHDRAWAL
        _기타_mask = df_card['카테고리'].isin(['', DEFAULT_CATEGORY])
        if _기타_mask.any():
            df_card.loc[_기타_mask & _is_deposit, '카테고리'] = CARD_DEFAULT_DEPOSIT
            df_card.loc[_기타_mask & ~_is_deposit, '카테고리'] = CARD_DEFAULT_WITHDRAWAL

        if not df_card.empty and '카드번호' in df_card.columns:
            def _card_no_str(v):
                if isinstance(v, float) and v == int(v):
                    return str(int(v))
                return str(v).strip()
            df_card = df_card[df_card['카드번호'].apply(_card_no_str).str.len() > 16]
        if not df_card.empty:
            time_cols = [c for c in df_card.columns if '시간' in str(c) and c != '이용시간']
            if time_cols:
                df_card = df_card.drop(columns=time_cols, errors='ignore')
            for col in ['이용일', '거래일']:
                if col in df_card.columns:
                    ser = pd.to_datetime(df_card[col], errors='coerce')
                    df_card[col] = ser.dt.strftime('%Y-%m-%d').where(ser.notna(), df_card[col])
        if '키워드' not in df_card.columns:
            df_card['키워드'] = ''
        else:
            df_card['키워드'] = df_card['키워드'].fillna('').astype(str).str.strip()
        if not df_card.empty and '폐업' in df_card.columns:
            df_card['폐업'] = df_card['폐업'].apply(
                lambda v: '폐업' if v is not None and str(v).strip() == '폐업' else ''
            )
        if not df_card.empty:
            if '이용시간' not in df_card.columns:
                df_card['이용시간'] = '00:00:00'
            else:
                df_card['이용시간'] = df_card['이용시간'].apply(_fill_time_card)
            if '취소' not in df_card.columns:
                df_card['취소'] = ''
        if not df_card.empty and '취소' in df_card.columns:
            df_card['취소'] = df_card['취소'].apply(lambda v: _normalize_cancel_value_card(v, empty_means_cancel_only=False))

        card_after_cols = ['카드사', '카드번호', '이용일', '이용시간', '입금액', '출금액', '취소', '사업자번호', '폐업', '키워드', '카테고리', '가맹점명', '대체구분']
        if '대체구분' not in df_card.columns:
            df_card['대체구분'] = ''
        existing = [c for c in card_after_cols if c in df_card.columns]
        extra = [c for c in df_card.columns if c not in card_after_cols]
        df_card = df_card.reindex(columns=existing + extra)

        safe_write_data_json(CARD_AFTER_FILE, df_card)

        if not had_category_file and CATEGORY_TABLE_FILE:
            try:
                create_category_table(df_card, category_filepath=CATEGORY_TABLE_FILE)
            except Exception as e:
                print(f"category_table.json 신용카드 섹션 생성 실패: {e}", flush=True)

        return (True, None, len(df_card))
    except FileNotFoundError as e:
        err = f'파일을 찾을 수 없습니다: {str(e)}'
        LAST_CLASSIFY_ERROR = err
        return (False, err, 0)
    except Exception as e:
        import traceback
        traceback.print_exc()
        err = str(e)
        LAST_CLASSIFY_ERROR = err
        return (False, err, 0)


# 카테고리 분류: apply_category_from_merchant에서 계정과목만 사용, 키워드 길이 순, 기본값 기타거래


def create_category_table(df=None, category_filepath=None):
    """category_table.json 생성·갱신 (구분 없음). 분류 = 계정과목 등. 기본값 또는 .source/category_table.xlsx 동기화."""
    unique_category_data = get_default_rules('card')
    category_df = pd.DataFrame(unique_category_data).drop_duplicates(subset=['분류', '키워드', '카테고리'], keep='first')
    _root = os.environ.get('MYRISK_ROOT') or os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
    # category_table.json: data 폴더에서 관리
    default_info = os.path.join(_root, 'data', 'category_table.json')
    out_path = str(Path(category_filepath).resolve()) if category_filepath else default_info
    try:
        parent_dir = os.path.dirname(out_path)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)
        if len(category_df) == 0:
            category_df = pd.DataFrame(columns=CATEGORY_TABLE_COLUMNS)
        out = normalize_category_df(category_df, extended=True)
        if os.path.exists(out_path):
            full = load_category_table(out_path, default_empty=True)
            if full is not None and not full.empty:
                full = normalize_category_df(full, extended=True)
                if not full.empty:
                    out = pd.concat([full, out], ignore_index=True).drop_duplicates(subset=CATEGORY_TABLE_COLUMNS, keep='first')
        safe_write_category_table(out_path, out, extended=True)
        if not os.path.exists(out_path):
            raise FileNotFoundError(f"오류: 파일 생성 후에도 {out_path} 파일이 존재하지 않습니다.")
    except PermissionError as e:
        print(f"오류: 파일 쓰기 권한이 없습니다 - {out_path}")
        raise
    except Exception as e:
        # category_table 생성/쓰기 실패 시 호출자에 전달
        print(f"오류: category_table 생성 실패 - {e}")
        raise
    return category_df


def apply_category_from_merchant(df, category_df):
    """가맹점명을 기초로 category_table(신용카드) 규칙을 적용해 df['카테고리'] 채움.
    분류=계정과목만 사용. 키워드 길이 긴 순 적용. 기본값 기타거래, 매칭된 행만 계정과목으로 덮어씀."""
    if df is None or df.empty or category_df is None or category_df.empty:
        return df
    if '가맹점명' not in df.columns:
        return df
    if '카테고리' not in df.columns:
        df = df.copy()
        df['카테고리'] = ''
    if '키워드' not in df.columns:
        df['키워드'] = ''
    category_df = category_df.copy()
    category_df.columns = [str(c).strip() for c in category_df.columns]
    need_cols = ['분류', '키워드', '카테고리']
    if not all(c in category_df.columns for c in need_cols):
        return df
    # 계정과목만 사용. 행별 최대 키워드 길이 기준 정렬(긴 것 먼저). 매칭된 키워드가 더 긴 경우에만 덮어씀.
    account_mask = (category_df['분류'].astype(str).str.strip() == CLASS_ACCOUNT)
    account_df = category_df.loc[account_mask].copy()
    if account_df.empty:
        return df
    def _max_kw_len(s):
        parts = [k.strip() for k in str(s).split('/') if k.strip()]
        return max(len(k) for k in parts) if parts else 0
    account_df['_max_klen'] = account_df['키워드'].apply(_max_kw_len)
    account_df = account_df.sort_values('_max_klen', ascending=False).drop(columns=['_max_klen'], errors='ignore')
    df = df.copy()
    df['카테고리'] = df['카테고리'].astype(object)
    df['키워드'] = df['키워드'].astype(object)
    _preserve_mask = df['카테고리'].isin([CARD_CASH_PROCESSING])
    df.loc[~_preserve_mask, '카테고리'] = DEFAULT_CATEGORY
    df.loc[~_preserve_mask, '키워드'] = ''

    _risk_pri = RISK_CODE_PRIORITY

    df['_m_len'] = 0
    df['_m_risk'] = 0
    df['_m_pos'] = 999999
    df['_m_code'] = ''
    merchants = df['가맹점명'].fillna('').astype(str).apply(safe_str)
    for _, cat_row in account_df.iterrows():
        cat_val = safe_str(cat_row.get('카테고리', '')).strip() or DEFAULT_CATEGORY
        keywords_str = safe_str(cat_row.get('키워드', ''))
        if not keywords_str:
            continue
        code = safe_str(cat_row.get('위험지표', '')).strip()
        risk_val = _risk_pri.get(code[0] if code else '', 0)

        raw_keywords = [k.strip() for k in keywords_str.split('/') if k.strip()]
        plain_kw = [k for k in raw_keywords if not k.startswith('re:')]
        regex_kw = [k[3:] for k in raw_keywords if k.startswith('re:')]
        if not plain_kw and not regex_kw:
            continue
        keywords_norm = [normalize_주식회사_for_match(k) for k in plain_kw if k]
        rule_match = pd.Series(False, index=df.index)
        for kw in keywords_norm:
            if kw:
                rule_match |= merchants.str.contains(kw, regex=False, na=False)
        for pat in regex_kw:
            try:
                rule_match |= merchants.str.contains(pat, regex=True, na=False)
            except re.error:
                pass

        def _best_match(m):
            t = str(m)
            results = []
            for k in keywords_norm:
                if k and k in t:
                    results.append((k, len(k), t.find(k)))
            for pat in regex_kw:
                try:
                    mx = re.search(pat, t)
                    if mx:
                        results.append((mx.group(0), len(mx.group(0)), mx.start()))
                except re.error:
                    pass
            if not results:
                return ('', 0, 999999)
            return max(results, key=lambda x: (x[1], -x[2]))

        info = merchants.apply(_best_match)
        matched_kw = info.apply(lambda x: x[0])
        matched_len = info.apply(lambda x: x[1]).astype(int)
        matched_pos = info.apply(lambda x: x[2]).astype(int)

        is_default = (df['카테고리'].fillna('').astype(str) == DEFAULT_CATEGORY)
        longer = (matched_len > df['_m_len'])
        same_len = (matched_len == df['_m_len']) & (matched_len > 0)
        higher_risk = same_len & (risk_val > df['_m_risk'])
        same_risk = same_len & (risk_val == df['_m_risk'])
        earlier_pos = same_risk & (matched_pos < df['_m_pos'])
        same_pos = same_risk & (matched_pos == df['_m_pos'])
        higher_code = same_pos & (code > df['_m_code'])

        fill_mask = rule_match & (
            is_default | longer | higher_risk | earlier_pos | higher_code
        )
        if fill_mask.any():
            df.loc[fill_mask, '카테고리'] = cat_val
            df.loc[fill_mask, '키워드'] = matched_kw.loc[fill_mask]
            df.loc[fill_mask, '_m_len'] = matched_len.loc[fill_mask]
            df.loc[fill_mask, '_m_risk'] = risk_val
            df.loc[fill_mask, '_m_pos'] = matched_pos.loc[fill_mask]
            df.loc[fill_mask, '_m_code'] = code
    df = df.drop(columns=['_m_len', '_m_risk', '_m_pos', '_m_code'], errors='ignore')
    return df


def main():
    """카드 전용: integrate_card_excel 또는 classify_and_save 실행 (은행 process_bank_data와 동일)."""
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == 'integrate_card':
            integrate_card_excel()
            return
        if cmd == 'classify':
            ok, err, n = classify_and_save()
            if ok:
                print(f"card_after 생성 완료: {n}건", flush=True)
            else:
                print(f"오류: {err}", file=sys.stderr, flush=True)
            return
    integrate_card_excel()


if __name__ == '__main__':
    main()

