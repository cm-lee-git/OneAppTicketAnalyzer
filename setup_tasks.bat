@echo off
setlocal

:: OneApp Ticket Analyzer - scheduled task registration
:: No admin rights required (uses schtasks.exe)
:: --silent : minimal output (called from update.bat)
:: --no-self: skip OneApp_AutoUpdate re-registration

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

:: Delete old tasks (legacy CCI_* and previous OneApp_*)
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

:: Doc1 Monday - full weekly rebuild (main.py --doc1)
schtasks /create /TN "OneApp_Doc1"           /TR "%DIR%\run_doc1.bat"       /SC WEEKLY /D MON                  /ST 10:00 /F

:: Doc1 Tue-Fri - daily new ticket addition + sub-page (main.py --doc1-daily)
schtasks /create /TN "OneApp_Doc1_Daily"     /TR "%DIR%\run_doc1_daily.bat" /SC WEEKLY /D "TUE,WED,THU,FRI"   /ST 10:00 /F

:: Doc2 weekdays - master doc update + daily sub-page (main.py --doc2-daily)
schtasks /create /TN "OneApp_Doc2"           /TR "%DIR%\run_doc2_daily.bat" /SC WEEKLY /D "MON,TUE,WED,THU,FRI" /ST 16:00 /F

:: Snapshot weekdays - saves only on cycle end dates
schtasks /create /TN "OneApp_Snapshot_Daily" /TR "%DIR%\run_snapshot.bat"   /SC WEEKLY /D "MON,TUE,WED,THU,FRI" /ST 18:00 /F

:: Notify weekdays
schtasks /create /TN "OneApp_Notify"         /TR "%DIR%\run_notify.bat"     /SC WEEKLY /D "MON,TUE,WED,THU,FRI" /ST 16:00 /F

:: Auto-update weekdays 09:00 (git pull + task re-registration)
if "%SKIP_SELF%"=="0" schtasks /create /TN "OneApp_AutoUpdate" /TR "%DIR%\update.bat" /SC WEEKLY /D "MON,TUE,WED,THU,FRI" /ST 09:00 /F

:: Apply advanced settings via PowerShell:
:: WakeToRun + battery/battery-stop fix for all tasks
:: StartWhenAvailable for all EXCEPT OneApp_Doc1 (Mon rebuild: avoid early-boot S4U auth failure)
powershell -NoProfile -Command "Get-ScheduledTask -TaskName 'OneApp_*' | ForEach-Object { $s = $_.Settings; $s.WakeToRun = $true; $s.DisallowStartIfOnBatteries = $false; $s.StopIfGoingOnBatteries = $false; if ($_.TaskName -ne 'OneApp_Doc1') { $s.StartWhenAvailable = $true }; Set-ScheduledTask -TaskName $_.TaskName -Settings $s } | Out-Null"

if "%SILENT%"=="0" (
    echo.
    echo === Registered OneApp tasks ===
    schtasks /query /fo TABLE | findstr "OneApp_"
    echo.
    pause
)
endlocal
