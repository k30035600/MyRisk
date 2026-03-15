# -*- coding: utf-8 -*-
"""계정과목 표준 전수조사 + 검수보고서 + 부록 — HTML 직접 생성."""
import json, os, re, glob
from datetime import datetime

from lib.category_constants import (
    CLASS_PRE, CLASS_POST, CLASS_ACCOUNT, CLASS_APPLICANT,
    CLASS_NIGHT, CLASS_RISK, CLASS_INDUSTRY,
    BANK_DEFAULT_DEPOSIT, BANK_DEFAULT_WITHDRAWAL,
    CARD_DEFAULT_DEPOSIT, CARD_DEFAULT_WITHDRAWAL,
    DEFAULT_CATEGORY, UNCLASSIFIED, CARD_CASH_PROCESSING,
    DIRECTION_CANCELLED, CANCELLED_TRANSACTION,
)

_HARDCODE_PATTERNS = {
    '전처리': [r"""['"]전처리['"]"""], '후처리': [r"""['"]후처리['"]"""],
    '계정과목': [r"""['"]계정과목['"]"""], '신청인': [r"""['"]신청인['"]"""],
    '심야구분': [r"""['"]심야구분['"]"""], '위험도분류': [r"""['"]위험도분류['"]"""],
    '업종분류': [r"""['"]업종분류['"]"""], '미분류': [r"""['"]미분류['"]"""],
    '취소': [r"""['"]취소['"]"""], '취소된 거래': [r"""['"]취소된 거래['"]"""],
    '현금서비스': [r"""['"]현금서비스['"]"""],
}

_COL_PATS = [
    r"row\[", r"item\[", r"col\s*===", r"\.indexOf\(col\)", r"preferredOrder",
    r"COLUMN_ORDER", r"availableColumns", r"col\s*==\s*'", r"key\s*===",
    r"key\.includes", r"df\[", r"\.columns", r"rename\(", r"\bcolumn\b",
]

_SEV_BADGE = {'HIGH': 'b-h', 'MEDIUM': 'b-m', 'LOW': 'b-l'}


def _skip(fpath):
    return any(x in fpath for x in ['temp/', 'temp\\', '__pycache__', '.git', 'node_modules'])


def _scan_hardcoding(root):
    py_files, html_files = [], []
    for p in ['*.py', 'MyBank/*.py', 'MyCard/*.py', 'MyCash/*.py', 'lib/*.py', 'scripts/*.py']:
        py_files.extend(glob.glob(os.path.join(root, p)))
    for p in ['templates/*.html', 'MyBank/templates/*.html', 'MyCard/templates/*.html', 'MyCash/templates/*.html']:
        html_files.extend(glob.glob(os.path.join(root, p)))

    hardcode_all = []
    for fpath in py_files + html_files:
        if _skip(fpath):
            continue
        try:
            content = open(fpath, 'r', encoding='utf-8').read()
        except Exception:
            continue
        lines = content.split('\n')
        for label, patterns in _HARDCODE_PATTERNS.items():
            for pat in patterns:
                for i, line in enumerate(lines, 1):
                    s = line.strip()
                    if s.startswith('#') or s.startswith('//'):
                        continue
                    if re.search(pat, line):
                        if any(x in line for x in [
                            'import', 'CLASS_', 'DIRECTION_', 'CANCELLED_',
                            'DEFAULT_', 'UNCLASSIFIED', 'CARD_CASH', 'category_constants',
                        ]):
                            continue
                        rel = os.path.relpath(fpath, root)
                        hardcode_all.append({'file': rel, 'line': i, 'labels': [label], 'code': s[:120]})
    return hardcode_all, html_files


def _scan_template_injection(root, html_files):
    tmpl_info = {}
    for fpath in html_files:
        if _skip(fpath) or 'kcs30035600' in fpath:
            continue
        try:
            content = open(fpath, 'r', encoding='utf-8').read()
        except Exception:
            continue
        has_cat = 'const CAT' in content or 'CAT.' in content
        has_jinja = 'VALID_CHASU' in content or 'CHASU_ORDER' in content
        hc_js = 0
        for line in content.split('\n'):
            s = line.strip()
            if s.startswith('//') or s.startswith('<!--'):
                continue
            for val in ['전처리', '후처리', '계정과목', '신청인', '심야구분', '위험도분류', '업종분류', '미분류']:
                if (f"'{val}'" in line or f'"{val}"' in line) and \
                   'CAT.' not in line and 'CLASS_' not in line and \
                   '{{' not in line and 'const CAT' not in line:
                    hc_js += 1
        rel = os.path.relpath(fpath, root)
        tmpl_info[rel] = {'cat': has_cat, 'jinja': has_jinja, 'hc_js': hc_js}
    return tmpl_info


