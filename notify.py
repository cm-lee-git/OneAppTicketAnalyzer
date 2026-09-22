"""
KCCIVOC / KEUVOCOP Jira 변경 알림 스크립트
- 매일 16:00 KST 1회 실행 (Windows 작업 스케줄러)
- 당일(00:00 KST~실행 시각) 변경된 상태·새 댓글만 수집 → 프로젝트별 이메일 발송
- KCCIVOC → haesoo@innocean.com / KEUVOCOP → jaekim98@innocean.com
- 발신: cmlee@innocean.com (로컬 Outlook COM 사용)
"""
import json
import os
from datetime import datetime, date, timezone, timedelta
from pathlib import Path

KST = timezone(timedelta(hours=9))   # 한국 표준시

import requests
from dotenv import load_dotenv
from requests.auth import HTTPBasicAuth

load_dotenv()

# ── 설정 ───────────────────────────────────────────────────────────
JIRA_BASE   = "https://hmg.atlassian.net/rest/api/3"
JIRA_EMAIL  = os.getenv("JIRA_EMAIL")
JIRA_TOKEN  = os.getenv("JIRA_API_TOKEN")
JIRA_AUTH   = HTTPBasicAuth(JIRA_EMAIL, JIRA_TOKEN)
JIRA_BROWSE = "https://hmg.atlassian.net/browse"

SMTP_USER  = os.getenv("SMTP_USER", "cmlee@innocean.com")   # 발신 주소 (Outlook에 로그인된 계정)

# 프로젝트별 수신자
PROJECT_RECIPIENTS: dict[str, list[str]] = {
    "KCCIVOC":  ["haesoo@innocean.com"],
    "KEUVOCOP": ["jaekim98@innocean.com"],
}

PROJECTS    = list(PROJECT_RECIPIENTS.keys())
STATE_FILE  = Path(__file__).parent / "notify_state.json"

# 알림할 상태 변경 (빈 set이면 모든 변경 알림)
WATCH_STATUS_CHANGES: set[str] = set()


# ── 상태 파일 ──────────────────────────────────────────────────────
def _load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    # 최초 실행: 어제 16시 KST부터 (하루치 보장)
    default_since = (datetime.now(KST).replace(hour=16, minute=0, second=0, microsecond=0)
                     - timedelta(days=1)).isoformat()
    return {"last_notification_time": default_since, "seen_comments": {}}


def _save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


# ── Jira 헬퍼 ─────────────────────────────────────────────────────
def _extract_text(doc) -> str:
    """ADF → 평문 변환 (text / mention / hardBreak 처리)."""
    if not doc:
        return ""
    if isinstance(doc, str):
        return doc
    texts = []
    def walk(node):
        if isinstance(node, dict):
            t = node.get("type", "")
            if t == "text":
                texts.append(node.get("text", ""))
            elif t == "mention":
                texts.append(node.get("attrs", {}).get("text", ""))
            elif t == "hardBreak":
                texts.append("\n")
            for child in node.get("content", []):
                walk(child)
    walk(doc)
    return " ".join(texts).strip()


def _jira_get(path: str, params: dict = None) -> dict:
    r = requests.get(f"{JIRA_BASE}{path}", auth=JIRA_AUTH,
                     headers={"Accept": "application/json"}, params=params)
    r.raise_for_status()
    return r.json()


def get_recently_updated(since_iso: str) -> list[dict]:
    """since_iso 이후 업데이트된 KCCIVOC/KEUVOCOP 티켓 조회 (전체 페이지네이션)."""
    # Jira Cloud는 ISO 형식 대신 'yyyy-MM-dd HH:mm' 형식 사용
    since_jira = since_iso[:16].replace("T", " ")
    jql = (
        f'project in ({", ".join(PROJECTS)}) '
        f'AND updated >= "{since_jira}" '
        f'AND issuetype in (10067, "Urgent Request") '
        f'AND (customfield_10183 in ("Kia", "Common") OR customfield_10585 in ("KMC", "ALL")) '
        f'ORDER BY updated ASC'
    )
    results = []
    payload = {"jql": jql, "maxResults": 50,
               "fields": ["summary", "status", "assignee", "updated"]}
    while True:
        r = requests.post(
            f"{JIRA_BASE}/search/jql",
            auth=JIRA_AUTH,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            json=payload,
        )
        r.raise_for_status()
        data = r.json()
        issues = data.get("issues", [])
        results.extend(issues)
        next_token = data.get("nextPageToken")
        if not next_token or not issues:
            break
        payload["nextPageToken"] = next_token
    return results


