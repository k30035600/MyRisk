# -*- coding: utf-8 -*-
"""
MyRisk 통합 서버 (app.py)

[역할]
- MyBank(은행거래), MyCard(신용카드), MyCash(금융정보) 서브앱을 하나의 Flask 앱으로 제공.
- 공통 템플릿: 프로젝트 루트 templates/ (index.html, help.html, 404.html 등).

[실행 흐름] (유지보수 시 참고)
  1. 환경·인코딩(LANG, UTF-8) 설정 → Flask 앱 생성 → after_request(charset, gzip)
  2. lib 로드 후 path_config로 data/temp 경로 확보, 필수 디렉터리 생성(.source, .source/Bank, .source/Card, data, temp, readme)
  3. SUBAPP_CONFIG 순서대로 MyBank → MyCard → MyCash 서브앱 소스 읽기 → UTF-8 블록 패치 → 메모리 로드 → prefix 라우트 등록
  4. 메인 라우트: /, /help, /bank, /card, /cash, /reset, /shutdown, /health
  5. __main__ 시: waitress 서버 기동

[서브앱 요청 처리]
- create_proxy_view()가 요청 시 해당 앱 디렉터리로 chdir 후 뷰 실행. 서브앱은 ensure_working_directory로 cwd 고정.
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
# Railway 등: data/ 가 Git 제외라 배포 시 비어 있음. category_table.json 없으면 빈 파일 생성
try:
    if CATEGORY_TABLE_PATH and not os.path.exists(CATEGORY_TABLE_PATH):
        from lib.category_table_io import create_empty_category_table
        create_empty_category_table(CATEGORY_TABLE_PATH)
except (ImportError, OSError):
    pass


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
    # 기동 시간은 한국 표준시(KST)로 출력
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
    resp = make_response(render_template('reset.html', reset_left_header=left_header))
    resp.headers.update(_no_cache_headers())
    return resp


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
        users = df[df['분류'] == '신청인']

        if users.empty:
            # 분류 "신청인" 없으면 생성 후 동일인 처리 (5컬럼 유지)
            new_row = pd.DataFrame([{'분류': '신청인', '키워드': email, '카테고리': username, '위험도': '', '업종코드': ''}])
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
            u = df[df['분류'] == '신청인']
            has_user = not u.empty and str(u.iloc[0].get('카테고리', '') or '').strip() != ''
            s = df[df['분류'] == '심야구분']
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
            u = df[df['분류'].astype(str).str.strip() == '신청인']
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
        idx_user = df[df['분류'] == '신청인'].index
        if len(idx_user) > 0:
            df.loc[idx_user[0], '키워드'] = 키워드_신청인
            df.loc[idx_user[0], '카테고리'] = 사용자명
        else:
            df = pd.concat([df, pd.DataFrame([{'분류': '신청인', '키워드': 키워드_신청인, '카테고리': 사용자명, '위험도': '', '업종코드': ''}])], ignore_index=True)

        # 심야구분 (5컬럼 유지)
        심야키워드 = (심야시작 + '/' + 심야종료) if (심야시작 or 심야종료) else ''
        idx_simya = df[df['분류'] == '심야구분'].index
        if len(idx_simya) > 0:
            df.loc[idx_simya[0], '키워드'] = 심야키워드
            df.loc[idx_simya[0], '카테고리'] = df.loc[idx_simya[0], '카테고리'] if '카테고리' in df.columns else '심야구분'
        else:
            df = pd.concat([df, pd.DataFrame([{'분류': '심야구분', '키워드': 심야키워드, '카테고리': '심야구분', '위험도': '', '업종코드': ''}])], ignore_index=True)

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
