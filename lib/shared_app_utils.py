# -*- coding: utf-8 -*-
"""
은행/카드/금융정보 앱 공통 유틸리티.

작업 디렉터리 전환, JSON 직렬화, 파일 목록, 바이트 포맷,
텍스트·금액·시간 정리, 은행 필터 별칭 등 전 모듈에서 쓰는 함수를 모은다.
"""
import os
import sys
import io
import functools
import zipfile
from pathlib import Path

try:
    import pandas as pd
except ImportError:
    pd = None


def make_ensure_working_directory(script_dir):
    """서브앱 뷰 실행 시 cwd를 script_dir로 바꾸는 데코/컨텍스트용. 반환: callable(context_manager 또는 함수)."""
    script_dir = os.path.abspath(script_dir)

    class _CwdContext:
        def __enter__(self):
            self._old = os.getcwd()
            os.chdir(script_dir)
            return script_dir

        def __exit__(self, *exc):
            os.chdir(self._old)
            return False

    def ensure_working_directory(func=None):
        if func is not None:
            @functools.wraps(func)
            def _wrapped(*a, **kw):
                old = os.getcwd()
                try:
                    os.chdir(script_dir)
                    return func(*a, **kw)
                finally:
                    os.chdir(old)
            return _wrapped
        return _CwdContext()

    return ensure_working_directory


def json_safe(obj):
    """dict/list 내 NaN, Infinity 등을 JSON 직렬화 가능한 값으로 변환."""
    if obj is None:
        return None
    if hasattr(obj, 'iterrows'):  # DataFrame
        return obj.fillna('').to_dict('records')
    if isinstance(obj, dict):
        return {k: json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_safe(v) for v in obj]
    if pd is not None and pd.isna(obj):
        return None
    if isinstance(obj, (int, float)):
        if obj != obj:  # NaN
            return None
        if obj == float('inf') or obj == float('-inf'):
            return None
    return obj


def is_bad_zip_error(e):
    """zip/손상 파일 관련 예외 여부."""
    if isinstance(e, zipfile.BadZipFile):
        return True
    msg = str(e).lower()
    return 'not a zip file' in msg or 'bad zip' in msg or 'zip' in msg


def format_bytes(n):
    """바이트 수를 사람이 읽기 쉬운 문자열로."""
    if n is None or (isinstance(n, float) and (n != n or n < 0)):
        return '0 B'
    n = int(n)
    for u, s in [(1024**3, 'GB'), (1024**2, 'MB'), (1024, 'KB')]:
        if n >= u:
            return f'{n / u:.1f} {s}'
    return f'{n} B'


def load_source_file_list(dir_path):
    """디렉터리 내 .xls, .xlsx 파일 목록 (경로 리스트)."""
    dir_path = Path(dir_path)
    if not dir_path.is_dir():
        return []
    out = []
    for f in dir_path.iterdir():
        if f.is_file() and f.suffix.lower() in ('.xls', '.xlsx'):
            out.append(str(f))
    return sorted(out)


def df_memory_bytes(df):
    """DataFrame 대략적 메모리 바이트."""
    if df is None or (pd is not None and (not hasattr(df, 'memory_usage') or df.empty)):
        return 0
    try:
        return int(df.memory_usage(deep=True).sum())
    except (AttributeError, TypeError):
        return 0


def list_memory_bytes(lst):
    """리스트(딕셔너리 등) 대략적 메모리 바이트."""
    if lst is None:
        return 0
    try:
        return sum(sys.getsizeof(x) for x in (lst if isinstance(lst, (list, tuple)) else [lst]))
    except (TypeError, AttributeError):
        return 0


from lib.category_table_io import normalize_주식회사_for_match as _normalize_주식회사


# ── Windows 콘솔 UTF-8 설정 ────────────────────────────────

def setup_win32_utf8():
    """Windows 콘솔 코드페이지를 65001(UTF-8)로 설정하고 stdout/stderr를 UTF-8로 래핑."""
    if sys.platform != 'win32':
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleOutputCP(65001)
        kernel32.SetConsoleCP(65001)
    except (OSError, AttributeError):
        pass
    for stream_name in ('stdout', 'stderr'):
        stream = getattr(sys, stream_name, None)
        if stream is None or isinstance(stream, io.TextIOWrapper):
            continue
        try:
            binary = getattr(stream, 'buffer', None)
            if binary:
                wrapped = io.TextIOWrapper(binary, encoding='utf-8', errors='replace', line_buffering=True)
                setattr(sys, stream_name, wrapped)
        except Exception:
            pass


def safe_str(value):
    """NaN/공백 처리, 주식회사·㈜ → (주) 통일(매칭용)."""
    if pd is not None and pd.isna(value):
        return ""
    if value is None:
        return ""
    val = str(value).strip()
    if val.lower() in ('nan', 'na', 'n', 'none', ''):
        return ""
    val = _normalize_주식회사(val)
    val = val.replace('((', '(').replace('))', ')')
    val = val.replace('__', '_')
    val = val.replace('{}', '').replace('[]', '')
    if val.count('(') != val.count(')'):
        if val.count('(') > val.count(')'):
            val = val.replace('(', '')
        elif val.count(')') > val.count('('):
            val = val.replace(')', '')
    return val


def clean_amount(value):
    """금액 데이터 정리 (쉼표 제거, 숫자 변환). NaN/공란 → 0."""
    if pd is not None and pd.isna(value):
        return 0
    if value == '' or value == 0:
        return 0
    if isinstance(value, (int, float)):
        return float(value)
    value_str = str(value).replace(',', '').strip()
    if value_str == '' or value_str == '-':
        return 0
    try:
        return float(value_str)
    except (ValueError, TypeError):
        return 0


def time_to_seconds(s):
    """'HH:MM:SS' 또는 'HHMMSS' 형태 시간 문자열을 초(int)로 변환. None/NaN/공란/형식오류 → None."""
    if s is None or (isinstance(s, float) and pd is not None and pd.isna(s)):
        return None
    s = str(s).strip()
    if not s:
        return None
    if ':' in s:
        p = s.split(':')
        try:
            h = int(p[0]) if len(p) > 0 else 0
            m = int(p[1]) if len(p) > 1 else 0
            sec = int(float(p[2])) if len(p) > 2 else 0
            return h * 3600 + m * 60 + sec
        except (ValueError, IndexError):
            return None
    s = s.replace(' ', '')
    if len(s) >= 6:
        try:
            h, m, sec = int(s[0:2]), int(s[2:4]), int(s[4:6])
            return h * 3600 + m * 60 + sec
        except ValueError:
            return None
    return None


# 은행 필터 드롭다운 값 → 데이터상 실제 은행명 별칭 매핑 (bank_after, cash_after 공통)
BANK_FILTER_ALIASES = {
    '국민은행': ['국민은행', 'KB국민은행', '한국주택은행', '국민', '국민 은행'],
    '신한은행': ['신한은행', '신한'],
    '하나은행': ['하나은행', '하나'],
}


def safe_취소(val):
    """취소 컬럼 정규화: NaN/None/nan → '', '취소'/'취소된 거래' 포함 → '취소'로 통일."""
    if val is None or (pd is not None and isinstance(val, float) and pd.isna(val)):
        return ''
    s = str(val).strip()
    if s in ('', 'nan', 'None'):
        return ''
    if '취소' in s or '취소된 거래' in s:
        return '취소'
    return s
