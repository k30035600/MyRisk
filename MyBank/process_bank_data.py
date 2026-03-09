# -*- coding: utf-8 -*-
"""
은행거래 전처리·분류·저장 (process_bank_data.py)

[역할]
- .source/Bank 엑셀 → 통합·전처리·계정과목 분류·후처리 → data/bank_after.json 저장.
- bank_before는 중간 산출물로만 사용 가능; 앱에서는 bank_after만 노출.

[주요 함수]
- integrate_bank_transactions(): .source/Bank xls/xlsx 읽기·통합·전처리(category_table '전처리' 규칙). bank_before.json 저장 후 DataFrame 반환.
- classify_and_save(input_df=None): input_df 없으면 bank_before 있으면 로드, 없으면 integrate로 df 확보 → 계정과목·후처리 적용 → bank_after.json 저장.

[source 읽기·before/after 생성 조건] (카드 process_card_data와 동일)
- before·after 모두 있음 → source 읽지 않음, 기존 JSON 사용.
- before 없음 → source 읽기 → before·after 생성.
- before만 있음(after 없음) → source 읽지 않음, before 파일에서 로드 후 after만 생성.
"""
import pandas as pd
import os
import re
import sys
import time
import traceback
import unicodedata
import zipfile
from pathlib import Path

if sys.platform == 'win32':
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleOutputCP(65001)
        kernel32.SetConsoleCP(65001)
    except (OSError, AttributeError):
        pass  # 콘솔 CP 설정 실패 시 무시

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.environ.get('MYRISK_ROOT') or os.path.normpath(os.path.join(_SCRIPT_DIR, '..'))
# category_table.json: data 폴더에서 관리 (lib.path_config.get_category_table_json_path와 동일 경로)
CATEGORY_TABLE_FILE = str((Path(_PROJECT_ROOT) / 'data' / 'category_table.json').resolve()) if _PROJECT_ROOT else None
if _PROJECT_ROOT and _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
try:
    from lib.shared_app_utils import is_bad_zip_error as _is_bad_zip_error, safe_str, clean_amount
except ImportError:
    def _is_bad_zip_error(e):
        msg = str(e).lower()
        return isinstance(e, zipfile.BadZipFile) or 'not a zip file' in msg or 'bad zip' in msg
try:
    from lib.excel_io import safe_write_excel
except ImportError:
    def safe_write_excel(df, filepath, max_retries=3):
        df.to_excel(filepath, index=False, engine='openpyxl')
        return True
try:
    from lib.category_table_defaults import get_default_rules
except ImportError:
    get_default_rules = None
try:
    from lib.category_table_io import (
        safe_write_category_table,
        load_category_table,
        create_empty_category_table,
        ensure_prepost_in_table,
        normalize_category_df,
        normalize_주식회사_for_match,
        CATEGORY_TABLE_COLUMNS,
        CATEGORY_TABLE_EXTENDED_COLUMNS,
    )
except ImportError:
    import json as _json
    def safe_write_category_table(path, df, extended=False):
        path = path.replace('.xlsx', '.json') if path else path
        if not path: return
        cols = ['분류', '키워드', '카테고리', '위험도', '업종코드'] if extended else ['분류', '키워드', '카테고리']
        for c in cols:
            if c not in df.columns:
                df = df.copy()
                df[c] = ''
        rec = df[cols].copy().fillna('').to_dict('records')
        with open(path, 'w', encoding='utf-8') as f:
            _json.dump(rec, f, ensure_ascii=False, indent=2)
    def load_category_table(path, default_empty=True):
        path = path.replace('.xlsx', '.json') if path else path
        if not path or not os.path.exists(path): return pd.DataFrame(columns=['분류', '키워드', '카테고리']) if default_empty else None
        with open(path, 'r', encoding='utf-8') as f:
            data = _json.load(f)
        return pd.DataFrame(data) if data else (pd.DataFrame(columns=['분류', '키워드', '카테고리']) if default_empty else None)
    def create_empty_category_table(path):
        path = path.replace('.xlsx', '.json') if path else path
        if path:
            with open(path, 'w', encoding='utf-8') as f:
                _json.dump([], f, ensure_ascii=False)
    def normalize_category_df(df, extended=False):
        cols = ['분류', '키워드', '카테고리', '위험도', '업종코드'] if extended else ['분류', '키워드', '카테고리']
        if df is None or df.empty: return pd.DataFrame(columns=cols)
        df = df.fillna(''); df = df.drop(columns=['구분'], errors='ignore')
        for c in cols: df[c] = df[c] if c in df.columns else ''
        return df[cols].copy()
    def ensure_prepost_in_table(path):
        return load_category_table(path, default_empty=True)
    CATEGORY_TABLE_COLUMNS = ['분류', '키워드', '카테고리']
    def normalize_주식회사_for_match(text):
        if text is None or (isinstance(text, str) and not str(text).strip()):
            return '' if text is None else str(text).strip()
        val = str(text).strip()
        val = re.sub(r'[\s/]*주식회사[\s/]*', '(주)', val)
        val = re.sub(r'[\s/]*㈜[\s/]*', '(주)', val)
        val = re.sub(r'(\(주\)[\s/]*)+', '(주)', val)
        return val
try:
    from lib.path_config import get_data_dir, get_bank_after_path, get_category_table_json_path, get_source_bank_dir
    CATEGORY_TABLE_FILE = get_category_table_json_path()
    SOURCE_BANK_DIR = get_source_bank_dir()
    OUTPUT_FILE = get_bank_after_path()
    BANK_BEFORE_FILE = os.path.join(get_data_dir(), 'bank_before.json')
except ImportError:
    SOURCE_BANK_DIR = os.path.join(_PROJECT_ROOT, '.source', 'Bank') if _PROJECT_ROOT else None
    OUTPUT_FILE = os.path.join(_PROJECT_ROOT, 'data', 'bank_after.json') if _PROJECT_ROOT else os.path.join(_SCRIPT_DIR, 'bank_after.json')
    BANK_BEFORE_FILE = os.path.join(_PROJECT_ROOT, 'data', 'bank_before.json') if _PROJECT_ROOT else os.path.join(_SCRIPT_DIR, 'bank_before.json')


def _safe_print(*args, **kwargs):
    """통합 서버(Waitress) 요청 스레드에서 stdout이 닫혀 있을 때 print()가 I/O operation on closed file 을 내지 않도록 처리."""
    try:
        print(*args, **kwargs)
    except (ValueError, OSError) as e:
        if 'closed file' not in str(e).lower():
            raise


def _safe_read_data_file(path, default_empty=True):
    """before/after JSON 읽기. 없거나 손상 시 빈 DataFrame 반환. .bak 생성하지 않음."""
    if not path or not os.path.exists(path) or os.path.getsize(path) == 0:
        return pd.DataFrame() if default_empty else None
    if str(path).lower().endswith('.json'):
        try:
            from lib.data_json_io import safe_read_data_json
            return safe_read_data_json(path, default_empty=default_empty)
        except ImportError:
            return pd.DataFrame() if default_empty else None
    try:
        return pd.read_excel(path, engine='openpyxl')
    except Exception as e:
        # zip/손상·파일 사용 중 예외만 처리, 그 외 재발생
        msg = str(e).lower()
        if (_is_bad_zip_error(e) or 'zip' in msg or 'not a zip' in msg or 'bad zip' in msg
                or 'decompress' in msg or 'invalid block' in msg or 'error -3' in msg):
            return pd.DataFrame() if default_empty else None
        raise


def _bank_after_is_empty():
    """bank_after가 없거나, 0바이트이거나, 데이터 행이 없으면 True."""
    if not os.path.exists(OUTPUT_FILE):
        return True
    if os.path.getsize(OUTPUT_FILE) == 0:
        return True
    df = _safe_read_data_file(OUTPUT_FILE, default_empty=True)
    if df is None or df.empty:
        return True
    return False


