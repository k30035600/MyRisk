# -*- coding: utf-8 -*-
"""
신용카드 Flask 서브앱 (card_app.py).

전처리 페이지·카테고리 페이지를 제공하고,
process_card_data로 card_after 생성 및 data 저장을 수행한다.
"""
from flask import Flask, render_template, jsonify, request
import traceback
import pandas as pd
from pathlib import Path
import sys
import io
import os
from datetime import datetime

# ----- 인코딩 (Windows 콘솔) -----
if sys.platform == 'win32':
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except (OSError, AttributeError):
        pass  # 콘솔 UTF-8 래핑 실패 시 무시(통합 서버에서 app.py가 이미 설정)

app = Flask(__name__)

# JSON 인코딩 설정 (한글 지원)
app.json.ensure_ascii = False
app.config['JSON_AS_ASCII'] = False

@app.after_request
def _set_json_charset(response):
    if response.content_type and response.content_type.startswith('application/json'):
        response.headers['Content-Type'] = 'application/json; charset=utf-8'
    return response

# ----- 경로·상수 -----
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.normpath(os.path.join(SCRIPT_DIR, '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
# category_table: MyRisk/data (category_table_io로 읽기/쓰기)
try:
    from lib.path_config import (
        get_category_table_json_path,
        get_card_after_path,
        get_source_card_dir,
    )
    CATEGORY_TABLE_PATH = get_category_table_json_path()
    CARD_AFTER_PATH = get_card_after_path()
    SOURCE_CARD_DIR = get_source_card_dir()
except ImportError:
    CATEGORY_TABLE_PATH = str(Path(PROJECT_ROOT) / 'data' / 'category_table.json')
    CARD_AFTER_PATH = os.path.join(PROJECT_ROOT, 'data', 'card_after.json')
    SOURCE_CARD_DIR = os.path.join(PROJECT_ROOT, '.source', 'Card')
from lib.category_table_io import (
    load_category_table, normalize_category_df,
    get_category_table as _io_get_category_table,
    apply_category_action,
    CATEGORY_TABLE_EXTENDED_COLUMNS,
    _to_str_no_decimal,
)
# 원본 카드·after 경로: path_config에서 로드 (ImportError 시 위 fallback)

def _card_before_path():
    """card_before.json 경로 (CARD_AFTER_PATH와 동일 data 폴더)."""
    return os.path.join(os.path.dirname(CARD_AFTER_PATH), 'card_before.json')
try:
    from lib.data_json_io import safe_read_data_json, safe_write_data_json
except ImportError:
    safe_read_data_json = None
    safe_write_data_json = None

def _load_process_card_data_module():
    """MyCard 내 process_card_data 모듈 로드 (은행과 동일하게 일반 import)."""
    if SCRIPT_DIR not in sys.path:
        sys.path.insert(0, SCRIPT_DIR)
    import process_card_data
    return process_card_data


def _ensure_card_category_file():
    """category_table.json이 없으면 기본 규칙으로 생성 (구분 없음)."""
    path = Path(CATEGORY_TABLE_PATH)
    if path.exists():
        return
    try:
        mod = _load_process_card_data_module()
        mod.create_category_table(None, category_filepath=CATEGORY_TABLE_PATH)
    except Exception as e:
        # category_table 생성 실패 시에도 앱 기동 유지
        print(f"[card_app] category_table.json 생성 실패: {e}")


def _call_integrate_card(write_before=False):
    """source→전처리 DataFrame 반환. card_before.json이 이미 있으면 source 읽지 않고 기존 파일 사용. write_before=True면 없을 때만 data/card_before.json 저장."""
    p_before = Path(_card_before_path())
    if p_before.exists() and p_before.stat().st_size > 2 and safe_read_data_json:
        df = safe_read_data_json(str(p_before), default_empty=True)
        if df is not None and not df.empty:
            # 기존 JSON 사용. 아래와 동일한 후처리만 적용 후 반환
            if all(c in df.columns for c in ['카드사', '카드번호', '이용일', '가맹점명']):
                has_card = (
                    df['카드사'].notna() & (df['카드사'].astype(str).str.strip() != '') &
                    df['카드번호'].notna() & (df['카드번호'].astype(str).str.strip() != '') &
                    df['이용일'].notna() & (df['이용일'].astype(str).str.strip() != '') &
                    (df['가맹점명'].fillna('').astype(str).str.strip() == '')
                )
                df = df.copy()
                df.loc[has_card, '가맹점명'] = df.loc[has_card, '카드사']
            _apply_카드사_사업자번호_기본값(df)
            if '할부' in df.columns:
                df = df.rename(columns={'할부': '폐업'})
            if '폐업' in df.columns:
                df['폐업'] = df['폐업'].apply(
                    lambda v: '폐업' if v is not None and str(v).strip() == '폐업' else ''
                )
            return df
    mod = _load_process_card_data_module()
    if write_before:
        df = mod.integrate_card_excel(output_file=_card_before_path(), skip_write=False)
    else:
        df = mod.integrate_card_excel(skip_write=True)
    if df is not None and not df.empty and all(c in df.columns for c in ['카드사', '카드번호', '이용일', '이용금액', '가맹점명']):
        has_card = (
            df['카드사'].notna() & (df['카드사'].astype(str).str.strip() != '') &
            df['카드번호'].notna() & (df['카드번호'].astype(str).str.strip() != '') &
            df['이용일'].notna() & (df['이용일'].astype(str).str.strip() != '') &
            df['이용금액'].notna() &
            (df['가맹점명'].fillna('').astype(str).str.strip() == '')
        )
        df.loc[has_card, '가맹점명'] = df.loc[has_card, '카드사']
    if df is not None and not df.empty:
        _apply_카드사_사업자번호_기본값(df)
    if df is not None and not df.empty:
        if '할부' in df.columns:
            df = df.rename(columns={'할부': '폐업'})
        if '폐업' in df.columns:
            df['폐업'] = df['폐업'].apply(
                lambda v: '폐업' if v is not None and str(v).strip() == '폐업' else ''
            )
    return df

# ensure_working_directory: 아래 공통 모듈 블록에서 생성
def _apply_카드사_사업자번호_기본값(df):
    """process_card_data의 동일 함수로 위임."""
    try:
        mod = _load_process_card_data_module()
        mod._apply_카드사_사업자번호_기본값(df)
    except (ImportError, AttributeError):
        if df.empty or '카드사' not in df.columns or '사업자번호' not in df.columns:
            return
        empty_biz = (df['사업자번호'].fillna('').astype(str).str.strip() == '')
        shinhan = df['카드사'].fillna('').astype(str).str.strip().str.contains('신한', case=False, na=False)
        hana = df['카드사'].fillna('').astype(str).str.strip().str.contains('하나', case=False, na=False)
        if (empty_biz & shinhan).any():
            df.loc[empty_biz & shinhan, '사업자번호'] = '202-81-48079'
        if (empty_biz & hana).any():
            df.loc[empty_biz & hana, '사업자번호'] = '104-86-56659'


def _card_deposit_withdraw_from_이용금액(df):
    """신용카드: 이용금액 → 입금액/출금액. 현금처리는 항상 입금.
    이용금액이 있는 행만 변환 (은행 데이터는 기존 입금액/출금액 유지)."""
    if df.empty or '이용금액' not in df.columns:
        return
    amt = pd.to_numeric(df['이용금액'], errors='coerce')
    has_amt = amt.notna() & (amt != 0)
    if not has_amt.any():
        return
    cat = df['카테고리'].fillna('').astype(str).str.strip() if '카테고리' in df.columns else pd.Series([''] * len(df), index=df.index)
    # 현금처리: 항상 입금 (이용금액 절대값을 입금액에)
    현금처리 = (cat == '현금처리')
    입금 = ((amt < 0) | 현금처리) & has_amt
    출금 = ((amt > 0) & ~현금처리) & has_amt
    if '입금액' not in df.columns:
        df['입금액'] = 0
    if '출금액' not in df.columns:
        df['출금액'] = 0
    df.loc[입금, '입금액'] = amt[입금].abs()
    df.loc[출금, '출금액'] = amt[출금].abs()


# ----- 데코레이터·JSON 유틸·캐시 (공통 모듈 사용) -----
from lib.shared_app_utils import (
    make_ensure_working_directory,
    json_safe as _json_safe,
    format_bytes,
    load_source_file_list,
    df_memory_bytes,
    list_memory_bytes,
    time_to_seconds as _time_to_seconds,
)
from lib.analysis_common import (
    apply_bank_filter, apply_category_filters,
    compute_summary, compute_by_category, compute_by_category_group,
    compute_by_month, compute_by_category_monthly, compute_by_content,
    compute_by_division, compute_by_bank, compute_transactions_by_content,
    compute_transactions, compute_content_by_category, compute_date_range,
)
try:
    from lib.after_cache import AfterCache
except ImportError:
    AfterCache = None
ensure_working_directory = make_ensure_working_directory(SCRIPT_DIR)


def _normalize_date_filter(s, max_len=None):
    """요청 날짜 필터 문자열 정규화 (공백·구분자 제거). max_len이 있으면 앞자리만 사용(예: 6=YYYYMM)."""
    if not s or not isinstance(s, str):
        return ''
    d = s.replace('-', '').replace('/', '').replace('.', '').replace(' ', '')
    if max_len is not None and max_len > 0:
        d = d[:max_len]
    return d


def _fill_time(v):
    """이용시간 값이 비어 있으면 '00:00:00' 반환 (테이블 표시용)."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return '00:00:00'
    s = str(v).strip()
    return '00:00:00' if not s else s


def _normalize_cancel_value(v, empty_means_cancel_only=False):
    """취소 컬럼 값 정규화: 0/0.0/nan/None → '', '취소' 또는 '취소된 거래' 포함 시 '취소'.
    empty_means_cancel_only=True면 비어있지 않으면 모두 '취소'로 통일(카테고리 적용 테이블용)."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ''
    s = str(v).strip()
    if s in ('', '0', '0.0', 'nan', 'None'):
        return ''
    if empty_means_cancel_only:
        return '취소' if s else ''
    return '취소' if '취소' in s else s


def load_source_files():
    """MyRisk/.source/Card 의 원본 파일 목록 가져오기. .xls, .xlsx만 취급."""
    return load_source_file_list(Path(SOURCE_CARD_DIR))



def _normalize_폐업_column(df):
    """폐업 컬럼 정규화: '폐업'만 유지, 일시불·취소·그 외는 공백."""
    if df is None or df.empty or '폐업' not in df.columns:
        return
    df['폐업'] = df['폐업'].apply(
        lambda v: '폐업' if v is not None and str(v).strip() == '폐업' else ''
    )


# 전처리전 source 캐시: .source/Card를 한 번만 읽어 JSON 형태로 보관, 서버 종료 또는 reintegrate 시에만 무효화
_source_card_cache = None

# card_after 캐시 (lib.after_cache 공통)
_card_after_cache_obj = AfterCache() if AfterCache else None

def _read_card_after_raw(path):
    """card_after 파일 읽기 + 컬럼 정규화 (캐시용)."""
    try:
        if safe_read_data_json and str(path).endswith('.json'):
            df = safe_read_data_json(path, default_empty=True)
        else:
            df = pd.read_excel(path, engine='openpyxl')
        if df is None or df.empty:
            return pd.DataFrame()
        df = df.copy()
        df.columns = [str(c).strip() for c in df.columns]
        if '구분' in df.columns and '폐업' not in df.columns:
            df = df.rename(columns={'구분': '폐업'})
        if '할부' in df.columns and '폐업' not in df.columns:
            df = df.rename(columns={'할부': '폐업'})
        _normalize_폐업_column(df)
        return df
    except Exception as e:
        print(f"Error reading {path}: {str(e)}")
        return pd.DataFrame()

def _load_card_after_cached():
    """card_after.json 로드. 캐시 있으면 재사용, 재생성 시에만 파일 재읽기."""
    if _card_after_cache_obj is None:
        return _read_card_after_raw(CARD_AFTER_PATH)
    return _card_after_cache_obj.get(CARD_AFTER_PATH, _read_card_after_raw)

def load_category_file():
    """card_after.json 로드. 캐시 사용, 이용금액→입금/출금 변환."""
    try:
        df = _load_card_after_cached()
        if not df.empty and '이용금액' in df.columns and '입금액' not in df.columns:
            _card_deposit_withdraw_from_이용금액(df)
        return df
    except Exception as e:
        print(f"오류: card_after 로드 실패 - {e}", flush=True)
        return pd.DataFrame()


# 전처리 페이지에서 사용하는 별칭 (load_category_file과 동일)
load_processed_file = load_category_file

@app.route('/')
def index():
    # 카테고리 정의 테이블: 서버에서 HTML로 렌더링. 신용카드 카테고리 조회에서는 분류=업종분류/위험도분류 제외.
    category_table_rows = []
    category_file_exists = False
    try:
        df, category_file_exists = _io_get_category_table(str(Path(CATEGORY_TABLE_PATH)))
        if df is not None and not df.empty:
            if '분류' in df.columns:
                분류_col = df['분류'].fillna('').astype(str).str.strip()
                df = df[~분류_col.isin(['업종분류', '위험도분류'])].copy()
            for c in CATEGORY_TABLE_EXTENDED_COLUMNS:
                if c not in df.columns:
                    df[c] = ''
            category_table_rows = df[CATEGORY_TABLE_EXTENDED_COLUMNS].fillna('').to_dict('records')
            for r in category_table_rows:
                r['업종코드'] = _to_str_no_decimal(r.get('업종코드'))
    except (OSError, ValueError, KeyError):
        category_file_exists = Path(CATEGORY_TABLE_PATH).exists()
    return render_template(
        'index.html',
        category_table_rows=category_table_rows,
        category_file_exists=category_file_exists,
    )

@app.route('/favicon.ico')
def favicon():
    return '', 204

@app.route('/api/cache-info')
def get_cache_info():
    """캐시 이름·크기·총메모리 (금융정보 분석 시스템 헤더 표시용)."""
    try:
        caches = []
        total = 0
        if _source_card_cache is not None:
            b = list_memory_bytes(_source_card_cache)
            total += b
            caches.append({'name': 'card_source', 'size_bytes': b})
        if _card_after_cache_obj is not None and _card_after_cache_obj.current is not None:
            b = df_memory_bytes(_card_after_cache_obj.current)
            total += b
            caches.append({'name': 'card_after', 'size_bytes': b})
        for c in caches:
            c['size_human'] = format_bytes(c['size_bytes'])
        return jsonify({
            'app': 'MyCard',
            'caches': caches,
            'total_bytes': total,
            'total_human': format_bytes(total),
        })
    except Exception as e:
        # 캐시 정보 수집 중 예외 시 에러 필드 포함해 200 반환
        return jsonify({'app': 'MyCard', 'caches': [], 'total_bytes': 0, 'total_human': '0 B', 'error': str(e)})

@app.route('/api/source-files')
@ensure_working_directory
def get_source_files():
    """원본 파일 목록 반환. MyRisk/.source/Card 의 .xls, .xlsx만 취급."""
    try:
        current_dir = os.getcwd()
        source_dir = Path(SOURCE_CARD_DIR)
        if not source_dir.exists():
            return jsonify({
                'error': f'.source/Card 폴더를 찾을 수 없습니다.\n현재 작업 디렉토리: {current_dir}\n.source/Card 경로: {source_dir}',
                'files': []
            }), 404
        
        files = load_source_files()
        response = jsonify({
            'files': files,
            'count': len(files)
        })

        return response
    except Exception as e:
        traceback.print_exc()
        current_dir = os.getcwd()
        return jsonify({
            'error': f'파일 목록 로드 중 오류가 발생했습니다: {str(e)}\n현재 작업 디렉토리: {current_dir}\n스크립트 디렉토리: {SCRIPT_DIR}',
            'files': []
        }), 500

@app.route('/api/card-before-data')
@ensure_working_directory
def get_card_before_data():
    """card_before(전처리 결과) JSON 반환. 전처리전 화면은 /api/source-data(원본 엑셀) 사용(Bank와 동일)."""
    try:
        df = _call_integrate_card(write_before=True)
        if df is None or df.empty:
            return jsonify({
                'columns': [],
                'data': [],
                'count': 0
            })
        df = df.where(pd.notna(df), None)
        columns = list(df.columns)
        data = _json_safe(df.to_dict('records'))
        return jsonify({
            'columns': columns,
            'data': data,
            'count': len(data)
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({
            'error': str(e),
            'columns': [],
            'data': [],
            'count': 0
        }), 500


@app.route('/api/run-card-preprocess', methods=['POST'])
@ensure_working_directory
def run_card_preprocess():
    """Source 전처리(card_before.json 저장)·카테고리 적용하여 card_after 생성/갱신."""
    try:
        df = _call_integrate_card(write_before=True)
        success, _, _ = _create_card_after(input_df=df)
        if not success:
            return jsonify({'success': False, 'error': 'card_after 생성 실패'}), 500
        return jsonify({'success': True, 'message': 'card_after가 생성되었습니다.'})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


def _remove_card_after_and_bak():
    """통합·카테고리 다시 실행 전에 card_after 삭제. 캐시 무효화 (card_before 미사용)."""
    global _source_card_cache
    _source_card_cache = None
    if _card_after_cache_obj is not None:
        _card_after_cache_obj.invalidate()
    p = Path(CARD_AFTER_PATH)
    try:
        if p.exists():
            p.unlink()
    except OSError:
        pass


@app.route('/api/clear-cache', methods=['POST'])
@ensure_working_directory
def clear_cache_card():
    """선택한 JSON만 삭제. body: { \"before\": bool, \"after\": bool } — before: card_before.json 삭제, after: card_after.json 삭제."""
    try:
        data = request.get_json(force=True, silent=True) or {}
        clear_before = data.get('before', False)
        clear_after = data.get('after', False)
        global _source_card_cache
        if clear_before:
            _source_card_cache = None
            p_before = Path(_card_before_path())
            try:
                if p_before.exists():
                    p_before.unlink()
            except OSError:
                pass
        if clear_after:
            if _card_after_cache_obj is not None:
                _card_after_cache_obj.invalidate()
            p = Path(CARD_AFTER_PATH)
            try:
                if p.exists():
                    p.unlink()
            except OSError:
                pass
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/reintegrate', methods=['POST'])
@ensure_working_directory
def reintegrate_card():
    """card_after를 .source/Card 기준으로 다시 전처리(card_before.json 저장)·분류·후처리하여 덮어쓴다."""
    try:
        _remove_card_after_and_bak()
        df = _call_integrate_card(write_before=True)
        success, _, _ = _create_card_after(input_df=df)
        if not success:
            return jsonify({'ok': False, 'error': 'card_after 생성 실패'}), 500
        return jsonify({'ok': True})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/processed-data')
@ensure_working_directory
def get_processed_data():
    """카드 데이터 반환 (card_after만 사용, 필터링 지원)."""
    try:
        output_path = Path(CARD_AFTER_PATH)
        if not output_path.exists() or output_path.stat().st_size == 0:
            try:
                df = _call_integrate_card(write_before=True)
                success, _, _ = _create_card_after(input_df=df)
                if not success or not output_path.exists():
                    return jsonify({
                        'error': 'card_after가 생성되지 않았습니다. MyRisk/.source/Card에 .xls, .xlsx 파일이 있는지 확인하세요.',
                        'count': 0,
                        'deposit_amount': 0,
                        'withdraw_amount': 0,
                        'data': []
                    }), 500
            except Exception as e:
                return jsonify({
                    'error': f'통합/카테고리 적용 오류: {str(e)}',
                    'count': 0,
                    'deposit_amount': 0,
                    'withdraw_amount': 0,
                    'data': []
                }), 500

        df = load_category_file()

        category_file_exists = Path(CATEGORY_TABLE_PATH).exists()
        
        if df.empty:
            response = jsonify({
                'count': 0,
                'deposit_amount': 0,
                'withdraw_amount': 0,
                'data': [],
                'file_exists': category_file_exists
            })
    
            return response
        
        # 필터 파라미터 (card_before: 카드사, 카드번호, 이용일 등)
        date_filter = request.args.get('date', '')
        bank_filter = request.args.get('bank', '')  # 카드사 필터
        cardno_filter = request.args.get('cardno', '')  # 카드번호 필터
        
        # 카드사 필터 (카드사 컬럼)
        if bank_filter and not df.empty and '카드사' in df.columns:
            df = df[df['카드사'].astype(str).str.strip() == bank_filter]
        # 카드번호 필터
        if cardno_filter and not df.empty and '카드번호' in df.columns:
            df = df[df['카드번호'].astype(str).str.strip() == cardno_filter]
        # 이용일 필터 (yy/mm 또는 yyyy-mm 등)
        if date_filter and not df.empty and '이용일' in df.columns:
            d = _normalize_date_filter(date_filter, max_len=6)
            df = df[df['이용일'].astype(str).str.replace(r'[\s\-/.]', '', regex=True).str.startswith(d)]
        elif date_filter and not df.empty:
            date_col = next((c for c in df.columns if '일' in str(c) or '날짜' in str(c)), None)
            if date_col:
                d = _normalize_date_filter(date_filter, max_len=None)
                df = df[df[date_col].astype(str).str.replace(r'[\s\-/.]', '', regex=True).str.startswith(d)]
        
        # 전처리후 화면: 입금액 절대값으로 표시 (card_before 생성 시에도 절대값 저장됨)
        if not df.empty and '입금액' in df.columns:
            df['입금액'] = pd.to_numeric(df['입금액'], errors='coerce').fillna(0).abs()
        
        # 카드번호 16자 이하 행 제외 (float → int 변환 후 길이 비교, 전처리후 표시용)
        if not df.empty and '카드번호' in df.columns:
            def _card_no_str(v):
                if isinstance(v, float) and v == int(v):
                    return str(int(v))
                return str(v).strip()
            df = df[df['카드번호'].apply(_card_no_str).str.len() > 16]
        
        # 집계 계산 (card_before: 이용금액<0 → 입금, 이용금액>0 → 출금, 현금처리 → 항상 입금 / 은행: 입금액·출금액)
        count = len(df)
        if not df.empty and '이용금액' in df.columns:
            _card_deposit_withdraw_from_이용금액(df)
            deposit_amount = int(df['입금액'].sum())
            withdraw_amount = int(df['출금액'].sum())
        else:
            deposit_amount = int(df['입금액'].sum()) if not df.empty and '입금액' in df.columns else 0
            withdraw_amount = int(df['출금액'].sum()) if not df.empty and '출금액' in df.columns else 0
        
        # NaN 값을 None으로 변환
        df = df.where(pd.notna(df), None)
        # 취소 컬럼: 0/0.0/'0'은 빈 문자열, "0 취소" 등은 '취소'로 통일
        if not df.empty and '취소' in df.columns:
            df['취소'] = df['취소'].apply(lambda v: _normalize_cancel_value(v, empty_means_cancel_only=False))
        # 이용시간 없으면 00:00:00 (전처리후 화면 표시)
        if not df.empty and '이용시간' in df.columns:
            df['이용시간'] = df['이용시간'].apply(_fill_time)
        # 전처리후 테이블: 이용일 → 이용시간 → 카드사 → 카드번호 올림차순
        sort_cols = [c for c in ('이용일', '이용시간', '카드사', '카드번호') if c in df.columns]
        if sort_cols:
            df = df.sort_values(by=sort_cols, ascending=True, na_position='last').reset_index(drop=True)
        
        total = len(df)
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
        traceback.print_exc()
        category_file_exists = Path(CARD_AFTER_PATH).exists()
        return jsonify({
            'error': str(e),
            'count': 0,
            'deposit_amount': 0,
            'withdraw_amount': 0,
            'data': [],
            'file_exists': category_file_exists
        }), 500

@app.route('/api/category-applied-data')
@ensure_working_directory
def get_category_applied_data():
    """카테고리 적용된 데이터 반환 (card_after, 필터링 지원).
    card_after 존재하면 사용만, 없으면 생성하지 않고 빈 데이터. 생성은 /api/generate-category(생성 필터)에서 백업 후 수행."""
    try:
        card_after_path = Path(CARD_AFTER_PATH)
        category_file_exists = card_after_path.exists() and card_after_path.stat().st_size > 0

        # 카테고리 파일 로드
        try:
            df = load_category_file()
        except Exception as e:
            print(f"Error loading category file: {str(e)}")
            traceback.print_exc()
            df = pd.DataFrame()
        
        if df.empty:
            response = jsonify({
                'count': 0,
                'total': 0,
                'deposit_amount': 0,
                'withdraw_amount': 0,
                'deposit_count': 0,
                'withdraw_count': 0,
                'data': [],
                'file_exists': category_file_exists
            })
    
            return response
        
        # 필터 파라미터 (전처리후 카드사/카드번호에 따라 필터링)
        bank_filter = (request.args.get('bank') or '').strip()
        date_filter = request.args.get('date', '')
        cardno_filter = (request.args.get('cardno') or '').strip()
        bank_col = '카드사' if not df.empty and '카드사' in df.columns else '은행명'
        if bank_filter and bank_col in df.columns:
            df = df[df[bank_col].astype(str).str.strip() == bank_filter]
        
        if cardno_filter and '카드번호' in df.columns:
            df = df[df['카드번호'].fillna('').astype(str).str.strip() == cardno_filter]
        
        if date_filter:
            date_col = '이용일' if '이용일' in df.columns else ('거래일' if '거래일' in df.columns else None)
            if date_col:
                try:
                    d = _normalize_date_filter(date_filter, max_len=6)
                    df['_date_str'] = df[date_col].astype(str).str.replace(r'[\s\-/.]', '', regex=True)
                    df = df[df['_date_str'].str.startswith(d, na=False)]
                    df = df.drop('_date_str', axis=1)
                except (TypeError, ValueError, KeyError) as e:
                    # 날짜 필터 실패 시 필터 없이 진행
                    print(f"Error filtering by date: {str(e)}")

        # 집계 계산: 카드(card_after)는 이용금액 기준(현금처리→입금), 은행은 입금액/출금액
        count = len(df)
        if not df.empty and '이용금액' in df.columns:
            _card_deposit_withdraw_from_이용금액(df)
            deposit_amount = int(df['입금액'].sum())
            withdraw_amount = int(df['출금액'].sum())
        else:
            for c in ['입금액', '출금액']:
                if c not in df.columns:
                    df[c] = 0
            deposit_amount = int(df['입금액'].sum()) if not df.empty else 0
            withdraw_amount = int(df['출금액'].sum()) if not df.empty else 0
        dep_series = pd.to_numeric(df['입금액'], errors='coerce').fillna(0) if not df.empty and '입금액' in df.columns else pd.Series(dtype=float)
        wit_series = pd.to_numeric(df['출금액'], errors='coerce').fillna(0) if not df.empty and '출금액' in df.columns else pd.Series(dtype=float)
        deposit_count = int((dep_series > 0).sum())
        withdraw_count = int((wit_series > 0).sum())
        
        df = df.where(pd.notna(df), None)
        # 취소 컬럼: 0/0.0/'0'/nan은 빈 문자열, 비어있지 않으면 '취소' (테이블에 "취소"만 표시)
        if not df.empty and '취소' in df.columns:
            df['취소'] = df['취소'].apply(lambda v: _normalize_cancel_value(v, empty_means_cancel_only=True))
        # 이용시간 없으면 00:00:00 (카테고리 조회 테이블 표시)
        if not df.empty and '이용시간' in df.columns:
            df['이용시간'] = df['이용시간'].apply(_fill_time)
        # 심야구분 컬럼: 이용시간이 category_table 심야 구간이면 '심야', 아니면 ''
        if not df.empty and '이용시간' in df.columns:
            simya_ranges = _get_simya_ranges_sec()
            df['심야구분'] = df['이용시간'].apply(lambda t: '심야' if _is_time_in_simya(t, simya_ranges) else '')
            cols = list(df.columns)
            if '심야구분' in cols:
                cols.remove('심야구분')
                idx = cols.index('이용시간') + 1 if '이용시간' in cols else 0
                cols.insert(idx, '심야구분')
                df = df[cols]
        elif not df.empty:
            df['심야구분'] = ''
        # 카테고리 적용후 테이블: 이용일/이용시간 다나가 순(내림), 카드사 가나다 순(오름)
        sort_cols = []
        ascending = []
        for c in ('이용일', '이용시간', '카드사', '카드번호'):
            if c in df.columns:
                sort_cols.append(c)
                ascending.append(False if c in ('이용일', '이용시간') else True)
        if sort_cols:
            df = df.sort_values(by=sort_cols, ascending=ascending, na_position='last').reset_index(drop=True)
        total = len(df)
        # 페이지네이션: limit/offset (limit 생략 또는 0이면 전체 반환)
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
            'deposit_count': deposit_count,
            'withdraw_count': withdraw_count,
            'data': data,
            'file_exists': category_file_exists
        })

        return response
    except Exception as e:
        traceback.print_exc()
        return jsonify({
            'error': str(e),
            'count': 0,
            'total': 0,
            'deposit_amount': 0,
            'withdraw_amount': 0,
            'deposit_count': 0,
            'withdraw_count': 0,
            'data': [],
            'file_exists': Path(CARD_AFTER_PATH).exists()
        }), 500

def _build_source_card_cache():
    """MyRisk/.source/Card 의 .xls/.xlsx를 읽어 전처리전 source 캐시(리스트)를 채운다. 실패 시 None."""
    global _source_card_cache
    source_dir = Path(SOURCE_CARD_DIR)
    if not source_dir.exists():
        return None
    excel_files = sorted(
        list(source_dir.glob('*.xls')) + list(source_dir.glob('*.xlsx')),
        key=lambda p: (p.name, str(p))
    )
    if not excel_files:
        return None
    all_data = []
    for file_path in excel_files:
        filename = file_path.name
        card_name = None
        if '국민' in filename:
            card_name = '국민카드'
        elif '신한' in filename:
            card_name = '신한카드'
        elif '하나' in filename:
            card_name = '하나카드'
        elif '현대' in filename:
            card_name = '현대카드'
        elif '농협' in filename:
            card_name = '농협카드'
        try:
            suf = file_path.suffix.lower()
            engine = 'xlrd' if suf == '.xls' else 'openpyxl'
            xls = pd.ExcelFile(file_path, engine=engine)
            for sheet_name in xls.sheet_names:
                try:
                    df = pd.read_excel(file_path, sheet_name=sheet_name, header=None, engine=engine)
                    df = df.where(pd.notna(df), None)
                    data_dict = df.to_dict('records')
                    data_dict = _json_safe(data_dict)
                    sheet_data = {
                        'filename': filename,
                        'sheet_name': sheet_name,
                        'card': card_name,
                        'data': data_dict
                    }
                    all_data.append(sheet_data)
                except Exception:
                    continue
        except Exception:
            continue
    _source_card_cache = all_data
    return _source_card_cache


@app.route('/api/source-data')
@ensure_working_directory
def get_source_data():
    """전처리전 테이블용: .source/Card 원본을 한 번만 읽어 캐시 후 재활용. 재생성 버튼 시 캐시 무효화."""
    try:
        global _source_card_cache
        source_dir = Path(SOURCE_CARD_DIR)
        current_dir = os.getcwd()
        if not source_dir.exists():
            return jsonify({
                'error': f'.source/Card 폴더를 찾을 수 없습니다.\n현재 작업 디렉토리: {current_dir}\n.source/Card 경로: {source_dir}',
                'count': 0,
                'deposit_amount': 0,
                'withdraw_amount': 0,
                'files': []
            }), 404

        card_filter = request.args.get('card', '')

        if _source_card_cache is None:
            _build_source_card_cache()
        if _source_card_cache is None:
            return jsonify({
                'error': f'.source/Card 폴더에 .xls, .xlsx 파일이 없습니다.\n현재 작업 디렉토리: {current_dir}\n.source/Card 경로: {source_dir}',
                'count': 0,
                'deposit_amount': 0,
                'withdraw_amount': 0,
                'files': []
            }), 404

        filtered = [s for s in _source_card_cache if not card_filter or s.get('card') == card_filter]
        count = sum(len(s['data']) for s in filtered)

        response = jsonify({
            'count': count,
            'deposit_amount': 0,
            'withdraw_amount': 0,
            'files': filtered
        })

        return response
    except Exception as e:
        traceback.print_exc()
        response = jsonify({
            'error': str(e),
            'count': 0,
            'deposit_amount': 0,
            'withdraw_amount': 0,
            'files': []
        })

        return response, 500

# 카테고리 페이지 라우트
@app.route('/category')
def category():
    """카테고리 페이지"""
    return render_template('category.html')

@app.route('/api/category')
def get_category_table():
    """category_table.json 반환. 신용카드 카테고리 조회에서는 분류=업종분류/위험도분류 제외."""
    path = str(Path(CATEGORY_TABLE_PATH))
    try:
        df, _ = _io_get_category_table(path)
        if df is not None and not df.empty and '분류' in df.columns:
            분류_col = df['분류'].fillna('').astype(str).str.strip()
            df = df[~분류_col.isin(['업종분류', '위험도분류'])].copy()
        if df is None or df.empty:
            data = []
        else:
            for c in CATEGORY_TABLE_EXTENDED_COLUMNS:
                if c not in df.columns:
                    df[c] = ''
            data = df[CATEGORY_TABLE_EXTENDED_COLUMNS].fillna('').to_dict('records')
            for r in data:
                r['업종코드'] = _to_str_no_decimal(r.get('업종코드'))
        response = jsonify({
            'data': data,
            'columns': CATEGORY_TABLE_EXTENDED_COLUMNS,
            'count': len(data),
            'file_exists': True
        })

        return response
    except Exception as e:
        traceback.print_exc()
        response = jsonify({
            'error': str(e),
            'data': [],
            'file_exists': Path(CATEGORY_TABLE_PATH).exists()
        })

        return response, 500



def _get_simya_ranges_sec():
    """category_table에서 분류=심야구분인 구간을 (start_sec, end_sec) 리스트로 반환. 공란/00:00:00 행은 제외."""
    try:
        df, _ = _io_get_category_table(str(Path(CATEGORY_TABLE_PATH)))
        if df is None or df.empty or '분류' not in df.columns:
            return []
        simya = df[df['분류'].fillna('').astype(str).str.strip() == '심야구분'].copy()
        result = []
        for _, row in simya.iterrows():
            kw = str(row.get('키워드', '') or '').strip()
            if not kw or '/' not in kw:
                continue
            parts = kw.split('/', 1)
            start_s, end_s = parts[0].strip(), parts[1].strip()
            if not start_s or not end_s:
                continue
            start_sec = _time_to_seconds(start_s)
            end_sec = _time_to_seconds(end_s)
            if start_sec is None or end_sec is None or start_sec == 0 or end_sec == 0:
                continue
            result.append((start_sec, end_sec))
        return result
    except Exception:
        return []


def _is_time_in_simya(time_str, ranges_sec):
    """이용시간이 심야 구간에 해당하면 True. 00:00:00은 False."""
    if not ranges_sec:
        return False
    t = _time_to_seconds(time_str)
    if t is None or t == 0:
        return False
    for start_sec, end_sec in ranges_sec:
        if end_sec >= start_sec:
            if start_sec <= t <= end_sec:
                return True
        else:
            if t >= start_sec or t <= end_sec:
                return True
    return False


@app.route('/api/simya-ranges')
@ensure_working_directory
def get_simya_ranges():
    """category_table.json에서 분류=심야구분인 행의 키워드(시작/종료 hh:mm:ss)를 파싱하여 반환. 00:00:00은 클라이언트에서 심야 제외."""
    try:
        df, _ = _io_get_category_table(str(Path(CATEGORY_TABLE_PATH)))
        if df is None or df.empty or '분류' not in df.columns:
            return jsonify({'ranges': []})
        simya = df[df['분류'].fillna('').astype(str).str.strip() == '심야구분'].copy()
        ranges = []
        for _, row in simya.iterrows():
            kw = str(row.get('키워드', '') or '').strip()
            if not kw or '/' not in kw:
                continue
            parts = kw.split('/', 1)
            start_s, end_s = parts[0].strip(), parts[1].strip()
            if not start_s or not end_s:
                continue
            start_sec = _time_to_seconds(start_s)
            end_sec = _time_to_seconds(end_s)
            if start_sec is None or end_sec is None or start_sec == 0 or end_sec == 0:
                continue
            ranges.append({'start': start_s if ':' in start_s else f'{start_s[0:2]}:{start_s[2:4]}:{start_s[4:6]}', 'end': end_s if ':' in end_s else f'{end_s[0:2]}:{end_s[2:4]}:{end_s[4:6]}'})
        return jsonify({'ranges': ranges})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'ranges': [], 'error': str(e)})


