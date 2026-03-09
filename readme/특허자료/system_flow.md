# MyRisk 시스템 구성도 · 순서도

> **특허 명세서 첨부용 기술 문서**
> 주식회사 나눔과 어울림 ShareHarmony · 금융정보 분석 시스템 MyRisk
> 작성일: 2026-03-09

---

## 1. 시스템 전체 구성도

> Mermaid Live Editor에 아래 코드 블록 내용만 붙여넣기

```mermaid
graph TB
    subgraph INPUT["1 데이터 입력 계층"]
        SRC_B["source Bank\n국민 신한 하나은행\nxls xlsx"]
        SRC_C["source Card\n전 카드사\nxls xlsx"]
    end

    subgraph CORE["2 처리 엔진 계층"]
        PP_B["은행 전처리 엔진\nprocess_bank_data"]
        PP_C["카드 전처리 엔진\nprocess_card_data"]
        CAT["카테고리 분류 엔진\ncategory_table_io"]
        MERGE["금융정보 통합 엔진\ncash_app"]
        RISK["위험도 산정 엔진\nrisk_indicators"]
        OPINION["소명서 생성 엔진\ncash_app"]
    end

    subgraph DATA["3 데이터 저장 계층"]
        BB["bank_before json"]
        CB["card_before json"]
        CT["category_table json\n분류 키워드 카테고리 위험도"]
        BA["bank_after json"]
        CA["card_after json"]
        CASH["cash_after json\n은행 카드 통합"]
    end

    subgraph OUTPUT["4 출력 보고서 계층"]
        RPT_BANK["은행거래 분석 보고서"]
        RPT_CARD["신용카드 분석 보고서"]
        RPT_CASH["금융정보 종합분석 보고서"]
        RPT_RISK["위험거래 분석 보고서"]
        RPT_OPIN["종합의견서 소명서 초안"]
    end

    SRC_B --> PP_B --> BB
    SRC_C --> PP_C --> CB
    CT --> PP_B
    CT --> PP_C
    BB --> CAT --> BA
    CB --> CAT --> CA
    BA --> MERGE
    CA --> MERGE
    CT --> MERGE
    MERGE --> CASH
    CASH --> RISK --> OPINION

    BA --> RPT_BANK
    CA --> RPT_CARD
    CASH --> RPT_CASH
    RISK --> RPT_RISK
    OPINION --> RPT_OPIN
```

---

## 2. 데이터 처리 순서도 - 전체 파이프라인

```mermaid
flowchart TD
    START(["시작"]) --> CHK_SRC{"source 폴더에\nxlsx 파일 존재"}

    CHK_SRC -- 예 --> LOAD_B["은행 xlsx 로드\n국민 신한 하나은행별 파서"]
    CHK_SRC -- 예 --> LOAD_C["카드 xlsx 로드\n헤더 자동감지 표준컬럼 매핑"]
    CHK_SRC -- 아니오 --> CHK_BF{"before json\n존재"}

    LOAD_B --> CLEAN_B["데이터 정제\n금액정리 잔액제거 정렬"]
    LOAD_C --> CLEAN_C["데이터 정제\n가맹점명 보정 입출금 변환"]

    CLEAN_B --> PRE_B["S1 전처리 적용\ncategory_table 전처리 규칙"]
    CLEAN_C --> PRE_C["S1 전처리 적용\ncategory_table 전처리 규칙"]

    PRE_B --> SAVE_BB["bank_before json 저장"]
    PRE_C --> SAVE_CB["card_before json 저장"]

    SAVE_BB --> CLASS_B["S2 계정과목 분류\n키워드 매칭 긴 키워드 우선"]
    SAVE_CB --> CLASS_C["S2 계정과목 분류\n가맹점명 기반 매칭"]

    CHK_BF -- 예 --> CLASS_B
    CHK_BF -- 예 --> CLASS_C

    CLASS_B --> POST_B["S3 후처리 적용\ncategory_table 후처리 규칙"]
    CLASS_C --> POST_C["S3 후처리 적용\ncategory_table 후처리 규칙"]

    POST_B --> SAVE_BA["bank_after json 저장"]
    POST_C --> SAVE_CA["card_after json 저장"]

    SAVE_BA --> MERGE_CASH["은행 카드 병합\n통합 DataFrame 생성"]
    SAVE_CA --> MERGE_CASH

    MERGE_CASH --> RISK_CLS["업종분류 코드 매칭\n1호 4호 위험도"]
    RISK_CLS --> RISK_IND["위험도 지표 적용\n1호 10호 순차 판정"]
    RISK_IND --> SAVE_CASH["cash_after json 저장"]

    SAVE_CASH --> REPORT["분석 보고서 생성"]
    SAVE_CASH --> RISK_RPT["위험거래 분석"]
    RISK_RPT --> OPINION_GEN["소명서 초안 자동 생성"]

    REPORT --> END(["완료"])
    OPINION_GEN --> END
```

