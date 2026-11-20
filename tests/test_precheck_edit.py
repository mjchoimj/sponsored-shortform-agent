"""사전 점검 '직접 고치기' — 사람이 고친 포인트를 코드가 규칙대로 정리하는지 (AI 호출 없음).

실행: python -m unittest tests.test_precheck_edit -v
"""

import unittest

from app.nodes.precheck import apply_edit


class ApplyEditTest(unittest.TestCase):
    def test_within_cap_kept_as_is(self):
        v, d, notes = apply_edit(["A", "B"], ["C"], 30)
        self.assertEqual((v, d, notes), (["A", "B"], ["C"], []))

    def test_over_cap_moves_tail_to_description(self):
        v, d, notes = apply_edit(["A", "B", "C", "D", "E"], ["F"], 30)  # 30초 상한 3개
        self.assertEqual(v, ["A", "B", "C"])
        self.assertEqual(d, ["D", "E", "F"])
        self.assertEqual(len(notes), 1)

    def test_blank_and_duplicates_removed(self):
        v, d, _ = apply_edit(["  A  ", "", "A", "B"], ["B", "C", "C"], 60)
        self.assertEqual(v, ["A", "B"])
        self.assertEqual(d, ["C"])  # 영상에 있는 B 는 설명란에서 뺀다

    def test_short_video_cap(self):
        v, d, _ = apply_edit(["A", "B", "C"], [], 15)  # 15초 상한 2개
        self.assertEqual((v, d), (["A", "B"], ["C"]))


if __name__ == "__main__":
    unittest.main()
