# -*- coding: utf-8 -*-
"""
통합 Flask 서버 (app.py).

MyBank, MyCard, MyCash 서브앱을 마운트하고,
홈페이지·초기화·도움말·백업/복원 API를 제공한다.
"""
import os
import sys
import io
import shutil
import tempfile
import traceback
import subprocess
import importlib.util
import warnings

# ----- 1. 환경·인코딩 (Railway·로컬 공통) -----
os.environ.setdefault("LANG", "en_US.UTF-8")
os.environ.setdefault("LC_ALL", "en_US.UTF-8")
os.environ.setdefault("PYTHONUTF8", "1")

if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        ctypes.windll.kernel32.SetConsoleCP(65001)
    except (OSError, AttributeError):
        pass  # 콘솔 CP 설정 실패 시 무시(터미널 환경에 따라 미지원)

from datetime import datetime, timezone, timedelta
from flask import Flask, render_template, render_template_string, redirect, make_response, request, jsonify, send_file

SERVER_START_TIME = None
_VERSION_DEFAULT = '26/03/01'
KST = timezone(timedelta(hours=9))  # 한국 표준시 (기동 시간 표시용)


def _get_version():
    """VERSION 파일에서 버전 문자열 반환 (서버 재시작 없이 반영)."""
    try:
        base = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(base, 'VERSION')
        if os.path.isfile(path):
            with open(path, 'r', encoding='utf-8') as f:
                return f.read().strip() or _VERSION_DEFAULT
    except (OSError, ValueError):
        pass  # 파일 없음/읽기 실패 시 기본값 사용
    return _VERSION_DEFAULT


# ----- 2. 서브앱 설정 (폴더명, URL prefix, 진입 스크립트, 표시명) -----
SUBAPP_CONFIG = (
    ('MyBank', '/bank', 'bank_app.py', '은행거래 통합정보'),
    ('MyCard', '/card', 'card_app.py', '신용카드 통합정보'),
    ('MyCash', '/cash', 'cash_app.py', '금융정보 종합분석'),
)


try:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    elif sys.platform == 'win32' and hasattr(sys.stdout, 'buffer') and not getattr(sys.stdout.buffer, 'closed', True):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True, errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', line_buffering=True, errors='replace')
except (OSError, AttributeError, ValueError):
    pass  # stdout/stderr UTF-8 래핑 실패 시 무시

warnings.filterwarnings('ignore', message='.*OLE2 inconsistency.*')
warnings.filterwarnings('ignore', message='.*SSCS size is 0 but SSAT.*')
warnings.filterwarnings('ignore', message='.*Cannot parse header or footer.*')

# ----- 3. Flask 앱 초기화 -----
app = Flask(__name__)
SERVER_START_TIME = datetime.now(timezone.utc)  # UTC로 저장 후 화면에는 KST로 출력

# Flask 2.2+: orjson으로 JSON 응답 직렬화 가속 (선택)
try:
    from flask.json.provider import DefaultJSONProvider
    import orjson as _orjson
    class _ORJSONProvider(DefaultJSONProvider):
        def dumps(self, obj, **kwargs):
            return _orjson.dumps(obj).decode('utf-8')
        def loads(self, s, **kwargs):
            if isinstance(s, bytes):
                return _orjson.loads(s)
            return _orjson.loads(s.encode('utf-8'))
    app.json_provider_class = _ORJSONProvider
except (ImportError, AttributeError, TypeError):
    pass  # orjson 미설치 또는 Provider 적용 실패 시 기본 JSON 사용

app.json.ensure_ascii = False
app.config['JSON_AS_ASCII'] = False
_root = os.path.dirname(os.path.abspath(__file__))
os.environ['MYRISK_ROOT'] = _root
if _root not in sys.path:
    sys.path.insert(0, _root)


def _clear_previous_run_at_startup():
    """시작 시 이전 실행에서 남은 __pycache__·temp/ 삭제. (이때는 아직 본 프로세스가 사용하지 않으므로 삭제 가능)"""
    try:
        root = _root
        for _dirpath, _dirnames, _ in os.walk(root, topdown=True):
            if '__pycache__' in _dirnames:
                _pycache = os.path.join(_dirpath, '__pycache__')
                try:
                    shutil.rmtree(_pycache, ignore_errors=True)
                except OSError:
                    pass
                _dirnames.remove('__pycache__')
    except OSError:
        pass
    # temp/ 아래 파일·하위폴더 전부 삭제 (temp 폴더 자체는 유지)
    try:
        _tmp = os.path.join(_root, 'temp')
        if os.path.isdir(_tmp):
            for _name in os.listdir(_tmp):
                _path = os.path.join(_tmp, _name)
                try:
                    if os.path.isfile(_path):
                        os.unlink(_path)
                    elif os.path.isdir(_path):
                        shutil.rmtree(_path, ignore_errors=True)
                except OSError:
                    pass
    except OSError:
        pass


_clear_previous_run_at_startup()


def _load_project_lib(base_dir, reload_lib=True):
    """프로젝트 루트(base_dir)의 lib 패키지를 표준 import로 로드.
    reload_lib=False: 서브앱 로드 시 사용. sys.path에서 루트를 제거하지 않고 맨 앞만 맞춘 뒤 lib 필요 시 로드."""
    base_abs = os.path.normpath(os.path.abspath(base_dir))
    if not reload_lib:
        # 서브앱용: 프로젝트 루트를 sys.path 맨 앞에만 두고, lib 없으면 로드 (제거하지 않아 경로 누락 방지)
        if base_abs not in sys.path:
            sys.path.insert(0, base_abs)
        elif sys.path[0] != base_abs:
            try:
                sys.path.remove(base_abs)
            except ValueError:
                pass
            sys.path.insert(0, base_abs)
        if 'lib' not in sys.modules:
            try:
                importlib.import_module('lib')
                return True
            except ImportError as e:
                if not reload_lib:
                    raise ImportError("lib 패키지를 로드할 수 없습니다. 프로젝트 루트의 lib 폴더를 확인하세요. 원인: %s" % e) from e
                return False
        return True
    while base_abs in sys.path:
        sys.path.remove(base_abs)
    sys.path.insert(0, base_abs)
    for _key in list(sys.modules):
        if _key == 'lib' or _key.startswith('lib.'):
            del sys.modules[_key]
    try:
        importlib.import_module('lib')
        return True
    except ImportError:
        return False


# 앱 기동 시 lib 로드 (Railway 등에서는 cwd가 프로젝트 루트인 경우 대체 시도)
if not _load_project_lib(_root):
    _cwd_root = os.path.normpath(os.path.abspath(os.getcwd()))
    if _cwd_root != _root and os.path.isdir(os.path.join(_cwd_root, 'lib')):
        sys.path.insert(0, _cwd_root)
        try:
            importlib.import_module('lib')
            _root = _cwd_root  # 이후 서브앱 로드 시 동일 경로 사용
        except ImportError:
            pass
from lib.category_constants import (
    CLASS_PRE, CLASS_POST, CLASS_ACCOUNT, CLASS_APPLICANT, CLASS_NIGHT,
    CLASS_RISK, CLASS_INDUSTRY,
    BANK_DEFAULT_DEPOSIT, BANK_DEFAULT_WITHDRAWAL,
    CARD_DEFAULT_DEPOSIT, CARD_DEFAULT_WITHDRAWAL,
    DEFAULT_CATEGORY, UNCLASSIFIED, CARD_CASH_PROCESSING,
    DIRECTION_CANCELLED, CANCELLED_TRANSACTION,
    RISK_CODE_PRIORITY, get_template_constants,
)
try:
    from lib.path_config import DATA_DIR, get_data_dir, get_temp_dir, get_category_table_json_path
    CATEGORY_TABLE_PATH = get_category_table_json_path()
    get_data_dir()
    get_temp_dir()
except ImportError:
    CATEGORY_TABLE_PATH = os.path.join(_root, 'data', 'category_table.json')
    os.makedirs(os.path.join(_root, 'data'), exist_ok=True)
    os.makedirs(os.path.join(_root, 'temp'), exist_ok=True)
# 필수 디렉터리 생성 (.source, data, temp, readme, .source/Bank, .source/Card. Cash는 bank_after+card_after만 사용하므로 .source/Cash 미생성)
try:
    for dir_path in (os.path.join(_root, '.source'), os.path.join(_root, '.source', 'Bank'), os.path.join(_root, '.source', 'Card'), os.path.join(_root, 'data'), os.path.join(_root, 'temp'), os.path.join(_root, 'readme')):
        os.makedirs(dir_path, exist_ok=True)
except OSError:
    pass
def _ensure_category_table_json():
    """category_table.json이 없으면 xlsx에서 생성, xlsx도 없으면 빈 파일 생성."""
    if CATEGORY_TABLE_PATH and os.path.isfile(CATEGORY_TABLE_PATH):
        return
    try:
        from lib.path_config import get_category_table_xlsx_path
        xlsx_path = get_category_table_xlsx_path()
        if xlsx_path and os.path.isfile(xlsx_path):
            import pandas as pd
            from lib.category_table_io import (
                safe_write_category_table,
                normalize_category_df,
            )
            df = pd.read_excel(xlsx_path, engine='openpyxl')
            df = normalize_category_df(df, extended=True)
            if CATEGORY_TABLE_PATH:
                os.makedirs(os.path.dirname(CATEGORY_TABLE_PATH) or '.', exist_ok=True)
                safe_write_category_table(CATEGORY_TABLE_PATH, df, extended=True)
        elif CATEGORY_TABLE_PATH and not os.path.exists(CATEGORY_TABLE_PATH):
            from lib.category_table_io import create_empty_category_table
            os.makedirs(os.path.dirname(CATEGORY_TABLE_PATH) or '.', exist_ok=True)
            create_empty_category_table(CATEGORY_TABLE_PATH)
    except (ImportError, OSError, Exception):
        pass

_ensure_category_table_json()


# ----- 4. 기동 시 캐시·임시파일 정리 (다음 실행 시 깨끗한 상태) -----
def _clear_startup_caches():
    """기동 시(라우트 등록 후) 모듈 캐시·__pycache__·temp 한 번 더 정리. (실제 정리는 _clear_previous_run_at_startup()에서 선행됨)"""
    for _mod_name in list(sys.modules):
        try:
            _mod = sys.modules.get(_mod_name)
            if _mod is not None and hasattr(_mod, '_HEADER_LIKE_STRINGS'):
                setattr(_mod, '_HEADER_LIKE_STRINGS', None)
        except (AttributeError, TypeError):
            pass
    # __pycache__·temp: 기동 직후 _clear_previous_run_at_startup()에서 이미 삭제. 여기서 한 번 더 시도(실패해도 무시)
    try:
        for _sub in ('MyBank', 'MyCard', 'MyCash'):
            _pycache = os.path.join(_root, _sub, '__pycache__')
            if os.path.isdir(_pycache):
                try:
                    shutil.rmtree(_pycache, ignore_errors=True)
                except OSError:
                    pass
        for _dirpath, _dirnames, _ in os.walk(_root, topdown=True):
            if '__pycache__' in _dirnames:
                _pycache = os.path.join(_dirpath, '__pycache__')
                try:
                    shutil.rmtree(_pycache, ignore_errors=True)
                except OSError:
                    pass
                _dirnames.remove('__pycache__')
    except OSError:
        pass
    # temp/ 아래 파일·하위폴더 전부 삭제 (temp 폴더 자체는 유지)
    try:
        from lib.path_config import get_temp_dir
        tmp_dir = get_temp_dir()
        for _name in os.listdir(tmp_dir):
            _path = os.path.join(tmp_dir, _name)
            try:
                if os.path.isfile(_path):
                    os.unlink(_path)
                elif os.path.isdir(_path):
                    shutil.rmtree(_path, ignore_errors=True)
            except OSError:
                pass
    except (OSError, ImportError):
        pass