@app.route('/api/category', methods=['POST'])
def save_category_table():
    """category_table.json 전체 갱신 (구분 없음)"""
    path = str(Path(CATEGORY_TABLE_PATH))
    try:
        data = request.json or {}
        action = data.get('action', 'add')
        success, error_msg, count = apply_category_action(path, action, data)
        if not success:
            return jsonify({'success': False, 'error': error_msg}), 400
        try:
            from lib.category_table_io import export_category_table_to_xlsx
            export_category_table_to_xlsx(path)
        except Exception:
            pass
        try:
            from lib.path_config import delete_all_after_files
            delete_all_after_files()
        except Exception:
            pass
        response = jsonify({
            'success': True,
            'message': '카테고리 테이블이 업데이트되었습니다.',
            'count': count
        })

        return response
    except Exception as e:
        traceback.print_exc()
        response = jsonify({
            'success': False,
            'error': str(e)
        })

        return response, 500

# 분석 페이지 라우트
@app.route('/analysis/basic')
def analysis_basic():
    """기본 기능 분석 페이지"""
    return render_template('analysis_basic.html')

# 분석 API 라우트
@app.route('/api/analysis/summary')
def get_analysis_summary():
    try:
        df = load_processed_file()
        if df.empty:
            return jsonify(compute_summary(df))
        bank_col = '카드사' if '카드사' in df.columns else '은행명'
        bank_filter = request.args.get('bank', '')
        df = apply_bank_filter(df, bank_col, bank_filter)
        return jsonify(compute_summary(df))
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/analysis/by-category')
def get_analysis_by_category():
    try:
        df = load_category_file()
        if df.empty:
            return jsonify({'data': []})
        bank_col = '카드사' if '카드사' in df.columns else '은행명'
        df = apply_bank_filter(df, bank_col, request.args.get('bank', ''))
        df = apply_category_filters(df,
            입출금_filter=request.args.get('입출금', ''),
            거래유형_filter=request.args.get('거래유형', ''),
            category_type=request.args.get('category_type', ''),
            category_value=request.args.get('category_value', ''))
        return jsonify({'data': compute_by_category(df, bank_col=bank_col, include_category_filter=False)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/analysis/by-category-group')
def get_analysis_by_category_group():
    try:
        df = load_category_file()
        if df.empty:
            return jsonify({'data': []})
        bank_col = '카드사' if '카드사' in df.columns else '은행명'
        df = apply_bank_filter(df, bank_col, request.args.get('bank', ''))
        df = apply_category_filters(df,
            입출금_filter=request.args.get('입출금', ''),
            거래유형_filter=request.args.get('거래유형', ''))
        return jsonify({'data': compute_by_category_group(df, bank_col=bank_col, include_category_groupby=False)})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/analysis/by-month')
def get_analysis_by_month():
    try:
        df = load_category_file()
        if df.empty:
            return jsonify({'months': [], 'deposit': [], 'withdraw': [], 'min_date': None, 'max_date': None})
        bank_col = '카드사' if '카드사' in df.columns else '은행명'
        df = apply_bank_filter(df, bank_col, request.args.get('bank', ''))
        df = apply_category_filters(df,
            입출금_filter=request.args.get('입출금', ''),
            거래유형_filter=request.args.get('거래유형', ''),
            category_type=request.args.get('category_type', ''),
            category_value=request.args.get('category_value', ''))
        return jsonify(compute_by_month(df))
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/analysis/by-category-monthly')
def get_analysis_by_category_monthly():
    try:
        df = load_category_file()
        if df.empty:
            return jsonify({'months': [], 'categories': []})
        bank_col = '카드사' if '카드사' in df.columns else '은행명'
        df = apply_bank_filter(df, bank_col, request.args.get('bank', ''))
        df = apply_category_filters(df,
            입출금_filter=request.args.get('입출금', ''),
            거래유형_filter=request.args.get('거래유형', ''))
        return jsonify(compute_by_category_monthly(df, include_category_groupby=False, label_cols=['거래유형']))
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e), 'months': [], 'categories': []}), 500

