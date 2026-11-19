"""웹 리서치 (T23, P2) — Tavily 검색 + 파일 캐시, 켜고 끄기 가능.

켜고 끄는 순서 (앞이 우선):
  1. 실행 옵션: python -m app.main 입력.json --web   (켜기) / --no-web (끄기)
  2. .env 의 WEB_SEARCH=on | off | auto
  3. 기본값 auto: TAVILY_API_KEY 가 있으면 켜고, 없으면 끈다.
평가(eval/run_eval)는 재현성과 공정한 비교를 위해 항상 끈다.

검색 결과는 knowledge/web_cache/ 에 저장한다. 같은 검색어는 다시 검색하지 않고 캐시를 쓴다.
키가 없어도 캐시에 있는 검색어(데모용)는 결과를 돌려준다.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime

from langchain_core.tools import tool

from app import config

log = logging.getLogger(__name__)

CACHE_DIR = config.ROOT / "knowledge" / "web_cache"
MAX_RESULTS = 3
SNIPPET_CHARS = 500


def web_enabled(override: bool | None = None) -> bool:
    """웹 검색을 쓸지. override(실행 옵션)가 있으면 그 값이 우선."""
    if override is not None:
        return override
    mode = config.WEB_SEARCH
    if mode in ("on", "true", "1", "yes"):
        return True
    if mode in ("off", "false", "0", "no"):
        return False
    return bool(config.TAVILY_API_KEY)  # auto


def _key(query: str) -> str:
    return hashlib.sha1(query.strip().lower().encode("utf-8")).hexdigest()[:16]


def _cache_path(query: str):
    return CACHE_DIR / f"{_key(query)}.json"


def _format(results: list[dict]) -> str:
    parts = []
    for r in results[:MAX_RESULTS]:
        content = (r.get("content") or "").strip().replace("\n", " ")[:SNIPPET_CHARS]
        parts.append(f"[{r.get('title', '')}] ({r.get('url', '')})\n{content}")
    return "\n\n".join(parts) or "(검색 결과 없음)"


def _tavily(query: str) -> list[dict]:
    from langchain_tavily import TavilySearch  # 키가 있을 때만 불러온다

    res = TavilySearch(max_results=MAX_RESULTS, tavily_api_key=config.TAVILY_API_KEY).invoke({"query": query})
    if isinstance(res, str):
        res = json.loads(res)
    return list(res.get("results", []))


def web_search(query: str) -> str:
    """캐시 → (키가 있으면) Tavily 순으로 찾는다."""
    path = _cache_path(query)
    if path.exists():
        log.info("웹 검색(캐시): %r", query)
        return _format(json.loads(path.read_text(encoding="utf-8"))["results"])
    if not config.TAVILY_API_KEY:
        log.info("웹 검색 건너뜀(키 없음, 캐시 없음): %r", query)
        return "(웹 검색 불가: Tavily 키가 없고 캐시도 없음)"
    try:
        results = _tavily(query)
    except Exception as e:  # 네트워크·한도 오류 → 기획은 계속 진행
        log.warning("웹 검색 실패: %s", e)
        return f"(웹 검색 실패: {e})"
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"query": query, "searched_at": datetime.now().isoformat(timespec="seconds"),
                                "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("웹 검색(Tavily): %r → %d건", query, len(results))
    return _format(results)


@tool
def search_web(query: str) -> str:
    """웹에서 협찬 제품의 실제 사양·특징·가격이나 카테고리 트렌드를 찾는다.
    query 는 제품 이름이 들어간 구체적인 한국어 검색어로 쓴다."""
    return web_search(query)