_GZIP_MIN_SIZE = 1024  # 이 크기 이상일 때만 gzip 적용
_SUBAPP_READ_TIMEOUT = 30  # 서브앱 소스 읽기 서브프로세스 타임아웃(초)

@app.after_request
def _ensure_utf8_charset(response):
    """응답 Content-Type에 charset=utf-8 보장."""
    ct = response.content_type or ""
    if ct.startswith("text/") or ct.startswith("application/json"):
        if "charset=" not in ct:
            response.content_type = f"{ct}; charset=utf-8"
    return response


@app.after_request
def _compress_response(response):
    """JSON/텍스트 응답이 일정 크기 이상이면 gzip 압축 (로딩 시간 단축)."""
    accept = request.headers.get("Accept-Encoding") or ""
    if "gzip" not in accept.lower():
        return response
    if response.direct_passthrough or response.status_code not in (200, 201):
        return response
    ct = (response.content_type or "").split(";")[0].strip()
    if ct not in ("application/json", "text/html", "text/plain", "text/css"):
        return response
    data = response.get_data(as_text=False)
    if not data or len(data) < _GZIP_MIN_SIZE:
        return response
    try:
        import gzip
        compressed = gzip.compress(data, compresslevel=6)
        response.set_data(compressed)
        response.headers["Content-Encoding"] = "gzip"
        response.headers["Content-Length"] = len(compressed)
    except (OSError, ValueError):
        pass  # gzip 압축 실패 시 원본 응답 유지
    return response


# ----- 5. 서브앱 소스 로드 시 UTF-8 블록 비활성화 (통합 서버에서 중복 설정 방지) -----
def _patch_utf8_in_source(code):
    """서브앱 소스 내 win32 UTF-8 블록 주석 처리(통합 서버에서 중복 방지)."""
    lines = code.split('\n')
    modified_lines = []
    in_utf8_block = False
    indent_level = 0
    for i, line in enumerate(lines):
        if 'if sys.platform' in line and "'win32'" in line:
            in_utf8_block = True
            indent_level = len(line) - len(line.lstrip())
            modified_lines.append('# UTF-8 블록 비활성화')
            continue
        if in_utf8_block:
            current_indent = len(line) - len(line.lstrip()) if line.strip() else indent_level + 1
            if line.strip() == '':
                modified_lines.append('')
                continue
            if current_indent <= indent_level and line.strip() and not line.strip().startswith('#'):
                in_utf8_block = False
                modified_lines.append(line)
            elif 'sys.stdout = io.TextIOWrapper' in line or 'sys.stderr = io.TextIOWrapper' in line:
                modified_lines.append('# ' + line)
            elif line.strip() == 'pass' and i > 0 and 'except:' in lines[i - 1]:
                modified_lines.append('# ' + line)
                in_utf8_block = False
            else:
                modified_lines.append('# ' + line)
        else:
            modified_lines.append(line)
    return '\n'.join(modified_lines)


def _read_app_file(app_file):
    """서브 앱 소스 파일 읽기. OneDrive/Errno 22 대응: open → pathlib → 서브프로세스 순으로 시도."""
    app_file = os.path.normpath(os.path.abspath(app_file))
    subapp_dir = os.path.dirname(app_file)
    base_name = os.path.basename(app_file)
    # 1) 일반 open
    try:
        with open(app_file, 'r', encoding='utf-8') as f:
            return f.read()
    except OSError as e:
        if getattr(e, 'errno', None) != 22:
            raise
        # 2) pathlib
        try:
            from pathlib import Path
            return Path(app_file).read_text(encoding='utf-8')
        except (OSError, ValueError, UnicodeDecodeError):
            pass  # pathlib 읽기 실패 시 서브프로세스 경로로 진행
        # 3) 서브프로세스에서 읽고 임시 파일로 출력 (OneDrive 클라우드 전용 파일 대응)
        # 인자: argv[1]=읽을 파일명(base_name), argv[2]=임시 출력 경로. cwd=subapp_dir 이므로 subapp_dir/base_name 경로로 열림.
        try:
            from lib.path_config import get_temp_dir
            tmp_dir = get_temp_dir()
        except ImportError:
            tmp_dir = tempfile.gettempdir()
        tmp_out = os.path.join(tmp_dir, 'myrisk_subapp_%s_%s.txt' % (os.getpid(), base_name))
        try:
            script = (
                "import sys; p=sys.argv[1]; t=sys.argv[2];\n"
                "f=open(p, encoding='utf-8'); c=f.read(); f.close();\n"
                "o=open(t, 'w', encoding='utf-8'); o.write(c); o.close()"
            )
            creationflags = getattr(subprocess, 'CREATE_NO_WINDOW', 0) if sys.platform == 'win32' else 0
            r = subprocess.run(
                [sys.executable, '-c', script, base_name, tmp_out],
                cwd=subapp_dir,
                capture_output=True,
                timeout=_SUBAPP_READ_TIMEOUT,
                creationflags=creationflags,
            )
            if r.returncode != 0:
                raise OSError(22, 'Invalid argument (subprocess read failed)')
            with open(tmp_out, 'r', encoding='utf-8') as f:
                return f.read()
        finally:
            try:
                if os.path.isfile(tmp_out):
                    os.unlink(tmp_out)
            except OSError:
                pass
        raise OSError(22, 'Invalid argument (OneDrive: 파일을 "항상 이 디바이스에 유지"로 설정 후 재시도)')


class _SubappLoader:
    """메모리에서 수정된 소스를 실행하는 로더 (임시 파일 미사용 → Errno 22 방지)"""
    def __init__(self, source_code, origin_path):
        self.source_code = source_code
        self.origin_path = origin_path

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        # card_app.py 등에서 __file__ 참조하므로 exec 전에 설정
        module.__file__ = self.origin_path
        code = compile(self.source_code, self.origin_path, 'exec')
        exec(code, module.__dict__)


# ----- 6. 서브앱 라우트 등록 (소스 읽기 → 패치 → 메모리 로드 → prefix 붙여 등록) -----
def load_subapp_routes(subapp_path, url_prefix, app_filename):
    """서브 앱의 라우트를 메인 앱에 등록. 실패 시 _subapp_errors에 저장 후 폴백 뷰 등록."""
    # 프로젝트 루트는 앱 기동 시 사용한 _root로 통일·정규화 (OneDrive/경로로 lib 못 찾는 것 방지)
    project_root = os.path.normpath(os.path.abspath(_root))
    # 폴더명 변경 호환: MyBank/MyCard 없으면 MYBCBANK/MYBCCARD 사용 (MyCash는 fallback 없이 오류)
    legacy_folders = {'MyBank': 'MYBCBANK', 'MyCard': 'MYBCCARD'}
    actual_path = subapp_path
    if not os.path.isdir(os.path.join(project_root, subapp_path)) and subapp_path in legacy_folders:
        alt = legacy_folders[subapp_path]
        if os.path.isdir(os.path.join(project_root, alt)):
            actual_path = alt
    subapp_dir = os.path.join(project_root, actual_path)
    original_cwd = os.getcwd()  # chdir 전 앱 시작 디렉터리 (Railway에서는 보통 /app)

    try:
        os.chdir(subapp_dir)
        # 배포(Railway)에서 cwd 기준 경로가 다를 수 있으므로, 시작 디렉터리(original_cwd)를 맨 앞에
        sys.path.insert(0, subapp_dir)
        sys.path.insert(0, project_root)
        if original_cwd not in sys.path:
            sys.path.insert(0, original_cwd)
        # 서브앱 exec 전: lib 로드. 실패 시 앱 시작 디렉터리(original_cwd)로 재시도 (Railway /app 대응)
        try:
            _load_project_lib(project_root, reload_lib=False)
        except ImportError as first_err:
            if original_cwd != project_root and os.path.isdir(os.path.join(original_cwd, 'lib')):
                if original_cwd not in sys.path:
                    sys.path.insert(0, original_cwd)
                try:
                    importlib.import_module('lib')
                except ImportError:
                    raise first_err
            else:
                raise
        if 'lib' not in sys.modules:
            try:
                importlib.import_module('lib')
            except ImportError as e:
                raise ImportError("lib 패키지를 로드할 수 없습니다. (배포 시 프로젝트 루트에 lib 폴더가 포함되는지 확인) 원인: %s" % e) from e

        app_file = os.path.join(subapp_dir, app_filename)
        app_file = os.path.normpath(os.path.abspath(app_file))
        
        code = _read_app_file(app_file)
        modified_code = _patch_utf8_in_source(code)
        
        # 임시 파일 없이 메모리에서 모듈 로드 (OneDrive/Errno 22 방지)
        loader = _SubappLoader(modified_code, app_file)
        spec = importlib.util.spec_from_loader("subapp", loader, origin=app_file)
        subapp_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(subapp_module)
        
        subapp_module.__file__ = app_file
        if hasattr(subapp_module, 'SCRIPT_DIR'):
            subapp_module.SCRIPT_DIR = subapp_dir
        if hasattr(subapp_module, 'CATEGORY_TABLE_PATH'):
            subapp_module.CATEGORY_TABLE_PATH = CATEGORY_TABLE_PATH
        try:
            from lib.path_config import DATA_DIR
            _data_dir = DATA_DIR
        except ImportError:
            _data_dir = os.path.join(_root, 'data')
        if subapp_path == 'MyBank':
            subapp_module.BANK_AFTER_PATH = os.path.join(_data_dir, 'bank_after.json')
        if subapp_path == 'MyCard' and hasattr(subapp_module, 'CARD_AFTER_PATH'):
            subapp_module.CARD_AFTER_PATH = os.path.join(_data_dir, 'card_after.json')
        sys.stdout = sys.__stdout__
        sys.stderr = sys.__stderr__
        subapp = subapp_module.app
        for rule in subapp.url_map.iter_rules():
            if rule.endpoint != 'static':
                view_func = subapp.view_functions[rule.endpoint]
                new_rule = str(rule.rule)
                if new_rule == '/':
                    new_rule = url_prefix + '/'
                else:
                    new_rule = url_prefix + new_rule
                proxy_func = create_proxy_view(view_func, subapp_dir, subapp)
                app.add_url_rule(
                    new_rule,
                    endpoint=f"{url_prefix.replace('/', '').replace('_', '')}_{rule.endpoint}",
                    view_func=proxy_func,
                    methods=rule.methods,
                    strict_slashes=False
                )
        
        return subapp
    finally:
        os.chdir(original_cwd)
        if subapp_dir in sys.path:
            sys.path.remove(subapp_dir)
        sys.stdout = sys.__stdout__
        sys.stderr = sys.__stderr__

def create_proxy_view(view_func, app_dir, subapp_instance):
    def proxy_view(*args, **kwargs):
        original_cwd = os.getcwd()
        try:
            os.chdir(app_dir)
            with subapp_instance.app_context():
                import flask
                original_flask_render = flask.render_template
                def subapp_render_template(template_name_or_list, **context):
                    return subapp_instance.render_template(template_name_or_list, **context)
                
                # 임시로 render_template 교체
                flask.render_template = subapp_render_template
                
                try:
                    result = view_func(*args, **kwargs)
                    return result
                finally:
                    # 원본 복원
                    flask.render_template = original_flask_render
        finally:
            os.chdir(original_cwd)
    return proxy_view

