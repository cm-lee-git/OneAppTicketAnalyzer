import os
from dotenv import load_dotenv

load_dotenv(override=True)

# Jira: HMG (현대자동차그룹) 인스턴스
JIRA_BASE_URL = "https://hmg.atlassian.net"
JIRA_EMAIL = os.getenv("JIRA_EMAIL")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")

# Confluence: IHQDF (이노션) 인스턴스
CONFLUENCE_BASE_URL = "https://ihqdf.atlassian.net"
CONFLUENCE_EMAIL = os.getenv("CONFLUENCE_EMAIL")
CONFLUENCE_API_TOKEN = os.getenv("CONFLUENCE_API_TOKEN")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

JIRA_PROJECTS = ["KCCIVOC", "KEUVOCOP"]

CONFLUENCE_PARENT_PAGE_ID = "68222989"

# 구조 참조용 복사본 페이지 ID (읽기 전용)
DOC_TEMPLATE_IDS = {
    "doc1": "70156303",   # 복사본: KKR OneApp 주간 보고
    "doc2": "70025250",   # 복사본: 신규/개선 티켓 스크리닝
}

# 자동화 업데이트 대상 페이지 ID (AI 생성 폴더)
DOC_PAGE_IDS = {
    "doc1":  "77529216",   # 1) KKR OneApp 주간 보고 폴더 (AI 생성 [78053444] > 1))
    "doc2":  "78020650",   # 2) 신규/개선 티켓 스크리닝 및 관리 폴더 (AI 생성 > 2))
    "doc21": "77922419",   # 2-1) 회차별 마감 히스토리 폴더 (AI 생성 > 2-1))
}

# 각 문서 페이지 제목 (부분 일치로 탐색, 폴백용)
DOC_TITLE_KEYWORDS = {
    "doc1": "KKR",
    "doc2": "신규/개선",       # (Kia) 제외
}

# Jira 커스텀 필드 ID (.env에서 오버라이드 가능)
JIRA_FIELDS = {
    "country":      os.getenv("JIRA_FIELD_COUNTRY",      "customfield_10175"),
    "brand":        os.getenv("JIRA_FIELD_BRAND",        "customfield_10183"),  # 대상 브랜드: Kia, Common
    "brand2":       os.getenv("JIRA_FIELD_BRAND2",       "customfield_10585"),  # Brand: KMC, ALL
    "due_date":     os.getenv("JIRA_FIELD_DUE_DATE",     "customfield_10570"),  # Due Date (실제 값)
    "end_date":     os.getenv("JIRA_FIELD_END_DATE",     "customfield_10185"),  # End date (Pending 관리 기준)
    "brd_status":   os.getenv("JIRA_FIELD_BRD_STATUS",   "customfield_10101"),
    "feature_type": os.getenv("JIRA_FIELD_FEATURE_TYPE", "customfield_10102"),
}

# BRD 상태 → 승인 여부 매핑
# Pre-BRD는 상태값이 아닌 생성일 기준 (created < 2026-06-08 = Cycle 1 시작일)
# 보류 상태라도 분석 결과 R1~R4 해당 시 → 반려로 최종 분류
BRD_STATUS_MAP = {
    # Approved
    "Confirmed":          "Approved",
    "HQ Discussion":      "Approved",
    "In Business Review": "Approved",
    "진행 중":             "Approved",
    "QA Sign-Off":        "Approved",
    "Re-Opened":          "Approved",
    "종료":               "Approved",
    "Deployed":           "Approved",
    "Dropped":            "Approved",
    "RESOLVE":            "Approved",
    "해결됨":              "Approved",
    # 보류
    "BRD Submitted":      "보류",
    "Create Issue":       "보류",
    "미해결":              "보류",
    "Reopen":             "보류",
    "Revision Requested": "보류",
}

# Priority 점수 산정 대상 항목 (각 0 또는 1, 합산 0~5)
# 시급성(urgency)은 Fast Track 분류용이며 합산에서 제외
SCORE_KEYS_FOR_PRIORITY = [
    "business_performance",
    "customer_experience",
    "operational_efficiency",
    "global_reach",
    "platform_strategy",
]

# 지역 분류
EU_COUNTRIES = {
    "Italy", "Spain", "France", "Germany", "Netherlands",
    "Belgium", "Poland", "Portugal", "Sweden", "Norway",
    "Denmark", "Finland", "Austria", "Switzerland", "UK",
}

# HMG Confluence 참조 페이지 (읽기 전용, Jira 인증 재사용)
HMG_DOC1_FOLDER_3Q = os.getenv("HMG_DOC1_FOLDER_3Q", "362152825")  # KR_2026_3Q 폴더 (7~9월)
HMG_DOC1_FOLDER_Q4 = os.getenv("HMG_DOC1_FOLDER_Q4", "362152798")  # 0. 2026 KR Weekly Ticket 폴더 (10~12월)
HMG_DOC2_PAGE_ID   = os.getenv("HMG_DOC2_PAGE_ID",   "657055974")  # 신규/개선 전체 현황 참조 페이지
