# -*- coding: utf-8 -*-
"""category_table.json 읽기/쓰기·정규화·액션. 은행/신용카드/금융정보 공통."""
import json
import os
import re

try:
    import pandas as pd
except ImportError:
    pd = None

CATEGORY_TABLE_COLUMNS = ['분류', '키워드', '카테고리']
# 확장 컬럼: xlsx→json 변환 시 위험도·업종코드 포함
CATEGORY_TABLE_EXTENDED_COLUMNS = ['분류', '키워드', '카테고리', '위험도', '업종코드']


def _to_str_no_decimal(val):
    """업종코드 등: 문자로 취급, 소수점 없이 정수 문자열로. (1.0 → '1')"""
    if val is None:
        return ''
    if isinstance(val, float):
        if val != val:  # NaN
            return ''
        if val == int(val):
            return str(int(val))
        return str(val).strip()
    if isinstance(val, int):
        return str(val)
    return str(val).strip() if val != '' else ''


def _norm_path(path):
    if path is None:
        return None
    p = str(path).strip()
    if p.endswith('.xlsx'):
        p = p.replace('.xlsx', '.json')
    return p or None


def load_category_table(path, default_empty=True):
    """JSON 카테고리 테이블 로드. 없거나 손상 시 default_empty면 빈 DataFrame, 아니면 None."""
    path = _norm_path(path)
    if not path or not os.path.exists(path):
        if pd is None:
            return [] if default_empty else None
        return pd.DataFrame(columns=CATEGORY_TABLE_COLUMNS) if default_empty else None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not data:
            return pd.DataFrame(columns=CATEGORY_TABLE_COLUMNS) if default_empty and pd else None
        if pd:
            df = pd.DataFrame(data)
            return df
        return data
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        if pd and default_empty:
            return pd.DataFrame(columns=CATEGORY_TABLE_COLUMNS)
        return None


def normalize_category_df(df, extended=False):
    """구분 등 제거, 표준 컬럼만 유지, fillna. extended=True면 위험도·업종코드 컬럼 포함."""
    if df is None or (pd is not None and df.empty):
        cols = CATEGORY_TABLE_EXTENDED_COLUMNS if extended else CATEGORY_TABLE_COLUMNS
        return pd.DataFrame(columns=cols) if pd else []
    df = df.fillna('')
    df = df.drop(columns=['구분', '폐업'], errors='ignore')
    out_cols = CATEGORY_TABLE_EXTENDED_COLUMNS if extended else CATEGORY_TABLE_COLUMNS
    for c in out_cols:
        if c not in df.columns:
            df[c] = ''
    if extended and pd is not None and '업종코드' in df.columns:
        df = df.copy()
        df['업종코드'] = df['업종코드'].apply(_to_str_no_decimal)
    return df[out_cols].copy()


def safe_write_category_table(path, df, extended=False):
    """카테고리 테이블 JSON 저장. extended=True이거나 df에 위험도·업종코드가 있으면 5컬럼으로 저장."""
    path = _norm_path(path)
    if not path:
        return
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    if df is None or (pd is not None and df.empty):
        rec = []
    else:
        if extended or (pd is not None and ('위험도' in df.columns or '업종코드' in df.columns)):
            write_cols = CATEGORY_TABLE_EXTENDED_COLUMNS
            if pd:
                for c in write_cols:
                    if c not in df.columns:
                        df = df.copy()
                        df[c] = ''
        else:
            write_cols = CATEGORY_TABLE_COLUMNS
        if pd:
            out = df[write_cols].copy().fillna('')
            if '업종코드' in out.columns:
                out['업종코드'] = out['업종코드'].apply(_to_str_no_decimal)
            rec = out.to_dict('records')
            if write_cols == CATEGORY_TABLE_EXTENDED_COLUMNS:
                for row in rec:
                    for c in write_cols:
                        if c not in row:
                            row[c] = ''
        else:
            out = df
            rec = out.to_dict('records') if hasattr(out, 'to_dict') else out
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(rec, f, ensure_ascii=False, indent=2)


def create_empty_category_table(path):
    """빈 category_table.json 생성."""
    path = _norm_path(path)
    if path:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump([], f, ensure_ascii=False)


def ensure_prepost_in_table(path):
    """테이블에 전처리/후처리 행이 있는지 확인 후 반환 (필요 시 여기서 보강 가능)."""
    return load_category_table(path, default_empty=True)


