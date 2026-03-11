# -*- coding: utf-8 -*-
"""
은행거래 Flask 서브앱 (bank_app.py).

전처리 페이지·카테고리 페이지를 제공하고,
process_bank_data로 bank_after 생성 및 data 저장을 수행한다.
"""
from flask import Flask, render_template, jsonify, request, make_response
import traceback
import pandas as pd
from pathlib import Path
import sys
import os
from datetime import datetime

# ----- 인코딩 (Windows 콘솔 한글) -----
if sys.platform == 'win32':
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        ctypes.windll.kernel32.SetConsoleCP(65001)
    except (OSError, AttributeError):
        pass  # 콘솔 CP 설정 실패 시 무시(통합 서버에서 app.py가 이미 설정)

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
try:
    from lib.data_json_io import safe_read_data_json, safe_write_data_json
except ImportError:
    safe_read_data_json = None
    safe_write_data_json = None
try:
    from lib.shared_app_utils import BANK_FILTER_ALIASES, safe_취소 as _safe_취소
except ImportError:
    BANK_FILTER_ALIASES = {
        '국민은행': ['국민은행', 'KB국민은행', '한국주택은행', '국민', '국민 은행'],
        '신한은행': ['신한은행', '신한'],
        '하나은행': ['하나은행', '하나'],
    }
    def _safe_취소(val):
        if val is None or (isinstance(val, float) and pd.isna(val)): return ''
        s = str(val).strip()
        if s in ('', 'nan', 'None'): return ''
        if '취소' in s or '취소된 거래' in s: return '취소'
        return s
# category: MyRisk/data/category_table.json 하나만 사용 (category_table_io로 읽기/쓰기)
try:
    from lib.path_config import (
        get_category_table_json_path,
        get_bank_after_path,
        get_source_bank_dir,
    )
    CATEGORY_TABLE_PATH = get_category_table_json_path()
    BANK_AFTER_PATH = get_bank_after_path()
    SOURCE_BANK_DIR = get_source_bank_dir()
except ImportError:
    CATEGORY_TABLE_PATH = str(Path(PROJECT_ROOT) / 'data' / 'category_table.json')
    BANK_AFTER_PATH = str(Path(PROJECT_ROOT) / 'data' / 'bank_after.json')
    SOURCE_BANK_DIR = os.path.join(PROJECT_ROOT, '.source', 'Bank')
from lib.category_table_io import (
    load_category_table, normalize_category_df, CATEGORY_TABLE_COLUMNS,
    CATEGORY_TABLE_EXTENDED_COLUMNS,
    get_category_table as _io_get_category_table,
    apply_category_action,
    _to_str_no_decimal,
)
# 원본 은행 파일·after 경로: path_config에서 로드 (ImportError 시 위 fallback)


def _remove_bad_data_file(path, recreate_empty=None):
    """손상된 데이터 파일 삭제. .bak 생성하지 않음. recreate_empty가 (columns리스트)이면 빈 JSON 재생성."""
    p = Path(path)
    if p.exists() and p.stat().st_size > 0:
        try:
            p.unlink()
        except FileNotFoundError:
            pass
        except OSError as ex:
            winerr = getattr(ex, 'winerror', None)
            errno_val = getattr(ex, 'errno', None)
            if winerr == 32 or errno_val == 13:
                print(f"안내: {p.name}이(가) 다른 프로그램에서 열려 있어 삭제할 수 없습니다. 파일을 닫은 뒤 다시 시도하세요.", flush=True)
            elif winerr != 2 and errno_val != 2:
                print(f"삭제 실패 {p}: {ex}", flush=True)
    if recreate_empty is not None:
        try:
            from lib.data_json_io import safe_write_data_json
            empty = pd.DataFrame(columns=recreate_empty)
            safe_write_data_json(p, empty)
        except Exception as ex:
            # 빈 데이터 재생성 실패 시에도 삭제는 유지
            print(f"빈 데이터 파일 재생성 실패 {p}: {ex}", flush=True)


def _is_file_in_use_error(e):
    """다른 프로세스가 파일 사용 중으로 읽기 실패한 경우(백업/삭제 대상 아님)."""
    if isinstance(e, PermissionError):
        return True
    if isinstance(e, OSError):
        if getattr(e, 'winerror', None) == 32:
            return True
        if getattr(e, 'errno', None) in (13, 32):  # EACCES, EBUSY
            return True
    msg = str(e).lower()
    return '다른 프로세스' in msg or 'used by another' in msg or 'access is denied' in msg or '파일을 사용 중' in msg


def safe_read_excel(path, default_empty=True):
    """xlsx 파일을 안전하게 읽음. 손상/비xlsx 시에만 백업 후 빈 DataFrame 반환. 파일 없음·사용 중이면 백업하지 않음."""
    path = Path(path)
    if not path.exists():
        return pd.DataFrame() if default_empty else None
    if path.stat().st_size == 0:
        # 0바이트: 백업/삭제하지 않음(방금 생성 중이거나 비어 있는 상태일 수 있음)
        return pd.DataFrame() if default_empty else None
    try:
        return pd.read_excel(str(path), engine='openpyxl')
    except Exception as e:
        # 다른 프로세스 사용 중으로 읽기 실패한 경우: 백업/삭제하지 않고 빈 DataFrame만 반환
        if _is_file_in_use_error(e):
            return pd.DataFrame() if default_empty else None
        err_msg = str(e).lower()
        if _is_bad_zip_error(e):
            _remove_bad_data_file(path)
            return pd.DataFrame() if default_empty else None
        if 'zip' in err_msg or 'not a zip' in err_msg or 'decompress' in err_msg or 'invalid block' in err_msg:
            _remove_bad_data_file(path)
            return pd.DataFrame() if default_empty else None
        raise


