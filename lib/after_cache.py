# -*- coding: utf-8 -*-
"""
after JSON 캐시 공통 모듈.

은행·카드·금융정보 앱의 bank_after, card_after, cash_after 파일을 mtime 기반으로 메모리 캐싱한다.
파일 수정 시 자동 재읽기, invalidate로 수동 무효화 가능.

주요 클래스: AfterCache (get, invalidate, current)
"""
from pathlib import Path
import pandas as pd


class AfterCache:
    """단일 after 파일에 대한 메모리 캐시 (mtime 기반 무효화)."""

    def __init__(self):
        self._cache = None
        self._cache_mtime = None

    def get(self, path, read_fn):
        """
        path: after 파일 경로 (str 또는 Path).
        read_fn: (path) -> DataFrame. 파일을 읽어 정규화한 DataFrame 반환.
        반환: 캐시 hit이면 copy, miss면 read_fn 호출 후 캐시 저장·copy 반환. 파일 없으면 빈 DataFrame.
        """
        p = Path(path) if not isinstance(path, Path) else path
        if not p.exists():
            self.invalidate()
            return pd.DataFrame()
        try:
            mtime = p.stat().st_mtime
        except OSError:
            mtime = None
        # mtime이 같으면 캐시 반환, 변경됐으면 무효화 후 재읽기
        if self._cache is not None and mtime is not None and mtime == self._cache_mtime:
            return self._cache.copy()
        if self._cache is not None:
            self.invalidate()
        df = read_fn(str(p)) if callable(read_fn) else read_fn
        if df is not None and not df.empty:
            self._cache = df
            self._cache_mtime = mtime
            return df.copy()
        return df if df is not None else pd.DataFrame()

    def invalidate(self):
        """캐시·mtime 초기화 (재생성/clear 시 호출)."""
        self._cache = None
        self._cache_mtime = None

    @property
    def current(self):
        """현재 캐시된 DataFrame (없으면 None). cache-info 등에서 사용."""
        return self._cache
