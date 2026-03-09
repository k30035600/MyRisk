# -*- coding: utf-8 -*-
"""
카테고리 기본 규칙 및 xlsx → json 동기화.

get_default_rules(kind) — 모듈별 기본 카테고리 규칙 반환.
sync_category_create_from_xlsx(json_path) — .source/category_table.xlsx → category_table.json 단방향 동기화.
"""
import os

_DEFAULT_RULES = {
    'bank': [],
    'card': [],
    'cash': [],
}


def get_default_rules(kind):
    """kind='bank'|'card'|'cash' → 기본 규칙 리스트 [{'분류','키워드','카테고리'}, ...]."""
    return list(_DEFAULT_RULES.get(kind, []))


def sync_category_create_from_xlsx(json_path):
    """.source/category_table.xlsx가 있으면 json_path로 동기화. 없거나 실패 시 무시."""
    try:
        from lib.path_config import get_category_table_xlsx_path
        xlsx_path = get_category_table_xlsx_path()
    except ImportError:
        return
    if not xlsx_path or not os.path.isfile(xlsx_path):
        return
    try:
        import pandas as pd
        df = pd.read_excel(xlsx_path, engine='openpyxl')
        if df is None or df.empty:
            return
        from lib.category_table_io import normalize_category_df, safe_write_category_table
        df = normalize_category_df(df, extended=True)
        safe_write_category_table(json_path, df, extended=True)
    except Exception:
        pass
