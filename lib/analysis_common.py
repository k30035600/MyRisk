# -*- coding: utf-8 -*-
"""bank_app / card_app 분석 API 공통 로직.

각 compute_* 함수는 Flask에 의존하지 않으며, DataFrame과 파라미터를 받아 dict/list를 반환합니다.
라우트 함수에서 request.args 파싱 → compute_* 호출 → jsonify 반환 순서로 사용합니다.
"""
from __future__ import annotations

import pandas as pd
from typing import Any, Callable, Dict, List, Optional, Tuple


def _safe_int(v) -> int:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return 0
    return int(v)


def _safe_label(v, fallback='(빈값)') -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return fallback
    s = str(v).strip()
    return s if s else fallback


def apply_bank_filter(df: pd.DataFrame, bank_col: str, bank_filter: str) -> pd.DataFrame:
    if not bank_filter or bank_col not in df.columns:
        return df
    return df[df[bank_col].astype(str).str.strip() == bank_filter]


def apply_category_filters(
    df: pd.DataFrame,
    입출금_filter: str = '',
    거래유형_filter: str = '',
    카테고리_filter: str = '',
    category_type: str = '',
    category_value: str = '',
) -> pd.DataFrame:
    if '카테고리분류' in df.columns and '입출금' not in df.columns:
        df = df.copy()
        df['입출금'] = df['카테고리분류']
    if category_type and category_value and category_type in df.columns:
        df = df[df[category_type] == category_value]
    if 입출금_filter and '입출금' in df.columns:
        df = df[df['입출금'] == 입출금_filter]
    if 거래유형_filter and '거래유형' in df.columns:
        df = df[df['거래유형'] == 거래유형_filter]
    if 카테고리_filter and '카테고리' in df.columns:
        df = df[df['카테고리'] == 카테고리_filter]
    return df


# ────────────────────────────────────────
# 1. summary
# ────────────────────────────────────────
def compute_summary(df: pd.DataFrame) -> dict:
    if '입금액' not in df.columns:
        df['입금액'] = 0
    if '출금액' not in df.columns:
        df['출금액'] = 0
    total_deposit = df['입금액'].sum()
    total_withdraw = df['출금액'].sum()
    deposit_count = int((pd.to_numeric(df['입금액'], errors='coerce').fillna(0) > 0).sum())
    withdraw_count = int((pd.to_numeric(df['출금액'], errors='coerce').fillna(0) > 0).sum())
    return {
        'total_deposit': _safe_int(total_deposit),
        'total_withdraw': _safe_int(total_withdraw),
        'net_balance': _safe_int(total_deposit - total_withdraw),
        'total_count': len(df),
        'deposit_count': deposit_count,
        'withdraw_count': withdraw_count,
    }


# ────────────────────────────────────────
# 2. by-category
# ────────────────────────────────────────
def compute_by_category(
    df: pd.DataFrame,
    bank_col: str = '은행명',
    include_category_filter: bool = True,
) -> List[dict]:
    group_col = '카테고리' if '카테고리' in df.columns else '적요'
    if group_col not in df.columns:
        df = df.copy()
        df[group_col] = '(빈값)'
    df = df.copy()
    df[group_col] = df[group_col].fillna('').astype(str).str.strip().replace('', '(빈값)')

    agg_dict: Dict[str, str] = {'입금액': 'sum', '출금액': 'sum'}
    for col in ['입출금', '거래유형', '카테고리', bank_col, '내용', '거래점']:
        if col in df.columns and col != group_col:
            agg_dict[col] = 'first'
    category_stats = df.groupby(group_col).agg(agg_dict).reset_index()
    counts = df.groupby(group_col).size().reset_index(name='count')
    category_stats = category_stats.merge(counts, on=group_col)
    category_stats['차액'] = category_stats['입금액'] - category_stats['출금액']
    category_stats = category_stats.sort_values(group_col, ascending=True)

    data = []
    for _, row in category_stats.iterrows():
        item = {
            'category': _safe_label(row[group_col]),
            'count': _safe_int(row.get('count')),
            'deposit': _safe_int(row.get('입금액')),
            'withdraw': _safe_int(row.get('출금액')),
            'balance': _safe_int(row.get('차액')),
        }
        item['classification'] = _safe_label(row.get('입출금'))
        item['transactionType'] = _safe_label(row.get('거래유형'))
        if include_category_filter and '카테고리' in row.index and '카테고리' != group_col:
            item['transactionTarget'] = _safe_label(row.get('카테고리'))
        else:
            item['transactionTarget'] = '(빈값)'
        item['bank'] = _safe_label(row.get(bank_col))
        item['content'] = _safe_label(row.get('내용'), fallback='')
        item['transactionPoint'] = _safe_label(row.get('거래점'), fallback='')
        data.append(item)
    return data


