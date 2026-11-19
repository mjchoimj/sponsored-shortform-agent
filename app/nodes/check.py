"""검증 노드 · 수정 루프 분기 · 최종 승인 HITL ③ (service.md "콘셉트와 계획", "검증").

- 검증 실패 → 원고가 아니라 씬 배분 계획부터 다시 (실패 이유를 check_feedback 으로 넘김)
- 최대 config.MAX_REVISIONS 회. 그래도 실패하면 '미통과' 표시를 단 채 최종 승인으로.
"""

from __future__ import annotations

from langgraph.types import interrupt

from app import config
from app.checks import CheckReport, run_checks
from app.mcp_client import check_forbidden_via_mcp
from app.state import PlanState


def _apply_mcp(report: CheckReport, state: PlanState) -> CheckReport:
    """C2(금지 표현)는 MCP 광고 규정 검사기 결과로 판정한다. 연결 실패 시 코드 판정 유지."""
    out = state["output"]
    pkg = out.upload_package
    text = "\n".join(
        [s.dialogue for s in out.storyboard.scenes] + [s.caption for s in out.storyboard.scenes]
        + [pkg.title, pkg.description, " ".join(pkg.hashtags)]
    )
    res = check_forbidden_via_mcp(text, state["sponsorship"].category)
    if res is None:
        return report
    words = [f["word"] for f in res["found"]]
    for item in report.items:
        if item.code == "C2":
            item.passed = not words
            item.detail = f"[MCP 검사기] 금지 표현 발견: {words}" if words else "[MCP 검사기] 금지 표현 0건"
    return report


def check_node(state: PlanState) -> dict:
    sp = state["sponsorship"]
    report = run_checks(
        state["channel"], sp, state["output"],
        state.get("video_points", sp.promo_points),
        state.get("description_points", []),
    )
    report = _apply_mcp(report, state)
    history = list(state.get("check_history", [])) + [report]
    return {"check_report": report, "check_history": history, "check_feedback": report.feedback()}


def route_after_check(state: PlanState) -> str:
    """'final' 또는 'revise'."""
    report: CheckReport = state["check_report"]
    if report.passed or state.get("revision", 0) >= config.MAX_REVISIONS:
        return "final"
    return "revise"


def revise_node(state: PlanState) -> dict:
    """수정 횟수를 올리고 계획 노드로 돌아간다 (check_feedback 은 이미 상태에 있음)."""
    return {"revision": state.get("revision", 0) + 1}


APPROVE = {"approve", "1", "y", "yes", "네", "예", "승인", "ㅇㅇ"}


def final_hitl_node(state: PlanState) -> dict:
    """HITL ③ — 검증 결과를 보여 주고 최종 승인을 받는다."""
    report: CheckReport = state["check_report"]
    unresolved = not report.passed
    answer = interrupt(
        {
            "stage": "final",
            "question": "검증 결과를 확인하고 최종 승인해 주세요.",
            "passed": report.passed,
            "unresolved": unresolved,
            "revision": state.get("revision", 0),
            "items": [i.model_dump() for i in report.items],
        }
    )
    approved = str(answer).strip().lower() in APPROVE
    return {"unresolved": unresolved, "approved": approved}
