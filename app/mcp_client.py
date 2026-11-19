"""MCP 광고 규정 검사기 연결 (langchain-mcp-adapters, stdio).

Agent 가 이 함수를 부르면 mcp_server 를 하위 프로세스로 자동 기동해 도구를 호출한다.
서버 연결이 실패하면 경고를 남기고 None 을 돌려준다 (호출한 쪽이 코드 판정으로 대신한다).
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys

from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools

from app import config

log = logging.getLogger(__name__)

SERVERS = {
    "ad_rules": {
        "command": sys.executable,
        "args": ["-m", "mcp_server.server"],
        "cwd": str(config.ROOT),
        "transport": "stdio",
    }
}


def _parse(result) -> dict:
    """도구 결과(문자열 · 콘텐츠 블록 목록 · dict)를 dict 로."""
    if isinstance(result, dict):
        return result
    if isinstance(result, list):
        texts = [b.get("text", "") if isinstance(b, dict) else getattr(b, "text", str(b)) for b in result]
        result = "".join(texts)
    return json.loads(result)


async def _call_many(calls: list[tuple[str, dict]]) -> list[dict]:
    """서버를 한 번 띄워 도구 여러 개를 차례로 부른다."""
    client = MultiServerMCPClient(SERVERS)
    async with client.session("ad_rules") as session:
        tools = {t.name: t for t in await load_mcp_tools(session)}
        return [_parse(await tools[name].ainvoke(args)) for name, args in calls]


def check_rules_via_mcp(text: str, category: str, title: str, description: str) -> dict | None:
    """금지 표현(C2) + 광고 표시(C1)를 MCP 검사기로 한 번에 검사한다. 실패하면 None."""
    try:
        log.info("MCP 도구 호출: check_forbidden_expressions(category=%s, 글자 수=%d), check_ad_disclosure", category, len(text))
        forbidden, ad = asyncio.run(_call_many([
            ("check_forbidden_expressions", {"text": text, "category": category}),
            ("check_ad_disclosure", {"title": title, "description": description}),
        ]))
        log.info("MCP 결과: 금지 표현 %d건, 광고 표시 %s", forbidden.get("count", 0), "통과" if ad.get("passed") else "실패")
        return {"forbidden": forbidden, "ad": ad}
    except Exception as e:  # 서버 기동 실패 등 → 코드 판정으로 대체
        log.warning("MCP 검사기 연결 실패, 코드 판정으로 대체: %s", e)
        return None