# ────────────────────────────────────────
# 3. by-category-group
# ────────────────────────────────────────
def compute_by_category_group(
    df: pd.DataFrame,
    bank_col: str = '은행명',
    include_category_groupby: bool = True,
) -> List[dict]:
    if '카테고리분류' in df.columns and '입출금' not in df.columns:
        df = df.copy()
        df['입출금'] = df['카테고리분류']

    groupby_columns: List[str] = []
    if '입출금' in df.columns:
        groupby_columns.append('입출금')
    if '거래유형' in df.columns:
        groupby_columns.append('거래유형')
    if include_category_groupby and '카테고리' in df.columns:
        groupby_columns.append('카테고리')
    if not groupby_columns:
        return []

    if bank_col not in df.columns:
        return []

    category_stats = df.groupby(groupby_columns + [bank_col]).agg({
        '입금액': 'sum', '출금액': 'sum'
    }).reset_index()
    category_stats['차액'] = category_stats['입금액'] - category_stats['출금액']
    category_stats['총거래액'] = category_stats['입금액'] + category_stats['출금액']

    category_final = []
    for category_group, group_df in category_stats.groupby(groupby_columns):
        main_bank_row = group_df.loc[group_df['총거래액'].idxmax()]
        main_bank = main_bank_row[bank_col]
        total_deposit = group_df['입금액'].sum()
        total_withdraw = group_df['출금액'].sum()

        item: Dict[str, Any] = {
            'deposit': _safe_int(total_deposit),
            'withdraw': _safe_int(total_withdraw),
            'balance': _safe_int(total_deposit - total_withdraw),
            bank_col: _safe_label(main_bank),
        }
        if isinstance(category_group, tuple):
            for i, col in enumerate(groupby_columns):
                item[col] = _safe_label(category_group[i] if i < len(category_group) else None)
        else:
            if groupby_columns:
                item[groupby_columns[0]] = _safe_label(category_group)
        category_final.append(item)

    if not category_final:
        return []
    cdf = pd.DataFrame(category_final)
    cdf['차액_절대값'] = cdf['balance'].abs()
    cdf = cdf.sort_values(['차액_절대값', 'balance', 'deposit'], ascending=[False, False, False])
    cdf = cdf.drop('차액_절대값', axis=1)
    return cdf.to_dict('records')


# ────────────────────────────────────────
# 4. by-month
# ────────────────────────────────────────
def compute_by_month(df: pd.DataFrame) -> dict:
    if df.empty or '거래일' not in df.columns:
        return {'months': [], 'deposit': [], 'withdraw': [], 'min_date': None, 'max_date': None}
    df_all = df.copy()
    df_all['거래일'] = pd.to_datetime(df_all['거래일'], errors='coerce')
    df_all = df_all[df_all['거래일'].notna()]
    if df_all.empty:
        return {'months': [], 'deposit': [], 'withdraw': [], 'min_date': None, 'max_date': None}
    min_date = df_all['거래일'].min()
    max_date = df_all['거래일'].max()
    df_all['거래월'] = df_all['거래일'].dt.to_period('M').astype(str)
    if pd.notna(min_date) and pd.notna(max_date):
        date_range = pd.period_range(start=min_date.to_period('M'), end=max_date.to_period('M'), freq='M')
        all_months = [str(p) for p in date_range]
    else:
        all_months = sorted(df_all['거래월'].unique().tolist())
    monthly = df_all.groupby('거래월').agg({'입금액': 'sum', '출금액': 'sum'}).reset_index()
    d_dict = dict(zip(monthly['거래월'], monthly['입금액']))
    w_dict = dict(zip(monthly['거래월'], monthly['출금액']))
    deposit = [_safe_int(d_dict.get(m, 0)) for m in all_months]
    withdraw = [_safe_int(w_dict.get(m, 0)) for m in all_months]
    return {
        'months': all_months,
        'deposit': deposit,
        'withdraw': withdraw,
        'min_date': str(min_date) if pd.notna(min_date) else None,
        'max_date': str(max_date) if pd.notna(max_date) else None,
    }


