"""T20 MCP 광고 표시 도구 테스트 — 서버 함수를 직접 부른다 (모델·네트워크 불필요).

실행: python -m unittest tests.test_mcp_server -v
"""

import unittest

from mcp_server.server import check_ad_disclosure


class AdDisclosureTest(unittest.TestCase):
    def test_title_tag_passes(self):
        self.assertTrue(check_ad_disclosure("[광고] 보풀 제거기 리뷰", "요약")["passed"])

    def test_description_first_line_passes(self):
        r = check_ad_disclosure("보풀 제거기 리뷰", "#광고 협찬을 받아 제작했습니다.\n본문")
        self.assertEqual(r["where"], ["설명란 첫 줄"])

    def test_tag_only_in_later_line_fails(self):
        self.assertFalse(check_ad_disclosure("리뷰", "요약\n#광고")["passed"])

    def test_weak_only_fails(self):
        r = check_ad_disclosure("크림 리뷰 #sponsored", "써 봤어요")
        self.assertFalse(r["passed"])
        self.assertIn("#sponsored", r["weak_only"])

    def test_ad_word_boundary(self):
        r = check_ad_disclosure("shadow add 리뷰", "요약")
        self.assertEqual(r["weak_only"], [])


if __name__ == "__main__":
    unittest.main()