def _bank_before_exists():
    """bank_before.json이 존재하고 유효한 데이터가 있으면 True. 없거나 비어 있으면 False. (카드 _card_before_exists와 동일 조건: size<=2면 빈 JSON으로 간주)"""
    if not BANK_BEFORE_FILE or not os.path.isfile(BANK_BEFORE_FILE):
        return False
    if os.path.getsize(BANK_BEFORE_FILE) <= 2:
        return False
    df = _safe_read_data_file(BANK_BEFORE_FILE, default_empty=True)
    return df is not None and not df.empty


def _ensure_bank_category_only():
    """category_table.json만 확보. bank_after 생성은 하지 않음 (카드 _ensure_card_category_file와 동일 구조)."""
    if not CATEGORY_TABLE_FILE:
        return

    if not os.path.exists(CATEGORY_TABLE_FILE):
        if _bank_before_exists():
            df = _safe_read_data_file(BANK_BEFORE_FILE, default_empty=True)
        elif not _bank_after_is_empty():
            df = _safe_read_data_file(OUTPUT_FILE, default_empty=True)
        else:
            df = integrate_bank_transactions()
        try:
            if df is not None and not df.empty:
                create_category_table(df)
            else:
                create_empty_category_table(CATEGORY_TABLE_FILE)
        except Exception as e:
            _safe_print(f"오류: category_table 생성 실패 - {e}")
        return

    full = load_category_table(CATEGORY_TABLE_FILE, default_empty=True)
    if (full is None or full.empty) and os.path.exists(CATEGORY_TABLE_FILE) and os.path.getsize(CATEGORY_TABLE_FILE) > 0:
        try:
            try:
                os.unlink(CATEGORY_TABLE_FILE)
            except OSError:
                pass
            if _bank_before_exists():
                df = _safe_read_data_file(BANK_BEFORE_FILE, default_empty=True)
            elif not _bank_after_is_empty():
                df = _safe_read_data_file(OUTPUT_FILE, default_empty=True)
            else:
                df = integrate_bank_transactions()
            create_category_table(df if df is not None and not df.empty else pd.DataFrame())
        except Exception as e:
            _safe_print(f"오류: category_table 손상 복구 실패 - {e}", flush=True)
    elif full is not None and not full.empty:
        try:
            migrate_bank_category_file(CATEGORY_TABLE_FILE)
        except Exception as e:
            if not _is_bad_zip_error(e):
                _safe_print(f"오류: category_table 마이그레이션 실패 - {e}")


def ensure_all_bank_files():
    """category_table만 확보 (카드 ensure와 동일 구조. before/after는 API·전처리 실행 시에만 생성)."""
    _ensure_bank_category_only()


def ensure_bank_before_and_category(bank_before_path=None):
    """하위 호환용. category_table만 확보 (카드 _ensure_card_category_file와 동일. bank_before_path 무시)."""
    _ensure_bank_category_only()


def normalize_text(text):
    if not text:
        return ""
    return str(text).strip()

LAST_INTEGRATE_ERROR = None
LAST_CLASSIFY_ERROR = None

def _excel_engine(path):
    """파일 확장자에 맞는 엔진 반환. .xls → xlrd, .xlsx → openpyxl"""
    suf = (path.suffix if hasattr(path, 'suffix') else os.path.splitext(str(path))[1]).lower()
    return 'xlrd' if suf == '.xls' else 'openpyxl'

def read_kb_file_excel(file_path):
    """국민은행 Excel(.xlsx) 파일 읽기. 시트별로 경로만 넘겨 read_excel 호출해 매번 열고 닫아 I/O closed file 방지."""
    path = Path(file_path)
    engine = _excel_engine(path)
    all_data = []
    with pd.ExcelFile(file_path, engine=engine) as xls:
        sheet_names = list(xls.sheet_names)
    for sheet_name in sheet_names:
        df_raw = pd.read_excel(file_path, sheet_name=sheet_name, header=None, engine=engine)
        header_row = None
        for idx in range(min(15, len(df_raw))):
            cell = df_raw.iloc[idx, 0]
            if pd.notna(cell) and ('거래일시' in str(cell) or '거래일자' in str(cell)):
                header_row = idx
                break
        if header_row is None:
            continue
        df = pd.read_excel(file_path, sheet_name=sheet_name, header=header_row, engine=engine)
        date_col = None
        for c in df.columns:
            s = str(c)
            if '거래일시' in s or '거래일자' in s:
                date_col = c
                break
        if date_col is None:
            continue
        df = df[df[date_col].notna()].copy()
        df = df[df[date_col].astype(str).str.strip() != ''].copy()
        df = df[df[date_col].astype(str) != '합계'].copy()

        account_number = None
        df_info = pd.read_excel(file_path, sheet_name=sheet_name, header=None, nrows=10, engine=engine)
        for idx in range(len(df_info)):
            for col in df_info.columns:
                value = str(df_info.iloc[idx, col])
                if '계좌번호' in value:
                    m = re.search(r'(\d{6}-\d{2}-\d{6})', value)
                    if m:
                        account_number = m.group(1)
                    break
            if account_number:
                break
        if not account_number:
            m = re.search(r'(\d{6}-\d{2}-\d{6})', str(file_path))
            if m:
                account_number = m.group(1)

        bank_name = '국민은행'
        if '거래일시' in str(date_col):
            df['거래일'] = df[date_col].astype(str).str.split(' ').str[0]
            df['거래시간'] = df[date_col].astype(str).str.split(' ').str[1]
            df['거래시간'] = df['거래시간'].fillna('')
        else:
            df['거래일'] = df[date_col].astype(str)
            df['거래시간'] = ''

        result_df = pd.DataFrame()
        result_df['거래일'] = df['거래일']
        result_df['거래시간'] = df['거래시간']
        result_df['적요'] = df['적요'] if '적요' in df.columns else ''
        result_df['출금액'] = df['출금액'] if '출금액' in df.columns else 0
        result_df['입금액'] = df['입금액'] if '입금액' in df.columns else 0
        result_df['잔액'] = df['잔액'] if '잔액' in df.columns else 0
        result_df['거래점'] = df['거래점'] if '거래점' in df.columns else ''
        result_df['취소'] = df['구분'] if '구분' in df.columns else (df['취소'] if '취소' in df.columns else '')
        content_col = None
        for c in df.columns:
            if '보낸분' in str(c) or '받는분' in str(c) or '내용' in str(c):
                content_col = c
                break
        result_df['내용'] = df[content_col].fillna('') if content_col else ''
        result_df['송금메모'] = df['송금메모'].fillna('') if '송금메모' in df.columns else ''
        result_df['메모'] = df['메모'].fillna('') if '메모' in df.columns else ''
        result_df['은행명'] = bank_name
        result_df['계좌번호'] = account_number
        result_df = result_df[result_df['거래일'].notna()].copy()
        result_df = result_df[result_df['거래일'].astype(str).str.strip() != ''].copy()
        all_data.append(result_df)

    if all_data:
        return pd.concat(all_data, ignore_index=True)
    return None

