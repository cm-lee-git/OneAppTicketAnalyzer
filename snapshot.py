"""
회차별 마감 히스토리 스냅샷 모듈

실행 시점: 각 회차 마감일(금요일) 다음날 15:00
동작:
  1. 어제가 회차 마감일인지 확인
  2. 맞으면 현재 티켓 현황을 cycle_snapshots.json에 저장
  3. 틀리면 종료 (스케줄러가 매일 실행해도 안전)
"""
import json
from datetime import date
from pathlib import Path

from cycle import get_cycle_bounds, get_cycle_number, ANCHOR
from jira_client import JiraClient
from analyzer import analyze_tickets_batch
from doc2_updater import _KR_REGIONS, _EU_REGIONS, _HQ_REGIONS, _c, _track_label, GREY, _effective_approval
from config import DOC_PAGE_IDS
from confluence_client import ConfluenceClient

SNAPSHOT_FILE = Path(__file__).parent / "cycle_snapshots.json"


def _is_cycle_end_today() -> int | None:
    """어제가 어떤 회차의 마감일이면 회차 번호 반환, 아니면 None.
    (스냅샷은 마감일 다음날 15:00에 실행되므로 어제 기준으로 판별)
    """
    from datetime import timedelta
    yesterday = date.today() - timedelta(days=1)
    if yesterday < ANCHOR:
        return None
    n = 1
    while True:
        start, end = get_cycle_bounds(n)
        if end == yesterday:
            return n
        if start > yesterday:
            return None
        n += 1


def load_snapshots() -> dict:
    if SNAPSHOT_FILE.exists():
        return json.loads(SNAPSHOT_FILE.read_text(encoding="utf-8"))
    return {}


def _save_snapshots(data: dict):
    SNAPSHOT_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _cnt(tickets, region_set, approval=None):
    result = [t for t in tickets if t.get("region") in region_set]
    if approval:
        if isinstance(approval, list):
            result = [t for t in result if _effective_approval(t) in approval]
        else:
            result = [t for t in result if _effective_approval(t) == approval]
    return len(result)


DOC11_TITLE_FMT = "{timestamp} 회차별 마감 히스토리 (AI 생성)"  # timestamp: MM-DD HH:MM

# 열 너비 (13열: 회차 + KR×4 + EU×4 + HQ×4)
_HIST_CW = [122, 108, 87, 92, 71, 90, 85, 106, 83, 98, 81, 92, 92]
_BOLD_WHITE = "#b3bac5"


def _build_history_html(snapshots: dict) -> str:
    """스냅샷 딕셔너리 → 회차별 마감 히스토리 표 HTML."""
    from doc2_updater import _colgroup, CW

    # 헤더 3행
    h1 = (
        "<tr>"
        + _c("th", "", bg=GREY, rs=3)
        + _c("th", "RHQ", bg=GREY, cs=8, bold_white=True)
        + _c("th", "HQ",  bg=GREY, cs=4, bold_white=True)
        + "</tr>"
    )
    h2 = (
        "<tr>"
        + _c("td", "KR",             bg=GREY, cs=4, bold_white=True)
        + _c("td", "EU",             bg=GREY, cs=4, bold_white=True)
        + _c("td", "GBCXD 및 타부문", bg=GREY, cs=4, bold_white=True)
        + "</tr>"
    )
    items = ["인입", "마감 시점 승인", "마감 시점 반려", "마감 시점 보류"]
    h3 = "<tr>" + "".join(_c("td", it, bg=GREY, bold_white=True) for it in items * 3) + "</tr>"

    # 데이터 행 (회차 오름차순)
    data_rows = []
    for cn_str in sorted(snapshots.keys(), key=int):
        snap = snapshots[cn_str]
        cn = int(cn_str)

        def v(region, field):
            return str(snap.get(region, {}).get(field, "-"))

        data_rows.append(
            "<tr>"
            + _c("td", _track_label(cn))
            + _c("td", v("KR", "total"))    + _c("td", v("KR", "approved"))
            + _c("td", v("KR", "rejected")) + _c("td", v("KR", "pending"))
            + _c("td", v("EU", "total"))    + _c("td", v("EU", "approved"))
            + _c("td", v("EU", "rejected")) + _c("td", v("EU", "pending"))
            + _c("td", v("HQ", "total"))    + _c("td", v("HQ", "approved"))
            + _c("td", v("HQ", "rejected")) + _c("td", v("HQ", "pending"))
            + "</tr>"
        )

    cols = "".join(f'<col style="width: {w}.0px;"/>' for w in _HIST_CW)
    colgroup = f"<colgroup>{cols}</colgroup>"
    body = "".join([h1, h2, h3] + data_rows)
    table = f"<table>{colgroup}<tbody>{body}</tbody></table>"

    toc = (
        '<ac:structured-macro ac:name="toc" ac:schema-version="1">'
        '<ac:parameter ac:name="style">none</ac:parameter>'
        '</ac:structured-macro>'
    )
    return toc + "<h1>회차별 마감 히스토리</h1>" + table


