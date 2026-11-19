"""RAG 노드 — 생성 모델이 검색 도구를 직접 골라 호출한다 (Tool Calling).

LangChain create_agent 로 작은 검색 에이전트를 만들고, 내장 미들웨어를 붙인다 (T18):
  ModelRetryMiddleware(일시 오류 재시도) · ModelCallLimitMiddleware(모델 호출 상한) ·
  ToolCallLimitMiddleware(검색 도구별 호출 상한).
도구:
  - search_knowledge: 로컬 노하우 문서(RAG). 항상 쓴다.
  - search_web: Tavily 웹 검색 (T23). 웹 검색이 켜져 있을 때만 준다 (app/web.py 의 켜고 끄기 참고).
도구 결과를 모아 state["knowledge"] 에 넣는다. 노하우 문서를 하나도 안 찾았으면 기본 검색어로 코드가 직접 찾는다.
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
from app.web import search_web, web_enabled

log = logging.getLogger(__name__)

PROMPT = """협찬 숏폼 기획에 참고할 자료를 찾는다. search_knowledge 도구를 2~3번 불러라.
찾을 것: (1) 이 제품 카테고리의 금지·주의 표현, (2) 이 영상 길이와 콘셉트에 맞는 훅·구성 노하우,
(3) 광고주 요구 조율이나 채널 톤 유지 방법 중 이번 건에 필요한 것.
{web_part}
채널: {channel_name} — {concept} (말투: {speech})
제품: {product_name} ({category}), {length_sec}초
제품 설명: {product_desc}
영상 포인트: {video_points}
"""

WEB_PART = """(4) search_web 도구도 1~2번 불러 이 제품의 실제 사양·특징·가격을 찾아라. 검색어에 제품 이름 "{product_name}" 을 넣는다.
"""

SEP = "\n\n---\n\n"  # 검색 결과 조각 구분자
DEFAULT_QUERIES = ["{category} 금지 표현", "첫 3초 훅 유형", "광고 표시 위치"]
WEB_HEADER = ("[웹 검색 결과 — 제품 사실 확인용 참고. 광고주 포인트·제품 설명과 다르면 광고주 쪽을 따른다. "
              "과장·단정 표현은 옮기지 않는다]")


def _tool_results(msgs, name: str) -> list[str]:
    return [m.content for m in msgs if isinstance(m, ToolMessage) and m.name == name
            and isinstance(m.content, str) and not m.content.startswith("Tool call limit")]


def _queries(msgs, name: str) -> list[str]:
    qs = [c["args"].get("query", "") for m in msgs if isinstance(m, AIMessage)
          for c in m.tool_calls if c["name"] == name]
    return [q for q in qs if q]


def research_node(state: PlanState) -> dict:
    ch, sp = state["channel"], state["sponsorship"]
    use_web = web_enabled(state.get("web_search"))
    prompt = PROMPT.format(
        web_part=WEB_PART.format(product_name=sp.product_name) if use_web else "",
        channel_name=ch.channel_name,
        concept=ch.concept,
        speech=ch.speech_style,
        product_name=sp.product_name,
        category=sp.category,
        length_sec=sp.length_sec,
        product_desc=sp.product_desc or "(없음)",
        video_points=state.get("video_points", sp.promo_points),
    )
    result = invoke_with_fallback(
        gen_models(), lambda m, r: _build_agent(m, r, use_web), {"messages": [("user", prompt)]}, role="gen"
    )
    msgs = result["messages"]

    queries = _queries(msgs, "search_knowledge")
    results = _tool_results(msgs, "search_knowledge")
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

    web_queries: list[str] = []
    web_facts = ""
    if use_web:
        web_queries = _queries(msgs, "search_web")
        web = [w for w in _tool_results(msgs, "search_web") if not w.startswith("(웹 검색")]
        for q in web_queries:
            log.info("웹 검색 도구 호출: search_web(%r)", q)
        if web:
            web_facts = "\n\n".join(web)
            chunks.append(WEB_HEADER + "\n" + web_facts)

    return {
        "knowledge": SEP.join(chunks),
        "rag_queries": queries[: config.RESEARCH_MAX_TOOL_CALLS],
        "web_queries": web_queries,
        "web_facts": web_facts,
        "web_search": use_web,
    }


def _build_agent(model: str, region: str, use_web: bool = False):
    tools = [search_knowledge, search_web] if use_web else [search_knowledge]
    limits = [ToolCallLimitMiddleware(tool_name="search_knowledge", run_limit=config.RESEARCH_MAX_TOOL_CALLS,
                                      exit_behavior="continue")]
    if use_web:
        limits.append(ToolCallLimitMiddleware(tool_name="search_web", run_limit=config.RESEARCH_MAX_WEB_CALLS,
                                              exit_behavior="continue"))
    return create_agent(
        chat(model, 0, 500, region),
        tools=tools,
        system_prompt="필요한 자료를 도구로 찾은 뒤, 다 찾았으면 '완료'라고만 답한다.",
        middleware=[
            ModelRetryMiddleware(max_retries=config.RETRY_MAX, initial_delay=config.RETRY_DELAY, on_failure="error"),
            ModelCallLimitMiddleware(run_limit=config.RESEARCH_MAX_MODEL_CALLS, exit_behavior="end"),
            *limits,
        ],
    )
