"""knowledge/rules.json 읽기 + 금지 표현 찾기 (코드 판정)."""

from __future__ import annotations

import json
from functools import lru_cache

from app import config


@lru_cache(maxsize=1)
def load_rules() -> dict:
    return json.loads(config.RULES_PATH.read_text(encoding="utf-8"))


def max_points(length_sec: int) -> int:
    return load_rules()["length"]["max_points_in_video"][str(length_sec)]


def forbidden_words(category: str) -> list[dict]:
    fe = load_rules()["forbidden_expressions"]
    return fe["common"] + fe["by_category"].get(category, [])


def find_forbidden(text: str, category: str) -> list[dict]:
    """text 에 들어 있는 금지 표현 목록. 공백은 무시하고 부분 일치로 찾는다."""
    squashed = text.replace(" ", "")
    return [w for w in forbidden_words(category) if w["word"].replace(" ", "") in squashed]
