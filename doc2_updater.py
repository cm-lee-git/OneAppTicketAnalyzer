"""
Document 2: 신규/개선 전체 현황 — 새 페이지 생성 방식
원본(71237682) 구조와 동일하게 생성:
  Section 0: 스크리닝 기준 (정적)
  Section 1: 전체 현황 + 회차별 트래킹 + 마감 히스토리 expand
  Section 2: KR 티켓 히스토리 (승인/보류/반려 × Pre-BRD/회차별 expand)
  Section 3: EU 티켓 히스토리
  Section 4: HQ GBCXD 및 타부문 티켓 히스토리
"""
import re as _re_module
from collections import defaultdict
from datetime import datetime

from confluence_client import ConfluenceClient, HmgConfluenceClient
from config import DOC_PAGE_IDS, HMG_DOC2_PAGE_ID
from cycle import cycle_label, get_cycle_bounds, get_active_cycle

JIRA_BROWSE = "https://hmg.atlassian.net/browse"
MASTER_TITLE = "신규/개선 전체 현황 (AI 생성)"

# Feature 1: 참조 문서 복제 — HMG Confluence에서 기존 티켓 행 읽기
DOC2_REF_PAGE_ID = HMG_DOC2_PAGE_ID  # HMG hmg.atlassian.net 참조 페이지

# ── closed/resolved 필터 ─────────────────────────────────────────
_CLOSED_RE = _re_module.compile(r'\b(resolved?|clos(?:e|ed))\b', _re_module.IGNORECASE)


def _is_closed_summary(text: str) -> bool:
    """Ticket Summary에 resolved/resolve/closed/close 포함 여부 (대소문자 무관)."""
    return bool(_CLOSED_RE.search(text or ''))


def _count_effective_cols_first_row(rows_html: str) -> int:
    """ref rows HTML 첫 번째 <tr>에서 colspan 반영 실질 컬럼 수 반환 (표 구조 검증용)."""
    from bs4 import BeautifulSoup as _bsBS
    soup = _bsBS(rows_html, 'html.parser')
    first_tr = soup.find('tr')
    if not first_tr:
        return 0
    cells = first_tr.find_all(['td', 'th'])
    return sum(int(c.get('colspan', 1)) for c in cells)


def _key_link(key: str) -> str:
    """Jira 티켓 키 → 하이퍼링크 HTML."""
    if not key:
        return ""
    return f'<a href="{JIRA_BROWSE}/{key}">{key}</a>'

# ── 상수 ────────────────────────────────────────────────────────
SCORE_LABELS = [
    "시급성", "사업 성과 기여", "고객 경험 영향도",
    "운영 효율화", "글로벌 파급 범위", "플랫폼 운영 전략 연계도",
]
SCORE_KEYS = [
    "urgency", "business_performance", "customer_experience",
    "operational_efficiency", "global_reach", "platform_strategy",
]

REGION_LABEL = {"KR": "RHQ KR", "EU": "RHQ EU", "HQ": "HQ GBCXD 및 타부문"}

# 각 섹션에 포함되는 region 값 (Global → KR+EU 모두)
_KR_REGIONS  = ("KR",)
_EU_REGIONS  = ("EU",)
_HQ_REGIONS  = ("HQ",)
APPROVAL_LABEL = {"Approved": "승인", "보류": "보류", "반려": "반려"}

# 표 셀 배경 색상 (원본 71237682 기준)
GREY       = "#b3bac5"   # 헤더/라벨 배경
LIGHT_GREY = "#f4f5f7"   # 종합 현황 데이터 셀
KR_BLUE    = "#4c9aff"   # KR 열 헤더
EU_TEAL    = "#79e2f2"   # EU 열 헤더
HQ_GREEN   = "#57d9a3"   # HQ 열 헤더
TOTAL_BLUE  = "#deebff"   # 트래킹 Total 행 데이터

# 셀프/AI 일치·불일치 셀 배경색 (승인 테이블 항목 분포 3열)
MATCH_BG    = "#e3fcef"   # 일치 (초록)
MISMATCH_BG = "#ffebe6"   # 불일치 (빨강)

# 참조 문서(71237682) 기준 colgroup 너비
CW = {
    "section1_overall":   [107, 159, 133, 133, 133, 133],      # 6열: 전체현황
    "section1_tracking":  [122, 108, 87, 92, 71, 90, 85, 106,  # 19열: 트래킹
                           83, 98, 81, 92, 92, 106, 87, 83, 92, 92, 92],
    "kr_approved":        [104, 93, 101, 167, 93, 93, 93,       # 13열: KR 승인 (항목|셀프|AI)
                           291, 93, 90, 110, 93, 104],
    "kr_pending":         [208, 110, 110, 110, 110, 110,        # 12열: KR 보류
                           110, 110, 110, 180, 180, 110],
    "kr_rejected":        [200, 132, 132, 135, 132, 132,        # 9열: KR 반려
                           132, 132, 250],
    "eu_approved":        [198, 122, 122, 122, 122, 122,        # 12열: EU 승인 (항목|셀프|AI)
                           122, 122, 90, 110, 122, 122],
    "eu_pending":         [198, 122, 122, 122, 122, 122,        # 11열: EU 보류
                           122, 122, 155, 155, 110],
    "eu_rejected":        [198, 122, 122, 122, 122, 122,        # 8열: EU 반려
                           122, 122, 250],
    "history":            [122, 108, 87, 92, 71, 90, 85, 106,  # 13열: 마감 히스토리
                           83, 98, 81, 92, 92],
}


# ── HTML 빌더 헬퍼 ───────────────────────────────────────────────
def _colgroup(widths):
    cols = "".join(f'<col style="width: {w}.0px;"/>' for w in widths)
    return f"<colgroup>{cols}</colgroup>"


def _table(widths, rows_html):
    cg = _colgroup(widths) if widths else ""
    return f"<table>{cg}<tbody>{''.join(rows_html)}</tbody></table>"


def _th(*headers):
    return "<tr>" + "".join(f"<th><p><strong>{h}</strong></p></th>" for h in headers) + "</tr>"


def _th_span(cells):
    """cells: list of (text, rowspan, colspan)"""
    parts = []
    for text, rs, cs in cells:
        attrs = (f' rowspan="{rs}"' if rs > 1 else "") + (f' colspan="{cs}"' if cs > 1 else "")
        parts.append(f"<th{attrs}><p><strong>{text}</strong></p></th>")
    return "<tr>" + "".join(parts) + "</tr>"


def _td(*cells, style=""):
    st = f' style="{style}"' if style else ""
    return "<tr>" + "".join(f"<td{st}><p>{c}</p></td>" for c in cells) + "</tr>"


def _p(text):
    return f"<p>{text}</p>"


def _p_bold(text):
    return f"<p><strong>{text}</strong></p>"


def _h2(text):
    return f"<h2>{text}</h2>"


def _h3(text):
    return f"<h3>{text}</h3>"


def _expand(title, content):
    return (
        f'<ac:structured-macro ac:name="expand">'
        f'<ac:parameter ac:name="title">{title}</ac:parameter>'
        f'<ac:rich-text-body>{content}</ac:rich-text-body>'
        f'</ac:structured-macro>'
    )


def _panel(bg_color, content):
    return (
        f'<ac:structured-macro ac:name="panel" ac:schema-version="1">'
        f'<ac:parameter ac:name="bgColor">{bg_color}</ac:parameter>'
        f'<ac:rich-text-body>{content}</ac:rich-text-body>'
        f'</ac:structured-macro>'
    )


def _c(tag, text, bg=None, rs=None, cs=None, bold_white=False, bold=False):
    """배경색·rowspan·colspan·흰 볼드·볼드 지원 셀 빌더."""
    attrs = ""
    if rs: attrs += f' rowspan="{rs}"'
    if cs: attrs += f' colspan="{cs}"'
    if bg: attrs += f' data-highlight-colour="{bg}"'
    if bold_white and text:
        content = f'<strong><span style="color: rgb(255,255,255);">{text}</span></strong>'
    elif bold and text:
        content = f'<strong>{text}</strong>'
    else:
        content = text
    return f'<{tag}{attrs}><p style="text-align: center;">{content}</p></{tag}>'