def _subapp_error_page(prefix_name, detail, app_folder, app_filename):
    """서브 앱 로드 실패 시 표시할 HTML"""
    return render_template_string('''<!DOCTYPE html>
<html lang="ko">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>라우트 등록 실패</title>
<style>
body { font-family: 'Malgun Gothic', sans-serif; background: #f5f5f5; padding: 40px; margin: 0; }
.container { max-width: 640px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
h1 { color: #c62828; margin-bottom: 16px; font-size: 1.4em; }
p { color: #444; line-height: 1.7; }
pre { background: #f5f5f5; padding: 12px; border-radius: 6px; overflow-x: auto; font-size: 0.9em; }
.nav { margin-top: 24px; }
a { color: #1976d2; text-decoration: none; }
a:hover { text-decoration: underline; }
.tip { background: #fff8e1; border-left: 4px solid #ff9800; padding: 12px; margin-top: 16px; }
</style>
</head>
<body>
<div class="container">
<h1>''' + prefix_name + ''' 라우트를 불러올 수 없습니다</h1>
<p>서버 시작 시 해당 모듈 등록에 실패했습니다. 아래 오류를 확인한 뒤 조치하세요.</p>
<pre>{{ detail }}</pre>
<div class="tip">
<strong>배포(Railway 등):</strong> 프로젝트 루트에 <code>lib</code> 폴더가 포함되어 있는지, 빌드 시 <code>COPY . .</code> 등으로 복사되는지 확인하세요. 저장소에 <code>lib/</code>가 있어야 합니다.<br>
<strong>로컬(OneDrive 등):</strong> 프로젝트가 OneDrive 폴더에 있으면 <code>''' + app_folder + '/' + app_filename + '''</code>가 클라우드 전용 상태일 수 있습니다. 해당 파일 우클릭 → <strong>항상 이 디바이스에 유지</strong>로 설정한 뒤 서버를 다시 시작하세요.
</div>
<div class="nav"><a href="/">홈으로</a> · <a href="/help">도움말</a></div>
</div>
</body>
</html>''', detail=detail)

# 서브 앱 라우트 등록 (SUBAPP_CONFIG 기반)
_subapp_errors = {}  # prefix -> (표시이름, 오류메시지)

for subapp_path, url_prefix, app_filename, display_name in SUBAPP_CONFIG:
    try:
        load_subapp_routes(subapp_path, url_prefix, app_filename)
        _subapp_errors.pop(url_prefix, None)
    except Exception as e:
        # 서브앱별 로드 실패 시 폴백 뷰 등록을 위해 모든 예외 처리
        err_msg = str(e)
        print(f"[ERROR] {display_name} ({url_prefix}, {subapp_path}/{app_filename}) 라우트 등록 실패: {err_msg}", flush=True)
        traceback.print_exc()
        _subapp_errors[url_prefix] = (display_name, err_msg)
        # 실패한 prefix에 대한 폴백 라우트 등록 (404 대신 오류 안내 표시)
        def _make_fallback(prefix, name, msg, folder, app_file):
            def fallback_view():
                return _subapp_error_page(name, msg, folder, app_file)
            return fallback_view
        _view = _make_fallback(url_prefix, display_name, err_msg, subapp_path, app_filename)
        app.add_url_rule(url_prefix + '/', endpoint='fallback_' + url_prefix.strip('/'), view_func=_view, strict_slashes=False)
        app.add_url_rule(url_prefix, endpoint='fallback_' + url_prefix.strip('/') + '_root', view_func=(lambda p: lambda: redirect(p + '/'))(url_prefix), methods=('GET',))

# 서버 기동 시 캐시·임시파일 초기화 (이전 실행 상태 제거)
_clear_startup_caches()

# ----- 7. 메인 라우트 (리다이렉트, 홈, 도움말, 종료, 헬스, 404) -----
# 신청인 검증: 서버 메모리에 유지 (쿠키 사용 안 함). 앱 종료 시 자동 소멸.
_APPLICANT_SESSION = {}  # {'verified': bool, 'name': str, 'email': str, 'contact': str}

@app.before_request
def _before_request_ensure_category():
    """페이지 진입 시 category_table.json이 없으면 자동 생성."""
    path = request.path
    if path == '/' or path.startswith(('/bank', '/card', '/cash', '/reset')):
        _ensure_category_table_json()


@app.route('/bank')
def redirect_bank():
    """은행거래 전처리: 끝 슬래시 없이 접속 시 /bank/ 로 리다이렉트"""
    return redirect('/bank/', code=302)


@app.route('/cash')
def redirect_cash():
    """금융정보 병합작업: 끝 슬래시 없이 접속 시 /cash/ 로 리다이렉트"""
    return redirect('/cash/', code=302)


@app.route('/card')
def redirect_card():
    """신용카드 전처리: 끝 슬래시 없이 접속 시 /card/ 로 리다이렉트"""
    return redirect('/card/', code=302)


def _no_cache_headers():
    """브라우저 캐시 방지 헤더 (수정 사항 즉시 반영용)"""
    return {
        'Cache-Control': 'no-cache, no-store, must-revalidate',
        'Pragma': 'no-cache',
        'Expires': '0',
    }

@app.route('/')
def index():
    """메인 홈페이지."""
    start_time_str = (SERVER_START_TIME.astimezone(KST).strftime('%H:%M:%S') if SERVER_START_TIME else '')
    resp = make_response(render_template(
        'index.html',
        version=_get_version(),
        server_start_time=start_time_str,
    ))
    resp.headers.update(_no_cache_headers())
    if start_time_str:
        resp.headers['X-Server-Start'] = start_time_str  # 새 서버 응답 여부 확인용 (F12 → Network → 응답 헤더)
    return resp


@app.route('/help')
def help_page():
    """도움말 (금융정보 보고서)"""
    resp = make_response(render_template('help.html'))
    resp.headers.update(_no_cache_headers())
    return resp


@app.route('/reset')
def reset_page():
    """초기화 페이지: 전처리전/전처리후 선택 후 해당 JSON 삭제. 좌측 패널 헤더는 MYRISK_RESET_LEFT_HEADER 환경변수로 지정."""
    left_header = os.environ.get('MYRISK_RESET_LEFT_HEADER', '환경변수 관리').strip() or '환경변수 관리'
    resp = make_response(render_template('reset.html', reset_left_header=left_header, **get_template_constants()))
    resp.headers.update(_no_cache_headers())
    return resp


@app.route('/category-standard')
def category_standard_page():
    resp = make_response(render_template('category_standard.html', **get_template_constants()))
    resp.headers.update(_no_cache_headers())
    return resp


@app.route('/category-audit-report-page')
def category_audit_report_page():
    from lib.audit_report import generate_report_html
    content = generate_report_html(_root)
    resp = make_response(content)
    resp.headers.update(_no_cache_headers())
    resp.headers['Content-Type'] = 'text/html; charset=utf-8'
    return resp


@app.route('/api/category-generate-md', methods=['POST'])
def api_category_generate_md():
    """전수조사: 기존 보고서 MD 삭제 → 현행 category_table.json 기준 카테고리_생성.md 저장."""
    import json as _json
    from datetime import datetime as _dt

    memo_dir = os.path.join(_root, 'readme', '분석메모')
    old_reports = [
        os.path.join(memo_dir, f) for f in os.listdir(memo_dir)
        if f.endswith('.md') and ('전수조사' in f or '검수보고서' in f or '카테고리_생성' in f)
    ] if os.path.isdir(memo_dir) else []
    removed = []
    for p in old_reports:
        try:
            os.remove(p)
            removed.append(os.path.basename(p))
        except OSError:
            pass

    ct_path = os.path.join(_root, 'data', 'category_table.json')
    if not os.path.exists(ct_path):
        return jsonify({'success': False, 'error': 'category_table.json 없음'}), 404

    with open(ct_path, 'r', encoding='utf-8') as f:
        ct = _json.load(f)

    now = _dt.now().strftime('%Y-%m-%d %H:%M')
    lines = [f'# 카테고리 생성 현황', '', f'> 생성일: {now}  ', f'> 총 {len(ct)}건', '']

    by_class = {}
    for r in ct:
        cls = r.get('분류', '') or '(미분류)'
        by_class.setdefault(cls, []).append(r)

    for cls in sorted(by_class.keys()):
        rows = by_class[cls]
        lines.append(f'## {cls} ({len(rows)}건)')
        lines.append('')
        lines.append('| 키워드 | 카테고리 | 위험도 | 위험지표 |')
        lines.append('|--------|----------|--------|----------|')
        for r in rows:
            kw = r.get('키워드', '')
            cat = r.get('카테고리', '')
            risk = r.get('위험도', '')
            biz = r.get('위험지표', '')
            lines.append(f'| {kw} | {cat} | {risk} | {biz} |')
        lines.append('')

    md_content = '\n'.join(lines)
    os.makedirs(memo_dir, exist_ok=True)
    out_path = os.path.join(memo_dir, '카테고리_생성.md')
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(md_content)

    return jsonify({
        'success': True,
        'removed': removed,
        'path': out_path,
        'count': len(ct),
        'md': md_content
    })


