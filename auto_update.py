"""GitHub private repo에서 최신 코드를 ZIP으로 받아 현재 폴더에 적용.

.env, logs/, notify_state.json 등 런타임 파일은 보존.
setup_tasks.bat을 재실행해 스케줄러도 자동 갱신.
"""
from dotenv import load_dotenv; load_dotenv()

import io, os, shutil, subprocess, sys, zipfile
import requests
from datetime import datetime

REPO   = "cm-lee-git/claude_ticket_analyst"
BRANCH = "main"
HERE   = os.path.dirname(os.path.abspath(__file__))

# 업데이트 시 절대 덮어쓰면 안 되는 파일/폴더
PRESERVE = {
    ".env",
    "logs",
    "notify_state.json",
    "notify_state.json.bak",
    "tickets_analyzed_latest.json",
    "cycle_snapshots.json",
    "ticket_overrides.json",
}


def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}")
    log_dir = os.path.join(HERE, "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, f"update_{datetime.now().strftime('%Y%m%d')}.log")
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {msg}\n")


def _gh_headers(token: str) -> dict:
    h = {"Accept": "application/vnd.github+json"}
    if token:
        h["Authorization"] = f"token {token}"
    return h


def download_zip(token: str) -> bytes:
    url = f"https://api.github.com/repos/{REPO}/zipball/{BRANCH}"
    r = requests.get(url, headers=_gh_headers(token), timeout=60)
    r.raise_for_status()
    return r.content


def get_latest_sha(token: str) -> str:
    url = f"https://api.github.com/repos/{REPO}/commits/{BRANCH}"
    r = requests.get(url, headers=_gh_headers(token), timeout=30)
    r.raise_for_status()
    return r.json()["sha"]


def read_current_sha() -> str:
    sha_file = os.path.join(HERE, ".last_update_sha")
    if os.path.exists(sha_file):
        with open(sha_file, "r") as f:
            return f.read().strip()
    return ""


def write_current_sha(sha: str):
    sha_file = os.path.join(HERE, ".last_update_sha")
    with open(sha_file, "w") as f:
        f.write(sha)


def apply_zip(zip_bytes: bytes):
    """ZIP 내용을 현재 폴더에 적용. PRESERVE 목록은 건드리지 않음."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = zf.namelist()
        # GitHub ZIP은 최상위에 "repo-branch-sha/" 폴더가 있음
        prefix = names[0].split("/")[0] + "/"

        for name in names:
            if not name.startswith(prefix):
                continue
            rel = name[len(prefix):]          # 폴더명 제거
            if not rel:
                continue                       # 루트 폴더 자체는 건너뜀

            # PRESERVE 대상이면 건너뜀
            top = rel.split("/")[0]
            if top in PRESERVE:
                continue

            dest = os.path.join(HERE, rel.replace("/", os.sep))

            if name.endswith("/"):             # 폴더
                os.makedirs(dest, exist_ok=True)
            else:                              # 파일
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with zf.open(name) as src, open(dest, "wb") as dst:
                    dst.write(src.read())


def run_setup_tasks():
    bat = os.path.join(HERE, "setup_tasks.bat")
    if os.path.exists(bat):
        subprocess.run([bat, "--silent"], shell=True, cwd=HERE)


def main():
    token = os.getenv("GITHUB_TOKEN", "").strip()  # public repo이면 없어도 동작

    log("최신 커밋 확인 중...")
    try:
        latest_sha = get_latest_sha(token)
    except Exception as e:
        log(f"[오류] GitHub 접근 실패: {e}")
        sys.exit(1)

    current_sha = read_current_sha()
    if latest_sha == current_sha:
        log(f"이미 최신 버전입니다 ({latest_sha[:7]}). 업데이트 불필요.")
        return

    log(f"새 버전 발견: {current_sha[:7] or '(첫 실행)'} → {latest_sha[:7]}")
    log("ZIP 다운로드 중...")
    try:
        zip_bytes = download_zip(token)
    except Exception as e:
        log(f"[오류] 다운로드 실패: {e}")
        sys.exit(1)

    log(f"다운로드 완료 ({len(zip_bytes)//1024}KB). 파일 적용 중...")
    apply_zip(zip_bytes)
    write_current_sha(latest_sha)

    log("작업 스케줄러 재등록 중...")
    run_setup_tasks()

    log(f"업데이트 완료 → {latest_sha[:7]}")


if __name__ == "__main__":
    main()
