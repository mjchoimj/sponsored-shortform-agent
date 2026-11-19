"""T12 수정 루프 테스트 — LLM 노드를 가짜로 바꿔 끼워 비용 없이 그래프 흐름만 확인한다.

실행: python -m unittest tests.test_loop -v
"""

import unittest
from unittest.mock import patch

from langgraph.types import Command

from app import config
from app.checks import CheckItem, CheckReport
from app.schemas import ScenePlan, ScenePlanItem, load_channel, load_request
from tests.test_checks import good_output

CH = load_channel("CH1")
SP = load_request("examples/normal.json").sponsorship
CALLS = {"plan": 0, "generate": 0, "feedback": []}


def fake_precheck(state):
    from app.schemas import PrecheckResult
    return {"precheck": PrecheckResult(video_points=list(SP.promo_points))}


def fake_research(state):
    return {"knowledge": "(테스트)"}


def fake_concept(state):
    from app.schemas import ConceptOptions
    return {"concepts": ConceptOptions(concepts=[good_output().concept.model_copy(update={"concept_no": n}) for n in (1, 2, 3)])}


def fake_plan(state):
    CALLS["plan"] += 1
    CALLS["feedback"].append(state.get("check_feedback", ""))
    return {"plan": ScenePlan(scenes=[ScenePlanItem(scene_no=1, seconds=30, purpose="테스트")])}


def fake_generate(state):
    CALLS["generate"] += 1
    return {"output": good_output()}


def always_fail(*args, **kwargs):
    # C2 는 MCP 검사기 결과로 덮어쓰이므로, 강제 실패는 MCP 와 무관한 항목에 둔다.
    return CheckReport(items=[CheckItem(code="A1", name="말투 일치", passed=False, detail="강제 실패")])


def run_graph(answers):
    from app.graph import build_graph
    g = build_graph()
    cfg = {"configurable": {"thread_id": "t"}}
    out = g.invoke({"channel": CH, "sponsorship": SP}, cfg)
    stages = []
    while "__interrupt__" in out:
        payload = out["__interrupt__"][0].value
        stages.append(payload)
        out = g.invoke(Command(resume=answers[payload["stage"]]), cfg)
    return out, stages


PATCHES = {
    "app.graph.precheck_node": fake_precheck,
    "app.graph.research_node": fake_research,
    "app.graph.concept_node": fake_concept,
    "app.graph.plan_node": fake_plan,
    "app.graph.generate_node": fake_generate,
}


class TestLoop(unittest.TestCase):
    def setUp(self):
        CALLS.update(plan=0, generate=0, feedback=[])
        self.patchers = [patch(k, v) for k, v in PATCHES.items()]
        for p in self.patchers:
            p.start()

    def tearDown(self):
        for p in self.patchers:
            p.stop()

    def test_forced_failure_hits_max_then_final(self):
        with patch("app.nodes.check.run_checks", always_fail):
            out, stages = run_graph({"concept": 1, "final": "approve"})
        n = config.MAX_REVISIONS
        self.assertEqual(out["revision"], n)
        self.assertEqual(CALLS["plan"], n + 1)  # 첫 생성 + 수정 n회, 매번 계획부터
        self.assertEqual(CALLS["generate"], n + 1)
        self.assertEqual(len(out["check_history"]), n + 1)
        self.assertTrue(out["unresolved"])  # 미통과 표시
        self.assertTrue(out["approved"])
        self.assertEqual(stages[-1]["stage"], "final")  # 최종 승인 단계 도달
        self.assertFalse(stages[-1]["passed"])
        self.assertEqual(CALLS["feedback"][0], "")  # 첫 계획엔 피드백 없음
        self.assertIn("강제 실패", CALLS["feedback"][1])  # 수정 때는 실패 이유가 계획으로 감

    def test_pass_goes_straight_to_final(self):
        out, stages = run_graph({"concept": 1, "final": "approve"})  # 진짜 코드 검증, good_output 은 통과
        self.assertEqual(out.get("revision", 0), 0)
        self.assertEqual(CALLS["plan"], 1)
        self.assertFalse(out["unresolved"])
        self.assertTrue(stages[-1]["passed"])

    def test_reject_at_final(self):
        out, _ = run_graph({"concept": 1, "final": "2"})
        self.assertFalse(out["approved"])


if __name__ == "__main__":
    unittest.main()
