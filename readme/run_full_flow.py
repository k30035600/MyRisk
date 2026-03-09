# -*- coding: utf-8 -*-
"""
전체 흐름 실행 (run_full_flow.py)

[역할]
- 은행 before/카테고리 확보(ensure) → MyCard·MyCash 모듈 로드 → (선택) 서버 기동.
- 사용: python run_full_flow.py [--no-server]
  --no-server 이면 서버는 기동하지 않고, 이후 python app.py 로 별도 실행.

[순서]
  1. MyBank.process_bank_data.ensure_bank_before_and_category()
  2. MyCard.card_app, MyCash.cash_app import (초기화)
  3. --no-server 없으면 app.py를 서브프로세스로 기동 후 포트 확인
"""
import os
import sys
import time

os.environ.setdefault("MYRISK_ROOT", os.path.dirname(os.path.abspath(__file__)))
_root = os.environ["MYRISK_ROOT"]
if _root not in sys.path:
    sys.path.insert(0, _root)
os.chdir(_root)

_SERVER_PORT = 8080
_SERVER_CHECK_WAIT = 2.0


def _log(msg):
    """표준 출력에 메시지 출력 (한글 등 인코딩 오류 시 무시)."""
    try:
        print(msg, flush=True)
    except (ValueError, OSError):
        pass


def _server_ready(host="127.0.0.1", port=_SERVER_PORT, timeout=2.0):
    """지정 포트에서 TCP 연결 가능 여부 확인. 서버 기동 완료 판단용."""
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        try:
            s.connect((host, port))
            return True
        finally:
            s.close()
    except (OSError, socket.error):
        return False


def main():
    """은행 ensure → 서브앱 로드 → (선택) 서버 기동."""
    _log("run_full_flow start")
    try:
        import MyBank.process_bank_data as pbd
        pbd.ensure_bank_before_and_category()
        _log("1. Bank OK")
        import MyCard.card_app
        import MyCash.cash_app
        _log("2. MyCard, MyCash OK")
        _log("3. Done.")
    except Exception as e:
        _log("ERROR: " + str(e))
        raise
    if "--no-server" not in sys.argv:
        _log("4. Starting server...")
        import subprocess
        subprocess.Popen(
            [sys.executable, os.path.join(_root, "app.py")],
            cwd=_root,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(_SERVER_CHECK_WAIT)
        if _server_ready(port=_SERVER_PORT):
            _log("5. Server ready: http://127.0.0.1:8080")
        else:
            _log("5. WARN: Server may not be ready yet. http://127.0.0.1:8080")
    else:
        _log("4. Server skipped (--no-server). Run: python app.py")


if __name__ == "__main__":
    main()