def _track_label(cycle_n):
    """트래킹 표 데이터 행 첫 셀 라벨: 'N회차 (M/D~M/D)' 형식."""
    if cycle_n == 0:
        from cycle import ANCHOR
        from datetime import date, timedelta
        end = ANCHOR - timedelta(days=1)
        return f"Pre-BRD (1/1~{end.month}/{end.day})"
    start, end = get_cycle_bounds(cycle_n)
    return f"{cycle_n}회차 ({start.month}/{start.day}~{end.month}/{end.day})"


def _no_tickets(prebrd=False):
    return _p("해당 사항 없음" if prebrd else "해당 티켓 없음")


def _score_mark(value):
    try:
        return "O" if float(value) > 0 else "X"
    except (ValueError, TypeError):
        return "X"


def _cycle_expand_title(cycle_n):
    start, end = get_cycle_bounds(cycle_n)
    return f"#Cycle {cycle_n} ({start.year}. {start.month}/{start.day}~{end.month}/{end.day})"


def _fill_missing_cycles(history_entries: list, active_cycle: int) -> list:
    """이전 회차 expand 목록에 누락된 회차를 '해당 티켓 없음'으로 채워 반환.
    Pre-BRD + Cycle 1 ~ active_cycle-1 전체를 순서대로 반환.
    """
    existing = {title: body for title, body in history_entries}
    result = []
    result.append(("Pre-BRD", existing.get("Pre-BRD", _no_tickets(prebrd=True))))
    for cn in range(1, active_cycle):
        title = _cycle_expand_title(cn)
        result.append((title, existing.get(title, _no_tickets())))
    return result


def _reporter_html(reporter: str, initiator: str, rs: int = 6) -> str:
    """Reporter + 발의자 셀 HTML."""
    content = f"<p>{reporter}</p>"
    if initiator:
        content += f"<p><em>(발의: {initiator})</em></p>"
    return f'<td rowspan="{rs}">{content}</td>'


def _effective_approval(ticket):
    """분석 결과(rejection_code/hold_code)를 우선 반영한 최종 승인 상태.
    Pre-BRD(cycle_number == 0) 티켓은 hold_code 판단 대상 제외.
    """
    if ticket.get("rejection_code"):
        return "반려"
    is_prebrd = ticket.get("cycle_number", 0) == 0
    if ticket.get("hold_code") and not is_prebrd:
        return "보류"
    return ticket.get("brd_approval", "")


def _load_ref_rows_doc2(hmg_client: HmgConfluenceClient) -> dict[str, str]:
    """HMG Confluence 참조 문서(DOC2_REF_PAGE_ID)에서 티켓별 행 HTML 추출.
    Returns: {ticket_key: rows_html_str}
    참조 실패 시 빈 dict 반환 → 모든 티켓 새로 생성.
    """
    import re as _re2
    from bs4 import BeautifulSoup as _BS
    _pat = _re2.compile(r'\b(KCCIVOC|KEUVOCOP|CCIPRJ)-\d+\b')
    try:
        html, _, _ = hmg_client.get_page_storage(DOC2_REF_PAGE_ID)
        soup = _BS(html, 'html.parser')
        result: dict[str, str] = {}
        from collections import defaultdict as _dd
        # 1패스: 키별 후보 수집 — <li> 내 참조 링크 제외, rowspan 기록
        all_matches: dict[str, list] = _dd(list)
        for a in soup.find_all('a', href=True):
            if a.find_parent('li'):
                continue  # 내용/배경/문제 열의 참조 링크 건너뜀
            href = a.get('href', '')
            text = a.get_text(strip=True)
            m = _pat.search(href) or _pat.search(text)
            if not m:
                continue
            key = m.group()
            tr = a.find_parent('tr')
            if not tr:
                continue
            first_td = tr.find(['td', 'th'])
            try:
                rowspan = int(first_td.get('rowspan', '1')) if first_td else 1
            except (ValueError, TypeError):
                rowspan = 1
            all_matches[key].append((rowspan, tr))
        # 2패스: 키별로 rowspan이 가장 큰 행(= 티켓 블록 첫 행) 선택
        for key, matches in all_matches.items():
            best_rowspan, best_tr = max(matches, key=lambda x: x[0])
            rows = [str(best_tr)]
            sib = best_tr.find_next_sibling('tr')
            for _ in range(best_rowspan - 1):
                if sib:
                    rows.append(str(sib))
                    sib = sib.find_next_sibling('tr')
            result[key] = ''.join(rows)
        print(f"  [ref_doc2] HMG 참조 문서 {DOC2_REF_PAGE_ID}에서 {len(result)}건 추출")
        return result
    except Exception as e:
        print(f"  [ref_doc2] HMG 참조 문서 조회 실패 → {e} (전체 새로 생성)")
        return {}


# ── history expand 블록 지원 ──────────────────────────────────────

def _load_ref_history_doc2(hmg_client: HmgConfluenceClient, current_cycle: int) -> dict:
    """HMG doc2 참조 페이지에서 current_cycle 미만의 expand 블록을 지역/승인별로 추출.

    Returns: {
        'KR': {'Approved': [(cycle_title, body_html), ...], '보류': [...], '반려': [...]},
        'EU': {...},
        'HQ': {...}
    }
    """
    import re as _re

    result = {r: {'Approved': [], '보류': [], '반려': []}
              for r in ('KR', 'EU', 'HQ')}

    try:
        html, _, _ = hmg_client.get_page_storage(DOC2_REF_PAGE_ID)
    except Exception as e:
        print(f"  [ref_history] HMG 참조 문서 조회 실패: {e}")
        return result

    # Confluence storage format 패턴
    EXPAND_PAT = _re.compile(
        r'<ac:structured-macro[^>]*ac:name=["\']expand["\'][^>]*>(.*?)</ac:structured-macro>',
        _re.DOTALL | _re.IGNORECASE,
    )
    TITLE_PAT = _re.compile(
        r'<ac:parameter[^>]*ac:name=["\']title["\'][^>]*>(.*?)</ac:parameter>',
        _re.DOTALL,
    )
    BODY_PAT = _re.compile(r'<ac:rich-text-body>(.*?)</ac:rich-text-body>', _re.DOTALL)
    CYCLE_NUM_PAT = _re.compile(r'Cycle\s+(\d+)', _re.I)

    REGION_MAP = [
        ('KR 티켓 히스토리', 'KR'),
        ('EU 티켓 히스토리', 'EU'),
        ('HQ GBCXD 및 타부문 티켓 히스토리', 'HQ'),
    ]
    APPROVAL_MAP = [
        ('승인 티켓', 'Approved'),
        ('보류 티켓', '보류'),
        ('반려 티켓', '반려'),
    ]

    for expand_m in EXPAND_PAT.finditer(html):
        macro_inner = expand_m.group(1)
        macro_start = expand_m.start()
        preceding = html[:macro_start]

        # 직전 h2 → region
        h2_matches = list(_re.finditer(r'<h2[^>]*>(.*?)</h2>', preceding, _re.DOTALL))
        if not h2_matches:
            continue
        h2_text = _re.sub(r'<[^>]+>', '', h2_matches[-1].group(1))
        region = next((r for kw, r in REGION_MAP if kw in h2_text), None)
        if not region:
            continue

        # h2 이후 직전 strong → approval
        h2_end_pos = h2_matches[-1].end()
        after_h2 = preceding[h2_end_pos:]
        strong_texts = list(_re.finditer(r'<strong[^>]*>(.*?)</strong>', after_h2, _re.DOTALL))
        approval = None
        for sm in reversed(strong_texts):
            txt = _re.sub(r'<[^>]+>', '', sm.group(1)).strip()
            for kw, appr in APPROVAL_MAP:
                if kw in txt:
                    approval = appr
                    break
            if approval:
                break
        if not approval:
            continue

        # Title 추출
        title_m = TITLE_PAT.search(macro_inner)
        if not title_m:
            continue
        title = _re.sub(r'<[^>]+>', '', title_m.group(1)).strip()

        # 현재 회차 이상 제외 (직접 계산으로 대체)
        cycle_m = CYCLE_NUM_PAT.search(title)
        if cycle_m and int(cycle_m.group(1)) >= current_cycle:
            continue

        # Body 추출
        body_m = BODY_PAT.search(macro_inner)
        if not body_m:
            continue
        body_html = body_m.group(1).strip()

        result[region][approval].append((title, body_html))

    total = sum(len(v) for r in result.values() for v in r.values())
    print(f"  [ref_history] {total}개 expand 블록 추출 ({current_cycle}회차 미만)")
    return result


