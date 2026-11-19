"""광고 규정 검사기 — MCP 서버 (FastMCP, stdio).

knowledge/rules.json 만 읽는 독립 서버다. Agent 가 실행될 때 stdio 로 자동으로 띄운다.
단독 실행:
    python -m mcp_server.server            # 서버 대기 (MCP 클라이언트가 연결)
    python -m mcp_server.server --selftest # 도구를 직접 한 번 불러 결과 출력
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

RULES_PATH = Path(__file__).resolve().parent.parent / "knowledge" / "rules.json"

mcp = FastMCP("ad-rule-checker", log_level="WARNING")


def _rules() -> dict:
    return json.loads(RULES_PATH.read_text(encoding="utf-8"))


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text)


@mcp.tool()
def check_forbidden_expressions(text: str, category: str) -> dict:
    """협찬 광고 원고(text)에서 금지 표현을 찾는다.

    category: 생활용품 · 전자·액세서리 · 일반식품 · 화장품.
    공통 금지 표현 + 해당 카테고리 금지 표현을 공백 무시 부분 일치로 찾고,
    찾은 표현마다 이유와 바꿔 쓸 표현을 돌려준다.
    """
    fe = _rules()["forbidden_expressions"]
    words = fe["common"] + fe["by_category"].get(category, [])
    squashed = _squash(text)
    found = [
        {"word": w["word"], "reason": w["reason"], "suggestion": w["suggestion"]}
        for w in words
        if _squash(w["word"]) in squashed
    ]
    return {"category": category, "checked_words": len(words), "count": len(found), "found": found}


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sample = "업계 1위 크림! 피부가 새로 태어나요. 촉촉함은 그대로."
        print(json.dumps(check_forbidden_expressions(sample, "화장품"), ensure_ascii=False, indent=2))
    else:
        mcp.run(transport="stdio")
