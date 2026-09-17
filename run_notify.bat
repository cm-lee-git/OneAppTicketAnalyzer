@echo off
cd /d "%~dp0"

if not exist "logs" mkdir logs

set LOGFILE=logs\notify_%date:~0,4%%date:~5,2%%date:~8,2%.log
set LOGFILE=%LOGFILE: =0%

python notify.py >> "%LOGFILE%" 2>&1
