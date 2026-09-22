# OneApp Ticket Analyzer — 프로젝트 컨텍스트

이 파일 하나로 신규 개발자가 프로젝트를 온보딩할 수 있도록 작성되었습니다.
글로벌 `CLAUDE.md` 또는 사용자별 메모리 파일 없이도 모든 판단 기준이 여기에 포함됩니다.

---

## 역할 정의

INNOCEAN 디지털플랫폼2팀 소속 **CCI Digital Platform 티켓 분석 봇**.
GBCXD(고객경험본부)와 협력하여 Jira 신규/개선 티켓을 자동 분석하고 Confluence 문서를 생성·유지한다.

**주요 책임:**
1. 티켓 내용(배경·문제·기능 유형) 요약
2. GBCXD New/Improvement Prioritization Framework로 점수 산정
3. 권역·승인 상태·회차 분류
4. 상태 변경 감지 및 에스컬레이션 알림
5. Confluence 3개 문서(Doc1 / Doc2 / Doc2-1) 자동 업데이트

**출력 원칙:** 텍스트 필드(summary, background, problem 등)는 **한국어**, 필드 키·JSON 구조는 **영어**로 출력.

---

## 1. 프로젝트 개요

INNOCEAN 디지털플랫폼2팀이 KIA GBCXD(고객경험본부)와 운영하는 **CCI Digital Platform 티켓 자동 분석 봇**.
Jira에서 Kia 관련 신규/개선 및 Pending 티켓을 가져와 Claude로 분석하고, Confluence 문서를 자동 생성한다.

- **Jira 인스턴스**: `https://hmg.atlassian.net` (프로젝트: KCCIVOC, KEUVOCOP)
- **Confluence 인스턴스**: `https://ihqdf.atlassian.net`
- **Claude API**: h-chat 사내 프록시 (`ANTHROPIC_BASE_URL`로 설정, api.anthropic.com 직접 호출 불가)
  - httpx로 직접 호출 (`analyzer.py`): `ANTHROPIC_BASE_URL`이 `/messages`로 끝나면 그대로 사용, 아니면 `/v1/messages` 추가
- **자동화**: GitHub Actions 사용 안 함 (h-chat이 사내망 전용) → Windows 작업 스케줄러로 로컬 실행

> **CCIPRJ 프로젝트 제외**: 2026-08-06 이후 CCIPRJ는 조회 대상에서 완전 제거. KCCIVOC + KEUVOCOP만 사용.

---

## 2. 실행 방법

```bash
# Doc1 업데이트 (KKR OneApp 주간 보고) — 월요일 전체 재생성
python main.py --doc1

# Doc1 업데이트 — 화~금 당일 신규 티켓만 추가
python main.py --doc1-daily

# Doc2 업데이트 (신규/개선 전체 현황) — 월요일 전체 재생성
python main.py --doc2

# Doc2 업데이트 — 당일 신규 티켓 있을 때 전체 재분석 후 업데이트
python main.py --doc2-daily

# Doc2-daily 실행 시 Claude 분석 생략하고 캐시 재사용
python main.py --doc2-daily --use-cache

# 회차 마감 히스토리 스냅샷 (회차 마감일 18:00 실행)
python main.py --snapshot

# 전체 업데이트 (Doc1 + Doc2)
python main.py --all

# 특정 Confluence 페이지 삭제
python main.py --delete-page PAGE_ID

# Jira 커스텀 필드 ID 목록 확인
python main.py --list-fields
```

---

## 3. 자동화 스케줄 (Windows 작업 스케줄러)

| 작업 이름 | 배치파일 | 실행 시점 |
|---|---|---|
| OneApp_Doc1 | `run_doc1.bat` | 평일 매일 10:00 |
| OneApp_Doc2 | `run_doc2.bat` | 평일 매일 16:00 |
| OneApp_Notify | `run_notify.bat` | 평일 매일 16:00 |
| OneApp_Snapshot_Daily | `run_snapshot.bat` | 평일 매일 18:00 |

**문서 업데이트 방식:**
- Doc1: **월요일** 신규 주간 페이지 생성(`M/D KKR OneApp`), **화~금** 동일 주간 페이지 업데이트. 매일 실행 시 변경 내용을 `M/D 업데이트` 하위 서브페이지로 자동 생성.
- Doc2: 매일 마스터 페이지 전체 갱신. 변경 내용을 `M/D 업데이트` 하위 서브페이지로 자동 생성.