def get_changelog(issue_key: str) -> list[dict]:
    """티켓 변경 이력 조회."""
    data = _jira_get(f"/issue/{issue_key}/changelog")
    return data.get("values", [])


def get_comments(issue_key: str) -> list[dict]:
    """티켓 댓글 조회 (최신순)."""
    data = _jira_get(f"/issue/{issue_key}/comment",
                     params={"maxResults": 20, "orderBy": "-created"})
    return data.get("comments", [])


# ── 변경 감지 ──────────────────────────────────────────────────────
def detect_status_changes(issue_key: str, since_iso: str) -> list[dict]:
    """since_iso 이후 상태 변경 이력 반환."""
    changes = []
    for history in get_changelog(issue_key):
        created = history.get("created", "")
        if created <= since_iso:
            continue
        for item in history.get("items", []):
            if item.get("field") != "status":
                continue
            from_s = item.get("fromString", "")
            to_s   = item.get("toString", "")
            if WATCH_STATUS_CHANGES and to_s not in WATCH_STATUS_CHANGES:
                continue
            changes.append({
                "created": created,
                "from":    from_s,
                "to":      to_s,
                "author":  history.get("author", {}).get("displayName", ""),
            })
    return changes


def detect_new_comments(issue_key: str, seen_ids: set, since_iso: str = "") -> list[dict]:
    """since_iso 이후 생성된 댓글 중 seen_ids에 없는 것만 반환."""
    new_comments = []
    for c in get_comments(issue_key):
        cid = c.get("id", "")
        if cid in seen_ids:
            continue
        # 생성 시각 필터: since_iso 이전 댓글은 무시
        if since_iso and c.get("created", "") <= since_iso:
            continue
        import html as _html
        parts = []
        def walk(node):
            if isinstance(node, dict):
                t = node.get("type", "")
                if t == "text":
                    parts.append(_html.escape(node.get("text", "")))
                elif t == "mention":
                    mt = _html.escape(node.get("attrs", {}).get("text", ""))
                    parts.append(f'<span style="color:#0052cc;font-weight:bold;">{mt}</span>')
                elif t == "hardBreak":
                    parts.append("<br>")
                for ch in node.get("content", []):
                    walk(ch)
        walk(c.get("body", {}))
        new_comments.append({
            "id":      cid,
            "created": c.get("created", ""),
            "author":  c.get("author", {}).get("displayName", ""),
            "body":    "".join(parts).strip(),
        })
    return new_comments


# ── 이메일 발송 ────────────────────────────────────────────────────
def _fmt_kst(iso: str) -> str:
    """ISO datetime → 'M월 D일 HH:MM' 형식 (KST 기준)."""
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=KST)
        dt = dt.astimezone(KST)
        return f"{dt.month}월 {dt.day}일 {dt.strftime('%H:%M')}"
    except Exception:
        return iso[:16].replace("T", " ")