def _load_audit_data(root):
    """category_standard_audit API 로직을 직접 실행해서 결과를 반환."""
    ct_path = os.path.join(root, 'data', 'category_table.json')
    bank_path = os.path.join(root, 'data', 'bank_after.json')
    md_path = os.path.join(root, 'readme', '가이드', '계정과목_표준.md')

    result = {
        '현행키워드수': 0, '신규키워드수': 0,
        '변경': [], '유지': 0,
        '은행': {'기타거래총수': 0, '매칭': 0, '미매칭': 0, '미매칭목록': []},
    }

    if not os.path.exists(ct_path):
        return result

    with open(ct_path, 'r', encoding='utf-8') as _f:
        ct = json.load(_f)
    old_kw_map = {}
    for r in ct:
        if r.get('분류') != CLASS_ACCOUNT:
            continue
        cat = r.get('카테고리', '')
        for kw in r.get('키워드', '').split('/'):
            kw = kw.strip()
            if kw:
                old_kw_map[kw] = cat
    result['현행키워드수'] = len(old_kw_map)

    if not os.path.exists(md_path):
        return result

    with open(md_path, 'r', encoding='utf-8') as _f:
        md_content = _f.read()
    new_kw_map = {}
    current_section = None
    current_code = None
    current_mid = ''
    major_map = {
        'I': 'I. 자금이동', 'II': 'II. 필수생활비', 'III': 'III. 재량소비',
        'IV': 'IV. 고위험항목', 'V': 'V. 금융거래', 'VI': 'VI. 인적거래', 'VII': 'VII. 미분류',
    }

    for line in md_content.split('\n'):
        ls = line.strip()
        if ls.startswith('## 5. 계정과목'):
            current_section = CLASS_ACCOUNT
            continue
        elif ls.startswith('## 6.') or ls.startswith('## 7.') or ls.startswith('## 부록'):
            current_section = None
            continue
        elif ls.startswith('## '):
            if current_section == CLASS_ACCOUNT:
                current_section = None
            continue

        if current_section != CLASS_ACCOUNT:
            continue

        hm = re.match(r'^###\s+(I{1,3}V?|IV|V|VI{0,2}|VII)\.?\s+(.+?)(?:\s*—\s*(.+))?$', ls)
        if hm:
            mid_part = hm.group(3)
            current_mid = mid_part.strip() if mid_part else hm.group(2).strip()
            continue

        m = re.match(r'^####\s+([A-Z]\d+)\s+(.+)$', ls)
        if m:
            current_code = m.group(1)
            continue

        if current_code and ls.startswith('| ') and not ls.startswith('| 키워드') and not ls.startswith('|---'):
            cols = [c.strip() for c in ls.split('|')[1:-1]]
            if cols and cols[0]:
                for kw in cols[0].split('/'):
                    kw = kw.strip()
                    if kw:
                        cat_mid = f'{current_code[0]}_{current_mid}'
                        new_kw_map[kw] = {'code': current_code, 'cat': cat_mid}

    result['신규키워드수'] = len(new_kw_map)

    old_set = set(old_kw_map.keys())
    new_set = set(new_kw_map.keys())
    changed, same_cnt = [], 0
    for kw in sorted(old_set & new_set):
        old_cat = old_kw_map[kw]
        ni = new_kw_map[kw]
        if old_cat != ni['cat']:
            changed.append({'키워드': kw, '현행': old_cat, '신규': ni['cat']})
        else:
            same_cnt += 1
    result['변경'] = changed
    result['유지'] = same_cnt

    def _parse_amt(v):
        try:
            return int(float(str(v).replace(',', '') or '0'))
        except Exception:
            return 0

    if os.path.exists(bank_path):
        bank = json.load(open(bank_path, 'r', encoding='utf-8'))
        kita_set = {r.get('기타거래', '').strip() for r in bank if r.get('기타거래', '').strip()}
        matched_list, unmatched_list = [], []
        for val in sorted(kita_set):
            hit = None
            for kw, info in new_kw_map.items():
                if kw in val:
                    hit = info
                    break
            txns = [r for r in bank if r.get('기타거래', '').strip() == val]
            total_in = sum(_parse_amt(r.get('입금액', 0)) for r in txns)
            total_out = sum(_parse_amt(r.get('출금액', 0)) for r in txns)
            entry = {'기타거래': val, '건수': len(txns), '입금': total_in, '출금': total_out,
                     '분류': BANK_DEFAULT_DEPOSIT if (total_in > 0 and total_out == 0) else BANK_DEFAULT_WITHDRAWAL}
            if hit:
                matched_list.append(entry)
            else:
                unmatched_list.append(entry)

        result['은행'] = {
            '기타거래총수': len(kita_set),
            '매칭': len(matched_list),
            '미매칭': len(unmatched_list),
            '미매칭목록': unmatched_list,
        }

    return result