@app.route('/api/analysis/by-content')
def get_analysis_by_content():
    try:
        df = load_processed_file()
        return jsonify(compute_by_content(df))
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/analysis/by-division')
def get_analysis_by_division():
    try:
        df = load_processed_file()
        return jsonify({'data': compute_by_division(df, division_col='폐업')})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/analysis/by-bank')
def get_analysis_by_bank():
    try:
        df = load_category_file()
        if df.empty:
            return jsonify({'bank': [], 'account': []})
        bank_col = '카드사' if '카드사' in df.columns else '은행명'
        account_col = '카드번호' if '카드번호' in df.columns else '계좌번호'
        return jsonify(compute_by_bank(df, bank_col=bank_col, account_col=account_col, include_count=False))
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/analysis/transactions-by-content')
def get_transactions_by_content():
    try:
        df = load_processed_file()
        if df.empty:
            return jsonify({'data': []})
        type_filter = request.args.get('type', 'deposit')
        limit = int(request.args.get('limit', 10))
        bank_col = '카드사' if '카드사' in df.columns else '은행명'
        content_col = '가맹점명' if '가맹점명' in df.columns and '내용' not in df.columns else '내용'
        if content_col not in df.columns:
            content_col = '가맹점명' if '가맹점명' in df.columns else '내용'
        data = compute_transactions_by_content(df, type_filter=type_filter, limit=limit,
            bank_col=bank_col, content_col=content_col, division_col='폐업',
            json_safe_fn=_json_safe)
        return jsonify({'data': data})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/analysis/transactions')
