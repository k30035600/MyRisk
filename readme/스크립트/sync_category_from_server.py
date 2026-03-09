# -*- coding: utf-8 -*-
"""
서버 → 로컬 category_table 복사 (날짜·시간 붙여 저장) (sync_category_from_server.py)

[역할]
- Railway 등 웹 앱에서 category_table을 수정·저장한 뒤, 그 내용을 로컬 data/에
  파일명 뒤에 _날짜_시간을 붙여 복사할 때 사용합니다.
- 저장 파일: data/category_table_YYYYMMDD_HHMMSS.json (예: category_table_20260302_143052.json)
- 서버의 GET /api/download/category_table.json 을 호출해 받은 내용을 해당 파일로 저장합니다.

[실행]
  프로젝트 루트에서:
    python readme/sync_category_from_server.py
    python readme/sync_category_from_server.py https://본인도메인.up.railway.app

  환경 변수로 서버 주소 고정:
    set SYNC_SERVER_URL=https://본인도메인.up.railway.app
    python readme/sync_category_from_server.py
"""
import os
import sys
from datetime import datetime
import urllib.request
import urllib.error

_script_dir = os.path.dirname(os.path.abspath(__file__))
_root = os.path.dirname(_script_dir)
if _root not in sys.path:
    sys.path.insert(0, _root)


def main():
    # 서버 URL: 인자 > 환경변수 SYNC_SERVER_URL
    base_url = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get('SYNC_SERVER_URL', '')).strip()
    if not base_url:
        print('사용법: python readme/sync_category_from_server.py <서버URL>')
        print('  예: python readme/sync_category_from_server.py https://본인도메인.up.railway.app')
        print('  또는 환경변수 SYNC_SERVER_URL 을 설정한 뒤 인자 없이 실행.')
        return 1
    base_url = base_url.rstrip('/')
    download_url = base_url + '/api/download/category_table.json'

    from lib import path_config
    data_dir = path_config.get_data_dir()
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    copy_filename = f'category_table_{ts}.json'
    json_path = os.path.join(data_dir, copy_filename)

    try:
        req = urllib.request.Request(download_url)
        req.add_header('Accept', 'application/json')
        with urllib.request.urlopen(req, timeout=30) as resp:
            if resp.status != 200:
                print(f'오류: 서버 응답 {resp.status} — {download_url}')
                return 1
            body = resp.read()
        # UTF-8로 저장 (날짜·시간 붙인 복사본)
        with open(json_path, 'wb') as f:
            f.write(body)
        print(f'복사 완료: {json_path}')
        return 0
    except urllib.error.HTTPError as e:
        print(f'HTTP 오류: {e.code} — {download_url}')
        if e.code == 404:
            print('  서버에 /api/download/category_table.json 라우트가 있는지 확인하세요.')
        return 1
    except urllib.error.URLError as e:
        print(f'연결 오류: {e.reason}')
        return 1
    except Exception as e:
        print(f'오류: {e}')
        return 1


if __name__ == '__main__':
    sys.exit(main())
