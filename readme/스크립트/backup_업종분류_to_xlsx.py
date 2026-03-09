# -*- coding: utf-8 -*-
"""
업종분류 데이터(category_table 기반) → data/업종분류_table.xlsx 내보내기.

category_table.json → .source/category_table.xlsx 백업은 data/category_table_j2x_backup.py 사용.

실행: 프로젝트 루트(MyRisk)에서
  python "readme/backup_업종분류_to_xlsx.py"

결과: data/업종분류_table.xlsx 생성.
"""
import os
import sys

_script_dir = os.path.dirname(os.path.abspath(__file__))
_root = os.path.dirname(_script_dir)
if _root not in sys.path:
    sys.path.insert(0, _root)

try:
    from lib.path_config import DATA_DIR
except ImportError:
    DATA_DIR = os.path.join(_root, 'data')

from lib.category_table_io import export_risk_class_table_to_xlsx


def backup_업종분류_table_to_xlsx():
    """업종분류 데이터(category_table 기반) → data/업종분류_table.xlsx. (True, path) or (False, error_msg)."""
    out_path = os.path.join(DATA_DIR, '업종분류_table.xlsx')
    ok, xpath, err = export_risk_class_table_to_xlsx(xlsx_path=out_path)
    if ok:
        return (True, xpath)
    return (False, err or "업종분류_table 내보내기 실패")


if __name__ == '__main__':
    ok, res = backup_업종분류_table_to_xlsx()
    if ok:
        print(f"[OK] 업종분류_table.xlsx → {res}")
    else:
        print(f"[FAIL] 업종분류_table: {res}")
        sys.exit(1)