---

## 3. 카테고리 3단계 분류 상세도

```mermaid
flowchart LR
    subgraph STAGE1["1단계 전처리"]
        direction TB
        S1_IN["원본 거래 데이터"] --> S1_LOAD["category_table에서\n분류 전처리 행 로드"]
        S1_LOAD --> S1_MATCH["키워드를 카테고리로 치환\n긴 키워드 우선 적용"]
        S1_MATCH --> S1_OUT["정제된 적요 가맹점명"]
    end

    subgraph STAGE2["2단계 계정과목 분류"]
        direction TB
        S2_IN["정제된 거래 데이터"] --> S2_TEXT["검색 문자열 생성\n적요 내용 송금메모 거래점"]
        S2_TEXT --> S2_MATCH["분류 계정과목 키워드 매칭\n가장 긴 키워드 우선"]
        S2_MATCH --> S2_CHK{"매칭\n성공"}
        S2_CHK -- 예 --> S2_CAT["해당 카테고리 부여"]
        S2_CHK -- 아니오 --> S2_DEF["기타거래 부여"]
    end

    subgraph STAGE3["3단계 후처리"]
        direction TB
        S3_IN["분류 완료 데이터"] --> S3_LOAD["category_table에서\n분류 후처리 행 로드"]
        S3_LOAD --> S3_MATCH["키워드를 카테고리로 재치환\n최종 보정"]
        S3_MATCH --> S3_OUT["after json 저장"]
    end

    STAGE1 --> STAGE2 --> STAGE3
```

### 카테고리 테이블 구조

| 컬럼 | 설명 | 예시 |
|------|------|------|
| **분류** | 처리 단계 구분 | `전처리`, `계정과목`, `후처리`, `위험도분류`, `심야구분` |
| **키워드** | 매칭 대상 문자열 | `카카오페이`, `스타벅스`, `국민연금` |
| **카테고리** | 분류 결과 | `간편결제`, `식음료`, `사회보험` |
| **위험도** | 위험도 등급 5호~10호 | `5호`, `6호`, `7호` |
| **업종코드** | 최소 금액 기준 등 | `50000` 원 |

---

## 4. 위험도 산정 순서도 - 1호~10호 지표

```mermaid
flowchart TD
    IN["cash_after 거래 1건"] --> BASE["1호 분류제외지표\n위험도 0.1\n기본값"]

    BASE --> CHK2{"2호 조건 충족\n폐업 Y OR\n심야 AND 출금 GTE 기준액"}
    CHK2 -- 예 --> SET2["2호 심야폐업지표\n위험도 0.5"]
    CHK2 -- 아니오 --> CHK3

    SET2 --> CHK3{"3호 조건 충족\n출금액 GTE 기준액"}
    CHK3 -- 예 --> SET3["3호 자료소명지표\n위험도 1.0"]
    CHK3 -- 아니오 --> CHK4

    SET3 --> CHK4{"4호 조건 충족\n입금 0 AND 출금 GTE 기준액\nAND 동일키워드 3회 이상"}
    CHK4 -- 예 --> SET4["4호 비정형지표\n위험도 1.5"]
    CHK4 -- 아니오 --> CHK5

    SET4 --> CHK5{"5호 to 10호 조건 충족\n위험도분류 키워드 매칭\nAND 출금 GTE 기준액"}

    CHK5 -- 5호 투기성 --> SET5["위험도 2.0"]
    CHK5 -- 6호 사기파산 --> SET6["위험도 2.5"]
    CHK5 -- 7호 가상자산 --> SET7["위험도 3.0"]
    CHK5 -- 8호 자산은닉 --> SET8["위험도 3.5"]
    CHK5 -- 9호 과소비 --> SET9["위험도 4.0"]
    CHK5 -- 10호 사행성 --> SET10["위험도 5.0"]
    CHK5 -- 미해당 --> KEEP["이전 단계 위험도 유지"]

    SET5 --> OUT["최종 위험도 확정"]
    SET6 --> OUT
    SET7 --> OUT
    SET8 --> OUT
    SET9 --> OUT
    SET10 --> OUT
    KEEP --> OUT
```