def read_sh_file(file_path):
    """신한은행 파일 읽기 (.xls, .xlsx). 시트별로 경로만 넘겨 read_excel 호출해 I/O closed file 방지."""
    path = Path(file_path)
    engine = _excel_engine(path)
    all_data = []
    with pd.ExcelFile(file_path, engine=engine) as xls:
        sheet_names = list(xls.sheet_names)
    for sheet_name in sheet_names:
        df_raw = pd.read_excel(file_path, sheet_name=sheet_name, header=None, engine=engine)
        header_row = None
        for idx in range(min(15, len(df_raw))):
            if pd.notna(df_raw.iloc[idx, 0]) and '거래일자' in str(df_raw.iloc[idx, 0]):
                header_row = idx
                break

        if header_row is None:
            continue

        df = pd.read_excel(file_path, sheet_name=sheet_name, header=header_row, engine=engine)
        df = df[df['거래일자'].notna()].copy()
        df = df[df['거래일자'] != ''].copy()

        account_number = None
        df_info = pd.read_excel(file_path, sheet_name=sheet_name, header=None, nrows=5, engine=engine)
        for idx in range(len(df_info)):
            for col in df_info.columns:
                value = str(df_info.iloc[idx, col])
                if '계좌번호' in value:
                    match = re.search(r'(\d{3}-\d{3}-\d{6})', value)
                    if match:
                        account_number = match.group(1)
                    break
            if account_number:
                break

        if not account_number:
            match = re.search(r'(\d{3}-\d{3}-\d{6})', str(file_path))
            if match:
                account_number = match.group(1)

        bank_name = '신한은행'

        result_df = pd.DataFrame(index=df.index)
        result_df['거래일'] = df['거래일자'] if '거래일자' in df.columns else ''
        result_df['거래시간'] = df['거래시간'].fillna('') if '거래시간' in df.columns else ''
        result_df['적요'] = df['적요'] if '적요' in df.columns else ''
        result_df['출금액'] = df['출금(원)'] if '출금(원)' in df.columns else (df['출금액'] if '출금액' in df.columns else 0)
        result_df['입금액'] = df['입금(원)'] if '입금(원)' in df.columns else (df['입금액'] if '입금액' in df.columns else 0)
        result_df['잔액'] = df['잔액(원)'] if '잔액(원)' in df.columns else (df['잔액'] if '잔액' in df.columns else 0)
        result_df['거래점'] = df['거래점'] if '거래점' in df.columns else ''
        result_df['취소'] = ''

        if '내용' in df.columns:
            result_df['내용'] = df['내용'].fillna('')
        else:
            content_found = False
            for col in df.columns:
                col_str = str(col).lower()
                if any(keyword in col_str for keyword in ['내용', '거래처', '상대방', '받는분', '보낸분', '거래상대방']):
                    result_df['내용'] = df[col].fillna('')
                    content_found = True
                    break

            if not content_found and len(df.columns) > 5:
                result_df['내용'] = df[df.columns[5]].fillna('')
            elif not content_found and len(df.columns) > 4:
                result_df['내용'] = df[df.columns[4]].fillna('')
            else:
                result_df['내용'] = ''

        result_df['송금메모'] = ''
        result_df['메모'] = df['메모'].fillna('') if '메모' in df.columns else ''
        result_df['은행명'] = bank_name
        result_df['계좌번호'] = account_number

        result_df = result_df[result_df['거래일'].notna()].copy()
        result_df = result_df[result_df['거래일'] != ''].copy()

        all_data.append(result_df)

    if all_data:
        return pd.concat(all_data, ignore_index=True)
    return None

def read_hana_file(file_path):
    """하나은행 파일 읽기 (.xls, .xlsx). 시트별로 경로만 넘겨 read_excel 호출해 I/O closed file 방지."""
    path = Path(file_path)
    engine = _excel_engine(path)
    all_data = []
    with pd.ExcelFile(file_path, engine=engine) as xls:
        sheet_names = list(xls.sheet_names)
    for sheet_name in sheet_names:
        df_raw = pd.read_excel(file_path, sheet_name=sheet_name, header=None, engine=engine)
        header_row = None
        for idx in range(min(15, len(df_raw))):
            if pd.notna(df_raw.iloc[idx, 0]) and ('거래일시' in str(df_raw.iloc[idx, 0]) or '거래일' in str(df_raw.iloc[idx, 0])):
                header_row = idx
                break

        if header_row is None:
            continue

        df = pd.read_excel(file_path, sheet_name=sheet_name, header=header_row, engine=engine)
        df = df[df['거래일시'].notna()].copy()

        account_number = None
        df_info = pd.read_excel(file_path, sheet_name=sheet_name, header=None, nrows=5, engine=engine)
        for idx in range(len(df_info)):
            for col in df_info.columns:
                value = str(df_info.iloc[idx, col])
                if '계좌번호' in value:
                    match = re.search(r'(\d{3}-\d{6}-\d{5})', value)
                    if match:
                        account_number = match.group(1)
                    break
            if account_number:
                break

        if not account_number:
            match = re.search(r'(\d{3}-\d{6}-\d{5})', str(file_path))
            if match:
                account_number = match.group(1)

        bank_name = '하나은행'

        df['거래일'] = df['거래일시'].astype(str).str.split(' ').str[0]
        df['거래시간'] = df['거래일시'].astype(str).str.split(' ').str[1]
        df['거래시간'] = df['거래시간'].fillna('')

        df = df[df['거래일'].notna()].copy()
        df = df[df['거래일'] != ''].copy()

        result_df = pd.DataFrame()
        result_df['거래일'] = df['거래일']
        result_df['거래시간'] = df['거래시간']
        result_df['적요'] = df['적요'] if '적요' in df.columns else ''
        result_df['출금액'] = df['출금액'] if '출금액' in df.columns else 0
        result_df['입금액'] = df['입금액'] if '입금액' in df.columns else 0
        result_df['잔액'] = df['잔액'] if '잔액' in df.columns else 0
        result_df['거래점'] = df['거래점'] if '거래점' in df.columns else ''
        result_df['취소'] = ''
        result_df['내용'] = df['내용'].fillna('') if '내용' in df.columns else ''
        result_df['송금메모'] = ''
        result_df['메모'] = ''
        result_df['은행명'] = bank_name
        result_df['계좌번호'] = account_number

        all_data.append(result_df)

    if all_data:
        return pd.concat(all_data, ignore_index=True)
    return None

def _bank_excel_files(source_dir):
    """국민/신한/하나 포함 .xls·.xlsx 목록."""
    out = []
    if not source_dir.exists():
        return out
    for ext in ('*.xls', '*.xlsx'):
        for p in source_dir.glob(ext):
            n = p.name
            if '국민은행' in n or '신한은행' in n or '하나은행' in n:
                out.append(p)
    return sorted(set(out), key=lambda p: (p.name, str(p)))

