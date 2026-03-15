# -*- coding: utf-8 -*-
"""
위험도 지표 1~10호 (risk_indicators.py).

cash_after 생성 후 위험도·위험도분류·위험도키워드 매칭을 적용한다.
1호 기본값부터 10호까지 순차 적용하며, 조건 만족 시 덮어쓴다.
"""
from __future__ import annotations

import json
import os
from typing import Dict, List, Optional, Tuple

import pandas as pd

import sys as _sys
_PROJECT_ROOT_RI = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
if _PROJECT_ROOT_RI not in _sys.path:
    _sys.path.insert(0, _PROJECT_ROOT_RI)
from lib.category_constants import CLASS_NIGHT, CLASS_RISK

DEFAULT_RISK = 0.1  # 1호 기본 위험도
CLASS_1호 = '분류제외지표'
CLASS_2호 = '심야폐업지표'

# 5~10호 위험도분류명 (category_table.json 분류 "위험도분류" 행의 키워드로 매칭, 카테고리/매칭키워드/위험도만 저장)
CLASS_5호 = '투기성지표'
CLASS_6호 = '사기파산지표'
CLASS_7호 = '가상자산지표'
CLASS_8호 = '자산은닉지표'
CLASS_9호 = '과소비지표'
CLASS_10호 = '사행성지표'
RISK_CLASSES_5_10 = (CLASS_5호, CLASS_6호, CLASS_7호, CLASS_8호, CLASS_9호, CLASS_10호)


def _num(val, default: float = 0.0) -> float:
    if val is None or val == '' or (isinstance(val, float) and pd.isna(val)):
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _str(val) -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ''
    return str(val).strip()


def _search_text(row, cols: List[str]) -> str:
    parts = []
    for c in cols:
        if c not in row.index:
            continue
        v = row[c]
        if v is None or (isinstance(v, float) and pd.isna(v)):
            continue
        parts.append(_str(v))
    return ' '.join(parts)


def _search_text_dedup(row, cols: List[str]) -> str:
    raw = _search_text(row, cols)
    if not raw:
        return ''
    tokens = raw.split()
    seen = set()
    unique = []
    for t in tokens:
        if t not in seen:
            seen.add(t)
            unique.append(t)
    return ' '.join(unique)


def _keyword_match(text: str, keywords: List[str]) -> bool:
    if not text:
        return False
    t = text.lower()
    for kw in keywords:
        if kw.lower() in t:
            return True
    return False


def _matched_keyword(text: str, keywords: List[str]) -> str:
    if not text:
        return ''
    t = text.lower()
    for kw in keywords:
        if kw.lower() in t:
            return kw
    return ''


def _parse_time_to_minutes(t: str) -> Optional[int]:
    """거래시간 문자열을 0~1439(자정 기준 분)로 변환. None이면 인식 불가."""
    if t is None or (isinstance(t, float) and pd.isna(t)):
        return None
    s = _str(t).replace(' ', '')
    if not s:
        return None
    # HH:MM:SS or HHMMSS or HHMM
    parts = s.replace(':', '').replace('.', '')[:6]
    if len(parts) < 4:
        return None
    try:
        h = int(parts[:2]) if len(parts) >= 2 else 0
        m = int(parts[2:4]) if len(parts) >= 4 else 0
        if h < 0 or h > 23 or m < 0 or m > 59:
            return None
        return h * 60 + m
    except ValueError:
        return None


def _hhmm_to_minutes(x: str) -> Optional[int]:
    """'HH:MM' 또는 'HHMM' 형태 문자열을 분(0~1439)으로 변환. 형식 오류면 None."""
    x = x.replace(':', '').replace('.', '')[:4]
    if len(x) < 4:
        return None
    try:
        h, m = int(x[:2]), int(x[2:4])
        if 0 <= h <= 23 and 0 <= m <= 59:
            return h * 60 + m
    except ValueError:
        pass
    return None


def _load_category_data(category_table_path: Optional[str]) -> Optional[list]:
    """category_table.json을 한 번만 읽어 list로 반환. 실패 시 None."""
    if not category_table_path or not os.path.isfile(category_table_path):
        return None
    try:
        with open(category_table_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError, TypeError):
        return None
    return data if isinstance(data, list) else None


def _load_simya_range(category_table_path: Optional[str] = None, *, data: Optional[list] = None) -> Optional[Tuple[int, int]]:
    """category_table에서 심야구분 키워드(예: 22:00:00/06:00:00) 로드. (시작분, 종료분) 0~1439."""
    if data is None:
        data = _load_category_data(category_table_path)
    if not data:
        return None
    for item in data:
        if not isinstance(item, dict):
            continue
        if _str(item.get('분류')) != CLASS_NIGHT:
            continue
        kw = _str(item.get('키워드', ''))
        if '/' not in kw:
            continue
        parts = kw.split('/')
        if len(parts) != 2:
            continue
        start_s = parts[0].strip()
        end_s = parts[1].strip()
        start_m = _hhmm_to_minutes(start_s)
        end_m = _hhmm_to_minutes(end_s)
        if start_m is None or end_m is None:
            continue
        return (start_m, end_m)
    return None