def get_analysis_transactions():
    try:
        df = load_category_file()
        if df.empty:
            return jsonify({'data': [], 'deposit_total': 0, 'withdraw_total': 0, 'balance': 0, 'deposit_count': 0, 'withdraw_count': 0})
        bank_col = '카드사' if not df.empty and '카드사' in df.columns else '은행명'
        filter_col = '카테고리' if '카테고리' in df.columns else '적요'
        date_col = '이용일' if '이용일' in df.columns else '거래일'
        cat_col = '카테고리' if '카테고리' in df.columns else '적요'
        merch_col = '가맹점명' if '가맹점명' in df.columns else '거래점'
        output_cols = [c for c in [cat_col, date_col, bank_col, '입금액', '출금액'] if c in df.columns]
        return jsonify(compute_transactions(df,
            transaction_type=request.args.get('type', 'deposit'),
            category_filter=request.args.get('category', ''),
            content_filter=request.args.get('content', ''),
            bank_filter=request.args.get('bank', ''),
            category_type=request.args.get('category_type', ''),
            category_value=request.args.get('category_value', ''),
            bank_col=bank_col, date_col=date_col,
            filter_col=filter_col, extra_col='내용',
            output_cols=output_cols,
            json_safe_fn=_json_safe))
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/analysis/content-by-category')
def get_content_by_category():
    try:
        df = load_processed_file()
        data = compute_content_by_category(df, filter_col='적요', category_filter=request.args.get('category', ''))
        return jsonify({'data': data})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/analysis/date-range')