@app.route('/api/category-inspection-report', methods=['POST'])
def api_category_inspection_report():
    """검수보고서: 현재 상태 기준 계정과목 표준 전수조사 보고서 생성."""
    import json as _json
    from datetime import datetime as _dt

    ct_path = os.path.join(_root, 'data', 'category_table.json')
    md_path = os.path.join(_root, 'readme', '가이드', '계정과목_표준.md')
    bank_path = os.path.join(_root, 'data', 'bank_after.json')
    card_path = os.path.join(_root, 'data', 'card_after.json')

    if not os.path.exists(ct_path):
        return jsonify({'success': False, 'error': 'category_table.json 없음'}), 404

    with open(ct_path, 'r', encoding='utf-8') as f:
        ct = _json.load(f)

    now = _dt.now().strftime('%Y-%m-%d %H:%M')
    lines = ['# 계정과목 표준 전수조사 보고서', '', f'> 기준일: {now}', '']

    by_class = {}
    for r in ct:
        cls = r.get('분류', '') or '(미분류)'
        by_class.setdefault(cls, []).append(r)

    lines.append('## 1. 카테고리 테이블 현황')
    lines.append('')
    lines.append(f'- 총 행수: **{len(ct)}건**')
    lines.append('')
    lines.append('| 분류 | 건수 |')
    lines.append('|------|------|')
    for cls in sorted(by_class.keys()):
        lines.append(f'| {cls} | {len(by_class[cls])} |')
    lines.append('')

    acc_rows = [r for r in ct if r.get('분류') == CLASS_ACCOUNT]
    kw_count = sum(len(r.get('키워드', '').split('/')) for r in acc_rows)
    cats = set(r.get('카테고리', '') for r in acc_rows)
    lines.append('## 2. 계정과목 상세')
    lines.append('')
    lines.append(f'- 계정과목 행: **{len(acc_rows)}건**, 개별 키워드: **{kw_count}개**, 카테고리: **{len(cats)}종**')
    lines.append('')

    has_std = os.path.exists(md_path)
    lines.append('## 3. 계정과목_표준.md 대비 검증')
    lines.append('')
    if not has_std:
        lines.append('- 계정과목_표준.md 파일 없음 — 비교 불가')
    else:
        import re as _re
        with open(md_path, 'r', encoding='utf-8') as f:
            md_content = f.read()
        old_kw_map = {}
        for r in acc_rows:
            cat = r.get('카테고리', '')
            for kw in r.get('키워드', '').split('/'):
                kw = kw.strip()
                if kw:
                    old_kw_map[kw] = cat
        new_kw_map = {}
        current_section = None
        current_code = None
        current_cat = None
        current_mid = ''
        major_map = {
            'I': 'I_자금이동', 'II': 'II_필수생활비', 'III': 'III_재량소비',
            'IV': 'IV_금융거래', 'V': 'V_인적거래', 'VI': 'VI_고위험항목',
        }
        for line in md_content.split('\n'):
            ls = line.strip()
            if ls.startswith('## 5. 계정과목'):
                current_section = CLASS_ACCOUNT; continue
            elif ls.startswith('## 6.') or ls.startswith('## 7.') or ls.startswith('## 부록'):
                current_section = None; continue
            elif ls.startswith('## '):
                if current_section == CLASS_ACCOUNT:
                    current_section = None
                continue
            if current_section == CLASS_ACCOUNT:
                hm = _re.match(r'^###\s+(?:(I{1,3}V?|IV|V|VI{0,2}|VII)\.?\s+)?(.+?)(?:\s*—\s*(.+))?$', ls)
                if hm and not ls.startswith('####'):
                    mid_part = hm.group(3)
                    current_mid = mid_part.strip() if mid_part else hm.group(2).strip()
                    continue
                m = _re.match(r'^####\s+([A-Z]\d+)\s+(.+)$', ls)
                if m:
                    current_code = m.group(1)
                    current_cat = m.group(2).strip()
                    continue
                if current_code and ls.startswith('| ') and not ls.startswith('| 키워드') and not ls.startswith('|---'):
                    cols = [c.strip() for c in ls.split('|')[1:-1]]
                    if cols and cols[0]:
                        for kw in cols[0].split('/'):
                            kw = kw.strip()
                            if kw:
                                new_kw_map[kw] = f'{current_code[0]}_{current_mid}'

        old_set = set(old_kw_map.keys())
        new_set = set(new_kw_map.keys())
        both = old_set & new_set
        changed = sum(1 for kw in both if old_kw_map[kw] != new_kw_map[kw])
        same = len(both) - changed

        lines.append(f'- 카테고리 테이블 키워드: **{len(old_set)}개**')
        lines.append(f'- 계정과목 표준 키워드: **{len(new_set)}개**')
        lines.append(f'- 양쪽 동일: **{same}개**')
        lines.append(f'- 카테고리 변경: **{changed}건**')
        lines.append(f'- 테이블에만 있음: **{len(old_set - new_set)}건**')
        lines.append(f'- 표준에만 있음: **{len(new_set - old_set)}건**')
    lines.append('')

    lines.append('## 4. 거래 데이터 매칭 현황')
    lines.append('')

    def _parse_amt(v):
        try:
            return int(float(str(v).replace(',', '') or '0'))
        except Exception:
            return 0

    if os.path.exists(bank_path):
        with open(bank_path, 'r', encoding='utf-8') as f:
            bank = _json.load(f)
        kita = set(r.get('기타거래', '').strip() for r in bank if r.get('기타거래', '').strip())
        matched_b = sum(1 for v in kita if any(kw in v for kw in old_kw_map)) if has_std else 0
        lines.append(f'### 은행거래 (bank_after.json)')
        lines.append(f'- 전체: {len(bank)}건, 고유 기타거래: {len(kita)}건')
        if has_std:
            lines.append(f'- 키워드 매칭: {matched_b}건, 미매칭: {len(kita) - matched_b}건')
    else:
        lines.append('### 은행거래: bank_after.json 없음')
    lines.append('')

    if os.path.exists(card_path):
        with open(card_path, 'r', encoding='utf-8') as f:
            card = _json.load(f)
        kw_set = set(r.get('키워드', '').strip() for r in card if r.get('키워드', '').strip())
        matched_c = sum(1 for v in kw_set if any(kw in v for kw in old_kw_map)) if has_std else 0
        lines.append(f'### 신용카드 (card_after.json)')
        lines.append(f'- 전체: {len(card)}건, 고유 키워드: {len(kw_set)}건')
        if has_std:
            lines.append(f'- 키워드 매칭: {matched_c}건, 미매칭: {len(kw_set) - matched_c}건')
    else:
        lines.append('### 신용카드: card_after.json 없음')
    lines.append('')

    pre_rows = [r for r in ct if r.get('분류') == CLASS_PRE]
    post_rows = [r for r in ct if r.get('분류') == CLASS_POST]
    risk_rows = [r for r in ct if r.get('분류') == CLASS_RISK]
    ind_rows = [r for r in ct if r.get('분류') == CLASS_INDUSTRY]

    lines.append('## 5. 기타 분류 현황')
    lines.append('')
    lines.append(f'- 전처리: {len(pre_rows)}건')
    lines.append(f'- 후처리: {len(post_rows)}건')
    lines.append(f'- 위험도분류: {len(risk_rows)}건')
    lines.append(f'- 업종분류: {len(ind_rows)}건')
    lines.append('')

    lines.append('## 6. 판정')
    lines.append('')
    ok_items = []
    if len(ct) > 0:
        ok_items.append('카테고리 테이블 존재')
    all_5col = all(all(k in r for k in ['분류', '위험도', '카테고리', '위험지표', '키워드']) for r in ct)
    if all_5col:
        ok_items.append('5컬럼 구조 정상')
    if len(acc_rows) > 0:
        ok_items.append(f'계정과목 {len(acc_rows)}건 등록')
    if len(risk_rows) > 0:
        ok_items.append(f'위험도분류 {len(risk_rows)}건 등록')

    for item in ok_items:
        lines.append(f'- [x] {item}')
    lines.append('')

    md_content = '\n'.join(lines)
    memo_dir = os.path.join(_root, 'readme', '분석메모')
    os.makedirs(memo_dir, exist_ok=True)
    out_path = os.path.join(memo_dir, '계정과목_표준_전수조사_보고서.md')
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(md_content)

    return jsonify({
        'success': True,
        'path': out_path,
        'md': md_content
    })


@app.route('/api/category-standard-data')
def category_standard_data():
    """계정과목_표준.md를 파싱하여 JSON으로 반환."""
    import re
    md_path = os.path.join(_root, 'readme', '가이드', '계정과목_표준.md')
    if not os.path.exists(md_path):
        return jsonify({'error': '계정과목_표준.md 파일이 없습니다.'}), 404
    with open(md_path, 'r', encoding='utf-8') as f:
        content = f.read()

    sections_map = {
        CLASS_PRE: [], CLASS_POST: [], CLASS_APPLICANT: [], CLASS_NIGHT: [],
        CLASS_RISK: [], CLASS_INDUSTRY: [],
    }
    account_items = []

    current_section = None
    current_code = None
    current_cat = None
    current_major = ''
    current_mid = ''

    major_map = {
        'I': 'I_자금이동', 'II': 'II_필수생활비', 'III': 'III_재량소비',
        'IV': 'IV_금융거래', 'V': 'V_인적거래', 'VI': 'VI_고위험항목',
    }

    for line in content.split('\n'):
        ls = line.strip()
        if ls.startswith('## 1. 전처리'):
            current_section = CLASS_PRE; current_code = None; continue
        elif ls.startswith('## 2. 후처리'):
            current_section = CLASS_POST; current_code = None; continue
        elif ls.startswith('## 3. 신청인'):
            current_section = CLASS_APPLICANT; current_code = None; continue
        elif ls.startswith('## 4. 심야구분'):
            current_section = CLASS_NIGHT; current_code = None; continue
        elif ls.startswith('## 5. 계정과목'):
            current_section = CLASS_ACCOUNT; current_code = None; continue
        elif ls.startswith('## 6. 위험도분류'):
            current_section = CLASS_RISK; current_code = None; continue
        elif ls.startswith('## 7. 업종분류'):
            current_section = CLASS_INDUSTRY; current_code = None; continue
        elif ls.startswith('## 부록'):
            current_section = None; continue

        if current_section in (CLASS_PRE, CLASS_POST, CLASS_APPLICANT, CLASS_NIGHT):
            if ls.startswith('| ') and not ls.startswith('| 키워드') and not ls.startswith('|---'):
                cols = [c.strip() for c in ls.split('|')[1:-1]]
                if len(cols) >= 2 and cols[0]:
                    sections_map[current_section].append({
                        '분류': current_section, '키워드': cols[0], '카테고리': cols[1],
                        '위험도': '', '위험지표': ''
                    })

        elif current_section == CLASS_ACCOUNT:
            hm = re.match(r'^###\s+(?:(I{1,3}V?|IV|V|VI{0,2}|VII)\.?\s+)?(.+?)(?:\s*—\s*(.+))?$', ls)
            if hm and not ls.startswith('####'):
                roman = hm.group(1) or ''
                name = hm.group(2).strip()
                if roman:
                    current_major = major_map.get(roman, roman + '_' + name)
                elif '미분류' in name:
                    current_major = '미분류'
                else:
                    current_major = name
                mid_part = hm.group(3)
                current_mid = mid_part.strip() if mid_part else name
                continue
            m = re.match(r'^####\s+([A-Z]\d+)\s+(.+)$', ls)
            if m:
                current_code = m.group(1)
                current_cat = m.group(2).strip()
                continue
            if current_code and ls.startswith('| ') and not ls.startswith('| 키워드') and not ls.startswith('|---'):
                cols = [c.strip() for c in ls.split('|')[1:-1]]
                if cols and cols[0]:
                    account_items.append({
                        '분류': CLASS_ACCOUNT, '코드': current_code,
                        '소분류': current_cat,
                        '카테고리': f'{current_code[0]}_{current_mid}',
                        '대분류': current_major, '중분류': current_mid,
                        '키워드': cols[0],
                        '위험도': current_major,
                        '위험지표': current_code,
                    })

        elif current_section in (CLASS_RISK, CLASS_INDUSTRY):
            if ls.startswith('| ') and not ls.startswith('| 키워드') and not ls.startswith('|---'):
                cols = [c.strip() for c in ls.split('|')[1:-1]]
                if len(cols) >= 4 and cols[0]:
                    sections_map[current_section].append({
                        '분류': current_section, '키워드': cols[0], '카테고리': cols[1],
                        '위험도': cols[2], '위험지표': cols[3]
                    })

    return jsonify({
        CLASS_PRE: sections_map[CLASS_PRE],
        CLASS_POST: sections_map[CLASS_POST],
        CLASS_APPLICANT: sections_map[CLASS_APPLICANT],
        CLASS_NIGHT: sections_map[CLASS_NIGHT],
        CLASS_ACCOUNT: account_items,
        CLASS_RISK: sections_map[CLASS_RISK],
        CLASS_INDUSTRY: sections_map[CLASS_INDUSTRY],
    })


