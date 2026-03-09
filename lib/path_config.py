# -*- coding: utf-8 -*-
"""
프로젝트 경로 설정 (data, temp, .source).

DATA_DIR, TEMP_DIR, SOURCE_DIR 상수와 get_category_table_json_path, get_bank_after_path 등
주요 파일 경로 함수를 제공한다. 배포 시 DATA_DIR, CATEGORY_TABLE_JSON_PATH 환경변수로 오버라이드 가능.

주요 상수: DATA_DIR, TEMP_DIR, SOURCE_DIR
주요 함수: get_data_dir, get_temp_dir, get_category_table_json_path, get_category_table_xlsx_path,
  get_bank_after_path, get_card_after_path, get_cash_after_path, delete_all_after_files,
  get_source_bank_dir, get_source_card_dir
"""
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DATA_DIR_ENV = os.environ.get("DATA_DIR", "").strip()
_CATEGORY_TABLE_JSON_ENV = os.environ.get("CATEGORY_TABLE_JSON_PATH", "").strip()

DATA_DIR = os.path.join(_ROOT, "data") if not _DATA_DIR_ENV else _DATA_DIR_ENV
TEMP_DIR = os.path.join(_ROOT, 'temp')
SOURCE_DIR = os.path.join(_ROOT, '.source')


def get_data_dir():
    """data 디렉터리 생성 후 경로 반환."""
    os.makedirs(DATA_DIR, exist_ok=True)
    return DATA_DIR


def get_temp_dir():
    """temp 디렉터리 생성 후 경로 반환."""
    os.makedirs(TEMP_DIR, exist_ok=True)
    return TEMP_DIR


def get_category_table_json_path():
    """category_table.json 경로 (data 폴더에서 관리).
    환경변수 CATEGORY_TABLE_JSON_PATH가 있으면 그 경로를 사용."""
    if _CATEGORY_TABLE_JSON_ENV:
        return _CATEGORY_TABLE_JSON_ENV
    return os.path.join(DATA_DIR, 'category_table.json')


def get_category_table_xlsx_path():
    """category_table.xlsx 경로 (.source 폴더에서 관리)."""
    return os.path.join(SOURCE_DIR, 'category_table.xlsx')


def get_bank_after_path():
    """bank_after.json 경로 (data 폴더)."""
    return os.path.join(DATA_DIR, 'bank_after.json')


def get_card_after_path():
    """card_after.json 경로 (data 폴더)."""
    return os.path.join(DATA_DIR, 'card_after.json')


def get_cash_after_path():
    """cash_after.json 경로 (data 폴더)."""
    return os.path.join(DATA_DIR, 'cash_after.json')


def delete_all_after_files():
    """카테고리 입력/수정/삭제 후 bank_after, card_after, cash_after 삭제 (재분류 유도)."""
    for p in (get_bank_after_path(), get_card_after_path(), get_cash_after_path()):
        try:
            if os.path.isfile(p):
                os.remove(p)
        except OSError:
            pass


def get_source_bank_dir():
    """은행 원본 디렉터리 (.source/Bank)."""
    return os.path.join(SOURCE_DIR, 'Bank')


def get_source_card_dir():
    """신용카드 원본 디렉터리 (.source/Card)."""
    return os.path.join(SOURCE_DIR, 'Card')