def _is_simya(거래시간_str, simya_range: Optional[Tuple[int, int]]) -> bool:
    """거래시간이 심야 구간에 해당하면 True. 00:00:00은 제외(심야로 보지 않음)."""
    if simya_range is None:
        return False
    t = _parse_time_to_minutes(거래시간_str)
    if t is None:
        return False
    if t == 0:
        return False  # 00:00:00은 심야구분에서 제외
    start_m, end_m = simya_range
    if start_m <= end_m:
        return start_m <= t < end_m
    # 넘침 (예: 22:00~06:00 → start_m=1320, end_m=360)
    return t >= start_m or t < end_m


def compute_simya_series(거래시간_series: pd.Series, category_table_path: Optional[str]) -> pd.Series:
    """거래시간 시리즈에 대해 심야 여부를 '심야' 또는 '' 로 반환. cash_after 표시용 파생 컬럼."""
    if 거래시간_series is None or 거래시간_series.empty:
        return pd.Series(dtype=object)
    simya_range = _load_simya_range(category_table_path)
    if simya_range is None:
        return pd.Series([''] * len(거래시간_series), index=거래시간_series.index, dtype=object)
    return 거래시간_series.apply(lambda t: '심야' if _is_simya(t, simya_range) else '')


def _parse_min_out(위험지표) -> Optional[float]:
    """위험지표를 숫자로 파싱하여 최소 출금액(원) 반환. 실패 시 None."""
    if 위험지표 is None or (isinstance(위험지표, float) and pd.isna(위험지표)):
        return None
    s = str(위험지표).strip()
    if not s:
        return None
    try:
        v = float(s)
        return v if v >= 0 else None
    except (TypeError, ValueError):
        return None


def _load_위험도분류_keywords(category_table_path: Optional[str] = None, *, data: Optional[list] = None) -> Tuple[Dict[str, dict], Dict[str, float]]:
    """category_table.json에서 분류='위험도분류'인 행만 추려,
    - 카테고리(5~10호)별 { 'keywords': [...], '위험도': float, 'min_out': float } 반환,
    - 전체 호별 최소 출금액(원) dict: { 카테고리: min_out }.
    매칭 시 출금액 >= 해당 호의 min_out(위험지표)일 때만 적용. 위험지표 없으면 0(금액 조건 없음)."""
    result: Dict[str, dict] = {cls: {'keywords': [], '위험도': 0.0, 'min_out': 0.0} for cls in RISK_CLASSES_5_10}
    default_risk = {CLASS_5호: 2.0, CLASS_6호: 2.5, CLASS_7호: 3.0, CLASS_8호: 3.5, CLASS_9호: 4.0, CLASS_10호: 5.0}
    for cls in RISK_CLASSES_5_10:
        result[cls]['위험도'] = default_risk.get(cls, 0.1)
    min_out_by_cat: Dict[str, float] = {}
    if data is None:
        data = _load_category_data(category_table_path)
    if not data:
        return result, min_out_by_cat
    for item in data:
        if not isinstance(item, dict):
            continue
        if _str(item.get('분류')) != CLASS_RISK:
            continue
        cat = _str(item.get('카테고리', ''))
        kw_raw = item.get('키워드', '')
        if kw_raw is None or (isinstance(kw_raw, float) and pd.isna(kw_raw)):
            kw_raw = ''
        kw_str = str(kw_raw).strip()
        위험도_val = item.get('위험도')
        try:
            r = float(위험도_val) if 위험도_val is not None and str(위험도_val).strip() != '' else None
        except (TypeError, ValueError):
            r = None
        parsed_min = _parse_min_out(item.get('위험지표'))
        if parsed_min is not None:
            min_out_by_cat[cat] = min(min_out_by_cat.get(cat, 1e12), parsed_min)
        if cat not in result:
            continue
        if r is not None:
            result[cat]['위험도'] = r
        if parsed_min is not None:
            cur = result[cat]['min_out']
            result[cat]['min_out'] = parsed_min if cur == 0 else min(cur, parsed_min)
        if not kw_str:
            continue
        for sep in (',', '/', '\n', '\r'):
            kw_str = kw_str.replace(sep, ' ')
        raw = [t.strip() for t in kw_str.split() if t.strip()]
        tokens = [t for t in raw if not (len(t) >= 4 and t.startswith('분류') and t.endswith('호'))]
        if tokens:
            result[cat]['keywords'].extend(tokens)
    for cat in result:
        result[cat]['keywords'] = list(dict.fromkeys(result[cat]['keywords']))
        result[cat]['min_out'] = min_out_by_cat.get(cat, 0.0)
    return result, min_out_by_cat


