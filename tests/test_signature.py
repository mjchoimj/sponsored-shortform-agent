"""시그니처 멘트 보정 테스트 — 모델이 바꿔 쓰거나 빠뜨린 오프닝·엔딩을 코드가 원문으로 넣는지.

실행: python -m unittest tests.test_signature -v
"""

import unittest

from app.checks import run_checks
from app.nodes.generate import _put_signature, ensure_signatures
from app.schemas import ScenePlan, ScenePlanItem, load_channel
from tests.test_checks import CH, SP, good_output

OPEN3 = load_channel("CH3").signature_opening


class SignatureTest(unittest.TestCase):
    def test_reworded_opening_replaced(self):
        reworded = OPEN3.replace("살림", "청소까지")
        self.assertEqual(_put_signature(reworded, OPEN3, at_end=False), OPEN3)

    def test_missing_opening_prepended(self):
        out = _put_signature("저녁 청소가 밀렸어요.", OPEN3, at_end=False)
        self.assertTrue(out.startswith(OPEN3))
        self.assertTrue(out.endswith("저녁 청소가 밀렸어요."))

    def test_missing_ending_appended(self):
        self.assertEqual(_put_signature("오늘도 고생했어.", "다음 꿀팁에서 보자", at_end=True),
                         "오늘도 고생했어. 다음 꿀팁에서 보자")

    def test_ensure_fixes_a2(self):
        out = good_output()
        scenes = out.storyboard.scenes
        scenes[0].dialogue = "빨래 냄새 진짜 싫다."
        scenes[-1].dialogue = "끝."
        plan = ScenePlan(scenes=[ScenePlanItem(scene_no=s.scene_no, seconds=s.seconds, purpose="t") for s in scenes])
        out.storyboard.scenes = ensure_signatures(scenes, plan, CH)
        a2 = next(i for i in run_checks(CH, SP, out).items if i.code == "A2")
        self.assertTrue(a2.passed, a2.detail)

    def test_untouched_when_present(self):
        out = good_output()
        before = [s.dialogue for s in out.storyboard.scenes]
        plan = ScenePlan(scenes=[ScenePlanItem(scene_no=s.scene_no, seconds=s.seconds, purpose="t") for s in out.storyboard.scenes])
        after = [s.dialogue for s in ensure_signatures(out.storyboard.scenes, plan, CH)]
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