def _update_summary_cell(cell_tag, new_summary_ko: str) -> bool:
    """내용 <td> 내 <Summary> 이후 첫 <ul>을 new_summary_ko로 교체. 성공 시 True."""
    from bs4 import BeautifulSoup as _BS
    for p_tag in cell_tag.find_all('p'):
        strong = p_tag.find('strong')
        if not strong or 'Summary' not in (strong.get_text() or ''):
            continue
        ul = p_tag.find_next_sibling('ul')
        if ul and ul.find_parent() == p_tag.find_parent():
            lines = [l.strip() for l in new_summary_ko.split('\n') if l.strip()] or [new_summary_ko.strip()]
            new_ul = _BS('<ul>' + ''.join(f'<li>{l}</li>' for l in lines) + '</ul>',
                         'html.parser').find('ul')
            ul.replace_with(new_ul)
            return True
    return False


def _rebuild_ticket_rows(t: dict, has_cycle_col: bool, table_type: str) -> str:
    """단일 티켓 HTML 행을 현재 코드 기준으로 재생성. 실패 시 ''."""
    if not t:
        return ''
    key = t.get('key', '')
    scores = t.get('scores', {})

    def td_rs(text, rs=6):
        return f'<td rowspan="{rs}"><p>{text}</p></td>'

    cc = (f'<td rowspan="6"><p>{cycle_label(t.get("cycle_number", 0))}</p></td>'
          if has_cycle_col else '')

    score_rows = ''.join(
        f'<tr><td><p>{SCORE_LABELS[i]}</p></td>'
        f'<td><p>—</p></td>'
        f'<td><p>{_score_mark(scores.get(SCORE_KEYS[i], 0))}</p></td></tr>'
        for i in range(1, 6)
    )

    if table_type == 'approved':
        is_prebrd = (t.get('cycle_number', 0) == 0)
        feature_label = t.get('feature_label') or '기존 기능 개선'
        parts = []
        for label, field in [('Summary', 'summary_ko'), ('배경', 'background'),
                              ('문제', 'problem'), (feature_label, 'feature')]:
            val = t.get(field) or (t.get('summary', '') if field == 'summary_ko' else '')
            if val:
                lines = [l.strip() for l in val.split('\n') if l.strip()] or [val.strip()]
                parts.append(f'<p><strong>&lt;{label}&gt;</strong></p><ul>'
                             + ''.join(f'<li>{l}</li>' for l in lines) + '</ul>')
        content_html = ''.join(parts)
        priority = str(sum(1 for k in SCORE_KEYS[1:] if float(scores.get(k, 0)) > 0))
        brd_val = '' if is_prebrd else APPROVAL_LABEL.get(_effective_approval(t), '')
        row1 = (
            f'<tr>{td_rs("1")}{cc}'
            f'<td rowspan="6"><p>{_key_link(key)}</p></td>'
            f'{td_rs(t.get("summary", ""))}'
            f'{_reporter_html(t.get("reporter", ""), t.get("initiator", ""))}'
            f'{td_rs(t.get("created", ""))}{td_rs(t.get("due_date", ""))}'
            f'<td rowspan="6">{content_html}</td>'
            f'<td><p>{SCORE_LABELS[0]}</p></td>'
            f'<td><p>—</p></td>'
            f'<td><p>{_score_mark(scores.get(SCORE_KEYS[0], 0))}</p></td>'
            f'{td_rs(priority)}{td_rs(brd_val)}</tr>'
        )
        return row1 + score_rows

    elif table_type == 'pending':
        hold_code = t.get('hold_code') or ''
        reason = t.get('hold_reason') or (t.get('background', '')[:150] if hold_code else '')
        return (
            f'<tr><td><p>1</p></td>{cc}'
            f'<td><p>{_key_link(key)}</p></td>'
            f'<td><p>{t.get("summary", "")}</p></td>'
            f'{_reporter_html(t.get("reporter", ""), t.get("initiator", ""), rs=1)}'
            f'<td><p>{t.get("created", "")}</p></td><td><p>{t.get("due_date", "")}</p></td>'
            f'<td><p>{hold_code}</p></td><td><p>{reason}</p></td>'
            f'<td></td><td></td><td></td></tr>'
        )

    elif table_type == 'rejected':
        rej_code = t.get('rejection_code') or ''
        reason = t.get('rejection_reason') or (t.get('problem', '')[:150] if rej_code else '')
        return (
            f'<tr><td><p>1</p></td>{cc}'
            f'<td><p>{_key_link(key)}</p></td>'
            f'<td><p>{t.get("summary", "")}</p></td>'
            f'{_reporter_html(t.get("reporter", ""), t.get("initiator", ""), rs=1)}'
            f'<td><p>{t.get("created", "")}</p></td><td><p>{t.get("due_date", "")}</p></td>'
            f'<td><p>{rej_code}</p></td><td><p>{reason}</p></td></tr>'
        )

    return ''


def _apply_history_filter_and_update(body_html: str, tickets_by_key: dict,
                                     has_cycle_col: bool, table_type: str) -> str:
    """history expand 블록 내 티켓 행 처리.

    - closed/resolved 티켓: 그대로 유지
    - 비-closed 티켓 중 tickets_by_key에 있고 컬럼 구조 불일치: 현재 데이터로 행 재생성
    - 비-closed 티켓 중 tickets_by_key에 있고 구조 일치: summary_ko 업데이트 (승인 테이블만)
    - 그 외: 그대로 유지
    """
    from bs4 import BeautifulSoup as _BS

    EXPECTED_COLS = {
        'approved': 13 if has_cycle_col else 12,
        'pending':  14 if has_cycle_col else 13,
        'rejected': 12 if has_cycle_col else 11,
    }
    expected_cols = EXPECTED_COLS.get(table_type, 0)
    key_col_idx     = 2 if has_cycle_col else 1
    summary_col_idx = 3 if has_cycle_col else 2
    content_col_idx = 7 if has_cycle_col else 6  # 승인 테이블 내용 컬럼

    soup = _BS(body_html, 'html.parser')
    table = soup.find('table')
    if not table:
        return body_html

    trs = list(table.find_all('tr'))
    modified = False
    new_trs: list = []
    i = 0

    while i < len(trs):
        tr = trs[i]
        cells = tr.find_all(['td', 'th'])

        try:
            rs = int(cells[0].get('rowspan', '1')) if cells else 1
        except (ValueError, TypeError):
            rs = 1

        # 헤더 행 또는 스코어 행 → 그대로
        if rs <= 1 or not cells:
            new_trs.append(tr)
            i += 1
            continue

        # Key / Jira Summary 추출
        key_text = ''
        if len(cells) > key_col_idx:
            a = cells[key_col_idx].find('a')
            key_text = a.get_text(strip=True) if a else cells[key_col_idx].get_text(strip=True)

        jira_sum = cells[summary_col_idx].get_text(strip=True) if len(cells) > summary_col_idx else ''

        # ① closed/resolved → 그대로
        if _is_closed_summary(jira_sum):
            new_trs.extend(trs[i:i + rs])
            i += rs
            continue

        actual_cols = sum(int(c.get('colspan', 1)) for c in cells)
        struct_ok = (expected_cols == 0 or actual_cols == expected_cols)
        t = tickets_by_key.get(key_text)

        # ② 구조 불일치 + 데이터 있음 → 재생성
        if not struct_ok and t:
            rebuilt = _rebuild_ticket_rows(t, has_cycle_col, table_type)
            if rebuilt:
                print(f"  [history 재생성] {key_text}: {actual_cols}열→{expected_cols}열 수정")
                rebuilt_soup = _BS(rebuilt, 'html.parser')
                new_trs.extend(rebuilt_soup.find_all('tr'))
                modified = True
                i += rs
                continue
            print(f"  [history 재생성 실패] {key_text}: 그대로 유지")

        # ③ 구조 불일치 + 데이터 없음 → 경고만
        if not struct_ok:
            print(f"  [history 구조 불일치] {key_text}: {actual_cols}열≠{expected_cols}열, 데이터 없어 그대로")

        # ④ 승인 테이블 + 데이터 있음 → summary_ko 업데이트
        if table_type == 'approved' and t:
            new_sum = t.get('summary_ko', '')
            if new_sum and len(cells) > content_col_idx:
                if _update_summary_cell(cells[content_col_idx], new_sum):
                    modified = True

        new_trs.extend(trs[i:i + rs])
        i += rs

    if not modified:
        return body_html

    # table 재구성
    for tr in list(table.find_all('tr')):
        tr.extract()
    tbody = table.find('tbody')
    target = tbody if tbody else table
    for tr in new_trs:
        target.append(tr)

    return str(soup)


