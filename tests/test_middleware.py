"""T18 미들웨어 테스트 — 모델을 부르지 않고 동작만 확인한다.

실행: python -m unittest tests.test_middleware -v
"""

import unittest

from pydantic import BaseModel

from app.middleware import (
    CallLimitExceeded,
    CallLimitMiddleware,
    ForbiddenGuardMiddleware,
    RetryMiddleware,
    is_transient,
    text_of,
)


class Out(BaseModel):
    dialogue: str
    image_prompt: str = ""


class RetryTest(unittest.TestCase):
    def test_transient_retried_then_success(self):
        calls, sleeps = [], []

        def flaky():
            calls.append(1)
            if len(calls) < 3:
                raise RuntimeError("ThrottlingException: Too many requests, please wait")
            return "ok"

        r = RetryMiddleware(max_retries=2, initial_delay=1, sleep=sleeps.append)
        self.assertEqual(r(flaky), "ok")
        self.assertEqual(len(calls), 3)
        self.assertEqual(sleeps, [1, 2])  # 대기 시간이 2배씩

    def test_daily_limit_not_retried(self):
        err = RuntimeError("ThrottlingException: Too many tokens per day")
        self.assertFalse(is_transient(err))
        calls = []

        def daily():
            calls.append(1)
            raise err

        with self.assertRaises(RuntimeError):
            RetryMiddleware(max_retries=2, sleep=lambda s: None)(daily)
        self.assertEqual(len(calls), 1)  # 바로 넘김 → 리전·모델 전환에 맡긴다

    def test_validation_error_not_retried(self):
        self.assertFalse(is_transient(ValueError("schema mismatch")))


class CallLimitTest(unittest.TestCase):
    def test_limit(self):
        lim = CallLimitMiddleware(limit=3)
        lim.reset()
        for _ in range(3):
            lim.check()
        with self.assertRaises(CallLimitExceeded):
            lim.check()
        lim.reset()
        lim.check()  # 새 실행이면 다시 셀 수 있다


class GuardTest(unittest.TestCase):
    def test_regenerates_once_with_feedback(self):
        prompts = []

        def invoke(p):
            prompts.append(p)
            return Out(dialogue="이거 효과 보장돼요" if len(prompts) == 1 else "피부가 촉촉해져요")

        out = ForbiddenGuardMiddleware("화장품")(invoke, "원래 요청")
        self.assertEqual(out.dialogue, "피부가 촉촉해져요")
        self.assertEqual(len(prompts), 2)
        self.assertIn("효과 보장", prompts[1])

    def test_clean_output_single_call(self):
        prompts = []
        ForbiddenGuardMiddleware("화장품")(lambda p: prompts.append(p) or Out(dialogue="촉촉해요"), "요청")
        self.assertEqual(len(prompts), 1)

    def test_image_prompt_ignored(self):
        self.assertNotIn("cure", text_of(Out(dialogue="안녕", image_prompt="cure")))


if __name__ == "__main__":
    unittest.main()
