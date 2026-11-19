"""광고 규정 검사기 — MCP 서버 (FastMCP, stdio).

knowledge/rules.json 만 읽는 독립 서버다. Agent 가 실행될 때 stdio 로 자동으로 띄운다.
단독 실행:
    python -m mcp_server.server            # 서버 대기 (MCP 클라이언트가 연결)
    python -m mcp_server.server --selftest # 도구를 직접 한 번 불러 결과 출력

도구: check_forbidden_expressions(금지 표현, C2) · check_ad_disclosure(광고 표시, C1)
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


@mcp.tool()
def check_ad_disclosure(title: str, description: str) -> dict:
    """업로드 패키지의 광고 표시를 검사한다.

    규정: 제목 또는 설명란 첫 줄에 인정 표시([광고]·#광고)가 있어야 한다.
    'sponsored'·'#ad'·'#내돈내산' 같은 표시만 있으면 실패다 (영문은 단어 단위·대소문자 무시).
    결과: passed, where(표시가 있는 곳), weak_only(인정 안 되는 표시), reason, suggestion.
    """
    ad = _rules()["ad_disclosure"]
    first = description.strip().splitlines()[0] if description.strip() else ""
    where = [name for name, t in (("제목", title), ("설명란 첫 줄", first)) if any(a in t for a in ad["allowed"])]
    weak = [
        w for w in ad["fail_if_alone"]
        if re.search(rf"(?<![0-9a-zA-Z가-힣]){re.escape(w)}(?![0-9a-zA-Z가-힣])", f"{title}\n{first}", re.I)
    ]
    if where:
        reason = f"{', '.join(where)}에 광고 표시 있음"
    elif weak:
        reason = f"인정되지 않는 표시만 있음: {weak}"
    else:
        reason = "제목·설명란 첫 줄에 광고 표시 없음"
    return {
        "passed": bool(where),
        "where": where,
        "weak_only": [] if where else weak,
        "reason": reason,
        "suggestion": "" if where else "제목 맨 앞에 [광고], 설명란 첫 줄에 #광고 를 넣으세요.",
        "note": ad.get("recommend_in_video", ""),
    }


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sample = "업계 1위 크림! 피부가 새로 태어나요. 촉촉함은 그대로."
        print(json.dumps(check_forbidden_expressions(sample, "화장품"), ensure_ascii=False, indent=2))
        print(json.dumps(check_ad_disclosure("촉촉 크림 리뷰 #ad", "써 봤어요\n#광고"), ensure_ascii=False, indent=2))
    else:
        mcp.run(transport="stdio")
