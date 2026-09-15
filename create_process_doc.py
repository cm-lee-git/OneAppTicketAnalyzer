"""
CCI 티켓 분석 봇 — 전체 프로세스 및 스코어링 기준 문서 생성
대상 폴더: https://ihqdf.atlassian.net/wiki/spaces/2/folder/66879494
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from confluence_client import ConfluenceClient

PARENT_FOLDER_ID = "66879494"
TITLE = "CCI 티켓 분석 봇 — 전체 프로세스 및 스코어링 기준"

# ─── Confluence storage format HTML ─────────────────────────────────────────

def _panel(bg, content):
    return (f'<ac:structured-macro ac:name="panel" ac:schema-version="1">'
            f'<ac:parameter ac:name="bgColor">{bg}</ac:parameter>'
            f'<ac:rich-text-body>{content}</ac:rich-text-body>'
            f'</ac:structured-macro>')

def _info(content):
    return (f'<ac:structured-macro ac:name="info" ac:schema-version="1">'
            f'<ac:rich-text-body>{content}</ac:rich-text-body>'
            f'</ac:structured-macro>')

def _note(content):
    return (f'<ac:structured-macro ac:name="note" ac:schema-version="1">'
            f'<ac:rich-text-body>{content}</ac:rich-text-body>'
            f'</ac:structured-macro>')

def _warning(content):
    return (f'<ac:structured-macro ac:name="warning" ac:schema-version="1">'
            f'<ac:rich-text-body>{content}</ac:rich-text-body>'
            f'</ac:structured-macro>')

def _code(lang, text):
    return (f'<ac:structured-macro ac:name="code" ac:schema-version="1">'
            f'<ac:parameter ac:name="language">{lang}</ac:parameter>'
            f'<ac:plain-text-body><![CDATA[{text}]]></ac:plain-text-body>'
            f'</ac:structured-macro>')

def _table(headers, rows, col_widths=None):
    """간단한 Confluence 표."""
    cg = ""
    if col_widths:
        cg = "<colgroup>" + "".join(f'<col style="width:{w}px;"/>' for w in col_widths) + "</colgroup>"
    th_row = "<tr>" + "".join(f"<th><p><strong>{h}</strong></p></th>" for h in headers) + "</tr>"
    body = "".join(
        "<tr>" + "".join(
            (f'<td style="background:{c[1]};">' if isinstance(c, tuple) else "<td>")
            + f"<p>{c[0] if isinstance(c, tuple) else c}</p></td>"
            for c in row
        ) + "</tr>"
        for row in rows
    )
    return f"<table>{cg}<tbody>{th_row}{body}</tbody></table>"


# ── 전체 흐름도 (텍스트 표) ──────────────────────────────────────────────────
FLOW = _panel("#EAE6FF",
    "<p><strong>전체 자동화 파이프라인</strong></p>"
    "<p>Jira API → 필터링 → 정규화 → Claude AI 분석 → 보류/반려 판별 → 스코어링 → Confluence 문서 업데이트</p>"
    "<p><em>main.py --doc1 / --doc2 / --doc1-daily / --doc2-daily / --snapshot</em></p>"
)

# ── Step 1: 티켓 수집 ────────────────────────────────────────────────────────
STEP1 = f"""
<h2>Step 1. 티켓 수집 및 필터링</h2>
<p>파일: <code>jira_client.py → JiraClient.get_new_improvement_tickets()</code></p>
<h3>1-1. JQL 기본 조건</h3>
{_code("sql", """project in (KCCIVOC, KEUVOCOP)
AND issuetype in (10067, "Urgent Request")
AND (
  customfield_10183 in ("Kia", "Common")   -- 대상 브랜드 필드 (10183)
  OR customfield_10585 in ("KMC", "ALL")   -- Brand 필드 (10585)
)
[AND created >= "2026-01-01"]  -- Doc1/Doc2 공통 날짜 cutoff
ORDER BY created DESC""")}
<ul>
  <li><strong>프로젝트</strong>: KCCIVOC (KR), KEUVOCOP (EU) — CCIPRJ는 2026-08-06부터 제외</li>
  <li><strong>이슈 타입</strong>: issuetype 10067 (신규/개선) + Urgent Request</li>
  <li><strong>브랜드 필터</strong>: customfield_10183 (Kia/Common) OR customfield_10585 (KMC/ALL) 중 하나라도 해당하면 포함. Hyundai/Genesis 전용은 자동 제외</li>
  <li><strong>날짜</strong>: <code>created &gt;= "2026-01-01"</code> — Doc1/Doc2/Pending 관리 표 모두 동일 적용</li>