def integrate_bank_transactions(output_file=None):
    """(1) .source/Bank xls/xlsx 읽기 (2) 전처리 적용 (3) data/bank_before.json 저장 (4) DataFrame 반환. 후처리·계정과목 미적용."""

    source_dir = Path(os.path.abspath(SOURCE_BANK_DIR)) if SOURCE_BANK_DIR else Path('.source', 'Bank').resolve()
    if not source_dir.exists():
        try:
            source_dir.mkdir(parents=True, exist_ok=True)
        except (OSError, PermissionError) as e:
            _safe_print(f"오류: .source/Bank 폴더 생성 실패 - {source_dir}: {e}", flush=True)
    global LAST_INTEGRATE_ERROR
    LAST_INTEGRATE_ERROR = None
    all_data = []
    read_errors = []
    bank_files = _bank_excel_files(source_dir)
    all_xls_xlsx = list(source_dir.glob('*.xls')) + list(source_dir.glob('*.xlsx')) if source_dir.exists() else []
    if not bank_files:
        if all_xls_xlsx:
            LAST_INTEGRATE_ERROR = (
                '파일명에 국민은행, 신한은행, 하나은행 중 하나가 포함되어야 합니다. '
                f'(현재 .source/Bank에 .xls/.xlsx {len(all_xls_xlsx)}개 있으나 해당하는 파일 없음)'
            )
        _safe_print(f"경고: 은행 파일 없음 - {source_dir}", flush=True)

    for file_path in bank_files:
        name = file_path.name
        suf = file_path.suffix.lower()
        try:
            if '국민은행' in name:
                if suf == '.xlsx':
                    df = read_kb_file_excel(file_path)
                else:
                    continue  # 국민은행 .xls 미지원, .xlsx만 사용
            elif '신한은행' in name:
                df = read_sh_file(file_path)
            elif '하나은행' in name:
                df = read_hana_file(file_path)
            else:
                df = None
            if df is not None and len(df) > 0:
                all_data.append(df)
        except Exception as e:
            # 은행별 파일 읽기 실패 시 오류 수집 후 다음 파일 계속
            err_str = str(e).strip()
            if 'xlrd' in err_str or 'No module' in err_str:
                err_str = err_str + ' ( .xls 파일은 pip install xlrd 필요 )'
            read_errors.append(f"{name}: {err_str}")
            _safe_print(f"오류: {name} 처리 실패 - {e}", flush=True)
            try:
                traceback.print_exc()
            except (ValueError, OSError):
                pass
    if bank_files and not all_data and read_errors:
        LAST_INTEGRATE_ERROR = ' | '.join(read_errors[:5])
        if len(read_errors) > 5:
            LAST_INTEGRATE_ERROR += f' ... 외 {len(read_errors)-5}건'
    elif bank_files and not all_data:
        # 예외 없이 스킵됐거나 빈 DataFrame 반환된 경우 (파일명·형식·시트 구조 등)
        LAST_INTEGRATE_ERROR = (
            '파일명에 국민은행/신한은행/하나은행이 포함되어야 합니다. '
            '국민은행은 .xlsx만 지원(.xls 미지원). '
            '또는 파일을 읽었지만 데이터 행이 없거나 시트 구조가 맞지 않습니다.'
        )
        _safe_print("경고: 통합 데이터 없음.", flush=True)

    if not all_data:
        combined_df = pd.DataFrame(columns=['거래일', '거래시간', '은행명', '계좌번호', '입금액', '출금액',
                                           '사업자번호', '폐업', '취소', '적요', '내용', '송금메모', '거래점'])
        # 카드와 동일: 데이터 없어도 bank_before.json은 생성 (나중에 after 생성·표시 흐름과 일치)
        try:
            from lib.data_json_io import safe_write_data_json
            if safe_write_data_json(BANK_BEFORE_FILE, combined_df):
                _safe_print(f"저장: {BANK_BEFORE_FILE} (0건)", flush=True)
        except ImportError:
            try:
                import json
                os.makedirs(os.path.dirname(BANK_BEFORE_FILE), exist_ok=True)
                with open(BANK_BEFORE_FILE, 'w', encoding='utf-8') as f:
                    json.dump([], f, ensure_ascii=False, indent=2)
                _safe_print(f"저장: {BANK_BEFORE_FILE} (0건)", flush=True)
            except Exception as e:
                _safe_print(f"경고: bank_before.json 저장 실패 - {e}", flush=True)
        return combined_df

    combined_df = pd.concat(all_data, ignore_index=True)

    # 금액 데이터 정리 (잔액 컬럼은 bank_after에서 사용하지 않음, 삭제)
    combined_df['출금액'] = combined_df['출금액'].apply(clean_amount)
    combined_df['입금액'] = combined_df['입금액'].apply(clean_amount)
    combined_df = combined_df.drop(columns=['잔액'], errors='ignore')
    combined_df['사업자번호'] = ''
    combined_df['폐업'] = ''

    # 정렬
    combined_df['거래일_정렬용'] = pd.to_datetime(combined_df['거래일'], errors='coerce')
    combined_df = combined_df.sort_values(['거래일_정렬용', '거래시간', '은행명', '계좌번호'], na_position='last')
    combined_df = combined_df.drop('거래일_정렬용', axis=1)

    # 거래일이 없는 행 제거
    combined_df = combined_df[combined_df['거래일'].notna()].copy()
    combined_df = combined_df[combined_df['거래일'] != ''].copy()

    # 메모/카테고리 컬럼 제거 (bank_before에는 포함하지 않음)
    combined_df = combined_df.drop(columns=['메모', '카테고리'], errors='ignore')

    # 적요/내용/송금메모/거래점: 전각→반각 변환
    for col in ['적요', '내용', '송금메모', '거래점']:
        if col in combined_df.columns:
            combined_df[col] = combined_df[col].fillna('').astype(str).apply(
                lambda s: unicodedata.normalize('NFKC', s) if s else ''
            )

    # 적요의 "-"를 공백으로 변경
    if '적요' in combined_df.columns:
        combined_df['적요'] = combined_df['적요'].astype(str).str.replace('-', ' ', regex=False)

    # bank_before 생성 시 컬럼명 통일: 구분 → 취소 (소스에 구분만 있는 경우 대비)
    if '구분' in combined_df.columns and '취소' not in combined_df.columns:
        combined_df = combined_df.rename(columns={'구분': '취소'})
    elif '구분' in combined_df.columns and '취소' in combined_df.columns:
        combined_df = combined_df.drop(columns=['구분'], errors='ignore')

    # 취소 컬럼에 "취소된 거래"는 "취소"로 변경 (bank_after에서 검색 문자열로 사용)
    if '취소' in combined_df.columns:
        combined_df['취소'] = combined_df['취소'].astype(str).str.replace('취소된 거래', '취소', regex=False)

    # 전처리: before 저장 전에만 수행. category_table '전처리' 규칙으로 적요·내용·송금메모·거래점 치환 (예: 초록마을→초록증권)
    try:
        combined_df = _apply_전처리_only(combined_df)
    except Exception as e:
        # 전처리 규칙 적용 실패 시 원본 유지
        _safe_print(f"경고: 전처리 오류(무시) - {e}", flush=True)

    # 적요/내용/송금메모가 모두 비어있으면 거래점을 송금메모에 저장
    if all(c in combined_df.columns for c in ['적요', '내용', '송금메모', '거래점']):
        empty_mask = (
            combined_df['적요'].fillna('').astype(str).str.strip() == ''
        ) & (
            combined_df['내용'].fillna('').astype(str).str.strip() == ''
        ) & (
            combined_df['송금메모'].fillna('').astype(str).str.strip() == ''
        ) & (
            combined_df['거래점'].fillna('').astype(str).str.strip() != ''
        )
        combined_df.loc[empty_mask, '송금메모'] = combined_df.loc[empty_mask, '거래점']

    # 컬럼 순서 정리 (출금액 뒤 사업자번호/폐업, 잔액 미사용)
    column_order = ['거래일', '거래시간', '은행명', '계좌번호', '입금액', '출금액',
                   '사업자번호', '폐업', '취소', '적요', '내용', '송금메모', '거래점']
    existing_columns = [col for col in column_order if col in combined_df.columns]
    for col in combined_df.columns:
        if col not in existing_columns:
            existing_columns.append(col)
    combined_df = combined_df[existing_columns]

    # 전처리 결과를 data/bank_before.json으로 저장 (source xls/xlsx 읽기 + 전처리 결과)
    try:
        from lib.data_json_io import safe_write_data_json
        if safe_write_data_json(BANK_BEFORE_FILE, combined_df):
            _safe_print(f"저장: {BANK_BEFORE_FILE}", flush=True)
    except ImportError:
        try:
            import json
            os.makedirs(os.path.dirname(BANK_BEFORE_FILE), exist_ok=True)
            rec = combined_df.fillna('').to_dict('records')
            for row in rec:
                for k, v in list(row.items()):
                    if hasattr(v, 'isoformat'):
                        row[k] = v.isoformat()
            with open(BANK_BEFORE_FILE, 'w', encoding='utf-8') as f:
                json.dump(rec, f, ensure_ascii=False, indent=2)
            _safe_print(f"저장: {BANK_BEFORE_FILE}", flush=True)
        except Exception as e:
            _safe_print(f"경고: bank_before.json 저장 실패 - {e}", flush=True)

    return combined_df