스케줄러 등록:
- `setup_tasks.bat` — 관리자 권한 불필요, `schtasks.exe` 기반, `%~dp0` 동적 경로
- `setup_tasks.ps1` — `RunLevel Highest` 사용, 관리자 권한 필요; Weekly 전용 `$WeeklySettings`에 `StartWhenAvailable` 제거됨

로그: `logs/` 폴더에 날짜별 저장

> **Outlook COM 이메일**: 사용자 로그인 + Outlook 실행 중 상태에서만 동작.

---

## 4. 파일 구조

```
OneAppTicketAnalyzer/
├── main.py              # CLI 진입점 (--doc1 / --doc1-daily / --doc2 / --doc2-daily / --snapshot / --all)
├── config.py            # 환경변수, Jira/Confluence 설정, BRD 상태 매핑
├── jira_client.py       # Jira API 클라이언트 (티켓 조회, description 수신)
├── analyzer.py          # Claude API 호출 → 티켓 분석 (summary/background/problem/scores)
├── confluence_client.py # Confluence API 클라이언트 (페이지 생성/업데이트/프로퍼티)
├── cycle.py             # 회차(Cycle) 계산 (앵커: 2026-06-08, 2주 단위)
├── doc1_updater.py      # Doc1 HTML 빌드 및 Confluence 페이지 생성
├── doc2_updater.py      # Doc2 업데이트 로직
├── snapshot.py          # Doc2-1 회차별 마감 히스토리 스냅샷
├── notify.py            # Jira 댓글/상태 변경 감지 → 이메일 알림
├── run_doc1.bat         # Doc1 월요일 전체 재생성
├── run_doc1_daily.bat   # Doc1 화~금 신규 티켓 추가
├── run_doc2.bat         # Doc2 월요일 전체 재생성
├── run_doc2_daily.bat   # Doc2 당일 신규 티켓 업데이트
├── run_snapshot.bat     # 회차 마감 히스토리 스냅샷
├── run_notify.bat       # 이메일 알림 실행
├── setup_tasks.bat      # Windows 작업 스케줄러 일괄 등록 (관리자 권한 불필요)
├── setup_tasks.ps1      # PowerShell 버전 스케줄러 등록 (관리자 권한 필요)
├── ticket_overrides.json  # 티켓별 수동 점수/분류 오버라이드
├── notify_state.json      # notify 상태 영속 데이터
├── tickets_analyzed_latest.json  # 마지막 분석 결과 캐시 (--use-cache 시 재사용)
├── cycle_snapshots.json   # 회차 스냅샷 영속 데이터 (아래 §15 참고)
├── logs/                  # 실행 로그 (날짜별)
└── .env                   # 인증 정보 (git 미포함)
```

---

## 5. 티켓 조회 필터 규칙

### 5-1. 날짜 필터

모든 문서(Doc1/Doc2) 및 **Doc1 Pending 관리 표** 모두 동일 적용:
- `created >= "2026-01-01"` 이후 티켓만

### 5-2. 프로젝트 필터

**KCCIVOC, KEUVOCOP 두 프로젝트만** 사용. CCIPRJ는 2026-08-06부터 제외.

```python
# jira_client.py의 JQL 기반
'project in (KCCIVOC, KEUVOCOP)'
'AND issuetype in ("신규/개선", "Urgent Request")'
```

### 5-3. 브랜드 필터

- **customfield_10183** (Kia/Common 브랜드 필드): `Kia` 또는 `Common`
- **customfield_10585** (KMC/ALL 브랜드 필드): `KMC` 또는 `ALL`
- 두 필드 중 하나라도 해당하면 포함 (OR 조건)
- Hyundai / Genesis 전용 티켓은 제외

### 5-4. Weekly JQL (`_WEEKLY_JQL`)

Doc1/Doc2 주간·일간 업데이트 시 적용. 종료된 티켓 제외:
```
AND status NOT IN ("Dropped", "해결됨", "종료", "RESOLVE", "Deployed")
```

> `main.py`의 `cmd_doc1`, `cmd_doc2`, `cmd_all`에서 공통으로 사용.

---

## 6. Confluence 문서 구조

