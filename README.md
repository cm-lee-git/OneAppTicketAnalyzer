# CCI Ticket Analyst

KCCIVOC · KEUVOCOP Jira 티켓을 자동으로 분석하고 Confluence 문서를 업데이트하는 자동화 도구입니다.
사내 Claude 프록시(h-chat)를 사용하므로 **사내망에서만 동작**하며, Windows 작업 스케줄러로 자동 실행됩니다.

---

## 자동화 대상 문서

| 문서 | Confluence 폴더 ID | 업데이트 시점 |
|---|---|---|
| 1) KKR OneApp 주간 보고 (Doc1) | 77529216 | 평일 10:00 (월요일 전체 재생성 / 화~금 업데이트) |
| 2) 신규/개선 전체 현황 (Doc2) | 78020650 | 평일 16:00 (전체 재분석) |
| 2-1) 회차별 마감 히스토리 | 77922419 | 평일 18:00 (회차 마감일에만 스냅샷 생성) |
| 이메일 알림 (Notify) | — | 평일 16:00 (상태 변경·신규 댓글 감지 시 발송) |

---

## 처음 세팅

### Step 1. 패키지 설치

```bash
cd cci-analyst
pip install -r requirements.txt
```

### Step 2. .env 파일 작성

`.env.example`을 복사하여 `.env`를 만들고 아래 항목을 입력합니다:

```
JIRA_EMAIL=...                   # Atlassian 로그인 이메일 (hmg.atlassian.net)
JIRA_API_TOKEN=...               # Atlassian API 토큰 (hmg.atlassian.net)
CONFLUENCE_EMAIL=...             # Atlassian 로그인 이메일 (ihqdf.atlassian.net)
CONFLUENCE_API_TOKEN=...         # Atlassian API 토큰 (ihqdf.atlassian.net)
ANTHROPIC_API_KEY=...            # h-chat API 키
ANTHROPIC_BASE_URL=https://internal-apigw-kr.hmg-corp.io/hchat-in/api/v3/claude/messages
ANALYST_OWNER_EMAIL=...          # 본인 이메일 (오류 알림 수신 + Jira 알림 CC)
```

> Jira(`hmg.atlassian.net`)와 Confluence(`ihqdf.atlassian.net`)는 인스턴스가 달라 토큰을 각각 발급해야 합니다.
> Atlassian API 토큰 발급: https://id.atlassian.com/manage-profile/security/api-tokens

### Step 3. Jira 커스텀 필드 ID 확인 (최초 1회)

```bash
python main.py --list-fields
```

출력 목록에서 Country · BRD Status · Feature Type에 해당하는 `customfield_XXXXX` 값을 확인합니다.
기본값은 `config.py`에 하드코딩되어 있으며, 다를 경우 `.env`에서 오버라이드합니다:

```
JIRA_FIELD_COUNTRY=customfield_10175
JIRA_FIELD_BRD_STATUS=customfield_10101
JIRA_FIELD_FEATURE_TYPE=customfield_10102
```

### Step 4. 동작 확인

```bash
python main.py --doc1        # Doc1 즉시 실행
python main.py --doc2        # Doc2 즉시 실행
python main.py --snapshot    # 스냅샷 즉시 실행 (회차 마감일이 아니면 자동 종료)
```

### Step 5. 작업 스케줄러 등록

`setup_tasks.bat`을 더블클릭하거나 cmd에서 실행합니다 (관리자 권한 불필요):

```bat
setup_tasks.bat
```

등록되는 작업 목록:

| 작업 이름 | 실행 시점 | 역할 |
|---|---|---|
| CCI_AutoUpdate | 평일 09:00 | 코드 자동 업데이트 + 스케줄 재등록 |
| CCI_Doc1 | 평일 10:00 | Doc1 업데이트 |
| CCI_Doc2 | 평일 16:00 | Doc2 업데이트 |
| CCI_Notify | 평일 16:00 | 이메일 알림 발송 |
| CCI_Snapshot_Daily | 평일 18:00 | 회차 마감 히스토리 스냅샷 |

> **9시 이후에 컴퓨터를 켜도 CCI_AutoUpdate가 즉시 실행됩니다.**
> `StartWhenAvailable` 설정이 적용되어 있어 예약 시각을 놓쳐도 로그인 직후 실행됩니다. 배터리 상태에서도 동작합니다.

---

## 이후 운영

- **자동 실행**: 컴퓨터가 켜져 있고 로그인된 상태여야 합니다.
- **수동 실행**: 터미널에서 `python main.py --doc1` 등을 직접 실행합니다.
- **코드 수동 업데이트**: `update.bat`을 실행하면 git pull 후 스케줄러를 재등록합니다.
- **로그 확인**: `logs/` 폴더에 날짜별 로그 파일이 저장됩니다.
- **스케줄 변경**: `setup_tasks.bat`을 수정 후 재실행하거나, Windows 작업 스케줄러에서 직접 수정합니다.
- **이메일 수신자 변경**: `notify.py` 상단 `RECIPIENTS` 딕셔너리를 수정합니다.
- **티켓 수동 오버라이드**: `ticket_overrides.json`에서 특정 티켓의 cycle·승인 상태·제외 여부를 조정합니다.

---

## 파일 구조

```
cci-analyst/
├── main.py                      # CLI 진입점
├── config.py                    # 환경변수, Jira/Confluence 설정, BRD 상태 매핑
├── jira_client.py               # Jira API 클라이언트
├── analyzer.py                  # Claude API 호출 → 티켓 분석
├── confluence_client.py         # Confluence API 클라이언트
├── cycle.py                     # 회차(Cycle) 계산 (앵커: 2026-06-08, 2주 단위)
├── doc1_updater.py              # Doc1 빌드
├── doc2_updater.py              # Doc2 빌드
├── snapshot.py                  # Doc2-1 스냅샷
├── notify.py                    # 이메일 알림
├── auto_update.py               # git 없이 ZIP으로 코드 업데이트 (대체 수단)
├── run_doc1.bat                 # Doc1 실행 (월요일 전체 재생성)
├── run_doc1_daily.bat           # Doc1 실행 (화~금 업데이트)
├── run_doc2.bat                 # Doc2 실행
├── run_doc2_daily.bat           # Doc2 실행 (일간)
├── run_snapshot.bat             # 스냅샷 실행
├── run_notify.bat               # 알림 실행
├── update.bat                   # 코드 업데이트 + 스케줄 재등록
├── setup_tasks.bat              # 작업 스케줄러 일괄 등록 (관리자 권한 불필요)
├── setup_tasks.ps1              # PowerShell 버전 (관리자 권한 필요)
├── ticket_overrides.json        # 티켓별 수동 오버라이드
├── prompts/
│   └── scoring_v2_system_prompt.md  # Claude 분석 프롬프트
├── logs/                        # 실행 로그 (git 미포함)
└── .env                         # 인증 정보 (git 미포함)
```

런타임에 자동 생성되는 파일 (git 미포함):

| 파일 | 설명 |
|---|---|
| `notify_state.json` | 알림 발송 상태 영속 데이터 |
| `tickets_analyzed_latest.json` | 마지막 분석 결과 캐시 (`--use-cache` 시 재사용) |
| `cycle_snapshots.json` | 회차 마감 시점 집계 데이터 |