</ul>
<h3>1-2. 조회 필드 (API fields)</h3>
<ul>
  <li>summary, reporter, creator, created, status, issuetype, description, subtasks</li>
  <li>customfield_10175 (country), customfield_10183 (대상 브랜드), customfield_10585 (Brand)</li>
  <li>customfield_10570 (Due Date), customfield_10185 (End date), labels</li>
</ul>
<h3>1-3. 페이지네이션</h3>
<p>POST /search/jql → maxResults: 50, nextPageToken 커서 기반으로 전체 결과 수집</p>
<h3>1-4. 보류 경유 이력 확인 (was_pending)</h3>
<p>Approved 티켓에 한해 GET /issue/{'{key}'}/changelog 호출 → 이력에 BRD Submitted / In Business Review / Revision Requested / HQ Discussion 상태가 있으면 <code>was_pending = True</code></p>
<p>Doc2 트래킹 표의 "승인 전환" / "반려 전환" 열 집계에 사용됨</p>
"""

# ── Step 2: 정규화 ───────────────────────────────────────────────────────────
STEP2 = f"""
<h2>Step 2. 티켓 정규화</h2>
<p>파일: <code>jira_client.py → JiraClient._normalize()</code></p>
<h3>2-1. 지역 분류</h3>
{_table(
    ["조건", "분류"],
    [
        ["country 값이 \"Global\"이면 (프로젝트 무관)", ("KR", "#DEEBFF") if False else "HQ"],
        ["KCCIVOC + country ≠ Global", "KR"],
        ["KEUVOCOP + country ≠ Global", "EU"],
        ["country = KR / Korea", "KR"],
        ["country = EU 국가 (Italy, Spain, France, Germany 등)", "EU"],
        ["country = All / Global / HQ", "HQ"],
    ],
    [280, 120]
)}
<h3>2-2. BRD 상태 매핑 (config.py → BRD_STATUS_MAP)</h3>
<p>Jira <code>status.name</code> 필드를 아래 테이블로 변환</p>
{_table(
    ["Jira 상태값", "매핑 결과"],
    [
        ["Confirmed, HQ Discussion, In Business Review, 진행 중, QA Sign-Off, Re-Opened, 종료, Deployed, Dropped, RESOLVE, 해결됨", ("Approved", "#E3FCEF") if False else "Approved"],
        ["BRD Submitted, Create Issue, 미해결, Reopen, Revision Requested", "보류"],
        ["(매핑되지 않는 값은 빈 문자열 처리)", "(없음)"],
    ],
    [420, 120]
)}
<h3>2-3. 회차(Cycle) 분류</h3>
<ul>
  <li><strong>앵커</strong>: 2026-06-08 (월) = 1회차 시작</li>
  <li><strong>계산식</strong>: cycle_number = (created - 2026-06-08).days // 14 + 1</li>
  <li><strong>Pre-BRD</strong>: created &lt; 2026-06-08 → cycle_number = 0 (BRD 승인 여부 미작성)</li>
  <li><strong>Post-BRD</strong>: created ≥ 2026-06-08 → cycle_number ≥ 1</li>
  <li>공휴일 고려 없음 — 고정 14일 계산</li>
</ul>
<h3>2-4. 그룹 티켓 식별</h3>
<p>subtasks 필드에 하위 작업이 있으면 <code>is_group = True</code> → Doc1에서 별도 2행 블록으로 표시 (스코어링 없음)</p>
<h3>2-5. Fast Track 티켓</h3>
<p>issuetype = "Urgent Request"이면 <code>is_fast_track = True</code> → 항목 분포 생략, BRD 승인 여부만 표시</p>
"""

# ── Step 3: Claude AI 분석 ────────────────────────────────────────────────────
STEP3 = f"""
<h2>Step 3. Claude AI 분석</h2>
<p>파일: <code>analyzer.py → analyze_ticket()</code></p>
<h3>3-1. 입력값 구성</h3>
<ul>
  <li>티켓 description (BRD 전문 텍스트)</li>
  <li>티켓 자체 댓글 (최신 5개) — R4/H 코드 보완용</li>
  <li>다른 티켓 목록 [(key, summary)] — R3 중복 감지용</li>