def get_date_range():
    try:
        df = load_processed_file()
        return jsonify(compute_date_range(df))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def _create_card_after(input_df=None):
    """card_before → card_after 생성. 은행과 동일하게 process_card_data.classify_and_save에서 처리."""
    mod = _load_process_card_data_module()
    return mod.classify_and_save(input_df=input_df)


@app.route('/api/generate-category', methods=['POST'])
@ensure_working_directory
def generate_category():
    """card_before → card_after 생성. category_table(신용카드) 규칙으로 카테고리(계정과목 등) 적용 후 저장."""
    had_category_file = Path(CATEGORY_TABLE_PATH).exists()
    success, error, count = _create_card_after()
    if success:
        return jsonify({
            'success': True,
            'message': f'card_after 생성 완료: {count}건' + (
                ' (카테고리 적용 없이 미분류로 저장 후 category_table 신용카드 섹션 생성)' if not had_category_file else ' (category_table 적용)'
            ),
            'count': count,
            'folder': str(Path(CARD_AFTER_PATH).parent),
            'filename': Path(CARD_AFTER_PATH).name
        })
    if error and ('만들 수 없습니다' in error or '없거나 비어' in error):
        return jsonify({'success': False, 'error': error}), 400
    return jsonify({'success': False, 'error': error or 'card_after 생성 실패'}), 500

