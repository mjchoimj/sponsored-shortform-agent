"""RAG 노드 — 생성 모델이 search_knowledge 도구를 직접 골라 호출한다 (Tool Calling).

LangChain create_agent 로 작은 검색 에이전트를 만들고, 내장 미들웨어 3개를 붙인다 (T18):
  ModelRetryMiddleware(일시 오류 재시도) · ModelCallLimitMiddleware(모델 호출 상한) ·
  ToolCallLimitMiddleware(검색 도구 호출 상한).
도구 결과를 모아 state["knowledge"] 에 넣는다. 도구를 하나도 부르지 않으면 기본 검색어로 코드가 직접 찾는다.
"""

from __future__ import annotations

import logging

from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware, ModelRetryMiddleware, ToolCallLimitMiddleware
from langchain_core.messages import AIMessage, ToolMessage

from app import config
from app.llm import chat, gen_models, invoke_with_fallback
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

SEP = "\n\n---\n\n"  # search_knowledge 결과 조각 구분자
DEFAULT_QUERIES = ["{category} 금지 표현", "첫 3초 훅 유형", "광고 표시 위치"]


def research_node(state: PlanState) -> dict:
    ch, sp = state["channel"], state["sponsorship"]
    prompt = PROMPT.format(
            channel_name=ch.channel_name,
            concept=ch.concept,
            speech=ch.speech_style,
            product_name=sp.product_name,
            category=sp.category,
            length_sec=sp.length_sec,
            video_points=state.get("video_points", sp.promo_points),
        )
    result = invoke_with_fallback(
        gen_models(), _build_agent, {"messages": [("user", prompt)]}, role="gen"
    )
    msgs = result["messages"]
    queries = [c["args"].get("query", "") for m in msgs if isinstance(m, AIMessage)
               for c in m.tool_calls if c["name"] == "search_knowledge"]
    queries = [q for q in queries if q]
    results = [m.content for m in msgs if isinstance(m, ToolMessage) and m.name == "search_knowledge"
               and isinstance(m.content, str) and not m.content.startswith("Tool call limit")]
    if not results:  # 도구를 안 불렀으면 기본 검색어로 코드가 직접 찾는다
        queries = [q.format(category=sp.category) for q in DEFAULT_QUERIES]
        for q in queries:
            log.info("RAG 기본 검색: search_knowledge(%r)", q)
        results = [search_knowledge.invoke({"query": q}) for q in queries]
    else:
        for q in queries:
            log.info("RAG 도구 호출: search_knowledge(%r)", q)

    chunks, seen = [], set()
    for res in results:
        for part in res.split(SEP):
            if part not in seen:
                seen.add(part)
                chunks.append(part)
    return {"knowledge": SEP.join(chunks), "rag_queries": queries[: config.RESEARCH_MAX_TOOL_CALLS]}


def _build_agent(model: str, region: str):
    return create_agent(
        chat(model, 0, 500, region),
        tools=[search_knowledge],
        system_prompt="필요한 자료를 search_knowledge 로 찾은 뒤, 다 찾았으면 '완료'라고만 답한다.",
        middleware=[
            ModelRetryMiddleware(max_retries=config.RETRY_MAX, initial_delay=config.RETRY_DELAY, on_failure="error"),
            ModelCallLimitMiddleware(run_limit=config.RESEARCH_MAX_MODEL_CALLS, exit_behavior="end"),
            ToolCallLimitMiddleware(tool_name="search_knowledge", run_limit=config.RESEARCH_MAX_TOOL_CALLS,
                                    exit_behavior="continue"),
        ],
    )