</ul>
<h3>3-2. API 호출</h3>
{_code("python", """# h-chat 사내 프록시 (api.anthropic.com 직접 호출 불가)
endpoint = ANTHROPIC_BASE_URL  # 환경변수
model    = "claude-sonnet-4-6"
max_tokens = 1500""")}
<h3>3-3. 프롬프트 버전 선택</h3>
{_warning("<p><strong>SCORING_PROMPT_VERSION 환경변수</strong>로 v1/v2 전환</p>"
          "<ul><li>기본값(미설정): v1 (기존 0/1 이진값, 합계 0~5)</li>"
          "<li>v2: .env에 SCORING_PROMPT_VERSION=v2 추가 → prompts/scoring_v2_system_prompt.md 로드</li></ul>")}
<h3>3-4. 출력 JSON 파싱</h3>
<p>Claude가 반환한 JSON에서 다음 필드를 추출:</p>
<ul>
  <li><strong>status_info</strong>: 현재 처리 상태 (\\n 구분)</li>
  <li><strong>summary_ko</strong>: AS-IS → TO-BE 대비 1~2문장</li>
  <li><strong>background / problem / feature</strong>: \\n 구분 불렛 포인트</li>
  <li><strong>feature_label</strong>: "기존 기능 개선" 또는 "신규 기능"</li>
  <li><strong>hold_code / hold_reason</strong>: H1~H4 (보류 상태일 때만)</li>
  <li><strong>rejection_code / rejection_reason</strong>: R1~R4 (반려 상태일 때만)</li>
  <li><strong>scores</strong>: 6개 항목 0/1 딕셔너리 (v1)</li>
  <li><strong>review</strong>: 하위 지표 포함 구조 (v2)</li>
</ul>
"""

# ── Step 4: 스코어링 ─────────────────────────────────────────────────────────
SCORING_V1 = f"""
<h2>Step 4. 스코어링 — v1 (기본)</h2>
<p>환경변수 미설정 또는 <code>SCORING_PROMPT_VERSION=v1</code> 시 적용</p>
{_info("<p><strong>Priority 점수 = business_performance + customer_experience + operational_efficiency + global_reach + platform_strategy</strong></p>"
       "<p>urgency는 Fast Track 분류 전용 — Priority 합산에서 제외. 합계 범위: 0~5</p>")}

<h3>4-1. urgency (시급성, 0 또는 1 — Fast Track 여부)</h3>
{_table(
    ["값", "판단 기준", "실제 사례"],
    [
        ["1", "아래 중 하나라도 해당:\n• 대규모 장애 / Critical Bug (핵심 여정 사용 불가·심각한 성능 저하)\n• 법규 대응 (GDPR 등 법적 리스크, 과징금, 감사 이슈)\n• 리더십 결정 (C-Level 지시, MBO 과제)", "C-Level 보고 결과 후속 과제"],
        ["0", "위 해당 없음", "일반 UX 개선 요청"],
    ], [60, 380, 200]
)}

<h3>4-2. business_performance (사업 성과 기여, 0 또는 1)</h3>
{_table(
    ["값", "판단 기준", "실제 사례 O", "실제 사례 X"],
    [
        ["1", "리드 확보·전환율·계약/구매 유도에 직접 영향. 정량 수치 또는 명확한 전환 경로 필요",
         "Fleet 차량 down time 최소화 → 품질비용 연 3억+ 절감 (KCCIVOC-5593)\nEV 충전 구독 전환율 직접 영향 (KCCIVOC-6229)",
         "단순 버튼 이름 변경 (KEUVOCOP-1881)\nSDK 마이그레이션만 (KEUVOCOP-2238)"],
        ["0", "간접 영향(브랜딩 개선 등) 또는 비즈니스 전환과 무관한 경우", "", ""],
    ], [40, 280, 240, 200]
)}

