"""
Document 1: KKR OneApp 주간 보고 (AI 생성) — Full Rebuild Updater
- 매 실행마다 Pre-BRD / Post-BRD를 단일 테이블로 완전히 재빌드
- Pre-BRD : cycle_number == 0인 티켓, created 오름차순  (참조 문서 서식 기준)
- Post-BRD: cycle_number >= 1인 티켓, cycle 오름차순 → created 오름차순  (AI Doc1 서식 기준)
업데이트 주기: 매주 월요일 10:00
"""
import json
import os
from datetime import datetime, date, timedelta
from bs4 import BeautifulSoup, Tag
from confluence_client import ConfluenceClient, HmgConfluenceClient
from config import DOC_PAGE_IDS, HMG_DOC1_FOLDER_3Q, HMG_DOC1_FOLDER_Q4
from cycle import cycle_label, get_active_cycle

# ─── 상수 ────────────────────────────────────────────────────────────────────

SCORE_LABELS = [
    "시급성", "사업 성과 기여", "고객 경험 영향도",
    "운영 효율화", "글로벌 파급 범위", "플랫폼 운영 전략 연계도",
]
SCORE_KEYS = [
    "urgency", "business_performance", "customer_experience",
    "operational_efficiency", "global_reach", "platform_strategy",
]
BRD_DISPLAY = {
    "Approved": "승인",
    "보류":     "보류",
    "반려":     "반려",
}

TABLE_TITLE  = "New/Improvement"
MASTER_TITLE = "KKR OneApp 주간 보고 (AI 생성)"
SECTION_PRE  = "BRD 프로세스 적용 이전 (Pre-BRD)"
SECTION_POST = "BRD 프로세스 적용 이후"
TOTAL_COLS   = 13   # 항목 분포: 항목|셀프(요청자)|AI(7.2 초안) 3열

# 셀프/AI 일치·불일치 셀 배경색
MATCH_BG    = "#e3fcef"   # 일치 (초록)
MISMATCH_BG = "#ffebe6"   # 불일치 (빨강)

# 참조 문서(71139380)의 New/Improvement 표 열 너비 (px) — 항목 분포 2열→3열
COL_WIDTHS = [51, 70, 182, 242, 93, 100, 98, 475, 147, 90, 110, 105, 107]

JIRA_BROWSE = "https://hmg.atlassian.net/browse"

# Feature 1: 참조 문서 복제 — HMG Confluence 폴더에서 최신 페이지 자동 탐색

# Pending 관리 표 열 너비 (원본 참조 문서 기준)
PENDING_COL_WIDTHS = [78, 138, 412, 108, 110, 134, 129, 591, 83]
PENDING_HEADERS    = ['#', 'Key', 'Ticket Summary', 'Reporter', 'Status',
                      'Created', 'End date', '진척사항 확인', '배포 필요']

# '배포 필요' X 판정 상태: 취소·종료·해결됨 계열
_NO_DEPLOY_STATUSES = frozenset({"Dropped", "해결됨", "종료", "RESOLVE", "Deployed"})

# ─── 오버라이드 로드 ─────────────────────────────────────────────────────────