### 위험도 지표 상세 정의

| 호수 | 지표명 | 위험도 값 | 판정 조건 | 법적 근거 |
|------|--------|----------|----------|----------|
| 1호 | 분류제외지표 | 0.1 | 2~10호 미해당 기본값 | - |
| 2호 | 심야폐업지표 | 0.5 | 폐업 업소 OR 심야시간대 AND 출금 GTE 기준 | 채무자회생법 제564조 |
| 3호 | 자료소명지표 | 1.0 | 출금액 GTE 기준액 | 채무자회생법 제564조 |
| 4호 | 비정형지표 | 1.5 | 입금 0원 출금 GTE 기준 동일키워드 3회 이상 반복 | 채무자회생법 제564조 |
| 5호 | 투기성지표 | 2.0 | 위험도분류 투기 키워드 출금 GTE 기준 | 동법 제564조 1항 5호 |
| 6호 | 사기파산지표 | 2.5 | 위험도분류 사기 키워드 출금 GTE 기준 | 동법 제564조 1항 2호 |
| 7호 | 가상자산지표 | 3.0 | 위험도분류 가상자산 키워드 출금 GTE 기준 | 동법 제564조 1항 5호 |
| 8호 | 자산은닉지표 | 3.5 | 위험도분류 은닉 키워드 출금 GTE 기준 | 동법 제564조 1항 1호 |
| 9호 | 과소비지표 | 4.0 | 위험도분류 과소비 키워드 출금 GTE 기준 | 동법 제564조 1항 5호 |
| 10호 | 사행성지표 | 5.0 | 위험도분류 사행성 키워드 출금 GTE 기준 | 동법 제564조 1항 5호 |

> **심야시간대**: category_table 심야구분 행에서 정의 기본 22시~06시
> **기준액**: category_table 위험도분류 행의 업종코드 값 단위 원
> **GTE**: 이상 Greater Than or Equal

---

## 5. 소명서 자동 생성 순서도

```mermaid
flowchart TD
    CASH["cash_after json\n위험도 적용 완료"] --> CALC["위험거래 집계\ncalculate_risk_report"]

    CALC --> FILTER{"위험도\nGTE 0.5"}
    FILTER -- 예 --> GROUP["지표별 그룹핑\n건수 금액 합산"]
    FILTER -- 아니오 --> SKIP["분석 대상 제외"]

    GROUP --> TOP5["상위 5개 항목 선정\n금액 기준 정렬"]

    TOP5 --> GEN_SUGGEST["소명 전략 생성\nSUGGESTION_TEMPLATES"]
    TOP5 --> GEN_LEGAL["법적 근거 매칭\nLEGAL_REFERENCES"]
    TOP5 --> GEN_DRAFT["소명서 초안 생성\ngenerate_draft_explanation"]

    GEN_SUGGEST --> COMPOSE["보고서 구성"]
    GEN_LEGAL --> COMPOSE
    GEN_DRAFT --> COMPOSE

    COMPOSE --> RPT_RISK["위험거래 분석 보고서"]
    COMPOSE --> RPT_OPIN["종합의견서"]
    COMPOSE --> RPT_PRINT["인쇄용 보고서"]
```

### 소명서 초안 생성 방식

```
입력: 지표명, 거래 건수, 총 금액

generate_draft_explanation("가상자산지표", 5, "3,500,000원")

출력:
"위 가상자산 관련 거래 5건(3,500,000원)은 투자 목적이었으며,
 현재는 모든 가상자산 계정을 해지하였고, 향후 가상자산 거래를
 하지 않겠습니다."

※ 지표별 10종의 법적 소명 템플릿 내장
```

---

## 6. 모듈 구성도

