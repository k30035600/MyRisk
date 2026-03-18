# -*- coding: utf-8 -*-
"""
데이터 JSON 읽기·쓰기 (DataFrame ↔ .json).

DataFrame을 UTF-8 JSON(records 형식)으로 저장·로드한다. datetime·numpy 타입은 JSON 호환으로 변환한다.

주요 함수: safe_write_data_json, safe_read_data_json
"""
import os
import json
import logging
import tempfile
import numpy as np
import pandas as pd

_logger = logging.getLogger(__name__)


def _records_to_json_serializable(rec):
    """to_dict('records') 결과에서 datetime·numpy 타입을 JSON 호환으로 변환."""
    for row in rec:
        for k, v in list(row.items()):
            if hasattr(v, 'isoformat'):
                row[k] = v.isoformat()
            elif pd.isna(v):
                row[k] = None
            elif isinstance(v, (np.integer, np.floating)):
                row[k] = float(v) if isinstance(v, np.floating) else int(v)
    return rec


def safe_write_data_json(path, df):
    """DataFrame을 path에 UTF-8 JSON(records 형식)으로 저장. 성공 시 True, 실패 시 False."""
    if df is None:
        df = pd.DataFrame()
    if not isinstance(df, pd.DataFrame):
        return False
    try:
        dir_name = os.path.dirname(os.path.abspath(path))
        os.makedirs(dir_name, exist_ok=True)
        rec = df.fillna('').to_dict('records')
        _records_to_json_serializable(rec)
        fd, tmp = tempfile.mkstemp(dir=dir_name, suffix='.tmp')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(rec, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        return True
    except Exception:
        _logger.exception('safe_write_data_json 실패: %s', path)
        return False


def safe_read_data_json(path, default_empty=True):
    """path의 JSON 파일을 DataFrame으로 읽기. 파일 없음/빈파일/손상 시 default_empty면 빈 DataFrame, 아니면 None."""
    if not path or not os.path.isfile(path):
        return pd.DataFrame() if default_empty else None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            raw = f.read().strip()
        if not raw:
            return pd.DataFrame() if default_empty else None
        data = json.loads(raw)
        if not data:
            return pd.DataFrame() if default_empty else None
        df = pd.DataFrame(data)
        return df if df is not None else (pd.DataFrame() if default_empty else None)
    except Exception:
        _logger.exception('safe_read_data_json 실패: %s', path)
        return pd.DataFrame() if default_empty else None