def normalize_주식회사_for_match(text):
    """가맹점명 등에서 '주식회사'·'㈜' → '(주)' 통일."""
    if text is None or (isinstance(text, str) and not str(text).strip()):
        return '' if text is None else str(text).strip()
    val = str(text).strip()
    val = re.sub(r'[\s/]*주식회사[\s/]*', '(주)', val)
    val = re.sub(r'[\s/]*㈜[\s/]*', '(주)', val)
    val = re.sub(r'(\(주\)[\s/]*)+', '(주)', val)
    return val


def get_category_table(path):
    """(df, file_existed) 반환. 파일이 있으면 file_existed True."""
    path = _norm_path(path)
    file_existed = path and os.path.exists(path)
    df = load_category_table(path, default_empty=True)
    return (df, file_existed)


def apply_category_action(path, action, data):
    """path에 action 적용. 반환 (success, error_msg, count). 5컬럼(분류·키워드·카테고리·위험도·업종코드) 유지.
    action: 'add', 'replace', 'update', 'delete'."""
    path = _norm_path(path)
    if not path:
        return (False, '경로가 없습니다.', 0)
    rows = data.get('rows') if isinstance(data, dict) else []
    if not isinstance(rows, list):
        rows = []
    cols = CATEGORY_TABLE_EXTENDED_COLUMNS
    try:
        if action == 'update' or action == 'delete':
            existing = load_category_table(path, default_empty=True)
            if existing is None or (pd is not None and existing.empty):
                return (False, '수정/삭제할 데이터가 없습니다.', 0)
            if pd is not None:
                existing = normalize_category_df(existing, extended=True)
            o_분류 = str(data.get('original_분류') or '').strip()
            o_키워드 = str(data.get('original_키워드') or '').strip()
            o_카테고리 = str(data.get('original_카테고리') or '').strip()
            if action == 'delete':
                if pd is not None:
                    mask = (
                        (existing['분류'].fillna('').astype(str).str.strip() == o_분류)
                        & (existing['키워드'].fillna('').astype(str).str.strip() == o_키워드)
                        & (existing['카테고리'].fillna('').astype(str).str.strip() == o_카테고리)
                    )
                    out = existing.loc[~mask].copy()
                else:
                    out_list = [r for r in (existing.to_dict('records') if hasattr(existing, 'to_dict') else existing)
                               if (str(r.get('분류') or '').strip(), str(r.get('키워드') or '').strip(), str(r.get('카테고리') or '').strip()) != (o_분류, o_키워드, o_카테고리)]
                    out = out_list
            else:
                # update: 해당 행을 새 값으로 교체
                n_분류 = str(data.get('분류') or '').strip()
                n_키워드 = str(data.get('키워드') or '').strip()
                n_카테고리 = str(data.get('카테고리') or '').strip()
                n_위험도 = str(data.get('위험도') or '').strip()
                n_업종코드 = _to_str_no_decimal(data.get('업종코드'))
                if pd is not None:
                    mask = (
                        (existing['분류'].fillna('').astype(str).str.strip() == o_분류)
                        & (existing['키워드'].fillna('').astype(str).str.strip() == o_키워드)
                        & (existing['카테고리'].fillna('').astype(str).str.strip() == o_카테고리)
                    )
                    existing.loc[mask, '분류'] = n_분류
                    existing.loc[mask, '키워드'] = n_키워드
                    existing.loc[mask, '카테고리'] = n_카테고리
                    existing.loc[mask, '위험도'] = n_위험도
                    existing.loc[mask, '업종코드'] = n_업종코드
                    out = existing
                else:
                    new_row = {cols[0]: n_분류, cols[1]: n_키워드, cols[2]: n_카테고리, cols[3]: n_위험도, cols[4]: n_업종코드}
                    out_list = []
                    for r in (existing.to_dict('records') if hasattr(existing, 'to_dict') else existing):
                        if (str(r.get('분류') or '').strip(), str(r.get('키워드') or '').strip(), str(r.get('카테고리') or '').strip()) == (o_분류, o_키워드, o_카테고리):
                            out_list.append(new_row)
                        else:
                            out_list.append({c: r.get(c, '') for c in cols})
                    out = out_list
            if pd is not None:
                safe_write_category_table(path, out, extended=True)
                return (True, '', len(out))
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(out, f, ensure_ascii=False, indent=2)
            return (True, '', len(out))
        if action == 'replace' or action == 'add':
            existing = load_category_table(path, default_empty=True)
            if existing is None or (pd is not None and existing.empty):
                existing = pd.DataFrame(columns=cols) if pd else []
            elif pd is not None:
                existing = normalize_category_df(existing, extended=True)
            new_rows = []
            for r in rows:
                if not isinstance(r, dict):
                    continue
                row = {c: str(r.get(c, '') or '').strip() for c in cols}
                if any(row.get(c, '') for c in CATEGORY_TABLE_COLUMNS):
                    new_rows.append(row)
            if pd:
                add_df = pd.DataFrame(new_rows)
                if add_df.empty and action == 'add':
                    return (True, '', len(existing) if hasattr(existing, '__len__') else 0)
                for c in cols:
                    if c not in add_df.columns:
                        add_df[c] = ''
                add_df = add_df[cols]
                if action == 'replace':
                    out = add_df.drop_duplicates(subset=CATEGORY_TABLE_COLUMNS, keep='first')
                else:
                    out = pd.concat([existing, add_df], ignore_index=True).drop_duplicates(subset=CATEGORY_TABLE_COLUMNS, keep='last')
                safe_write_category_table(path, out, extended=True)
                return (True, '', len(out))
            # no pandas: list only
            existing_list = existing.to_dict('records') if hasattr(existing, 'to_dict') else (existing if isinstance(existing, list) else [])
            for row in existing_list:
                for c in cols:
                    if c not in row:
                        row[c] = ''
            if action == 'replace':
                out_list = new_rows
            else:
                seen = set()
                out_list = []
                for r in existing_list + new_rows:
                    key = tuple(r.get(c, '') for c in CATEGORY_TABLE_COLUMNS)
                    if key in seen:
                        continue
                    seen.add(key)
                    out_list.append({c: r.get(c, '') for c in cols})
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(out_list, f, ensure_ascii=False, indent=2)
            return (True, '', len(out_list))
        return (False, f'지원하지 않는 action: {action}', 0)
    except Exception as e:
        return (False, str(e), 0)