def _cnt(tickets, region=None, approval=None, transition=None):
    """티켓 수 카운트.
    transition: None=전체 / "direct"=보류 미경유 / "converted"=보류 경유
    """
    result = tickets
    if region:
        if isinstance(region, (list, tuple)):
            result = [t for t in result if t.get("region") in region]
        else:
            result = [t for t in result if t.get("region") == region]
    if approval:
        if isinstance(approval, list):
            result = [t for t in result if _effective_approval(t) in approval]
        else:
            result = [t for t in result if _effective_approval(t) == approval]
    if transition == "direct":
        result = [t for t in result if not t.get("was_pending", False)]
    elif transition == "converted":
        result = [t for t in result if t.get("was_pending", False)]
    return len(result)


def _get_all_cycles(tickets):
    return sorted({t.get("cycle_number", 0) for t in tickets if t.get("cycle_number", 0) > 0})


# ── 승인 티켓 테이블 (rowspan=6 스코어링, KR 12열 / EU·HQ 11열) ───
def _build_approved_table(tickets, widths, has_cycle_col, is_prebrd=False, ref_rows=None):
    tickets = sorted(tickets, key=lambda t: t.get("created", ""))
    if not tickets:
        return _no_tickets(prebrd=is_prebrd)

    last_col = "CCI 안건 상정 여부" if is_prebrd else "BRD 승인 여부"
    if has_cycle_col:
        # 항목 분포 3열(항목|셀프|AI), 2행 헤더
        header1 = _th_span([
            ("#", 2, 1), ("회차", 2, 1), ("Key", 2, 1), ("Ticket Summary", 2, 1),
            ("Reporter", 2, 1), ("Created", 2, 1), ("Due date", 2, 1), ("내용", 2, 1),
            ("항목 분포", 1, 3), ("Priority 점수", 2, 1), (last_col, 2, 1),
        ])
    else:
        header1 = _th_span([
            ("#", 2, 1), ("Key", 2, 1), ("Ticket Summary", 2, 1),
            ("Reporter", 2, 1), ("Created", 2, 1), ("Due date", 2, 1), ("Summary", 2, 1),
            ("항목 분포", 1, 3), ("Priority Score", 2, 1), (last_col, 2, 1),
        ])
    header2 = _th_span([
        ("항목", 1, 1), ("셀프(요청자)", 1, 1), ("AI(7.2 초안)", 1, 1),
    ])

    def td_rs(text, rs=6):
        return f'<td rowspan="{rs}"><p>{text}</p></td>'

    def _content_html(t):
        feature_label = t.get("feature_label") or "기존 기능 개선"
        parts = []
        for label, key in [("Summary", "summary_ko"), ("배경", "background"),
                            ("문제", "problem"), (feature_label, "feature")]:
            val = t.get(key) or (t.get("summary", "") if key == "summary_ko" else "")
            if val:
                lines = [line.strip() for line in val.split("\n") if line.strip()] or [val.strip()]
                bullets = "".join(f"<li>{line}</li>" for line in lines)
                parts.append(f"<p><strong>&lt;{label}&gt;</strong></p><ul>{bullets}</ul>")
        return "".join(parts)

    def _score_td3(t, i):
        """항목명 | 셀프 | AI(7.2 초안) 3개 셀 HTML."""
        sco  = t.get("scores", {})
        selfs = t.get("self_scores") or {}
        det   = t.get("review_detail", {})
        k  = SCORE_KEYS[i]
        s  = selfs.get(k) if selfs else None
        a  = _score_mark(sco.get(k, 0))
        a_text = a + (f" ({det[k]})" if k in det else "")
        if s is None:
            return (f'<td><p>{SCORE_LABELS[i]}</p></td>'
                    f'<td><p>—</p></td>'
                    f'<td><p>{a_text}</p></td>')
        bg = MATCH_BG if s == a else MISMATCH_BG
        return (f'<td><p>{SCORE_LABELS[i]}</p></td>'
                f'<td data-highlight-colour="{bg}"><p>{s}</p></td>'
                f'<td data-highlight-colour="{bg}"><p>{a_text}</p></td>')

    rows = [header1, header2]
    seq = 0
    for t in tickets:
        seq += 1
        key = t.get("key", "")
        created = t.get("created", "")
        if ref_rows and key in ref_rows:
            _exp = 13 if has_cycle_col else 12
            _act = _count_effective_cols_first_row(ref_rows[key])
            if _act == _exp:
                rows.append(ref_rows[key])
                continue
            print(f"  [ref 구조 불일치-승인] {key}: 예상 {_exp}열, 실제 {_act}열 → 재생성")
        scores = t.get("scores", {})
        selfs  = t.get("self_scores") or {}

        ai_total = sum(1 for k in SCORE_KEYS[1:] if float(scores.get(k, 0)) > 0)
        if selfs:
            self_total = selfs.get('self_total', '')
            matched    = sum(1 for k in SCORE_KEYS
                            if selfs.get(k) and selfs.get(k) == _score_mark(scores.get(k, 0)))
            comparable = sum(1 for k in SCORE_KEYS if selfs.get(k))
            priority_td = (f'<td rowspan="6">'
                           f'<p>셀프 {self_total} / AI {ai_total}</p>'
                           f'<p>(항목 일치 {matched}/{comparable})</p></td>')
        else:
            priority_td = td_rs(str(ai_total))

        brd_val = "" if is_prebrd else APPROVAL_LABEL.get(_effective_approval(t), "")
        content_html = _content_html(t)
        cycle_col = f'<td rowspan="6"><p>{cycle_label(t.get("cycle_number", 0))}</p></td>' if has_cycle_col else ""

        # Row 1
        rows.append(
            f"<tr>"
            f'{td_rs(str(seq))}'
            f'{cycle_col}'
            f'<td rowspan="6"><p>{_key_link(key)}</p></td>'
            f'{td_rs(t.get("summary", ""))}'
            f'{_reporter_html(t.get("reporter", ""), t.get("initiator", ""))}'
            f'{td_rs(created)}'
            f'{td_rs(t.get("due_date", ""))}'
            f'<td rowspan="6">{content_html}</td>'
            f'{_score_td3(t, 0)}'
            f'{priority_td}'
            f'{td_rs(brd_val)}'
            f"</tr>"
        )
        # Rows 2-6
        for i in range(1, 6):
            rows.append(
                f"<tr>"
                f'{_score_td3(t, i)}'
                f"</tr>"
            )

    return _table(widths, rows)


