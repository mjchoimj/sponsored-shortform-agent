"""그래프 상태 — 노드끼리 주고받는 값."""

from __future__ import annotations

from typing import TypedDict

from app.checks import CheckReport
from app.schemas import (
    ChannelProfile,
    Concept,
    ConceptOptions,
    PlanOutput,
    PrecheckResult,
    ScenePlan,
    Sponsorship,
)


class PlanState(TypedDict, total=False):
    channel: ChannelProfile
    sponsorship: Sponsorship
    # 사전 점검
    precheck: PrecheckResult
    precheck_decision: str  # accept_suggestion | proceed | cancel | edit
    confirm_points: bool  # 참이면 문제가 없어도 포인트 구분을 사람에게 확인받는다 (웹 화면)
    edit_notes: list[str]  # 사람이 고친 포인트를 코드가 정리하며 남긴 안내
    video_points: list[str]
    description_points: list[str]
    stopped: bool  # 거절·취소로 멈췄는지
    stop_reason: str
    # RAG + 콘셉트
    knowledge: str  # 검색해 온 참고 문단
    rag_queries: list[str]  # 모델이 도구로 검색한 질의
    concepts: ConceptOptions
    concept: Concept  # 사용자가 고른 안
    # 계획 · 생성
    plan: ScenePlan
    output: PlanOutput
    check_feedback: str  # 수정 루프에서 검증 실패 이유 (T12)
    # 검증 · 수정 루프 · 최종 승인
    check_report: CheckReport
    check_history: list[CheckReport]  # 회차별 검증 결과
    revision: int  # 수정 횟수 (0 = 첫 생성)
    unresolved: bool  # 최대 수정 후에도 미통과
    approved: bool  # 최종 승인 여부
    final_action: str  # 최종 확인 답: approve | revise | reject
    human_feedback: list[str]  # 사람이 최종 확인에서 남긴 수정 요청 (누적)
    output_dir: str  # 저장 폴더