# ────────────────────────────────────────
# 5. by-category-monthly
# ────────────────────────────────────────
def compute_by_category_monthly(
    df: pd.DataFrame,
    include_category_groupby: bool = True,
    label_cols: Optional[List[str]] = None,
) -> dict:
    if '카테고리분류' in df.columns and '입출금' not in df.columns:
        df = df.copy()
        df['입출금'] = df['카테고리분류']
    if df.empty or '거래일' not in df.columns:
        return {'months': [], 'categories': []}
    df = df.copy()
    df['거래일'] = pd.to_datetime(df['거래일'], errors='coerce')
    df = df[df['거래일'].notna()]
    df['거래월'] = df['거래일'].dt.to_period('M').astype(str)
    groupby_columns: List[str] = []
    if '입출금' in df.columns:
        groupby_columns.append('입출금')
    if '거래유형' in df.columns:
        groupby_columns.append('거래유형')
    if include_category_groupby and '카테고리' in df.columns:
        groupby_columns.append('카테고리')
    if not groupby_columns:
        return {'months': [], 'categories': []}
    if label_cols is None:
        label_cols = [c for c in groupby_columns if c != '입출금']

    monthly_by_cat = df.groupby(groupby_columns + ['거래월']).agg({'입금액': 'sum', '출금액': 'sum'}).reset_index()
    all_months = sorted(df['거래월'].unique().tolist())
    categories_data = []
    for cat_group, gdf in monthly_by_cat.groupby(groupby_columns):
        parts = []
        if isinstance(cat_group, tuple):
            for i, col in enumerate(groupby_columns):
                if col in label_cols:
                    v = cat_group[i] if i < len(cat_group) else None
                    if pd.notna(v) and v != '':
                        parts.append(str(v))
        else:
            if pd.notna(cat_group) and cat_group != '':
                parts.append(str(cat_group))
        label = '_'.join(parts) if parts else '(빈값)'
        md, mw = {}, {}
        for _, row in gdf.iterrows():
            m = row['거래월']
            md[m] = _safe_int(row['입금액'])
            mw[m] = _safe_int(row['출금액'])
        dep = [md.get(m, 0) for m in all_months]
        wit = [mw.get(m, 0) for m in all_months]
        td, tw = sum(dep), sum(wit)
        categories_data.append({
            'label': label, 'deposit': dep, 'withdraw': wit,
            'total_deposit': td, 'total_withdraw': tw,
            'total_balance': td - tw, 'abs_balance': abs(td - tw),
        })
    categories_data.sort(key=lambda x: x['abs_balance'], reverse=True)
    return {'months': all_months, 'categories': categories_data[:10]}


# ────────────────────────────────────────
# 6. by-content
# ────────────────────────────────────────
def compute_by_content(df: pd.DataFrame) -> dict:
    if df.empty or '내용' not in df.columns:
        return {'deposit': [], 'withdraw': []}
    dep = df.groupby('내용')['입금액'].sum().sort_values(ascending=False)
    wit = df.groupby('내용')['출금액'].sum().sort_values(ascending=False)
    return {
        'deposit': [{'content': idx if idx else '(빈값)', 'amount': int(val)} for idx, val in dep.items() if val > 0],
        'withdraw': [{'content': idx if idx else '(빈값)', 'amount': int(val)} for idx, val in wit.items() if val > 0],
    }


# ────────────────────────────────────────
# 7. by-division
# ────────────────────────────────────────
def compute_by_division(
    df: pd.DataFrame,
    division_col: str = '취소',
    normalizer: Optional[Callable] = None,
) -> List[dict]:
    if df.empty or division_col not in df.columns:
        return []
    df = df.copy()
    if normalizer is not None:
        df[division_col] = df[division_col].apply(normalizer)
    count_col = next((c for c in ['거래일', '이용일'] if c in df.columns), df.columns[0])
    stats = df.groupby(division_col).agg({'입금액': 'sum', '출금액': 'sum', count_col: 'count'}).reset_index()
    stats.columns = ['division', 'deposit', 'withdraw', 'count']
    stats = stats.fillna('')
    stats['deposit'] = stats['deposit'].astype(int)
    stats['withdraw'] = stats['withdraw'].astype(int)
    return stats.to_dict('records')


