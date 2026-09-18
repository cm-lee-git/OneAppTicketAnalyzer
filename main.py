"""
CCI Ticket Analyst — 메인 실행 파일

사용법:
  python main.py --doc1          # Doc1 업데이트 (KKR 주간 보고)
  python main.py --doc2          # Doc2 업데이트 (신규/개선 전체 현황)
  python main.py --all           # 전체 문서 업데이트
  python main.py --list-fields   # Jira 커스텀 필드 ID 목록 출력 (초기 설정용)
"""
import argparse
import os
import re
import sys
import traceback
from datetime import date, datetime, timezone, timedelta

# Windows cp949 콘솔에서 Unicode 출력 시 인코딩 오류 방지
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from config import JIRA_EMAIL, JIRA_API_TOKEN, CONFLUENCE_EMAIL, CONFLUENCE_API_TOKEN, ANTHROPIC_API_KEY
from cycle import get_cycle_number, get_cycle_bounds
from jira_client import JiraClient
from confluence_client import ConfluenceClient
from analyzer import analyze_tickets_batch
import doc1_updater
import doc2_updater
import snapshot as snapshot_module


def _check_env():
    missing = []
    if not JIRA_EMAIL:
        missing.append("JIRA_EMAIL")
    if not JIRA_API_TOKEN:
        missing.append("JIRA_API_TOKEN")
    if not CONFLUENCE_EMAIL:
        missing.append("CONFLUENCE_EMAIL")
    if not CONFLUENCE_API_TOKEN:
        missing.append("CONFLUENCE_API_TOKEN")
    if not ANTHROPIC_API_KEY:
        missing.append("ANTHROPIC_API_KEY")
    if missing:
        print(f"[오류] .env 파일에 다음 항목이 없습니다: {', '.join(missing)}")
        print("       .env.example 파일을 참고해서 .env를 만들어주세요.")
        sys.exit(1)


_KST = timezone(timedelta(hours=9))


def _notify_outlook_error(cmd: str, exc: BaseException) -> None:
    """분석 실패 시 Outlook COM으로 오류 알림 이메일 전송."""
    from notify import SMTP_USER, PROJECT_RECIPIENTS, CC_ALWAYS
    import win32com.client
    now_str = datetime.now(_KST).strftime("%Y-%m-%d %H:%M KST")
    tb = traceback.format_exc()
    short_tb = "\n".join(tb.strip().splitlines()[-5:])
    subject = f"[CCI Analyst 오류] {cmd} 실패 — {now_str}"
    body = f"""<p><b>[CCI Analyst] 자동화 스크립트 오류 발생</b></p>
<table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse;font-family:Arial;font-size:13px;">
  <tr><td><b>실행 명령</b></td><td>{cmd}</td></tr>
  <tr><td><b>발생 시각</b></td><td>{now_str}</td></tr>
  <tr><td><b>오류 유형</b></td><td>{type(exc).__name__}</td></tr>
  <tr><td><b>오류 메시지</b></td><td>{str(exc)[:400]}</td></tr>
  <tr><td><b>스택 트레이스</b></td><td><pre style="font-size:11px;">{short_tb}</pre></td></tr>
</table>
<p style="color:gray;font-size:11px;">본 메일은 CCI Analyst 자동화 시스템에서 발송되었습니다.</p>"""
    # 오류 알림은 운영자 본인에게만 발송 (.env ANALYST_OWNER_EMAIL로 설정)
    all_to = [os.getenv("ANALYST_OWNER_EMAIL", "cmlee@innocean.com")]
    try:
        outlook = win32com.client.Dispatch("Outlook.Application")
        mail = outlook.CreateItem(0)
        mail.To = "; ".join(all_to)
        mail.CC = CC_ALWAYS
        mail.Subject = subject
        mail.HTMLBody = body
        mail.SentOnBehalfOfName = SMTP_USER
        mail.Send()
        print(f"[오류 알림] Outlook 발송 완료 → {all_to}")
    except Exception as e:
        print(f"[오류 알림] Outlook 발송 실패: {e}")


_TEST_SUMMARY_RE = re.compile(r'^\s*(brd\s*)?test\s*$', re.IGNORECASE)


def _is_test_ticket(t: dict) -> bool:
    """테스트/예시용 티켓 여부 판별."""
    # Jira 원본 제목이 "test" 또는 "BRD Test" 수준인 경우
    if _TEST_SUMMARY_RE.match(t.get("summary", "")):
        return True
    # Claude 분석 결과에서 "테스트 티켓"으로 명시한 경우
    if "테스트 티켓" in t.get("summary_ko", ""):
        return True
    return False


def _apply_test_filter(tickets: list[dict]) -> list[dict]:
    """테스트 티켓 제외 후 유효 티켓 반환. 제외 목록은 콘솔에 출력."""
    excluded = [t for t in tickets if _is_test_ticket(t)]
    if excluded:
        print(f"  → 테스트/예시 티켓 제외 ({len(excluded)}건):")
        for t in excluded:
            print(f"     - {t['key']}: {t.get('summary', '')}")
    return [t for t in tickets if not _is_test_ticket(t)]


