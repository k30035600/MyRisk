# -*- coding: utf-8 -*-
"""
금융정보 전용 데이터 처리 (process_cash_data.py)

cash_after는 bank_after + card_after 병합 후 업종분류·위험도(1~10호)만 적용.
실제 병합 로직은 cash_app.merge_bank_card_to_cash_after()에서 수행.
이 모듈은 경로 상수만 제공한다.
"""
import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.normpath(os.path.join(_SCRIPT_DIR, '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

CATEGORY_TABLE_FILE = os.path.join(os.environ.get('MYRISK_ROOT', PROJECT_ROOT), 'data', 'category_table.json')
CASH_CATEGORY_LABEL = '금융정보'
OUTPUT_FILE = os.path.join(PROJECT_ROOT, "data", "cash_after.json")