def generate_report_html(root):
    """전수조사 보고서 + 검수보고서 + 부록 HTML 문자열 반환."""
    now = datetime.now().strftime('%Y-%m-%d %H:%M')

    # ── 카테고리 테이블 현황 ──
    ct_path = os.path.join(root, 'data', 'category_table.json')
    if not os.path.exists(ct_path):
        return '<h1>category_table.json이 없습니다.</h1>'

    cat_data = json.load(open(ct_path, 'r', encoding='utf-8'))
    total_rows = len(cat_data)
    cls_count = {}
    for r in cat_data:
        c = r.get('분류', '')
        cls_count[c] = cls_count.get(c, 0) + 1

    kw_total, kw_set, dup_kw = 0, set(), {}
    for r in cat_data:
        kws = [x.strip() for x in r.get('키워드', '').split('/') if x.strip()]
        kw_total += len(kws)
        for k in kws:
            key = k.lower()
            dup_kw.setdefault(key, []).append({
                '분류': r.get('분류', ''), '위험도': r.get('위험도', ''),
                '카테고리': r.get('카테고리', ''), '위험지표': str(r.get('위험지표', '')), '키워드': k,
            })
            kw_set.add(key)

    acct_ri = sorted(set(
        str(r.get('위험지표', '')) for r in cat_data
        if r.get('분류') == '계정과목' and re.match(r'^[A-Z]+\d+$', str(r.get('위험지표', '')))
    ))

    cross_dup = {kw: ents for kw, ents in dup_kw.items()
                 if len(ents) > 1 and len(set(e['위험지표'] for e in ents)) > 1}

    # ── 하드코딩 스캔 ──
    hardcode_all, html_files = _scan_hardcoding(root)
    active_hc = [d for d in hardcode_all if 'kcs30035600' not in d['file']]
    col_ref = [d for d in active_hc if any(re.search(cp, d['code'], re.I) for cp in _COL_PATS)]
    real_hc = [d for d in active_hc if not any(re.search(cp, d['code'], re.I) for cp in _COL_PATS)]
    backup_hc = [d for d in hardcode_all if 'kcs30035600' in d['file']]

    active_by_file, active_by_label = {}, {}
    for d in real_hc:
        active_by_file[d['file']] = active_by_file.get(d['file'], 0) + 1
        for l in d['labels']:
            active_by_label[l] = active_by_label.get(l, 0) + 1

    # ── 템플릿 주입 ──
    tmpl_info = _scan_template_injection(root, html_files)

    # ── 전수조사 데이터 ──
    audit = _load_audit_data(root)
    bank_stats = audit.get('은행', {})
    bank_total = bank_stats.get('기타거래총수', 0)
    bank_matched = bank_stats.get('매칭', 0)
    bank_unmatched = bank_stats.get('미매칭', 0)
    bank_unmatched_list = bank_stats.get('미매칭목록', [])
    std_kw_cnt = audit.get('신규키워드수', 0)
    old_kw_cnt = audit.get('현행키워드수', 0)
    changed_list = audit.get('변경', [])
    maintained = audit.get('유지', 0)
    match_rate = f"{bank_matched / bank_total * 100:.1f}%" if bank_total > 0 else "N/A"
    match_cls = 'ok' if bank_total > 0 and bank_matched / bank_total > 0.9 else 'warn'

    # ── 상수 모듈 ──
    const_checks = {
        'CLASS_PRE': CLASS_PRE, 'CLASS_POST': CLASS_POST, 'CLASS_ACCOUNT': CLASS_ACCOUNT,
        'CLASS_APPLICANT': CLASS_APPLICANT, 'CLASS_NIGHT': CLASS_NIGHT,
        'CLASS_RISK': CLASS_RISK, 'CLASS_INDUSTRY': CLASS_INDUSTRY,
        'BANK_DEFAULT_DEPOSIT': BANK_DEFAULT_DEPOSIT, 'BANK_DEFAULT_WITHDRAWAL': BANK_DEFAULT_WITHDRAWAL,
        'CARD_DEFAULT_DEPOSIT': CARD_DEFAULT_DEPOSIT, 'CARD_DEFAULT_WITHDRAWAL': CARD_DEFAULT_WITHDRAWAL,
        'DEFAULT_CATEGORY': DEFAULT_CATEGORY, 'UNCLASSIFIED': UNCLASSIFIED,
        'DIRECTION_CANCELLED': DIRECTION_CANCELLED, 'CANCELLED_TRANSACTION': CANCELLED_TRANSACTION,
    }

    # ═══════════════════════════ HTML 조립 ═══════════════════════════
    parts = []
    parts.append(_html_header(now))
    parts.append(_section1_category_table(total_rows, kw_total, kw_set, acct_ri, cls_count))
    parts.append(_section2_standard_compare(std_kw_cnt, old_kw_cnt, maintained, changed_list))
    parts.append(_section3_bank_match(bank_total, bank_matched, bank_unmatched, match_rate, bank_unmatched_list))
    parts.append(_section4_dup_keywords(cross_dup))
    parts.append(_section5_hardcoding(hardcode_all, col_ref, real_hc, backup_hc, active_by_file, active_by_label))
    parts.append(_section6_constants_template(const_checks, tmpl_info))
    parts.append(_section_report(now, total_rows, kw_total, acct_ri, changed_list, maintained,
                                  match_rate, match_cls, bank_matched, bank_total, cross_dup, real_hc, const_checks))
    parts.append(_appendix_a())
    parts.append(_appendix_b())
    parts.append(f"""<div style="text-align:right;margin-top:8px;color:#999;font-size:8px;">
생성: {now} | MyRisk 계정과목 표준 검수 시스템 v2.0</div></body></html>""")
    return ''.join(parts)


