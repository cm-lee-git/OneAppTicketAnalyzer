@echo off
setlocal
cd /d "%~dp0"

set "LOGDIR=%~dp0logs"
if not exist "%LOGDIR%" mkdir "%LOGDIR%"
set "LOGFILE=%LOGDIR%\update_%date:~0,4%%date:~5,2%%date:~8,2%.log"
set "LOGFILE=%LOGFILE: =0%"

echo [%date% %time%] ===== 자동 업데이트 시작 ===== >> "%LOGFILE%"

echo [%date% %time%] git pull 실행... >> "%LOGFILE%"
git pull origin main >> "%LOGFILE%" 2>&1
if errorlevel 1 (
    echo [%date% %time%] [경고] git pull 실패. 로그 확인 필요. >> "%LOGFILE%"
) else (
    echo [%date% %time%] git pull 완료. >> "%LOGFILE%"
)

echo [%date% %time%] 작업 스케줄러 재등록... >> "%LOGFILE%"
call "%~dp0setup_tasks.bat" --silent --no-self >> "%LOGFILE%" 2>&1

echo [%date% %time%] ===== 자동 업데이트 완료 ===== >> "%LOGFILE%"
endlocal
