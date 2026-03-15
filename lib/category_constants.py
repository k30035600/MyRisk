# -*- coding: utf-8 -*-
"""
카테고리 시스템 상수 (은행/신용카드/금융정보 공통).

업무 규칙(키워드→카테고리)은 category_table.json에서 관리하고,
처리 파이프라인의 골격이 되는 시스템 상수는 이 모듈에서 단일 관리한다.
"""

# ── 기본/미매칭 카테고리 (카테고리 컬럼에 할당되는 값) ──
DEFAULT_CATEGORY = '기타거래'
UNCLASSIFIED = '미분류'
UNCLASSIFIED_DEPOSIT = '미분류입금'
UNCLASSIFIED_WITHDRAWAL = '미분류출금'

BANK_DEFAULT_DEPOSIT = '기타은행입금'
BANK_DEFAULT_WITHDRAWAL = '기타은행출금'
CARD_DEFAULT_DEPOSIT = '기타카드입금'
CARD_DEFAULT_WITHDRAWAL = '기타카드출금'
CARD_CASH_PROCESSING = '현금처리'

APPLICANT_SELF = '신청인본인'
NO_ENTRY = '(미기재)'

# ── 입출금 방향 (입출금 컬럼에 할당되는 값) ──
DIRECTION_DEPOSIT = '입금'
DIRECTION_WITHDRAWAL = '출금'
DIRECTION_CANCELLED = '취소'
CANCELLED_TRANSACTION = '취소된 거래'

# ── 분류(차수) 체계 ──
CLASS_PRE = '전처리'
CLASS_POST = '후처리'
CLASS_ACCOUNT = '계정과목'
CLASS_APPLICANT = '신청인'
CLASS_NIGHT = '심야구분'
CLASS_RISK = '위험도분류'
CLASS_INDUSTRY = '업종분류'
EXCLUDED_CLASSES = ['거래방법', '거래지점']

VALID_CLASSES = [
    CLASS_PRE, CLASS_POST, CLASS_ACCOUNT,
    '신용카드', '가상자산', '증권투자', '해외송금',
    CLASS_NIGHT, CLASS_INDUSTRY,
]

# ── 차수↔분류 매핑 (구 xlsx '차수' 컬럼 호환) ──
CHASU_TO_CLASS = {
    '1차': '입출금',
    '2차': CLASS_PRE,
    '6차': DEFAULT_CATEGORY,
}

# ── 계정과목 코드 위험도 우선순위 (5단계 캐스케이드용) ──
RISK_CODE_PRIORITY = {'M': 1, 'L': 2, 'D': 3, 'F': 4, 'P': 5, 'H': 6, 'X': 0}

# ── 위험도 분류 (1~10호) ──
RISK_CLASS_TO_VALUE = {
    '분류제외지표': 0.1,
    '심야폐업지표': 0.5,
    '자료소명지표': 1.0,
    '비정형지표': 1.5,
    '투기성지표': 2.0,
    '사기파산지표': 2.5,
    '가상자산지표': 3.0,
    '자산은닉지표': 3.5,
    '과소비지표': 4.0,
    '사행성지표': 5.0,
}

# ── 템플릿 공통 상수 (Jinja 주입용) ──
DIRECTION_CODES = [DIRECTION_DEPOSIT, DIRECTION_WITHDRAWAL]
CHASU_SORT_ORDER = {CLASS_ACCOUNT: 0, CLASS_PRE: 998, CLASS_POST: 999}

# 앱별 컬럼↔차수 매핑 (각 앱의 DataFrame 컬럼 구조 반영)
BANK_COLUMN_CHASU = {
    '입출금': '1차', '거래유형': '2차',
    '카테고리': CLASS_ACCOUNT, '기타거래': '5차',
}
CARD_COLUMN_CHASU = {
    '입출금': '1차', '거래유형': '2차', '기타거래': '5차',
}
CASH_COLUMN_CHASU = {
    '입출금': '1차', '거래유형': '2차',
    '카테고리': '3차', '기타거래': '5차',
}


def get_template_constants(app_type='bank'):
    """Jinja render_template에 **kwargs로 풀어서 넘길 상수 dict."""
    col_chasu = {
        'bank': BANK_COLUMN_CHASU,
        'card': CARD_COLUMN_CHASU,
        'cash': CASH_COLUMN_CHASU,
    }.get(app_type, BANK_COLUMN_CHASU)
    return {
        'VALID_CHASU': VALID_CLASSES,
        'CHASU_1_CODES': DIRECTION_CODES,
        'CHASU_ORDER': CHASU_SORT_ORDER,
        'COLUMN_CHASU_MAP': col_chasu,
        'CHASU_COLUMN_MAP': {v: k for k, v in col_chasu.items()},
        'DIRECTION_CANCELLED': DIRECTION_CANCELLED,
        'CANCELLED_TRANSACTION': CANCELLED_TRANSACTION,
        'CLASS_ACCOUNT': CLASS_ACCOUNT,
        'CLASS_PRE': CLASS_PRE,
        'CLASS_POST': CLASS_POST,
        'CLASS_NIGHT': CLASS_NIGHT,
        'CLASS_RISK': CLASS_RISK,
        'CLASS_INDUSTRY': CLASS_INDUSTRY,
        'CLASS_APPLICANT': CLASS_APPLICANT,
        'DEFAULT_CATEGORY': DEFAULT_CATEGORY,
        'UNCLASSIFIED': UNCLASSIFIED,
    }