def _load_overrides() -> dict:
    path = os.path.join(os.path.dirname(__file__), "ticket_overrides.json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

_OVERRIDES = _load_overrides()
_CYCLE_OV      = _OVERRIDES.get("cycle_overrides", {})       # key → cycle_number
_BRD_OV        = _OVERRIDES.get("brd_approval_overrides", {}) # key → 보류/승인/반려
_EXCLUDED_KEYS = set(_OVERRIDES.get("excluded_keys", []))     # 제외 키 집합


# ─── 공통 헬퍼 ──────────────────────────────────────────────────────────────

import re as _re
_TICKET_PATTERN = _re.compile(r'\b(KCCIVOC|KEUVOCOP|CCIPRJ)-\d+\b')


def _linkify(soup: BeautifulSoup, text: str) -> list:
    """텍스트 내 Jira 티켓 키 패턴을 하이퍼링크로 변환."""
    parts = []
    last = 0
    for m in _TICKET_PATTERN.finditer(text):
        if m.start() > last:
            parts.append(soup.new_string(text[last:m.start()]))
        a = soup.new_tag('a', href=f"{JIRA_BROWSE}/{m.group()}")
        a.string = m.group()
        parts.append(a)
        last = m.end()
    if last < len(text):
        parts.append(soup.new_string(text[last:]))
    return parts or [soup.new_string(text)]


def _td(soup: BeautifulSoup, text, rowspan: int = 1, center: bool = False) -> Tag:
    base = "padding: 14px 10px; line-height: 1.6;"
    style = base + " text-align: center;" if center else base
    cell = soup.new_tag('td', style=style)
    if rowspan > 1:
        cell['rowspan'] = str(rowspan)
    p = soup.new_tag('p')
    p.string = str(text)
    cell.append(p)
    return cell


def _td_link(soup: BeautifulSoup, key: str, rowspan: int = 1, center: bool = False) -> Tag:
    """Key 셀 — Jira 티켓 URL 하이퍼링크."""
    base = "padding: 14px 10px; line-height: 1.6;"
    style = base + " text-align: center;" if center else base
    cell = soup.new_tag('td', style=style)
    if rowspan > 1:
        cell['rowspan'] = str(rowspan)
    p = soup.new_tag('p')
    a = soup.new_tag('a', href=f"{JIRA_BROWSE}/{key}")
    a.string = key
    p.append(a)
    cell.append(p)
    return cell


def _td_reporter(soup: BeautifulSoup, reporter: str, initiator: str, rowspan: int = 1, center: bool = False) -> Tag:
    """Reporter 셀 — 이름 + (발의: 000) 표시."""
    base = "padding: 14px 10px; line-height: 1.6;"
    style = base + " text-align: center;" if center else base
    cell = soup.new_tag('td', style=style)
    if rowspan > 1:
        cell['rowspan'] = str(rowspan)
    p_r = soup.new_tag('p')
    p_r.string = reporter
    cell.append(p_r)
    if initiator:
        p_i = soup.new_tag('p')
        em = soup.new_tag('em')
        em.string = f"(발의: {initiator})"
        p_i.append(em)
        cell.append(p_i)
    return cell


def _score_mark(value) -> str:
    try:
        return 'O' if float(value) > 0 else 'X'
    except (ValueError, TypeError):
        return 'X'


def _mark_td(soup: BeautifulSoup, text, bg: str = None, rowspan: int = 1, center: bool = False) -> Tag:
    """배경색 강조 셀 — 셀프/AI 일치·불일치 표기용."""
    cell = _td(soup, text, rowspan=rowspan, center=center)
    if bg:
        cell['data-highlight-colour'] = bg
    return cell


def _count_o(scores: dict) -> str:
    """Priority 점수 = 시급성 제외 5개 항목 중 O 개수."""
    keys = SCORE_KEYS[1:]
    return str(sum(1 for k in keys if float(scores.get(k, 0)) > 0))


def _patch_ticket_summary(tr: Tag, summary: str, soup: BeautifulSoup) -> None:
    """참조 문서 복사 행의 Ticket Summary 셀(4번째 td)을 실제 Jira 타이틀로 교체.

    참조 문서에서 티켓 키가 다른 티켓의 내용 링크로 먼저 등장해 잘못된 행이
    캡처될 수 있고, Jira 타이틀이 변경되어도 불일치가 생긴다.
    첫 번째 행(rowspan 셀이 있는 행)에만 Ticket Summary 셀이 존재한다.
    """
    tds = tr.find_all('td', recursive=False)
    # 열 순서: # | Cycle | Key | Ticket Summary | Reporter | Created | Due date | ...
    if len(tds) > 3:
        td = tds[3]
        for child in list(td.children):
            child.extract()
        p = soup.new_tag('p')
        p.string = summary
        td.append(p)


def _section_row(soup: BeautifulSoup, text: str, colour: str = "") -> Tag:
    """섹션 구분 행 (colspan 전체, 굵게)."""
    tr = soup.new_tag('tr')
    td = soup.new_tag('td')
    td['colspan'] = str(TOTAL_COLS)
    if colour:
        td['data-highlight-colour'] = colour
    p = soup.new_tag('p')
    strong = soup.new_tag('strong')
    strong.string = text
    p.append(strong)
    td.append(p)
    tr.append(td)
    return tr


def _header_row(soup: BeautifulSoup) -> list:
    """2행 헤더 반환: 1행=메인 컬럼, 2행=항목 분포 하위 컬럼(항목|셀프|AI)."""
    col_specs = [
        ('#', 1), ('Cycle', 1), ('Key', 1), ('Ticket Summary', 1),
        ('Reporter', 1), ('Created', 1), ('Due date', 1),
        ('내용', 1), ('항목 분포', 3), ('Priority 점수', 1), ('BRD 승인 여부', 1),
    ]
    tr1 = soup.new_tag('tr')
    for text, colspan in col_specs:
        th = soup.new_tag('th', style="padding: 14px 10px;")
        if colspan > 1:
            th['colspan'] = str(colspan)
        p = soup.new_tag('p')
        p.string = text
        th.append(p)
        tr1.append(th)

    tr2 = soup.new_tag('tr')
    for _ in range(8):                              # 앞 8열: 빈 헤더
        th = soup.new_tag('th', style="padding: 6px 10px;")
        tr2.append(th)
    for sub in ('항목', '셀프(요청자)', 'AI(7.2 초안)'):
        th = soup.new_tag('th', style="padding: 6px 10px;")
        p = soup.new_tag('p')
        p.string = sub
        th.append(p)
        tr2.append(th)
    for _ in range(2):                              # Priority 점수 + BRD 승인 여부
        th = soup.new_tag('th', style="padding: 6px 10px;")
        tr2.append(th)
    return [tr1, tr2]


def _make_table(soup: BeautifulSoup) -> tuple[Tag, Tag]:
    """colgroup이 있는 빈 table + tbody 반환."""
    table = soup.new_tag('table')
    colgroup = soup.new_tag('colgroup')
    for w in COL_WIDTHS:
        col = soup.new_tag('col', style=f"width: {w}.0px;")
        colgroup.append(col)
    table.append(colgroup)
    tbody = soup.new_tag('tbody')
    table.append(tbody)
    return table, tbody


# ─── 참조 문서 행 추출 ──────────────────────────────────────────────────────

def _find_hmg_doc1_ref_page(hmg_client: HmgConfluenceClient) -> str | None:
    """분기에 맞는 HMG Confluence 폴더에서 가장 최근 수정된 자식 페이지 ID 반환."""
    month = datetime.now().month
    folder_id = HMG_DOC1_FOLDER_Q4 if month >= 10 else HMG_DOC1_FOLDER_3Q
    try:
        pages = hmg_client.get_child_pages(folder_id)
        if not pages:
            print(f"  [hmg_doc1] 폴더 {folder_id} 자식 페이지 없음")
            return None
        latest = pages[0]  # sort=-modified → 첫 번째가 최신
        print(f"  [hmg_doc1] 최신 참조 페이지: {latest['title']} (id={latest['id']})")
        return latest["id"]
    except Exception as e:
        print(f"  [hmg_doc1] 폴더 탐색 실패: {e}")
        return None


def _load_ref_rows_doc1(hmg_client: HmgConfluenceClient) -> dict[str, list[str]]:
    """HMG Confluence 최신 주간 보고 페이지에서 티켓별 행 HTML 추출.
    Returns: {ticket_key: [row_html_str, ...]}
    참조 실패 시 빈 dict 반환 → 모든 티켓 새로 생성.
    """
    try:
        page_id = _find_hmg_doc1_ref_page(hmg_client)
        if not page_id:
            return {}
        html, _, title = hmg_client.get_page_storage(page_id)
        soup = BeautifulSoup(html, 'html.parser')
        result: dict[str, list[str]] = {}
        for a in soup.find_all('a', href=True):
            href = a.get('href', '')
            text = a.get_text(strip=True)
            m = _TICKET_PATTERN.search(href) or _TICKET_PATTERN.search(text)
            if not m:
                continue
            key = m.group()
            if key in result:
                continue
            tr = a.find_parent('tr')
            if not tr:
                continue
            first_td = tr.find(['td', 'th'])
            try:
                rowspan = int(first_td.get('rowspan', '1')) if first_td else 1
            except (ValueError, TypeError):
                rowspan = 1
            rows = [str(tr)]
            sib = tr.find_next_sibling('tr')
            for _ in range(rowspan - 1):
                if sib:
                    rows.append(str(sib))
                    sib = sib.find_next_sibling('tr')
            result[key] = rows
        print(f"  [ref_doc1] HMG '{title}'에서 {len(result)}건 추출")
        return result
    except Exception as e:
        print(f"  [ref_doc1] HMG 참조 조회 실패 → {e} (전체 새로 생성)")
        return {}


# ─── 내용 셀 빌더 ────────────────────────────────────────────────────────────

def _append_section(cell: Tag, soup: BeautifulSoup, label: str, content, linkify: bool = True):
    """<label> 헤더 + 불렛 리스트를 셀에 추가."""
    p_label = soup.new_tag('p')
    strong = soup.new_tag('strong')
    strong.string = f'<{label}>'
    p_label.append(strong)
    cell.append(p_label)

    ul = soup.new_tag('ul')
    if isinstance(content, list):
        items = [str(x).strip() for x in content if str(x).strip()]
    else:
        items = [line.strip() for line in str(content).split('\n') if line.strip()]
        if not items:
            items = [str(content).strip()]
    for item in items:
        li = soup.new_tag('li')
        if linkify:
            for node in _linkify(soup, item):
                li.append(node)
        else:
            li.string = item
        ul.append(li)
    cell.append(ul)


def _fill_pre_brd_content_cell(cell: Tag, ticket: dict, soup: BeautifulSoup):
    """Pre-BRD 내용 셀: 참조 문서 서식 기준
    - <Status> 태그 없음
    - status_info가 있으면 '※ ...' 비고 문단으로 표기
    - <Summary> → <배경> → <문제> → <개선/신규>
    """
    for child in list(cell.children):
        child.extract()

    # ※ 비고 (status_info 있을 때만)
    status_info = (ticket.get('status_info') or '').strip()
    if status_info:
        p_note = soup.new_tag('p')
        p_note.string = f'※ {status_info}'
        cell.append(p_note)

    # <Summary>
    summary = (ticket.get('summary_ko') or ticket.get('summary', '')).strip()
    if summary:
        _append_section(cell, soup, 'Summary', summary)

    # <배경>
    background = ticket.get('background', '')
    if background:
        _append_section(cell, soup, '배경', background)

    # <문제>
    problem = ticket.get('problem', '')
    if problem:
        _append_section(cell, soup, '문제', problem)

    # <기존 기능 개선> or <신규 기능>
    feature_label = ticket.get('feature_label') or '기존 기능 개선'
    feature = ticket.get('feature', '')
    if feature:
        _append_section(cell, soup, feature_label, feature)


def _fill_content_cell(cell: Tag, ticket: dict, soup: BeautifulSoup):
    """render_sample 호환 alias → _fill_post_brd_content_cell."""
    _fill_post_brd_content_cell(cell, ticket, soup)


def _fill_post_brd_content_cell(cell: Tag, ticket: dict, soup: BeautifulSoup):
    """Post-BRD 내용 셀: AI Doc1 서식 기준
    - <Status> 태그 유지
    - <Summary> → <배경> → <문제> → <개선/신규>
    """
    for child in list(cell.children):
        child.extract()

    feature_label = ticket.get('feature_label') or '기존 기능 개선'
    sections = [
        ('Status',      ticket.get('status_info') or ''),
        ('Summary',     ticket.get('summary_ko') or ticket.get('summary', '')),
        ('배경',        ticket.get('background', '')),
        ('문제',        ticket.get('problem', '')),
        (feature_label, ticket.get('feature', '')),
    ]
    for label, content in sections:
        if not content:
            continue
        _append_section(cell, soup, label, content)


# ─── 티켓 블록 빌더 ──────────────────────────────────────────────────────────

def _effective_brd(ticket: dict, include_brd: bool) -> str:
    """BRD 승인 여부 셀 텍스트 결정.
    Pre-BRD(cycle_number == 0) 티켓은 hold_code 판단 대상 제외.
    """
    if not include_brd:
        return '-'
    key = ticket.get('key', '')
    # 참조 문서 기준 오버라이드
    if key in _BRD_OV:
        return _BRD_OV[key]
    # rejection_code > hold_code > brd_approval 순
    # hold_code는 Post-BRD(cycle_number >= 1)에만 적용
    if ticket.get('rejection_code'):
        return '반려'
    is_prebrd = ticket.get('cycle_number', 0) == 0
    if ticket.get('hold_code') and not is_prebrd:
        return '보류'
    return BRD_DISPLAY.get(ticket.get('brd_approval', ''), '')


def _build_pre_brd_block(soup: BeautifulSoup, ticket: dict, seq_num: int) -> list[Tag]:
    """Pre-BRD 6행 블록 — 참조 문서 서식."""
    scores = ticket.get('scores', {})
    priority_text = _count_o(scores)
    brd_text = '-'

    rows = []
    tr1 = soup.new_tag('tr')
    tr1.append(_td(soup, seq_num, rowspan=6, center=True))
    tr1.append(_td(soup, cycle_label(ticket.get('cycle_number', 0)), rowspan=6, center=True))
    tr1.append(_td_link(soup, ticket.get('key', ''), rowspan=6, center=True))
    tr1.append(_td(soup, ticket.get('summary', ''), rowspan=6))
    tr1.append(_td_reporter(soup, ticket.get('reporter', ''), ticket.get('initiator', ''), rowspan=6, center=True))
    tr1.append(_td(soup, ticket.get('created', ''), rowspan=6))
    tr1.append(_td(soup, ticket.get('due_date', '') or '-', rowspan=6))

    content_td = soup.new_tag('td')
    content_td['rowspan'] = '6'
    _fill_pre_brd_content_cell(content_td, ticket, soup)
    tr1.append(content_td)

    # 항목 분포 3열: 항목 | — (셀프 없음) | O/X
    tr1.append(_td(soup, SCORE_LABELS[0]))
    tr1.append(_td(soup, '—'))
    tr1.append(_td(soup, _score_mark(scores.get(SCORE_KEYS[0], 0))))
    tr1.append(_td(soup, priority_text, rowspan=6, center=True))
    tr1.append(_td(soup, brd_text, rowspan=6, center=True))
    rows.append(tr1)

    for i in range(1, 6):
        tr = soup.new_tag('tr')
        tr.append(_td(soup, SCORE_LABELS[i]))
        tr.append(_td(soup, '—'))
        tr.append(_td(soup, _score_mark(scores.get(SCORE_KEYS[i], 0))))
        rows.append(tr)

    return rows


def _build_post_brd_normal_block(soup: BeautifulSoup, ticket: dict,
                                  seq_num: int) -> list[Tag]:
    """Post-BRD 일반 6행 블록 — 항목 분포 3열(항목|셀프|AI), 셀프/AI 색상 비교."""
    scores = ticket.get('scores', {})
    selfs  = ticket.get('self_scores') or {}
    det    = ticket.get('review_detail', {})
    brd_text = _effective_brd(ticket, include_brd=True)

    ai_total = sum(1 for k in SCORE_KEYS[1:] if float(scores.get(k, 0)) > 0)

    if selfs:
        self_total = selfs.get('self_total', '')
        matched    = sum(1 for k in SCORE_KEYS
                        if selfs.get(k) and selfs.get(k) == _score_mark(scores.get(k, 0)))
        comparable = sum(1 for k in SCORE_KEYS if selfs.get(k))
        priority_text = f"셀프 {self_total} / AI {ai_total}\n(항목 일치 {matched}/{comparable})"
    else:
        priority_text = str(ai_total)

    def _row_cells(i):
        key = SCORE_KEYS[i]
        s = selfs.get(key) if selfs else None   # 'O' | 'X' | None
        a = _score_mark(scores.get(key, 0))
        a_text = a + (f" ({det[key]})" if key in det else "")
        if s is None:
            return [_td(soup, SCORE_LABELS[i]), _mark_td(soup, '—'), _mark_td(soup, a_text)]
        bg = MATCH_BG if s == a else MISMATCH_BG
        return [_td(soup, SCORE_LABELS[i]), _mark_td(soup, s, bg), _mark_td(soup, a_text, bg)]

    rows = []
    tr1 = soup.new_tag('tr')
    tr1.append(_td(soup, seq_num, rowspan=6, center=True))
    tr1.append(_td(soup, cycle_label(ticket.get('cycle_number', 0)), rowspan=6, center=True))
    tr1.append(_td_link(soup, ticket.get('key', ''), rowspan=6, center=True))
    tr1.append(_td(soup, ticket.get('summary', ''), rowspan=6))
    tr1.append(_td_reporter(soup, ticket.get('reporter', ''), ticket.get('initiator', ''), rowspan=6, center=True))
    tr1.append(_td(soup, ticket.get('created', ''), rowspan=6))
    tr1.append(_td(soup, ticket.get('due_date', '') or '-', rowspan=6))

    content_td = soup.new_tag('td')
    content_td['rowspan'] = '6'
    _fill_post_brd_content_cell(content_td, ticket, soup)
    tr1.append(content_td)

    # Priority 점수 셀 — 멀티라인 지원
    pt = soup.new_tag('td', style="padding: 14px 10px; line-height: 1.6;")
    pt['rowspan'] = '6'
    for line in priority_text.split('\n'):
        p = soup.new_tag('p')
        p.string = line
        pt.append(p)

    for c in _row_cells(0):
        tr1.append(c)
    tr1.append(pt)
    tr1.append(_td(soup, brd_text, rowspan=6, center=True))
    rows.append(tr1)

    for i in range(1, 6):
        tr = soup.new_tag('tr')
        for c in _row_cells(i):
            tr.append(c)
        rows.append(tr)

    return rows


def _build_fast_track_block(soup: BeautifulSoup, ticket: dict,
                             seq_num: int) -> list[Tag]:
    """Fast Track (Urgent Request) 2행 블록 — 참조 문서 기준.
    항목 분포 없이 BRD 승인 여부만 표기.
    """
    brd_text = _effective_brd(ticket, include_brd=True)

    # 내용 셀: ※ 형식 (참조 문서 기준) — <Status> 태그 사용 안 함
    content_td = soup.new_tag('td')
    content_td['rowspan'] = '2'
    _fill_pre_brd_content_cell(content_td, ticket, soup)

    tr1 = soup.new_tag('tr')
    tr1.append(_td(soup, seq_num, rowspan=2, center=True))
    tr1.append(_td(soup, cycle_label(ticket.get('cycle_number', 0)), rowspan=2, center=True))
    tr1.append(_td_link(soup, ticket.get('key', ''), rowspan=2, center=True))
    tr1.append(_td(soup, ticket.get('summary', ''), rowspan=2))
    tr1.append(_td_reporter(soup, ticket.get('reporter', ''), ticket.get('initiator', ''), rowspan=2, center=True))
    tr1.append(_td(soup, ticket.get('created', ''), rowspan=2))
    tr1.append(_td(soup, ticket.get('due_date', '') or '-', rowspan=2))
    tr1.append(content_td)
    # 항목 분포 3열 span (빈 셀)
    empty_dist = soup.new_tag('td')
    empty_dist['colspan'] = '3'
    empty_dist['rowspan'] = '2'
    p_empty = soup.new_tag('p')
    p_empty.string = ''
    empty_dist.append(p_empty)
    tr1.append(empty_dist)
    # Priority 점수 (빈)
    tr1.append(_td(soup, '', rowspan=2, center=True))
    # BRD 승인 여부
    tr1.append(_td(soup, brd_text, rowspan=2, center=True))

    tr2 = soup.new_tag('tr')

    return [tr1, tr2]


def _build_group_ticket_block(soup: BeautifulSoup, ticket: dict,
                               seq_num: int) -> list[Tag]:
    """그룹 티켓 2행 블록 — 참조 문서 기준.
    BRD 심사 불필요. 항목 분포 없음.
    """
    subtask_keys = ticket.get('subtask_keys', [])

    content_td = soup.new_tag('td')
    content_td['rowspan'] = '2'

    # ※ 그룹 티켓 비고
    p_note = soup.new_tag('p')
    p_note.string = '※ 그룹 티켓으로 BRD 작성 및 심사(스코어링) 불필요'
    content_td.append(p_note)

    # <배경> — description 활용
    background = ticket.get('background', '') or ticket.get('description', '')
    if background:
        _append_section(content_td, soup, '배경', background)

    # <티켓 목록>
    if subtask_keys:
        p_label = soup.new_tag('p')
        strong = soup.new_tag('strong')
        strong.string = '<티켓 목록>'
        p_label.append(strong)
        content_td.append(p_label)
        ul = soup.new_tag('ul')
        for sk in subtask_keys:
            li = soup.new_tag('li')
            for node in _linkify(soup, sk):
                li.append(node)
            ul.append(li)
        content_td.append(ul)

    tr1 = soup.new_tag('tr')
    tr1.append(_td(soup, seq_num, rowspan=2, center=True))
    tr1.append(_td(soup, cycle_label(ticket.get('cycle_number', 0)), rowspan=2, center=True))
    tr1.append(_td_link(soup, ticket.get('key', ''), rowspan=2, center=True))
    tr1.append(_td(soup, ticket.get('summary', ''), rowspan=2))
    tr1.append(_td_reporter(soup, ticket.get('reporter', ''), ticket.get('initiator', ''), rowspan=2, center=True))
    tr1.append(_td(soup, ticket.get('created', ''), rowspan=2))
    tr1.append(_td(soup, ticket.get('due_date', '') or '-', rowspan=2))
    tr1.append(content_td)
    # 항목 분포 3열 span (빈 셀)
    empty_dist = soup.new_tag('td')
    empty_dist['colspan'] = '3'
    empty_dist['rowspan'] = '2'
    p_empty = soup.new_tag('p')
    p_empty.string = ''
    empty_dist.append(p_empty)
    tr1.append(empty_dist)
    # Priority 점수 (빈)
    tr1.append(_td(soup, '', rowspan=2, center=True))
    # BRD 승인 여부: "-"
    tr1.append(_td(soup, '-', rowspan=2, center=True))

    tr2 = soup.new_tag('tr')

    return [tr1, tr2]


def _build_post_brd_block(soup: BeautifulSoup, ticket: dict,
                           seq_num: int) -> list[Tag]:
    """티켓 타입에 따라 적절한 블록 빌더로 라우팅."""
    if ticket.get('is_group'):
        return _build_group_ticket_block(soup, ticket, seq_num)
    if ticket.get('is_fast_track'):
        return _build_fast_track_block(soup, ticket, seq_num)
    return _build_post_brd_normal_block(soup, ticket, seq_num)


def _build_ticket_block(soup: BeautifulSoup, ticket: dict,
                         seq_num: int, include_brd: bool = True) -> list[Tag]:
    """render_sample 호환 alias → _build_post_brd_block."""
    return _build_post_brd_block(soup, ticket, seq_num)


# ─── 표 빌더 ─────────────────────────────────────────────────────────────────

def _build_pre_brd_table(soup: BeautifulSoup, pre_brd: list[dict],
                          ref_rows: dict | None = None) -> Tag:
    table, tbody = _make_table(soup)
    for hr in _header_row(soup):
        tbody.append(hr)
    seq = 0
    for ticket in pre_brd:
        seq += 1
        for row in _build_pre_brd_block(soup, ticket, seq):
            tbody.append(row)
    return table


def _build_post_brd_table(soup: BeautifulSoup, post_brd: list[dict],
                           offset: int, ref_rows: dict | None = None) -> Tag:
    table, tbody = _make_table(soup)
    for hr in _header_row(soup):
        tbody.append(hr)
    seq = offset
    for ticket in post_brd:
        seq += 1
        for row in _build_post_brd_block(soup, ticket, seq):
            tbody.append(row)
    return table


# ─── Pending 관리 ────────────────────────────────────────────────────────────

def _has_deployment_label(labels: list) -> bool:
    """배포 완료 레이블 여부: '배포' 포함 AND '배포영향' 미포함."""
    for label in labels:
        if "배포" in label and "배포영향" not in label:
            return True
    return False


def _infer_deployment_needed(status: str) -> str:
    """'배포 필요' 추론: 취소·종료·해결됨 계열 → X, 그 외 진행 중 → O."""
    return "X" if status in _NO_DEPLOY_STATUSES else "O"


def _filter_pending_tickets(tickets: list[dict]) -> list[dict]:
    """Pending 관리 필터: KR 티켓 중 end_date가 오늘 이전 AND 배포 레이블 없는 티켓."""
    today_str = date.today().isoformat()
    result = []
    for t in tickets:
        if t.get("region") != "KR":
            continue
        end_date = t.get("end_date", "")
        if not end_date or end_date >= today_str:
            continue
        if _has_deployment_label(t.get("labels", [])):
            continue
        result.append(t)
    return sorted(result, key=lambda t: t.get("end_date", ""))


def _build_pending_table(soup: BeautifulSoup, tickets: list[dict],
                         jira_client=None) -> Tag:
    """Pending 관리 표 빌드 (9열).

    jira_client: JiraClient 인스턴스 — 진척사항 확인(댓글) 조회에 사용.
                 None이면 내부에서 생성.
    """
    if jira_client is None:
        from jira_client import JiraClient
        jira_client = JiraClient()

    table = soup.new_tag('table')
    colgroup = soup.new_tag('colgroup')
    for w in PENDING_COL_WIDTHS:
        col = soup.new_tag('col', style=f"width: {w}.0px;")
        colgroup.append(col)
    table.append(colgroup)

    tbody = soup.new_tag('tbody')

    # 헤더 행
    tr_h = soup.new_tag('tr')
    for h in PENDING_HEADERS:
        th = soup.new_tag('th', style="padding: 14px 10px; text-align: center;")
        p = soup.new_tag('p')
        strong = soup.new_tag('strong')
        strong.string = h
        p.append(strong)
        th.append(p)
        tr_h.append(th)
    tbody.append(tr_h)

    for i, ticket in enumerate(tickets):
        key    = ticket.get('key', '')
        status = ticket.get('status', '')

        # 진척사항 확인: Jira 최신 댓글 3개
        comments_raw = jira_client.get_own_comments(key, max_comments=3)
        comment_lines = [ln.strip() for ln in comments_raw.splitlines() if ln.strip()]

        # 배포 필요: 상태 기반 추론
        deploy_needed = _infer_deployment_needed(status)

        tr = soup.new_tag('tr')

        # 단순 텍스트 셀 (인덱스 0, 2~6)
        simple_vals = {
            0: str(i + 1),
            2: ticket.get('summary', ''),
            3: ticket.get('reporter', ''),
            4: status,
            5: ticket.get('created', ''),
            6: ticket.get('end_date', '') or '-',
            8: deploy_needed,
        }
        for j in range(9):
            base_style = "padding: 14px 10px; line-height: 1.6;"
            style = base_style if j == 7 else base_style + " text-align: center;"
            td = soup.new_tag('td', style=style)
            if j == 1:
                # Key 컬럼: 링크
                p = soup.new_tag('p')
                a = soup.new_tag('a', href=f"{JIRA_BROWSE}/{key}")
                a.string = key
                p.append(a)
                td.append(p)
            elif j == 3:
                # Reporter + 발의자
                p = soup.new_tag('p')
                p.string = ticket.get('reporter', '')
                td.append(p)
                initiator = ticket.get('initiator', '')
                if initiator:
                    p_i = soup.new_tag('p')
                    em = soup.new_tag('em')
                    em.string = f"(발의: {initiator})"
                    p_i.append(em)
                    td.append(p_i)
            elif j == 7:
                # 진척사항 확인: 댓글 불렛 리스트
                if comment_lines:
                    ul = soup.new_tag('ul')
                    for line in comment_lines:
                        li = soup.new_tag('li')
                        li.string = line
                        ul.append(li)
                    td.append(ul)
                else:
                    p = soup.new_tag('p')
                    p.string = '-'
                    td.append(p)
            else:
                p = soup.new_tag('p')
                p.string = simple_vals[j]
                td.append(p)
            tr.append(td)

        tbody.append(tr)

    table.append(tbody)
    return table


# ─── 티켓 전처리 ─────────────────────────────────────────────────────────────

def _apply_overrides(tickets: list[dict]) -> list[dict]:
    """ticket_overrides.json 기준 오버라이드 적용 및 제외 처리."""
    result = []
    for t in tickets:
        key = t.get('key', '')
        if key in _EXCLUDED_KEYS:
            print(f"  [override] {key}: 제외 (excluded_keys)")
            continue
        if key in _CYCLE_OV:
            old = t.get('cycle_number', 0)
            t = {**t, 'cycle_number': _CYCLE_OV[key]}
            print(f"  [override] {key}: cycle_number {old} → {_CYCLE_OV[key]}")
        result.append(t)
    return result


def _split_tickets(tickets: list[dict]) -> tuple[list[dict], list[dict]]:
    """Pre-BRD / Post-BRD 분리 + 정렬 (created 오름차순)."""
    pre = sorted(
        [t for t in tickets if t.get('cycle_number', 0) == 0],
        key=lambda t: t.get('created', '')
    )
    post = sorted(
        [t for t in tickets if t.get('cycle_number', 0) > 0],
        key=lambda t: t.get('created', '')
    )
    return pre, post


# ─── 마스터 페이지 헬퍼 ──────────────────────────────────────────────────────

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
        print(f"[Doc1] 스냅샷 생성: {snapshot_title}")
    except Exception as e:
        print(f"[Doc1] 스냅샷 생성 실패 (계속 진행): {e}")


def _get_weekly_page_title() -> str:
    """이번 주 월요일 날짜 기반 Doc1 페이지 제목. 형식: 'M/D KKR OneApp'"""
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    return f"{monday.month}/{monday.day} KKR OneApp"


def _find_weekly_page(client: ConfluenceClient,
                      folder_id: str, title: str) -> tuple[str | None, int]:
    """폴더 내 title과 일치하는 주간 페이지 탐색. 반환: (page_id, version)"""
    cursor: str | None = None
    while True:
        params: dict = {"parentId": folder_id, "limit": 50}
        if cursor:
            params["cursor"] = cursor
        data = client._get("/pages", params=params)
        for page in data.get("results", []):
            if page["title"] == title:
                _, version, _ = client.get_page_storage(page["id"])
                return page["id"], version
        nxt = data.get("_links", {}).get("next", "")
        if not nxt:
            break
        for part in nxt.split("&"):
            if "cursor=" in part:
                cursor = part.split("cursor=")[-1]
                break
        else:
            break
    return None, 0


# ─── 변경 감지 / 서브페이지 ──────────────────────────────────────────────────

def _detect_ticket_changes(kr_tickets: list[dict], prev_tickets: list[dict]) -> dict:
    """현재 KR 티켓 vs 이전 실행 전체 티켓 비교. 신규/상태변경 분류."""
    prev_map = {t.get('key'): t for t in prev_tickets if t.get('key')}
    new_tickets: list = []
    changed_tickets: list = []
    for t in kr_tickets:
        key = t.get('key')
        if not key:
            continue
        pt = prev_map.get(key)
        if pt is None:
            new_tickets.append(t)
        else:
            curr_eff = _effective_brd(t, include_brd=True)
            prev_eff = _effective_brd(pt, include_brd=True)
            curr_status = t.get('status', '')
            prev_status = pt.get('status', '')
            diffs: dict = {}
            if curr_eff and prev_eff and curr_eff != prev_eff:
                diffs['brd'] = {'from': prev_eff, 'to': curr_eff}
            if curr_status and prev_status and curr_status != prev_status:
                diffs['status'] = {'from': prev_status, 'to': curr_status}
            if diffs:
                changed_tickets.append({'ticket': t, 'changes': diffs})
    return {'new': new_tickets, 'changed': changed_tickets}


def _build_changes_subpage_html(changes: dict, timestamp: str) -> str:
    """일별 변경사항 서브페이지 HTML."""
    new_tickets = changes.get('new', [])
    changed_tickets = changes.get('changed', [])
    parts = [f'<p><em>{timestamp} 기준 변경사항</em></p>']
    if not new_tickets and not changed_tickets:
        parts.append('<p>변경사항 없음</p>')
        return '\n'.join(parts)
    if new_tickets:
        parts.append(f'<h2>신규 티켓 ({len(new_tickets)}건)</h2><ul>')
        for t in sorted(new_tickets, key=lambda x: x.get('created', '')):
            key = t.get('key', '')
            eff = _effective_brd(t, include_brd=True)
            parts.append(
                f'<li><a href="{JIRA_BROWSE}/{key}">{key}</a> — {t.get("summary", "")}'
                f' | {cycle_label(t.get("cycle_number", 0))}'
                + (f' | {eff}' if eff else '') + '</li>'
            )
        parts.append('</ul>')
    if changed_tickets:
        parts.append(f'<h2>상태 변경 ({len(changed_tickets)}건)</h2><ul>')
        for item in changed_tickets:
            t = item['ticket']
            ch = item['changes']
            key = t.get('key', '')
            desc = []
            if 'brd' in ch:
                desc.append(f"BRD: {ch['brd']['from']} → {ch['brd']['to']}")
            if 'status' in ch:
                desc.append(f"상태: {ch['status']['from']} → {ch['status']['to']}")
            parts.append(
                f'<li><a href="{JIRA_BROWSE}/{key}">{key}</a> — {t.get("summary", "")}'
                f' | {", ".join(desc)}</li>'
            )
        parts.append('</ul>')
    return '\n'.join(parts)


# ─── 전체 재빌드 ─────────────────────────────────────────────────────────────

def update(tickets_with_analysis: list[dict], client: ConfluenceClient | None = None,
           as_of: str | None = None, jira_client=None,
           prev_tickets: list[dict] | None = None):
    if client is None:
        client = ConfluenceClient()

    active_cycle = get_active_cycle()

    # 오버라이드 적용 → KR 권역, 전체 회차 포함
    all_tickets = _apply_overrides(tickets_with_analysis)
    kr_tickets = [t for t in all_tickets if t.get("region") == "KR"]

    # Pre-BRD / Post-BRD 분리
    pre_brd, post_brd = _split_tickets(kr_tickets)
    all_post_cycles = sorted({t.get('cycle_number', 0) for t in post_brd if t.get('cycle_number', 0) > 0})
    current_tickets = [t for t in post_brd if t.get('cycle_number', 0) == active_cycle]

    # Feature 1: HMG Confluence에서 이전 티켓 행 추출
    hmg_client = HmgConfluenceClient()
    ref_rows = _load_ref_rows_doc1(hmg_client)

    now = datetime.now()
    soup = BeautifulSoup("", 'html.parser')

    # 업데이트 노트 (맨 위)
    note_p = soup.new_tag('p')
    em_tag = soup.new_tag('em')
    em_tag.string = (f"{now.strftime('%Y-%m-%d %H:%M')} 업데이트 "
                     f"({active_cycle}회차 기준, 총 {len(kr_tickets)}건, 이번 회차 {len(current_tickets)}건)")
    note_p.append(em_tag)
    soup.append(note_p)

    # 목차
    toc = BeautifulSoup(
        '<ac:structured-macro ac:name="toc" ac:schema-version="1">'
        '<ac:parameter ac:name="style">none</ac:parameter>'
        '</ac:structured-macro>', 'html.parser')
    soup.append(toc)

    # h1: New/Improvement
    h1 = soup.new_tag('h1')
    h1.string = TABLE_TITLE
    soup.append(h1)

    # Pre-BRD 섹션
    if pre_brd:
        h2_pre = soup.new_tag('h2')
        h2_pre.string = SECTION_PRE
        soup.append(h2_pre)
        soup.append(_build_pre_brd_table(soup, pre_brd, ref_rows=ref_rows))

    # Post-BRD 섹션 (회차별 h3 구분)
    h2_post = soup.new_tag('h2')
    h2_post.string = SECTION_POST
    soup.append(h2_post)

    post_offset = 0
    for cn in all_post_cycles:
        cycle_tickets = sorted(
            [t for t in post_brd if t.get('cycle_number', 0) == cn],
            key=lambda t: t.get('created', '')
        )
        h3 = soup.new_tag('h3')
        h3.string = cycle_label(cn)
        soup.append(h3)
        soup.append(_build_post_brd_table(soup, cycle_tickets, offset=post_offset, ref_rows=ref_rows))
        post_offset += len(cycle_tickets)

    # h1: Pending 관리 — 2026-01-01 이후 티켓만 (end_date 기준 필터 적용)
    if jira_client is not None:
        from cycle import get_cycle_number
        from datetime import date as _date
        _today = _date.today()
        _raw = jira_client.get_new_improvement_tickets(extra_jql='created >= "2026-01-01"')
        for t in _raw:
            created = _date.fromisoformat(t["created"]) if t.get("created") else _today
            t["cycle_number"] = get_cycle_number(created)
        _pending_source = _apply_overrides(_raw)
    else:
        _pending_source = all_tickets
    pending_tickets = _filter_pending_tickets(_pending_source)
    h1_pending = soup.new_tag('h1')
    h1_pending.string = 'Pending 관리'
    soup.append(h1_pending)

    p_label = soup.new_tag('p')
    strong_label = soup.new_tag('strong')
    strong_label.string = f'[New/Improvement] - {len(pending_tickets)}건'
    p_label.append(strong_label)
    soup.append(p_label)

    soup.append(_build_pending_table(soup, pending_tickets, jira_client=None))
    print(f"[Doc1] Pending 관리: {len(pending_tickets)}건")

    # 면책 문구
    p_disclaimer = soup.new_tag('p')
    em = soup.new_tag('em')
    em.string = ('⚠ 본 표의 \"진척사항 확인\" 및 \"배포 필요\" 항목은 Jira 댓글과 상태값을 기반으로 '
                 'AI가 자동 생성하였으며, 실제 상황과 다를 수 있습니다. 담당자가 직접 확인 후 수정하시기 바랍니다.')
    p_disclaimer.append(em)
    soup.append(p_disclaimer)

    # 이번 주 페이지 제목 (월요일 기준) + 탐색 후 업데이트/생성
    page_title = _get_weekly_page_title()
    timestamp = as_of if as_of else now.strftime("%m-%d %H:%M")
    page_id, page_version = _find_weekly_page(client, DOC_PAGE_IDS["doc1"], page_title)
    if page_id:
        client.update_page(page_id, page_title, str(soup), page_version,
                           message=f"{timestamp} 업데이트: {len(kr_tickets)}건")
        print(f"[Doc1] 주간 페이지 업데이트 ({page_title}: {len(kr_tickets)}건, id={page_id})")
    else:
        result = client.create_page(DOC_PAGE_IDS["doc1"], page_title, str(soup))
        page_id = result.get("id", "")
        print(f"[Doc1] 주간 페이지 생성 ({page_title}: {len(kr_tickets)}건, id={page_id})")

    # 일별 변경사항 서브페이지 (이전 실행 데이터가 있을 때만)
    if prev_tickets and page_id:
        changes = _detect_ticket_changes(kr_tickets, prev_tickets)
        today = date.today()
        sub_title = f"{today.month}/{today.day} 업데이트"
        sub_html = _build_changes_subpage_html(changes, now.strftime('%Y-%m-%d %H:%M'))
        sub_id, sub_ver = _find_weekly_page(client, page_id, sub_title)
        if sub_id:
            client.update_page(sub_id, sub_title, sub_html, sub_ver,
                               message=f"{timestamp} 재업데이트")
        else:
            client.create_page(page_id, sub_title, sub_html)
        total_ch = len(changes['new']) + len(changes['changed'])
        print(f"[Doc1] 변경사항 서브페이지 {'업데이트' if sub_id else '생성'}: {sub_title} "
              f"(신규 {len(changes['new'])}건, 변경 {len(changes['changed'])}건)")