| 키 | 폴더 Page ID | 역할 |
|---|---|---|
| `doc1` | `77529216` | 1) KKR OneApp 주간 보고 (AI 생성 페이지의 부모 폴더) |
| `doc2` | `78020650` | 2) 신규/개선 티켓 스크리닝 및 관리 폴더 |
| `doc21` | `77922419` | 2-1) 회차별 마감 히스토리 폴더 |

**Doc1 업데이트 방식**: 고정 마스터 페이지를 매일 전체 갱신 + 하위 스냅샷
- 마스터 페이지 제목: `KKR OneApp 주간 보고 (AI 생성)` (고정, 타임스탬프 없음)
- 부모: `77529216`
- 실행 시: ① 기존 마스터 내용을 하위 스냅샷으로 보관 → ② 마스터 페이지 전체 갱신
- 스냅샷 제목 형식: `MM-DD HH:MM 스냅샷` (마스터 페이지의 자식 페이지)

**Doc2 업데이트 방식**: 동일한 마스터 페이지 + 스냅샷 구조
- 마스터 페이지 제목: `신규/개선 전체 현황 (AI 생성)` (고정)
- 부모: `78020650`

**Doc2-1 생성 방식**: 회차 마감일(매 회차 마지막 금요일) 18:00 스냅샷
- 제목 형식: `MM-DD HH:MM 회차별 마감 히스토리 (AI 생성)`
- 부모: `77922419`

**Doc2 Confluence 폴더 404 대응**: `get_child_pages()`에서 `/pages/{id}/children` 404 시 `/pages?parentId={id}`로 폴백.

---

## 7. 사이클(Cycle) 정의

- **단위**: 2주 (고정 14일, 공휴일 고려 안 함)
- **앵커**: 2026-06-08 (월) = 1회차 시작
- **계산식**: `start = 2026-06-08 + n×14`, n = 0, 1, 2, …
- **종료일**: `start + 11일` (금요일)

| 회차 | 시작 | 종료 |
|---|---|---|
| 1 | 2026-06-08 | 2026-06-19 |
| 2 | 2026-06-22 | 2026-07-03 |
| 3 | 2026-07-06 | 2026-07-17 |
| 4 | 2026-07-20 | 2026-07-31 |
| 5 | 2026-08-03 | 2026-08-14 |
| 6 | 2026-08-17 | 2026-08-28 |

**Pre-BRD**: `created < 2026-06-08` → cycle_number = 0
**Post-BRD**: `created >= 2026-06-08` → cycle_number ≥ 1

---

## 8. 스코어링 프레임워크

### 8-1. 점수 구조

모든 도메인은 **0 또는 1 이진값** (0~5 가중평균 아님).

| 도메인 | 키 | Priority 합산 포함 여부 |
|---|---|---|
| 시급성 | `urgency` | **제외** (Fast Track 분류 전용) |
| 사업 성과 기여 | `business_performance` | 포함 |
| 고객 경험 영향도 | `customer_experience` | 포함 |
| 운영 효율화 | `operational_efficiency` | 포함 |
| 글로벌 파급 범위 | `global_reach` | 포함 |
| 플랫폼 운영 전략 연계도 | `platform_strategy` | 포함 |

**Priority 점수** = `business_performance + customer_experience + operational_efficiency + global_reach + platform_strategy` (합계 0~5)

### 8-2. 도메인별 1점 기준

**urgency (시급성)** — Fast Track 해당 여부:
- 대규모 장애(Major Incident) 대응
- 법규/컴플라이언스 대응
- 리더십(임원/HQ) 직접 지시 사항

**business_performance (사업 성과 기여)**:
- 전환율·구매·리드 유도에 **직접** 영향이 있는 경우
- 간접 영향(브랜딩 개선 등)은 0점

**customer_experience (고객 경험 영향도)**:
- 반복 VoC 또는 CS 건수로 입증된 불편
- 행동 데이터(이탈률, 세션, 완료율 등) 기반 근거가 있는 경우

**operational_efficiency (운영 효율화)**:
- 수기 반복 작업 제거 또는 비용 절감 수치가 구체적으로 확인되는 경우

**global_reach (글로벌 파급 범위)**:
- **MAU 2M+ OR 수혜 국가 비율 50%+** 중 **하나만 충족해도** 1점
- 두 조건 모두 미충족이면 0점 (단일 국가 요청은 무조건 0)