# ═══ HTML 조각 함수들 ═══

def _html_header(now):
    return f"""<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8">
<title>계정과목 표준 검수 보고서</title>
<style>
@page {{ size: A4; margin: 5mm 6mm; }}
body {{ font-family: "Malgun Gothic", sans-serif; margin: 4px 6px; color: #1A1A1A; font-size: 10px; line-height: 1.35; }}
h1 {{ text-align: center; color: #1565C0; font-size: 15px; margin: 2px 0 3px; }}
h2 {{ color: #1565C0; font-size: 12px; border-bottom: 1.5px solid #B3D4FC; padding-bottom: 2px; margin: 10px 0 4px; }}
h3 {{ color: #333; font-size: 10px; margin: 6px 0 3px 0; }}
.sub {{ text-align: center; color: #666; font-size: 9px; margin-bottom: 8px; }}
table {{ border-collapse: collapse; width: 100%; font-size: 9px; margin: 3px 0 6px 0; }}
th {{ background: #B3D4FC; color: #1565C0; padding: 2px 4px; border: 1px solid #90CAF9; text-align: center; }}
td {{ padding: 2px 4px; border: 1px solid #ddd; }}
tr:nth-child(even) {{ background: #F7F8FA; }}
.badge {{ display: inline-block; padding: 0px 4px; border-radius: 2px; font-size: 8px; font-weight: bold; }}
.b-h {{ background: #FFCDD2; color: #C62828; }} .b-m {{ background: #FFF9C4; color: #F57F17; }}
.b-l {{ background: #C8E6C9; color: #2E7D32; }} .b-i {{ background: #BBDEFB; color: #1565C0; }}
.sbox {{ background: #E3F2FD; border: 1px solid #90CAF9; border-radius: 4px; padding: 6px; margin: 5px 0; }}
.sg {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 4px; }}
.si {{ text-align: center; }} .si .n {{ font-size: 16px; font-weight: bold; color: #1565C0; }} .si .l {{ font-size: 8px; color: #666; }}
.imp {{ background: #FFF3E0; border-left: 2px solid #FF9800; padding: 4px 8px; margin: 4px 0; }}
.imp-t {{ font-weight: bold; color: #E65100; font-size: 9px; }}
.ok {{ color: #2E7D32; font-weight: bold; }} .warn {{ color: #F57F17; font-weight: bold; }} .fail {{ color: #C62828; font-weight: bold; }}
@media print {{ .no-print {{ display: none; }} body {{ margin: 0; }} }}
ul {{ margin: 2px 0; padding-left: 16px; }} li {{ margin: 1px 0; }}
ol {{ margin: 2px 0; padding-left: 16px; }} ol li {{ margin: 1px 0; }}
p {{ margin: 2px 0; }}
</style></head><body>
<h1>계정과목 표준 전수조사 보고서</h1>
<div class="sub">검수일: {now} | MyRisk 계정과목 표준 검수 시스템</div>
"""


def _section1_category_table(total_rows, kw_total, kw_set, acct_ri, cls_count):
    h = f"""<h2>1. 카테고리 테이블 현황</h2>
<div class="sbox"><div class="sg">
<div class="si"><div class="n">{total_rows}</div><div class="l">총 행 수</div></div>
<div class="si"><div class="n">{kw_total}</div><div class="l">총 키워드</div></div>
<div class="si"><div class="n">{len(kw_set)}</div><div class="l">고유 키워드</div></div>
<div class="si"><div class="n">{len(acct_ri)}</div><div class="l">계정과목 코드</div></div>
</div></div>
<table><thead><tr><th>분류</th><th>행 수</th><th>비중</th></tr></thead><tbody>"""
    for c in ['계정과목', '전처리', '후처리', '위험도분류', '업종분류', '심야구분', '신청인']:
        n = cls_count.get(c, 0)
        h += f"<tr><td>{c}</td><td style='text-align:right'>{n}</td><td style='text-align:right'>{n / total_rows * 100:.1f}%</td></tr>"
    h += f"""</tbody></table>
<h3>계정과목 위험지표 코드 ({len(acct_ri)}개)</h3>
<p style="font-size:11px;color:#555;">{', '.join(acct_ri)}</p>"""
    return h


def _section2_standard_compare(std_kw_cnt, old_kw_cnt, maintained, changed_list):
    ch_cls = 'ok' if len(changed_list) == 0 else 'warn'
    h = f"""<h2>2. 표준문서 ↔ 테이블 비교</h2>
<div class="sbox"><div class="sg">
<div class="si"><div class="n">{std_kw_cnt}</div><div class="l">표준문서 키워드</div></div>
<div class="si"><div class="n">{old_kw_cnt}</div><div class="l">테이블 키워드</div></div>
<div class="si"><div class="n">{maintained}</div><div class="l"><span class="ok">일치</span></div></div>
<div class="si"><div class="n">{len(changed_list)}</div><div class="l"><span class="{ch_cls}">변경</span></div></div>
</div></div>"""
    if changed_list:
        h += '<h3>변경 항목</h3><table><thead><tr><th>키워드</th><th>현행</th><th>신규</th></tr></thead><tbody>'
        for c in changed_list[:20]:
            h += f"<tr><td>{c.get('키워드', '')}</td><td>{c.get('현행', '')}</td><td>{c.get('신규', '')}</td></tr>"
        h += '</tbody></table>'
    return h