def _fetch_and_analyze(extra_jql: str = "", save_path: str = "") -> list[dict]:
    import json, pathlib
    print("Jira 티켓 조회 중...")
    jira = JiraClient()
    tickets = jira.get_new_improvement_tickets(extra_jql=extra_jql)
    print(f"  → {len(tickets)}건 조회됨")

    # cycle_number 부여
    today = date.today()
    for t in tickets:
        created = date.fromisoformat(t["created"]) if t.get("created") else today
        t["cycle_number"] = get_cycle_number(created)

    print("Claude로 티켓 분석 중...")
    result = analyze_tickets_batch(tickets)
    print(f"  → {len(result)}건 분석 완료")

    # 테스트/예시 티켓 제외
    result = _apply_test_filter(result)

    # 분석 결과 저장 (다음 실행 시 재사용 가능)
    if save_path:
        pathlib.Path(save_path).write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"  → 분석 결과 저장: {save_path}")

    return result


def cmd_list_fields():
    _check_env()
    jira = JiraClient()
    fields = jira.list_fields()
    custom = [f for f in fields if f.get("id", "").startswith("customfield_")]
    print(f"{'ID':<30} {'이름'}")
    print("-" * 60)
    for f in sorted(custom, key=lambda x: x.get("id", "")):
        print(f"{f['id']:<30} {f.get('name', '')}")


_STATUS_FILTER = 'status not in ("Dropped", "해결됨", "종료", "RESOLVE", "Deployed")'

# ── Test 모드 설정 ─────────────────────────────────────────────────────────
_TEST_CYCLES = [6, 7]  # test 모드에서만 조회할 회차


def _get_weekly_jql() -> str:
    """전체 티켓 조회 JQL.
    - 현재 회차 이전: 상태 무관하게 모두 포함 (히스토리 보전)
    - 현재 회차: 종료·취소 상태 제외 (_STATUS_FILTER 적용)
    """
    current_start, _ = get_cycle_bounds(get_cycle_number(date.today()))
    return (
        'created >= "2026-01-01" AND ('
        f'created < "{current_start}" '
        f'OR {_STATUS_FILTER}'
        ')'
    )


def _build_test_jql() -> str:
    """6·7회차 생성일 범위 JQL.
    - 이전 회차(6회차): 상태 무관 포함, 현재 회차(7회차): 종료 상태 제외.
    """
    min_date = get_cycle_bounds(_TEST_CYCLES[0])[0]
    max_date = get_cycle_bounds(_TEST_CYCLES[-1])[1]
    current_start, _ = get_cycle_bounds(get_cycle_number(date.today()))
    if current_start > min_date:
        return (
            f'created >= "{min_date}" AND created <= "{max_date}" AND ('
            f'created < "{current_start}" OR {_STATUS_FILTER}'
            ')'
        )
    return f'created >= "{min_date}" AND created <= "{max_date}" AND {_STATUS_FILTER}'


def _apply_test_cycle_filter(tickets: list[dict]) -> list[dict]:
    """테스트 모드: _TEST_CYCLES 이외 회차 티켓 제거."""
    before = len(tickets)
    result = [t for t in tickets if t.get("cycle_number") in _TEST_CYCLES]
    dropped = before - len(result)
    if dropped:
        print(f"  [test] {_TEST_CYCLES[0]}·{_TEST_CYCLES[-1]}회차 외 제외: {dropped}건")
    print(f"  [test] 유효 티켓: {len(result)}건 ({_TEST_CYCLES[0]}~{_TEST_CYCLES[-1]}회차)")
    return result


def _load_prev_tickets(cache_path: str = "tickets_analyzed_latest.json") -> list[dict]:
    """분석 전 이전 캐시 로드 (변경 감지용). 없으면 빈 리스트 반환."""
    import json
    import pathlib
    p = pathlib.Path(cache_path)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def cmd_doc1(as_of: str | None = None, test_mode: bool = False):
    """평일: 전체 티켓 분석 후 주간 페이지 업데이트 + 일별 변경사항 서브페이지."""
    _check_env()
    jira = JiraClient()
    jql = _build_test_jql() if test_mode else _get_weekly_jql()
    prev_tickets = _load_prev_tickets()
    tickets = _fetch_and_analyze(
        extra_jql=jql,
        save_path="tickets_analyzed_latest.json",
    )
    if test_mode:
        tickets = _apply_test_cycle_filter(tickets)
    doc1_updater.update(tickets, ConfluenceClient(), as_of=as_of, jira_client=jira,
                        prev_tickets=prev_tickets)


