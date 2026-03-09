# -*- coding: utf-8 -*-
"""카테고리 기본 규칙(bank/card/cash) 및 xlsx 동기화. get_default_rules, sync_category_create_from_xlsx."""
import os

# 기본 규칙: 분류·키워드·카테고리 리스트 (최소한으로 빈 리스트 가능)
_DEFAULT_RULES = {
    'bank': [],
    'card': [],
    'cash': [],
}


def get_default_rules(kind):
    """kind in ('bank','card','cash') → [{'분류','키워드','카테고리'}, ...]"""
    return list(_DEFAULT_RULES.get(kind, []))


def sync_category_create_from_xlsx(path):
    """.source/category_table.xlsx에서 category_table 동기화. 실패 시 무시(no-op). path: category_table.json 경로."""
    # 스텁: 실제 구현 시 xlsx는 lib.path_config.get_category_table_xlsx_path() (.source/category_table.xlsx) 사용
    pass
