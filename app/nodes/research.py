"""RAG 노드 — 생성 모델이 search_knowledge 도구를 직접 골라 호출한다 (Tool Calling).

모델이 검색어를 정하고, 도구 호출 결과를 모아 state["knowledge"] 에 넣는다.
모델이 도구를 하나도 부르지 않으면 기본 검색어로 코드가 직접 찾는다.
"""

from __future__ import annotations

import logging

from langchain_aws import ChatBedrockConverse

from app import config
from app.rag import search_knowledge
from app.state import PlanState

log = logging.getLogger(__name__)

PROMPT = """협찬 숏폼 기획에 참고할 자료를 찾는다. search_knowledge 도구를 2~3번 불러라.
찾을 것: (1) 이 제품 카테고리의 금지·주의 표현, (2) 이 영상 길이와 콘셉트에 맞는 훅·구성 노하우,
(3) 광고주 요구 조율이나 채널 톤 유지 방법 중 이번 건에 필요한 것.

채널: {channel_name} — {concept} (말투: {speech})
제품: {product_name} ({category}), {length_sec}초
영상 포인트: {video_points}
"""

DEFAULT_QUERIES = ["{category} 금지 표현", "첫 3초 훅 유형", "광고 표시 위치"]


def research_node(state: PlanState) -> dict:
    ch, sp = state["channel"], state["sponsorship"]
    llm = ChatBedrockConverse(
        model=config.GEN_MODEL, region_name=config.AWS_REGION, temperature=0, max_tokens=500
    ).bind_tools([search_knowledge])
    msg = llm.invoke(
        PROMPT.format(
            channel_name=ch.channel_name,
            concept=ch.concept,
            speech=ch.speech_style,
            product_name=sp.product_name,
            category=sp.category,
            length_sec=sp.length_sec,
            video_points=state.get("video_points", sp.promo_points),
        )
    )
    queries = [c["args"].get("query", "") for c in msg.tool_calls if c["name"] == "search_knowledge"]
    queries = [q for q in queries if q] or [q.format(category=sp.category) for q in DEFAULT_QUERIES]

    chunks, seen = [], set()
    for q in queries[:4]:
        log.info("RAG 도구 호출: search_knowledge(%r)", q)
        for part in search_knowledge.invoke({"query": q}).split("\n\n---\n\n"):
            if part not in seen:
                seen.add(part)
                chunks.append(part)
    return {"knowledge": "\n\n---\n\n".join(chunks), "rag_queries": queries[:4]}
