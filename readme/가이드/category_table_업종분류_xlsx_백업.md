# category_table / 업종분류 백업 (JSON ↔ XLSX)

**category_table.json**과 **업종분류 데이터**를 각각 xlsx 파일로 내보내거나, xlsx에서 JSON을 복원하는 방법입니다.

---

## 1. 요약

| 방향 | 원본 | 결과 | 스크립트 |
|------|------|------|----------|
| **JSON → XLSX** (category_table) | `data/category_table.json` | `.source/category_table.xlsx` | `data/category_table_j2x_backup.py` |
| **JSON → XLSX** (업종분류_table) | category_table 위험도 분류 행(1~10호) | `data/업종분류_table.xlsx` | `readme/스크립트/backup_업종분류_to_xlsx.py` |
| **XLSX → JSON** (복원) | `.source/category_table.xlsx` | `data/category_table.json` | `.source/category_table_x2j_backup.py` |

- 앱(은행/카드/금융정보)은 **JSON만** 읽고 씁니다. xlsx는 **백업·참고·엑셀 편집용**입니다.

---

## 2. JSON → XLSX 내보내기

### 2.1 category_table만 xlsx로

```powershell
cd MyRisk
python data/category_table_j2x_backup.py
```

- 성공 시: `저장됨: ...\.source\category_table.xlsx` 출력.
- 실패 시: 오류 메시지 출력 후 종료 코드 1.

Python에서 직접 호출:

```python
from lib.category_table_io import export_category_table_to_xlsx, get_category_table_path

ok, xlsx_path, err = export_category_table_to_xlsx(get_category_table_path())
if ok:
    print("저장됨:", xlsx_path)
else:
    print("실패:", err)
```

### 2.2 업종분류_table만 xlsx로

```powershell
cd MyRisk
python "readme/스크립트/backup_업종분류_to_xlsx.py"
```

Python에서 직접 호출:

```python
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

## 3. XLSX → JSON 복원

`.source/category_table.xlsx`를 읽어 `data/category_table.json`을 생성·복원합니다.

```powershell
cd MyRisk
python .source/category_table_x2j_backup.py
```

선택 인자로 xlsx 경로를 지정할 수 있습니다:

```powershell
python .source/category_table_x2j_backup.py [xlsx경로]
```

---

## 4. xlsx 컬럼

### category_table.xlsx (3컬럼)

| 컬럼 | 설명 |
|------|------|
| 분류 | 전처리, 후처리, 계정과목 등 |
| 키워드 | 매칭 키워드 (복수 시 `/` 구분) |
| 카테고리 | 매칭 시 넣을 값 |

### 업종분류_table.xlsx (4컬럼)

| 컬럼 | 설명 |
|------|------|
| 업종분류 | 자료소명지표, 비정형지표, 투기성지표 등 |
| 위험도 | 위험도 수치 (소수점 1자리, 예: 1.0, 3.5) |
| 업종코드 | 업종 코드 (숫자일 경우 소수점 없이 문자) |
| 키워드 | 키워드·조건 설명 |

### XLSX → JSON 복원 시 JSON 컬럼 (5컬럼)

| 컬럼 | 설명 |
|------|------|
| 분류 | 전처리, 후처리, 계정과목, 업종분류 등 |
| 키워드 | 매칭 키워드 |
| 카테고리 | 매칭 시 부여값 |
| 위험도 | 위험도 수치 (0.1~5.0 등) |
| 업종코드 | 업종 코드·참고용. **문자로 취급** (숫자 입력 시 소수점 없이 저장, 예: 1.0 → "1") |

---

## 5. xlsx 수정 후 JSON에 반영하려면

1. **카테고리 화면 사용**: 웹 앱의 카테고리 페이지에서 항목 추가/수정/삭제하면 **JSON에만** 저장됩니다.  
   → 필요 시 위 방법으로 다시 **JSON → xlsx** 내보내기만 하면 됩니다.

2. **xlsx만 수정한 경우**:  
   - 현재 앱은 **xlsx → JSON** 자동 반영 기능을 제공하지 않습니다.  
   - xlsx에서 편집한 내용을 반영하려면, 카테고리 화면에서 같은 내용을 입력하거나,  
     XLSX → JSON 복원 스크립트(`.source/category_table_x2j_backup.py`)를 실행해야 합니다.

---

## 6. 스크립트 위치 정리

| 용도 | 위치 | 실행 |
|------|------|------|
| **JSON → XLSX** (category_table) | `data/category_table_j2x_backup.py` | `python data/category_table_j2x_backup.py` |
| **JSON → XLSX** (업종분류_table) | `readme/스크립트/backup_업종분류_to_xlsx.py` | `python "readme/스크립트/backup_업종분류_to_xlsx.py"` |
| **XLSX → JSON** (복원) | `.source/category_table_x2j_backup.py` | `python .source/category_table_x2j_backup.py` |

## 7. 관련 파일

| 파일 | 역할 |
|------|------|
| `lib/category_table_io.py` | `export_category_table_to_xlsx()`, `export_risk_class_table_to_xlsx()` 제공 |
| `data/category_table_j2x_backup.py` | category_table JSON → XLSX 내보내기 스크립트 |
| `readme/스크립트/backup_업종분류_to_xlsx.py` | 업종분류_table JSON → XLSX 내보내기 스크립트 |
| `.source/category_table_x2j_backup.py` | XLSX → JSON 복원 스크립트 |
