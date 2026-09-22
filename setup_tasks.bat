@echo off
setlocal

:: OneApp Ticket Analyzer scheduled task registration
:: Works without PowerShell, without admin rights
:: Run by double-clicking or from cmd.exe
:: --silent 인자 시: 출력 최소화 (update.bat에서 호출 시 사용)

set "DIR=%~dp0"
if "%DIR:~-1%"=="\" set "DIR=%DIR:~0,-1%"
set "SILENT=0"
set "SKIP_SELF=0"
if "%1"=="--silent" set "SILENT=1"
if "%2"=="--no-self" set "SKIP_SELF=1"
if "%1"=="--no-self" set "SKIP_SELF=1"

if "%SILENT%"=="0" (
    echo.
    echo ================================================
    echo  OneApp Ticket Analyzer Task Scheduler Setup
    echo  Folder: %DIR%
    echo ================================================
    echo.
)

:: 기존 작업 삭제 (구버전 포함)
schtasks /delete /TN "CCI_Doc1_Weekly"         /F 2>nul
schtasks /delete /TN "CCI_Doc1_Daily"          /F 2>nul
schtasks /delete /TN "CCI_Doc2_Weekly"         /F 2>nul
schtasks /delete /TN "CCI_Doc2_Daily"          /F 2>nul
schtasks /delete /TN "CCI_Doc1"                /F 2>nul
schtasks /delete /TN "CCI_Doc2"                /F 2>nul
schtasks /delete /TN "CCI_Snapshot_Daily"      /F 2>nul
schtasks /delete /TN "CCI_Notify"              /F 2>nul
schtasks /delete /TN "CCI_Doc2_Doc3_Daily"     /F 2>nul
schtasks /delete /TN "CCI_AutoUpdate"          /F 2>nul
schtasks /delete /TN "OneApp_Doc1_Weekly"      /F 2>nul
schtasks /delete /TN "OneApp_Doc1_Daily"       /F 2>nul
schtasks /delete /TN "OneApp_Doc2_Weekly"      /F 2>nul
schtasks /delete /TN "OneApp_Doc2_Daily"       /F 2>nul
schtasks /delete /TN "OneApp_Doc1"             /F 2>nul
schtasks /delete /TN "OneApp_Doc2"             /F 2>nul
schtasks /delete /TN "OneApp_Snapshot_Daily"   /F 2>nul
schtasks /delete /TN "OneApp_Notify"           /F 2>nul
if "%SKIP_SELF%"=="0" schtasks /delete /TN "OneApp_AutoUpdate" /F 2>nul

:: OneApp Ticket Analyzer 실행 작업 등록 (마스터 페이지 + 스냅샷 구조)
schtasks /create /TN "OneApp_Doc1"           /TR "%DIR%\run_doc1.bat"     /SC WEEKLY /D "MON,TUE,WED,THU,FRI" /ST 10:00 /F
schtasks /create /TN "OneApp_Doc2"           /TR "%DIR%\run_doc2.bat"     /SC WEEKLY /D "MON,TUE,WED,THU,FRI" /ST 16:00 /F
schtasks /create /TN "OneApp_Snapshot_Daily" /TR "%DIR%\run_snapshot.bat" /SC WEEKLY /D "MON,TUE,WED,THU,FRI" /ST 18:00 /F
schtasks /create /TN "OneApp_Notify"         /TR "%DIR%\run_notify.bat"   /SC WEEKLY /D "MON,TUE,WED,THU,FRI" /ST 16:00 /F

:: 자동 업데이트 작업 등록 (매일 09:00 — 다른 작업보다 먼저 실행)
if "%SKIP_SELF%"=="0" schtasks /create /TN "OneApp_AutoUpdate"  /TR "%DIR%\update.bat"       /SC WEEKLY /D "MON,TUE,WED,THU,FRI" /ST 09:00 /F

:: 절전 해제 후 실행 + 예약 시각 놓쳤을 때 켜지면 즉시 실행 + 배터리 상태에서도 실행
:: schtasks는 미지원이므로 PowerShell로 사후 적용
powershell -NoProfile -Command ^
  "Get-ScheduledTask -TaskName 'OneApp_*' | ForEach-Object { $s = $_.Settings; $s.WakeToRun = $true; $s.StartWhenAvailable = $true; $s.DisallowStartIfOnBatteries = $false; $s.StopIfGoingOnBatteries = $false; Set-ScheduledTask -TaskName $_.TaskName -Settings $s } | Out-Null"

if "%SILENT%"=="0" (
    echo.
    echo === 등록된 OneApp 작업 목록 ===
    schtasks /query /fo TABLE | findstr "OneApp_"
    echo.
    pause
)
endlocal