# ────────────────────────────────────────
# 8. by-bank
# ────────────────────────────────────────
def compute_by_bank(
    df: pd.DataFrame,
    bank_col: str = '은행명',
    account_col: str = '계좌번호',
    include_count: bool = True,
) -> dict:
    if df.empty or bank_col not in df.columns:
        return {'bank': [], 'account': []}
    bank_stats = df.groupby(bank_col).agg({'입금액': 'sum', '출금액': 'sum'}).reset_index()
    if include_count:
        bc = df.groupby(bank_col).size().reset_index(name='count')
        bank_stats = bank_stats.merge(bc, on=bank_col)
    bank_data = []
    for _, row in bank_stats.iterrows():
        item = {'bank': row[bank_col], 'deposit': _safe_int(row['입금액']), 'withdraw': _safe_int(row['출금액'])}
        if include_count:
            item['count'] = _safe_int(row.get('count'))
        bank_data.append(item)

    account_data = []
    if account_col in df.columns:
        acc_stats = df.groupby([bank_col, account_col]).agg({'입금액': 'sum', '출금액': 'sum'}).reset_index()
        if include_count:
            ac = df.groupby([bank_col, account_col]).size().reset_index(name='count')
            acc_stats = acc_stats.merge(ac, on=[bank_col, account_col])
        for _, row in acc_stats.iterrows():
            item = {
                'bank': row[bank_col] if pd.notna(row[bank_col]) else '',
                'account': str(row[account_col]).strip() if pd.notna(row[account_col]) else '',
                'deposit': _safe_int(row['입금액']),
                'withdraw': _safe_int(row['출금액']),
            }
            if include_count:
                item['count'] = _safe_int(row.get('count'))
            account_data.append(item)
    return {'bank': bank_data, 'account': account_data}


# ────────────────────────────────────────
# 9. transactions-by-content
# ────────────────────────────────────────
def compute_transactions_by_content(
    df: pd.DataFrame,
    type_filter: str = 'deposit',
    limit: int = 10,
    bank_col: str = '은행명',
    content_col: str = '내용',
    division_col: str = '취소',
    output_cols: Optional[List[str]] = None,
    json_safe_fn: Optional[Callable] = None,
) -> List[dict]:
    if df.empty:
        return []
    if type_filter == 'deposit':
        amt_col = '입금액' if '입금액' in df.columns else '이용금액'
    else:
        amt_col = '출금액' if '출금액' in df.columns else '이용금액'
    if amt_col not in df.columns:
        return []
    top = df[df[amt_col] > 0].groupby(content_col)[amt_col].sum().sort_values(ascending=False).head(limit)
    top_list = top.index.tolist()
    txns = df[(df[content_col].isin(top_list)) & (df[amt_col] > 0)].copy()
    txns = txns.sort_values(amt_col, ascending=False)
    txns = txns.where(pd.notna(txns), None)
    if output_cols is None:
        output_cols = [c for c in ['거래일', '거래시간', '이용일', '이용시간', bank_col, amt_col, division_col, '적요', content_col, '거래점', '카테고리'] if c in txns.columns]
    else:
        output_cols = [c for c in output_cols if c in txns.columns]
    data = txns[output_cols].to_dict('records') if output_cols else []
    if json_safe_fn:
        data = json_safe_fn(data)
    return data