@app.route('/help')
def help():
    """신용카드 도움말 페이지"""
    return render_template('help.html')

def _get_daechae_info(df):
    """card_after DataFrame에서 대체거래 통계를 dict로 반환."""
    info = {'daechae_total_count': 0, 'daechae_bank_count': 0, 'daechae_card_count': 0, 'daechae_cancel_count': 0,
            'daechae_bank_deposit': 0, 'daechae_bank_withdraw': 0, 'daechae_card_deposit': 0, 'daechae_card_withdraw': 0,
            'daechae_cancel_deposit': 0, 'daechae_cancel_withdraw': 0,
            'daechae_total_deposit': 0, 'daechae_total_withdraw': 0, 'daechae_total_amount': 0, 'daechae_comment': ''}
    if df is None or df.empty or '대체구분' not in df.columns:
        return info
    dc = df['대체구분'].fillna('').astype(str).str.strip()
    df_dc = df[dc != '']
    if df_dc.empty:
        return info
    dc_vals = df_dc['대체구분'].fillna('').astype(str).str.strip()
    for label, mask in [('은행대체', dc_vals == '은행대체'), ('카드대체', dc_vals == '카드대체'), ('취소거래', dc_vals == '취소거래')]:
        cnt = int(mask.sum())
        dep = int(df_dc.loc[mask, '입금액'].sum()) if '입금액' in df_dc.columns else 0
        wit = int(df_dc.loc[mask, '출금액'].sum()) if '출금액' in df_dc.columns else 0
        if label == '은행대체':
            info['daechae_bank_count'], info['daechae_bank_deposit'], info['daechae_bank_withdraw'] = cnt, dep, wit
        elif label == '카드대체':
            info['daechae_card_count'], info['daechae_card_deposit'], info['daechae_card_withdraw'] = cnt, dep, wit
        else:
            info['daechae_cancel_count'], info['daechae_cancel_deposit'], info['daechae_cancel_withdraw'] = cnt, dep, wit
    info['daechae_total_count'] = info['daechae_bank_count'] + info['daechae_card_count'] + info['daechae_cancel_count']
    info['daechae_total_deposit'] = info['daechae_bank_deposit'] + info['daechae_card_deposit'] + info['daechae_cancel_deposit']
    info['daechae_total_withdraw'] = info['daechae_bank_withdraw'] + info['daechae_card_withdraw'] + info['daechae_cancel_withdraw']
    info['daechae_total_amount'] = info['daechae_total_deposit'] + info['daechae_total_withdraw']
    total_dep = int(pd.to_numeric(df['입금액'], errors='coerce').fillna(0).sum()) if '입금액' in df.columns else 0
    total_wit = int(pd.to_numeric(df['출금액'], errors='coerce').fillna(0).sum()) if '출금액' in df.columns else 0
    info['daechae_net_deposit'] = total_dep - info['daechae_total_deposit']
    info['daechae_net_withdraw'] = total_wit - info['daechae_total_withdraw']
    info['daechae_total_deposit_all'] = total_dep
    info['daechae_total_withdraw_all'] = total_wit
    info['daechae_comment'] = '신용카드 거래 중 대체거래(계좌 간 이체·환불 등)로 분류된 거래가 {}건으로 확인되었다. 자세한 내용은 금융정보 종합분석 보고서를 참조한다.'.format(info['daechae_total_count'])
    return info