@app.route('/api/category-standard-audit')
def category_standard_audit():
    """카테고리 테이블 vs 계정과목 표준 대비 전수조사 결과 JSON."""
    import re as _re
    import json as _json

    ct_path = os.path.join(_root, 'data', 'category_table.json')
    bank_path = os.path.join(_root, 'data', 'bank_after.json')
    card_path = os.path.join(_root, 'data', 'card_after.json')

    result = {'테이블키워드수': 0, '표준키워드수': 0, '테이블전용': [], '표준전용': [],
              '변경': [], '유지': 0, '은행': {}, '카드': {}, '충돌': []}

    if not os.path.exists(ct_path):
        return jsonify({'error': 'category_table.json 없음'}), 404

    with open(ct_path, 'r', encoding='utf-8') as f:
        ct = _json.load(f)
    old_kw_map = {}
    for r in ct:
        if r.get('분류') != CLASS_ACCOUNT:
            continue
        cat = r.get('카테고리', '')
        for kw in r.get('키워드', '').split('/'):
            kw = kw.strip()
            if kw:
                old_kw_map[kw] = cat
    result['테이블키워드수'] = len(old_kw_map)

    md_path = os.path.join(_root, 'readme', '가이드', '계정과목_표준.md')
    if not os.path.exists(md_path):
        return jsonify({'error': '계정과목_표준.md 없음'}), 404

    with open(md_path, 'r', encoding='utf-8') as f:
        md_content = f.read()

    new_kw_map = {}
    pre_map = {}
    current_section = None
    current_code = None
    current_cat = None
    current_major = ''
    current_mid = ''
    major_map = {
        'I': 'I_자금이동', 'II': 'II_필수생활비', 'III': 'III_재량소비',
        'IV': 'IV_금융거래', 'V': 'V_인적거래', 'VI': 'VI_고위험항목',
    }

    for line in md_content.split('\n'):
        ls = line.strip()
        if ls.startswith('## 1. 전처리'):
            current_section = CLASS_PRE; continue
        elif ls.startswith('## 2. 후처리'):
            current_section = CLASS_POST; continue
        elif ls.startswith('## 5. 계정과목'):
            current_section = CLASS_ACCOUNT; continue
        elif ls.startswith('## 6.') or ls.startswith('## 7.') or ls.startswith('## 부록'):
            current_section = None; continue
        elif ls.startswith('## 3.') or ls.startswith('## 4.'):
            current_section = None; continue

        if current_section == CLASS_PRE:
            if ls.startswith('| ') and not ls.startswith('| 키워드') and not ls.startswith('|---'):
                cols = [c.strip() for c in ls.split('|')[1:-1]]
                if len(cols) >= 2 and cols[0]:
                    for kw in cols[0].split('/'):
                        kw = kw.strip()
                        if kw:
                            pre_map[kw] = cols[1]

        elif current_section == CLASS_ACCOUNT:
            hm = _re.match(r'^###\s+(?:(I{1,3}V?|IV|V|VI{0,2}|VII)\.?\s+)?(.+?)(?:\s*—\s*(.+))?$', ls)
            if hm and not ls.startswith('####'):
                roman = hm.group(1) or ''
                name = hm.group(2).strip()
                if roman:
                    current_major = major_map.get(roman, roman + '_' + name)
                elif '미분류' in name:
                    current_major = '미분류'
                else:
                    current_major = name
                mid_part = hm.group(3)
                current_mid = mid_part.strip() if mid_part else name
                continue
            m = _re.match(r'^####\s+([A-Z]\d+)\s+(.+)$', ls)
            if m:
                current_code = m.group(1)
                current_cat = m.group(2).strip()
                continue
            if current_code and ls.startswith('| ') and not ls.startswith('| 키워드') and not ls.startswith('|---'):
                cols = [c.strip() for c in ls.split('|')[1:-1]]
                if cols and cols[0]:
                    for kw in cols[0].split('/'):
                        kw = kw.strip()
                        if kw:
                            cat_mid = f'{current_code[0]}_{current_mid}'
                            new_kw_map[kw] = {'code': current_code, 'cat': cat_mid, 'sub': current_cat, 'major': current_major, 'mid': current_mid}

    result['표준키워드수'] = len(new_kw_map)

    old_set = set(old_kw_map.keys())
    new_set = set(new_kw_map.keys())
    result['테이블전용'] = [{'키워드': kw, '테이블카테고리': old_kw_map[kw]} for kw in sorted(old_set - new_set)]
    result['표준전용'] = [{'키워드': kw, '코드': new_kw_map[kw]['code'], '카테고리': new_kw_map[kw]['cat']} for kw in sorted(new_set - old_set)]

    changed = []
    same_cnt = 0
    for kw in sorted(old_set & new_set):
        old_cat = old_kw_map[kw]
        ni = new_kw_map[kw]
        if old_cat != ni['cat']:
            changed.append({'키워드': kw, '테이블카테고리': old_cat, '코드': ni['code'], '표준카테고리': ni['cat']})
        else:
            same_cnt += 1
    result['변경'] = changed
    result['유지'] = same_cnt

    def _parse_amt(v):
        try:
            return int(float(str(v).replace(',', '') or '0'))
        except Exception:
            return 0

    if os.path.exists(bank_path):
        with open(bank_path, 'r', encoding='utf-8') as f:
            bank = _json.load(f)
        kita_set = set()
        for r in bank:
            v = r.get('기타거래', '').strip()
            if v:
                kita_set.add(v)

        _risk_priority = RISK_CODE_PRIORITY

        def _kw_match(kw, val):
            if kw.startswith('re:'):
                return bool(_re.search(kw[3:], val))
            return kw in val

        matched_list = []
        unmatched_list = []
        for val in sorted(kita_set):
            hit = None
            for kw, info in new_kw_map.items():
                if _kw_match(kw, val):
                    hit = info
                    break
            txns = [r for r in bank if r.get('기타거래', '').strip() == val]
            total_in = sum(_parse_amt(r.get('입금액', 0)) for r in txns)
            total_out = sum(_parse_amt(r.get('출금액', 0)) for r in txns)
            entry = {'기타거래': val, '건수': len(txns),
                     '입금': total_in, '출금': total_out,
                     '테이블카테고리': txns[0].get('카테고리', '') if txns else ''}
            if hit:
                entry['매칭코드'] = hit['code']
                entry['매칭카테고리'] = hit['cat']
                matched_list.append(entry)
            elif total_in > 0 and total_out == 0 and total_in <= 10:
                entry['매칭코드'] = 'M01'
                entry['매칭카테고리'] = 'M_계좌이동'
                entry['비고'] = '소액입금(계좌인증)'
                matched_list.append(entry)
            else:
                entry['분류'] = BANK_DEFAULT_DEPOSIT if (total_in > 0 and total_out == 0) else BANK_DEFAULT_WITHDRAWAL
                unmatched_list.append(entry)

        # 충돌 감지 + 위험도 자동 해결
        conflict_list = []
        resolved_list = []
        for val in sorted(kita_set):
            matches = {}
            for kw, info in new_kw_map.items():
                if _kw_match(kw, val):
                    c = info['code']
                    if c not in matches:
                        matches[c] = {'cat': info['cat'], 'kw': kw}
            if len(matches) > 1:
                items = [{'코드': c, '카테고리': v['cat'], '키워드': v['kw']} for c, v in sorted(matches.items())]
                priorities = [_risk_priority.get(c[0], 0) for c in matches.keys()]
                max_p = max(priorities)
                top_codes = [c for c, v in matches.items() if _risk_priority.get(c[0], 0) == max_p]
                if len(top_codes) == 1:
                    resolved_list.append({'기타거래': val, '매칭': items, '해결코드': top_codes[0], '해결카테고리': matches[top_codes[0]]['cat'], '해결방법': '위험도'})
                else:
                    # 타이브레이커: 같은 카테고리 → 자동 해결
                    top_cats = set(matches[c]['cat'] for c in top_codes)
                    if len(top_cats) == 1:
                        winner = max(top_codes)
                        resolved_list.append({'기타거래': val, '매칭': items, '해결코드': winner, '해결카테고리': matches[winner]['cat'], '해결방법': '동일카테고리'})
                    else:
                        # 타이브레이커: 긴 키워드(구체적 매칭) 우선
                        longest_len = max(len(matches[c]['kw']) for c in top_codes)
                        longest_codes = [c for c in top_codes if len(matches[c]['kw']) == longest_len]
                        if len(longest_codes) == 1:
                            winner = longest_codes[0]
                            resolved_list.append({'기타거래': val, '매칭': items, '해결코드': winner, '해결카테고리': matches[winner]['cat'], '해결방법': '키워드구체성'})
                        else:
                            winner = max(longest_codes)
                            resolved_list.append({'기타거래': val, '매칭': items, '해결코드': winner, '해결카테고리': matches[winner]['cat'], '해결방법': '코드순서'})

        result['은행'] = {'전체': len(bank), '고유기타거래': len(kita_set),
                         '매칭': len(matched_list), '미매칭': len(unmatched_list),
                         '미매칭목록': unmatched_list,
                         '충돌수': len(conflict_list), '충돌목록': conflict_list[:50],
                         '해결수': len(resolved_list), '해결목록': resolved_list[:50]}

    if os.path.exists(card_path):
        with open(card_path, 'r', encoding='utf-8') as f:
            card = _json.load(f)
        kw_set = set()
        for r in card:
            v = r.get('키워드', '').strip()
            if v:
                kw_set.add(v)
        def _kw_match_card(kw, val):
            if kw.startswith('re:'):
                return bool(_re.search(kw[3:], val))
            return kw in val

        card_matched = []
        card_unmatched = []
        for val in sorted(kw_set):
            hit = None
            for kw, info in new_kw_map.items():
                if _kw_match_card(kw, val):
                    hit = info
                    break
            txns = [r for r in card if r.get('키워드', '').strip() == val]
            total_in = sum(_parse_amt(r.get('입금액', 0)) for r in txns)
            total_out = sum(_parse_amt(r.get('출금액', 0)) for r in txns)
            entry = {'키워드': val, '건수': len(txns), '테이블카테고리': txns[0].get('카테고리', '') if txns else ''}
            if hit:
                entry['매칭코드'] = hit['code']
                entry['매칭카테고리'] = hit['cat']
                card_matched.append(entry)
            else:
                entry['분류'] = CARD_DEFAULT_DEPOSIT if (total_in > 0 and total_out == 0) else CARD_DEFAULT_WITHDRAWAL
                card_unmatched.append(entry)

        result['카드'] = {'전체': len(card), '고유키워드': len(kw_set),
                         '매칭': len(card_matched), '미매칭': len(card_unmatched),
                         '미매칭목록': card_unmatched}

    return jsonify(result)


