# -*- coding: utf-8 -*-
"""
카테고리 기본 규칙.

get_default_rules(kind) — 모듈별 기본 카테고리 규칙 반환.
"""
_DEFAULT_RULES = {
    'bank': [],
    'card': [],
    'cash': [],
}


def get_default_rules(kind):
    """kind='bank'|'card'|'cash' → 기본 규칙 리스트 [{'분류','키워드','카테고리'}, ...]."""
    return list(_DEFAULT_RULES.get(kind, []))


