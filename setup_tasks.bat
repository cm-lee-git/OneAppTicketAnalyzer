@echo off
setlocal

:: CCI scheduled task registration
:: Works without PowerShell, without admin rights
:: Run by double-clicking or from cmd.exe
:: --silent 인자 시: 출력 최소화 (update.bat에서 호출 시 사용)

set "DIR=%~dp0"
if "%DIR:~-1%"=="\" set "DIR=%DIR:~0,-1%"
set "SILENT=0"
if "%1"=="--silent" set "SILENT=1"

if "%SILENT%"=="0" (
    echo.
    echo ================================================
    echo  CCI Task Scheduler Setup
    echo  Folder: %DIR%
    echo ================================================
    echo.
)

:: 기존 작업 삭제 (구버전 포함)
schtasks /delete /TN "CCI_Doc1_Weekly"     /F 2>nul
schtasks /delete /TN "CCI_Doc1_Daily"      /F 2>nul
schtasks /delete /TN "CCI_Doc2_Weekly"     /F 2>nul
schtasks /delete /TN "CCI_Doc2_Daily"      /F 2>nul
schtasks /delete /TN "CCI_Doc1"            /F 2>nul
schtasks /delete /TN "CCI_Doc2"            /F 2>nul
schtasks /delete /TN "CCI_Snapshot_Daily"  /F 2>nul
schtasks /delete /TN "CCI_Notify"          /F 2>nul
schtasks /delete /TN "CCI_Doc2_Doc3_Daily" /F 2>nul
schtasks /delete /TN "CCI_AutoUpdate"      /F 2>nul

:: CCI 실행 작업 등록 (마스터 페이지 + 스냅샷 구조)
schtasks /create /TN "CCI_Doc1"           /TR "%DIR%\run_doc1.bat"     /SC WEEKLY /D MON /ST 10:00 /F
schtasks /create /TN "CCI_Doc2"           /TR "%DIR%\run_doc2.bat"     /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 16:00 /F
schtasks /create /TN "CCI_Snapshot_Daily" /TR "%DIR%\run_snapshot.bat" /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 18:00 /F
schtasks /create /TN "CCI_Notify"         /TR "%DIR%\run_notify.bat"   /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 16:00 /F

:: 자동 업데이트 작업 등록 (매일 08:30 — 다른 작업보다 먼저 실행)
schtasks /create /TN "CCI_AutoUpdate"     /TR "%DIR%\update.bat"       /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 08:30 /F

if "%SILENT%"=="0" (
    echo.
    echo === 등록된 CCI 작업 목록 ===
    schtasks /query /fo TABLE | findstr "CCI_"
    echo.
    pause
)
endlocal
