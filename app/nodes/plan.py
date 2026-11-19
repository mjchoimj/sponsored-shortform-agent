"""씬 배분 계획 노드 (service.md "콘셉트와 계획").

LLM 이 초안을 짜고, 셀 수 있는 규칙은 코드가 계산해 바로잡거나 이유를 알려 주고 다시 시킨다.
- 코드가 직접 고침: 씬 초 합 = 목표 길이, 첫 씬 ≤ 3초·제품 없음, 씬 번호
- 다시 시킴: 제품 노출 > 30%, 영상 포인트 누락, 시그니처 위치
수정 루프(T12)에서 돌아오면 state["check_feedback"] 을 프롬프트에 넣는다.
"""

from __future__ import annotations

from app.llm import gen_structured
from app.rules import load_rules
from app.schemas import ChannelProfile, Concept, ScenePlan, Sponsorship
from app.state import PlanState

PROMPT = """너는 협찬 숏폼(9:16, {length_sec}초) 기획자다. 고른 콘셉트로 '씬 배분 계획'을 세운다. 아직 대사는 쓰지 않는다.

[지켜야 할 숫자]
- 씬 seconds 는 정수, 모든 씬 합이 정확히 {length_sec}초.
- 1번 씬은 훅: {hook_max}초 이하, product_visible=false.
- product_visible=true 인 씬의 seconds 합 ≤ {max_product_sec}초 (전체의 30%).
- 씬 수는 {scene_hint}개 정도.

[내용 규칙]
- 영상 포인트(아래 번호) 하나하나가 어떤 씬의 point_indices 에 반드시 들어가야 한다.
- signature: 오프닝 멘트("{opening}")는 1번 또는 2번 씬에 "opening", 엔딩 멘트("{ending}")는 마지막 씬에 "ending". 나머지 "none".
- purpose 는 씬 역할(훅, 문제 상황, 포인트 소개, 사용 장면, 비교·정리, 마무리 등) 한국어로.
- 제품 장면보다 '제품 덕에 달라진 결과·상황'을 많이 보여 준다.
- notes 에 계획 의도를 한두 문장(한국어)으로.
- description_points 는 비워 둔다 (코드가 채운다).

[채널] {channel_name} — {concept_text} / 대표 포맷: {format}
[콘셉트] {concept_no}안 {title} (훅 유형: {hook_type})
  첫 대사: {hook_line}
  흐름: {summary}
[제품] {product_name} — {product_desc}
[영상 포인트]
{video_points}
[설명란으로 갈 포인트] {description_points}

[참고 자료]
{knowledge}
{feedback}"""

SCENE_HINT = {15: "3~4", 30: "5~6", 45: "6~8", 60: "8~10"}


def _max_product_sec(length: int) -> int:
    return int(length * load_rules()["product_exposure"]["max_ratio"])


def normalize(plan: ScenePlan, length: int) -> ScenePlan:
    """코드로 고칠 수 있는 것은 고친다: 번호, 첫 씬, 초 합."""
    hook_max = load_rules()["hook"]["max_sec"]
    scenes = plan.scenes
    for i, s in enumerate(scenes, start=1):
        s.scene_no = i
        s.seconds = max(1, int(s.seconds))
    first = scenes[0]
    first.product_visible = False
    first.seconds = min(first.seconds, hook_max)

    diff = length - sum(s.seconds for s in scenes)
    # 차이는 훅이 아닌 씬 중 제품이 안 나오는 가장 긴 씬부터 흡수 (노출 비율을 건드리지 않게).
    others = sorted(scenes[1:], key=lambda s: (s.product_visible, -s.seconds)) or [first]
    j = 0
    while diff != 0 and j < 1000:
        s = others[j % len(others)]
        step = 1 if diff > 0 else -1
        if s.seconds + step >= 1:
            s.seconds += step
            diff -= step
        j += 1

    # 제품 노출 > 30% 이면 제품 씬 초를 1초씩 줄여 제품 없는 씬(훅 제외)으로 옮긴다. 합은 그대로.
    cap = _max_product_sec(length)
    prod = [s for s in scenes if s.product_visible]
    free = [s for s in scenes[1:] if not s.product_visible]
    while free and sum(s.seconds for s in prod) > cap:
        donor = max(prod, key=lambda s: s.seconds)
        if donor.seconds <= 1:
            break
        donor.seconds -= 1
        min(free, key=lambda s: s.seconds).seconds += 1
    return plan


def problems(plan: ScenePlan, length: int, n_points: int) -> list[str]:
    probs = []
    prod = sum(s.seconds for s in plan.scenes if s.product_visible)
    if prod > _max_product_sec(length):
        probs.append(f"제품 노출 씬 합이 {prod}초로 상한 {_max_product_sec(length)}초를 넘는다.")
    covered = {i for s in plan.scenes for i in s.point_indices}
    missing = [i for i in range(n_points) if i not in covered]
    if missing:
        probs.append(f"영상 포인트 {missing}번이 어떤 씬에도 없다.")
    sigs = [s.signature for s in plan.scenes]
    if "opening" not in sigs[:2]:
        probs.append("오프닝 멘트가 1·2번 씬에 없다.")
    if sigs[-1] != "ending":
        probs.append("엔딩 멘트가 마지막 씬에 없다.")
    return probs


def make_plan(ch: ChannelProfile, sp: Sponsorship, concept: Concept, video_points: list[str],
              description_points: list[str], knowledge: str, feedback: str = "") -> ScenePlan:
    runner = gen_structured(ScenePlan, temperature=0.4)
    note = f"\n[이전 검증에서 실패한 점 — 반드시 고칠 것]\n{feedback}" if feedback else ""
    plan = None
    for _ in range(3):
        prompt = PROMPT.format(
            length_sec=sp.length_sec,
            hook_max=load_rules()["hook"]["max_sec"],
            max_product_sec=_max_product_sec(sp.length_sec),
            scene_hint=SCENE_HINT[sp.length_sec],
            opening=ch.signature_opening,
            ending=ch.signature_ending,
            channel_name=ch.channel_name,
            concept_text=ch.concept,
            format=ch.representative_format,
            concept_no=concept.concept_no,
            title=concept.title,
            hook_type=concept.hook_type,
            hook_line=concept.hook_line,
            summary=concept.summary,
            product_name=sp.product_name,
            product_desc=sp.product_desc,
            video_points="\n".join(f"{i}. {p}" for i, p in enumerate(video_points)),
            description_points=description_points or "(없음)",
            knowledge=knowledge,
            feedback=note,
        )
        plan = normalize(runner.invoke(prompt), sp.length_sec)
        probs = problems(plan, sp.length_sec, len(video_points))
        if not probs:
            break
        note = (note + "\n" if feedback else "\n[이전 계획의 문제 — 고쳐서 다시]\n") + "\n".join(probs)
    plan.description_points = list(description_points)
    return plan


def plan_node(state: PlanState) -> dict:
    sp = state["sponsorship"]
    plan = make_plan(
        state["channel"], sp, state["concept"],
        state.get("video_points", sp.promo_points),
        state.get("description_points", []),
        state.get("knowledge", ""),
        state.get("check_feedback", ""),
    )
    return {"plan": plan}
