# -*- coding: utf-8 -*-
"""
금융정보 전용 데이터 처리 (process_cash_data.py)

[역할]
- cash_after는 bank_after + card_after 병합 후 업종분류·위험도(1~10호)만 적용. 전처리/계정과목/후처리 단계 없음.
- 병합 시 bank/card after를 다시 만들지 않고, 이미 있는 JSON만 읽어 사용. 은행·카드에서 적용된 키워드·카테고리를 유지하고 업종분류·위험도만 추가.

[주요 사용처]
- cash_app.merge_bank_card_to_cash_after(): 병합·저장 진입점.
- classify_and_save(): cash_before 단일 파일용 예외 경로(전처리/후처리 미적용).
"""
import pandas as pd
import os
import re
import unicodedata
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.normpath(os.path.join(_SCRIPT_DIR, '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from lib.shared_app_utils import setup_win32_utf8, safe_str, clean_amount
from lib.excel_io import safe_write_excel
from lib.category_table_defaults import get_default_rules
from lib.category_constants import (
    DEFAULT_CATEGORY, UNCLASSIFIED, CHASU_TO_CLASS, CLASS_PRE,
    DIRECTION_CANCELLED, CANCELLED_TRANSACTION,
)
from lib.category_table_io import (
    load_category_table as load_category_table_io,
    normalize_category_df,
    normalize_주식회사_for_match,
    CATEGORY_TABLE_COLUMNS,
)
from lib.data_json_io import safe_write_data_json, safe_read_data_json

setup_win32_utf8()

# 금융정보는 bank_after+card_after만 사용. .source/Cash 미사용.
# category_table.json: data 폴더에서 관리
CATEGORY_TABLE_FILE = os.path.join(os.environ.get('MYRISK_ROOT', PROJECT_ROOT), 'data', 'category_table.json')
CASH_CATEGORY_LABEL = '금융정보'

OUTPUT_FILE = os.path.join(PROJECT_ROOT, "data", "cash_after.json")


def ensure_all_cash_files():
    """금융정보에서는 category_table.json을 생성하지 않음. cash_after는 bank/card 병합(merge_bank_card)으로만 생성."""
    pass


def normalize_text(text):
    """텍스트 정규화 (대소문자 구분)"""
    if not text:
        return ""
    return str(text).strip()

def create_before_text(row):
    """before_text 생성"""
    bank_name = safe_str(row.get("은행명", ""))
    parts = []

    적요 = safe_str(row.get("적요", ""))
    if not 적요 and bank_name:
        적요 = f"[{bank_name}]"
    parts.append(적요)

    내용 = safe_str(row.get("내용", ""))
    if not 내용 and bank_name:
        내용 = f"[{bank_name}]"
    parts.append(내용)

    parts.append(safe_str(row.get("거래점", "")))
    parts.append(safe_str(row.get("송금메모", "")))

    return "#".join([p for p in parts if p])

def classify_1st_category(row):
    """입출금 분류: 입금/출금/취소"""
    before_text = safe_str(row.get("before_text", ""))
    구분 = safe_str(row.get("폐업", row.get("구분", "")))

    if DIRECTION_CANCELLED in before_text or CANCELLED_TRANSACTION in before_text:
        return DIRECTION_CANCELLED
    if DIRECTION_CANCELLED in 구분 or CANCELLED_TRANSACTION in 구분:
        return DIRECTION_CANCELLED

    in_amt = row.get("입금액", 0) or 0
    out_amt = row.get("출금액", 0) or 0

    if out_amt > 0:
        return "출금"
    return "입금"

def classify_etc(row_idx, df, category_tables):
    """기타거래 분류"""
    row = df.iloc[row_idx]
    before_text_raw = row.get("before_text", "")
    before_text = normalize_text(before_text_raw)

    if not before_text_raw or not before_text_raw.strip():
        적요 = safe_str(row.get("적요", ""))
        if 적요:
            return 적요[:30] if len(적요) > 30 else 적요
        return ""

    result = ""
    if DEFAULT_CATEGORY in category_tables:
        category_table = category_tables[DEFAULT_CATEGORY]
        category_rows_list = list(category_table.iterrows())
        sorted_rows = sorted(category_rows_list, key=lambda x: len(str(x[1].get("키워드", ""))), reverse=True)

        for _, cat_row in sorted_rows:
            keyword_raw = cat_row.get("키워드", "")
            if pd.isna(keyword_raw) or not keyword_raw:
                continue

            keyword = normalize_text(keyword_raw)

            if keyword and before_text and keyword in before_text:
                category_raw = cat_row.get("카테고리", "")

                original_before_text = safe_str(row.get("before_text", ""))
                updated_before_text = original_before_text.replace(str(keyword_raw), "").strip()
                df.at[row_idx, "before_text"] = updated_before_text

                if pd.notna(category_raw):
                    category_str = str(category_raw).strip()
                    if category_str:
                        result = category_str

                break

    current_before_text = safe_str(row.get("before_text", ""))
    normalized_current = normalize_text(current_before_text)
    if normalized_current in ['space']:
        df.at[row_idx, "before_text"] = ""
        return ""

    if result:
        return result

    before_text = safe_str(row.get("before_text", ""))
    before_text = re.sub(r'\[[^\]]+\]', '', before_text)

    excluded_texts = []

    branch = safe_str(row.get("거래지점", ""))
    if branch and branch != UNCLASSIFIED:
        excluded_texts.append(branch)
        bracket_matches = re.findall(r'\(([^)]+)\)', branch)
        excluded_texts.extend(bracket_matches)

    bank_name = safe_str(row.get("은행명", ""))
    if bank_name:
        excluded_texts.append(bank_name)

    excluded_texts = list(set([t.strip() for t in excluded_texts if t.strip()]))
    excluded_texts.sort(key=len, reverse=True)

    remaining_text = before_text
    for excluded in excluded_texts:
        if excluded:
            pattern = re.escape(excluded)
            remaining_text = re.sub(r'\b' + pattern + r'\b', ' ', remaining_text, flags=re.IGNORECASE)
            remaining_text = remaining_text.replace(excluded, " ")

    remaining_text = re.sub(r'\s+', ' ', remaining_text).strip()
    remaining_text = remaining_text.replace('#', ' ').strip()

    if remaining_text:
        return remaining_text[:30] if len(remaining_text) > 30 else remaining_text

    return ""

def load_category_table():
    """category_table.json 로드 및 category_tables 구성 (구분 없음). 금융정보에서는 전처리/후처리 미적용, 계정과목·기타거래용으로만 사용. 파일 없으면 빈 dict 반환."""
    if not CATEGORY_TABLE_FILE or not os.path.exists(CATEGORY_TABLE_FILE):
        return {}
    category_df = load_category_table_io(CATEGORY_TABLE_FILE, default_empty=True)
    if category_df is None or category_df.empty:
        return {}
    category_df = normalize_category_df(category_df)
    category_tables = {}
    분류_컬럼명 = '분류' if '분류' in category_df.columns else '차수'
    for 값 in category_df[분류_컬럼명].unique():
        if pd.notna(값):
            값_str = str(값).strip()
            if 분류_컬럼명 == '차수' and 값_str in CHASU_TO_CLASS:
                분류명 = CHASU_TO_CLASS[값_str]
            else:
                분류명 = 값_str
            category_tables[분류명] = category_df[category_df[분류_컬럼명] == 값].copy()

    return category_tables

if __name__ == '__main__':
    ensure_all_cash_files()
