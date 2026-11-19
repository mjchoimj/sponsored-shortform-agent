"""그래프 상태 — 노드끼리 주고받는 값."""

from __future__ import annotations

from typing import TypedDict

from app.schemas import ChannelProfile, Concept, ConceptOptions, PrecheckResult, Sponsorship


class PlanState(TypedDict, total=False):
    channel: ChannelProfile
    sponsorship: Sponsorship
    # 사전 점검
    precheck: PrecheckResult
    precheck_decision: str  # accept_suggestion | proceed | cancel
    video_points: list[str]
    description_points: list[str]
    stopped: bool  # 거절·취소로 멈췄는지
    stop_reason: str
    # RAG + 콘셉트
    knowledge: str  # 검색해 온 참고 문단
    concepts: ConceptOptions
    concept: Concept  # 사용자가 고른 안
