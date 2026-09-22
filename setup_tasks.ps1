# OneApp Ticket Analyzer - Windows 작업 스케줄러 설치 스크립트
# ══════════════════════════════════════════════════
# ※ 모든 시각은 시스템 로컬 시각 기준 = KST (UTC+9)
#    Windows 작업 스케줄러는 항상 로컬 시간 사용
#    시스템 시간대 확인: tzutil /g → "Korea Standard Time" 이어야 함
# ══════════════════════════════════════════════════
# 실행 방법: 관리자 권한 PowerShell에서 .\setup_tasks.ps1
# 스케줄:
#   Doc1 월요일 11:00 → 전체 재생성 (run_doc1.bat)
#   Doc1 화~금 11:00 → 당일 신규 티켓 추가 (run_doc1_daily.bat)
#   Doc2 평일 11:00  → 전체 재생성 (run_doc2.bat)

$ScriptDir    = Split-Path -Parent $MyInvocation.MyCommand.Path
$Doc1Bat      = Join-Path $ScriptDir "run_doc1.bat"
$Doc1DailyBat = Join-Path $ScriptDir "run_doc1_daily.bat"
$Doc2Bat      = Join-Path $ScriptDir "run_doc2.bat"
$Doc2DailyBat = Join-Path $ScriptDir "run_doc2_daily.bat"
$SnapshotBat  = Join-Path $ScriptDir "run_snapshot.bat"
$NotifyBat    = Join-Path $ScriptDir "run_notify.bat"
$UpdateBat    = Join-Path $ScriptDir "update.bat"

if (-not (Test-Path $Doc1Bat))      { Write-Error "run_doc1.bat 없음: $Doc1Bat"; exit 1 }
if (-not (Test-Path $Doc1DailyBat)) { Write-Error "run_doc1_daily.bat 없음: $Doc1DailyBat"; exit 1 }
if (-not (Test-Path $Doc2Bat))      { Write-Error "run_doc2.bat 없음: $Doc2Bat"; exit 1 }
if (-not (Test-Path $Doc2DailyBat)) { Write-Error "run_doc2_daily.bat 없음: $Doc2DailyBat"; exit 1 }
if (-not (Test-Path $SnapshotBat))  { Write-Error "run_snapshot.bat 없음: $SnapshotBat"; exit 1 }
if (-not (Test-Path $NotifyBat))    { Write-Error "run_notify.bat 없음: $NotifyBat"; exit 1 }

# ── 공통 설정 ───────────────────────────────────────────────────────
# Daily: 예약 시간 놓쳤으면 켜지는 즉시 실행
$Settings = New-ScheduledTaskSettingsSet `
    -WakeToRun `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable

# Weekly: StartWhenAvailable 제거 — 부팅 직후 조기 실행 시 S4U 인증 실패 방지
# 월요일 예약 시각에 PC가 켜져 있어야 실행됨
$WeeklySettings = New-ScheduledTaskSettingsSet `
    -WakeToRun `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -MultipleInstances IgnoreNew

$Principal = New-ScheduledTaskPrincipal `
    -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType S4U `
    -RunLevel Highest

# ── 구버전 CCI_ 태스크 정리 ────────────────────────────────────────
foreach ($old in @("CCI_Doc1_Weekly","CCI_Doc1_Daily","CCI_Doc2_Weekly","CCI_Doc2_Daily",
                   "CCI_Doc1","CCI_Doc2","CCI_Snapshot_Daily","CCI_Notify",
                   "CCI_Doc2_Doc3_Daily","CCI_Doc3_Daily","CCI_AutoUpdate")) {
    if (Get-ScheduledTask -TaskName $old -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $old -Confirm:$false
        Write-Host "[정리] $old 기존 태스크 제거"
    }
}

# ── Task 1: Doc1 월요일 전체 재생성 (월 11:00) ──────────────────────
$Trigger1 = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At "11:00"

$Action1 = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument "/c `"$Doc1Bat`"" `
    -WorkingDirectory $ScriptDir

if (Get-ScheduledTask -TaskName "OneApp_Doc1_Weekly" -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName "OneApp_Doc1_Weekly" -Confirm:$false
}
Register-ScheduledTask `
    -TaskName "OneApp_Doc1_Weekly" `
    -Description "OneApp KKR 주간 보고 전체 재생성 (매주 월 11:00)" `
    -Trigger $Trigger1 `
    -Action $Action1 `
    -Settings $WeeklySettings `
    -Principal $Principal | Out-Null
Write-Host "[OK] OneApp_Doc1_Weekly 등록 완료 (매주 월요일 11:00)"

# ── Task 2: Doc1 화~금 신규 티켓 추가 (화~금 11:00) ────────────────
$Trigger1D = New-ScheduledTaskTrigger `
    -Weekly `
    -DaysOfWeek Tuesday,Wednesday,Thursday,Friday `
    -At "11:00"

$Action1D = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument "/c `"$Doc1DailyBat`"" `
    -WorkingDirectory $ScriptDir

if (Get-ScheduledTask -TaskName "OneApp_Doc1_Daily" -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName "OneApp_Doc1_Daily" -Confirm:$false
}
Register-ScheduledTask `
    -TaskName "OneApp_Doc1_Daily" `
    -Description "OneApp Doc1 당일 신규 티켓 추가 (화~금 11:00)" `
    -Trigger $Trigger1D `
    -Action $Action1D `
    -Settings $Settings `
    -Principal $Principal | Out-Null
