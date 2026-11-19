"""검증 노드 · 수정 루프 분기 · 최종 승인 HITL ③ (service.md "콘셉트와 계획", "검증").

- 검증 실패 → 원고가 아니라 씬 배분 계획부터 다시 (실패 이유를 check_feedback 으로 넘김)
- 최대 config.MAX_REVISIONS 회. 그래도 실패하면 '미통과' 표시를 단 채 최종 승인으로.
"""

from __future__ import annotations

from langgraph.types import interrupt

from app import config
from app.checks import CheckReport, run_checks
from app.mcp_client import check_rules_via_mcp
from app.state import PlanState


def _apply_mcp(report: CheckReport, state: PlanState) -> CheckReport:
    """C1(광고 표시)·C2(금지 표현)는 MCP 광고 규정 검사기 결과로 판정한다. 연결 실패 시 코드 판정 유지."""
    out = state["output"]
    pkg = out.upload_package
    text = "\n".join(
        [s.dialogue for s in out.storyboard.scenes] + [s.caption for s in out.storyboard.scenes]
        + [pkg.title, pkg.description, " ".join(pkg.hashtags)]
    )
    res = check_rules_via_mcp(text, state["sponsorship"].category, pkg.title, pkg.description)
    if res is None:
        return report
    words = [f["word"] for f in res["forbidden"]["found"]]
    ad = res["ad"]
    for item in report.items:
        if item.code == "C1":
            item.passed = bool(ad["passed"])
            item.detail = f"[MCP 검사기] {ad['reason']}" + (f" → {ad['suggestion']}" if ad["suggestion"] else "")
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


REVISE = {"revise", "2", "수정", "수정 요청"}


def parse_final_answer(answer) -> tuple[str, str]:
    """최종 확인 답 → (action, 수정 요청 내용). action: approve | revise | reject.

    수정 요청은 {"action": "revise", "feedback": "..."} 또는 "수정: ..." 문자열로 받는다.
    """
    if isinstance(answer, dict):
        action = str(answer.get("action", "")).lower()
        fb = str(answer.get("feedback", "")).strip()
        if action in REVISE and fb:
            return "revise", fb
        return ("approve" if action in APPROVE else "reject"), ""
    text = str(answer).strip()
    for prefix in ("수정:", "수정 :", "revise:"):
        if text.lower().startswith(prefix) and text[len(prefix):].strip():
            return "revise", text[len(prefix):].strip()
    return ("approve" if text.lower() in APPROVE else "reject"), ""


def final_hitl_node(state: PlanState) -> dict:
    """HITL ③ — 스토리보드·업로드 패키지와 검증 결과를 보여 주고 사람의 최종 확인을 받는다.

    승인 → 저장 / 수정 요청 → 요청을 반영해 계획부터 다시 (자동 검증 후 다시 확인) / 반려 → 미승인으로 저장.
    """
    report: CheckReport = state["check_report"]
    unresolved = not report.passed
    history = list(state.get("human_feedback", []))
    can_revise = len(history) < config.MAX_HUMAN_REVISIONS
    answer = interrupt(
        {
            "stage": "final",
            "question": "스토리보드와 업로드 패키지를 검토하고 승인해 주세요.",
            "output": state["output"].model_dump(mode="json"),
            "passed": report.passed,
            "unresolved": unresolved,
            "revision": state.get("revision", 0),
            "items": [i.model_dump() for i in report.items],
            "human_feedback": history,
            "can_revise": can_revise,
        }
    )
    action, fb = parse_final_answer(answer)
    if action == "revise" and can_revise:
        # 수정 요청: 자동 수정 횟수를 0으로 되돌리고 계획부터 다시 만든다.
        return {"final_action": "revise", "human_feedback": history + [fb], "revision": 0, "approved": False}
    if action == "revise":  # 수정 요청 한도를 넘음 → 미승인으로 저장
        action = "reject"
    return {"unresolved": unresolved, "approved": action == "approve", "final_action": action}


def route_after_final(state: PlanState) -> str:
    return "plan" if state.get("final_action") == "revise" else "save"


def human_feedback_text(state: PlanState) -> str:
    """plan·generate 프롬프트에 붙일 사람의 수정 요청 (자동 검증 피드백과 함께)."""
    fbs = state.get("human_feedback", [])
    if not fbs:
        return ""
    lines = "\n".join(f"- {f}" for f in fbs)
    return f"[사용자 수정 요청 — 최우선으로 반드시 반영. 단, 광고 규정·채널 금지 표현은 지킨다]\n{lines}"