# ────────────────────────────────────────
# 10. transactions
# ────────────────────────────────────────
def compute_transactions(
    df: pd.DataFrame,
    transaction_type: str = 'deposit',
    category_filter: str = '',
    content_filter: str = '',
    bank_filter: str = '',
    category_type: str = '',
    category_value: str = '',
    bank_col: str = '은행명',
    date_col: str = '거래일',
    filter_col: str = '카테고리',
    extra_col: str = '기타거래',
    output_cols: Optional[List[str]] = None,
    json_safe_fn: Optional[Callable] = None,
) -> dict:
    empty = {'data': [], 'deposit_total': 0, 'withdraw_total': 0, 'balance': 0, 'deposit_count': 0, 'withdraw_count': 0}
    if df.empty:
        return empty
    if filter_col not in df.columns:
        filter_col = '적요'
    if category_filter:
        filtered_df = df[df[filter_col].fillna('').astype(str).str.strip() == category_filter].copy()
    elif content_filter:
        filtered_df = df[df['내용'] == content_filter].copy()
    else:
        return empty
    if bank_filter and bank_col in filtered_df.columns:
        filtered_df = filtered_df[filtered_df[bank_col].astype(str).str.strip() == bank_filter].copy()
    if category_type and category_value and category_type in filtered_df.columns:
        filtered_df = filtered_df[filtered_df[category_type] == category_value].copy()

    deposit_total = filtered_df['입금액'].sum() if not filtered_df.empty else 0
    withdraw_total = filtered_df['출금액'].sum() if not filtered_df.empty else 0
    deposit_count = int((filtered_df['입금액'] > 0).sum()) if not filtered_df.empty else 0
    withdraw_count = int((filtered_df['출금액'] > 0).sum()) if not filtered_df.empty else 0

    if extra_col not in filtered_df.columns:
        extra_col = '내용'

    if transaction_type == 'detail':
        result_df = filtered_df.copy()
    elif transaction_type in ('deposit', 'withdraw'):
        amt_key = '입금액' if transaction_type == 'deposit' else '출금액'
        filtered_df = filtered_df[filtered_df[amt_key] > 0]
        if output_cols:
            cols = [c for c in output_cols if c in filtered_df.columns]
        else:
            cols = [c for c in [date_col, bank_col, amt_key, '취소', '적요', extra_col, '거래점'] if c in filtered_df.columns]
        result_df = filtered_df[cols].copy() if cols else filtered_df.copy()
        if amt_key in result_df.columns:
            result_df = result_df.rename(columns={amt_key: '금액'})
    else:
        dep_df = filtered_df[filtered_df['입금액'] > 0].copy()
        wit_df = filtered_df[filtered_df['출금액'] > 0].copy()
        if output_cols:
            cols_d = [c for c in output_cols if c in dep_df.columns]
            cols_w = [c for c in output_cols if c in wit_df.columns]
        else:
            cols_d = [c for c in [date_col, bank_col, '입금액', '취소', '적요', extra_col, '거래점'] if c in dep_df.columns]
            cols_w = [c for c in [date_col, bank_col, '출금액', '취소', '적요', extra_col, '거래점'] if c in wit_df.columns]
        dep_res = dep_df[cols_d].copy() if cols_d else dep_df.copy()
        if '입금액' in dep_res.columns:
            dep_res = dep_res.rename(columns={'입금액': '금액'})
        dep_res['거래유형'] = '입금'
        wit_res = wit_df[cols_w].copy() if cols_w else wit_df.copy()
        if '출금액' in wit_res.columns:
            wit_res = wit_res.rename(columns={'출금액': '금액'})
        wit_res['거래유형'] = '출금'
        result_df = pd.concat([dep_res, wit_res], ignore_index=True)

    sort_col = date_col if date_col in result_df.columns else '거래일'
    if sort_col in result_df.columns:
        result_df = result_df.sort_values(sort_col)
    if extra_col in result_df.columns:
        result_df[extra_col] = result_df[extra_col].fillna('').astype(str).str.strip()
    result_df = result_df.where(pd.notna(result_df), None)
    if extra_col in result_df.columns:
        result_df[extra_col] = result_df[extra_col].apply(lambda x: '' if x is None else str(x).strip())
    data = result_df.to_dict('records')
    if json_safe_fn:
        data = json_safe_fn(data)
    return {
        'data': data,
        'deposit_total': _safe_int(deposit_total),
        'withdraw_total': _safe_int(withdraw_total),
        'balance': _safe_int(deposit_total - withdraw_total),
        'deposit_count': deposit_count,
        'withdraw_count': withdraw_count,
    }


# ────────────────────────────────────────
# 11. content-by-category
# ────────────────────────────────────────
def compute_content_by_category(df: pd.DataFrame, filter_col: str = '카테고리', category_filter: str = '') -> List[dict]:
    if df.empty or not category_filter:
        return []
    if filter_col not in df.columns:
        filter_col = '적요' if '적요' in df.columns else '카테고리'
    if filter_col not in df.columns:
        return []
    filtered = df[(df[filter_col].fillna('').astype(str).str.strip() == category_filter) & (df['입금액'] > 0)].copy()
    if filtered.empty:
        return []
    stats = filtered.groupby('내용')['입금액'].sum().sort_values(ascending=False).reset_index()
    return [{'content': _safe_label(r['내용'], '(빈값)'), 'amount': _safe_int(r['입금액'])} for _, r in stats.iterrows()]


# ────────────────────────────────────────
# 12. date-range
# ────────────────────────────────────────
def compute_date_range(df: pd.DataFrame) -> dict:
    if df.empty or '거래일' not in df.columns:
        return {'min_date': None, 'max_date': None}
    df = df.copy()
    df['거래일'] = pd.to_datetime(df['거래일'], errors='coerce')
    df = df[df['거래일'].notna()]
    if df.empty:
        return {'min_date': None, 'max_date': None}
    return {
        'min_date': df['거래일'].min().strftime('%Y-%m-%d'),
        'max_date': df['거래일'].max().strftime('%Y-%m-%d'),
    }