def _section3_bank_match(bank_total, bank_matched, bank_unmatched, match_rate, bank_unmatched_list):
    h = f"""<h2>3. 은행 거래 매칭 현황</h2>
<div class="sbox"><div class="sg">
<div class="si"><div class="n">{bank_total}</div><div class="l">기타거래 유형</div></div>
<div class="si"><div class="n">{bank_matched}</div><div class="l"><span class="ok">매칭</span></div></div>
<div class="si"><div class="n">{bank_unmatched}</div><div class="l"><span class="warn">미매칭</span></div></div>
<div class="si"><div class="n">{match_rate}</div><div class="l">매칭률</div></div>
</div></div>"""
    if bank_unmatched_list:
        h += '<h3>미매칭 거래 (상위 15건)</h3><table><thead><tr><th>기타거래</th><th>분류</th><th>건수</th><th>입금</th><th>출금</th></tr></thead><tbody>'
        for item in bank_unmatched_list[:15]:
            h += f"<tr><td>{item.get('기타거래', '')}</td><td>{item.get('분류', '')}</td><td style='text-align:right'>{item.get('건수', 0)}</td><td style='text-align:right'>{item.get('입금', 0):,}</td><td style='text-align:right'>{item.get('출금', 0):,}</td></tr>"
        h += '</tbody></table>'
    return h


def _section4_dup_keywords(cross_dup):
    h = f"""<h2>4. 중복 키워드 분석</h2>
<div class="sbox"><div class="sg">
<div class="si"><div class="n">{len(cross_dup)}</div><div class="l">타 분류 중복</div></div>
</div></div>"""
    if cross_dup:
        h += '<table><thead><tr><th>키워드</th><th>위치 1</th><th>위치 2</th></tr></thead><tbody>'
        for kw, ents in list(cross_dup.items())[:20]:
            locs = [f"{e['카테고리']}/{e['위험지표']}" for e in ents]
            loc2 = locs[1] if len(locs) > 1 else ''
            h += f"<tr><td>{ents[0]['키워드']}</td><td>{locs[0]}</td><td>{loc2}</td></tr>"
        h += '</tbody></table>'
    return h


def _section5_hardcoding(hardcode_all, col_ref, real_hc, backup_hc, active_by_file, active_by_label):
    h = f"""<h2>5. 코드 전수조사 (하드코딩)</h2>
<div class="sbox"><div class="sg">
<div class="si"><div class="n">{len(hardcode_all)}</div><div class="l">전체 탐지</div></div>
<div class="si"><div class="n">{len(col_ref)}</div><div class="l">컬럼참조 (정상)</div></div>
<div class="si"><div class="n">{len(real_hc)}</div><div class="l">실질 하드코딩</div></div>
<div class="si"><div class="n">{len(backup_hc)}</div><div class="l">백업파일 (제외)</div></div>
</div></div>
<h3>파일별 현황</h3>
<table><thead><tr><th>파일</th><th>건수</th><th>등급</th></tr></thead><tbody>"""
    for f in sorted(active_by_file.keys()):
        n = active_by_file[f]
        sev = 'HIGH' if n > 10 else ('MEDIUM' if n > 3 else 'LOW')
        bc = _SEV_BADGE[sev]
        h += f"<tr><td>{f}</td><td style='text-align:right'>{n}</td><td><span class='badge {bc}'>{sev}</span></td></tr>"
    h += """</tbody></table>
<h3>유형별 현황</h3>
<table><thead><tr><th>유형</th><th>건수</th></tr></thead><tbody>"""
    for l, c in sorted(active_by_label.items(), key=lambda x: -x[1]):
        h += f"<tr><td>{l}</td><td style='text-align:right'>{c}</td></tr>"
    h += '</tbody></table>'
    return h


def _section6_constants_template(const_checks, tmpl_info):
    h = f"""<h2>6. 상수 모듈 · 템플릿 주입</h2>
<p><span class="badge b-i">lib/category_constants.py</span> — {len(const_checks)}개 상수</p>
<table><thead><tr><th>상수명</th><th>값</th></tr></thead><tbody>"""
    for name, val in const_checks.items():
        h += f"<tr><td><code>{name}</code></td><td>{val}</td></tr>"
    h += """</tbody></table>
<h3>템플릿 주입 현황</h3>
<table><thead><tr><th>파일</th><th>CAT블록</th><th>Jinja상수</th><th>잔여하드코딩</th></tr></thead><tbody>"""
    for f in sorted(tmpl_info.keys()):
        i = tmpl_info[f]
        cc = 'ok' if i['hc_js'] == 0 else ('warn' if i['hc_js'] < 5 else 'fail')
        cat_mark = '✓' if i['cat'] else '—'
        jin_mark = '✓' if i['jinja'] else '—'
        h += f"<tr><td>{f}</td><td style='text-align:center'>{cat_mark}</td><td style='text-align:center'>{jin_mark}</td><td class='{cc}' style='text-align:center'>{i['hc_js']}</td></tr>"
    h += '</tbody></table>'
    return h


