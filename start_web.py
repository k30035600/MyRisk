#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
웹 서버 기동 진입점 (start_web.py)

[역할]
- PORT 환경변수 해석: 없거나 '$PORT'이면 8080 사용 (Heroku/Railway 호환).
- gunicorn 우선 실행; 미설치 시(Windows 등) waitress로 app:app 실행.

[사용]
  python start_web.py   또는 호스팅에서 이 스크립트를 프로세스로 지정.
"""
import os
import sys

# Railway 등 Linux 한글 출력을 위한 로케일 (자식 프로세스에 상속)
os.environ.setdefault("LANG", "en_US.UTF-8")
os.environ.setdefault("LC_ALL", "en_US.UTF-8")
os.environ.setdefault("PYTHONUTF8", "1")

try:
    port = (os.environ.get("PORT", "8080") or "").strip()
    if not port or port == "$PORT" or not port.isdigit():
        port = "8080"
    port = str(int(port))
except (ValueError, TypeError):
    port = "8080"
os.environ["PORT"] = port

# app이 프로젝트 루트 기준 경로를 쓰므로 진입 스크립트 위치로 chdir
_script_dir = os.path.dirname(os.path.abspath(__file__))
if _script_dir and os.path.isdir(_script_dir):
    os.chdir(_script_dir)

# Windows: gunicorn은 fcntl 등 Unix 전용이라 미지원 → waitress만 사용
if sys.platform == "win32":
    try:
        from waitress import serve
        from app import app
        serve(app, host="0.0.0.0", port=int(port))
    except ImportError as e:
        print("waitress가 없습니다. pip install waitress", file=sys.stderr)
        sys.exit(1)
else:
    # Linux 등: gunicorn 실행; 실패 시 waitress로 대체
    try:
        os.execvp(
            "gunicorn",
            [
                "gunicorn",
                "--bind", f"0.0.0.0:{port}",
                "app:app",
            ],
        )
    except (OSError, FileNotFoundError):
        try:
            from waitress import serve
            from app import app
            serve(app, host="0.0.0.0", port=int(port))
        except ImportError:
            print("gunicorn과 waitress가 모두 없습니다. pip install waitress 또는 gunicorn", file=sys.stderr)
            sys.exit(1)