# ----- 데코레이터·JSON 유틸·캐시 (공통 모듈 사용) -----
from lib.shared_app_utils import (
    make_ensure_working_directory,
    json_safe as _json_safe,
    is_bad_zip_error as _is_bad_zip_error,
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


def load_source_files():
    """MyRisk/.source/Bank 의 원본 파일 목록 가져오기. .xls, .xlsx만 취급."""
    return load_source_file_list(Path(SOURCE_BANK_DIR))

# 전처리전 source 캐시: .source/Bank를 한 번만 읽어 JSON 형태로 보관, 서버 종료 또는 reintegrate 시에만 무효화
_source_bank_cache = None

# bank_after 캐시 (lib.after_cache 공통. 재생성/clear 시 무효화)
_bank_after_cache_obj = AfterCache() if AfterCache else None

def _read_bank_after_raw(path):
    """bank_after 파일 읽기 + 컬럼 정규화 (캐시용)."""
    if safe_read_data_json:
        df = safe_read_data_json(path, default_empty=True)
    else:
        df = safe_read_excel(Path(path), default_empty=True)
    if df is None or df.empty:
        return df
    df = df.copy()
    df.columns = [str(c).strip().lstrip('\ufeff') for c in df.columns]
    if '구분' in df.columns and '취소' not in df.columns:
        df = df.rename(columns={'구분': '취소'})
    return df


def load_category_file():
    """카테고리 적용 파일 로드 (MyBank/bank_after.json). 캐시 있으면 재사용, 재생성 시에만 파일 재읽기."""
    if _bank_after_cache_obj is None:
        try:
            category_file = Path(BANK_AFTER_PATH)
            if not category_file.exists():
                return pd.DataFrame()
            df = _read_bank_after_raw(BANK_AFTER_PATH)
            return df if df is not None else pd.DataFrame()
        except Exception as e:
            print(f"Error in load_category_file: {str(e)}", flush=True)
            return pd.DataFrame()
    try:
        return _bank_after_cache_obj.get(BANK_AFTER_PATH, _read_bank_after_raw)
    except Exception as e:
        print(f"Error in load_category_file: {str(e)}", flush=True)
        return pd.DataFrame()

@app.route('/')
def index():
    # 카테고리 정의 테이블: 서버에서 HTML로 렌더링. 은행 카테고리 조회에서는 분류=심야구분/업종분류/위험도분류 제외.
    category_table_rows = []
    category_file_exists = False
    try:
        df, category_file_exists = _io_get_category_table(str(Path(CATEGORY_TABLE_PATH)))
        if df is not None and not df.empty:
            if '분류' in df.columns:
                분류_col = df['분류'].fillna('').astype(str).str.strip()
                df = df[~분류_col.isin(['심야구분', '업종분류', '위험도분류'])].copy()
            for c in CATEGORY_TABLE_EXTENDED_COLUMNS:
                if c not in df.columns:
                    df[c] = ''
            category_table_rows = df[CATEGORY_TABLE_EXTENDED_COLUMNS].fillna('').to_dict('records')
            for r in category_table_rows:
                r['업종코드'] = _to_str_no_decimal(r.get('업종코드'))
    except (OSError, ValueError, KeyError):
        category_file_exists = Path(CATEGORY_TABLE_PATH).exists()
    resp = make_response(render_template(
        'index.html',
        category_table_rows=category_table_rows,
        category_file_exists=category_file_exists,
    ))
    # 전처리 페이지 캐시 방지: 네비게이션 갱신이 바로 반영되도록
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['Expires'] = '0'
    return resp

@app.route('/favicon.ico')
def favicon():
    return '', 204

def _apply_bank_filter_for_analysis(df):
    """분석 API용: request의 bank 파라미터로 DataFrame 필터. 은행명 일치만 적용."""
    bank_filter = (request.args.get('bank') or '').strip()
    if not bank_filter or '은행명' not in df.columns:
        return df
    return df[df['은행명'].fillna('').astype(str).str.strip() == bank_filter].copy()


@app.route('/api/cache-info')
def get_cache_info():
    """캐시 이름·크기·총메모리 (금융정보 분석 시스템 헤더 표시용)."""
    try:
        caches = []
        total = 0
        if _source_bank_cache is not None:
            b = list_memory_bytes(_source_bank_cache)
            total += b
            caches.append({'name': 'bank_source', 'size_bytes': b})
        if _bank_after_cache_obj is not None and _bank_after_cache_obj.current is not None:
            b = df_memory_bytes(_bank_after_cache_obj.current)
            total += b
            caches.append({'name': 'bank_after', 'size_bytes': b})
        for c in caches:
            c['size_human'] = format_bytes(c['size_bytes'])
        return jsonify({
            'app': 'MyBank',
            'caches': caches,
            'total_bytes': total,
            'total_human': format_bytes(total),
        })
    except Exception as e:
        # 캐시 정보 수집 중 예외 시 에러 필드 포함해 200 반환
        return jsonify({'app': 'MyBank', 'caches': [], 'total_bytes': 0, 'total_human': '0 B', 'error': str(e)})

@app.route('/api/source-files')
@ensure_working_directory
def get_source_files():
    """원본 파일 목록 반환. MyRisk/.source/Bank 의 .xls, .xlsx만 취급."""
    try:
        current_dir = os.getcwd()
        source_dir = Path(SOURCE_BANK_DIR)
        if not source_dir.exists():
            return jsonify({
                'error': f'.source/Bank 폴더를 찾을 수 없습니다.\n현재 작업 디렉토리: {current_dir}\n.source/Bank 경로: {source_dir}',
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

def _create_empty_bank_after(path):
    """bank_after가 없을 때 빈 표준 컬럼 JSON 생성. 데이터 로딩 오류(Errno 2) 방지."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = ['거래일', '거래시간', '은행명', '계좌번호', '입금액', '출금액',
            '사업자번호', '폐업', '취소', '적요', '내용', '송금메모', '거래점', '키워드', '카테고리', '기타거래']
    empty = pd.DataFrame(columns=cols)
    if safe_write_data_json:
        safe_write_data_json(str(path), empty)
    else:
        empty.to_excel(str(path), index=False, engine='openpyxl')


def _remove_bank_after_and_bak():
    """통합·카테고리 다시 실행 전에 bank_after 삭제. 캐시 무효화 (bank_before 미사용)."""
    global _source_bank_cache
    _source_bank_cache = None
    if _bank_after_cache_obj is not None:
        _bank_after_cache_obj.invalidate()
    p = Path(BANK_AFTER_PATH)
    try:
        if p.exists():
            p.unlink()
    except OSError:
        pass


@app.route('/api/clear-cache', methods=['POST'])
@ensure_working_directory
def clear_cache_bank():
    """선택한 JSON만 삭제. body: { \"before\": bool, \"after\": bool } — before: bank_before.json 삭제, after: bank_after.json 삭제."""
    try:
        data = request.get_json(force=True, silent=True) or {}
        clear_before = data.get('before', False)
        clear_after = data.get('after', False)
        global _source_bank_cache
        if clear_before:
            _source_bank_cache = None
            p_before = Path(os.path.join(os.path.dirname(BANK_AFTER_PATH), 'bank_before.json'))
            try:
                if p_before.exists():
                    p_before.unlink()
            except OSError:
                pass
        if clear_after:
            if _bank_after_cache_obj is not None:
                _bank_after_cache_obj.invalidate()
            p = Path(BANK_AFTER_PATH)
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
def reintegrate_bank():
    """bank_after를 .source/Bank 기준으로 다시 통합·전처리·분류·후처리하여 덮어쓴다. 카드와 동일하게 전처리 실행 시 bank_before.json 생성 후 bank_after 생성."""
    try:
        global _source_bank_cache
        _source_bank_cache = None
        _remove_bank_after_and_bak()
        _path_added = False
        try:
            _dir_str = str(SCRIPT_DIR)
            if _dir_str not in sys.path:
                sys.path.insert(0, _dir_str)
                _path_added = True
            import process_bank_data as _pbd
            _pbd.ensure_bank_before_and_category()
            df = _pbd.integrate_bank_transactions()
            if df is None or df.empty:
                return jsonify({
                    'ok': False,
                    'error': getattr(_pbd, 'LAST_INTEGRATE_ERROR', None) or '통합·전처리 결과가 비어 있습니다. .source/Bank 파일명에 국민은행·신한은행·하나은행이 포함되는지 확인하세요.'
                }), 400
            success, detail, _ = _pbd.classify_and_save(input_df=df)
            if not success:
                return jsonify({'ok': False, 'error': detail or 'bank_after 생성 실패'}), 500
        except Exception as e:
            return jsonify({'ok': False, 'error': str(e)}), 500
        finally:
            if _path_added and str(SCRIPT_DIR) in sys.path:
                sys.path.remove(str(SCRIPT_DIR))
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/processed-data')
@ensure_working_directory
def get_processed_data():
    """은행 데이터 반환 (bank_after만 사용, 필터링 지원). 캐시 있으면 ensure 생략."""
    try:
        output_path = Path(BANK_AFTER_PATH).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        # 캐시 없을 때: bank_after 없거나 비면 자동으로 before → after 순차 생성 (버튼 없이 자동 진행)
        if _bank_after_cache_obj is None or _bank_after_cache_obj.current is None:
            _path_added = False
            try:
                _dir_str = str(SCRIPT_DIR)
                if _dir_str not in sys.path:
                    sys.path.insert(0, _dir_str)
                    _path_added = True
                import process_bank_data as _pbd
                _pbd.ensure_bank_before_and_category()
                # after 없거나 비어 있으면 자동으로 전처리(before) → 카테고리적용(after) 순차 실행
                if not output_path.exists() or output_path.stat().st_size <= 2:
                    df = _pbd.integrate_bank_transactions()
                    if df is not None and not df.empty:
                        _pbd.classify_and_save(input_df=df)
                    elif not output_path.exists():
                        _create_empty_bank_after(output_path)
            except Exception as e:
                error_msg = str(e)
                hint = []
                if 'bank_after' in error_msg or 'PermissionError' in error_msg or '사용 중' in error_msg:
                    hint.append('bank_after.json을 열어둔 프로그램을 닫아주세요.')
                if 'xlrd' in error_msg or 'No module' in error_msg:
                    hint.append('.xls 파일 읽기에는 xlrd 패키지가 필요합니다: pip install xlrd')
                extra = '\n' + '\n'.join(hint) if hint else ''
                return jsonify({
                    'error': f'파일 생성 실패: {error_msg}{extra}',
                    'count': 0,
                    'deposit_amount': 0,
                    'withdraw_amount': 0,
                    'data': []
                }), 500
            finally:
                if _path_added and str(SCRIPT_DIR) in sys.path:
                    sys.path.remove(str(SCRIPT_DIR))

        df = load_category_file()
        category_file_exists = output_path.exists()

        if df.empty:
            # 데이터 없음 시 추출 실패 이유(LAST_INTEGRATE_ERROR)를 함께 반환해 화면에 표시
            integrate_reason = None
            try:
                import process_bank_data as _pbd_reason
                integrate_reason = getattr(_pbd_reason, 'LAST_INTEGRATE_ERROR', None) or None
                if integrate_reason and not isinstance(integrate_reason, str):
                    integrate_reason = None
            except Exception:
                pass  # 사유 조회 실패 시 None 유지
            response = jsonify({
                'total': 0,
                'count': 0,
                'deposit_amount': 0,
                'withdraw_amount': 0,
                'deposit_count': 0,
                'withdraw_count': 0,
                'data': [],
                'file_exists': category_file_exists,
                'integrate_reason': (integrate_reason.strip() if integrate_reason else None)
            })
    
            return response

        # 카테고리 조회 테이블용: 키워드·카테고리·기타거래 없으면 빈 컬럼 추가
        for col in ['키워드', '카테고리', '기타거래']:
            if col not in df.columns:
                df[col] = ''

        # 필터 파라미터
        bank_filter = (request.args.get('bank') or '').strip()
        date_filter = request.args.get('date', '')
        account_filter = (request.args.get('account') or '').strip()
        
        # 은행 필터: bank_after의 '은행명' 컬럼에서 적용
        bank_col = next((c for c in df.columns if str(c).strip() == '은행명'), None)
        if bank_filter and bank_col is not None:
            allowed = set(BANK_FILTER_ALIASES.get(bank_filter, [bank_filter]))
            s = df[bank_col].fillna('').astype(str).str.strip()
            df = df[s.isin(allowed)].copy()
        
        if date_filter:
            d = date_filter.replace('-', '').replace('/', '')
            s = df['거래일'].astype(str).str.replace(r'[\s\-/.]', '', regex=True)
            df = df[s.str.startswith(d, na=False)]
        
        if account_filter and '계좌번호' in df.columns:
            df = df[df['계좌번호'].fillna('').astype(str).str.strip() == account_filter]
        
        # 집계 계산 (전체 필터된 데이터 기준)
        count = len(df)
        deposit_amount = df['입금액'].sum() if not df.empty else 0
        withdraw_amount = df['출금액'].sum() if not df.empty else 0
        deposit_count = int((pd.to_numeric(df['입금액'], errors='coerce').fillna(0) > 0).sum()) if not df.empty and '입금액' in df.columns else 0
        withdraw_count = int((pd.to_numeric(df['출금액'], errors='coerce').fillna(0) > 0).sum()) if not df.empty and '출금액' in df.columns else 0

        # NaN 값을 None으로 변환
        df = df.where(pd.notna(df), None)
        # 취소 컬럼 정규화: nan/'nan'/'취소된 거래' → '' 또는 '취소'
        if '취소' in df.columns:
            df['취소'] = df['취소'].apply(_safe_취소)

        total = len(df)
        limit = request.args.get('limit', type=int)
        offset = request.args.get('offset', type=int) or 0
        if limit and limit > 0:
            df_slice = df.iloc[offset:offset + limit]
        else:
            df_slice = df.iloc[offset:]
        data = df_slice.to_dict('records')
        data = _json_safe(data)
        resp_payload = {
            'total': total,
            'count': len(data),
            'deposit_amount': int(deposit_amount),
            'withdraw_amount': int(withdraw_amount),
            'deposit_count': deposit_count,
            'withdraw_count': withdraw_count,
            'data': data,
            'file_exists': category_file_exists
        }
        response = jsonify(resp_payload)

        return response
    except Exception as e:
        traceback.print_exc()
        category_file_exists = Path(BANK_AFTER_PATH).exists()
        return jsonify({
            'error': str(e),
            'total': 0,
            'count': 0,
            'deposit_amount': 0,
            'withdraw_amount': 0,
            'deposit_count': 0,
            'withdraw_count': 0,
            'data': [],
            'file_exists': category_file_exists
        }), 500


@app.route('/api/simya-ranges')
@ensure_working_directory
def get_simya_ranges():
    """category_table.json에서 분류=심야구분인 행의 키워드(시작/종료 hh:mm:ss)를 파싱하여 반환."""
    try:
        df = load_category_table(CATEGORY_TABLE_PATH, default_empty=True)
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
            if start_sec is None or end_sec is None:
                continue
            if start_sec == 0 or end_sec == 0:
                continue
            ranges.append({'start': start_s if ':' in start_s else f'{start_s[0:2]}:{start_s[2:4]}:{start_s[4:6]}', 'end': end_s if ':' in end_s else f'{end_s[0:2]}:{end_s[2:4]}:{end_s[4:6]}'})
        return jsonify({'ranges': ranges})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'ranges': [], 'error': str(e)})


@app.route('/api/category-applied-data')
@ensure_working_directory
def get_category_applied_data():
    """카테고리 적용된 데이터 반환 (필터링 지원). 캐시 있으면 즉시 반환, 없을 때만 ensure 후 로드."""
    try:
        category_file_exists = Path(BANK_AFTER_PATH).exists()
        # 캐시 있으면 ensure 생략하여 테이블 로딩 시간 단축 (재생성 버튼 시에만 캐시 무효화)
        if _bank_after_cache_obj is None or _bank_after_cache_obj.current is None:
            _path_added = False
            try:
                _dir_str = str(SCRIPT_DIR)
                if _dir_str not in sys.path:
                    sys.path.insert(0, _dir_str)
                    _path_added = True
                import process_bank_data as _pbd
                _pbd.ensure_bank_before_and_category()
            except Exception as _e:
                print(f"[WARN] ensure_bank_before_and_category 실패: {_e}", flush=True)
            finally:
                if _path_added and str(SCRIPT_DIR) in sys.path:
                    sys.path.remove(str(SCRIPT_DIR))
        
        try:
            df = load_category_file()
        except Exception as e:
            print(f"Error loading category file: {str(e)}")
            traceback.print_exc()
            # 파일 로드 실패 시 빈 DataFrame 반환
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
        
        # 필터 파라미터 (전처리후 은행/계좌에 따라 필터링)
        bank_filter = (request.args.get('bank') or '').strip()
        date_filter = request.args.get('date', '')
        account_filter = (request.args.get('account') or '').strip()
        
        # 필터 적용
        if bank_filter and '은행명' in df.columns:
            allowed = set(BANK_FILTER_ALIASES.get(bank_filter, [bank_filter]))
            s = df['은행명'].fillna('').astype(str).str.strip()
            df = df[s.isin(allowed)].copy()
        
        if account_filter and '계좌번호' in df.columns:
            df = df[df['계좌번호'].fillna('').astype(str).str.strip() == account_filter]
        
        if date_filter and '거래일' in df.columns:
            try:
                # 거래일 컬럼을 안전하게 문자열로 변환
                df['거래일_str'] = df['거래일'].astype(str)
                df = df[df['거래일_str'].str.startswith(date_filter, na=False)]
                df = df.drop('거래일_str', axis=1)
            except (TypeError, ValueError, KeyError) as e:
                # 날짜 필터링 실패 시 필터 없이 진행
                print(f"Error filtering by date: {str(e)}")
        
        # 필수 컬럼 확인
        required_columns = ['입금액', '출금액']
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns and not df.empty:
            print(f"Warning: Missing columns in data: {missing_columns}")
            for col in missing_columns:
                df[col] = 0
        # 카테고리 적용후 테이블용: 키워드·카테고리·기타거래 없으면 빈 컬럼 추가
        for col in ['키워드', '카테고리', '기타거래']:
            if col not in df.columns:
                df[col] = ''

        # 집계 계산 (필터 적용 후 전체 기준)
        count = len(df)
        deposit_amount = df['입금액'].sum() if not df.empty and '입금액' in df.columns else 0
        withdraw_amount = df['출금액'].sum() if not df.empty and '출금액' in df.columns else 0
        dep_series = pd.to_numeric(df['입금액'], errors='coerce').fillna(0) if not df.empty and '입금액' in df.columns else pd.Series(dtype=float)
        wit_series = pd.to_numeric(df['출금액'], errors='coerce').fillna(0) if not df.empty and '출금액' in df.columns else pd.Series(dtype=float)
        deposit_count = int((dep_series > 0).sum())
        withdraw_count = int((wit_series > 0).sum())
        
        df = df.where(pd.notna(df), None)
        # 취소 컬럼 정규화: nan/'nan'/'취소된 거래' → '' 또는 '취소'
        if '취소' in df.columns:
            df['취소'] = df['취소'].apply(_safe_취소)
        # 카테고리 적용후 테이블: 거래일/거래시간 다나가 순(내림), 은행명 가나다 순(오름)
        sort_cols = []
        ascending = []
        if '거래일' in df.columns:
            sort_cols.append('거래일')
            ascending.append(False)
        if '거래시간' in df.columns:
            sort_cols.append('거래시간')
            ascending.append(False)
        if '은행명' in df.columns:
            sort_cols.append('은행명')
            ascending.append(True)
        if '계좌번호' in df.columns:
            sort_cols.append('계좌번호')
            ascending.append(True)
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
        category_file_exists = Path(BANK_AFTER_PATH).exists()
        return jsonify({
            'error': str(e),
            'count': 0,
            'deposit_amount': 0,
            'withdraw_amount': 0,
            'data': [],
            'file_exists': category_file_exists
        }), 500

def _build_source_bank_cache():
    """MyRisk/.source/Bank 의 .xls, .xlsx를 읽어 전처리전 source 캐시(리스트)를 채운다. 실패 시 None.
    전처리 실행(bank_before 생성)과 동일한 파일만 표시: 파일명에 국민은행·신한은행·하나은행이 포함된 것만."""
    global _source_bank_cache
    source_dir = Path(SOURCE_BANK_DIR)
    if not source_dir.exists():
        return None
    xls_files = list(source_dir.glob('*.xls')) + list(source_dir.glob('*.xlsx'))
    xls_files = sorted(set(xls_files), key=lambda p: (p.name, str(p)))
    # 전처리 실행 시 사용하는 파일과 동일: 은행명 포함 파일만 (전처리전에 나왔으면 반드시 before 생성 가능하도록)
    xls_files = [p for p in xls_files if '국민은행' in p.name or '신한은행' in p.name or '하나은행' in p.name]
    if not xls_files:
        return None
    all_data = []
    for file_path in xls_files:
        filename = file_path.name
        bank_name = None
        if '국민은행' in filename:
            bank_name = '국민은행'
        elif '신한은행' in filename:
            bank_name = '신한은행'
        elif '하나은행' in filename:
            bank_name = '하나은행'
        try:
            xls = pd.ExcelFile(file_path)
            for sheet_name in xls.sheet_names:
                try:
                    df = pd.read_excel(file_path, sheet_name=sheet_name, header=None)
                    df = df.where(pd.notna(df), None)
                    data_dict = df.to_dict('records')
                    data_dict = _json_safe(data_dict)
                    sheet_data = {
                        'filename': filename,
                        'sheet_name': sheet_name,
                        'bank': bank_name,
                        'data': data_dict
                    }
                    all_data.append(sheet_data)
                except Exception:
                    continue
        except Exception:
            continue
    _source_bank_cache = all_data
    return _source_bank_cache


@app.route('/api/source-data')
@ensure_working_directory
def get_source_data():
    """원본 파일 데이터 반환 (필터링 지원). 전처리전 source는 한 번만 읽어 캐시 후 재활용. 재생성 버튼 시 캐시 무효화."""
    try:
        global _source_bank_cache
        source_dir = Path(SOURCE_BANK_DIR)
        current_dir = os.getcwd()
        if not source_dir.exists():
            return jsonify({
                'error': f'.source/Bank 폴더를 찾을 수 없습니다.\n현재 작업 디렉토리: {current_dir}\n.source/Bank 경로: {source_dir}',
                'count': 0,
                'deposit_amount': 0,
                'withdraw_amount': 0,
                'files': []
            }), 404

        bank_filter = request.args.get('bank', '')
        date_filter = request.args.get('date', '')

        if _source_bank_cache is None:
            _build_source_bank_cache()
        if _source_bank_cache is None:
            return jsonify({
                'error': f'.source/Bank 폴더에 .xls, .xlsx 파일이 없습니다.\n현재 작업 디렉토리: {current_dir}\n.source/Bank 경로: {source_dir}',
                'count': 0,
                'deposit_amount': 0,
                'withdraw_amount': 0,
                'files': []
            }), 404

        # 캐시에서 은행 필터만 적용하여 반환
        filtered = [s for s in _source_bank_cache if not bank_filter or s.get('bank') == bank_filter]
        count = sum(len(s['data']) for s in filtered)
        deposit_amount = 0
        withdraw_amount = 0

        response = jsonify({
            'count': count,
            'deposit_amount': int(deposit_amount),
            'withdraw_amount': int(withdraw_amount),
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

# 카테고리: MyRisk/data/category_table.json 단일 테이블(구분 없음, 은행/신용카드 공통)
@app.route('/api/category')
@ensure_working_directory
def get_category_table():
    """category_table.json 전체 반환 (구분 없음). 없으면 생성 후 반환."""
    path = Path(CATEGORY_TABLE_PATH)
    try:
        _path_added = False
        try:
            _dir_str = str(SCRIPT_DIR)
            if _dir_str not in sys.path:
                sys.path.insert(0, _dir_str)
                _path_added = True
            import process_bank_data as _pbd
            _pbd.ensure_bank_before_and_category()
            if path.exists():
                _pbd.migrate_bank_category_file(str(path))
        except Exception as _e:
            if str(path).endswith('.json'):
                try:
                    if path.exists() and path.stat().st_size > 0:
                        path.unlink()
                    from lib.category_table_io import create_empty_category_table
                    create_empty_category_table(str(path))
                except Exception:
                    pass  # 빈 테이블 생성 실패 시 응답 계속
            else:
                raise
        finally:
            if _path_added and str(SCRIPT_DIR) in sys.path:
                sys.path.remove(str(SCRIPT_DIR))

        df, file_existed = _io_get_category_table(str(path))
        cols = CATEGORY_TABLE_COLUMNS
        if file_existed and (df is None or df.empty) and path.exists() and path.stat().st_size > 0:
            if str(path).endswith('.json'):
                try:
                    path.unlink()
                    from lib.category_table_io import create_empty_category_table
                    create_empty_category_table(str(path))
                except Exception:
                    pass  # 손상 파일 삭제 후 빈 테이블 생성 실패 시 응답 계속
            df = pd.DataFrame(columns=cols)
        if len(df) == 0 and path.exists():
            _orig_cwd = os.getcwd()
            try:
                if str(SCRIPT_DIR) not in sys.path:
                    sys.path.insert(0, str(SCRIPT_DIR))
                import process_bank_data as _pbd_fill
                os.chdir(SCRIPT_DIR)
                _pbd_fill.create_category_table(pd.DataFrame())
                df, _ = _io_get_category_table(str(path))
            except Exception:
                pass  # create_category_table 실패 시 빈 df 유지
            finally:
                os.chdir(_orig_cwd)
        if df is None or df.empty:
            df = pd.DataFrame(columns=cols)
        # 은행 카테고리 조회: 분류=심야구분/업종분류/위험도분류 제외, 5컬럼(위험도·업종코드 포함) 반환
        if not df.empty and '분류' in df.columns:
            분류_col = df['분류'].fillna('').astype(str).str.strip()
            df = df[~분류_col.isin(['심야구분', '업종분류', '위험도분류'])].copy()
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
        err_msg = str(e).lower()
        if str(path).endswith('.json'):
            try:
                if path.exists() and path.stat().st_size > 0:
                    path.unlink()
                from lib.category_table_io import create_empty_category_table
                create_empty_category_table(str(path))
            except Exception as _e:
                print(f"[WARN] category_table 빈 파일 생성 실패: {_e}", flush=True)
            df = pd.DataFrame(columns=['분류', '키워드', '카테고리'])
            response = jsonify({
                'data': df.to_dict('records'),
                'columns': ['분류', '키워드', '카테고리'],
                'count': 0,
                'file_exists': True
            })
    
            return response
        file_exists = path.exists()
        response = jsonify({
            'error': str(e),
            'data': [],
            'file_exists': file_exists
        })

        return response, 500

@app.route('/api/category', methods=['POST'])
@ensure_working_directory
def save_category_table():
    """category_table.json 전체 갱신 (구분 없음)"""
    try:
        path = str(Path(CATEGORY_TABLE_PATH))
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

@app.route('/analysis/print')
@ensure_working_directory
def print_analysis():
    """은행거래 기본분석 인쇄용 페이지 (bank_after.xlsx 사용, 신용카드 기본분석과 동일 양식)"""
    try:
        bank_filter = request.args.get('bank', '')
        category_filter = request.args.get('category', '')  # 선택한 카테고리 (출력 시 사용)

        df = load_category_file()
        if df.empty:
            return "데이터가 없습니다.", 400

        if bank_filter and '은행명' in df.columns:
            df = df[df['은행명'].astype(str).str.strip() == bank_filter]

        total_count = len(df)
        deposit_count = int((pd.to_numeric(df['입금액'], errors='coerce').fillna(0) > 0).sum())
        withdraw_count = int((pd.to_numeric(df['출금액'], errors='coerce').fillna(0) > 0).sum())
        total_deposit = int(df['입금액'].sum())
        total_withdraw = int(df['출금액'].sum())
        net_balance = total_deposit - total_withdraw

        # 카테고리별 입출금 내역 (bank_after의 카테고리 컬럼 기준)
        category_col = '카테고리' if '카테고리' in df.columns else '적요'
        if category_col not in df.columns:
            df[category_col] = '(빈값)'
        df[category_col] = df[category_col].fillna('').astype(str).str.strip().replace('', '(빈값)')
        category_stats = df.groupby(category_col).agg({
            '입금액': 'sum',
            '출금액': 'sum'
        }).reset_index()
        category_stats = category_stats.rename(columns={category_col: '카테고리'})
        category_stats['차액'] = category_stats['입금액'] - category_stats['출금액']
        # 프린터: 카테고리 가나다순
        category_stats = category_stats.sort_values('카테고리', ascending=True)

        top_category = category_stats.iloc[0]['카테고리'] if not category_stats.empty else ''
        selected_category = category_filter or ''
        if selected_category:
            trans_all = df[df[category_col] == selected_category]
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

        bank_col = '은행명'
        bank_stats = df.groupby(bank_col).agg({
            '입금액': 'sum',
            '출금액': 'sum'
        }).reset_index()
        bank_stats['차액'] = bank_stats['입금액'] - bank_stats['출금액']

        account_col = '계좌번호'
        if account_col in df.columns:
            account_stats = df.groupby([bank_col, account_col]).agg({
                '입금액': 'sum',
                '출금액': 'sum'
            }).reset_index()
            account_stats['차액'] = account_stats['입금액'] - account_stats['출금액']
            # 출력용: 계좌번호 뒤 6자리 (그래픽 레이블/범례와 동일)
            acc_ser = account_stats[account_col].astype(str).str.strip()
            account_stats['account_short'] = acc_ser.apply(lambda x: x[-6:] if len(x) > 6 else x)
        else:
            account_stats = pd.DataFrame()

        max_deposit = int(bank_stats['입금액'].max()) if not bank_stats.empty else 1
        max_withdraw = int(bank_stats['출금액'].max()) if not bank_stats.empty else 1
        max_account_deposit = int(account_stats['입금액'].max()) if not account_stats.empty and '입금액' in account_stats.columns else 1
        max_account_withdraw = int(account_stats['출금액'].max()) if not account_stats.empty and '출금액' in account_stats.columns else 1
        total_account_deposit = int(account_stats['입금액'].sum()) if not account_stats.empty and '입금액' in account_stats.columns else 0
        total_account_withdraw = int(account_stats['출금액'].sum()) if not account_stats.empty and '출금액' in account_stats.columns else 0
        total_account_deposit_10 = int(account_stats.head(10)['입금액'].sum()) if not account_stats.empty and '입금액' in account_stats.columns else 0
        total_account_withdraw_10 = int(account_stats.head(10)['출금액'].sum()) if not account_stats.empty and '출금액' in account_stats.columns else 0

        date_col = '거래일'
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
                             max_account_deposit=max_account_deposit,
                             max_account_withdraw=max_account_withdraw,
                             total_account_deposit=total_account_deposit,
                             total_account_withdraw=total_account_withdraw,
                             total_account_deposit_10=total_account_deposit_10,
                             total_account_withdraw_10=total_account_withdraw_10,
                             transaction_total_count=transaction_total_count,
                             transaction_deposit_total=transaction_deposit_total,
                             transaction_withdraw_total=transaction_withdraw_total,
                             transaction_balance_total=transaction_balance_total,
                             months_list=months_list,
                             monthly_totals_list=monthly_totals_list,
                             max_monthly_withdraw=max_monthly_withdraw,
                             max_monthly_both=max_monthly_both)
    except Exception as e:
        traceback.print_exc()
        return f"오류 발생: {str(e)}", 500

# 분석 API 라우트
@app.route('/api/analysis/summary')
@ensure_working_directory
def get_analysis_summary():
    try:
        df = load_category_file()
        if df.empty:
            return jsonify(compute_summary(df))
        df = _apply_bank_filter_for_analysis(df)
        return jsonify(compute_summary(df))
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/analysis/by-category')
@ensure_working_directory
def get_analysis_by_category():
    try:
        df = load_category_file()
        if df.empty:
            return jsonify({'data': []})
        df = _apply_bank_filter_for_analysis(df)
        df = apply_category_filters(df,
            입출금_filter=request.args.get('입출금', ''),
            거래유형_filter=request.args.get('거래유형', ''),
            카테고리_filter=request.args.get('카테고리', ''),
            category_type=request.args.get('category_type', ''),
            category_value=request.args.get('category_value', ''))
        return jsonify({'data': compute_by_category(df, bank_col='은행명', include_category_filter=True)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/analysis/by-category-group')
@ensure_working_directory
def get_analysis_by_category_group():
    try:
        df = load_category_file()
        if df.empty:
            return jsonify({'data': []})
        df = _apply_bank_filter_for_analysis(df)
        df = apply_category_filters(df,
            입출금_filter=request.args.get('입출금', ''),
            거래유형_filter=request.args.get('거래유형', ''),
            카테고리_filter=request.args.get('카테고리', ''))
        return jsonify({'data': compute_by_category_group(df, bank_col='은행명', include_category_groupby=True)})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/analysis/by-month')
@ensure_working_directory
def get_analysis_by_month():
    try:
        df = load_category_file()
        if df.empty:
            return jsonify({'months': [], 'deposit': [], 'withdraw': [], 'min_date': None, 'max_date': None})
        df = _apply_bank_filter_for_analysis(df)
        df = apply_category_filters(df,
            입출금_filter=request.args.get('입출금', ''),
            거래유형_filter=request.args.get('거래유형', ''),
            카테고리_filter=request.args.get('카테고리', ''),
            category_type=request.args.get('category_type', ''),
            category_value=request.args.get('category_value', ''))
        return jsonify(compute_by_month(df))
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/analysis/by-category-monthly')
@ensure_working_directory
def get_analysis_by_category_monthly():
    try:
        df = load_category_file()
        if df.empty:
            return jsonify({'months': [], 'categories': []})
        df = _apply_bank_filter_for_analysis(df)
        df = apply_category_filters(df,
            입출금_filter=request.args.get('입출금', ''),
            거래유형_filter=request.args.get('거래유형', ''),
            카테고리_filter=request.args.get('카테고리', ''))
        return jsonify(compute_by_category_monthly(df, include_category_groupby=True, label_cols=['거래유형', '카테고리']))
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e), 'months': [], 'categories': []}), 500

@app.route('/api/analysis/by-content')
@ensure_working_directory
def get_analysis_by_content():
    try:
        df = load_category_file()
        return jsonify(compute_by_content(df))
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/analysis/by-division')
@ensure_working_directory
def get_analysis_by_division():
    try:
        df = load_category_file()
        return jsonify({'data': compute_by_division(df, division_col='취소', normalizer=_safe_취소)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/analysis/by-bank')
@ensure_working_directory
def get_analysis_by_bank():
    try:
        df = load_category_file()
        if df.empty:
            return jsonify({'bank': [], 'account': []})
        df = _apply_bank_filter_for_analysis(df)
        if '계좌번호' not in df.columns:
            df['계좌번호'] = ''
        return jsonify(compute_by_bank(df, bank_col='은행명', account_col='계좌번호', include_count=True))
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/analysis/transactions-by-content')
@ensure_working_directory
def get_transactions_by_content():
    try:
        df = load_category_file()
        if df.empty:
            return jsonify({'data': []})
        type_filter = request.args.get('type', 'deposit')
        limit = int(request.args.get('limit', 10))
        amt_col = '입금액' if type_filter == 'deposit' else '출금액'
        out_cols = ['거래일', '은행명', amt_col, '취소', '적요', '내용', '거래점']
        data = compute_transactions_by_content(df, type_filter=type_filter, limit=limit,
            bank_col='은행명', content_col='내용', division_col='취소',
            output_cols=out_cols, json_safe_fn=_json_safe)
        return jsonify({'data': data})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/analysis/transactions')
@ensure_working_directory
def get_analysis_transactions():
    try:
        df = load_category_file()
        if df.empty:
            return jsonify({'data': [], 'deposit_total': 0, 'withdraw_total': 0, 'balance': 0, 'deposit_count': 0, 'withdraw_count': 0})
        filter_col = '카테고리' if '카테고리' in df.columns else '적요'
        extra_col = '기타거래' if '기타거래' in df.columns else '내용'
        return jsonify(compute_transactions(df,
            transaction_type=request.args.get('type', 'deposit'),
            category_filter=request.args.get('category', ''),
            content_filter=request.args.get('content', ''),
            bank_filter=request.args.get('bank', ''),
            category_type=request.args.get('category_type', ''),
            category_value=request.args.get('category_value', ''),
            bank_col='은행명', date_col='거래일',
            filter_col=filter_col, extra_col=extra_col,
            json_safe_fn=_json_safe))
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/analysis/content-by-category')
@ensure_working_directory
def get_content_by_category():
    try:
        df = load_category_file()
        filter_col = '카테고리' if '카테고리' in df.columns else '적요'
        data = compute_content_by_category(df, filter_col=filter_col, category_filter=request.args.get('category', ''))
        return jsonify({'data': data})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/analysis/date-range')
@ensure_working_directory
def get_date_range():
    try:
        df = load_category_file()
        return jsonify(compute_date_range(df))
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def _json_500(obj):
    """500 응답도 JSON으로 통일."""
    r = jsonify(obj)
    return r, 500

@app.route('/api/generate-category', methods=['POST'])
@ensure_working_directory
def generate_category():
    """카테고리 자동 생성 실행. 항상 JSON 반환."""
    try:
        # process_bank_data.py 같은 프로세스에서 실행 (subprocess 시 debugpy/venv 오류 방지)
        script_path = Path(SCRIPT_DIR) / 'process_bank_data.py'
        if not script_path.exists():
            return _json_500({
                'success': False,
                'error': f'process_bank_data.py 파일을 찾을 수 없습니다. 경로: {script_path}'
            })
        
        _orig_cwd = os.getcwd()
        _path_added = False
        detail = None
        success = False
        count = None
        try:
            os.chdir(SCRIPT_DIR)
            _dir_str = str(SCRIPT_DIR)
            if _dir_str not in sys.path:
                sys.path.insert(0, _dir_str)
                _path_added = True
            import process_bank_data as _pbd
            _pbd.ensure_bank_before_and_category()  # bank_before, category_table 준비 (생성 시에만 카테고리 분류)
            # 이미 확보된 df가 있으면 넘겨서 integrate 중복 호출 방지
            _df = None
            if Path(BANK_AFTER_PATH).exists() and safe_read_data_json:
                _df = safe_read_data_json(BANK_AFTER_PATH, default_empty=True)
            if _df is not None and not _df.empty:
                success, detail, count = _pbd.classify_and_save(input_df=_df)
            else:
                success, detail, count = _pbd.classify_and_save()
        except Exception as e:
            success = False
            detail = str(e)
            count = 0
            traceback.print_exc()
        finally:
            os.chdir(_orig_cwd)
            if _path_added and str(SCRIPT_DIR) in sys.path:
                sys.path.remove(str(SCRIPT_DIR))
        
        if not success:
            err_msg = '카테고리 분류 중 오류가 발생했습니다.'
            if detail:
                err_msg += '\n[원인] ' + detail
            return _json_500({'success': False, 'error': err_msg})
        
        # bank_after 생성 성공 (count는 classify_and_save 반환값 사용)
        output_path = Path(BANK_AFTER_PATH)
        if output_path.exists() or count is not None:
            resp = jsonify({
                'success': True,
                'message': f'카테고리 생성 완료: {count or 0}건',
                'count': count or 0
            })
            return resp
        return _json_500({
            'success': False,
            'error': f'bank_after 파일이 생성되지 않았습니다. 경로: {output_path}'
        })
    except FileNotFoundError as e:
        return _json_500({'success': False, 'error': f'파일을 찾을 수 없습니다: {str(e)}'})
    except Exception as e:
        error_trace = traceback.format_exc()
        return _json_500({
            'success': False,
            'error': f'{str(e)}\n상세 정보는 서버 로그를 확인하세요.'
        })

@app.route('/help')
def help():
    """은행거래 도움말 페이지"""
    return render_template('help.html')

if __name__ == '__main__':
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)
    # use_reloader=False: 프로젝트 루트에서 실행 시 리로더가 잘못된 경로로 재실행되어 실패하는 것 방지
    app.run(debug=True, port=5001, host='127.0.0.1', use_reloader=False)
