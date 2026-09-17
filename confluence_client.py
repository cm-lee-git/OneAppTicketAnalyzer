import re
import requests
from requests.auth import HTTPBasicAuth
from config import CONFLUENCE_BASE_URL, CONFLUENCE_EMAIL, CONFLUENCE_API_TOKEN, CONFLUENCE_PARENT_PAGE_ID, DOC_TITLE_KEYWORDS, DOC_PAGE_IDS


class ConfluenceClient:
    def __init__(self):
        self.base = f"{CONFLUENCE_BASE_URL}/wiki/api/v2"
        self.auth = HTTPBasicAuth(CONFLUENCE_EMAIL, CONFLUENCE_API_TOKEN)
        self.headers = {"Accept": "application/json", "Content-Type": "application/json"}
        self._page_cache: dict[str, dict] = {}

    def _get(self, path: str, params: dict = None) -> dict:
        r = requests.get(f"{self.base}{path}", auth=self.auth, headers=self.headers, params=params, timeout=30)
        r.raise_for_status()
        return r.json()

    def _put(self, path: str, payload: dict) -> dict:
        r = requests.put(f"{self.base}{path}", auth=self.auth, headers=self.headers, json=payload, timeout=30)
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, payload: dict) -> dict:
        r = requests.post(f"{self.base}{path}", auth=self.auth, headers=self.headers, json=payload, timeout=30)
        if not r.ok:
            print(f"[Confluence 오류] POST {path}: {r.status_code}\n{r.text[:800]}")
        r.raise_for_status()
        return r.json()

    _space_id_cache: str = ""   # 같은 공간이므로 한 번만 조회 후 캐시
    _space_key_cache: str = ""  # v1 API 폴백용 space key 캐시

    def get_space_id(self, page_id: str) -> str:
        if ConfluenceClient._space_id_cache:
            return ConfluenceClient._space_id_cache
        # v2 API 시도
        try:
            data = self._get(f"/pages/{page_id}")
            sid = data["spaceId"]
            ConfluenceClient._space_id_cache = sid
            # space key도 같이 확보 (v1 폴백용)
            try:
                space_data = self._get(f"/spaces/{sid}")
                ConfluenceClient._space_key_cache = space_data.get("key", "")
            except Exception:
                pass
            return sid
        except Exception:
            pass
        # v1 API 폴백: space.key → v2 spaces API로 spaceId 조회
        base_v1 = f"{CONFLUENCE_BASE_URL}/wiki/rest/api"
        r = requests.get(f"{base_v1}/content/{page_id}",
                         auth=self.auth, headers={"Accept": "application/json"},
                         params={"expand": "space"}, timeout=30)
        r.raise_for_status()
        space_key = r.json()["space"]["key"]
        ConfluenceClient._space_key_cache = space_key
        spaces = self._get("/spaces", {"keys": space_key, "limit": 1})
        sid = spaces["results"][0]["id"]
        ConfluenceClient._space_id_cache = sid
        return sid

    def _post_v1(self, path: str, payload: dict) -> dict:
        base_v1 = f"{CONFLUENCE_BASE_URL}/wiki/rest/api"
        r = requests.post(f"{base_v1}{path}", auth=self.auth, headers=self.headers, json=payload, timeout=30)
        r.raise_for_status()
        return r.json()

    def create_page(self, parent_id: str, title: str, html: str) -> dict:
        """parent_id 하위에 새 페이지 생성 (간격 넓게 포함). v2 실패 시 v1 폴백."""
        space_id = self.get_space_id(parent_id)
        try:
            result = self._post("/pages", {
                "spaceId": space_id,
                "status": "current",
                "title": title,
                "parentId": parent_id,
                "body": {"representation": "storage", "value": html},
            })
        except Exception as e:
            # v2 실패(500 등) → v1 API로 폴백
            space_key = ConfluenceClient._space_key_cache
            if not space_key:
                # 캐시 없으면 spaceId로 역조회
                space_data = self._get(f"/spaces/{space_id}")
                space_key = space_data.get("key", "")
                ConfluenceClient._space_key_cache = space_key
            print(f"  [create_page] v2 실패 ({e}), v1 API 폴백 (space={space_key})")
            result = self._post_v1("/content", {
                "type": "page",
                "title": title,
                "space": {"key": space_key},
                "ancestors": [{"id": parent_id}],
                "body": {"storage": {"value": html, "representation": "storage"}},
            })
        # 간격 넓게: v1 content property API로 full-width 설정
        page_id = result.get("id", "")
        if page_id:
            for key in ("content-appearance-published", "content-appearance-draft"):
                try:
                    self._post_v1(f"/content/{page_id}/property", {
                        "key": key,
                        "value": "full-width",
                    })
                except Exception as e:
                    print(f"  [spacing] {key} 설정 실패: {e}")
        return result

    def get_child_pages(self, parent_id: str = CONFLUENCE_PARENT_PAGE_ID) -> list[dict]:
        # /pages/{id}/children 은 폴더 ID에서 404 반환 → parentId 쿼리로 폴백
        try:
            data = self._get(f"/pages/{parent_id}/children", params={"limit": 50})
            return data.get("results", [])
        except Exception:
            pass
        data = self._get("/pages", params={"parentId": parent_id, "limit": 50})
        return data.get("results", [])

    def find_page(self, doc_key: str) -> dict:
        """doc_key ('doc1'|'doc2'|'doc21') 에 해당하는 페이지 메타 반환."""
        if doc_key in self._page_cache:
            return self._page_cache[doc_key]
        page_id = DOC_PAGE_IDS[doc_key]
        data = self._get(f"/pages/{page_id}")
        self._page_cache[doc_key] = {"id": page_id, "title": data.get("title", "")}
        return self._page_cache[doc_key]

    def get_page_storage(self, page_id: str) -> tuple[str, int, str]:
        """페이지 Storage Format HTML, 버전 번호, 제목을 반환."""
        data = self._get(f"/pages/{page_id}", params={"body-format": "storage"})
        html = data["body"]["storage"]["value"]
        version = data["version"]["number"]
        title = data["title"]
        return html, version, title

    def update_page(self, page_id: str, title: str, new_html: str, version: int, message: str = "Automated update") -> dict:
        return self._put(f"/pages/{page_id}", {
            "id": page_id,
            "status": "current",
            "title": title,
            "body": {"representation": "storage", "value": new_html},
            "version": {"number": version + 1, "message": message},
        })

    # ──────────────────────────────────────────────
    # Placeholder 기반 구역 교체 (Step 3 핵심 로직)
    # ──────────────────────────────────────────────

    @staticmethod
    def replace_section(html: str, marker: str, new_content: str) -> str:
        """<p>MARKER_START</p> ~ <p>MARKER_END</p> 사이를 new_content로 덮어씁니다."""
        pattern = rf'(<p>{marker}_START</p>).*?(<p>{marker}_END</p>)'
        replacement = rf'\1\n{new_content}\n\2'
        result = re.sub(pattern, replacement, html, flags=re.DOTALL)
        if result == html:
            raise ValueError(
                f"마커 '{marker}_START / {marker}_END'를 페이지에서 찾을 수 없습니다.\n"
                f"Confluence 페이지에 <p>{marker}_START</p> 마커가 있는지 확인하세요."
            )
        return result

    def delete_page(self, page_id: str) -> None:
        """페이지 영구 삭제 (v1 REST API)."""
        base_v1 = f"{CONFLUENCE_BASE_URL}/wiki/rest/api"
        r = requests.delete(f"{base_v1}/content/{page_id}",
                            auth=self.auth, headers={"Accept": "application/json"}, timeout=30)
        if r.status_code == 204:
            print(f"[Confluence] 페이지 삭제 완료 (id={page_id})")
        else:
            print(f"[Confluence] 삭제 실패 (id={page_id}): {r.status_code} {r.text[:200]}")
            r.raise_for_status()

    @staticmethod
    def append_to_section(html: str, marker: str, new_content: str) -> str:

        """<p>MARKER_START</p> ~ <p>MARKER_END</p> 사이 끝에 new_content를 추가합니다 (히스토리 누적용)."""
        pattern = rf'(<p>{marker}_START</p>.*?)(<p>{marker}_END</p>)'
        replacement = rf'\1{new_content}\n\2'
        result = re.sub(pattern, replacement, html, flags=re.DOTALL)
        if result == html:
            raise ValueError(
                f"마커 '{marker}_START / {marker}_END'를 페이지에서 찾을 수 없습니다.\n"
                f"Confluence 페이지에 <p>{marker}_START</p> 마커가 있는지 확인하세요."
            )
        return result


