# Bank / Card : source → before → after 구현 비교

은행(MyBank)과 신용카드(MyCard)의 **원본(source) → 전처리(before) → 카테고리적용(after)** 구현 방식을 비교한 문서입니다.

---

## 1. 전체 흐름

| 단계 | 은행 (Bank) | 카드 (Card) |
|------|-------------|--------------|
| **Source** | `.source/Bank` 의 .xls, .xlsx | `.source/Card` 의 .xls, .xlsx |
| **Before** | `data/bank_before.json` (전처리만) | `data/card_before.json` (전처리만) |
| **After** | `data/bank_after.json` (계정과목·후처리 적용) | `data/card_after.json` (계정과목·후처리 적용) |
| **공통** | `data/category_table.json` (전처리/후처리/계정과목 규칙) | 동일 |

---

## 2. 구현 위치 (모듈·함수)

| 구분 | 은행 | 카드 |
|------|------|------|
| **모듈** | `MyBank/process_bank_data.py` | `MyCard/process_card_data.py` |
| **Source → Before** | `integrate_bank_transactions(output_file=None)` | `integrate_card_excel(output_file=None, base_dir=None, skip_write=False)` |
| **Before → After** | `classify_and_save(input_file=None, output_file=None, input_df=None)` | `classify_and_save(input_df=None)` |
| **앱 역할** | 위 두 함수만 호출 (bank_app) | 위 두 함수만 호출 (card_app) |

둘 다 **한 process_*_data 모듈**에서 source 읽기, before 저장, after 생성까지 담당합니다.

---

## 3. Source 읽기 (→ Before 입력)

| 항목 | 은행 | 카드 |
|------|------|------|
| **소스 경로** | `SOURCE_BANK_DIR` = `.source/Bank` | `SOURCE_CARD_DIR` = `.source/Card` |
| **파일 조건** | 파일명에 국민은행/신한은행/하나은행 포함 (국민은행은 .xlsx만) | 모든 .xls, .xlsx |
| **읽기 방식** | 은행별 전용 함수 (read_kb_file_excel, read_sh_file, read_hana_file) | pd.read_excel(header=None) + 시트별 _extract_rows_from_sheet |
| **출력** | DataFrame 리스트 → pd.concat | 행 리스트 → DataFrame(_EXTRACT_COLUMNS) |

---

## 4. Before 생성 (저장)

| 항목 | 은행 | 카드 |
|------|------|------|
| **저장 경로** | `BANK_BEFORE_FILE` (항상 `data/bank_before.json`) | `CARD_BEFORE_FILE` (항상 `data/card_before.json`) |
| **output_file 인자** | 있으나 **미사용** (항상 고정 경로) | 있으나 **미사용** (은행 기준 통일) |
| **데이터 없을 때** | 저장 안 함, 빈 DataFrame 반환 | 저장 안 함, 빈 DataFrame 반환 |
| **전처리** | _apply_전처리_only (적요·내용·송금메모·거래점) | _apply_전처리_only_to_columns (가맹점명·카드사) |
| **표준 컬럼** | 거래일, 거래시간, 은행명, 계좌번호, 입금액, 출금액, 사업자번호, 폐업, 취소, 적요, 내용, 송금메모, 거래점 | 카드사, 카드번호, 이용일, 이용시간, 입금액, 출금액, 취소, 가맹점명, 사업자번호, 폐업 |
| **오류 보관** | `LAST_INTEGRATE_ERROR` | `LAST_INTEGRATE_ERROR` |
| **카드 전용** | — | `skip_write=True` 시 저장 생략(전처리전 조회용) |

---

## 5. After 생성 (저장)

| 항목 | 은행 | 카드 |
|------|------|------|
| **저장 경로** | `OUTPUT_FILE` = `data/bank_after.json` | `CARD_AFTER_FILE` = `data/card_after.json` |
| **입력** | input_df 없으면 `integrate_bank_transactions()` 호출 | input_df 없으면 `integrate_card_excel(skip_write=False)` 호출 |
| **데이터 없을 때** | (False, error, 0) 반환, 저장 안 함 | (False, error, 0) 반환, 저장 안 함 |
| **분류 기준** | before_text(적요·내용·송금메모·거래점) + category_table 계정과목 | 가맹점명 + category_table 계정과목 |
| **적용 함수** | apply_category_from_bank, apply_후처리_bank | apply_category_from_merchant, _apply_후처리_only_to_columns |
| **반환** | (success: bool, error: Optional[str], count: int) | (success: bool, error: Optional[str], count: int) |
| **오류 보관** | `LAST_CLASSIFY_ERROR` (실패 시 설정) | `LAST_CLASSIFY_ERROR` (실패 시 설정) |

---

## 6. 경로·상수 정리

