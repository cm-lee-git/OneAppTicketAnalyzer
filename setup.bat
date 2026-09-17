@echo off
setlocal
cd /d "%~dp0"

echo.
echo ================================================
echo  CCI Analyst 초기 설정
echo ================================================
echo.

:: ── 1. Python 확인 ────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo [오류] Python이 설치되어 있지 않습니다.
    echo https://www.python.org/downloads/ 에서 설치 후 다시 실행하세요.
    pause
    exit /b 1
)
echo [OK] Python 확인됨

:: ── 2. Git 확인 및 자동 설치 ──────────────────────
git --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo [Git 없음] winget 으로 Git 을 자동 설치합니다...
    winget install --id Git.Git -e --source winget --silent --accept-package-agreements --accept-source-agreements
    :: 설치 후 PATH 갱신을 위해 환경변수 다시 로드
    call refreshenv >nul 2>&1
    git --version >nul 2>&1
    if errorlevel 1 (
        echo.
        echo [오류] Git 자동 설치에 실패했습니다.
        echo 아래 주소에서 직접 설치 후 이 파일을 다시 실행하세요.
        echo   https://git-scm.com/download/win
        pause
        exit /b 1
    )
    echo [OK] Git 설치 완료
) else (
    echo [OK] Git 확인됨
)

:: ── 3. Git 저장소 초기화 (최초 1회 / ZIP 압축 해제 시) ──
if not exist ".git" (
    echo.
    echo [Git 초기화] 최초 설정 중...
    git init
    git remote add origin https://github.com/cm-lee-git/claude_ticket_analyst.git
    git fetch origin main
    git checkout -f main
    echo [OK] Git 저장소 초기화 완료
)

:: ── 4. pip 패키지 설치 ────────────────────────────
echo.
echo [패키지] 설치 중...
pip install -r requirements.txt
if errorlevel 1 (
    echo [오류] pip install 실패. 위 오류 메시지를 확인하세요.
    pause
    exit /b 1
)
echo [OK] 패키지 설치 완료

:: ── 5. .env 파일 생성 ─────────────────────────────
echo.
echo [환경설정] .env 파일 확인...
if not exist ".env" (
    copy ".env.example" ".env" >nul
    echo [생성됨] .env 파일이 만들어졌습니다.
    echo.
    echo !! 중요: 아래 파일을 열어서 본인의 API 키와 이메일을 입력하세요 !!
    echo    %~dp0.env
    echo.
    notepad "%~dp0.env"
) else (
    echo [OK] .env 파일이 이미 존재합니다.
)

:: ── 6. 작업 스케줄러 등록 ─────────────────────────
echo.
echo [스케줄러] Windows 작업 스케줄러 등록 중...
call "%~dp0setup_tasks.bat"

echo.
echo ================================================
echo  설정 완료!
echo.
echo  [자동 업데이트 안내]
echo  - 매일 08:30 에 GitHub 최신 코드를 자동으로 받아옵니다.
echo  - 수동 업데이트: update.bat 실행
echo ================================================
echo.
endlocal
