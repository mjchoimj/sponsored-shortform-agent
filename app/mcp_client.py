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


async def _call(tool_name: str, args: dict) -> dict:
    client = MultiServerMCPClient(SERVERS)
    tools = {t.name: t for t in await client.get_tools()}
    return _parse(await tools[tool_name].ainvoke(args))


def check_forbidden_via_mcp(text: str, category: str) -> dict | None:
    try:
        log.info("MCP 도구 호출: ad_rules.check_forbidden_expressions(category=%s, 글자 수=%d)", category, len(text))
        out = asyncio.run(_call("check_forbidden_expressions", {"text": text, "category": category}))
        log.info("MCP 결과: 금지 표현 %d건", out.get("count", 0))
        return out
    except Exception as e:  # 서버 기동 실패 등 → 코드 판정으로 대체
        log.warning("MCP 검사기 연결 실패, 코드 판정으로 대체: %s", e)
        return None