<h3>4-3. customer_experience (고객 경험 영향도, 0 또는 1)</h3>
{_table(
    ["값", "판단 기준", "실제 사례 O", "실제 사례 X"],
    [
        ["1", "반복적 VoC 또는 행동 데이터로 확인된 고객 불편. CS 건수·이탈 단계·세션 데이터 등 정량 근거 필요",
         "정비 T/O 확인 불편, 빈자리 알림 니즈 (KCCIVOC-5539)\n딜러 검색 결과 오류 — 핵심 여정 혼선 (KEUVOCOP-1923)",
         "단순 버튼 이름 변경 (KEUVOCOP-1881)\n정량 근거 없는 \"편의성 향상\" 서술만"],
        ["0", "위 해당 없음 또는 정량 근거 없이 추정 수준", "", ""],
    ], [40, 280, 240, 200]
)}

<h3>4-4. operational_efficiency (운영 효율화, 0 또는 1)</h3>
{_table(
    ["값", "판단 기준", "실제 사례 O", "실제 사례 X"],
    [
        ["1", "수기 반복 제거 또는 비용 절감 효과가 수치(건수·시간·금액)로 확인됨",
         "OTA 활성화로 서비스센터 물리 입고 대체 (KCCIVOC-5593)\nCS팀 VIN 수동 조회 자동화 (KEUVOCOP-1865)",
         "정량 수치 없이 \"효율 향상 예상\"만 있는 경우"],
        ["0", "위 해당 없음", "", ""],
    ], [40, 280, 240, 200]
)}

<h3>4-5. global_reach (글로벌 파급 범위, 0 또는 1 — 두 조건 AND)</h3>
{_panel("#FFF0B3",
    "<p><strong>v1: MAU 2M 이상 AND 수혜 국가 비율 50% 이상 — 두 조건 동시 충족해야 1</strong></p>"
    "<p>단일 국가 요청은 무조건 0 (MAU 조건 충족 여부와 무관)</p>")}
{_table(
    ["조건", "값", "실제 사례"],
    [
        ["MAU 2M+ AND 수혜국가 50%+", "1", "KR 전체 원앱 대상 기능 (MAU 조건 충족, 수혜 국가 100%)"],
        ["단일 국가 요청", "0", "독일 딜러 검색 오류 (KEUVOCOP-1923), Germany 단일"],
        ["Country=All이어도 MAU 별도 확인", "경우에 따라", "Marketing Cloud SDK — SDK 인프라 작업은 MAU 직접 증가 연관 낮음 → 0 (KEUVOCOP-2238)"],
    ], [260, 60, 340]
)}

<h3>4-6. platform_strategy (플랫폼 운영 전략 연계도, 0 또는 1)</h3>
{_table(
    ["권역", "1점 기준 KPI", "실제 사례 O"],
    [
        ["KR", "핵심 기능 사용율 (원격제어 / 정비 알림 / 충전 / 비즈니스 전환율)", "원격진단 알람 (KCCIVOC-5593), 충전 서비스 (KCCIVOC-6229)"],
        ["EU", "앱 다운로드 수 & 가입율에 직결되는 기능", "Model Year 표시 → 가입 전환 영향 (KEUVOCOP-2168)"],
        ["Global/HQ", "Non-CCS/CCS 표준화 기여, 글로벌 BPM 연계", "HQ BPM 방향성 직결 기능"],
        ["공통 X", "단순 UX 개선, SDK 기반 작업만, 단일 화면 버그", "단순 버튼 rename, SDK 교체만"],
    ], [120, 280, 260]
)}
"""

SCORING_V2 = f"""
<h2>Step 4'. 스코어링 — v2 (SCORING_PROMPT_VERSION=v2)</h2>
{_warning("<p>.env에 <code>SCORING_PROMPT_VERSION=v2</code> 추가 시 활성화. 미설정이면 v1 그대로 동작.</p>")}
<p>파일: <code>prompts/scoring_v2_system_prompt.md</code> (<!-- PROMPT_START --> 이후 내용만 로드)</p>
<p>v2는 BRD 템플릿 <strong>7.2 신규/개선 티켓 GBCXD 우선 순위 선별 검토 결과</strong> 표와 1:1 대응하도록 설계됨</p>