**platform_strategy (플랫폼 운영 전략 연계도)**:
- KR KPI: 원격 제어 / 정비 알림 / 충전 기능
- EU KPI: 앱 다운로드 & 가입
- Global KPI: Non-CCS/CCS 표준화, BPM 연계

### 8-3. BRD 승인 상태 매핑 (`config.py` `BRD_STATUS_MAP`)

**Approved 목록**:
`Confirmed`, `HQ Discussion`, `In Business Review`, `진행 중`, `QA Sign-Off`,
`Re-Opened`, `종료`, `Deployed`, `Dropped`, `RESOLVE`, `해결됨`

**보류(Hold) 목록**:
`BRD Submitted`, `Create Issue`, `미해결`, `Reopen`, `Revision Requested`

> **판단 우선 원칙**: 보류 상태라도 분석 결과 R1~R4 해당 시 → 최종 **반려** 분류.

---

## 9. 보류 유형 분류 (H1~H4)

H5는 2026-08-05부로 제거됨. H1~H4만 사용.

| 코드 | 명칭 | 1점 기준 (보류 판정) |
|---|---|---|
| H1 | 필수항목 누락 | 배경·문제·기능 개선 요건 중 1개 이상 누락 |
| H2 | 요건 미구체화 | 정성적 목표만 있고 측정 가능한 지표 없음 |
| H3 | 데이터/근거 부족 | 전환율·VoC·MAU 등 수치 미제시 |
| H4 | 선행과제 미완료 | 의존성 있는 선행과제 존재하며 미완료 상태 |

**보류 해소 조건**: 보류 안내일로부터 **10 영업일** 이내 미보완 시 자동 반려.

---

## 10. 반려 유형 분류 (R1~R4)

R5는 2026-08-05부로 제거됨. R1~R4만 사용.

| 코드 | 명칭 | 판정 기준 |
|---|---|---|
| R1 | 자동 판별 | `urgency == 0 AND priority == 0` (AND 보류 상태) → 자동 반려 |
| R2 | 범위 외 | GBCXD 업무 범위 외 요청 |
| R3 | 중복 | 기존 처리 중인 티켓과 실질적으로 동일한 내용 |
| R4 | 전략 방향 상충 | 플랫폼 전략 또는 KPI 방향과 상충 |

**R1 자동 판별** (`analyzer.py`): `urgency == 0 AND priority == 0 AND brd_approval == "보류"` 조건 충족 시 `rejection_code = "R1"` 자동 설정.

---

## 11. 지역 분류 규칙

| 조건 | 분류 |
|---|---|
| `country` 값이 "Global" | **HQ** (프로젝트 무관) |
| KCCIVOC 프로젝트 + non-Global | **KR** |
| KEUVOCOP 프로젝트 + non-Global | **EU** |
| country = "KR" / "Korea" | KR |
| country = EU 국가 (Italy, Spain, France, Germany 등) | EU |
| country = "All" / "Global" / "HQ" | HQ |

> country = "Global"이면 프로젝트가 KCCIVOC여도 HQ로 분류.

---

## 12. BRD 승인 판단 로직 (`_effective_approval`)

`brd_approval` 필드만으로 최종 상태를 결정하지 않음. 다음 우선순위 적용:

```
1. rejection_code 존재 → "반려"
2. hold_code 존재 → "보류"
3. 나머지 → brd_approval 값 그대로
```

이 로직이 `snapshot.py`, `doc2_updater.py` 집계 전반에 적용됨.

---

## 13. 이메일 알림 (notify.py)

**발신**: `cmlee@innocean.com`
**수신**: 프로젝트별 구분
- KCCIVOC 담당: `haesoo@innocean.com`
- KEUVOCOP 담당: `jaekim98@innocean.com`

**참조(CC)**: `rayoun@innocean.com` (공통)

**제목 형식**: `[Jira 알림/PROJ] 상태변경 N건 / 새댓글 N건`

**본문 구조**: "🔄 상태 변경" / "💬 새 댓글" 두 섹션, 최신순 정렬, 티켓 키에만 링크.

**오류 처리**: `detect_status_changes()` / `detect_new_comments()` 각각 `try/except`로 독립 실행 (SSL 오류 등에서 전체 알림 중단 방지).

---

## 14. 참조 문서 복제 규칙

신규 문서 생성 시, 일정 날짜 이전 티켓은 **참조 문서**에서 기존 HTML 행을 그대로 복사해 사용.
Claude 재분석 없이 이전 결과 유지 + 생성 속도 향상.

