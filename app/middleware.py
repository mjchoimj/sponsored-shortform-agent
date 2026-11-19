"""미들웨어 3종 (T18) — 모든 생성 모델 호출을 감싸는 공통 안전장치.

1. 재시도(RetryMiddleware): 일시적 오류(속도 제한·일시 장애·시간 초과)면 같은 모델·리전으로 잠시 쉬었다 다시 부른다.
   '하루 한도 초과'처럼 기다려도 안 풀리는 오류는 바로 넘긴다 → llm.invoke_with_fallback 이 다른 리전·모델로 전환.
2. 호출 횟수 상한(CallLimitMiddleware): 실행 1회(입력 1건)당 생성 모델 호출 수를 제한한다.
   수정 루프·재시도가 꼬여도 비용이 끝없이 늘지 않게 한다. 넘으면 CallLimitExceeded.
3. 금지 표현 가드(ForbiddenGuardMiddleware): 생성 결과에 광고 규정 금지 표현(rules.json)이 있으면
   그 표현을 짚어서 한 번 다시 생성시킨다. 판정은 코드(find_forbidden)로 한다.

에이전트형 노드(research)는 LangChain 내장 미들웨어(ModelRetryMiddleware·ModelCallLimitMiddleware·
ToolCallLimitMiddleware)를 create_agent 에 붙여 쓴다 — research.py 참고.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

from app import config
from app.rules import find_forbidden

log = logging.getLogger(__name__)


# --- 1. 재시도 -----------------------------------------------------------------------
TRANSIENT = ("throttl", "too many requests", "rate exceeded", "serviceunavailable",
             "service unavailable", "timed out", "timeout", "internalserver", "modelnotready")
PERMANENT = ("per day", "daily")  # 하루 한도 — 기다려도 안 풀림


def is_transient(err: Exception) -> bool:
    msg = f"{type(err).__name__} {err}".lower()
    return any(k in msg for k in TRANSIENT) and not any(k in msg for k in PERMANENT)


class RetryMiddleware:
    def __init__(self, max_retries: int = config.RETRY_MAX, initial_delay: float = config.RETRY_DELAY,
                 sleep: Callable[[float], None] = time.sleep):
        self.max_retries, self.initial_delay, self.sleep = max_retries, initial_delay, sleep

    def __call__(self, call: Callable[[], Any], label: str = "") -> Any:
        delay = self.initial_delay
        for attempt in range(self.max_retries + 1):
            try:
                return call()
            except Exception as e:
                if attempt >= self.max_retries or not is_transient(e):
                    raise
                log.warning("재시도 %d/%d (%s): %s — %.1f초 후", attempt + 1, self.max_retries, label, e, delay)
                self.sleep(delay)
                delay *= 2


# --- 2. 호출 횟수 상한 ---------------------------------------------------------------
class CallLimitExceeded(RuntimeError):
    pass


_budget = threading.local()


class CallLimitMiddleware:
    """실행 1회당 생성 모델 호출 수 상한. reset() 으로 새 실행을 시작한다 (precheck 노드에서 호출)."""

    def __init__(self, limit: int = config.MAX_LLM_CALLS):
        self.limit = limit

    def reset(self) -> None:
        _budget.used = 0

    @property
    def used(self) -> int:
        return getattr(_budget, "used", 0)

    def check(self, label: str = "") -> None:
        if self.used >= self.limit:
            raise CallLimitExceeded(f"생성 모델 호출 상한 {self.limit}회를 넘었습니다 ({label}). 실행을 멈춥니다.")
        _budget.used = self.used + 1


# --- 3. 금지 표현 가드 ---------------------------------------------------------------
def text_of(obj: Any) -> str:
    """Pydantic 결과에서 사람이 읽는 한국어 문자열만 모은다 (영문 image_prompt·style_sheet 제외)."""
    data = obj.model_dump() if hasattr(obj, "model_dump") else obj
    out: list[str] = []

    def walk(x: Any, key: str = "") -> None:
        if key in ("image_prompt", "style_sheet"):
            return
        if isinstance(x, str):
            out.append(x)
        elif isinstance(x, dict):
            for k, v in x.items():
                walk(v, k)
        elif isinstance(x, list):
            for v in x:
                walk(v, key)

    walk(data)
    return "\n".join(out)


class ForbiddenGuardMiddleware:
    def __init__(self, category: str, max_retries: int = 1):
        self.category, self.max_retries = category, max_retries

    def __call__(self, invoke: Callable[[Any], Any], prompt: Any) -> Any:
        result = invoke(prompt)
        for _ in range(self.max_retries):
            hits = find_forbidden(text_of(result), self.category)
            if not hits:
                return result
            words = ", ".join(f'"{h["word"]}"' for h in hits)
            log.warning("금지 표현 가드: %s 발견 → 다시 생성", words)
            prompt = f"{prompt}\n\n[금지 표현 가드] 이전 답에 광고 규정 금지 표현 {words} 이(가) 있었다. 이 표현과 비슷한 단정·과장 표현 없이 다시 써라."
            result = invoke(prompt)
        hits = find_forbidden(text_of(result), self.category)
        if hits:
            log.warning("금지 표현 가드: 재생성 후에도 %s 남음 — 검증 단계(C2)에서 다시 잡습니다.", [h["word"] for h in hits])
        return result


# 공용 인스턴스
retry = RetryMiddleware()
call_limit = CallLimitMiddleware()
