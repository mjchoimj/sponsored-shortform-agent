"""상태 그래프 — 사전 점검 → RAG → 콘셉트 → 계획 → 생성 → 검증 ⇄ (수정 루프) → 최종 승인 → 저장."""

from __future__ import annotations

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph

from app import schemas
from app.nodes.check import check_node, final_hitl_node, revise_node, route_after_check
from app.nodes.concept import concept_hitl_node, concept_node
from app.nodes.generate import generate_node
from app.nodes.plan import plan_node
from app.nodes.precheck import precheck_hitl_node, precheck_node
from app.nodes.research import research_node
from app.nodes.save import save_node
from app.state import PlanState

# 체크포인트에 저장해도 되는 우리 데이터 모델 (LangGraph 경고 방지)
_ALLOWED = [
    ("app.schemas", name)
    for name, obj in vars(schemas).items()
    if isinstance(obj, type) and issubclass(obj, schemas.BaseModel) and obj.__module__ == "app.schemas"
] + [("app.checks", "CheckReport"), ("app.checks", "CheckItem")]


def _after_precheck(state: PlanState) -> str:
    return END if state.get("stopped") else "research"


def build_graph(checkpointer=None):
    g = StateGraph(PlanState)
    g.add_node("precheck", precheck_node)
    g.add_node("precheck_hitl", precheck_hitl_node)  # HITL ①
    g.add_node("research", research_node)  # RAG (Tool Calling)
    g.add_node("concept", concept_node)
    g.add_node("concept_hitl", concept_hitl_node)  # HITL ②
    g.add_node("plan", plan_node)
    g.add_node("generate", generate_node)
    g.add_node("check", check_node)
    g.add_node("revise", revise_node)  # 수정 루프: 계획부터 다시
    g.add_node("final_hitl", final_hitl_node)  # HITL ③
    g.add_node("save", save_node)

    g.add_edge(START, "precheck")
    g.add_edge("precheck", "precheck_hitl")
    g.add_conditional_edges("precheck_hitl", _after_precheck, ["research", END])
    g.add_edge("research", "concept")
    g.add_edge("concept", "concept_hitl")
    g.add_edge("concept_hitl", "plan")
    g.add_edge("plan", "generate")
    g.add_edge("generate", "check")
    g.add_conditional_edges("check", route_after_check, {"revise": "revise", "final": "final_hitl"})
    g.add_edge("revise", "plan")
    g.add_edge("final_hitl", "save")
    g.add_edge("save", END)

    if checkpointer is None:
        checkpointer = InMemorySaver(serde=JsonPlusSerializer(allowed_msgpack_modules=_ALLOWED))
    return g.compile(checkpointer=checkpointer)
