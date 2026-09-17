@echo off
cd /d "%~dp0"

if not exist "logs" mkdir logs

set LOGFILE=logs\doc2_%date:~0,4%%date:~5,2%%date:~8,2%_%time:~0,2%%time:~3,2%.log
set LOGFILE=%LOGFILE: =0%

echo [%date% %time%] Doc2 업데이트 시작 >> "%LOGFILE%"
python main.py --doc2 >> "%LOGFILE%" 2>&1
echo [%date% %time%] 완료 >> "%LOGFILE%"