@app.route('/analysis/print')
@ensure_working_directory
def print_analysis():
    """신용카드 기본분석 인쇄용 페이지"""
    try:
        bank_filter = request.args.get('bank', '')
        category_filter = request.args.get('category', '')  # 선택한 카테고리 (출력 시 사용)
        
        # 데이터 로드
        df = load_category_file()
        if df.empty:
            return "데이터가 없습니다.", 400
        
        # 카드사 필터 적용
        bank_col = '카드사' if '카드사' in df.columns else '은행명'
        if bank_filter and bank_col in df.columns:
            df = df[df[bank_col].astype(str).str.strip() == bank_filter]
        
        # 통계 계산
        total_count = len(df)
        deposit_count = len(df[df['입금액'] > 0])
        withdraw_count = len(df[df['출금액'] > 0])
        total_deposit = int(df['입금액'].sum())
        total_withdraw = int(df['출금액'].sum())
        net_balance = total_deposit - total_withdraw
        
        # 카테고리별 입출금 내역 (가나다순)
        if '카테고리' not in df.columns:
            df['카테고리'] = '(빈값)'
        df['카테고리'] = df['카테고리'].fillna('').astype(str).str.strip().replace('', '(빈값)')
        category_stats = df.groupby('카테고리').agg({
            '입금액': 'sum',
            '출금액': 'sum'
        }).reset_index()
        category_stats = category_stats.sort_values('카테고리', ascending=True)

        # 카테고리별 거래내역: 선택한 카테고리가 있으면 해당 카테고리, 없으면 출금액 최대 카테고리
        top_category = category_stats.loc[category_stats['출금액'].idxmax(), '카테고리'] if not category_stats.empty else ''
        selected_category = category_filter or ''
        if selected_category:
            trans_all = df[df['카테고리'] == selected_category]
            transaction_total_count = len(trans_all)
            transactions = trans_all
            transaction_deposit_total = int(trans_all['입금액'].sum())
            transaction_withdraw_total = int(trans_all['출금액'].sum())
            transaction_balance_total = transaction_deposit_total - transaction_withdraw_total
        else:
            transaction_total_count = 0
            transactions = pd.DataFrame()
            transaction_deposit_total = 0
            transaction_withdraw_total = 0
            transaction_balance_total = 0
        
        # 카드사별 통계
        bank_stats = df.groupby(bank_col).agg({
            '입금액': 'sum',
            '출금액': 'sum'
        }).reset_index()
        
        # 카드별 통계
        account_col = '카드번호' if '카드번호' in df.columns else '계좌번호'
        if account_col in df.columns:
            account_stats = df.groupby([bank_col, account_col]).agg({
                '입금액': 'sum',
                '출금액': 'sum'
            }).reset_index()
        else:
            account_stats = pd.DataFrame()
        
        # 카드사별 통계 막대그래프용 최대값 (세로 막대 높이 비율)
        max_deposit = int(bank_stats['입금액'].max()) if not bank_stats.empty else 1
        max_withdraw = int(bank_stats['출금액'].max()) if not bank_stats.empty else 1
        
        # 카테고리별 월그래프 테이블용: 월별 입금/출금 집계
        date_col = '이용일' if '이용일' in df.columns else '거래일'
        if date_col in df.columns:
            df_print = df.copy()
            df_print['_dt'] = pd.to_datetime(df_print[date_col], errors='coerce')
            df_print = df_print[df_print['_dt'].notna()]
            df_print['월'] = df_print['_dt'].dt.to_period('M').astype(str)
            monthly_totals = df_print.groupby('월').agg({'입금액': 'sum', '출금액': 'sum'}).reset_index()
            monthly_totals = monthly_totals.sort_values('월')
            months_list = monthly_totals['월'].tolist()
            monthly_totals_list = monthly_totals.to_dict('records')
            max_monthly_withdraw = int(monthly_totals['출금액'].max()) if not monthly_totals.empty else 1
            max_monthly_both = int(max(monthly_totals['입금액'].max(), monthly_totals['출금액'].max())) if not monthly_totals.empty else 1
        else:
            months_list = []
            monthly_totals_list = []
            max_monthly_withdraw = 1
            max_monthly_both = 1
        
        daechae_info = _get_daechae_info(df)

        return render_template('print_analysis.html',
                             report_date=datetime.now().strftime('%Y-%m-%d'),
                             bank_filter=bank_filter or '전체',
                             total_count=total_count,
                             deposit_count=deposit_count,
                             withdraw_count=withdraw_count,
                             total_deposit=total_deposit,
                             total_withdraw=total_withdraw,
                             net_balance=net_balance,
                             category_stats=category_stats.to_dict('records'),
                             transactions=transactions.to_dict('records'),
                             bank_stats=bank_stats.to_dict('records'),
                             account_stats=account_stats.to_dict('records'),
                             bank_col=bank_col,
                             account_col=account_col,
                             selected_category=selected_category,
                             max_deposit=max_deposit,
                             max_withdraw=max_withdraw,
                             transaction_total_count=transaction_total_count,
                             transaction_deposit_total=transaction_deposit_total,
                             transaction_withdraw_total=transaction_withdraw_total,
                             transaction_balance_total=transaction_balance_total,
                             months_list=months_list,
                             monthly_totals_list=monthly_totals_list,
                             max_monthly_withdraw=max_monthly_withdraw,
                             max_monthly_both=max_monthly_both,
                             **daechae_info)
        
    except Exception as e:
        traceback.print_exc()
        return f"오류 발생: {str(e)}", 500

# category_table(신용카드) 섹션 없으면 기본 규칙으로 생성 (모듈 로드 시 한 번)
_ensure_card_category_file()

if __name__ == '__main__':
    # 현재 디렉토리를 스크립트 위치로 변경
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)
    
    app.run(debug=True, port=5002, host='127.0.0.1')