def create_category_table(df):
    """통합·전처리 데이터를 기반으로 category_table.json 생성(구분 없음). 전처리·후처리·계정과목만 사용."""
    load_rules = get_default_rules
    if load_rules is None:
        from lib.category_table_defaults import get_default_rules as load_rules
    unique_category_data = load_rules('bank')

    # DataFrame 생성 (get_default_rules에서 이미 중복 제거됨)
    category_df = pd.DataFrame(unique_category_data)
    category_df = category_df.drop_duplicates(subset=['분류', '키워드', '카테고리'], keep='first')

    try:
        if len(category_df) == 0:
            category_df = pd.DataFrame(columns=CATEGORY_TABLE_COLUMNS)
        out = normalize_category_df(category_df, extended=True)
        if os.path.exists(CATEGORY_TABLE_FILE):
            full = load_category_table(CATEGORY_TABLE_FILE, default_empty=True)
            if full is not None and not full.empty:
                full = normalize_category_df(full, extended=True)
                if not full.empty:
                    out = pd.concat([full, out], ignore_index=True).drop_duplicates(subset=CATEGORY_TABLE_COLUMNS, keep='first')
        safe_write_category_table(CATEGORY_TABLE_FILE, out, extended=True)
        if not os.path.exists(CATEGORY_TABLE_FILE):
            raise FileNotFoundError(f"오류: 파일 생성 후에도 {CATEGORY_TABLE_FILE} 파일이 존재하지 않습니다.")
    except PermissionError as e:
        _safe_print(f"오류: 파일 쓰기 권한이 없습니다 - {CATEGORY_TABLE_FILE}")
        raise
    except Exception as e:
        _safe_print(f"오류: category_table 생성 실패 - {e}")
        raise

    return category_df


def migrate_bank_category_file(category_filepath=None):
    """category_table.json에서 거래방법/거래지점 행 제거, 계정과목 보강 후 저장 (구분 없음)."""
    path = str(Path(category_filepath).resolve()) if category_filepath else (CATEGORY_TABLE_FILE or '')
    if not path or not os.path.exists(path):
        return
    full_df = load_category_table(path, default_empty=True)
    if full_df is None or full_df.empty:
        return
    category_df = normalize_category_df(full_df, extended=True)
    if category_df.empty:
        return
    분류_col = category_df['분류'].astype(str).str.strip()
    keep_mask = ~분류_col.isin(['거래방법', '거래지점'])
    migrated_df = category_df.loc[keep_mask].copy()
    계정과목_mask = (migrated_df['분류'].astype(str).str.strip() == '계정과목')
    if not 계정과목_mask.any() or 계정과목_mask.sum() < 10:
        account_rows = pd.DataFrame(_DEFAULT_BANK_ACCOUNT_RULES)
        existing_account = migrated_df[계정과목_mask] if 계정과목_mask.any() else pd.DataFrame(columns=(CATEGORY_TABLE_EXTENDED_COLUMNS if 'CATEGORY_TABLE_EXTENDED_COLUMNS' in dir() else ['분류', '키워드', '카테고리', '위험도', '업종코드']))
        other_rows = migrated_df[~계정과목_mask]
        combined = pd.concat([existing_account, account_rows], ignore_index=True).drop_duplicates(subset=CATEGORY_TABLE_COLUMNS, keep='first')
        migrated_df = pd.concat([other_rows, combined], ignore_index=True)
    migrated_df = migrated_df.drop_duplicates(subset=CATEGORY_TABLE_COLUMNS, keep='first')
    try:
        safe_write_category_table(path, migrated_df, extended=True)
    except Exception as e:
        _safe_print(f"오류: category_table 마이그레이션 저장 실패 - {e}")
        raise


def _bank_row_search_text(row):
    """카테고리 매칭용 검색 문자열 생성 (취소, 적요, 내용, 송금메모, 거래점, 메모). 공백 정규화하여 키워드 매칭률 향상."""
    parts = []
    for col in ['취소', '적요', '내용', '송금메모', '거래점', '메모']:
        parts.append(safe_str(row.get(col, '')))
    text = '#'.join(p for p in parts if p)
    # 연속 공백 1개로 축소 (Excel/복사 시 공백 차이 보정)
    if text:
        text = re.sub(r'\s+', ' ', text).strip()
    return text


def apply_신청인본인_from_신청인(df, 신청인_df):
    """분류 '신청인' 행으로 before_text 매칭 시: 키워드에 category_table의 카테고리(성명), 카테고리에 '신청인본인' 저장."""
    if df is None or df.empty or 신청인_df is None or 신청인_df.empty:
        return df
    if 'before_text' not in df.columns or '카테고리' not in df.columns:
        return df
    need = ['키워드', '카테고리']
    신청인_df = 신청인_df.copy()
    신청인_df.columns = [str(c).strip() for c in 신청인_df.columns]
    if not all(c in 신청인_df.columns for c in need):
        return df
    df = df.copy()
    search_series = df['before_text'].fillna('').astype(str)
    for _, row in 신청인_df.iterrows():
        kw = safe_str(row.get('키워드', '')).strip()
        # 키워드=이메일/연락처 또는 이메일_연락처 형식이면 앞부분만 이메일로 사용
        이메일 = (kw.split('/', 1)[0] if '/' in kw else (kw.split('_', 1)[0] if '_' in kw else kw)).strip()
        성명 = safe_str(row.get('카테고리', '')).strip()  # category_table의 카테고리(성명)
        if not 이메일 and not 성명:
            continue
        match_mask = pd.Series(False, index=df.index)
        if 이메일:
            match_mask |= search_series.str.contains(re.escape(이메일), regex=False, na=False)
        if 성명:
            match_mask |= search_series.str.contains(re.escape(성명), regex=False, na=False)
        if match_mask.any():
            df.loc[match_mask, '카테고리'] = '신청인본인'
            if '키워드' in df.columns:
                # 키워드 = 성명(category_table의 카테고리)
                df.loc[match_mask, '키워드'] = 성명
    return df


def apply_category_from_bank(df, category_df):
    """계정과목 규칙 적용: before_text만 사용해 키워드 매칭. 매칭되면 해당 계정과목으로 덮어씀."""
    if df is None or df.empty or category_df is None or category_df.empty:
        return df
    need_cols = ['분류', '키워드', '카테고리']
    category_df = category_df.copy()
    category_df.columns = [str(c).strip() for c in category_df.columns]
    if not all(c in category_df.columns for c in need_cols):
        return df
    # 계정과목만 사용
    account_df = category_df[category_df['분류'].astype(str).str.strip() == '계정과목'].copy()
    if account_df.empty:
        return df
    if '카테고리' not in df.columns:
        df = df.copy()
        df['카테고리'] = ''
    if '키워드' not in df.columns:
        df['키워드'] = ''
    df = df.copy()
    df['카테고리'] = df['카테고리'].astype(object)
    df['키워드'] = df['키워드'].astype(object)
    if 'before_text' not in df.columns:
        return df
    search_series = df['before_text'].fillna('').astype(str)

    # 1단계: 먼저 전체를 '기타거래'로 할당
    df['카테고리'] = '기타거래'

    # 2단계: 행별 최대 키워드 길이 기준 정렬(긴 것 먼저). 매칭된 키워드가 더 긴 경우에만 덮어씀.
    account_df = account_df.copy()

    def _max_kw_len(s):
        parts = [k.strip() for k in str(s).split('/') if k.strip()]
        return max(len(k) for k in parts) if parts else 0
    account_df['_max_klen'] = account_df['키워드'].apply(_max_kw_len)
    account_df = account_df.sort_values('_max_klen', ascending=False).drop(columns=['_max_klen'], errors='ignore')

    df['_matched_kw_len'] = 0
    for _, cat_row in account_df.iterrows():
        cat_val = safe_str(cat_row.get('카테고리', '')).strip() or '기타거래'
        keywords_str = safe_str(cat_row.get('키워드', ''))
        if not keywords_str:
            continue
        keywords = [re.sub(r'\s+', ' ', k.strip()) for k in keywords_str.split('/') if k.strip()]
        if not keywords:
            continue
        rule_match = pd.Series(False, index=df.index)
        for kw in keywords:
            if kw:
                rule_match |= search_series.str.contains(re.escape(kw), regex=False, na=False)
        # 행별로 매칭된 키워드 중 가장 긴 것
        def longest_matched(text):
            t = str(text)
            matched = [k for k in keywords if k and k in t]
            return max(matched, key=len) if matched else ''
        matched_kw = search_series.apply(longest_matched)
        matched_len = matched_kw.str.len()
        fill_mask = rule_match & (
            (df['카테고리'].fillna('').astype(str) == '기타거래') | (matched_len > df['_matched_kw_len'])
        )
        if fill_mask.any():
            df.loc[fill_mask, '카테고리'] = cat_val
            df.loc[fill_mask, '키워드'] = matched_kw.loc[fill_mask]
            df.loc[fill_mask, '_matched_kw_len'] = matched_len.loc[fill_mask]
    df = df.drop(columns=['_matched_kw_len'], errors='ignore')
    return df


