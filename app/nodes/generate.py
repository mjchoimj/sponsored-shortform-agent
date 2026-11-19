"""스토리보드 + 업로드 패키지 생성 노드.

씬 수·초·제품 노출 여부는 계획(plan)이 기준이다. LLM 결과를 계획에 맞춰 코드가 덮어쓴다.
광고 표시가 제목·설명란 첫 줄에 없으면 코드가 설명란 첫 줄에 붙인다.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.llm import gen_structured
from app.rules import forbidden_words, load_rules
from app.schemas import (
    ChannelProfile,
    Concept,
    PlanOutput,
    Scene,
    ScenePlan,
    Sponsorship,
    StyleSheet,
    Storyboard,
    UploadPackage,
)
from app.state import PlanState


class GenOutput(BaseModel):
    style_sheet: StyleSheet
    scenes: list[Scene] = Field(min_length=1)
    upload_package: UploadPackage


PROMPT = """너는 인플루언서 채널의 협찬 숏폼 작가다. 아래 씬 배분 계획을 그대로 따라 스토리보드와 업로드 패키지를 쓴다.

[반드시 지킬 것]
- 씬 수·순서·seconds·product_visible 은 계획과 똑같이.
- dialogue(대사)와 caption(자막)은 한국어, 채널 말투 "{speech}"로. 모든 문장을 {speech} 어미로 끝낸다.
- signature 가 "opening" 인 씬 대사에 "{opening}" 를 그대로, "ending" 인 씬 대사에 "{ending}" 를 그대로 넣는다.
- 계획의 point_indices 에 해당하는 영상 포인트를 그 씬 대사나 자막에서 다룬다.
- 대사 길이는 씬 seconds 에 맞게: 1초에 한글 약 7글자 이내 (예: 3초 씬은 20자 안팎).
  다 못 한 말은 자막이나 설명란으로 넘긴다.
- 1번 씬(훅)은 콘셉트의 첫 대사로 시작하고 제품을 보여 주지 않는다.
- visual 은 화면 설명(한국어). product_visible=false 인 씬의 visual·image_prompt 에는 제품이 나오지 않게.
- image_prompt 와 style_sheet 는 영어. image_prompt 는 스타일 시트와 어울리게, 9:16 세로 구도, 씬마다 한 문단.
- 쓰지 말 표현(채널 avoid): {avoid}
- 쓰지 말 표현(광고 규정): {forbidden}
- 협찬인데 직접 구매한 것처럼 말하지 않는다("내돈내산" 등).

[업로드 패키지]
- title: 한국어, 맨 앞에 "[광고]".
- description: 첫 줄은 "#광고 {product_name} 협찬을 받아 제작했습니다." 처럼 광고 표시로 시작.
  그 아래 영상 요약 한두 줄, 그리고 '설명란 포인트'를 하나도 빠짐없이 목록으로 적는다.
- hashtags: 5~8개, "#" 로 시작, 첫 번째는 "#광고".
- ad_disclosure: 사용한 광고 표시 문구.

[채널] {channel_name} — {concept_text}, 톤: {tone}
[콘셉트] {title} (훅: {hook_type}) — 첫 대사: {hook_line}
[제품] {product_name} ({category}) — {product_desc}
[영상 포인트]
{video_points}
[설명란 포인트]
{description_points}
[씬 배분 계획]
{plan}
{feedback}"""


def _ensure_ad_disclosure(pkg: UploadPackage) -> UploadPackage:
    allowed = load_rules()["ad_disclosure"]["allowed"]
    first_line = pkg.description.splitlines()[0] if pkg.description else ""
    if not any(a in pkg.title or a in first_line for a in allowed):
        pkg.description = f"#광고 협찬을 받아 제작했습니다.\n{pkg.description}"
        pkg.ad_disclosure = "#광고"
    return pkg


def _apply_plan(out: GenOutput, plan: ScenePlan) -> list[Scene] | None:
    if len(out.scenes) != len(plan.scenes):
        return None
    scenes = []
    for p, s in zip(plan.scenes, out.scenes):
        s.scene_no, s.seconds, s.product_visible = p.scene_no, p.seconds, p.product_visible
        scenes.append(s)
    return scenes


def generate(ch: ChannelProfile, sp: Sponsorship, concept: Concept, plan: ScenePlan,
             video_points: list[str], feedback: str = "") -> PlanOutput:
    runner = gen_structured(GenOutput, temperature=0.7, max_tokens=8000)
    note = f"\n[이전 검증에서 실패한 점 — 반드시 고칠 것]\n{feedback}" if feedback else ""
    for _ in range(2):
        prompt = PROMPT.format(
            speech=ch.speech_style,
            opening=ch.signature_opening,
            ending=ch.signature_ending,
            avoid=", ".join(ch.avoid) or "(없음)",
            forbidden=", ".join(w["word"] for w in forbidden_words(sp.category)),
            product_name=sp.product_name,
            channel_name=ch.channel_name,
            concept_text=ch.concept,
            tone=", ".join(ch.tone_keywords),
            title=concept.title,
            hook_type=concept.hook_type,
            hook_line=concept.hook_line,
            category=sp.category,
            product_desc=sp.product_desc,
            video_points="\n".join(f"{i}. {p}" for i, p in enumerate(video_points)),
            description_points="\n".join(f"- {p}" for p in plan.description_points) or "(없음)",
            plan=plan.model_dump_json(indent=1, exclude={"description_points"}),
            feedback=note,
        )
        out: GenOutput = runner.invoke(prompt)
        scenes = _apply_plan(out, plan)
        if scenes is not None:
            break
        note += f"\n[이전 답의 문제] 씬 수가 {len(out.scenes)}개였다. 계획대로 {len(plan.scenes)}개로."
    else:
        raise RuntimeError("스토리보드 씬 수가 계획과 맞지 않습니다.")

    return PlanOutput(
        concept=concept,
        storyboard=Storyboard(style_sheet=out.style_sheet, scenes=scenes),
        upload_package=_ensure_ad_disclosure(out.upload_package),
    )


def generate_node(state: PlanState) -> dict:
    sp = state["sponsorship"]
    out = generate(
        state["channel"], sp, state["concept"], state["plan"],
        state.get("video_points", sp.promo_points),
        state.get("check_feedback", ""),
    )
    return {"output": out}