def _build_html(events: list[dict], since_iso: str = "", now_iso: str = "") -> str:
    _FF = "font-family:'Malgun Gothic',Arial,sans-serif;"
    # 알림 기간 안내 문구
    if since_iso and now_iso:
        period = (f"{_fmt_kst(since_iso)}부터 {_fmt_kst(now_iso)}까지 진행된 "
                  f"상태 변경 및 댓글 추가에 대한 자동화된 알림입니다.")
    else:
        period = "Jira 상태 변경 및 댓글 추가에 대한 자동화된 알림입니다."

    # 티켓별 그룹화 + 최신 이벤트 기준 정렬 (최신 티켓 → 상단)
    from collections import defaultdict
    grouped: dict[str, list] = defaultdict(list)
    for ev in events:
        grouped[ev["key"]].append(ev)
    sorted_keys = sorted(grouped.keys(),
                         key=lambda k: min(e["when"] for e in grouped[k]))
    for k in sorted_keys:
        grouped[k].sort(key=lambda e: e["when"])

    rows_html = ""
    ticket_border = "border-bottom:2px solid #d0d0d0;"
    for key in sorted_keys:
        evs = grouped[key]
        rowspan = len(evs)
        first = evs[0]
        link = f'{JIRA_BROWSE}/{key}'
        title = first["summary"]
        ticket_cell = (
            f'<a href="{link}" style="{_FF}font-weight:bold;color:#0052cc;">{key}</a>'
            f'<div style="{_FF}color:#555;font-size:13px;margin-top:2px;">{title}</div>'
        )
        for i, ev in enumerate(evs):
            is_last = (i == rowspan - 1)
            ev_border = ticket_border if is_last else "border-bottom:1px solid #f0f0f0;"
            if ev["type"] == "status":
                badge = (f'<span style="{_FF}color:#0052cc;font-size:12px;'
                         f'font-weight:bold;">🔄 상태변경</span><br>')
                detail = (
                    badge
                    + f'<b style="{_FF}">{ev["from"]}</b> → <b style="{_FF}">{ev["to"]}</b><br>'
                    + f'<span style="{_FF}color:#666;font-size:13px;">'
                    + f'{ev["author"]}  |  {ev["when"][:16].replace("T", " ")}</span>'
                )
            else:
                badge = (f'<span style="{_FF}color:#00875a;font-size:12px;'
                         f'font-weight:bold;">💬 새 댓글</span><br>')
                detail = (
                    badge
                    + f'<span style="{_FF}color:#666;font-size:13px;">'
                    + f'{ev["author"]}  |  {ev["when"][:16].replace("T", " ")}</span><br>'
                    + f'<blockquote style="{_FF}font-size:13px;border-left:3px solid #ccc;margin:6px 0 0;'
                    + f'padding:4px 8px;color:#555;white-space:pre-wrap;">{ev["body"]}</blockquote>'
                )
            if i == 0:
                tc_style = f'{_FF}padding:12px;vertical-align:top;width:200px;{ticket_border}'
                rows_html += f"""
        <tr>
          <td style="{tc_style}" rowspan="{rowspan}">{ticket_cell}</td>
          <td style="{_FF}padding:12px;{ev_border}">{detail}</td>
        </tr>"""
            else:
                rows_html += f"""
        <tr>
          <td style="{_FF}padding:12px;{ev_border}">{detail}</td>
        </tr>"""

    if not rows_html:
        rows_html = (
            '<tr><td colspan="2" style="' + _FF + 'padding:20px;text-align:center;color:#999;">'
            '변경사항이 없습니다.</td></tr>'
        )

    return f"""
    <html><body style="{_FF}font-size:14px;">
    <h2 style="{_FF}color:#0052cc;">🔔 Jira 변경 알림 (KCCIVOC / KEUVOCOP)</h2>
    <p style="{_FF}color:#333;background:#f4f5f7;padding:10px;border-radius:4px;">{period}</p>
    <table style="border-collapse:collapse;width:100%;">
      <tr style="background:#f4f5f7;">
        <th style="{_FF}padding:10px;text-align:left;width:200px;">티켓</th>
        <th style="{_FF}padding:10px;text-align:left;">내용</th>
      </tr>
      {rows_html}
    </table>
    <p style="{_FF}color:#999;font-size:12px;margin-top:24px;">
      자동 알림 — OneApp Ticket Analyzer Bot ({datetime.now().strftime('%Y-%m-%d %H:%M')})
    </p>
    </body></html>"""


_OWNER_EMAIL = os.getenv("ANALYST_OWNER_EMAIL", "cmlee@innocean.com")
CC_ALWAYS = f"rayoun@innocean.com; {_OWNER_EMAIL}"  # 항상 참조 추가 (_OWNER_EMAIL은 .env로 설정)

# send_email → _send_one으로 since/now 전달용 모듈 변수
_send_email_since: str = ""
_send_email_now: str = ""


def _send_one(to: list[str], subject: str, events: list[dict],
              since_iso: str = "", now_iso: str = ""):
    """로컬 Outlook COM을 통해 이메일 발송 (SMTP 불필요, 계정 인증 자동)."""
    import win32com.client
    try:
        outlook = win32com.client.Dispatch("Outlook.Application")
        mail = outlook.CreateItem(0)   # 0 = olMailItem
        mail.To      = "; ".join(to)
        mail.CC      = CC_ALWAYS
        mail.Subject = subject
        mail.HTMLBody = _build_html(events, since_iso, now_iso)
        mail.SentOnBehalfOfName = SMTP_USER   # 발신자 주소
        mail.Send()
        print(f"[알림] Outlook 발송 완료 → {to}  CC: {CC_ALWAYS}  ({len(events)}건)")
    except Exception as e:
        print(f"[알림] Outlook 발송 실패: {e}")