```mermaid
graph LR
    subgraph MAIN["메인 애플리케이션"]
        FLASK["Flask 웹 서버"]
        ROUTER["라우트 등록 프록시"]
    end

    subgraph BANK["MyBank 모듈"]
        B_APP["bank_app\n웹 인터페이스"]
        B_PROC["process_bank_data\n전처리 분류 저장"]
    end

    subgraph CARD["MyCard 모듈"]
        C_APP["card_app\n웹 인터페이스"]
        C_PROC["process_card_data\n전처리 분류 저장"]
    end

    subgraph CASHMOD["MyCash 모듈"]
        CASH_APP["cash_app\n병합 위험도 보고서"]
        RISK_IND["risk_indicators\n1호 to 10호 위험도 산정"]
    end

    subgraph LIB["공통 라이브러리"]
        PATH["path_config\n경로 관리"]
        DJIO["data_json_io\nJSON 안전 읽기 쓰기"]
        CTIO["category_table_io\n카테고리 테이블 관리"]
    end

    FLASK --> ROUTER
    ROUTER --> B_APP --> B_PROC
    ROUTER --> C_APP --> C_PROC
    ROUTER --> CASH_APP --> RISK_IND

    B_PROC --> CTIO
    C_PROC --> CTIO
    CASH_APP --> CTIO
    B_PROC --> DJIO
    C_PROC --> DJIO
    CASH_APP --> DJIO
    CTIO --> PATH
    DJIO --> PATH
```

---

## 7. 발명의 핵심 청구항 구성 참고

```
[청구항 1]

금융기관 발행 거래 내역 데이터를 입력받는 수신 단계;

사전 정의된 카테고리 테이블을 이용하여
전처리, 계정과목 분류, 후처리의 3단계로
상기 거래 내역을 자동 분류하는 분류 단계;

이기종 금융 데이터(은행 거래 + 신용카드 거래)를
단일 통합 데이터로 병합하는 통합 단계;

상기 통합 데이터의 각 거래에 대해
소정의 위험도 지표(1호~10호)를 순차 적용하여
위험도 점수를 산정하는 위험도 산정 단계;

산정된 위험도에 기초하여 법적 소명 문안을
자동 생성하는 소명서 생성 단계;

를 포함하는, 법원 회생/파산/면책 절차를 위한
금융 거래 위험도 분석 및 소명서 자동 생성 방법.


[청구항 2]

제1항에 있어서,
상기 위험도 산정 단계는
기본값(1호, 0.1)을 부여한 후
2호(심야폐업)~10호(사행성)를 순차 판정하되,
상위 호수 조건 충족 시 하위 호수를 덮어쓰는
단계적 위험도 상향 방식인 것을 특징으로 하는 방법.


[청구항 3]

제1항에 있어서,
상기 3단계 분류에서
전처리는 원본 데이터의 비정형 텍스트를 정규화하고,
계정과목 분류는 키워드 길이 역순으로 매칭하여
최장 일치(Longest Match) 방식으로 분류하며,
후처리는 분류 결과를 법적 용어로 재정규화하는 것을
특징으로 하는 방법.
```

---

## 8. 용어 정의

| 용어 | 정의 |
|------|------|
| **전처리** | 금융기관별로 상이한 원본 데이터의 적요 가맹점명을 표준화하는 과정 |
| **계정과목 분류** | 표준화된 거래 텍스트를 사전 정의된 키워드와 대조하여 회계 카테고리를 부여하는 과정 |
| **후처리** | 분류 완료된 데이터에 대해 법적 절차에 적합한 용어로 최종 보정하는 과정 |
| **위험도 지표** | 채무자회생법 제564조에 근거한 면책불허가 사유 해당 여부를 수치화한 등급 0.1~5.0 |
| **소명서 초안** | 위험 거래에 대해 채무자가 법원에 제출할 해명 문안의 자동 생성본 |
| **카테고리 테이블** | 분류 키워드 카테고리 위험도를 정의한 규칙 데이터베이스 |
| **최장 일치 방식** | 복수의 키워드가 동시에 매칭될 때 가장 긴 키워드를 우선 적용하는 알고리즘 |
| **GTE** | 이상 Greater Than or Equal |

---

> **본 문서의 Mermaid 다이어그램은 특허 명세서 첨부 시 이미지로 변환하여 사용합니다.**
> 각 다이어그램을 개별적으로 Mermaid Live Editor에 붙여넣어 이미지로 변환하세요.
> 변환 도구: https://mermaid.live
