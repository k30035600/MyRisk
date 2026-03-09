# category_table XLSX → JSON 백업 (복원)

**.source/category_table.xlsx**를 읽어 **data/category_table.json**을 생성·복원하는 스크립트 안내.

## 스크립트

| 항목 | 내용 |
|------|------|
| **파일** | `.source/category_table_x2j_backup.py` |
| **실행** | 프로젝트 루트에서 `python .source/category_table_x2j_backup.py` |
| **선택 인자** | `python .source/category_table_x2j_backup.py [xlsx경로]` |

## 출력 JSON 컬럼 (5개)

| 컬럼 | 설명 |
|------|------|
| **분류** | 전처리, 후처리, 계정과목, 업종분류 등 |
| **키워드** | 매칭 키워드 |
| **카테고리** | 매칭 시 부여값 |
| **위험도** | 위험도 수치 (0.1~5.0 등) |
| **업종코드** | 업종 코드·참고용. **문자로 취급**(숫자 입력 시 소수점 없이 저장, 예: 1.0 → "1") |

- **업종코드**는 엑셀에서 숫자로 들어와도 JSON에는 정수 문자열로 저장됩니다(소수점 없음).

## 참고

- JSON → XLSX 백업: `data/category_table_j2x_backup.py`, [category_table_backup_정리.md](category_table_backup_정리.md)
