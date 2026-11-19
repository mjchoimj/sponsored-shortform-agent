"""실행 진입점.

    python -m app.main examples/normal.json          # 대화형 (질문마다 직접 답하기)
    python -m app.main examples/normal.json --auto   # 자동 (제안 수락, 1안 선택)
"""

from __future__ import annotations

import argparse
import logging
import sys
import uuid

from langgraph.types import Command

from app.graph import build_graph
from app.tracing import trace_config
from app.schemas import PlanOutput, load_channel, load_request

STEP_NAMES = {
    "precheck": "사전 점검",
    "precheck_hitl": "사전 점검 확인",
    "research": "참고 자료 검색(RAG)",
    "concept": "콘셉트 3안",
    "concept_hitl": "콘셉트 선택",
    "plan": "씬 배분 계획",
    "generate": "스토리보드·업로드 패키지 작성",
    "check": "자동 검증",
    "revise": "수정 (계획부터 다시)",
    "final_hitl": "최종 승인",
    "save": "파일 저장",
}

AUTO_ANSWERS = {"precheck": "accept_suggestion", "concept": 1, "final": "approve"}


# --- 질문 화면 -------------------------------------------------------------------
def ask(payload: dict, auto: bool):
    stage = payload["stage"]
    print("\n" + "=" * 60)
    print("🙋 " + payload["question"])
    if stage == "precheck":
        for it in payload["issues"]:
            print(f"  • [{it['type']}] {it['detail']}")
            print(f"    → 제안: {it['suggestion']}")
        prop = payload["proposal"]
        print("  영상에 넣을 포인트:", *[f"\n    - {p}" for p in prop["video_points"]])
        if prop["description_points"]:
            print("  설명란으로 보낼 포인트:", *[f"\n    - {p}" for p in prop["description_points"]])
        print("\n  1) 제안대로   2) 원래 포인트 그대로   3) 중단")
    elif stage == "concept":
        for c in payload["concepts"]:
            print(f"\n  {c['concept_no']}안 · {c['title']}  [{c['hook_type']}]")
            print(f"     첫 대사: {c['hook_line']}")
            print(f"     {c['summary']}")
    elif stage == "final":
        status = "모두 통과" if payload["passed"] else f"미통과 (수정 {payload['revision']}회 후)"
        print(f"  검증 결과: {status}")
        for it in payload["items"]:
            print(f"   {'✅' if it['passed'] else '❌'} {it['code']} {it['name']}: {it['detail']}")
        print("\n  1) 승인   2) 반려")
    if auto:
        a = AUTO_ANSWERS.get(stage, "1")
        print(f"  (자동 답: {a})")
        return a
    return input("\n번호를 입력하세요 > ").strip() or "1"


# --- 결과 화면 -------------------------------------------------------------------
def show(out: PlanOutput) -> None:
    sb, pkg = out.storyboard, out.upload_package
    print("\n" + "=" * 60)
    print(f"✅ 기획 완료 — {out.concept.concept_no}안 · {out.concept.title}")
    print(f"   총 {sb.total_seconds}초 · 씬 {len(sb.scenes)}개")
    for s in sb.scenes:
        mark = "📦" if s.product_visible else "  "
        print(f"\n  #{s.scene_no} ({s.seconds}초) {mark} {s.visual}")
        print(f"     대사: {s.dialogue}")
        print(f"     자막: {s.caption}")
    print("\n[업로드 패키지]")
    print("  제목:", pkg.title)
    print("  설명란:\n    " + pkg.description.replace("\n", "\n    "))
    print("  해시태그:", " ".join(pkg.hashtags))


# --- 실행 ------------------------------------------------------------------------
def run(path: str, auto: bool = False) -> dict:
    req = load_request(path)
    graph = build_graph()
    cfg = {"configurable": {"thread_id": str(uuid.uuid4())}}
    cfg, trace_where = trace_config(cfg, name=req.sponsorship.product_name, tags=[req.channel_id])
    payload = {"channel": load_channel(req.channel_id), "sponsorship": req.sponsorship}

    print(f"📥 입력: {req.sponsorship.product_name} · 채널 {req.channel_id} · {req.sponsorship.length_sec}초")
    while True:
        pending = None
        for chunk in graph.stream(payload, cfg, stream_mode="updates"):
            for node, _ in chunk.items():
                if node == "__interrupt__":
                    pending = chunk[node][0].value
                else:
                    print(f"  ▶ {STEP_NAMES.get(node, node)} 완료")
        if pending is None:
            break
        payload = Command(resume=ask(pending, auto))

    state = graph.get_state(cfg).values
    if state.get("stopped"):
        print("\n⛔ 중단:", state.get("stop_reason", ""))
    elif state.get("output"):
        show(state["output"])
        rep = state.get("check_report")
        if rep is not None:
            mark = "✅ 검증 통과" if rep.passed else "⚠️ 미통과 표시"
            print(f"\n{mark} · 수정 {state.get('revision', 0)}회 · 최종 승인: {'예' if state.get('approved') else '아니오'}")
        if state.get("output_dir"):
            print(f"💾 저장: {state['output_dir']}")
    print(f"🧭 실행 기록(Trace): {trace_where}")
    return state


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    logging.basicConfig(level=logging.WARNING, format="  · %(message)s", stream=sys.stdout)
    logging.getLogger("app").setLevel(logging.INFO)

    p = argparse.ArgumentParser(description="협찬 숏폼 기획 Agent")
    p.add_argument("input", help="입력 파일 (예: examples/normal.json)")
    p.add_argument("--auto", action="store_true", help="질문에 자동으로 답하기 (제안 수락, 1안)")
    args = p.parse_args()
    run(args.input, auto=args.auto)


if __name__ == "__main__":
    main()