def get_category_table_path():
    """기본 category_table.json 경로 (data 폴더에서 관리)."""
    try:
        from lib.path_config import get_category_table_json_path
        return get_category_table_json_path()
    except ImportError:
        return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'category_table.json')


def export_category_table_to_xlsx(category_table_path):
    """category_table.json을 .source/category_table.xlsx로 내보내기. 5컬럼(분류·키워드·카테고리·위험도·업종코드) 유지. (ok, xlsx_path, error_msg)."""
    try:
        import pandas as pd
        try:
            from lib.path_config import get_category_table_xlsx_path
            out_path = get_category_table_xlsx_path()
        except ImportError:
            _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            out_path = os.path.join(_root, '.source', 'category_table.xlsx')
        path = _norm_path(category_table_path) or get_category_table_path()
        df = load_category_table(path, default_empty=True)
        os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
        if df is None or df.empty:
            pd.DataFrame(columns=CATEGORY_TABLE_EXTENDED_COLUMNS).to_excel(out_path, index=False, engine='openpyxl')
            return (True, out_path, None)
        df = normalize_category_df(df, extended=True)
        df[CATEGORY_TABLE_EXTENDED_COLUMNS].to_excel(out_path, index=False, engine='openpyxl')
        return (True, out_path, None)
    except Exception as e:
        return (False, None, str(e))


# ----- 업종분류·위험도 매칭 (category_table만 사용) -----
# 분류/카테고리가 아래 이름인 행만 업종분류 조회·매칭에 사용. 위험도 수치는 고정 매핑.
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


def _risk_value(분류명):
    """분류명에 해당하는 위험도 수치. 없으면 0.1."""
    if not 분류명 or not isinstance(분류명, str):
        return 0.1
    return RISK_CLASS_TO_VALUE.get(분류명.strip(), 0.1)


def _is_risk_class(분류, 카테고리):
    """분류 또는 카테고리가 위험도 분류명(1~10호)인지 여부."""
    s = (분류 or '').strip() or (카테고리 or '').strip()
    return s in RISK_CLASS_TO_VALUE


def _load_category_table_raw(path=None):
    """category_table.json을 리스트[dict]로 로드. 실패 시 []."""
    path = path or get_category_table_path()
    if not path or not os.path.exists(path) or os.path.getsize(path) == 0:
        return []
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError, TypeError):
        return []