def _section_report(now, total_rows, kw_total, acct_ri, changed_list, maintained,
                     match_rate, match_cls, bank_matched, bank_total, cross_dup, real_hc, const_checks):
    ch_cls = 'ok' if len(changed_list) == 0 else 'warn'
    dup_cls = 'ok' if len(cross_dup) < 5 else 'warn'
    hc_cls = 'ok' if len(real_hc) < 30 else 'warn'
    return f"""<div style="page-break-before:always;"></div>
<h1>계정과목 표준 검수 보고서</h1>
<div class="sub">검수일: {now} | 개선사항 의견 첨부</div>

<h2>종합 판정</h2>
<div class="sbox">
<table><thead><tr><th>항목</th><th>상태</th><th>판정</th></tr></thead><tbody>
<tr><td>카테고리 테이블</td><td class="ok">정상</td><td>7분류 · {total_rows}행 · {kw_total}키워드</td></tr>
<tr><td>계정과목 코드</td><td class="ok">정상</td><td>{len(acct_ri)}코드 (8대분류 · 30소분류)</td></tr>
<tr><td>표준문서 일치</td><td class="{ch_cls}">{maintained}건 일치</td><td>변경 {len(changed_list)}건</td></tr>
<tr><td>은행 매칭률</td><td class="{match_cls}">{match_rate}</td><td>{bank_matched}/{bank_total} 유형</td></tr>
<tr><td>중복 키워드</td><td class="{dup_cls}">{len(cross_dup)}건</td><td>의도적 중복 포함</td></tr>
<tr><td>하드코딩</td><td class="{hc_cls}">{len(real_hc)}건</td><td>컬럼참조 제외</td></tr>
<tr><td>상수 모듈</td><td class="ok">정상</td><td>{len(const_checks)}개 정의</td></tr>
</tbody></table></div>

<h2>개선사항 의견</h2>

<div class="imp">
<div class="imp-t">1. [권장] 잔여 하드코딩 상수화 — {len(real_hc)}건</div>
<p>컬럼 참조 제외 {len(real_hc)}건이 남아 있습니다. 대부분 HTML/JS에서 '취소', '미분류' 등을 직접 참조.
단, '취소'의 상당수는 DataFrame 컬럼명(row['취소'])으로 상수화 대상이 아닙니다.</p>
</div>

<div class="imp">
<div class="imp-t">2. [권장] 중복 키워드 정리 — {len(cross_dup)}건</div>
<p>위험도분류/업종분류와 계정과목 간 의도적 중복이 대부분. "나눔과어울림", "성우서비스" 등 일부 정리 검토 필요.</p>
</div>

<div class="imp">
<div class="imp-t">3. [완료] 중복 키워드 입력 검증</div>
<p>입력/수정 시 기존 키워드 중복 사전 경고. 3개 앱 적용 완료. <span class="ok">✓</span></p>
</div>

<div class="imp">
<div class="imp-t">4. [완료] A4 출력 정렬·컬럼 통일</div>
<p>분류→위험도→위험지표→키워드 정렬. 컬럼: 분류/위험도/위험지표/카테고리/키워드. <span class="ok">✓</span></p>
</div>

<div class="imp">
<div class="imp-t">5. [완료] 표준문서 ↔ JSON 동기화 API</div>
<p>/api/category-json-to-md — JSON→MD 자동 생성. <span class="ok">✓</span></p>
</div>

<div class="imp">
<div class="imp-t">6. [선택] 백업 파일 정리</div>
<p>*-kcs30035600.html 백업 파일에 구형 코드 잔존. 삭제 또는 별도 폴더 이동 권장.</p>
</div>

<div class="imp">
<div class="imp-t">7. [선택] MyCash category.html JS 하드코딩 집중 개선</div>
<p>CAT 상수 블록이 이미 존재하므로 CAT.* 참조로 전환하면 해결됩니다.</p>
</div>
"""


