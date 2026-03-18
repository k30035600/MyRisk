# -*- coding: utf-8 -*-
"""
Excel 파일 안전 쓰기 공통 모듈.

권한 오류 방지를 위해 재시도 로직이 포함된 Excel 저장을 제공한다.
process_bank_data, process_card_data, process_cash_data, card_app에서 사용한다.

주요 함수: safe_write_excel
"""
import os
import tempfile
import time


def safe_write_excel(df, filepath, max_retries=3):
    """임시 파일에 쓴 뒤 os.replace()로 원자적 교체. 쓰기 중 크래시 시 기존 파일 보존."""
    dir_name = os.path.dirname(os.path.abspath(filepath))
    os.makedirs(dir_name, exist_ok=True)
    for attempt in range(max_retries):
        fd, tmp = tempfile.mkstemp(dir=dir_name, suffix='.xlsx.tmp')
        try:
            os.close(fd)
            df.to_excel(tmp, index=False, engine='openpyxl')
            os.replace(tmp, filepath)
            return True
        except PermissionError:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            if attempt < max_retries - 1:
                time.sleep(0.5)
                continue
            raise
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    return False