# ── 보류 티켓 테이블 (rowspan=6, 항목 분포 포함) ─────────────────
def _build_pending_table(tickets, widths, has_cycle_col, prebrd=False, ref_rows=None):
    tickets = sorted(tickets, key=lambda t: t.get("created", ""))
    if not tickets:
        return _no_tickets(prebrd=prebrd)

    if has_cycle_col:
        header = _th_span([
            ("#", 1, 1), ("회차", 1, 1), ("Key", 1, 1), ("Ticket Summary", 1, 1),
            ("Reporter", 1, 1), ("Created", 1, 1), ("Due date", 1, 1),
            ("보류 code", 1, 1), ("보류 사유", 1, 1),
            ("댓글 히스토리", 1, 1), ("최종 결과(승인/반려 전환 결과 및 사유 & 날짜)", 1, 1),
            ("IMG", 1, 1),
        ])
    else:
        header = _th_span([
            ("#", 1, 1), ("Key", 1, 1), ("Ticket Summary", 1, 1),
            ("Reporter", 1, 1), ("Created", 1, 1), ("Due date", 1, 1),
            ("보류 code", 1, 1), ("보류 사유", 1, 1),
            ("댓글 히스토리", 1, 1), ("최종 결과(승인/반려 전환 결과 및 사유 & 날짜)", 1, 1),
            ("IMG", 1, 1),
        ])

    def td(text):
        return f'<td><p>{text}</p></td>'

    rows = [header]
    seq = 0
    for t in tickets:
        seq += 1
        key = t.get("key", "")
        created = t.get("created", "")
        if ref_rows and key in ref_rows:
            _exp = 12 if has_cycle_col else 11
            _act = _count_effective_cols_first_row(ref_rows[key])
            if _act == _exp:
                rows.append(ref_rows[key])
                continue
            print(f"  [ref 구조 불일치-보류] {key}: 예상 {_exp}열, 실제 {_act}열 → 재생성")
        hold_code = t.get("hold_code") or ""
        reason = t.get("hold_reason") or (t.get("background", "")[:150] if hold_code else "")
        cycle_col = f'<td><p>{cycle_label(t.get("cycle_number", 0))}</p></td>' if has_cycle_col else ""

        rows.append(
            f"<tr>"
            f'{td(str(seq))}'
            f'{cycle_col}'
            f'<td><p>{_key_link(key)}</p></td>'
            f'{td(t.get("summary", ""))}'
            f'{_reporter_html(t.get("reporter", ""), t.get("initiator", ""), rs=1)}'
            f'{td(created)}'
            f'{td(t.get("due_date", ""))}'
            f'{td(hold_code)}'
            f'{td(reason)}'
            f'<td></td>'
            f'<td></td>'
            f'<td></td>'
            f"</tr>"
        )

    return _table(widths, rows)


# ── 반려 티켓 테이블 ──────────────────────────────────────────────
def _build_rejected_table(tickets, widths, has_cycle_col, prebrd=False, ref_rows=None):
    tickets = sorted(tickets, key=lambda t: t.get("created", ""))
    if not tickets:
        return _no_tickets(prebrd=prebrd)

    if has_cycle_col:
        header = _th_span([
            ("#", 1, 1), ("회차", 1, 1), ("Key", 1, 1), ("Ticket Summary", 1, 1),
            ("Reporter", 1, 1), ("Created", 1, 1), ("Due date", 1, 1),
            ("반려 code", 1, 1), ("반려 사유", 1, 1),
        ])
    else:
        header = _th_span([
            ("#", 1, 1), ("Key", 1, 1), ("Ticket Summary", 1, 1),
            ("Reporter", 1, 1), ("Created", 1, 1), ("Due date", 1, 1),
            ("반려 code", 1, 1), ("반려 사유", 1, 1),
        ])

    def td(text):
        return f'<td><p>{text}</p></td>'

    rows = [header]
    seq = 0
    for t in tickets:
        seq += 1
        key = t.get("key", "")
        created = t.get("created", "")
        if ref_rows and key in ref_rows:
            _exp = 9 if has_cycle_col else 8
            _act = _count_effective_cols_first_row(ref_rows[key])
            if _act == _exp:
                rows.append(ref_rows[key])
                continue
            print(f"  [ref 구조 불일치-반려] {key}: 예상 {_exp}열, 실제 {_act}열 → 재생성")
        rej_code = t.get("rejection_code") or ""
        reason = t.get("rejection_reason") or (t.get("problem", "")[:150] if rej_code else "")
        cycle_col = f'<td><p>{cycle_label(t.get("cycle_number", 0))}</p></td>' if has_cycle_col else ""

        rows.append(
            f"<tr>"
            f'{td(str(seq))}'
            f'{cycle_col}'
            f'<td><p>{_key_link(key)}</p></td>'
            f'{td(t.get("summary", ""))}'
            f'{_reporter_html(t.get("reporter", ""), t.get("initiator", ""), rs=1)}'
            f'{td(created)}'
            f'{td(t.get("due_date", ""))}'
            f'{td(rej_code)}'
            f'{td(reason)}'
            f"</tr>"
        )

    return _table(widths, rows)


# ── Section 0: 스크리닝 기준 ─────────────────────────────────────
def _build_section0():
    intro_panel = _panel("#DEEBFF",
        "<p><strong>회차별 신규/개선 티켓 스크리닝 운영 및 의견에서 이력 관리 및 관련 내용</strong></p>"
        "<ul>"
        "<li><p>티켓 검토 기준: 티켓 생성 후 2 영업일 이내 승인 / 보류 / 반려 의견 전달</p></li>"
        "<li><p>페이지 업데이트 기준: 검토 완료 시점으로부터 1 영업일 이내 현황 수치 및 권역별 히스토리 반영</p></li>"
        "</ul>"
        "<p>▶ 본 문서</p>"
        "<p>ㅇ 티켓 스크리닝 현황 및 이력 관리</p>"
    )
    criteria_panel = _panel("#F4F5F7",
        "<ul>"
        "<li><p>스크리닝 진행 현황에 따라 승인 / 보류 / 반려 세 그룹으로 분류되며, 티켓 처리 과정에 필요한 세부 단계 및 관련 요청 사항</p></li>"
        "<li><p>보류 안내일로부터 10 영업일 이내 미보완 시 자동 반려 <strong>*별도 안내 필요</strong></p></li>"
        "</ul>"
    )
    code_table = _table(CW.get("section1_overall", []), [
        _th_span([("보류", 1, 3), ("반려", 1, 4)]),
        _th("code", "유형", "판단 기준", "해소 조건", "code", "유형", "판단 기준"),
        _td("H1", "필수 항목 누락", "BRD 필수 항목 미작성 (추진 배경, 기능 목록, IT 연동 등)", "BRD 보완 후 재검토",
            "R1", "평가 항목 전항목 미충족", "시급성 해당 없음 + 5개 평가 항목 합계 0점"),
        _td("H2", "구체성 부족", "작성 항목의 요건 구체성 부족 또는 구현 로직 불명확", "요건 구체화 후 재검토",
            "R2", "운영 범위 외", "OneApp 플랫폼 운영 범위 외 요청 (타 시스템·채널 소관)"),
        _td("H3", "정량 근거 부족", "스코어링 근거가 추정 수준, 정량 데이터 보완 필요", "정량 데이터 보완 후 재검토",
            "R3", "중복 티켓", "실질적으로 동일한 요건이 이미 진행 중인 티켓 존재"),
        _td("H4", "선행 조건 미충족", "타 티켓/프로젝트 완료 또는 정책 확정이 선행 필요", "선행 조건 해소 후 재검토",
            "R4", "방향성 배치", "글로벌 BPM 방향성 또는 리더십 결정 사항과 배치"),
    ])
    return [
        intro_panel,
        _h2("0. 티켓 스크리닝 기준"),
        criteria_panel,
        code_table,
        _p("*code : 처리 품질 리스트에 적용되는 트래킹 코드 - H=Hold / R=Reject"),
    ]