Write-Host "[OK] OneApp_Doc1_Daily 등록 완료 (화~금 11:00)"

# ── Task 3: Doc2 월요일 전체 재생성 (월 10:00) ──────────────────────
$Trigger2 = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At "10:00"

$Action2 = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument "/c `"$Doc2Bat`"" `
    -WorkingDirectory $ScriptDir

if (Get-ScheduledTask -TaskName "OneApp_Doc2_Weekly" -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName "OneApp_Doc2_Weekly" -Confirm:$false
}
Register-ScheduledTask `
    -TaskName "OneApp_Doc2_Weekly" `
    -Description "OneApp 신규/개선 전체 현황 전체 재생성 (매주 월 10:00)" `
    -Trigger $Trigger2 `
    -Action $Action2 `
    -Settings $WeeklySettings `
    -Principal $Principal | Out-Null
Write-Host "[OK] OneApp_Doc2_Weekly 등록 완료 (매주 월요일 10:00)"

# ── Task 4: Doc2 일일 업데이트 (월16시, 화~금 16시) ─────────────────
$Trigger2D = New-ScheduledTaskTrigger `
    -Weekly `
    -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday `
    -At "16:00"

$Action2D = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument "/c `"$Doc2DailyBat`"" `
    -WorkingDirectory $ScriptDir

if (Get-ScheduledTask -TaskName "OneApp_Doc2_Daily" -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName "OneApp_Doc2_Daily" -Confirm:$false
}
Register-ScheduledTask `
    -TaskName "OneApp_Doc2_Daily" `
    -Description "OneApp Doc2 당일 신규 티켓 업데이트 (평일 16:00)" `
    -Trigger $Trigger2D `
    -Action $Action2D `
    -Settings $Settings `
    -Principal $Principal | Out-Null
Write-Host "[OK] OneApp_Doc2_Daily 등록 완료 (평일 16:00, 신규 티켓 없으면 자동 종료)"

# ── Task: Doc1-1 회차별 마감 히스토리 스냅샷 (평일 18:00, 마감일 아니면 자동 종료) ──
$TriggerSnap = New-ScheduledTaskTrigger `
    -Weekly `
    -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday `
    -At "18:00"

$ActionSnap = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument "/c `"$SnapshotBat`"" `
    -WorkingDirectory $ScriptDir

if (Get-ScheduledTask -TaskName "OneApp_Snapshot_Daily" -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName "OneApp_Snapshot_Daily" -Confirm:$false
}
Register-ScheduledTask `
    -TaskName "OneApp_Snapshot_Daily" `
    -Description "회차별 마감 히스토리 스냅샷 — 평일 18:00 실행, 마감일만 저장" `
    -Trigger $TriggerSnap `
    -Action $ActionSnap `
    -Settings $Settings `
    -Principal $Principal | Out-Null
Write-Host "[OK] OneApp_Snapshot_Daily 등록 완료 (평일 18:00, 마감일에만 실제 저장)"

# ── Task: Jira 변경 알림 (평일 16:00 KST 1회) ───────────────────────
# ※ Windows 작업 스케줄러는 시스템 로컬 시각 사용 → 시스템이 KST(UTC+9)이면 16:00 = 16:00 KST
$TriggerNotify = New-ScheduledTaskTrigger `
    -Weekly `
    -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday `
    -At "16:00"

$ActionNotify = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument "/c `"$NotifyBat`"" `
    -WorkingDirectory $ScriptDir

if (Get-ScheduledTask -TaskName "OneApp_Notify" -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName "OneApp_Notify" -Confirm:$false
}
Register-ScheduledTask `
    -TaskName "OneApp_Notify" `
    -Description "KCCIVOC/KEUVOCOP 당일 변경사항 이메일 알림 (평일 16:00 KST, 1일치 묶음 발송)" `
    -Trigger $TriggerNotify `
    -Action $ActionNotify `
    -Settings $Settings `
    -Principal $Principal | Out-Null
Write-Host "[OK] OneApp_Notify 등록 완료 (평일 16:00)"

# ── Task: 자동 업데이트 (평일 09:00, 다른 작업보다 먼저) ────────────────
$TriggerUpdate = New-ScheduledTaskTrigger `
    -Weekly `
    -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday `
    -At "09:00"

$ActionUpdate = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument "/c `"$UpdateBat`"" `
    -WorkingDirectory $ScriptDir

if (Get-ScheduledTask -TaskName "OneApp_AutoUpdate" -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName "OneApp_AutoUpdate" -Confirm:$false
}
Register-ScheduledTask `
    -TaskName "OneApp_AutoUpdate" `
    -Description "GitHub 최신 코드 자동 업데이트 (평일 09:00, 다른 작업 전 실행)" `
    -Trigger $TriggerUpdate `
    -Action $ActionUpdate `
    -Settings $Settings `
    -Principal $Principal | Out-Null
Write-Host "[OK] OneApp_AutoUpdate 등록 완료 (평일 09:00)"

Write-Host ""
Write-Host "설치 완료. 등록된 작업:"
Get-ScheduledTask | Where-Object { $_.TaskName -like "OneApp_*" } |
    Select-Object TaskName, State |
    Format-Table -AutoSize