def _create_doc21_page(client: ConfluenceClient, html: str, as_of: str | None = None):
    """Doc2-1 페이지를 타임스탬프 제목으로 새로 생성 (Doc1/Doc2와 동일 방식)."""
    from datetime import datetime as _dt
    timestamp = as_of if as_of else _dt.now().strftime("%m-%d %H:%M")
    title = DOC11_TITLE_FMT.format(timestamp=timestamp)
    parent_id = DOC_PAGE_IDS["doc21"]
    result = client.create_page(parent_id, title, html)
    print(f"[Doc2-1] 새 페이지 생성: {title}  (id={result.get('id', '')})")


def take_snapshot(force_cycle: int | None = None, as_of: str | None = None):
    """
    force_cycle: 테스트용 — 특정 회차 번호를 강제 지정 (None이면 오늘 날짜 자동 판별)
    """
    cycle_n = force_cycle if force_cycle is not None else _is_cycle_end_today()
    if cycle_n is None:
        from datetime import timedelta
        yesterday = date.today() - timedelta(days=1)
        print(f"[Snapshot] {yesterday} 는 회차 마감일이 아닙니다. 종료.")
        return

    start, end = get_cycle_bounds(cycle_n)
    print(f"[Snapshot] {cycle_n}회차 마감 스냅샷 생성 ({start}~{end})")

    jira = JiraClient()
    tickets = jira.get_new_improvement_tickets(
        extra_jql=f'created >= "2026-01-01" AND created <= "{end}"'
    )

    # cycle_number 부여
    from datetime import date as _date
    for t in tickets:
        created = _date.fromisoformat(t["created"]) if t.get("created") else _date.today()
        t["cycle_number"] = get_cycle_number(created)

    # Claude 분석 (rejection_code/hold_code 확보)
    print(f"[Snapshot] Claude 분석 시작 ({len(tickets)}건)...")
    tickets = analyze_tickets_batch(tickets)
    print(f"[Snapshot] Claude 분석 완료")

    # 테스트/예시 티켓 제외
    from main import _apply_test_filter
    tickets = _apply_test_filter(tickets)

    # 해당 회차 티켓
    cyc = [t for t in tickets if t.get("cycle_number") == cycle_n]
    pend = ["보류"]

    def cnt(region_set, appr=None):
        return _cnt(cyc, region_set, appr)

    snapshot = {
        "cycle_number":  cycle_n,
        "snapshot_date": date.today().isoformat(),
        "KR": {
            "total":    cnt(_KR_REGIONS),
            "approved": cnt(_KR_REGIONS, "Approved"),
            "rejected": cnt(_KR_REGIONS, "반려"),
            "pending":  cnt(_KR_REGIONS, pend),
        },
        "EU": {
            "total":    cnt(_EU_REGIONS),
            "approved": cnt(_EU_REGIONS, "Approved"),
            "rejected": cnt(_EU_REGIONS, "반려"),
            "pending":  cnt(_EU_REGIONS, pend),
        },
        "HQ": {
            "total":    cnt(_HQ_REGIONS),
            "approved": cnt(_HQ_REGIONS, "Approved"),
            "rejected": cnt(_HQ_REGIONS, "반려"),
            "pending":  cnt(_HQ_REGIONS, pend),
        },
    }

    snapshots = load_snapshots()
    snapshots[str(cycle_n)] = snapshot
    _save_snapshots(snapshots)
    print(f"[Snapshot] 저장 완료 → {SNAPSHOT_FILE}")
    for rk in ("KR", "EU", "HQ"):
        s = snapshot[rk]
        print(f"  {rk}: 인입={s['total']} 승인={s['approved']} 반려={s['rejected']} 보류={s['pending']}")

    # Doc2와 일치 확인 (tickets_analyzed_latest.json 기준)
    latest_path = Path(__file__).parent / "tickets_analyzed_latest.json"
    if latest_path.exists():
        doc2_all = json.loads(latest_path.read_text(encoding="utf-8"))
        doc2_cyc = [t for t in doc2_all if t.get("cycle_number") == cycle_n]
        mismatch = False
        for rk, region_set in [("KR", _KR_REGIONS), ("EU", _EU_REGIONS), ("HQ", _HQ_REGIONS)]:
            d2_total    = _cnt(doc2_cyc, region_set)
            d2_approved = _cnt(doc2_cyc, region_set, "Approved")
            d2_rejected = _cnt(doc2_cyc, region_set, "반려")
            d2_pending  = _cnt(doc2_cyc, region_set, ["보류"])
            s = snapshot[rk]
            if (s["total"] != d2_total or s["approved"] != d2_approved
                    or s["rejected"] != d2_rejected or s["pending"] != d2_pending):
                mismatch = True
                print(f"  [경고] {rk} Doc2 불일치: "
                      f"인입 snap={s['total']} doc2={d2_total} / "
                      f"승인 snap={s['approved']} doc2={d2_approved} / "
                      f"반려 snap={s['rejected']} doc2={d2_rejected} / "
                      f"보류 snap={s['pending']} doc2={d2_pending}")
        if not mismatch:
            print("  [확인] Doc2와 수치 일치 ✓")
    else:
        print("  [경고] tickets_analyzed_latest.json 없음 — Doc2 일치 확인 불가")

    # Doc2-1 페이지 새로 생성
    html = _build_history_html(snapshots)
    client = ConfluenceClient()
    _create_doc21_page(client, html, as_of=as_of)