# ── Section 1: 스크리닝 현황 ──────────────────────────────────────
def _load_ref_tracking_data(hmg_client: HmgConfluenceClient, cutoff_cycle=None):
    """참조 문서에서 회차별 트래킹 현황 데이터 행과 Total 수치 추출.
    cutoff_cycle: 이 번호 이상의 회차 행은 포함하지 않음 (해당 회차는 직접 계산).
    Returns: {'data_rows': [html_str, ...], 'total_vals': [int×18] or None}
    """
    import re as _re
    from bs4 import BeautifulSoup as _BS
    _cpat = _re.compile(r'Pre-BRD|\d+회차')
    _cycnum_pat = _re.compile(r'^(\d+)회차')

    def _cell_int(cell):
        t = cell.get_text(strip=True)
        if _re.match(r'^\d+$', t):
            return int(t)
        return 0   # '-' 및 기타는 0 처리

    try:
        html, _, _ = hmg_client.get_page_storage(DOC2_REF_PAGE_ID)
        soup = _BS(html, 'html.parser')
        for table in soup.find_all('table'):
            ttext = table.get_text()
            if '보류 중' not in ttext or '승인 전환' not in ttext:
                continue
            rows = table.find_all('tr')
            data_rows, total_vals, had_filtered = [], None, False
            for tr in rows:
                cells = tr.find_all(['td', 'th'])
                if not cells:
                    continue
                first = cells[0].get_text(strip=True)
                if _cpat.search(first):
                    if cutoff_cycle is not None:
                        m = _cycnum_pat.match(first)
                        if m and int(m.group(1)) >= cutoff_cycle:
                            had_filtered = True
                            continue  # 현재 회차 이상 제외 → 직접 계산으로 대체
                    data_rows.append(str(tr))
                elif first == 'Total':
                    nums = [_cell_int(c) for c in cells[1:]]
                    if len(nums) >= 18:
                        total_vals = nums[:18]
            # 필터로 제거된 행이 있으면 ref Total도 신뢰 불가 (해당 회차 포함됐을 수 있음)
            if had_filtered:
                total_vals = None
            if data_rows:
                print(f"  [ref_tracking] {len(data_rows)}개 행, total={'있음' if total_vals else '없음'}"
                      + (f" (cutoff={cutoff_cycle}회차 이상 제외)" if had_filtered else ""))
                return {'data_rows': data_rows, 'total_vals': total_vals}
    except Exception as e:
        print(f"  [ref_tracking] 실패: {e}")
    return {'data_rows': [], 'total_vals': None}