@app.route('/api/category-audit-report')
def category_audit_report():
    """계정과목 표준 검수 보고서 — 리팩토링 후 코드 전수검사 (2차)."""
    import json as _json, re as _re

    def _read(rel):
        p = os.path.join(_root, rel)
        if not os.path.exists(p):
            return ''
        try:
            with open(p, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception:
            return ''

    report = {}

    # ── 1. category_table.json 현황 ──
    ct_path = os.path.join(_root, 'data', 'category_table.json')
    ct = []
    if os.path.exists(ct_path):
        try:
            with open(ct_path, 'r', encoding='utf-8') as f:
                ct = _json.load(f)
        except Exception:
            pass
    by_cls = {}
    cat_set = set()
    kw_total = 0
    for r in ct:
        s = r.get('분류', '')
        by_cls[s] = by_cls.get(s, 0) + 1
        v = r.get('카테고리', '').strip()
        if v:
            cat_set.add(v)
        kw = r.get('키워드', '').strip()
        if kw:
            kw_total += len([k for k in kw.split('/') if k.strip()])
    report['현황'] = {
        '총행수': len(ct), '분류별': by_cls,
        '카테고리수': len(cat_set), '키워드수': kw_total,
    }

    # ── 파일 목록 ──
    py_files = [
        'MyBank/process_bank_data.py', 'MyBank/bank_app.py',
        'MyCard/process_card_data.py', 'MyCard/card_app.py',
        'MyCash/process_cash_data.py', 'MyCash/cash_app.py',
        'lib/category_table_io.py',
    ]
    tpl_files = [
        'MyBank/templates/index.html', 'MyBank/templates/category.html',
        'MyCard/templates/index.html', 'MyCard/templates/category.html',
        'MyCash/templates/index.html', 'MyCash/templates/category.html',
    ]

    # ── 2. 코드 표준화 현황 ──
    py_status = []
    for fp in py_files:
        content = _read(fp)
        has = bool(_re.search(r'from lib\.category_constants import', content))
        py_status.append({'파일': fp, '적용': has})

    tpl_status = []
    for fp in tpl_files:
        content = _read(fp)
        checks = {
            'VALID_CHASU': '{{ VALID_CHASU' in content,
            'COLUMN_CHASU_MAP': '{{ COLUMN_CHASU_MAP' in content,
            'CHASU_ORDER': '{{ CHASU_ORDER' in content,
            'CHASU_1_CODES': '{{ CHASU_1_CODES' in content,
        }
        tpl_status.append({'파일': fp, '적용수': sum(v for v in checks.values()), '상세': checks})
    report['표준화'] = {'Python': py_status, '템플릿': tpl_status}

    # ── 3. Python 하드코딩 전수검사 ──
    scan_pats = [
        (DIRECTION_CANCELLED, 'DIRECTION_CANCELLED'),
        (CANCELLED_TRANSACTION, 'CANCELLED_TRANSACTION'),
        (CLASS_NIGHT, 'CLASS_NIGHT'),
        (CLASS_INDUSTRY, 'CLASS_INDUSTRY'),
        (CLASS_RISK, 'CLASS_RISK'),
        (CLASS_PRE, 'CLASS_PRE'),
        (CLASS_POST, 'CLASS_POST'),
    ]
    py_hard = []
    for fp in py_files:
        lines = _read(fp).split('\n')
        for i, ln in enumerate(lines):
            s = ln.strip()
            if not s or s.startswith('#') or s.startswith('"""') or s.startswith("'''") or 'import ' in s:
                continue
            code = ln.split('#')[0] if '#' in ln else ln
            for pat, const in scan_pats:
                q1, q2 = "'" + pat + "'", '"' + pat + '"'
                if q1 not in code and q2 not in code:
                    continue
                if pat == DIRECTION_CANCELLED and ('취소된' in code or '취소_' in code):
                    continue
                col_ref = ("[" + q1 + "]") in code or ("[" + q2 + "]") in code
                col_ref = col_ref or (".get(" + q1) in code or (".get(" + q2) in code
                col_ref = col_ref or ("columns" in code.lower() and pat in code)
                if col_ref:
                    continue
                py_hard.append({
                    '파일': fp, '줄': i + 1,
                    '값': pat, '권장상수': const,
                    '코드': s[:140],
                })
    report['Python잔존'] = py_hard

    # ── 4. 템플릿 하드코딩 전수검사 ──
    tpl_pats = [
        CLASS_PRE, CLASS_POST, CLASS_ACCOUNT, CLASS_NIGHT, CLASS_INDUSTRY, CLASS_RISK,
        UNCLASSIFIED, DEFAULT_CATEGORY, CARD_CASH_PROCESSING, CANCELLED_TRANSACTION,
        BANK_DEFAULT_DEPOSIT, BANK_DEFAULT_WITHDRAWAL, CARD_DEFAULT_DEPOSIT, CARD_DEFAULT_WITHDRAWAL,
    ]
    tpl_hard = []
    for fp in tpl_files:
        lines = _read(fp).split('\n')
        for i, ln in enumerate(lines):
            if '{{' in ln and 'tojson' in ln:
                continue
            for pat in tpl_pats:
                if ("'" + pat + "'") in ln or ('"' + pat + '"') in ln or ('value="' + pat + '"') in ln or ('>' + pat + '</option>') in ln:
                    tpl_hard.append({
                        '파일': fp, '줄': i + 1,
                        '값': pat, '코드': ln.strip()[:140],
                    })
                    break
    report['템플릿잔존'] = tpl_hard

    # ── 5. 위험도 상수 분산 ──
    risk_consts = {
        'RISK_CLASS_TO_VALUE': ['lib/category_constants.py', 'lib/category_table_io.py'],
        'RISK_GUIDELINES_FIXED': ['MyCash/cash_app.py'],
        'RISK_DISPLAY_PRINT': ['MyCash/cash_app.py'],
        'RISK_DISPLAY_MAP': ['MyCash/templates/analysis_basic.html'],
        'RISK_CHART_LABELS': ['MyCash/templates/analysis_basic.html'],
        'SUGGESTION_TEMPLATES': ['MyCash/cash_app.py'],
        'LEGAL_REFERENCES': ['MyCash/cash_app.py'],
    }
    risk_findings = []
    for name, files in risk_consts.items():
        for fp in files:
            if name in _read(fp):
                risk_findings.append({'상수': name, '파일': fp})
    report['위험도상수'] = risk_findings

    # ── 6. 필터 특수값 ──
    filter_map = {}
    for fp in tpl_files:
        for m in _re.findall(r'__(\w{2,})__', _read(fp)):
            fv = '__' + m + '__'
            if fv not in filter_map:
                filter_map[fv] = []
            if fp not in filter_map[fv]:
                filter_map[fv].append(fp)
    report['필터특수값'] = [{'값': k, '파일': v} for k, v in sorted(filter_map.items())]

    # ── 7. 파편화 현황 (상수화 진행 상태 포함) ──
    report['파편화'] = [
        {'의미': '미매칭 입금', '은행': BANK_DEFAULT_DEPOSIT, '카드': CARD_DEFAULT_DEPOSIT, '금융종합': '(없음)', '상수화': 'O'},
        {'의미': '미매칭 출금', '은행': BANK_DEFAULT_WITHDRAWAL, '카드': CARD_DEFAULT_WITHDRAWAL, '금융종합': '(없음)', '상수화': 'O'},
        {'의미': '미매칭 기본값', '은행': '기타거래', '카드': '기타거래', '금융종합': '기타거래', '상수화': 'O'},
        {'의미': '미분류 상태', '은행': '미분류/미분류입금/출금', '카드': '미분류/미분류입금/출금', '금융종합': '미분류', '상수화': 'O'},
        {'의미': '카드 입금 특수', '은행': '—', '카드': '현금처리', '금융종합': '—', '상수화': 'O'},
        {'의미': '취소 거래', '은행': f'{DIRECTION_CANCELLED}/{CANCELLED_TRANSACTION}', '카드': DIRECTION_CANCELLED, '금융종합': DIRECTION_CANCELLED, '상수화': '△'},
        {'의미': '분류체계', '은행': '전처리/후처리/계정과목', '카드': '전처리/후처리/계정과목', '금융종합': '전처리/후처리/계정과목', '상수화': '△'},
    ]

    # ── 8. 종합 ──
    py_ok = sum(1 for s in py_status if s['적용'])
    tpl_ok = sum(1 for s in tpl_status if s['적용수'] > 0)
    py_by_p = {}
    for h in py_hard:
        py_by_p[h['값']] = py_by_p.get(h['값'], 0) + 1
    tpl_by_p = {}
    for h in tpl_hard:
        tpl_by_p[h['값']] = tpl_by_p.get(h['값'], 0) + 1
    report['종합'] = {
        'Python적용': f'{py_ok}/{len(py_files)}',
        'Jinja적용': f'{tpl_ok}/{len(tpl_files)}',
        'Python잔존수': len(py_hard),
        'Python잔존패턴': py_by_p,
        '템플릿잔존수': len(tpl_hard),
        '템플릿잔존패턴': tpl_by_p,
        '위험도상수수': len(risk_findings),
        '필터특수값수': len(report['필터특수값']),
    }

    return jsonify(report)


@app.route('/shutdown')
def shutdown():
    """서버 종료 요청. 로컬호스트에서만 허용. (임시폴더/파일 삭제는 시작 시에만 수행)"""
    remote = request.remote_addr or ''
    if remote not in ('127.0.0.1', '::1', 'localhost'):
        return 'Forbidden', 403, {'Content-Type': 'text/plain; charset=utf-8'}
    import threading
    def _do_shutdown():
        import time
        time.sleep(0.5)  # 응답 전송 대기
        try:
            os._exit(0)
        except Exception:
            sys.exit(0)
    threading.Thread(target=_do_shutdown, daemon=True).start()
    resp = make_response('''<!DOCTYPE html>
<html lang="ko"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>서버 종료</title><style>body{font-family:'Malgun Gothic',sans-serif;background:#f5f5f5;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;}
.container{text-align:center;padding:40px;background:white;border-radius:12px;box-shadow:0 2px 10px rgba(0,0,0,0.1);}
h1{color:#333;margin-bottom:16px;}p{color:#666;}</style></head>
<body><div class="container"><h1>서버를 종료합니다</h1><p>다음에 서버를 시작할 때 임시파일·임시폴더가 정리됩니다.</p><p id="msg" style="margin-top:20px;color:#999;">창을 닫는 중...</p></div>
<script>
setTimeout(function(){ try{ window.close(); setTimeout(function(){ document.getElementById("msg").innerHTML="자동으로 닫히지 않으면 이 창을 직접 닫아 주세요."; }, 500); }catch(e){} }, 800);
</script></body></html>''')
    resp.headers['Content-Type'] = 'text/html; charset=utf-8'
    resp.headers.update(_no_cache_headers())
    _APPLICANT_SESSION.clear()
    return resp


@app.route('/health')
def health():
    """Railway 등에서 서비스 생존 확인용 (템플릿 없이 200 반환)"""
    return 'OK', 200, {'Content-Type': 'text/plain; charset=utf-8'}


@app.route('/favicon.ico')
def favicon():
    return '', 204


@app.route('/img/<path:filename>')
def serve_img(filename):
    """보고서 배경 등에 사용하는 이미지 서빙 (프로젝트 루트 img/ 폴더)."""
    base = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(base, 'img', filename)
    if not os.path.isfile(path):
        return '', 404
    try:
        return send_file(path, as_attachment=False, max_age=3600)
    except Exception:
        return '', 404


@app.route('/api/verify-applicant', methods=['POST'])
def api_verify_applicant():
    """사용자명·이메일을 category_table 분류 '신청인'(카테고리=성명, 키워드=이메일)와 대조하여 동일인이면 쿠키 설정. 없으면 행 생성 후 성공."""
    try:
        data = request.get_json(force=True, silent=True) or {}
        username = (data.get('username') or '').strip()
        email = (data.get('email') or '').strip()
    except Exception:
        return jsonify({'ok': False, 'message': '요청 형식이 올바르지 않습니다.'}), 400

    if not username or not email:
        return jsonify({'ok': False, 'message': '사용자명과 이메일을 모두 입력하세요.'}), 200

    try:
        import pandas as pd
        from lib.path_config import get_category_table_json_path
        from lib.category_table_io import load_category_table, safe_write_category_table, normalize_category_df, CATEGORY_TABLE_COLUMNS
        path = get_category_table_json_path()
        df = load_category_table(path, default_empty=True)
        if df is None:
            df = pd.DataFrame(columns=CATEGORY_TABLE_COLUMNS)
        df = normalize_category_df(df, extended=True)
        df['분류'] = df['분류'].astype(str).str.strip()
        for col in ('분류', '키워드', '카테고리'):
            if col not in df.columns:
                return jsonify({'ok': False, 'message': '카테고리 테이블 형식이 올바르지 않습니다.'}), 200
        users = df[df['분류'] == CLASS_APPLICANT]

        if users.empty:
            new_row = pd.DataFrame([{'분류': CLASS_APPLICANT, '키워드': email, '카테고리': username, '위험도': '', '위험지표': ''}])
            df = pd.concat([df, new_row], ignore_index=True)
            safe_write_category_table(path, df, extended=True)
        else:
            matched = False
            for _, row in users.iterrows():
                kw = (str(row.get('키워드') or '')).strip()
                cat = (str(row.get('카테고리') or '')).strip()
                # 키워드가 이메일/연락처 형식이면 앞부분만 이메일로 비교
                stored_email = (kw.split('/', 1)[0] if '/' in kw else (kw.split('_', 1)[0] if '_' in kw else kw)).strip() if kw else ''
                if cat == username and stored_email == email:
                    matched = True
                    break
            if not matched:
                return jsonify({'ok': False, 'message': '일치하는 신청인 정보가 없습니다. 사용자명·이메일을 확인하거나 저장 후 다시 확인하세요.'}), 200

        _APPLICANT_SESSION['verified'] = True
        _APPLICANT_SESSION['name'] = username
        _APPLICANT_SESSION['email'] = email
        resp = make_response(jsonify({'ok': True}))
        resp.headers.update(_no_cache_headers())
        return resp
    except Exception as e:
        return jsonify({'ok': False, 'message': '확인 중 오류가 발생했습니다.'}), 200


def _dir_total_bytes(dir_path):
    """폴더 내 모든 파일 크기 합계(바이트). 없거나 오류 시 0."""
    if not dir_path or not os.path.isdir(dir_path):
        return 0
    try:
        total = 0
        for _rp, _dirs, _files in os.walk(dir_path):
            for _f in _files:
                try:
                    total += os.path.getsize(os.path.join(_rp, _f))
                except OSError:
                    pass
        return total
    except OSError:
        return 0


@app.route('/api/reset-file-sizes')
def reset_file_sizes():
    """초기화 페이지용: data/.source 내 JSON·XLSX 파일 크기 + bank/card/cash 의 __pycache__ 폴더 크기 반환."""
    try:
        data_dir = os.path.join(_root, 'data')
        out = {}
        for key, name in [
            ('bank_before', 'bank_before.json'),
            ('bank_after', 'bank_after.json'),
            ('card_before', 'card_before.json'),
            ('card_after', 'card_after.json'),
            ('cash_after', 'cash_after.json'),
            ('category_table_json', 'category_table.json'),
        ]:
            p = os.path.join(data_dir, name)
            if os.path.isfile(p):
                try:
                    out[key] = os.path.getsize(p)
                except OSError:
                    out[key] = None
            else:
                out[key] = None
        try:
            from lib.path_config import get_category_table_xlsx_path
            xlsx_path = get_category_table_xlsx_path()
        except ImportError:
            xlsx_path = os.path.join(_root, '.source', 'category_table.xlsx')
        if os.path.isfile(xlsx_path):
            try:
                out['category_table_xlsx'] = os.path.getsize(xlsx_path)
            except OSError:
                out['category_table_xlsx'] = None
        else:
            out['category_table_xlsx'] = None
        out['bank_pycache'] = _dir_total_bytes(os.path.join(_root, 'MyBank', '__pycache__'))
        out['card_pycache'] = _dir_total_bytes(os.path.join(_root, 'MyCard', '__pycache__'))
        out['cash_pycache'] = _dir_total_bytes(os.path.join(_root, 'MyCash', '__pycache__'))
        return jsonify(out)
    except Exception as e:
        return jsonify({}), 200


@app.route('/api/category-json-to-xlsx', methods=['POST'])
def api_category_json_to_xlsx():
    """category_table.json → .source/category_table.xlsx (category_json_to_xlsx.py 동작)."""
    try:
        from lib.category_table_io import export_category_table_to_xlsx, get_category_table_path
        ok, xlsx_path, err = export_category_table_to_xlsx(get_category_table_path())
        if ok:
            return jsonify({'success': True, 'path': xlsx_path})
        return jsonify({'success': False, 'error': err or '내보내기 실패'}), 400
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/category-json-to-md', methods=['POST'])
def category_json_to_md():
    """category_table.json → readme/가이드/계정과목_표준.md (계정과목 섹션만 재생성)."""
    import json as _json
    import re as _re

    json_path = os.path.join(_root, 'data', 'category_table.json')
    md_path = os.path.join(_root, 'readme', '가이드', '계정과목_표준.md')

    if not os.path.isfile(json_path):
        return jsonify({'success': False, 'error': 'category_table.json not found'}), 404

    with open(json_path, 'r', encoding='utf-8') as f:
        ct = _json.load(f)

    # --- 1. 기존 MD 읽기 → 헤더(## 5 이전) / 후미(## 6 이후) / 코드→소분류명·면책성격 매핑 파싱 ---
    header_lines = []
    footer_lines = []
    code_name_map = {}       # e.g. 'M01' → '자기계좌이체'
    code_desc_map = {}       # e.g. 'M01' → '본인 계좌 간 이동, 뱅킹 수수료 등. 실질 소비 아님.'
    code_immunity_map = {}   # e.g. 'M01' → '비소비성 — 실질 소비에서 분리'

    if os.path.isfile(md_path):
        with open(md_path, 'r', encoding='utf-8') as f:
            existing = f.read()
        lines = existing.split('\n')
        section = 'header'
        current_code = None
        for line in lines:
            ls = line.strip()
            if ls.startswith('## 5. 계정과목'):
                section = 'account'
                continue
            if section == 'account' and (ls.startswith('## 6.') or ls.startswith('## 6 ')):
                section = 'footer'
                footer_lines.append(line)
                continue
            if section == 'header':
                header_lines.append(line)
            elif section == 'footer':
                footer_lines.append(line)
            elif section == 'account':
                m = _re.match(r'^####\s+([A-Z]\d+)\s+(.+)$', ls)
                if m:
                    current_code = m.group(1)
                    code_name_map[current_code] = m.group(2).strip()
                    continue
                if current_code and ls.startswith('>'):
                    code_desc_map[current_code] = ls.lstrip('> ').strip()

        # 분류 체계 요약 테이블에서 면책 심사 성격 파싱
        in_summary = False
        for line in lines:
            ls = line.strip()
            if '면책 심사 성격' in ls:
                in_summary = True
                continue
            if in_summary and ls.startswith('|---'):
                continue
            if in_summary and ls.startswith('| '):
                cols = [c.strip() for c in ls.split('|')[1:-1]]
                if len(cols) >= 5:
                    code_col = cols[2].strip()
                    immunity_col = cols[4].strip()
                    if _re.match(r'^[A-Z]\d+$', code_col) and immunity_col:
                        code_immunity_map[code_col] = immunity_col
            elif in_summary and not ls.startswith('|'):
                in_summary = False
    else:
        header_lines = [
            '# 계정과목 표준 (Category Table Standard)',
            '',
            '> **용도**: 이 문서의 각 섹션을 파싱하여 `data/category_table.json`을 생성한다.',
            '',
            '---',
        ]

    # --- 2. JSON 데이터를 분류별로 그룹화 ---
    account_rows = [r for r in ct if r.get('분류') == CLASS_ACCOUNT]

    roman_order = ['I', 'II', 'III', 'IV', 'V', 'VI', 'VII']
    roman_name_map = {
        'I': '자금이동', 'II': '필수생활비', 'III': '재량소비',
        'IV': '고위험항목', 'V': '금융거래', 'VI': '인적거래', 'VII': '미분류',
    }

    def _extract_roman(risk_str):
        """'V_금융거래' → ('V', '금융거래')"""
        if not risk_str:
            return ('', '')
        m = _re.match(r'^(VII|VI|IV|V|III|II|I)[._\s]*(.*)', risk_str)
        if m:
            return (m.group(1), m.group(2).strip())
        return ('', risk_str)

    def _extract_mid(cat_str):
        """'F_금융' → '금융'"""
        if '_' in cat_str:
            return cat_str.split('_', 1)[1]
        return cat_str

    # 위험도(대분류) → 카테고리(중분류) → 위험지표(소분류코드) → [rows]
    from collections import OrderedDict
    struct = OrderedDict()
    for row in account_rows:
        risk = row.get('위험도', '')
        cat = row.get('카테고리', '')
        code = row.get('위험지표', '')
        roman, _ = _extract_roman(risk)
        if roman not in struct:
            struct[roman] = OrderedDict()
        if cat not in struct[roman]:
            struct[roman][cat] = OrderedDict()
        if code not in struct[roman][cat]:
            struct[roman][cat][code] = []
        struct[roman][cat][code].append(row)

    # roman 순서 정렬
    sorted_struct = OrderedDict()
    for r in roman_order:
        if r in struct:
            sorted_struct[r] = struct[r]
    for r in struct:
        if r not in sorted_struct:
            sorted_struct[r] = struct[r]

    # --- 3. 분류 체계 요약 테이블 생성 ---
    summary_lines = []
    summary_lines.append('### 분류 체계: 대분류 %d → 중분류 %d → 소분류 %d' % (
        len(sorted_struct),
        sum(len(cats) for cats in sorted_struct.values()),
        sum(len(codes) for cats in sorted_struct.values() for codes in cats.values()),
    ))
    summary_lines.append('')
    summary_lines.append('| 대분류 | 중분류 | 소분류 코드 | 소분류명 | 면책 심사 성격 |')
    summary_lines.append('|--------|--------|------------|---------|--------------|')

    for roman, cats in sorted_struct.items():
        roman_label = '%s. %s' % (roman, roman_name_map.get(roman, ''))
        first_roman = True
        for cat, codes in cats.items():
            mid_name = _extract_mid(cat)
            first_mid = True
            for code in sorted(codes.keys()):
                sub_name = code_name_map.get(code, '')
                immunity = code_immunity_map.get(code, '')
                r_col = roman_label if first_roman else ''
                m_col = mid_name if first_mid else ''
                summary_lines.append('| %s | %s | %s | %s | %s |' % (r_col, m_col, code, sub_name, immunity))
                first_roman = False
                first_mid = False

    # --- 4. 각 소분류별 상세 섹션 생성 ---
    detail_lines = []
    prev_roman = None
    prev_cat = None

    for roman, cats in sorted_struct.items():
        for cat, codes in cats.items():
            mid_name = _extract_mid(cat)
            roman_label = '%s. %s' % (roman, roman_name_map.get(roman, ''))

            if roman != prev_roman or cat != prev_cat:
                if prev_roman is not None:
                    detail_lines.append('')
                    detail_lines.append('---')
                detail_lines.append('')
                detail_lines.append('### %s — %s' % (roman_label, mid_name))

            for code in sorted(codes.keys()):
                sub_name = code_name_map.get(code, code)
                detail_lines.append('')
                detail_lines.append('#### %s %s' % (code, sub_name))

                desc = code_desc_map.get(code, '')
                if desc:
                    detail_lines.append('')
                    detail_lines.append('> %s' % desc)

                detail_lines.append('')
                detail_lines.append('| 키워드 |')
                detail_lines.append('|--------|')
                for row in codes[code]:
                    kw = row.get('키워드', '')
                    if kw:
                        detail_lines.append('| %s |' % kw)

            prev_roman = roman
            prev_cat = cat

    detail_lines.append('')
    detail_lines.append('---')

    # --- 5. 최종 조합: 헤더 + ## 5 계정과목 + 후미 ---
    output_parts = []
    output_parts.append('\n'.join(header_lines))
    output_parts.append('')
    output_parts.append('## 5. 계정과목')
    output_parts.append('')
    output_parts.append('\n'.join(summary_lines))
    output_parts.append('')
    output_parts.append('\n'.join(detail_lines))
    output_parts.append('')
    if footer_lines:
        output_parts.append('\n'.join(footer_lines))

    final = '\n'.join(output_parts)
    # 연속 빈줄 3개 이상 → 2개로 정리
    final = _re.sub(r'\n{4,}', '\n\n\n', final)

    os.makedirs(os.path.dirname(md_path), exist_ok=True)
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(final)

    return jsonify({'success': True, 'path': md_path})


@app.route('/api/category-xlsx-to-json', methods=['POST'])
def api_category_xlsx_to_json():
    """category_table.xlsx → data/category_table.json (category_xlsx_to_json.py 동작)."""
    try:
        import pandas as pd
        from lib import path_config
        from lib.category_table_io import (
            safe_write_category_table,
            normalize_category_df,
            get_category_table_path,
        )
        xlsx_path = path_config.get_category_table_xlsx_path()
        if not os.path.isfile(xlsx_path):
            return jsonify({'success': False, 'error': 'xlsx 파일이 없습니다: ' + xlsx_path}), 400
        df = pd.read_excel(xlsx_path, engine='openpyxl')
        df.columns = df.columns.astype(str).str.strip()
        df = normalize_category_df(df, extended=True)
        json_path = path_config.get_category_table_json_path()
        safe_write_category_table(json_path, df, extended=True)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ── 백업(j2x) / 복원(x2j) ──────────────────────────────────────────

@app.route('/api/backup', methods=['POST'])
def api_backup():
    """백업(j2x): data/*.json → xlsx 변환 + .source/ 원본 파일 → zip 다운로드."""
    import pandas as pd
    import zipfile
    from datetime import datetime

    _root = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(_root, 'data')
    source_dir = os.path.join(_root, '.source')
    json_names = [
        'category_table.json',
        'bank_before.json', 'bank_after.json',
        'card_before.json', 'card_after.json',
        'cash_after.json',
    ]

    items = []
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for jn in json_names:
            jp = os.path.join(data_dir, jn)
            if not os.path.isfile(jp):
                continue
            try:
                df = pd.read_json(jp, encoding='utf-8')
                xbuf = io.BytesIO()
                df.to_excel(xbuf, index=False, engine='openpyxl')
                xlsx_name = 'data/' + jn.replace('.json', '.xlsx')
                zf.writestr(xlsx_name, xbuf.getvalue())
                items.append(xlsx_name)
            except Exception:
                continue

        if os.path.isdir(source_dir):
            for dirpath, _dirs, files in os.walk(source_dir):
                for fname in files:
                    fpath = os.path.join(dirpath, fname)
                    arcname = '.source/' + os.path.relpath(fpath, source_dir).replace('\\', '/')
                    zf.write(fpath, arcname)
                    items.append(arcname)

    if not items:
        return jsonify({'success': False, 'error': '백업할 파일이 없습니다 (data/, .source/ 모두 비어 있음).'}), 400

    zip_buf.seek(0)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    return send_file(
        zip_buf,
        mimetype='application/zip',
        as_attachment=True,
        download_name=f'MyRisk_backup_{ts}.zip',
    )


@app.route('/api/restore', methods=['POST'])
def api_restore():
    """복원(x2j): zip 업로드 → .source/ 경로는 원래 구조로, data/ xlsx는 .source/에 추출."""
    import zipfile

    if 'file' not in request.files:
        return jsonify({'success': False, 'error': 'zip 파일이 전송되지 않았습니다.'}), 400

    f = request.files['file']
    if not f.filename or not f.filename.lower().endswith('.zip'):
        return jsonify({'success': False, 'error': 'zip 파일만 업로드 가능합니다.'}), 400

    _root = os.path.dirname(os.path.abspath(__file__))
    source_dir = os.path.join(_root, '.source')
    os.makedirs(source_dir, exist_ok=True)

    try:
        zip_data = io.BytesIO(f.read())
        extracted = []
        with zipfile.ZipFile(zip_data, 'r') as zf:
            for name in zf.namelist():
                low = name.lower()
                if not (low.endswith('.xlsx') or low.endswith('.xls')):
                    continue
                basename = os.path.basename(name)
                if not basename:
                    continue
                norm = name.replace('\\', '/')
                if norm.startswith('.source/'):
                    rel = norm[len('.source/'):]
                    target = os.path.join(source_dir, rel.replace('/', os.sep))
                else:
                    target = os.path.join(source_dir, basename)
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with zf.open(name) as src, open(target, 'wb') as dst:
                    dst.write(src.read())
                extracted.append(norm if norm.startswith('.source/') else basename)

        if not extracted:
            return jsonify({'success': False, 'error': 'zip 안에 xlsx/xls 파일이 없습니다.'}), 400
        return jsonify({'success': True, 'files': extracted})
    except zipfile.BadZipFile:
        return jsonify({'success': False, 'error': '유효하지 않은 zip 파일입니다.'}), 400
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/download/category_table.json')
def api_download_category_table_json():
    """서버의 category_table.json 파일 다운로드. Railway 등에서 수정 후 로컬 data와 동기화할 때 사용."""
    try:
        from lib.path_config import get_category_table_json_path
        path = get_category_table_json_path()
        if not path or not os.path.isfile(path):
            return jsonify({'error': 'category_table.json not found'}), 404
        return send_file(
            path,
            as_attachment=True,
            download_name='category_table.json',
            mimetype='application/json; charset=utf-8',
        )
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/reset-form-data')
def api_reset_form_data():
    """초기화 페이지 좌측 폼용: 입력란은 항상 공란 반환. 세션 인증 여부·심야구분(category_table)만 전달."""
    try:
        from lib.path_config import get_category_table_json_path
        from lib.category_table_io import load_category_table
        path = get_category_table_json_path()
        df = load_category_table(path, default_empty=True)
        심야시작 = ''
        심야종료 = ''
        has_user = False
        if df is not None and not (hasattr(df, 'empty') and df.empty):
            df = df.fillna('')
            df['분류'] = df['분류'].astype(str).str.strip()
            u = df[df['분류'] == CLASS_APPLICANT]
            has_user = not u.empty and str(u.iloc[0].get('카테고리', '') or '').strip() != ''
            s = df[df['분류'] == CLASS_NIGHT]
            if not s.empty:
                kw = str(s.iloc[0].get('키워드', '') or '').strip()
                if '/' in kw:
                    parts = kw.split('/', 1)
                    심야시작 = parts[0].strip()
                    심야종료 = parts[1].strip() if len(parts) > 1 else ''
        verified = _APPLICANT_SESSION.get('verified', False)
        return jsonify({
            '사용자명': '', '연락처': '', '이메일': '',
            '심야시작': 심야시작, '심야종료': 심야종료,
            'has_user': has_user,
            'verified': verified,
        })
    except Exception as e:
        return jsonify({'사용자명': '', '연락처': '', '이메일': '', '심야시작': '', '심야종료': '', 'has_user': False, 'verified': False, 'error': str(e)})


@app.route('/api/reset-form-lookup')
def api_reset_form_lookup():
    """신청인(성명)으로 category_table 분류 '신청인' 행 조회 → 연락처·이메일 반환. 없으면 빈 값."""
    try:
        from lib.path_config import get_category_table_json_path
        from lib.category_table_io import load_category_table
        name = (request.args.get('name') or '').strip()
        path = get_category_table_json_path()
        df = load_category_table(path, default_empty=True)
        연락처 = ''
        이메일 = ''
        if name and df is not None and not (hasattr(df, 'empty') and df.empty):
            df = df.fillna('')
            u = df[df['분류'].astype(str).str.strip() == CLASS_APPLICANT]
            if not u.empty:
                row = u.iloc[0]
                저장_성명 = str(row.get('카테고리', '') or '').strip()
                if 저장_성명 == name:
                    kw = str(row.get('키워드', '') or '').strip()
                    if '/' in kw:
                        parts = kw.split('/', 1)
                        이메일 = parts[0].strip() if len(parts) > 0 else ''
                        연락처 = parts[1].strip() if len(parts) > 1 else ''
                    elif '_' in kw:
                        parts = kw.split('_', 1)
                        이메일 = parts[0].strip() if len(parts) > 0 else ''
                        연락처 = parts[1].strip() if len(parts) > 1 else ''
                    else:
                        이메일 = kw
        return jsonify({'연락처': 연락처, '이메일': 이메일})
    except Exception as e:
        return jsonify({'연락처': '', '이메일': '', 'error': str(e)})


@app.route('/api/reset-form-save', methods=['POST'])
def api_reset_form_save():
    """초기화 페이지 좌측 폼 저장: 신청인(키워드=이메일/연락처, 카테고리=성명)·심야구분 행 추가 또는 갱신."""
    try:
        import pandas as pd
        from lib.path_config import get_category_table_json_path
        from lib.category_table_io import load_category_table, safe_write_category_table, normalize_category_df, CATEGORY_TABLE_COLUMNS
        data = request.get_json(force=True, silent=True) or {}
        사용자명 = str(data.get('사용자명', '') or '').strip()
        연락처 = str(data.get('연락처', '') or '').strip()
        이메일 = str(data.get('이메일', '') or '').strip()
        심야시작 = str(data.get('심야시작', '') or '').strip()
        심야종료 = str(data.get('심야종료', '') or '').strip()
        path = get_category_table_json_path()
        df = load_category_table(path, default_empty=True)
        if df is None:
            df = pd.DataFrame(columns=CATEGORY_TABLE_COLUMNS)
        df = normalize_category_df(df, extended=True)
        df['분류'] = df['분류'].astype(str).str.strip()

        # 분류 "신청인": 키워드=이메일/연락처 (슬래시 구분), 카테고리=성명 (1행만 유지, 5컬럼 유지)
        키워드_신청인 = '/'.join([이메일, 연락처]).strip('/')  # 이메일/연락처
        idx_user = df[df['분류'] == CLASS_APPLICANT].index
        if len(idx_user) > 0:
            df.loc[idx_user[0], '키워드'] = 키워드_신청인
            df.loc[idx_user[0], '카테고리'] = 사용자명
        else:
            df = pd.concat([df, pd.DataFrame([{'분류': CLASS_APPLICANT, '키워드': 키워드_신청인, '카테고리': 사용자명, '위험도': '', '위험지표': ''}])], ignore_index=True)

        # 심야구분 (5컬럼 유지)
        심야키워드 = (심야시작 + '/' + 심야종료) if (심야시작 or 심야종료) else ''
        idx_simya = df[df['분류'] == CLASS_NIGHT].index
        if len(idx_simya) > 0:
            df.loc[idx_simya[0], '키워드'] = 심야키워드
            df.loc[idx_simya[0], '카테고리'] = df.loc[idx_simya[0], '카테고리'] if '카테고리' in df.columns else CLASS_NIGHT
        else:
            df = pd.concat([df, pd.DataFrame([{'분류': CLASS_NIGHT, '키워드': 심야키워드, '카테고리': CLASS_NIGHT, '위험도': '', '위험지표': ''}])], ignore_index=True)

        safe_write_category_table(path, df, extended=True)
        if 사용자명 and 이메일:
            _APPLICANT_SESSION['verified'] = True
            _APPLICANT_SESSION['name'] = 사용자명
            _APPLICANT_SESSION['email'] = 이메일
            _APPLICANT_SESSION['contact'] = 연락처
        resp = make_response(jsonify({'success': True}))
        resp.headers.update(_no_cache_headers())
        return resp
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.errorhandler(404)
def page_not_found(e):
    """404 시 한글 안내 페이지 및 접속 가능한 URL 목록 표시"""
    return render_template('404.html'), 404


# ----- 8. 클라이언트 기동 시 서버에서 category_table 자동 당겨오기 -----
def _auto_sync_category_from_server():
    """SYNC_SERVER_URL이 설정된 경우 서버에서 category_table을 받아 data/category_table_YYYYMMDD_HHMMSS.json 으로 저장. 백그라운드에서 한 번만 실행."""
    import urllib.request
    import urllib.error
    from datetime import datetime
    base_url = os.environ.get('SYNC_SERVER_URL', '').strip().rstrip('/')
    if not base_url:
        return
    download_url = base_url + '/api/download/category_table.json'
    try:
        from lib import path_config
        data_dir = path_config.get_data_dir()
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        json_path = os.path.join(data_dir, f'category_table_{ts}.json')
        req = urllib.request.Request(download_url)
        req.add_header('Accept', 'application/json')
        with urllib.request.urlopen(req, timeout=30) as resp:
            if resp.status != 200:
                print(f"[자동동기화] 서버 응답 {resp.status}, 건너뜀.", flush=True)
                return
            body = resp.read()
        with open(json_path, 'wb') as f:
            f.write(body)
        print(f"[자동동기화] 복사 완료: {json_path}", flush=True)
    except Exception as e:
        print(f"[자동동기화] 실패 (건너뜀): {e}", flush=True)


# ----- 9. 진입점: 작업 디렉터리 설정 → waitress 서버 기동 -----
if __name__ == '__main__':
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)
    # 클라이언트에서 작업할 때: SYNC_SERVER_URL 이 있으면 서버에서 category_table 자동 당겨오기 (비동기)
    if os.environ.get('SYNC_SERVER_URL', '').strip():
        import threading
        t = threading.Thread(target=_auto_sync_category_from_server, daemon=True)
        t.start()
    # Railway/Heroku 등에서는 PORT가 주입되며 0.0.0.0으로 바인딩 필요
    try:
        port = int(os.environ.get('PORT', '8080'))
    except (TypeError, ValueError):
        port = 8080
    # 0.0.0.0으로 listen 시 localhost(IPv4/IPv6) 접속 가능
    host = '0.0.0.0'
    try:
        from waitress import serve
        print(f"서버 시작: http://127.0.0.1:{port} (종료: http://127.0.0.1:{port}/shutdown)", flush=True)
        # 로컬 기동 시 브라우저 자동 열기 (전체 화면 사용 권장)
        if not os.environ.get('RAILWAY_ENVIRONMENT') and not os.environ.get('HEROKU'):
            import threading
            import webbrowser
            import time
            def _open_browser():
                time.sleep(1.5)
                try:
                    webbrowser.open(f'http://127.0.0.1:{port}')
                except Exception:
                    pass
            threading.Thread(target=_open_browser, daemon=True).start()
        # threads 늘려서 요청 대기 시 queue depth 경고 완화
        serve(app, host=host, port=port, threads=8)
    except (ImportError, OSError) as e:
        # waitress 미설치 또는 바인딩 실패
        print(f"서버 시작 오류: {e}", flush=True)
        traceback.print_exc()
