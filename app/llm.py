"""LLM 만들기 — Agent 는 생성 모델만 쓴다 (채점 모델은 eval/ 에서만).

생성 모델이 실패(한도·장애)하면 config.GEN_MODEL_FALLBACKS 순서로 자동 전환한다.
"""

from __future__ import annotations

from typing import TypeVar

from langchain_aws import ChatBedrockConverse
from pydantic import BaseModel

from app import config

T = TypeVar("T", bound=BaseModel)


def _chat(model: str, temperature: float, max_tokens: int) -> ChatBedrockConverse:
    return ChatBedrockConverse(
        model=model,
        region_name=config.AWS_REGION,
        temperature=temperature,
        max_tokens=max_tokens,
    )


def gen_structured(schema: type[T], temperature: float = 0.7, max_tokens: int = 4096):
    """생성 모델 + 예비 모델을 묶어, schema 모양으로 답하는 실행기를 돌려준다."""
    config.require_aws_keys()
    models = [config.GEN_MODEL, *config.GEN_MODEL_FALLBACKS]
    runners = [_chat(m, temperature, max_tokens).with_structured_output(schema) for m in models]
    return runners[0].with_fallbacks(runners[1:]) if len(runners) > 1 else runners[0]