def _build_section1(tickets, current_cycle, hmg_client=None):
    _ref_tk = _load_ref_tracking_data(hmg_client, cutoff_cycle=current_cycle) if hmg_client else {'data_rows': [], 'total_vals': None}
    c6      = [t for t in tickets if t.get("cycle_number") == current_cycle]
    has_tk  = bool(_ref_tk.get('data_rows'))
    pend    = ["보류"]

    # ── 18개 집계값 (KR×6 + EU×6 + HQ×6) ─────────────────────────
    # 각 영역: [인입, 승인직접, 반려직접, 보류중, 승인전환, 반려전환]
    def _mk6(reg, src):
        return [
            _cnt(src, reg),
            _cnt(src, reg, "Approved", "direct"),
            _cnt(src, reg, "반려",     "direct"),
            _cnt(src, reg, pend),
            _cnt(src, reg, "Approved", "converted"),
            _cnt(src, reg, "반려",     "converted"),
        ]

    c6_vals = _mk6(_KR_REGIONS, c6) + _mk6(_EU_REGIONS, c6) + _mk6(_HQ_REGIONS, c6)

    ref_tv = _ref_tk.get('total_vals')
    if ref_tv and len(ref_tv) >= 18:
        agg = [ref_tv[i] + c6_vals[i] for i in range(18)]
    else:
        # 폴백: 전체 티켓에서 18개 직접 계산
        agg = _mk6(_KR_REGIONS, tickets) + _mk6(_EU_REGIONS, tickets) + _mk6(_HQ_REGIONS, tickets)


    # ── 회차별 트래킹 표 (19열, 4행 헤더) ──────────────────────────
    # 헤더 4행
    track_h1 = (
        "<tr>"
        + _c("th", "",    bg=GREY, rs=4)          # 회차 열 (rowspan=4, 빈 헤더)
        + _c("th", "RHQ", bg=GREY, cs=12, bold_white=True)
        + _c("th", "HQ",  bg=GREY, cs=6,  bold_white=True)
        + "</tr>"
    )
    track_h2 = (
        "<tr>"
        + _c("th", "KR",             bg=KR_BLUE,  cs=6, bold_white=True)
        + _c("td", "EU",             bg=EU_TEAL,  cs=6, bold_white=True)
        + _c("td", "GBCXD 및 타부문", bg=HQ_GREEN, cs=6, bold_white=True)
        + "</tr>"
    )
    track_h3 = (
        "<tr>"
        # KR
        + _c("th", "티켓 인입 수", bg=KR_BLUE, rs=2, bold_white=True)
        + _c("td", "승인",        bg=KR_BLUE, rs=2, bold_white=True)
        + _c("td", "반려",        bg=KR_BLUE, rs=2, bold_white=True)
        + _c("td", "보류",        bg=KR_BLUE, cs=3, bold_white=True)
        # EU
        + _c("td", "티켓 인입 수", bg=EU_TEAL, rs=2, bold_white=True)
        + _c("td", "승인",        bg=EU_TEAL, rs=2, bold_white=True)
        + _c("td", "반려",        bg=EU_TEAL, rs=2, bold_white=True)
        + _c("td", "보류",        bg=EU_TEAL, cs=3, bold_white=True)
        # HQ
        + _c("td", "티켓 인입 수", bg=HQ_GREEN, rs=2, bold_white=True)
        + _c("td", "승인",        bg=HQ_GREEN, rs=2, bold_white=True)
        + _c("td", "반려",        bg=HQ_GREEN, rs=2, bold_white=True)
        + _c("td", "보류",        bg=HQ_GREEN, cs=3, bold_white=True)
        + "</tr>"
    )
    track_h4 = (
        "<tr>"
        + _c("th", "보류 중",   bg=KR_BLUE, bold_white=True)
        + _c("td", "승인 전환", bg=KR_BLUE, bold_white=True)
        + _c("td", "반려 전환", bg=KR_BLUE, bold_white=True)
        + _c("td", "보류 중",   bg=EU_TEAL, bold_white=True)
        + _c("td", "승인 전환", bg=EU_TEAL, bold_white=True)
        + _c("td", "반려 전환", bg=EU_TEAL, bold_white=True)
        + _c("td", "보류 중",   bg=HQ_GREEN, bold_white=True)
        + _c("td", "승인 전환", bg=HQ_GREEN, bold_white=True)
        + _c("td", "반려 전환", bg=HQ_GREEN, bold_white=True)
        + "</tr>"
    )

    # 데이터 행 + Total 행
    def _dash(n: int) -> str:
        return "-" if n == 0 else str(n)

    if has_tk:
        # 참조 문서에서 Pre-BRD~이전 회차 행 복제, 현재 회차만 직접 계산
        def _sc6(reg=None, appr=None, trans=None):
            return _dash(_cnt(c6, reg, appr, transition=trans))

        c6_row = (
            "<tr>"
            + _c("th", _track_label(current_cycle), bg=GREY, bold_white=True)
            + _c("td", _sc6(_KR_REGIONS))
            + _c("td", _sc6(_KR_REGIONS, "Approved",  "direct"))
            + _c("td", _sc6(_KR_REGIONS, "반려",      "direct"))
            + _c("td", _sc6(_KR_REGIONS, pend))
            + _c("td", _sc6(_KR_REGIONS, "Approved",  "converted"))
            + _c("td", _sc6(_KR_REGIONS, "반려",      "converted"))
            + _c("td", _sc6(_EU_REGIONS))
            + _c("td", _sc6(_EU_REGIONS, "Approved",  "direct"))
            + _c("td", _sc6(_EU_REGIONS, "반려",      "direct"))
            + _c("td", _sc6(_EU_REGIONS, pend))
            + _c("td", _sc6(_EU_REGIONS, "Approved",  "converted"))
            + _c("td", _sc6(_EU_REGIONS, "반려",      "converted"))
            + _c("td", _sc6(_HQ_REGIONS))
            + _c("td", _sc6(_HQ_REGIONS, "Approved",  "direct"))
            + _c("td", _sc6(_HQ_REGIONS, "반려",      "direct"))
            + _c("td", _sc6(_HQ_REGIONS, pend))
            + _c("td", _sc6(_HQ_REGIONS, "Approved",  "converted"))
            + _c("td", _sc6(_HQ_REGIONS, "반려",      "converted"))
            + "</tr>"
        )
        track_data = list(_ref_tk['data_rows']) + [c6_row]

        # Total = ref 누적 + c6
        ref_tv = _ref_tk.get('total_vals')
        c6_vals = [
            _cnt(c6, _KR_REGIONS),                               # KR 인입
            _cnt(c6, _KR_REGIONS, "Approved",  "direct"),
            _cnt(c6, _KR_REGIONS, "반려",      "direct"),
            _cnt(c6, _KR_REGIONS, pend),
            _cnt(c6, _KR_REGIONS, "Approved",  "converted"),
            _cnt(c6, _KR_REGIONS, "반려",      "converted"),
            _cnt(c6, _EU_REGIONS),                               # EU 인입
            _cnt(c6, _EU_REGIONS, "Approved",  "direct"),
            _cnt(c6, _EU_REGIONS, "반려",      "direct"),
            _cnt(c6, _EU_REGIONS, pend),
            _cnt(c6, _EU_REGIONS, "Approved",  "converted"),
            _cnt(c6, _EU_REGIONS, "반려",      "converted"),
            _cnt(c6, _HQ_REGIONS),                               # HQ 인입
            _cnt(c6, _HQ_REGIONS, "Approved",  "direct"),
            _cnt(c6, _HQ_REGIONS, "반려",      "direct"),
            _cnt(c6, _HQ_REGIONS, pend),
            _cnt(c6, _HQ_REGIONS, "Approved",  "converted"),
            _cnt(c6, _HQ_REGIONS, "반려",      "converted"),
        ]
        if ref_tv and len(ref_tv) >= 18:
            nt = [_dash(ref_tv[i] + c6_vals[i]) for i in range(18)]
        else:
            # ref Total 신뢰 불가(필터로 제거됨 또는 없음) → 전체 캐시 기반 agg 사용
            nt = [_dash(v) for v in agg]

        total_track = (
            "<tr>"
            + _c("th", "Total", bg=GREY, bold_white=True)
            + _c("td", nt[0],  bg=TOTAL_BLUE, bold=True)
            + _c("td", nt[1],  bg=TOTAL_BLUE, bold=True)
            + _c("td", nt[2],  bg=TOTAL_BLUE, bold=True)
            + _c("td", nt[3],  bg=TOTAL_BLUE, bold=True)
            + _c("td", nt[4],  bg=TOTAL_BLUE, bold=True)
            + _c("td", nt[5],  bg=TOTAL_BLUE, bold=True)
            + _c("td", nt[6],  bg=TOTAL_BLUE, bold=True)
            + _c("td", nt[7],  bg=TOTAL_BLUE, bold=True)
            + _c("td", nt[8],  bg=TOTAL_BLUE, bold=True)
            + _c("td", nt[9],  bg=TOTAL_BLUE, bold=True)
            + _c("td", nt[10], bg=TOTAL_BLUE, bold=True)
            + _c("td", nt[11], bg=TOTAL_BLUE, bold=True)
            + _c("td", nt[12], bg=TOTAL_BLUE, bold=True)
            + _c("td", nt[13], bg=TOTAL_BLUE, bold=True)
            + _c("td", nt[14], bg=TOTAL_BLUE, bold=True)
            + _c("td", nt[15], bg=TOTAL_BLUE, bold=True)
            + _c("td", nt[16], bg=TOTAL_BLUE, bold=True)
            + _c("td", nt[17], bg=TOTAL_BLUE, bold=True)
            + "</tr>"
        )
    else:
        # 폴백: 티켓 데이터에서 직접 계산
        all_cycles = sorted({t.get("cycle_number", 0) for t in tickets})
        track_data = []
        for cn in all_cycles:
            cyc = [t for t in tickets if t.get("cycle_number") == cn]
            def _s(reg=None, appr=None, trans=None, _cyc=cyc):
                return _dash(_cnt(_cyc, reg, appr, transition=trans))
            row = (
                "<tr>"
                + _c("th", _track_label(cn), bg=GREY, bold_white=True)
                + _c("td", _s(_KR_REGIONS))
                + _c("td", _s(_KR_REGIONS, "Approved",  "direct"))
                + _c("td", _s(_KR_REGIONS, "반려",      "direct"))
                + _c("td", _s(_KR_REGIONS, pend))
                + _c("td", _s(_KR_REGIONS, "Approved",  "converted"))
                + _c("td", _s(_KR_REGIONS, "반려",      "converted"))
                + _c("td", _s(_EU_REGIONS))
                + _c("td", _s(_EU_REGIONS, "Approved",  "direct"))
                + _c("td", _s(_EU_REGIONS, "반려",      "direct"))
                + _c("td", _s(_EU_REGIONS, pend))
                + _c("td", _s(_EU_REGIONS, "Approved",  "converted"))
                + _c("td", _s(_EU_REGIONS, "반려",      "converted"))
                + _c("td", _s(_HQ_REGIONS))
                + _c("td", _s(_HQ_REGIONS, "Approved",  "direct"))
                + _c("td", _s(_HQ_REGIONS, "반려",      "direct"))
                + _c("td", _s(_HQ_REGIONS, pend))
                + _c("td", _s(_HQ_REGIONS, "Approved",  "converted"))
                + _c("td", _s(_HQ_REGIONS, "반려",      "converted"))
                + "</tr>"
            )
            track_data.append(row)

        def _st(reg, appr=None, trans=None):
            return _dash(_cnt(tickets, reg, appr, transition=trans))
        total_track = (
            "<tr>"
            + _c("th", "Total", bg=GREY, bold_white=True)
            + _c("td", _st(_KR_REGIONS),                            bg=TOTAL_BLUE, bold=True)
            + _c("td", _st(_KR_REGIONS, "Approved",  "direct"),    bg=TOTAL_BLUE, bold=True)
            + _c("td", _st(_KR_REGIONS, "반려",      "direct"),    bg=TOTAL_BLUE, bold=True)
            + _c("td", _st(_KR_REGIONS, pend),                     bg=TOTAL_BLUE, bold=True)
            + _c("td", _st(_KR_REGIONS, "Approved",  "converted"), bg=TOTAL_BLUE, bold=True)
            + _c("td", _st(_KR_REGIONS, "반려",      "converted"), bg=TOTAL_BLUE, bold=True)
            + _c("td", _st(_EU_REGIONS),                            bg=TOTAL_BLUE, bold=True)
            + _c("td", _st(_EU_REGIONS, "Approved",  "direct"),    bg=TOTAL_BLUE, bold=True)
            + _c("td", _st(_EU_REGIONS, "반려",      "direct"),    bg=TOTAL_BLUE, bold=True)
            + _c("td", _st(_EU_REGIONS, pend),                     bg=TOTAL_BLUE, bold=True)
            + _c("td", _st(_EU_REGIONS, "Approved",  "converted"), bg=TOTAL_BLUE, bold=True)
            + _c("td", _st(_EU_REGIONS, "반려",      "converted"), bg=TOTAL_BLUE, bold=True)
            + _c("td", _st(_HQ_REGIONS),                            bg=TOTAL_BLUE, bold=True)
            + _c("td", _st(_HQ_REGIONS, "Approved",  "direct"),    bg=TOTAL_BLUE, bold=True)
            + _c("td", _st(_HQ_REGIONS, "반려",      "direct"),    bg=TOTAL_BLUE, bold=True)
            + _c("td", _st(_HQ_REGIONS, pend),                     bg=TOTAL_BLUE, bold=True)
            + _c("td", _st(_HQ_REGIONS, "Approved",  "converted"), bg=TOTAL_BLUE, bold=True)
            + _c("td", _st(_HQ_REGIONS, "반려",      "converted"), bg=TOTAL_BLUE, bold=True)
            + "</tr>"
        )

    tracking_table = _table(CW["section1_tracking"],
                            [track_h1, track_h2, track_h3, track_h4]
                            + track_data + [total_track])

    # 회차별 마감 히스토리 섹션 (표 자체는 Doc2-1 별도 페이지에 생성)
    history_section = (
        _h3("■ 회차별 마감 히스토리")
        + _p('참고: 회차별 마감 히스토리')
    )

    return [
        _h2("1. 티켓 스크리닝 현황"),
        _p(f"(업데이트) {datetime.now().strftime('%y.%m.%d')} 기준"),
        _h3("■ 회차별 트래킹 현황"),
        tracking_table,
        history_section,
    ]


