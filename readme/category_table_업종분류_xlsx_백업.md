# category_table / 업종분류 JSON → xlsx 백업

**category_table.json**과 **업종분류 데이터**(category_table 기반)를 각각 xlsx 파일로 내보내 백업·엑셀 편집용으로 사용하는 방법입니다.

---

## 1. 요약

| 항목 | category_table | 업종분류_table |
|------|----------------|----------------|
| **원본** | `MyRisk/data/category_table.json` | category_table 위험도 분류 행(1~10호) |
| **내보내기 결과** | `MyRisk/.source/category_table.xlsx` | `MyRisk/data/업종분류_table.xlsx` |
| **용도** | 백업, 엑셀 편집 | 백업, 엑셀 편집 |

- 앱(은행/카드/금융정보)은 **JSON만** 읽고 씁니다. xlsx는 **백업·참고·엑셀 편집용**입니다.

---

## 2. 개별 실행

### 2.1 category_table만 xlsx로

```powershell
cd MyRisk
python data/category_table_j2x_backup.py
```

- 상세: [category_table_xlsx_복구.md](category_table_xlsx_복구.md)

### 2.2 업종분류_table만 xlsx로

```powershell
cd MyRisk
python "readme/backup_업종분류_to_xlsx.py"
```

또는 Python에서:

```python
# 프로젝트 루트에서
from lib.category_table_io import export_risk_class_table_to_xlsx
from lib.path_config import DATA_DIR
import os
out_path = os.path.join(DATA_DIR, '업종분류_table.xlsx')
ok, path, err = export_risk_class_table_to_xlsx(xlsx_path=out_path)
if ok:
    print("저장됨:", path)
else:
    print("실패:", err)
```

---

## 3. xlsx 컬럼

### category_table.xlsx

| 컬럼 | 설명 |
|------|------|
| 분류 | 전처리, 후처리, 계정과목 등 |
| 키워드 | 매칭 키워드 (복수 시 `/` 구분) |
| 카테고리 | 매칭 시 넣을 값 |

### 업종분류_table.xlsx

| 컬럼 | 설명 |
|------|------|
| 업종분류 | 자료소명지표, 비정형지표, 투기성지표 등 |
| 위험도 | 위험도 수치 (소수점 1자리, 예: 1.0, 3.5) |
| 업종코드 | 업종 코드 (숫자일 경우 소수점 없이 문자) |
| 키워드 | 키워드·조건 설명 |

---

## 4. 관련 파일

| 파일 | 역할 |
|------|------|
| `lib/category_table_io.py` | `export_category_table_to_xlsx()`, `export_risk_class_table_to_xlsx()` 제공 |
| `data/category_table_j2x_backup.py` | category_table만 xlsx로 내보내는 스크립트 (data 폴더 백업용) |
| `readme/backup_업종분류_to_xlsx.py` | 업종분류_table만 xlsx로 내보내는 스크립트 |
| [category_table_xlsx_복구.md](category_table_xlsx_복구.md) | category_table xlsx 복구 상세 |