def create_before_text(row):
    """before_text 생성. 계정과목 매칭용. 취소 + 적요·내용·송금메모·거래점(전처리 반영), 구분자 #."""
    bank_name = safe_str(row.get("은행명", ""))
    parts = []
    취소 = safe_str(row.get("취소", "")).strip()
    if 취소:
        parts.append(취소)

    적요 = safe_str(row.get("적요", ""))
    if not 적요 and bank_name:
        적요 = bank_name
    parts.append(적요)

    내용 = safe_str(row.get("내용", ""))
    if not 내용 and bank_name:
        내용 = bank_name
    parts.append(내용)

    parts.append(safe_str(row.get("송금메모", "")))
    parts.append(safe_str(row.get("거래점", "")))

    return "#".join([p for p in parts if p])

def classify_1st_category(row):
    """입출금 분류: 입금/출금/취소"""
    before_text = safe_str(row.get("before_text", ""))
    취소_val = safe_str(row.get("취소", ""))

    if "취소" in before_text or "취소된 거래" in before_text:
        return "취소"
    if "취소" in 취소_val or "취소된 거래" in 취소_val:
        return "취소"

    in_amt = row.get("입금액", 0) or 0
    out_amt = row.get("출금액", 0) or 0

    if out_amt > 0:
        return "출금"
    return "입금"

def _load_전처리_규칙():
    """category_table.json에서 분류=전처리인 행만 (키워드, 카테고리) 리스트로 반환. 긴 키워드 먼저."""
    if not CATEGORY_TABLE_FILE or not os.path.exists(CATEGORY_TABLE_FILE):
        return []
    try:
        category_tables = get_category_tables()
        if not category_tables or "전처리" not in category_tables:
            return []
        tbl = category_tables["전처리"]
        rules = []
        for _, row in tbl.iterrows():
            kw = str(row.get("키워드", "") or "").strip()
            cat = str(row.get("카테고리", "") or "").strip()
            if not kw or pd.isna(row.get("카테고리")):
                continue
            if kw == cat:
                continue
            kw_norm = normalize_주식회사_for_match(kw)
            if kw_norm:
                rules.append((kw_norm, cat))
        rules.sort(key=lambda x: len(x[0]), reverse=True)
        return rules
    except (OSError, ValueError, TypeError, KeyError):
        return []


def _전처리_한칸_치환(cell_val, keyword, category):
    """한 셀 값에서 키워드(공백 허용)를 카테고리로 치환. 셀 내 모든 매칭 치환. NFC 정규화."""
    if cell_val is None or (isinstance(cell_val, float) and pd.isna(cell_val)):
        return cell_val
    s = unicodedata.normalize('NFC', str(cell_val))
    if not keyword or keyword not in re.sub(r'\s+', '', s):
        return cell_val
    pattern = r'\s*'.join(re.escape(c) for c in keyword)
    out = re.sub(pattern, category, s)
    return out if out != s else cell_val


def _apply_전처리_only(df):
    """before 저장 전: source 읽은 df의 적요·내용·송금메모·거래점에 전처리 규칙(키워드→카테고리) 적용."""
    if df is None or df.empty:
        return df
    if not CATEGORY_TABLE_FILE or not os.path.exists(CATEGORY_TABLE_FILE):
        try:
            create_empty_category_table(CATEGORY_TABLE_FILE)
            ensure_prepost_in_table(CATEGORY_TABLE_FILE)
        except (OSError, ValueError):
            pass
    rules = _load_전처리_규칙()
    if not rules:
        return df
    df = df.copy()
    cols = [c for c in ['적요', '내용', '송금메모', '거래점'] if c in df.columns]
    for col in cols:
        for kw, cat in rules:
            df[col] = df[col].apply(lambda v, k=kw, c=cat: _전처리_한칸_치환(v, k, c))
    return df


def apply_후처리_bank(df, category_tables):
    """은행거래 후처리: category_table 후처리 규칙으로 적요/내용/송금메모 컬럼의 키워드 → 카테고리 치환."""
    if df is None or df.empty or "후처리" not in category_tables:
        return df
    category_table = category_tables["후처리"]
    if category_table is None or category_table.empty:
        return df
    rules = []
    for _, row in category_table.iterrows():
        kw = str(row.get("키워드", "")).strip()
        cat = str(row.get("카테고리", "")).strip() if pd.notna(row.get("카테고리")) else ""
        if kw:
            kw_norm = normalize_주식회사_for_match(kw)
            if kw_norm:
                rules.append((kw_norm, cat))
    rules.sort(key=lambda x: len(x[0]), reverse=True)
    if not rules:
        return df
    df = df.copy()
    for col in ['적요', '내용', '송금메모']:
        if col not in df.columns:
            continue
        for kw_norm, cat in rules:
            df[col] = df[col].fillna('').astype(str).str.replace(re.escape(kw_norm), cat, regex=True)
    return df


def compute_기타거래(row):
    """기타거래: 취소(비어있지 않으면 '취소'만)/적요/내용/송금메모를 '_'로 연결, 중복 단어 제거, 연속 '_'·공백 정리. (거래점 제외)
    단, 취소/적요/내용/송금메모가 모두 스페이스나 널이면 거래점을 송금메모로 사용."""
    parts = []
    취소 = safe_str(row.get('취소', '')).strip()
    적요 = safe_str(row.get('적요', '')).strip()
    내용 = safe_str(row.get('내용', '')).strip()
    송금메모 = safe_str(row.get('송금메모', '')).strip()
    거래점 = safe_str(row.get('거래점', '')).strip()
    if not 취소 and not 적요 and not 내용 and not 송금메모 and 거래점:
        송금메모 = 거래점
    if 취소:
        parts.append('취소')
    for val in (적요, 내용, 송금메모):
        if val:
            parts.append(val)
    s = '_'.join(parts)
    # 중복 단어: 공백·'_'로 나눈 단어 중 처음 나온 것만 유지
    tokens = [w for w in re.split(r'[\s_]+', s) if w]
    seen = set()
    unique = []
    for w in tokens:
        if w not in seen:
            seen.add(w)
            unique.append(w)
    s = '_'.join(unique)
    # '_' 2개 이상 → 1개
    s = re.sub(r'_+', '_', s)
    return s.strip('_')


