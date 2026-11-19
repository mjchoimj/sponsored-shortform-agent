"""데이터 모델 — Agent 가 주고받는 모든 데이터의 모양을 Pydantic 으로 정한다.

여기서는 '모양'(필드·타입)만 확인한다. 길이 합·노출 비율 같은 규칙 판정은
app/checks/ 의 코드가 knowledge/rules.json 을 보고 한다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from app import config

LengthSec = Literal[15, 30, 45, 60]
TrapType = Literal[
    "overflow_count",  # 분량 초과 · 개수
    "overflow_length",  # 분량 초과 · 길이
    "overflow_ratio",  # 분량 초과 · 비율
    "contradiction",  # 모순
    "concept_conflict",  # 채널 콘셉트 충돌
    "exaggeration",  # 과장 표현
]


# --- 입력 --------------------------------------------------------------------
class ChannelProfile(BaseModel):
    """채널 프로필 (eval/channels/CH*.json)."""

    channel_id: str
    channel_name: str
    category_focus: str = ""
    concept: str
    speech_style: Literal["반말", "존댓말"]
    tone_keywords: list[str]
    signature_opening: str
    signature_ending: str
    representative_format: str
    avoid: list[str] = Field(default_factory=list)
    avoid_notes: str = ""


class Sponsorship(BaseModel):
    """협찬 정보. category 는 거절 카테고리도 받아야 하므로 자유 문자열이다."""

    product_name: str
    category: str
    promo_points: list[str] = Field(min_length=1)
    length_sec: LengthSec
    product_desc: str


class PlanRequest(BaseModel):
    """실행 입력 한 건 (examples/*.json). 채널은 channel_id 로 가리킨다."""

    channel_id: str
    sponsorship: Sponsorship
    demo: str = ""


# --- 평가셋 ------------------------------------------------------------------
class HitlResponse(BaseModel):
    stage: Literal["precheck", "concept", "final"]
    answer: str | int


class ExpectedTrap(BaseModel):
    type: TrapType
    trap_detail: str
    trap_points: list[int] = Field(default_factory=list)
    expected_handling: str


class EvalCase(BaseModel):
    """평가 케이스 한 건 (eval/cases/*.json)."""

    case_id: str
    case_type: Literal["normal"] | TrapType
    channel_id: str
    pair_group: str | None = None
    sponsorship: Sponsorship
    hitl_responses: list[HitlResponse] = Field(min_length=3, max_length=3)
    expected_trap: ExpectedTrap | None = None
    memo: str = ""


# --- 사전 점검 ----------------------------------------------------------------
class PrecheckIssue(BaseModel):
    type: TrapType
    detail: str = Field(description="무엇이 문제인지 한 문장")
    point_indices: list[int] = Field(default_factory=list, description="문제 포인트 위치(0부터)")
    suggestion: str = Field(description="사용자에게 제안할 처리 방법")
    source: Literal["code", "llm"] = "llm"


class PrecheckResult(BaseModel):
    rejected: bool = False
    reject_reason: str = ""
    issues: list[PrecheckIssue] = Field(default_factory=list)
    video_points: list[str] = Field(default_factory=list, description="영상에 넣을 포인트")
    description_points: list[str] = Field(default_factory=list, description="설명란으로 보낼 포인트")


# --- 콘셉트 -------------------------------------------------------------------
class Concept(BaseModel):
    concept_no: int = Field(ge=1, le=3)
    title: str
    hook_type: str = Field(description="훅 유형 (문제 제기, 질문형, 비포·애프터 등)")
    hook_line: str = Field(description="첫 대사, 채널 말투")
    summary: str


class ConceptOptions(BaseModel):
    concepts: list[Concept] = Field(min_length=3, max_length=3)


# --- 씬 배분 계획 --------------------------------------------------------------
class ScenePlanItem(BaseModel):
    scene_no: int = Field(ge=1)
    seconds: int = Field(ge=1)
    purpose: str = Field(description="이 씬의 역할 (훅, 문제, 포인트 소개, 마무리 등)")
    point_indices: list[int] = Field(default_factory=list, description="다룰 video_points 위치")
    signature: Literal["opening", "ending", "none"] = "none"
    product_visible: bool = False


class ScenePlan(BaseModel):
    scenes: list[ScenePlanItem] = Field(min_length=1)
    description_points: list[str] = Field(default_factory=list)
    notes: str = ""


# --- 스토리보드 · 업로드 패키지 -------------------------------------------------
class StyleSheet(BaseModel):
    """이미지 생성 AI 용 공통 스타일. 영어."""

    visual_style: str
    color_palette: str
    lighting: str
    aspect_ratio: Literal["9:16"] = "9:16"
    character: str = ""


class Scene(BaseModel):
    scene_no: int = Field(ge=1)
    seconds: int = Field(ge=1, description="정수 초")
    visual: str = Field(description="화면 설명, 한국어")
    dialogue: str = Field(description="대사, 한국어 채널 말투")
    caption: str = Field(description="자막, 한국어")
    product_visible: bool
    image_prompt: str = Field(description="이미지 생성 프롬프트, 영어")


class Storyboard(BaseModel):
    style_sheet: StyleSheet
    scenes: list[Scene] = Field(min_length=1)

    @property
    def total_seconds(self) -> int:
        return sum(s.seconds for s in self.scenes)


class UploadPackage(BaseModel):
    title: str
    description: str = Field(description="설명란 전체. 첫 줄에 광고 표시")
    hashtags: list[str] = Field(default_factory=list)
    ad_disclosure: str = Field(description="사용한 광고 표시 문구, 예: [광고]")


class PlanOutput(BaseModel):
    """최종 산출물 묶음 (storyboard.json 의 바탕)."""

    concept: Concept
    storyboard: Storyboard
    upload_package: UploadPackage


# --- 읽기 도우미 ---------------------------------------------------------------
def _read_json(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_channel(channel_id: str) -> ChannelProfile:
    return ChannelProfile.model_validate(
        _read_json(config.EVAL_DIR / "channels" / f"{channel_id}.json")
    )


def load_request(path: str | Path) -> PlanRequest:
    return PlanRequest.model_validate(_read_json(Path(path)))


def load_case(path: str | Path) -> EvalCase:
    return EvalCase.model_validate(_read_json(Path(path)))