| 용도 | 은행 | 카드 |
|------|------|------|
| **Source** | SOURCE_BANK_DIR | SOURCE_CARD_DIR |
| **Before 파일** | BANK_BEFORE_FILE | CARD_BEFORE_FILE |
| **After 파일** | OUTPUT_FILE | CARD_AFTER_FILE |
| **Category** | CATEGORY_TABLE_FILE | CATEGORY_TABLE_FILE |

---

## 7. 앱에서의 호출

| 상황 | 은행 (bank_app) | 카드 (card_app) |
|------|------------------|------------------|
| **Before 확보** | process_bank_data.integrate_bank_transactions() | process_card_data.integrate_card_excel(skip_write=True/False) |
| **After 생성** | process_bank_data.classify_and_save() | process_card_data.classify_and_save(input_df=...) |
| **재생성** | after 삭제 후 classify_and_save() | after 삭제 후 _create_card_after(input_df=df) → classify_and_save(input_df=df) |

---

## 8. CLI (main)

| 명령 | 은행 | 카드 |
|------|------|------|
| **통합만** | `python process_bank_data.py integrate` | `python process_card_data.py integrate_card` |
| **분류·저장** | `python process_bank_data.py classify` | `python process_card_data.py classify` |
| **인자 없음** | integrate 실행 | integrate_card_excel 실행 |

---

## 9. 요약

- **공통점**: source → before → after 가 모두 **process_*_data 한 모듈**에 있고, 앱은 해당 함수만 호출. 데이터 없으면 before/after 저장 안 함. 경로는 항상 data/*.json.
- **차이점**: 은행은 입출금·적요/내용/거래점 기준 분류, 카드는 가맹점명 기준 분류. 카드만 before 단계에 skip_write 옵션 있음. **classify_and_save**는 은행·카드 모두 **(success, error, count)** 반환, 실패 시 **LAST_CLASSIFY_ERROR**에 오류 메시지 설정.

---

## 10. Bank / Card / Cash : after.json 구현 방법 차이

| 항목 | 은행 (bank_after) | 카드 (card_after) | 금융정보 (cash_after) |
|------|-------------------|-------------------|------------------------|
| **입력** | `.source/Bank` 원본 → before → after | `.source/Card` 원본 → before → after | **bank_after + card_after** (원본·before 없음) |
| **구현 위치** | `process_bank_data.classify_and_save()` | `process_card_data.classify_and_save()` | **cash_app.merge_bank_card_to_cash_after()** (앱 내부) |
| **별도 process 모듈** | O (process_bank_data) | O (process_card_data) | 주 경로는 **process 없음** (병합·저장이 cash_app에 있음). process_cash_data.classify_and_save()는 cash_before.xlsx 단일 파일용 예외 경로 |
| **전처리 / 계정과목 / 후처리** | O (적요·내용·거래점→계정과목·후처리) | O (가맹점명→계정과목·후처리) | **없음**. bank/card after의 키워드·카테고리 유지, **업종분류·위험도(1~10호)만 추가** |
| **저장 경로** | `data/bank_after.json` | `data/card_after.json` | `data/cash_after.json` |
| **반환** | (success, error, count) | (success, error, count) | merge_bank_card_to_cash_after() → (success, error, count) (동일 형식) |
| **오류 보관** | LAST_CLASSIFY_ERROR | LAST_CLASSIFY_ERROR | **LAST_MERGE_ERROR** (실패 시 설정) |
| **.source 사용** | `.source/Bank` | `.source/Card` | **.source/Cash 미사용** |

- **은행·카드**: 원본(source) → 한 process_*_data 모듈에서 before 저장·after 생성까지 담당. after는 **계정과목 분류 + 후처리** 적용.
- **금융정보(cash)**: 원본이 없고, **이미 만든 bank_after + card_after를 읽어 병합**한 뒤 업종분류·위험도만 적용해 cash_after.json 저장. 주 진입점은 **cash_app**의 `merge_bank_card_to_cash_after()`이며, process_cash_data는 cash_before 단일 파일용 보조 경로만 제공. 실패 시 **LAST_MERGE_ERROR**에 오류 메시지 설정.

---

## 11. 경로·캐시 (공통 사항)

- **경로**: `data/*.json`, `.source/Bank`, `.source/Card`는 **lib.path_config**에서 중앙 정의. `get_bank_after_path()`, `get_card_after_path()`, `get_cash_after_path()`, `get_source_bank_dir()`, `get_source_card_dir()`, `get_category_table_json_path()` 등. 앱·process 모듈은 ImportError 시 각자 PROJECT_ROOT 기반 fallback.
- **캐시**: 은행·카드·금융정보 모두 **after JSON**을 메모리 캐시로 보관. **lib.after_cache.AfterCache** 사용 (mtime 기반 재읽기). 재생성·clear 시 `invalidate()` 호출.