<h3>v2 출력 구조 (review 딕셔너리)</h3>
{_code("json", """{
  "review": {
    "urgency": {
      "critical_incident":   {"mark": "O|X", "basis": "근거"},
      "legal_compliance":    {"mark": "O|X", "basis": "근거"},
      "leadership_decision": {"mark": "O|X", "basis": "근거"},
      "fast_track": 0  /* 셋 중 하나라도 O면 1 */
    },
    "business_performance":   {"mark": "O|X", "score": 0, "basis": "근거"},
    "customer_experience":    {"mark": "O|X", "score": 0, "basis": "근거"},
    "operational_efficiency": {"mark": "O|X", "score": 0, "basis": "근거"},
    "global_reach": {
      "mau":      {"mark": "O|X", "basis": "MAU 2M 이상 여부"},
      "coverage": {"mark": "O|X", "basis": "수혜 국가 비율 50% 이상 여부"},
      "score": 0  /* mau(O=1) + coverage(O=1) → 0~2 */
    },
    "platform_strategy": {"mark": "O|X", "score": 0, "kpi": "해당 KPI명", "basis": "근거"},
    "total": 0  /* 시급성 제외, 합계 0~6 */
  }
}""")}

<h3>v1 vs v2 주요 차이점</h3>
{_table(
    ["항목", "v1", "v2"],
    [
        ["urgency", "0 또는 1 (단일 값)", "3개 하위 지표 (critical_incident / legal_compliance / leadership_decision) → fast_track 0/1"],
        ["global_reach", "0 또는 1 (AND 조건)", "MAU / coverage 각각 독립 판정 → 0~2점 (AND 규칙 폐기)"],
        ["basis 필드", "없음", "모든 항목에 근거 1~2문장 필수"],
        ["합계 범위", "0~5 (urgency 제외)", "0~6 (urgency 제외, global_reach 0~2로 확장)"],
        ["platform_strategy", "mark + score", "mark + score + kpi (적용 KPI명 명시)"],
    ],
    [200, 240, 320]
)}

<h3>v2 → v1 호환 변환 (analyzer.py)</h3>
<p>v2 출력을 받으면 analyzer.py가 자동으로 v1 호환 scores 딕셔너리로 변환하여 doc1/doc2 렌더링에 전달</p>
{_code("python", """# analyzer.py - v2 review → v1 scores 변환
parsed["scores"] = {
    "urgency":                rev["urgency"]["fast_track"],
    "business_performance":   1 if rev["business_performance"]["mark"] == "O" else 0,
    "customer_experience":    1 if rev["customer_experience"]["mark"] == "O" else 0,
    "operational_efficiency": 1 if rev["operational_efficiency"]["mark"] == "O" else 0,
    "global_reach":           rev["global_reach"]["score"],  # 0~2 (v2에서만)
    "platform_strategy":      1 if rev["platform_strategy"]["mark"] == "O" else 0,
}
# review_detail: 항목 분포 셀 보조 표기 (Doc1/Doc2 AI 열에 표시)
# 예) urgency → "리더십 결정 O", global_reach → "MAU X · 수혜국가 X"
parsed["review_detail"] = { ... }
parsed["priority_score"] = rev.get("total", 0)  # 0~6""")}

<h3>셀프 스코어링 (self_scores, 현재 미구현)</h3>
{_note("<p>Jira BRD 7.1 셀프 스코어링 섹션을 jira_client가 추출하면 ticket 딕셔너리에 <code>self_scores</code> 필드가 채워짐 (현재는 항상 없음)</p>"
       "<p>self_scores가 있을 때: Doc1/Doc2 항목 분포 셀이 셀프(요청자) 열과 AI(7.2 초안) 열로 분리되어 일치(초록)/불일치(빨강) 색상 강조</p>"
       "<p>self_scores가 없을 때(현재): 셀프 열에 — 표시, AI 열에 정상 표시</p>")}
"""

# ── Step 5: 보류/반려 판별 ────────────────────────────────────────────────────
STEP5 = f"""
<h2>Step 5. 보류·반려 분류</h2>
<h3>5-1. 최종 승인 판단 우선순위</h3>
{_panel("#DEEBFF",
    "<p><strong>판단 우선 원칙 (analyzer.py + doc1/doc2_updater.py _effective_approval/brd)</strong></p>"
    "<ol>"
    "<li>rejection_code 존재 → <strong>반려</strong> (BRD 상태 무관)</li>"
    "<li>hold_code 존재 + Post-BRD → <strong>보류</strong></li>"
    "<li>나머지 → brd_approval 매핑값 그대로 (Approved / 보류)</li>"
    "</ol>"
    "<p>Pre-BRD 티켓(cycle_number=0)은 hold_code 판단 제외 — BRD 프로세스 적용 전 생성된 티켓</p>")}

