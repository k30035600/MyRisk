# category_table 백업 스크립트 정리

## 현재 사용 (권장)

| 용도 | 위치 | 실행 |
|------|------|------|
| **JSON → XLSX** (data 폴더 기준 백업) | `data/category_table_j2x_backup.py`, `data/category_table_j2x_backup.md` | `python data/category_table_j2x_backup.py` |
| **XLSX → JSON** (.source 폴더 기준 복원) | `.source/category_table_x2j_backup.py`, `readme/category_table_j2x_backup.md` | `python .source/category_table_x2j_backup.py` |

- **입력/출력**: data/category_table.json ↔ .source/category_table.xlsx (lib.path_config 경로 사용)
- **XLSX → JSON 스크립트 실제 위치**: `.source/` 폴더. (기존 `category_xlsx_to_json_backup.*` → `category_table_x2j_backup.*` 로 파일명 변경)

## 삭제한 파일

- `readme/export_category_table_to_xlsx.py` — 기능이 `data/category_table_j2x_backup.py`로 통합됨.
- `readme/category_table_xlsx_to_json.py` — 기능이 `.source/category_table_x2j_backup.py`로 통합됨.
- `category_table_xlsx_to_json.py` (루트) — 위와 중복되어 삭제.
- `backup_category_risk_class_xlsx.py` (루트) — 삭제. 업종분류 xlsx는 `readme/backup_업종분류_to_xlsx.py`로 내보냄 (data/업종분류_table.xlsx).
- `readme/category_create.md` — 삭제. 앱에서 파싱하지 않음(문서 참고용이었음).

## 수정한 파일 (category_table 백업 제거)

- **readme/backup_업종분류_to_xlsx.py** — 업종분류_table xlsx 내보내기만 수행. (category_table 백업은 `data/category_table_j2x_backup.py` 사용.)

## 유지한 파일

- **lib/category_table_io.py** — `export_category_table_to_xlsx()` 등은 계속 사용. data/.source 백업 스크립트가 이 함수를 호출함.
- **readme/add_virtual_asset_category.py** — category_table.json에 행 추가용. 백업 스크립트와 무관하여 유지.