def cmd_doc2(as_of: str | None = None, test_mode: bool = False,
             use_cache: bool = False):
    """평일: 전체 티켓 분석 후 마스터 페이지 업데이트 + 일별 변경사항 서브페이지.

    use_cache: True이면 tickets_analyzed_latest.json 재사용 (Claude 분석 생략).
    """
    _check_env()
    import json, pathlib
    jql = _build_test_jql() if test_mode else _get_weekly_jql()

    cache_path = pathlib.Path("tickets_analyzed_latest.json")
    prev_tickets = _load_prev_tickets()
    if use_cache and cache_path.exists():
        print(f"[Doc2] 캐시 사용 → {cache_path} ({cache_path.stat().st_size // 1024}KB)")
        tickets = json.loads(cache_path.read_text(encoding="utf-8"))
        if test_mode:
            tickets = _apply_test_cycle_filter(tickets)
    else:
        tickets = _fetch_and_analyze(
            extra_jql=jql,
            save_path="tickets_analyzed_latest.json",
        )
        if test_mode:
            tickets = _apply_test_cycle_filter(tickets)

    doc2_updater.update(tickets, ConfluenceClient(), as_of=as_of, prev_tickets=prev_tickets)


def cmd_snapshot(force_cycle=None, as_of: str | None = None):
    """회차 마감일 18:00 스냅샷 — 오늘이 마감일이 아니면 자동 종료."""
    _check_env()
    snapshot_module.take_snapshot(force_cycle=force_cycle, as_of=as_of)


def cmd_all(test_mode: bool = False):
    _check_env()
    jira = JiraClient()
    jql = _build_test_jql() if test_mode else _get_weekly_jql()
    prev_tickets = _load_prev_tickets()
    tickets = _fetch_and_analyze(
        extra_jql=jql,
        save_path="tickets_analyzed_latest.json",
    )
    if test_mode:
        tickets = _apply_test_cycle_filter(tickets)
    client = ConfluenceClient()
    doc1_updater.update(tickets, client, jira_client=jira, prev_tickets=prev_tickets)
    doc2_updater.update(tickets, client, prev_tickets=prev_tickets)


def _cmd_doc2_daily_compat(as_of, from_date, use_cache, test_mode):
    """하위 호환: --doc2-daily는 --doc2와 동일하게 동작."""
    cmd_doc2(as_of=as_of, test_mode=test_mode, use_cache=use_cache)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CCI Ticket Analyst")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--doc1",         action="store_true", help="Doc1 업데이트 (마스터 페이지 + 스냅샷)")
    group.add_argument("--doc2",         action="store_true", help="Doc2 업데이트 (마스터 페이지 + 스냅샷)")
    group.add_argument("--doc1-daily",   action="store_true", help="(--doc1과 동일, 하위 호환)")
    group.add_argument("--doc2-daily",   action="store_true", help="(--doc2와 동일, 하위 호환)")
    group.add_argument("--snapshot",     action="store_true", help="회차별 마감 히스토리 스냅샷 (회차 마감일 18시)")
    group.add_argument("--all",          action="store_true", help="전체 문서 업데이트 (Doc1+Doc2)")
    group.add_argument("--list-fields",  action="store_true", help="Jira 커스텀 필드 목록 출력")
    group.add_argument("--delete-page",  type=str, metavar="PAGE_ID", help="Confluence 페이지 영구 삭제")
    parser.add_argument("--force-cycle", type=int, default=None, metavar="N",
                        help="--snapshot 테스트용: 특정 회차 번호 강제 지정")
    parser.add_argument("--timestamp", type=str, default=None, metavar="MM-DD HH:MM",
                        help="스냅샷 제목 타임스탬프 오버라이드 (예: '09-14 11:00'). 미지정 시 현재 시각")
    parser.add_argument("--from-date", type=str, default=None, metavar="YYYY-MM-DD",
                        help="(하위 호환용, 현재 사용 안 함)")
    parser.add_argument("--use-cache", action="store_true",
                        help="--doc2: tickets_analyzed_latest.json 재사용, Claude 분석 생략")
    parser.add_argument("--test", action="store_true",
                        help=f"테스트 모드: {_TEST_CYCLES[0]}·{_TEST_CYCLES[-1]}회차 티켓만 조회·분석")
    args = parser.parse_args()

    _cmd_label = " ".join(sys.argv[1:])  # 예: "--doc1 --test"

    try:
        if args.delete_page:
            _check_env()
            ConfluenceClient().delete_page(args.delete_page)
        elif args.list_fields:
            cmd_list_fields()
        elif args.doc1 or args.doc1_daily:
            cmd_doc1(as_of=args.timestamp, test_mode=args.test)
        elif args.doc2 or args.doc2_daily:
            cmd_doc2(as_of=args.timestamp, test_mode=args.test, use_cache=args.use_cache)
        elif args.snapshot:
            cmd_snapshot(force_cycle=args.force_cycle, as_of=args.timestamp)
        elif args.all:
            cmd_all(test_mode=args.test)
    except Exception as exc:
        print(f"[오류] {_cmd_label} 실행 중 예외 발생: {exc}", file=sys.stderr)
        traceback.print_exc()
        _notify_outlook_error(_cmd_label, exc)
        sys.exit(1)