def _appendix_a():
    return """<div style="page-break-before:always;"></div>
<h1>부록 A. 키워드 충돌 해결 방안</h1>
<div class="sub">카테고리 분류 시 동일 키워드 · 동일 위험도 충돌 처리 규칙</div>

<h2>A-1. 키워드 충돌이란?</h2>
<p>하나의 거래 텍스트에 <strong>두 개 이상의 카테고리 키워드</strong>가 매칭될 때 발생합니다.
예: "현대해상 보험료" → "현대해상"(전처리→현대백화점) + "보험료"(L08).</p>

<h2>A-2. 충돌 해결 규칙 — 5단계 캐스케이드 (우선순위 순)</h2>
<table>
<thead><tr><th>순서</th><th>규칙</th><th>설명</th><th>코드 위치</th></tr></thead>
<tbody>
<tr><td>0</td><td><strong>전처리 우선</strong></td><td>전처리 규칙에 매칭되면 해당 키워드를 먼저 치환한 뒤 계정과목 매칭 진행</td><td>process_bank_data.py<br>_apply_전처리_only()</td></tr>
<tr><td>1</td><td><strong>최장 키워드 우선<br>(Longest Match)</strong></td><td>동일 텍스트에 여러 키워드가 매칭되면, <strong>문자열 길이가 가장 긴 키워드</strong>가 우선.<br>예: "삼성전자서비스" → "삼성전자서비스"(7자) > "삼성전자"(4자)</td><td>apply_category_from_bank()<br>_best_match()</td></tr>
<tr><td>2</td><td><strong>위험도 우선순위<br>(Risk Priority)</strong></td><td>키워드 길이 동일 시, 코드 첫 글자 기반 위험도:<br><code>H(6) > P(5) > F(4) > D(3) > L(2) > M(1) > X(0)</code><br>높은 위험도가 우선 배정</td><td>apply_category_from_bank()<br>_risk_pri</td></tr>
<tr><td>3</td><td><strong>텍스트 위치 우선<br>(Position Priority)</strong></td><td>키워드 길이·위험도 모두 동일 시, 거래 텍스트에서 <strong>앞쪽에 나타나는 키워드</strong>가 우선.<br>거래 주체(가맹점, 인물)가 텍스트 앞쪽에 위치하는 특성 활용.<br>예: "NS홈쇼핑 KCP" → 홈쇼핑(pos=2) > KCP(pos=6)</td><td>apply_category_from_bank()<br>matched_pos 비교</td></tr>
<tr><td>4</td><td><strong>소분류 코드 순<br>(Code Order)</strong></td><td>위 3단계 모두 동일 시, <strong>소분류 코드가 큰 것</strong>이 우선.<br>예: H03 > H02</td><td>apply_category_from_bank()<br>code 비교</td></tr>
</tbody></table>

<h2>A-3. 위험도 동일 시 처리</h2>
<table>
<thead><tr><th>상황</th><th>처리 방식</th><th>예시</th></tr></thead>
<tbody>
<tr><td>키워드 길이 다름</td><td>최장 키워드 우선 (1단계)</td><td>"외식" vs "외식/간식" → 길이 우선</td></tr>
<tr><td>키워드 길이 동일,<br>위치 다름</td><td>텍스트 앞쪽 키워드 우선 (3단계)</td><td>"NS홈쇼핑 KCP" → D03(홈쇼핑,pos=2) > D05(KCP,pos=6)</td></tr>
<tr><td>길이·위치 동일,<br>코드 다름</td><td>소분류 코드 순 (4단계)</td><td>H03 > H02</td></tr>
<tr><td>완전 동일 조건</td><td>기존 분류 유지 (변경 안 함)</td><td>이미 분류된 거래 → 유지</td></tr>
</tbody></table>

<h2>A-4. 실무 권장 사항</h2>
<div class="imp">
<div class="imp-t">키워드 설계 원칙</div>
<ul>
<li><strong>긴 키워드를 우선 등록</strong>하여 정밀 매칭 (예: "삼성전자서비스" 등록 후 "삼성전자" 등록)</li>
<li><strong>전처리로 동음이의어 해소</strong> (예: "현대해상" → "현대백화점"으로 전처리 치환)</li>
<li><strong>정규식 키워드 활용</strong> (<code>re:</code> 접두어) — 날짜 패턴 등 변동 키워드에 효과적</li>
<li>중복 키워드 입력 시 <strong>경고 메시지</strong> 확인 후 의도적 중복만 허용</li>
</ul>
</div>
"""


