"""콘셉트 3안 노드 + HITL ② (service.md "콘셉트와 계획").

1안: 채널 대표 포맷에 제품만 끼워 넣기. 2·3안: 훅 유형을 바꾼다. 셋 다 채널 말투 유지.
훅 유형이 서로 다른지·번호가 1~3인지는 코드로 확인하고, 어기면 한 번 다시 만든다.
"""

from __future__ import annotations

from langgraph.types import interrupt

from app.llm import gen_structured
from app.rag import search
from app.schemas import ChannelProfile, Concept, ConceptOptions, Sponsorship
from app.state import PlanState

PROMPT = """너는 인플루언서 채널의 협찬 숏폼(9:16, {length_sec}초) 기획자다.
아래 채널의 평소 톤 그대로, 협찬 제품을 다루는 콘셉트 3안을 만든다.

[3안 규칙]
- 1안: 채널 대표 포맷("{format}") 흐름 그대로, 제품만 자연스럽게 끼워 넣는다.
- 2안·3안: 1안과 훅(첫 3초) 유형이 다르다. 세 안의 hook_type 은 서로 모두 달라야 한다.
  훅 유형 예: 문제 제기, 질문형, 지적·잔소리형, 비포·애프터, 숫자형, 공감형.
- 세 안 모두 이 채널의 concept("{concept}") 안에 있어야 한다. 훅만 바꾸고, 다른 채널 같은 주제로 바꾸지 않는다.
- 셋 다 채널 말투({speech})를 지킨다. hook_line 은 영상 첫 대사이고 {speech}로 쓴다.
- 첫 3초에는 제품을 보여 주지 않는다. hook_line 에 제품명을 넣지 않는다.
- avoid 표현과 과장·효능 단정 표현을 쓰지 않는다.
- title 은 콘셉트 이름(짧게), summary 는 영상 흐름을 2~3문장으로. 모두 한국어.

[채널 프로필]
{channel}

[협찬 정보]
제품: {product_name} ({category})
제품 설명: {product_desc}
영상에 넣을 포인트: {video_points}
설명란으로 보낼 포인트: {description_points}

[참고 자료 — 숏폼 노하우·규정]
{knowledge}
{retry_note}"""


def _knowledge(state: PlanState) -> str:
    if state.get("knowledge"):
        return state["knowledge"]
    docs = search("첫 3초 훅 유형", k=1) + search("채널 대표 포맷 말투 유지", k=1)
    return "\n\n".join(d.page_content for d in docs)


def _problems(opts: ConceptOptions) -> list[str]:
    probs = []
    if sorted(c.concept_no for c in opts.concepts) != [1, 2, 3]:
        probs.append("concept_no 는 1, 2, 3 이어야 한다.")
    hooks = [c.hook_type.replace(" ", "") for c in opts.concepts]
    if len(set(hooks)) != 3:
        probs.append(f"hook_type 이 겹친다: {hooks}. 세 안 모두 다른 훅 유형으로.")
    return probs


def make_concepts(ch: ChannelProfile, sp: Sponsorship, video_points: list[str],
                  description_points: list[str], knowledge: str) -> ConceptOptions:
    runner = gen_structured(ConceptOptions, temperature=0.8)
    retry_note = ""
    for _ in range(2):
        prompt = PROMPT.format(
            length_sec=sp.length_sec,
            format=ch.representative_format,
            concept=ch.concept,
            speech=ch.speech_style,
            channel=ch.model_dump_json(indent=1),
            product_name=sp.product_name,
            category=sp.category,
            product_desc=sp.product_desc,
            video_points=video_points,
            description_points=description_points or "(없음)",
            knowledge=knowledge,
            retry_note=retry_note,
        )
        opts: ConceptOptions = runner.invoke(prompt)
        probs = _problems(opts)
        if not probs:
            break
        retry_note = "\n[이전 답의 문제 — 고쳐서 다시]\n" + "\n".join(probs)
    opts.concepts.sort(key=lambda c: c.concept_no)
    return opts


def concept_node(state: PlanState) -> dict:
    sp = state["sponsorship"]
    knowledge = _knowledge(state)
    opts = make_concepts(
        state["channel"], sp,
        state.get("video_points", sp.promo_points),
        state.get("description_points", []),
        knowledge,
    )
    return {"concepts": opts, "knowledge": knowledge}


def concept_hitl_node(state: PlanState) -> dict:
    """HITL ② — 3안 중 하나를 고른다. 1~3 이 아닌 답은 1안으로 본다."""
    opts: ConceptOptions = state["concepts"]
    answer = interrupt(
        {
            "stage": "concept",
            "question": "콘셉트 3안 중 하나를 골라 주세요 (1, 2, 3).",
            "concepts": [c.model_dump() for c in opts.concepts],
        }
    )
    try:
        no = int(str(answer).strip().rstrip("안번"))
    except ValueError:
        no = 1
    chosen: Concept = next((c for c in opts.concepts if c.concept_no == no), opts.concepts[0])
    return {"concept": chosen}