def apply_risk_indicators(df: pd.DataFrame, category_table_path: Optional[str] = None) -> None:
    """
    cash_after DataFrame에 대해 1~10호 위험도 지표 적용. in-place 수정.
    1호를 기본값으로 두고, 2호~10호를 순차 적용하며 조건 만족 시 덮어씀.
    """
    if df is None or df.empty:
        return
    if '입금액' not in df.columns or '출금액' not in df.columns:
        return

    분류_col = '위험도분류' if '위험도분류' in df.columns else ('업종분류' if '업종분류' in df.columns else None)
    has_업종 = 분류_col is not None
    if has_업종 and 분류_col != CLASS_RISK:
        df['위험도분류'] = df[분류_col].fillna('')
    elif not has_업종:
        df['위험도분류'] = ''
        분류_col = '위험도분류'
    has_위험도 = '위험도' in df.columns
    if not has_위험도:
        df['위험도'] = DEFAULT_RISK
    # 1호를 기본값으로 설정(이후 2~10호 순차 적용 시 덮어씀)
    df['위험도'] = DEFAULT_RISK
    df['위험도분류'] = CLASS_1호
    if '위험도키워드' not in df.columns:
        if '업종키워드' in df.columns:
            df['위험도키워드'] = df['업종키워드'].fillna('').astype(str).str.strip()
        elif '위험지표' in df.columns:
            df['위험도키워드'] = df['위험지표'].fillna('').astype(str).str.strip()
        else:
            df['위험도키워드'] = ''

    if '키워드' not in df.columns:
        df['키워드'] = ''
    if '카테고리' not in df.columns:
        df['카테고리'] = ''
    kw_series = df['키워드'].fillna('').astype(str).str.strip()

    sort_1 = [c for c in ['키워드', '거래일'] if c in df.columns]
    if sort_1:
        df.sort_values(by=sort_1, ascending=True, inplace=True, na_position='last')

    # ---------- 2호: 심야폐업지표 0.5 — 폐업은 금액 무관, 심야구분은 출금액 >= 위험도분류 해당 호 위험지표(숫자) ----------
    # 심야구분: category_table 분류='심야구분' 행의 키워드로 시간 구간 로드. 최소 출금액 = 분류 '위험도분류' 해당 호 위험지표(숫자), 없으면 0.
    # 폐업: cash_after의 '폐업' 컬럼이 '폐업'인 행. 금액 무관. 2호 해당 행은 3~10호 조건을 보지 않음.
    if '거래시간' not in df.columns:
        df['거래시간'] = ''
    if '폐업' not in df.columns:
        df['폐업'] = ''
    cat_data = _load_category_data(category_table_path)
    simya_range = _load_simya_range(data=cat_data)
    keywords_5_10, min_out_by_cat = _load_위험도분류_keywords(data=cat_data)
    simya_min_out = min_out_by_cat.get('심야폐업지표', 0)

    # ---------- 2호: 벡터화 — 폐업 마스크 OR 심야+출금 마스크 ----------
    mask_폐업 = df['폐업'].apply(lambda v: _str(v).strip() == '폐업')
    mask_simya = df['거래시간'].apply(lambda v: _is_simya(v, simya_range))
    out_series = df['출금액'].apply(_num) if '출금액' in df.columns else pd.Series(0.0, index=df.index)
    mask_simya_ok = mask_simya & (out_series >= simya_min_out)
    mask_2호 = mask_폐업 | mask_simya_ok

    # 위험도키워드: 폐업만, 심야만, 폐업+심야 세 경우 구분
    df.loc[mask_폐업 & ~mask_simya_ok, '위험도키워드'] = '폐업'
    df.loc[~mask_폐업 & mask_simya_ok, '위험도키워드'] = '심야'
    df.loc[mask_폐업 & mask_simya_ok, '위험도키워드'] = '폐업 심야'
    if has_업종:
        df.loc[mask_2호, '위험도분류'] = CLASS_2호
    if has_위험도:
        df.loc[mask_2호, '위험도'] = 0.5
    df['_2호적용'] = mask_2호

    # ---------- 3호: 자료소명지표 1.0 (2호 미적용 행만) ----------
    min_out_3 = min_out_by_cat.get('자료소명지표', 0)
    mask_3호 = ~mask_2호 & (df['출금액'].apply(_num) >= min_out_3)
    if mask_3호.any():
        기타거래_col = df['기타거래'] if '기타거래' in df.columns else pd.Series('', index=df.index)
        kw_3 = df['키워드'].apply(_str).where(df['키워드'].apply(_str) != '', 기타거래_col.apply(_str))
        df.loc[mask_3호, '위험도키워드'] = kw_3[mask_3호]
        if has_업종:
            df.loc[mask_3호, '위험도분류'] = '자료소명지표'
        if has_위험도:
            df.loc[mask_3호, '위험도'] = 1.0

    # ---------- 4호: 비정형지표 1.5 (2호 미적용 행만) ----------
    min_out_4 = min_out_by_cat.get('비정형지표', 0)
    out_only_1m = (df['출금액'].apply(_num) >= min_out_4) & (df['입금액'].apply(_num) <= 0)
    df['_kw'] = kw_series
    count_per_kw = df.loc[out_only_1m].groupby('_kw').size()
    kw_3_or_more = set(count_per_kw[count_per_kw >= 3].index)
    mask_4호 = ~mask_2호 & df['_kw'].isin(kw_3_or_more) & out_only_1m
    df['_4호대상'] = mask_4호
    if mask_4호.any():
        df.loc[mask_4호, '위험도키워드'] = '{:,.0f}'.format(min_out_4) + ' 이상'
        if has_업종:
            df.loc[mask_4호, '위험도분류'] = '비정형지표'
        if has_위험도:
            df.loc[mask_4호, '위험도'] = 1.5

    sort_2 = [c for c in ['카테고리', '키워드', '거래일'] if c in df.columns]
    if sort_2:
        df.sort_values(by=sort_2, ascending=True, inplace=True, na_position='last')

    SEARCH_COLS = ['카테고리', '키워드', '기타거래']

    # 5~10호: 2호 미적용 행만 순회. 키워드 매칭 의존성으로 행별 처리 유지.
    CLASS_CONFIG = [(CLASS_5호, 0), (CLASS_6호, 0), (CLASS_7호, 0), (CLASS_8호, 0), (CLASS_9호, 0), (CLASS_10호, 0)]
    idx_5_10 = df.index[~mask_2호]
    for i in idx_5_10:
        row = df.loc[i]
        inp, out = _num(row.get('입금액')), _num(row.get('출금액'))
        text = _search_text_dedup(row, SEARCH_COLS)
        matched = False
        for class_name, max_inp in CLASS_CONFIG:
            info = keywords_5_10.get(class_name, {'keywords': [], '위험도': 0.1, 'min_out': 0})
            min_out = info.get('min_out', 0)
            if out < min_out or inp > max_inp:
                continue
            kw_list = info.get('keywords', [])
            risk_val = info.get('위험도', 0.1)
            if class_name == CLASS_7호 and '가상자산' in _str(row.get('카테고리', '')):
                df.at[i, '위험도키워드'] = '가상자산'
                if has_업종:
                    df.at[i, '위험도분류'] = class_name
                if has_위험도:
                    df.at[i, '위험도'] = risk_val
                matched = True
                break
            if kw_list and _keyword_match(text, kw_list):
                df.at[i, '위험도키워드'] = _matched_keyword(text, kw_list)
                if has_업종:
                    df.at[i, '위험도분류'] = class_name
                if has_위험도:
                    df.at[i, '위험도'] = risk_val
                matched = True
                break

    df.drop(columns=['_kw', '_4호대상', '_2호적용'], errors='ignore', inplace=True)

    if has_위험도:
        df['위험도'] = df['위험도'].apply(lambda v: max(DEFAULT_RISK, _num(v, DEFAULT_RISK)))


def get_risk_indicators_document() -> str:
    """위험도 지표 1~10호 요약 문서용 텍스트."""
    lines = [
        "1호. 분류제외지표: 금액제한 없음, 2~10호에 해당하지 않은 거래, 위험도 0.1",
        "2호. 심야폐업지표: 폐업은 금액 무관, 심야구분은 출금액 10만원 이상일 때만, 위험도키워드 '폐업'/'심야', 위험도 0.5",
        "3호. 자료소명지표: 출금 500만원 이상, 해당 행 키워드를 위험도키워드로 저장, 위험도 1.0",
        "4호. 비정형지표: 출금만 최소출금액(위험지표) 이상, 동일 키워드 3회 이상, 위험도키워드=최소출금액+이상, 위험도 1.5",
        "5~10호. 키워드 매칭: category_table 분류 '위험도분류' 행의 키워드로만 매칭. 출금액은 각 호 해당 위험지표(숫자) 이상일 때만 적용. 매칭 시 위험도분류/위험도키워드/위험도만 저장.",
    ]
    return "\n".join(lines)
