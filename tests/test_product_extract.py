"""붙여넣기 정리(product_extract) 코드 확인 테스트 — AI 호출 없음.

실행: python -m unittest tests.test_product_extract -v
"""

import unittest

from app.product_extract import ExtractedPoint, ProductDraft, quote_in_source, verify

SOURCE = """포근 보풀 제거기 PG-100
USB-C 충전 방식으로 1회 충전 시 약 60분 사용 가능합니다.
날 높이를 3단계로 조절할 수 있어 니트, 코트 등 다양한 소재에 사용하세요.
보풀 통은 분리형으로 간편하게 비울 수 있습니다.
무게 180g / 정가 15,900원
※ 교환·반품은 수령 후 7일 이내 가능합니다."""


def draft(points, category="생활용품"):
    return ProductDraft(product_name=" 포근  보풀 제거기 ", category=category,
                        product_desc="충전식 보풀 제거기. 무게 180g, 정가 15,900원.",
                        points=[ExtractedPoint(point=p, quote=q) for p, q in points])


class QuoteTest(unittest.TestCase):
    def test_exact_and_spacing(self):
        self.assertTrue(quote_in_source("USB-C 충전 방식으로 1회 충전 시 약 60분 사용 가능합니다.", SOURCE))
        self.assertTrue(quote_in_source("USB-C충전방식으로  1회 충전 시 약 60분", SOURCE))

    def test_made_up_quote(self):
        self.assertFalse(quote_in_source("방수 기능으로 물세척 가능", SOURCE))

    def test_too_short(self):
        self.assertFalse(quote_in_source("무게", SOURCE))


class VerifyTest(unittest.TestCase):
    def test_keeps_grounded_drops_made_up(self):
        r = verify(draft([
            ("USB-C 충전, 1회 60분 사용", "USB-C 충전 방식으로 1회 충전 시 약 60분 사용 가능합니다."),
            ("물세척 가능한 방수 설계", "방수 기능으로 물세척 가능"),
            ("3단 높이 조절로 니트도 안전", "날 높이를 3단계로 조절할 수 있어"),
        ]), SOURCE)
        self.assertEqual(r.points, ["USB-C 충전, 1회 60분 사용", "3단 높이 조절로 니트도 안전"])
        self.assertEqual(r.dropped, ["물세척 가능한 방수 설계"])
        self.assertEqual(r.product_name, "포근 보풀 제거기")
        self.assertTrue(any("근거를 찾지 못한" in n for n in r.notes))

    def test_unknown_category_left_blank(self):
        r = verify(draft([("3단 높이 조절", "날 높이를 3단계로 조절할 수 있어")], category="주방가전"), SOURCE)
        self.assertEqual(r.category, "")

    def test_duplicates_removed_and_capped(self):
        q = "날 높이를 3단계로 조절할 수 있어"
        pts = [("3단 높이 조절", q), ("3단 높이 조절", q)] + [(f"특징 {i}번", q) for i in range(6)]
        r = verify(draft(pts), SOURCE)
        self.assertEqual(len(r.points), 5)
        self.assertEqual(r.points.count("3단 높이 조절"), 1)

    def test_forbidden_word_flagged(self):
        r = verify(draft([("업계 1위 보풀 제거기", "포근 보풀 제거기 PG-100")]), SOURCE)
        self.assertTrue(any("금지 표현" in n for n in r.notes))


if __name__ == "__main__":
    unittest.main()