| 문서 | 참조 Page ID | cutoff 날짜 | 의미 |
|---|---|---|---|
| Doc1 | `93061205` | `2026-08-19` | 이 날짜 이전 생성 티켓 행을 참조 문서에서 복사 |
| Doc2 | `94863368` | `2026-08-17` | 동일 |

**`_load_ref_rows_doc2` 동작**:
1. 참조 문서의 모든 `<a>` 태그 탐색
2. `<li>` 태그 내 참조 링크(내용/배경/문제 열의 링크)는 건너뜀
3. 티켓 키별로 후보 행 수집 후 **rowspan이 가장 큰 행** 선택 (= 티켓 블록 첫 행)
4. rowspan 수만큼 후속 `<tr>` 수집하여 전체 행 조합 반환

---

## 15. Doc1 표 구조

**Pre-BRD (cycle_number = 0)**: 2026-06-08 앵커 이전 생성 티켓, `created` 오름차순 정렬
**Post-BRD (cycle_number ≥ 1)**: `cycle_number` 오름차순 → `created` 오름차순 정렬

**컬럼**: # | Cycle | Key | Ticket Summary | Reporter | Created | Due date | 내용 | 항목 분포(×2) | Priority 점수 | BRD 승인 여부

> Pre-BRD 티켓에는 **BRD 승인 여부 미작성** (해당 프로세스 적용 전 생성).

**내용 셀 형식**:
```
<Summary>
• 1~2문장 요약

<배경>
• 포인트1
• 포인트2

<문제>
• 포인트1

<기존 기능 개선 / 신규 기능>
• 포인트1
```

**Pending 관리 표** (Post-BRD 섹션 하단 자동 추가):
- 조건: `end_date < today` AND 배포 레이블 없는 티켓
- `created >= "2026-01-01"` 동일 적용
- 컬럼: # | Key | Ticket Summary | Reporter | Status | Created | End date | 진척사항 확인 | 배포 필요
- 진척사항 확인·배포 필요는 `-` 자동 채움 (수동 입력 대상)
- **매주 월요일 Doc1 전체 재빌드 시에만 업데이트** (Daily 업데이트 시 건드리지 않음)

---

## 16. 회차 스냅샷 (`cycle_snapshots.json`)

회차 마감 시점(매 회차 마지막 금요일 18:00)의 KR/EU/HQ 티켓 집계를 영속 보관.

```json
{
  "5": {
    "cycle_number": 5,
    "snapshot_date": "2026-08-14",
    "KR": {"total": 2, "approved": 2, "rejected": 0, "pending": 0},
    "EU": {"total": 5, "approved": 1, "rejected": 0, "pending": 4},
    "HQ": {"total": 0, "approved": 0, "rejected": 0, "pending": 0}
  }
}
```

**주의**: `take_snapshot(force_cycle=N)`을 과거 회차 대상으로 실행하면 **현재 Jira 상태**가 반영되어 마감 시점 값과 달라진다. 과거 회차 값이 틀린 경우 `cycle_snapshots.json`을 **직접 수정**할 것.

**`snapshot.py` JQL**: `created >= "2026-01-01" AND created <= "{end_date}"` — 미래 티켓이 과거 회차 집계에 포함되지 않도록 상한 적용.

---

## 17. 환경 설정

`.env` 파일 필수 항목 (`.env.example` 참고):
```
JIRA_EMAIL=...
JIRA_API_TOKEN=...
CONFLUENCE_EMAIL=...
CONFLUENCE_API_TOKEN=...
ANTHROPIC_API_KEY=...           # h-chat API 키
ANTHROPIC_BASE_URL=https://internal-apigw-kr.hmg-corp.io/hchat-in/api/v3/claude/messages

# Jira 커스텀 필드 ID (기본값은 config.py에 하드코딩, 필요시 오버라이드)
JIRA_FIELD_COUNTRY=customfield_10175
JIRA_FIELD_BRD_STATUS=customfield_10101
JIRA_FIELD_FEATURE_TYPE=customfield_10102
```

> `ANTHROPIC_BASE_URL`이 `/messages`로 끝나면 httpx가 그대로 엔드포인트로 사용.
> 그렇지 않으면 `/v1/messages`를 자동 추가 (표준 Anthropic 패턴).
> 필드 ID 확인: `python main.py --list-fields`