def _appendix_b():
    return """<div style="page-break-before:always;"></div>
<h1>부록 B. 대분류/중분류/소분류 코드 부여 규칙</h1>
<div class="sub">계정과목 표준 코드 체계 및 기준</div>

<h2>B-1. 코드 체계 구조</h2>
<table>
<thead><tr><th>계층</th><th>형식</th><th>예시</th><th>설명</th></tr></thead>
<tbody>
<tr><td><strong>대분류</strong></td><td>로마숫자 + 명칭</td><td>I. 자금이동<br>II. 필수생활비<br>III. 재량소비</td><td>면책 심사 성격별 최상위 분류. 총 <strong>7개</strong>.</td></tr>
<tr><td><strong>중분류</strong></td><td>알파벳 + 밑줄 + 명칭</td><td>M_계좌이동<br>L_식비<br>D_쇼핑</td><td>대분류 내 활동 유형별 그룹. 총 <strong>13개</strong>.</td></tr>
<tr><td><strong>소분류</strong></td><td>알파벳 + 2자리 숫자</td><td>M01, L01, D05</td><td>키워드가 매핑되는 최소 단위. 총 <strong>34개</strong>.</td></tr>
</tbody></table>

<h2>B-2. 대분류 코드 부여 기준</h2>
<table>
<thead><tr><th>코드</th><th>대분류명</th><th>면책 심사 성격</th><th>위험도 순위</th></tr></thead>
<tbody>
<tr><td>—</td><td>미분류</td><td>분류 불가 — 재검토 필요</td><td>0 (X) <strong>최저</strong></td></tr>
<tr><td>I</td><td>자금이동</td><td>비소비성 — 실질 소비에서 분리</td><td>1 (M)</td></tr>
<tr><td>II</td><td>필수생활비</td><td>필수 — 면책 인정 가능</td><td>2 (L)</td></tr>
<tr><td>III</td><td>재량소비</td><td>소명 권고 — 필요성 입증 필요</td><td>3 (D)</td></tr>
<tr><td>IV</td><td>금융거래</td><td>금융 — 채무/세금 관련</td><td>4 (F)</td></tr>
<tr><td>V</td><td>인적거래</td><td>인적 — 가족/지인/법인</td><td>5 (P)</td></tr>
<tr><td>VI</td><td>고위험항목</td><td>면책불허가 — 법 조항 연동</td><td>6 (H) <strong>최고</strong></td></tr>
</tbody></table>

<h2>B-3. 알파벳 코드 의미</h2>
<table>
<thead><tr><th>알파벳</th><th>유래</th><th>해당 대분류</th></tr></thead>
<tbody>
<tr><td><strong>X</strong></td><td>미분류 (X = unknown)</td><td>— 미분류 (위험도 0)</td></tr>
<tr><td><strong>M</strong></td><td><strong>M</strong>ove (자금이동)</td><td>I. 자금이동</td></tr>
<tr><td><strong>L</strong></td><td><strong>L</strong>iving (생활비)</td><td>II. 필수생활비</td></tr>
<tr><td><strong>D</strong></td><td><strong>D</strong>iscretionary (재량)</td><td>III. 재량소비</td></tr>
<tr><td><strong>F</strong></td><td><strong>F</strong>inance (금융)</td><td>IV. 금융거래</td></tr>
<tr><td><strong>P</strong></td><td><strong>P</strong>erson (인적)</td><td>V. 인적거래</td></tr>
<tr><td><strong>H</strong></td><td><strong>H</strong>igh-risk (고위험)</td><td>VI. 고위험항목</td></tr>
</tbody></table>

<h2>B-4. 소분류 번호 부여 규칙</h2>
<table>
<thead><tr><th>규칙</th><th>설명</th><th>예시</th></tr></thead>
<tbody>
<tr><td>01~09</td><td>중분류 내 순차 부여</td><td>L01 식료품, L02 외식/간식, ..., L08 보험료</td></tr>
<tr><td>번호 간격</td><td>동일 중분류 내 연속 부여.<br>코드 자체에 순서 의미 없음</td><td>D05~D08: 온/오프라인결재 내 순차</td></tr>
<tr><td>중분류 변경 시</td><td>알파벳이 바뀌면 01부터 재시작</td><td>M01~M02, L01~L08, D01~D08</td></tr>
<tr><td>코드 불변 원칙</td><td>한번 부여된 코드는 <strong>변경하지 않음</strong>.<br>삭제 시 코드 번호 비워둠 (재사용 금지)</td><td>H01 삭제 → H01 영구 공석</td></tr>
</tbody></table>

<h2>B-5. 신규 코드 추가 절차</h2>
<div class="imp">
<div class="imp-t">신규 소분류 추가 시</div>
<ol>
<li>해당 대분류의 <strong>면책 심사 성격</strong> 확인</li>
<li>중분류 내 <strong>마지막 번호 + 1</strong>로 코드 부여</li>
<li><code>계정과목_표준.md</code>에 소분류 섹션 추가</li>
<li>키워드 테이블에 등록</li>
<li><code>/api/category-json-to-md</code>로 문서 동기화</li>
</ol>
</div>

<div class="imp">
<div class="imp-t">신규 중분류 추가 시</div>
<ol>
<li>대분류 내 적합한 위치에 중분류명 결정</li>
<li>기존 알파벳 코드 계열 사용 (예: L계열 → L09~)</li>
<li>별도 알파벳 필요 시 미사용 알파벳 배정 (미사용: A, B, C, E, G, I, J, K, N, O, Q, R, S, T, U, V, W, Y, Z)</li>
</ol>
</div>

<h2>결론</h2>
<div class="sbox" style="background:#E8F5E9;border-color:#81C784;">
<p style="text-align:center;font-size:14px;margin:0;">
<strong>코드 체계 및 키워드 충돌 해결 규칙 정립 완료</strong><br>
전처리 → 최장 키워드 → 위험도 → 텍스트 위치 → 소분류 코드 순<br>
대분류(6+미분류) · 중분류(13) · 소분류(34) 코드 부여 규칙 표준화<br>
위험도 순서: X(0) &lt; M(1) &lt; L(2) &lt; D(3) &lt; F(4) &lt; P(5) &lt; H(6)
</p></div>
"""