def _기타거래_중복단어_제거(text):
    """기타거래 문자열에서 구분자(_#공백,)로 나눈 뒤 동일 단어 중복 제거(순서 유지)."""
    if not text or (isinstance(text, float) and pd.isna(text)):
        return ''
    s = str(text).strip()
    if not s:
        return ''
    tokens = [w for w in re.split(r'[\s_#,]+', s) if w]
    seen = set()
    unique = []
    for w in tokens:
        if w not in seen:
            seen.add(w)
            unique.append(w)
    return '_'.join(unique)


def _normalize_branch(value):
    """거래점 문자열 정규화: 숫자 제거, 괄호 쌍 보정."""
    if pd.isna(value) or not value:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    text = re.sub(r'\d+', '', text)
    text = text.replace('((', '(').replace('))', ')')
    open_count = text.count('(')
    close_count = text.count(')')
    if open_count > close_count:
        text = text + ')' * (open_count - close_count)
    elif close_count > open_count:
        text = '(' * (close_count - open_count) + text
    return text.strip()


def _normalize_etc(value):
    """기타거래 문자열 정규화: 빈 괄호 제거, 중복 단어 제거, 전각→반각."""
    if pd.isna(value) or not value:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    text = re.sub(r'\(\s*\)', '', text)
    text = text.replace('((', '(').replace('))', ')')
    open_count = text.count('(')
    close_count = text.count(')')
    if open_count > close_count:
        text = text + ')' * (open_count - close_count)
    elif close_count > open_count:
        text = '(' * (close_count - open_count) + text
    text = re.sub(r'\s*\(주\)\s*', '(주)', text)
    text = re.sub(r'\s*㈜\s*', '(주)', text)
    words = [w for w in re.split(r'[\s_]+', text) if w]
    seen: set = set()
    result_words = []
    for word in words:
        word_clean = re.sub(r'[()]', '', word).strip()
        if word_clean and word_clean not in seen:
            seen.add(word_clean)
            result_words.append(word)
        elif not word_clean:
            if word not in result_words:
                result_words.append(word)
    text = re.sub(r'\s+', ' ', ' '.join(result_words)).strip()
    words_list = text.split()
    if len(words_list) >= 2:
        first_word = words_list[0]
        for i in range(1, len(words_list)):
            if words_list[i].startswith(first_word) or first_word.startswith(words_list[i]):
                text = ' '.join(words_list[:i])
                break
    return text


def _normalize_spaces(value):
    """공백 정규화: 전각/특수 공백을 반각 공백 1개로 치환, 전각 문자 반각 변환."""
    if pd.isna(value):
        return value
    s = str(value)
    if not s:
        return ''
    s = unicodedata.normalize('NFKC', s)
    s = re.sub(r'[\s\u3000\u00a0\u2002\u2003\u2009]+', ' ', s)
    return s.strip()


