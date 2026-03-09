# -*- coding: utf-8 -*-
"""
category_table XLSX → JSON (category_table_xlsx_to_json.py)

[역할]
- .source/category_table.xlsx를 읽어 data/category_table.json을 생성·갱신.
- 출력 JSON 컬럼: 분류, 키워드, 카테고리, 위험도, 업종코드 (5컬럼).

[실행]
  프로젝트 루트에서: python readme/category_table_xlsx_to_json.py
"""
import os
import sys

_script_dir = os.path.dirname(os.path.abspath(__file__))
_root = os.path.dirname(_script_dir)
if _root not in sys.path:
    sys.path.insert(0, _root)

def main():
    import pandas as pd
    from lib import path_config
    from lib.category_table_io import (
        safe_write_category_table,
        normalize_category_df,
        CATEGORY_TABLE_EXTENDED_COLUMNS,
    )
    xlsx_path = path_config.get_category_table_xlsx_path()
    if not os.path.isfile(xlsx_path):
        print(f"xlsx 파일이 없습니다: {xlsx_path}")
        return 1
    df = pd.read_excel(xlsx_path, engine='openpyxl')
    df = normalize_category_df(df, extended=True)
    json_path = path_config.get_category_table_json_path()
    os.makedirs(os.path.dirname(json_path) or '.', exist_ok=True)
    safe_write_category_table(json_path, df, extended=True)
    print(f"저장됨: {json_path} (행 수: {len(df)}, 컬럼: {CATEGORY_TABLE_EXTENDED_COLUMNS})")
    return 0

if __name__ == '__main__':
    sys.exit(main())
