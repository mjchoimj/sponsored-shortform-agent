"""LLM 만들기 — Agent 는 생성 모델만 쓴다 (채점 모델은 eval/ 에서만).

모델 목록을 앞에서부터 시도하고, 실패(한도·장애)하면 다음 모델로 넘어간다.
실제로 응답한 모델은 호출 기록(usage log)에 남는다 — 평가에서 케이스별로 어떤 모델을 썼는지 남기기 위해.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, TypeVar

from langchain_aws import ChatBedrockConverse
from pydantic import BaseModel

from app import config

T = TypeVar("T", bound=BaseModel)
log = logging.getLogger(__name__)

# --- 호출 기록 (스레드별) ------------------------------------------------------------
_local = threading.local()


def start_usage_log() -> None:
    _local.calls = []


def get_usage_log() -> list[dict]:
    return list(getattr(_local, "calls", []))


def _record(role: str, model: str, fallback_from: list[str]) -> None:
    if hasattr(_local, "calls"):
        _local.calls.append({"role": role, "model": model, "fallback_from": fallback_from})


# --- 모델 ---------------------------------------------------------------------------
def chat(model: str, temperature: float, max_tokens: int) -> ChatBedrockConverse:
    return ChatBedrockConverse(
        model=model,
        region_name=config.AWS_REGION,
        temperature=temperature,
        max_tokens=max_tokens,
    )


def invoke_with_fallback(models: list[str], build: Callable[[str], Any], prompt: Any, role: str) -> Any:
    """models 를 차례로 시도한다. build(model) 은 invoke 가능한 객체를 돌려준다."""
    failed: list[str] = []
    last_err: Exception | None = None
    for m in models:
        try:
            out = build(m).invoke(prompt)
            if failed:
                log.warning("%s 모델 전환: %s 실패 → %s 사용", role, ", ".join(failed), m)
            _record(role, m, failed)
            return out
        except Exception as e:  # 한도 초과·장애·형식 오류 → 다음 모델
            failed.append(m)
            last_err = e
    raise last_err  # type: ignore[misc]


def gen_models() -> list[str]:
    return [config.GEN_MODEL, *config.GEN_MODEL_FALLBACKS]


class _GenRunner:
    def __init__(self, schema: type[T], temperature: float, max_tokens: int):
        self.schema, self.temperature, self.max_tokens = schema, temperature, max_tokens

    def invoke(self, prompt: Any) -> T:
        return invoke_with_fallback(
            gen_models(),
            lambda m: chat(m, self.temperature, self.max_tokens).with_structured_output(self.schema),
            prompt,
            role="gen",
        )


def gen_structured(schema: type[T], temperature: float = 0.7, max_tokens: int = 4096) -> _GenRunner:
    """생성 모델(+ 예비 모델)로 schema 모양 답을 받는 실행기."""
    config.require_aws_keys()
    return _GenRunner(schema, temperature, max_tokens)