class HmgConfluenceClient:
    """HMG Confluence(hmg.atlassian.net) 읽기 전용 클라이언트.
    Jira와 동일 인스턴스이므로 JIRA_EMAIL + JIRA_API_TOKEN 재사용.
    """

    def __init__(self):
        from config import JIRA_EMAIL, JIRA_API_TOKEN
        self.base = "https://hmg.atlassian.net/wiki/api/v2"
        self.auth = HTTPBasicAuth(JIRA_EMAIL, JIRA_API_TOKEN)
        self.headers = {"Accept": "application/json"}

    def get_page_storage(self, page_id: str) -> tuple[str, int, str]:
        """페이지 Storage Format HTML, 버전 번호, 제목 반환."""
        r = requests.get(
            f"{self.base}/pages/{page_id}",
            auth=self.auth, headers=self.headers,
            params={"body-format": "storage"}, timeout=60,
        )
        r.raise_for_status()
        data = r.json()
        return data["body"]["storage"]["value"], data["version"]["number"], data["title"]

    def get_child_pages(self, folder_id: str) -> list[dict]:
        """폴더 내 자식 페이지 전체 조회 (v1 REST API, 최신 수정순 Python 정렬).
        v2 ?parentId= 필터가 hmg.atlassian.net에서 오작동하므로 v1 API 사용.
        """
        results: list[dict] = []
        base_v1 = "https://hmg.atlassian.net/wiki/rest/api"
        start = 0
        limit = 50
        while True:
            r = requests.get(
                f"{base_v1}/content/{folder_id}/child/page",
                auth=self.auth,
                headers={"Accept": "application/json"},
                params={"limit": limit, "start": start, "expand": "version"},
                timeout=30,
            )
            r.raise_for_status()
            data = r.json()
            page_results = data.get("results", [])
            results.extend(page_results)
            if len(page_results) < limit:
                break
            start += limit
        # version.when 기준 최신순 정렬
        results.sort(key=lambda p: p.get("version", {}).get("when", ""), reverse=True)
        return results