<h3>5-2. 보류 코드 (H1 → H4 순으로 판별, 가장 주된 1개만)</h3>
{_table(
    ["코드", "명칭", "판단 기준 (하나라도 해당 시)", "해소 조건"],
    [
        ["H1", "필수 항목 누락",
         "다음 중 1개 이상 공란·예시 그대로:\n• 1.1 추진 배경\n• 3.3 기능 목록 (기능명/설명/진입경로/연동시스템)\n• 2.3 IT 검토사항 (연동 시스템 목록, 데이터 요구사항)\n• 7.1 셀프 스코어링\n• Due Date",
         "BRD 보완 후 재검토"],
        ["H2", "요건 미구체화",
         "필수 섹션은 있으나:\n• 기능 설명이 1줄 서술 수준\n• 기능명만 있고 진입경로·연동시스템 공란\n• As-is/To-be가 예시 문구 수준",
         "요건 구체화 후 재검토"],
        ["H3", "정량 근거 부족",
         "H1·H2 아닌데:\n• 7.1 스코어링 근거에 정량 수치(건수·%·시간·금액) 없이 \"예상됨\" 수준\n• 기대 효과가 정성 서술만",
         "정량 데이터 보완 후 재검토"],
        ["H4", "선행 조건 미충족",
         "타 티켓/프로젝트 완료 또는 정책 확정이 선행 필요 — 댓글·본문에 명시적 언급",
         "선행 조건 해소 후 재검토"],
    ], [50, 130, 350, 170]
)}
<p><em>* H5는 2026-08-05부로 제거됨. H1~H4만 사용.</em></p>
<p><strong>보류 해소 기한</strong>: 보류 안내일로부터 <strong>10 영업일</strong> 이내 미보완 시 자동 반려</p>

<h3>5-3. 반려 코드</h3>
{_table(
    ["코드", "명칭", "판단 기준", "비고"],
    [
        ["R1", "전항목 미충족", "urgency == 0 AND priority == 0 (자동 판별, 보류 상태일 때)", "analyzer.py에서 자동 설정"],
        ["R2", "범위 외", "OneApp 플랫폼 운영 범위 외 요청 (타 시스템·채널 소관)", ""],
        ["R3", "중복 티켓", "실질적으로 동일한 요건이 이미 진행 중인 다른 티켓 존재", "전체 티켓 목록 참고"],
        ["R4", "방향성 배치", "글로벌 BPM 방향성 또는 리더십 결정 사항과 배치 (댓글 내용에서 근거 확인)",
         "스코어 2점이어도 R4 가능 (KCCIVOC-6735 사례)"],
    ], [50, 130, 330, 200]
)}
<p><em>* R5는 2026-08-05부로 제거됨. R1~R4만 사용.</em></p>
"""

# ── Step 6: 문서 업데이트 ─────────────────────────────────────────────────────
STEP6 = f"""
<h2>Step 6. Confluence 문서 업데이트</h2>
<h3>6-1. 자동화 스케줄</h3>
{_table(
    ["작업", "배치파일", "실행 시점", "동작"],
    [
        ["CCI_Doc1_Weekly",   "run_doc1.bat",       "매주 월요일 11:00", "Doc1 페이지 신규 생성 (타임스탬프 제목)"],
        ["CCI_Doc1_Daily",    "run_doc1_daily.bat", "매주 화~금 11:00",  "기존 최신 Doc1에 당일 신규 KR 티켓 추가"],
        ["CCI_Doc2_Weekly",   "run_doc2.bat",       "매주 월요일 10:00", "Doc2 페이지 신규 생성"],
        ["CCI_Doc2_Daily",    "run_doc2_daily.bat", "평일 매일 16:00",   "당일 신규 티켓 있으면 전체 재구성 후 업데이트"],
        ["CCI_Notify",        "run_notify.bat",     "평일 매일 16:00",   "상태변경·새 댓글 감지 → 이메일 알림"],
        ["CCI_Snapshot_Daily","run_snapshot.bat",   "평일 매일 18:00",   "회차 마감일이면 Doc2-1 스냅샷 생성"],
    ], [180, 180, 160, 280]
)}