def send_email(events: list[dict]):
    """프로젝트별로 수신자를 분리하여 이메일 발송. 이벤트가 0건이어도 각 프로젝트에 개별 발송."""
    # 프로젝트별로 이벤트 그룹화
    by_project: dict[str, list[dict]] = {}
    for ev in events:
        proj = ev["key"].split("-")[0]   # "KCCIVOC-7407" → "KCCIVOC"
        by_project.setdefault(proj, []).append(ev)

    # PROJECT_RECIPIENTS 기준으로 항상 모든 프로젝트에 발송 (0건 포함)
    for proj, to in PROJECT_RECIPIENTS.items():
        proj_events = by_project.get(proj, [])
        n_status  = sum(1 for e in proj_events if e["type"] == "status")
        n_comment = sum(1 for e in proj_events if e["type"] == "comment")
        parts = []
        if n_status:  parts.append(f"상태변경 {n_status}건")
        if n_comment: parts.append(f"새댓글 {n_comment}건")
        subject = f"[Jira 알림/{proj}] {' / '.join(parts) if parts else '상태변경 0건 / 새댓글 0건'}"
        _send_one(to, subject, proj_events, since_iso=_send_email_since, now_iso=_send_email_now)


# ── 메인 ──────────────────────────────────────────────────────────
def run(force_now: datetime | None = None):
    """
    매일 16:00 KST 1회 실행.
    조회 범위: last_notification_time ~ 지금
      - 월요일 16시: 금요일 16시 이후 변경사항 포함 (주말 자동 커버)
      - 화~금 16시: 전달 16시 이후 변경사항
    force_now: 테스트용 현재 시각 오버라이드 (지정 시 state 업데이트도 이 시각으로)
    """
    now_kst = force_now if force_now is not None else datetime.now(KST)
    state   = _load_state()
    since   = state["last_notification_time"]  # 마지막 발송 시각 (ISO, KST)
    seen    = state.get("seen_comments", {})

    print(f"[알림] {since[:16]} (KST) 이후 ~ 지금까지 변경 확인 중...")

    issues = get_recently_updated(since)
    events = []

    for issue in issues:
        key     = issue["key"]
        summary = issue["fields"].get("summary", "")

        # 1) 상태 변경 감지
        try:
            for sc in detect_status_changes(key, since):
                events.append({
                    "key": key, "summary": summary, "type": "status",
                    "from": sc["from"], "to": sc["to"],
                    "author": sc["author"], "when": sc["created"], "body": "",
                })
        except Exception as e:
            print(f"[알림] {key} changelog 조회 실패: {e} → 건너뜀")

        # 2) 새 댓글 감지 (since 이후 생성된 것만)
        try:
            seen_ids     = set(seen.get(key, []))
            new_comments = detect_new_comments(key, seen_ids, since_iso=since)
            for nc in new_comments:
                events.append({
                    "key": key, "summary": summary, "type": "comment",
                    "from": "", "to": "", "author": nc["author"],
                    "when": nc["created"], "body": nc["body"],
                })
                seen_ids.add(nc["id"])
            seen[key] = list(seen_ids)
        except Exception as e:
            print(f"[알림] {key} comments 조회 실패: {e} → 건너뜀")

    # 이메일 발송 (since/now를 모듈 변수로 전달)
    global _send_email_since, _send_email_now
    _send_email_since = since
    _send_email_now   = now_kst.isoformat()
    send_email(events)
    if events:
        print(f"[알림] 총 {len(events)}건 발송 완료")
    else:
        print(f"[알림] 변경 없음 — 0건 이메일 발송 완료 (조회 {len(issues)}건)")

    # 마지막 발송 시각을 현재 시각(KST)으로 업데이트
    state["last_notification_time"] = now_kst.isoformat()
    state["seen_comments"]          = seen
    _save_state(state)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--force-now", type=str, default=None,
                        help="현재 시각 오버라이드 (ISO 형식, 예: '2026-08-26T16:00:00+09:00')")
    args = parser.parse_args()
    _force_now = None
    if args.force_now:
        _force_now = datetime.fromisoformat(args.force_now)
    run(force_now=_force_now)