# ── Section 2-4: 지역별 티켓 히스토리 ────────────────────────────
def _build_region_section(tickets, region_code, section_num, approved_widths,
                          pending_widths, rejected_widths, has_cycle_col,
                          active_cycle, ref_rows=None, ref_history=None,
                          tickets_by_key=None):
    """지역별 티켓 히스토리 섹션 HTML 빌드.

    ref_history: _load_ref_history_doc2() 반환값. 이전 회차 expand 블록.
    tickets_by_key: {ticket_key: analysis_dict} — history 행 업데이트용.
    """
    region_tickets = [t for t in tickets if t.get("region") in {
        "KR": _KR_REGIONS, "EU": _EU_REGIONS, "HQ": _HQ_REGIONS
    }[region_code]]
    region_name = {"KR": "KR", "EU": "EU", "HQ": "HQ GBCXD 및 타부문"}[region_code]

    def _filter(appr=None):
        result = [t for t in region_tickets if t.get("cycle_number") == active_cycle]
        if appr:
            if isinstance(appr, list):
                result = [t for t in result if _effective_approval(t) in appr]
            else:
                result = [t for t in result if _effective_approval(t) == appr]
        return result

    region_hist = (ref_history or {}).get(region_code, {})
    tbk = tickets_by_key or {}
    parts = [_h2(f"{section_num}. {region_name} 티켓 히스토리")]

    # ── 승인 티켓 ──
    parts.append(_p_bold(f"{section_num}.1. 승인 티켓"))
    # 이전 회차 — 누락 회차는 '해당 티켓 없음'으로 채움
    for cycle_title, body_html in _fill_missing_cycles(region_hist.get('Approved', []), active_cycle):
        updated = _apply_history_filter_and_update(body_html, tbk, has_cycle_col, 'approved')
        parts.append(_expand(cycle_title, updated))
    # 현재 회차
    parts.append(_expand(_cycle_expand_title(active_cycle),
        _build_approved_table(_filter("Approved"), approved_widths, has_cycle_col, ref_rows=ref_rows)))

    # ── 보류 티켓 ──
    parts.append(_p_bold(f"{section_num}.2. 보류 티켓"))
    # 이전 회차 — 누락 회차는 '해당 티켓 없음'으로 채움
    for cycle_title, body_html in _fill_missing_cycles(region_hist.get('보류', []), active_cycle):
        updated = _apply_history_filter_and_update(body_html, tbk, has_cycle_col, 'pending')
        parts.append(_expand(cycle_title, updated))
    # 현재 회차
    parts.append(_expand(_cycle_expand_title(active_cycle),
        _build_pending_table(_filter("보류"), pending_widths, has_cycle_col, ref_rows=ref_rows)))

    # ── 반려 티켓 ──
    parts.append(_p_bold(f"{section_num}.3. 반려 티켓"))
    # 이전 회차 — 누락 회차는 '해당 티켓 없음'으로 채움
    for cycle_title, body_html in _fill_missing_cycles(region_hist.get('반려', []), active_cycle):
        updated = _apply_history_filter_and_update(body_html, tbk, has_cycle_col, 'rejected')
        parts.append(_expand(cycle_title, updated))
    # 현재 회차
    parts.append(_expand(_cycle_expand_title(active_cycle),
        _build_rejected_table(_filter("반려"), rejected_widths, has_cycle_col, ref_rows=ref_rows)))

    return parts


# ── 마스터 페이지 헬퍼 ──────────────────────────────────────────

def _find_master_page(client: ConfluenceClient,
                      folder_id: str) -> tuple[str | None, str | None, int]:
    """폴더 내 고정 제목 마스터 페이지 탐색. 없으면 (None, None, 0) 반환."""
    cursor: str | None = None
    while True:
        params: dict = {"parentId": folder_id, "limit": 50}
        if cursor:
            params["cursor"] = cursor
        data = client._get("/pages", params=params)
        for page in data.get("results", []):
            if page["title"] == MASTER_TITLE:
                html, version, _ = client.get_page_storage(page["id"])
                return page["id"], html, version
        nxt = data.get("_links", {}).get("next", "")
        if not nxt:
            break
        for part in nxt.split("&"):
            if "cursor=" in part:
                cursor = part.split("cursor=")[-1]
                break
        else:
            break
    return None, None, 0


def _create_snapshot(client: ConfluenceClient, master_id: str,
                     content: str, timestamp: str) -> None:
    """마스터 페이지 현재 내용을 하위 스냅샷 페이지로 보관."""
    snapshot_title = f"{timestamp} 스냅샷"
    try:
        client.create_page(master_id, snapshot_title, content)
        print(f"[Doc2] 스냅샷 생성: {snapshot_title}")
    except Exception as e:
        print(f"[Doc2] 스냅샷 생성 실패 (계속 진행): {e}")


# ── 메인 업데이트 함수 ──────────────────────────────────────────
def update(tickets_with_analysis: list[dict], client: ConfluenceClient | None = None, as_of: str | None = None):
    if client is None:
        client = ConfluenceClient()

    active_cycle = get_active_cycle()

    # Feature 1: HMG Confluence 참조 문서에서 이전 티켓 행 추출
    hmg_client = HmgConfluenceClient()
    ref_rows = _load_ref_rows_doc2(hmg_client)
    ref_history = _load_ref_history_doc2(hmg_client, active_cycle)
    tickets_by_key = {t.get('key', ''): t for t in tickets_with_analysis if t.get('key')}

    now = datetime.now()
    note_html = (f'<p><em>{now.strftime("%Y-%m-%d %H:%M")} 전체 재생성, '
                 f'{active_cycle}회차 기준</em></p>')
    _toc = (
        '<ac:structured-macro ac:name="toc" ac:schema-version="1">'
        '<ac:parameter ac:name="style">none</ac:parameter>'
        '</ac:structured-macro>'
    )
    sections = [note_html, _toc]
    sections += _build_section1(tickets_with_analysis, active_cycle, hmg_client=hmg_client)
    sections += _build_region_section(
        tickets_with_analysis, "KR", 2,
        CW["kr_approved"], CW["kr_pending"], CW["kr_rejected"], has_cycle_col=True,
        active_cycle=active_cycle, ref_rows=ref_rows,
        ref_history=ref_history, tickets_by_key=tickets_by_key)
    sections += _build_region_section(
        tickets_with_analysis, "EU", 3,
        CW["eu_approved"], CW["eu_pending"], CW["eu_rejected"], has_cycle_col=False,
        active_cycle=active_cycle, ref_rows=ref_rows,
        ref_history=ref_history, tickets_by_key=tickets_by_key)
    sections += _build_region_section(
        tickets_with_analysis, "HQ", 4,
        CW["eu_approved"], CW["eu_pending"], CW["eu_rejected"], has_cycle_col=False,
        active_cycle=active_cycle, ref_rows=ref_rows,
        ref_history=ref_history, tickets_by_key=tickets_by_key)

    html = "\n".join(sections)

    timestamp = as_of if as_of else now.strftime("%m-%d %H:%M")
    master_id, current_html, current_version = _find_master_page(client, DOC_PAGE_IDS["doc2"])
    if master_id:
        if current_html and current_html.strip():
            _create_snapshot(client, master_id, current_html, timestamp)
        client.update_page(master_id, MASTER_TITLE, html, current_version,
                           message=f"{timestamp} 업데이트: {len(tickets_with_analysis)}건")
        print(f"[Doc2] 마스터 페이지 업데이트 완료 (총 {len(tickets_with_analysis)}건, id={master_id})")
    else:
        result = client.create_page(DOC_PAGE_IDS["doc2"], MASTER_TITLE, html)
        new_id = result.get("id", "")
        print(f"[Doc2] 마스터 페이지 최초 생성 (총 {len(tickets_with_analysis)}건, id={new_id})")