<h3>6-2. 페이지 ID 구조</h3>
{_table(
    ["문서", "폴더 Page ID", "설명"],
    [
        ["Doc1 (KKR OneApp 주간 보고)", "77529216", "실행마다 타임스탬프 제목으로 새 페이지 생성"],
        ["Doc2 (신규/개선 전체 현황)", "78020650", "자동생성 페이지 탐색 후 업데이트 (create_page)"],
        ["Doc2-1 (회차별 마감 히스토리)", "77922419", "회차 마감일 스냅샷 생성"],
    ], [200, 120, 380]
)}

<h3>6-3. Doc1 표 구조 (항목 분포 — v2 도입 후)</h3>
{_panel("#EAE6FF",
    "<p>총 13열 (v2 도입 전 12열)</p>"
    "<p><strong>항목 분포</strong>: 항목명(1열) | 셀프(요청자)(1열) | AI(7.2 초안)(1열) — colspan=3</p>"
    "<p>셀프/AI 값이 일치하면 초록 (#e3fcef), 불일치하면 빨강 (#ffebe6) 배경</p>"
    "<p>현재 셀프 열은 — (미구현, jira_client 7.1 파서 추가 시 활성화)</p>"
    "<p>AI 열에 review_detail 보조 표기: 예) \"O (리더십 결정 O)\", \"O (MAU O · 수혜국가 X)\"</p>"
)}

<h3>6-4. HMG Confluence 참조 문서 복제</h3>
<ul>
  <li>Doc1 참조: HMG Confluence 폴더에서 최신 주간 보고 페이지 자동 탐색 → 기존 티켓 행 HTML 복사</li>
  <li>Doc2 참조: HMG_DOC2_PAGE_ID (589030689) → 기존 티켓 행 + 히스토리 expand 블록 복사</li>
  <li>구조가 변경(열 수 불일치)된 행은 자동 재생성</li>
</ul>
"""

# ── 실제 사례 요약 ───────────────────────────────────────────────────────────
EXAMPLES = f"""
<h2>참고. 실제 사례 기반 판단 보정</h2>
{_table(
    ["티켓", "권역", "bp", "cx", "oe", "gr", "ps", "합계", "최종"],
    [
        ["KCCIVOC-5593 (원격진단 선제 알람)", "KR", "1", "1", "1", "1", "1", "5", "Approved"],
        ["KEUVOCOP-1881 (버튼명 변경 1줄)", "EU", "0", "0", "0", "0", "0", "0", "보류→R1 반려"],
        ["KEUVOCOP-2238 (Marketing Cloud SDK)", "EU", "0", "0", "1", "0", "0", "1", "Approved"],
        ["KEUVOCOP-1923 (독일 딜러 검색 오류)", "EU", "0", "1", "0", "0(단일국가)", "0", "1", "Approved"],
        ["KCCIVOC-6735 (웰컴 메시지 개인화)", "KR", "1", "0", "0", "1", "0", "2", "R4 반려 (BPM 배치)"],
        ["KCCIVOC-6934 (OTA 기능 고도화)", "KR", "0", "1", "1", "1", "0", "3", "H1 보류 (BRD 미완성)"],
    ], [220, 60, 40, 40, 40, 80, 40, 60, 150]
)}
"""

# ── 조합 ────────────────────────────────────────────────────────────────────
HTML = "\n".join([
    FLOW,
    STEP1,
    STEP2,
    STEP3,
    SCORING_V1,
    SCORING_V2,
    STEP5,
    STEP6,
    EXAMPLES,
])

if __name__ == "__main__":
    client = ConfluenceClient()
    result = client.create_page(PARENT_FOLDER_ID, TITLE, HTML)
    page_id = result.get("id", "")
    print(f"[완료] 페이지 생성: {TITLE}")
    print(f"       ID: {page_id}")
    print(f"       URL: https://ihqdf.atlassian.net/wiki/spaces/2/pages/{page_id}")
