"""T11 코드 검증 테스트 — 정상 스토리보드는 모두 통과, 일부러 틀린 것은 해당 항목만 실패.

실행: python -m unittest tests.test_checks -v
"""

import unittest

from app.checks import run_checks
from app.checks.items import speech_of
from app.schemas import (
    Concept,
    PlanOutput,
    Scene,
    StyleSheet,
    Storyboard,
    UploadPackage,
    load_channel,
    load_request,
)

CH = load_channel("CH1")  # 자취 살림, 반말
SP = load_request("examples/normal.json").sponsorship  # 보풀 제거기 30초, 포인트 3개


def scene(no, sec, dialogue, caption, product=False):
    return Scene(
        scene_no=no, seconds=sec, visual="자취방 장면", dialogue=dialogue, caption=caption,
        product_visible=product, image_prompt="vertical 9:16 cozy studio apartment",
    )


def good_output() -> PlanOutput:
    scenes = [
        scene(1, 3, "니트 보풀 때문에 또 버릴 뻔했지? 자취 5년 차 꿀팁 들어간다.", "니트 보풀 지옥"),
        scene(2, 6, "손으로 뜯으면 구멍 나. 나도 그러다 두 벌 날렸어.", "손으로 뜯지 마"),
        scene(3, 5, "USB-C 충전식이라 건전지 필요 없어. 3단 높이 조절로 니트도 안전하게 밀 수 있어.",
              "충전식 · 3단 높이 조절", product=True),
        scene(4, 6, "다 밀고 나면 새 옷 같아. 니트 한 벌 값이면 이걸로 겨울 내내 버티지.", "비용 비교 끝"),
        scene(5, 4, "보풀 통이 커서 비우기 편함. 한 번에 꽤 모여.", "보풀 통 큼", product=True),
        scene(6, 6, "이 정도면 자취생 기준 할 만해. 다음 꿀팁에서 보자.", "다음 꿀팁에서 보자"),
    ]
    return PlanOutput(
        concept=Concept(concept_no=1, title="니트 보풀 해결", hook_type="문제 제기",
                        hook_line="니트 보풀 때문에 또 버릴 뻔했지?", summary="문제 → 꿀팁 → 비용 비교"),
        storyboard=Storyboard(
            style_sheet=StyleSheet(visual_style="casual vlog", color_palette="warm", lighting="natural"),
            scenes=scenes,
        ),
        upload_package=UploadPackage(
            title="[광고] 니트 보풀, 자취생은 이렇게 해결해",
            description="#광고 포근 보풀 제거기 협찬을 받아 제작했어.\n니트 보풀 해결 꿀팁.",
            hashtags=["#광고", "#자취꿀팁"],
            ad_disclosure="[광고]",
        ),
    )


def failed_codes(out, **kw):
    return {i.code for i in run_checks(CH, SP, out, **kw).failed}


class TestChecks(unittest.TestCase):
    def test_good_passes_all(self):
        report = run_checks(CH, SP, good_output())
        self.assertTrue(report.passed, report.feedback())

    def test_a1_wrong_speech(self):
        out = good_output()
        for s in out.storyboard.scenes[1:5]:
            s.dialogue = "이 제품 정말 좋아요. 꼭 써 보세요."
        self.assertIn("A1", failed_codes(out))

    def test_a2_missing_signature(self):
        out = good_output()
        out.storyboard.scenes[-1].dialogue = "그럼 안녕."
        out.storyboard.scenes[-1].caption = "끝"
        self.assertEqual({"A2"}, failed_codes(out))

    def test_a3_avoid(self):
        out = good_output()
        out.storyboard.scenes[3].dialogue = "이거 없으면 못 살아. 다들 사."
        self.assertIn("A3", failed_codes(out))

    def test_b1_missing_point(self):
        out = good_output()
        out.storyboard.scenes[4].dialogue = "그리고 색깔도 예뻐."
        out.storyboard.scenes[4].caption = "색깔 예쁨"
        self.assertEqual({"B1"}, failed_codes(out))

    def test_b1_description_point(self):
        out = good_output()
        kw = {"video_points": SP.promo_points, "description_points": ["무게 180g으로 가벼움"]}
        self.assertIn("B1", failed_codes(out, **kw))
        out.upload_package.description += "\n- 무게 180g으로 가벼움"
        self.assertNotIn("B1", failed_codes(out, **kw))

    def test_c1_no_disclosure(self):
        out = good_output()
        out.upload_package.title = "니트 보풀 해결 꿀팁"
        out.upload_package.description = "보풀 제거기 써 봤어.\n#광고"  # 첫 줄이 아니면 실패
        self.assertEqual({"C1"}, failed_codes(out))

    def test_c1_weak_disclosure_only(self):
        out = good_output()
        out.upload_package.title = "니트 보풀 해결 (sponsored)"
        out.upload_package.description = "#ad 포근 보풀 제거기"
        self.assertEqual({"C1"}, failed_codes(out))

    def test_c2_forbidden(self):
        out = good_output()
        out.storyboard.scenes[3].caption = "업계 1위 보풀 제거기"
        self.assertEqual({"C2"}, failed_codes(out))

    def test_c3_exposure(self):
        out = good_output()
        out.storyboard.scenes[3].product_visible = True  # 5+4+6 = 15초 = 50%
        self.assertEqual({"C3"}, failed_codes(out))

    def test_c4_first_scene_product(self):
        out = good_output()
        out.storyboard.scenes[0].product_visible = True
        self.assertIn("C4", failed_codes(out))

    def test_c4_hook_too_long(self):
        out = good_output()
        out.storyboard.scenes[0].seconds = 5
        out.storyboard.scenes[1].seconds = 4
        self.assertEqual({"C4"}, failed_codes(out))

    def test_c5_length(self):
        out = good_output()
        out.storyboard.scenes[-1].seconds = 9
        self.assertEqual({"C5"}, failed_codes(out))

    def test_speech_classifier(self):
        self.assertEqual(speech_of("다음 꿀팁에서 보자."), "반말")
        self.assertEqual(speech_of("오늘도 고생 많으셨어요"), "존댓말")
        self.assertEqual(speech_of("감사합니다!"), "존댓말")
        self.assertEqual(speech_of("꿀팁 대방출"), "중립")
        self.assertEqual(speech_of("보풀 통 큼"), "중립")


if __name__ == "__main__":
    unittest.main()