def _default_risk_class_rows():
    """category_table에 위험도 행이 없을 때 사용할 기본 1~10호 행."""
    return [
        {'업종분류': name, '위험도': str(val), '업종코드': '', '키워드': ''}
        for name, val in RISK_CLASS_TO_VALUE.items()
    ]


def get_risk_class_table_data():
    """
    업종분류 조회용 데이터 반환.
    category_table에서 분류='위험도분류'인 행만 추려 변환:
    업종분류=카테고리, 위험도=행의 위험도, 업종코드=행의 업종코드, 키워드=키워드.
    """
    rows = _load_category_table_raw()
    out = []
    for r in rows:
        분류 = (r.get('분류') or '').strip()
        if 분류 != '위험도분류':
            continue
        키워드 = (r.get('키워드') or '').strip()
        카테고리 = (r.get('카테고리') or '').strip()
        if not 카테고리 or 카테고리 not in RISK_CLASS_TO_VALUE:
            continue
        위험도_val = r.get('위험도')
        try:
            risk_str = str(float(위험도_val)) if 위험도_val is not None and str(위험도_val).strip() != '' else str(_risk_value(카테고리))
        except (TypeError, ValueError):
            risk_str = str(_risk_value(카테고리))
        업종코드 = (r.get('업종코드') or '')
        if hasattr(업종코드, 'strip'):
            업종코드 = str(업종코드).strip()
        else:
            업종코드 = _to_str_no_decimal(업종코드) if 업종코드 else ''
        out.append({
            '업종분류': 카테고리,
            '위험도': risk_str,
            '업종코드': 업종코드,
            '키워드': 키워드,
        })
    if not out:
        return _default_risk_class_rows()
    return out


def _split_keywords(키워드):
    """키워드 문자열을 쉼표·슬래시로 나누어 리스트로 반환."""
    if not 키워드 or not isinstance(키워드, str):
        return []
    parts = []
    for s in 키워드.replace('/', ',').split(','):
        s = s.strip()
        if s:
            parts.append(s)
    return parts if parts else [키워드.strip()] if 키워드.strip() else []


def get_risk_class_map_for_apply():
    """
    cash_after 행별 매칭용: (code_to_업종분류, code_to_위험도) 반환.
    분류='위험도분류'인 행만 사용. 키워드로 매칭 시 카테고리→위험도분류, 행의 위험도 저장.
    """
    rows = _load_category_table_raw()
    code_to_업종분류 = {}
    code_to_위험도 = {}
    for r in rows:
        분류 = (r.get('분류') or '').strip()
        if 분류 != '위험도분류':
            continue
        키워드 = (r.get('키워드') or '').strip()
        카테고리 = (r.get('카테고리') or '').strip()
        if not 카테고리 or 카테고리 not in RISK_CLASS_TO_VALUE:
            continue
        위험도_val = r.get('위험도')
        try:
            risk_str = str(float(위험도_val)) if 위험도_val is not None and str(위험도_val).strip() != '' else str(_risk_value(카테고리))
        except (TypeError, ValueError):
            risk_str = str(_risk_value(카테고리))
        code_to_업종분류[카테고리] = 카테고리
        code_to_위험도[카테고리] = risk_str
        for kw in _split_keywords(키워드):
            if kw and not (len(kw) >= 4 and kw.startswith('분류') and kw.endswith('호')):
                code_to_업종분류[kw] = 카테고리
                code_to_위험도[kw] = risk_str
        if 키워드:
            code_to_업종분류[키워드] = 카테고리
            code_to_위험도[키워드] = risk_str
    for name, val in RISK_CLASS_TO_VALUE.items():
        if name not in code_to_업종분류:
            code_to_업종분류[name] = name
            code_to_위험도[name] = str(val)
    return (code_to_업종분류, code_to_위험도)


def export_risk_class_table_to_xlsx(json_path=None, xlsx_path=None):
    """
    업종분류 데이터( get_risk_class_table_data() )를 xlsx로 내보내기.
    category_table 기반. (ok, xlsx_path, error_msg).
    """
    try:
        import pandas as pd
        data = get_risk_class_table_data()
        out_path = xlsx_path or (os.path.join(os.path.dirname(get_category_table_path()), '업종분류_table.xlsx'))
        os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
        cols = ['업종분류', '위험도', '업종코드', '키워드']
        df = pd.DataFrame(data)
        for c in cols:
            if c not in df.columns:
                df[c] = ''
        df[cols].to_excel(out_path, index=False, engine='openpyxl')
        return (True, out_path, None)
    except Exception as e:
        return (False, None, str(e))