def _fill_거래시간(v):
    """거래시간이 비어 있으면 00:00:00으로 채운다."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return '00:00:00'
    s = str(v).strip()
    return '00:00:00' if not s else s


def get_category_tables():
    """category_table.json 로드 및 category_tables 구성 (구분 없음, 거래방법/거래지점 미사용). 전처리/후처리 없으면 기본 규칙 보강.
    파일 없으면 None, 파일 있으나 비어 있으면 {} 반환(Railway 등에서 source→JSON 생성 가능하도록)."""
    if not CATEGORY_TABLE_FILE or not os.path.exists(CATEGORY_TABLE_FILE):
        return None
    category_df = ensure_prepost_in_table(CATEGORY_TABLE_FILE)
    if category_df is None or category_df.empty:
        return {}  # 빈 테이블이면 빈 dict로 진행 가능(분류 규칙 없이 source→after 생성)
    category_df = category_df.fillna('')
    # 컬럼명 앞뒤 공백 제거 (Excel 등에서 올 수 있음)
    category_df.columns = [str(c).strip() for c in category_df.columns]
    if '구분' in category_df.columns:
        category_df = category_df.drop(columns=['구분'], errors='ignore')
    category_tables = {}
    분류_컬럼명 = '분류' if '분류' in category_df.columns else '차수'
    차수_분류_매핑 = {
        '1차': '입출금',
        '2차': '전처리',
        '6차': '기타거래'
    }

    for 값 in category_df[분류_컬럼명].unique():
        if pd.notna(값):
            값_str = str(값).strip()
            if 분류_컬럼명 == '차수' and 값_str in 차수_분류_매핑:
                분류명 = 차수_분류_매핑[값_str]
            else:
                분류명 = 값_str
            category_tables[분류명] = category_df[category_df[분류_컬럼명] == 값].copy()

    return category_tables

def classify_and_save(input_file=None, output_file=None, input_df=None):
    """source→전처리(메모리) 또는 input_df → 계정과목 분류·후처리 → bank_after.json만 저장.
    input_df 없으면: bank_before 있으면 로드, 없으면 integrate_bank_transactions()로 확보. (카드 classify_and_save와 동일 조건)
    Returns: (success: bool, error: Optional[str], count: int) — 카드와 동일."""
    global LAST_CLASSIFY_ERROR
    LAST_CLASSIFY_ERROR = None
    if output_file is None:
        output_file = OUTPUT_FILE

    if input_df is not None and not input_df.empty:
        df = input_df.copy()
    else:
        if _bank_before_exists():
            df = _safe_read_data_file(BANK_BEFORE_FILE, default_empty=True)
        else:
            df = None
        if df is None or df.empty:
            df = integrate_bank_transactions()
        if df is None or df.empty:
            LAST_CLASSIFY_ERROR = "통합·전처리 결과가 비어 있습니다. .source/Bank 폴더와 원본 파일을 확인하세요."
            _safe_print(f"오류: {LAST_CLASSIFY_ERROR}", flush=True)
            return (False, LAST_CLASSIFY_ERROR, 0)

    # 컬럼명 앞뒤 공백 제거 (취소·적요·내용·송금메모·거래점 매칭 보장)
    df.columns = [str(c).strip() for c in df.columns]
    # 기존 파일 호환: 구분 → 취소
    if '구분' in df.columns and '취소' not in df.columns:
        df = df.rename(columns={'구분': '취소'})

    if not CATEGORY_TABLE_FILE or not os.path.exists(CATEGORY_TABLE_FILE):
        try:
            if not df.empty:
                create_category_table(df)
            else:
                create_empty_category_table(CATEGORY_TABLE_FILE)
        except Exception as e:
            # classify_and_save 진입 시 category_table 없으면 생성 시도, 실패 시 False
            LAST_CLASSIFY_ERROR = f"category_table 생성 실패: {e}"
            _safe_print(f"오류: {LAST_CLASSIFY_ERROR}")
            return (False, LAST_CLASSIFY_ERROR, 0)

    category_tables = get_category_tables()
    if category_tables is None:
        # 손상된 xlsx(File is not a zip file) 등: 한 번만 백업 후 재생성 시도
        if CATEGORY_TABLE_FILE and os.path.exists(CATEGORY_TABLE_FILE) and os.path.getsize(CATEGORY_TABLE_FILE) > 0:
            try:
                try:
                    os.unlink(CATEGORY_TABLE_FILE)
                except OSError:
                    pass
                create_category_table(df if not df.empty else pd.DataFrame())
                category_tables = get_category_tables()
            except Exception as e:
                # 손상 파일 삭제 후 재생성 실패
                _safe_print(f"오류: category_table 손상 복구 실패 - {e}", flush=True)
        if category_tables is None:
            LAST_CLASSIFY_ERROR = f"{CATEGORY_TABLE_FILE} 로드 실패(파일 없음 또는 비어 있음)"
            _safe_print(f"오류: {LAST_CLASSIFY_ERROR}")
            return (False, LAST_CLASSIFY_ERROR, 0)

    try:
        df["before_text"] = df.apply(create_before_text, axis=1)
    except Exception as e:
        # before_text 생성 실패 시 classify 중단
        LAST_CLASSIFY_ERROR = f"before_text 생성 실패: {e}"
        _safe_print(f"오류: {LAST_CLASSIFY_ERROR}", flush=True)
        try:
            traceback.print_exc()
        except (ValueError, OSError):
            pass
        return (False, LAST_CLASSIFY_ERROR, 0)

    # 후처리 매칭 전에 적요·내용·송금메모를 주식회사→(주) 등으로 정규화 (전처리는 before 저장 시 이미 적용됨)
    for col in ['적요', '내용', '송금메모']:
        if col in df.columns:
            df[col] = df[col].apply(lambda v: safe_str(v))

    df["입출금"] = df.apply(classify_1st_category, axis=1)
    # 기타거래: before_text와 통일(구분자 # → _), 동일 단어 중복 1개로 치환. 빈 값이면 안 됨 → 은행명 또는 '(미기재)'로 채움.
    df["기타거래"] = (
        df["before_text"].fillna('').astype(str).str.replace("#", "_", regex=False)
        .apply(_기타거래_중복단어_제거)
    )
    # 기타거래가 빈 문자열인 행: 은행명으로 채우고, 없으면 '(미기재)'
    empty_etc = (df["기타거래"].fillna('').astype(str).str.strip() == '')
    if empty_etc.any():
        bank_col = df['은행명'].fillna('').astype(str).str.strip() if '은행명' in df.columns else pd.Series('', index=df.index)
        df.loc[empty_etc, '기타거래'] = bank_col.loc[empty_etc].where(bank_col.loc[empty_etc] != '', '(미기재)')
    # 카테고리: 계정과목 규칙 적용 (before_text만 사용해 키워드 매칭)
    if '계정과목' in category_tables:
        if '카테고리' not in df.columns:
            df['카테고리'] = ''
        df['카테고리'] = ''  # 기존 값 무시, category_table 계정과목만으로 재분류
        try:
            df = apply_category_from_bank(df, category_tables['계정과목'])
        except Exception as e:
            # 계정과목 매칭 실패 시 classify 중단
            LAST_CLASSIFY_ERROR = f"계정과목(카테고리) 적용 실패: {e}"
            _safe_print(f"오류: {LAST_CLASSIFY_ERROR}", flush=True)
            try:
                traceback.print_exc()
            except (ValueError, OSError):
                pass
            return (False, LAST_CLASSIFY_ERROR, 0)
        # 신청인본인: 분류 '신청인' 행으로 before_text 매칭 시 키워드=category_table 카테고리(성명), 카테고리='신청인본인' 저장
        신청인_df = category_tables.get('신청인')
        if 신청인_df is not None and not 신청인_df.empty:
            try:
                df = apply_신청인본인_from_신청인(df, 신청인_df)
            except Exception as e:
                _safe_print(f"경고: 신청인본인 매칭 적용 중 오류(무시): {e}", flush=True)
    else:
        if '카테고리' not in df.columns:
            df['카테고리'] = '기타거래'
        if '키워드' not in df.columns:
            df['키워드'] = ''

    # 후처리: 계정과목 분류 끝난 뒤, 저장 전에 수행. category_table '후처리' 규칙으로 적요/내용/송금메모 치환
    try:
        df = apply_후처리_bank(df, category_tables)
    except Exception as e:
        # 후처리 규칙 적용 실패 시 classify 중단
        LAST_CLASSIFY_ERROR = f"후처리 적용 실패: {e}"
        _safe_print(f"오류: {LAST_CLASSIFY_ERROR}", flush=True)
        try:
            traceback.print_exc()
        except (ValueError, OSError):
            pass
        return (False, LAST_CLASSIFY_ERROR, 0)

    # 기타거래: 저장 전 컬럼 확보 및 빈 값 제거(절대 비우지 않음)
    if '기타거래' not in df.columns and 'before_text' in df.columns:
        df["기타거래"] = (
            df["before_text"].fillna('').astype(str).str.replace("#", "_", regex=False)
            .apply(_기타거래_중복단어_제거)
        )
    if '기타거래' in df.columns:
        empty_etc = (df["기타거래"].fillna('').astype(str).str.strip() == '')
        if empty_etc.any():
            bank_col = df['은행명'].fillna('').astype(str).str.strip() if '은행명' in df.columns else pd.Series('', index=df.index)
            df.loc[empty_etc, '기타거래'] = bank_col.loc[empty_etc].where(bank_col.loc[empty_etc] != '', '(미기재)')

    # 잔액 컬럼 삭제, 출금액 뒤 사업자번호/폐업 공란 추가 (기존 파일 호환)
    df = df.drop(columns=['잔액'], errors='ignore')
    if '사업자번호' not in df.columns:
        df['사업자번호'] = ''
    if '폐업' not in df.columns:
        df['폐업'] = ''

    output_columns = [
        '거래일', '거래시간', '은행명', '계좌번호', '입금액', '출금액',
        '사업자번호', '폐업', '취소', '적요', '내용', '송금메모', '거래점',
        '입출금', '키워드', '카테고리', '기타거래'
    ]

    available_columns = [col for col in output_columns if col in df.columns]
    result_df = df[available_columns].copy()

    result_df = result_df.fillna('')

    if '기타거래' in result_df.columns:
        result_df['기타거래'] = result_df['기타거래'].apply(_normalize_etc)

    for col in ['취소', '적요', '내용', '송금메모', '거래점', '기타거래']:
        if col in result_df.columns:
            result_df[col] = result_df[col].apply(_normalize_spaces)

    if '거래시간' in result_df.columns:
        result_df['거래시간'] = result_df['거래시간'].apply(_fill_거래시간)

    try:
        out_dir = os.path.dirname(output_file)
        if out_dir and not os.path.exists(out_dir):
            try:
                os.makedirs(out_dir, exist_ok=True)
            except OSError as ex:
                _safe_print(f"오류: 출력 폴더 생성 실패 - {out_dir}: {ex}")
        try:
            from lib.data_json_io import safe_write_data_json
            safe_write_data_json(output_file, result_df)
        except ImportError:
            if not safe_write_excel(result_df, output_file):
                LAST_CLASSIFY_ERROR = f"파일 저장 실패: {output_file} (쓰기 권한 또는 파일 사용 중 확인)"
                _safe_print(f"오류: {LAST_CLASSIFY_ERROR}")
                return (False, LAST_CLASSIFY_ERROR, 0)
    except PermissionError as e:
        LAST_CLASSIFY_ERROR = f"bank_after 저장 권한 없음(파일을 닫아주세요): {e}"
        _safe_print(f"오류: {LAST_CLASSIFY_ERROR}")
        try:
            traceback.print_exc()
        except (ValueError, OSError):
            pass
        return (False, LAST_CLASSIFY_ERROR, 0)
    except Exception as e:
        # JSON/Excel 저장 중 기타 예외
        LAST_CLASSIFY_ERROR = f"파일 저장 중 예외: {e}"
        _safe_print(f"오류: {LAST_CLASSIFY_ERROR}")
        try:
            traceback.print_exc()
        except (ValueError, OSError):
            pass
        return (False, LAST_CLASSIFY_ERROR, 0)

    return (True, None, len(result_df))

def main():
    """전체 워크플로우 실행. bank_after만 사용."""
    if len(sys.argv) > 1:
        command = sys.argv[1]
        if command == 'integrate':
            integrate_bank_transactions()
            return
        elif command == 'classify':
            success, _, _ = classify_and_save()
            if not success:
                _safe_print("카테고리 분류 중 오류가 발생했습니다.")
            return

    ensure_all_bank_files()

if __name__ == '__main__':
    main()
