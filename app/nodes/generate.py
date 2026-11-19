"""스토리보드 + 업로드 패키지 생성 노드.

씬 수·초·제품 노출 여부는 계획(plan)이 기준이다. LLM 결과를 계획에 맞춰 코드가 덮어쓴다.
광고 표시가 제목·설명란 첫 줄에 없으면 코드가 설명란 첫 줄에 붙인다.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from app.llm import gen_structured
from app.checks.items import product_terms
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
  제품 이름({product_terms})을 쓰지 말고, 제품을 손에 들기·착용하기·옆에 켜 두기 같은 장면도 안 된다. 사람·상황·결과만 보여 준다.
- 채널 평소 영상처럼 만든다 (제품 소개 영상이 아니다):
  · 채널 대표 포맷 "{format}" 의 단계가 하나도 빠짐없이 순서대로 씬에 드러나게.
  · 톤 키워드 {tone} 가 각각 대사에 최소 한 번씩 분명히 드러나게.
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


def _squash(text: str) -> str:
    return re.sub(r"[^0-9a-zA-Z가-힣]", "", text)


def _bigrams(text: str) -> set[str]:
    t = _squash(text)
    return {t[i:i + 2] for i in range(len(t) - 1)}


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?~])\s+", text.strip()) if s.strip()]


def _put_signature(dialogue: str, sig: str, at_end: bool) -> str:
    """대사에 시그니처 멘트를 원문 그대로 넣는다.

    모델이 비슷하게 바꿔 쓴 문장(두 글자 단위 겹침 50% 이상)이 있으면 그 문장을 원문으로 바꾸고,
    없으면 맨 앞(오프닝) 또는 맨 끝(엔딩)에 붙인다.
    """
    sig_parts = _sentences(sig) or [sig]
    target = _bigrams(sig)
    kept, replaced = [], False
    for s in _sentences(dialogue):
        b = _bigrams(s)
        if target and b and len(b & target) / len(b) >= 0.5:
            if not replaced:
                kept.extend(sig_parts)
                replaced = True
            continue  # 바꿔 쓴 시그니처 문장은 원문으로 대체
        kept.append(s)
    if not replaced:
        kept = kept + sig_parts if at_end else sig_parts + kept
    return " ".join(kept)


def ensure_signatures(scenes: list[Scene], plan: ScenePlan, ch: ChannelProfile) -> list[Scene]:
    """오프닝·엔딩 멘트가 대사·자막에 원문 그대로 없으면 코드가 넣는다 (A2 보정, 광고 표시 보정과 같은 방식).

    넣는 곳: 계획에서 signature 로 정한 씬. 없으면 오프닝은 1번 씬, 엔딩은 마지막 씬.
    """
    script = _squash(" ".join(s.dialogue + " " + s.caption for s in scenes))
    marks = {p.scene_no: p.signature for p in plan.scenes}
    for kind, sig, at_end in (("opening", ch.signature_opening, False), ("ending", ch.signature_ending, True)):
        if not sig or _squash(sig) in script:
            continue
        idx = next((i for i, s in enumerate(scenes) if marks.get(s.scene_no) == kind), 0 if not at_end else len(scenes) - 1)
        scenes[idx] = scenes[idx].model_copy(update={"dialogue": _put_signature(scenes[idx].dialogue, sig, at_end)})
    return scenes


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
    runner = gen_structured(GenOutput, temperature=0.7, max_tokens=8000, guard_category=sp.category)
    note = f"\n[이전 검증에서 실패한 점 — 반드시 고칠 것]\n{feedback}" if feedback else ""
    scenes = None
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
            format=ch.representative_format,
            product_terms=", ".join(product_terms(sp)),
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
        new = _apply_plan(out, plan)
        if new is None:
            note += f"\n[이전 답의 문제] 씬 수가 {len(out.scenes)}개였다. 계획대로 {len(plan.scenes)}개로."
            continue
        scenes = new
        terms = product_terms(sp)
        hidden = [sc.scene_no for sc in scenes if not sc.product_visible and any(t in sc.visual for t in terms)]
        if not hidden:
            break
        note += (f"\n[이전 답의 문제] 씬 {hidden}은 product_visible=false 인데 화면 설명에 제품이 나왔다. "
                 "그 씬은 제품 없이 사람·상황·결과만 보이게.")
    if scenes is None:
        raise RuntimeError("스토리보드 씬 수가 계획과 맞지 않습니다.")

    return PlanOutput(
        concept=concept,
        storyboard=Storyboard(style_sheet=out.style_sheet, scenes=ensure_signatures(scenes, plan, ch)),
        upload_package=_ensure_ad_disclosure(out.upload_package),
    )


def generate_node(state: PlanState) -> dict:
    sp = state["sponsorship"]
    out = generate(
        state["channel"], sp, state["concept"], state["plan"],
        state.get("video_points", sp.promo_points),
        _feedback(state),
    )
    return {"output": out}


def _feedback(state: PlanState) -> str:
    """자동 검증 실패 이유 + 사람의 수정 요청."""
    from app.nodes.check import human_feedback_text
    return "\n".join(x for x in (state.get("check_feedback", ""), human_feedback_text(state)) if x)
