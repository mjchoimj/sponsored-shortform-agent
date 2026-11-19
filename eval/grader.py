"""최종 채점기 — 코드 항목 + 채점 모델(상위 모델, temperature 0) 의미 판정.

채점 AI 판정은 반드시 근거 문장 인용을 받고, 인용이 원고에 실제로 있는지 코드로 확인한다.
인용이 원고에 없으면 그 판정은 인정하지 않는다(실패).
Agent 코드(app/)는 이 파일과 채점 프롬프트를 import 하지 않는다 (service.md "Agent는 채점기를 보지 못한다").

    python -m eval.grader eval/cases/N01_CH1.json eval/results/baseline/N01.json
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from pydantic import BaseModel, Field

from app import config
from app.checks import run_checks
from app.llm import chat, get_usage_log, invoke_with_fallback
from app.rules import load_rules
from app.schemas import ChannelProfile, EvalCase, PlanOutput, load_case, load_channel

GROUPS = {"A": ["A1", "A2", "A3", "A4"], "B": ["B1"], "C": ["C1", "C2", "C3", "C4", "C5"], "T1": ["T1"]}
# 함정 처리에서 포인트를 빼는 게 정답인 유형 → B1 대상에서 제외 (T1 이 따로 본다)
DROP_TRAPS = {"overflow_ratio", "contradiction", "concept_conflict"}


# --- 채점 AI 출력 모양 ------------------------------------------------------------
class SigJudge(BaseModel):
    opening_present: bool = Field(description="오프닝 멘트와 의미가 같은 문장이 대사·자막에 있는가")
    opening_quote: str = Field(description="그 문장을 원고에서 그대로 인용. 없으면 빈 문자열")
    ending_present: bool
    ending_quote: str


class ConceptJudge(BaseModel):
    score: int = Field(ge=1, le=5, description="채널 콘셉트·톤 적합도 1~5")
    reason: str
    quote: str = Field(description="판단 근거가 된 대사·자막을 원고에서 그대로 인용")


class PointJudge(BaseModel):
    point_index: int
    covered: bool = Field(description="이 포인트의 핵심 내용이 영상(대사·자막·화면) 또는 설명란에 있는가")
    quote: str = Field(description="반영된 문장을 원고에서 그대로 인용. 없으면 빈 문자열")


class SceneJudge(BaseModel):
    scene_no: int
    product_visible: bool = Field(description="화면 설명·대사로 볼 때 이 씬에 협찬 제품이 화면에 보이는가")


class TrapJudge(BaseModel):
    handled: bool = Field(description="결과물이 기대 처리대로 함정을 처리했는가")
    reason: str
    quote: str = Field(description="처리를 보여 주는 문장을 원고에서 그대로 인용 (빼는 처리라 보여 줄 문장이 없으면 빈 문자열)")


class GradeLLM(BaseModel):
    signature: SigJudge
    concept: ConceptJudge
    points: list[PointJudge]
    scenes: list[SceneJudge]
    trap: TrapJudge | None = None


PROMPT = """너는 협찬 숏폼 기획 결과물을 채점하는 엄격한 평가자다. 아래 결과물을 읽고 판정만 한다.
모든 quote 는 결과물 원고에서 한 글자도 바꾸지 말고 그대로 복사한다. 원고에 없는 문장을 지어내면 판정이 무효가 된다.

[채널 프로필]
{channel}

[협찬 포인트 (번호: 내용)]
{points}

[결과물 — 콘셉트 · 스토리보드 · 업로드 패키지]
{output}

판정할 것:
1. signature: 오프닝 "{opening}" / 엔딩 "{ending}" 와 의미가 같은 문장이 대사·자막에 있는가 (표현이 조금 달라도 의미가 같으면 true).
2. concept: 이 결과물이 채널 콘셉트·톤("{concept}", 톤 {tone})에 얼마나 맞는가 1~5점. 5=채널 평소 영상 같음, 3=무난하지만 채널색 약함, 1=다른 채널 같음.
3. points: 위 포인트 번호 각각({point_ids})이 영상 또는 설명란에 반영됐는가.
4. scenes: 씬 번호 각각에 대해, 화면 설명(visual)과 대사로 볼 때 협찬 제품이 화면에 보이는가 (결과물의 product_visible 값은 무시하고 직접 판단).
{trap_part}"""

TRAP_PART = """5. trap: 이 케이스의 광고주 요구에는 함정이 있다.
   유형: {type} — {detail}
   기대 처리: {handling}
   결과물이 기대 처리대로 처리했는가."""


# --- 인용 확인 -------------------------------------------------------------------
def _squash(text: str) -> str:
    return re.sub(r"[^0-9a-zA-Z가-힣]", "", text.lower())


def output_text(out: PlanOutput) -> str:
    sb, pkg = out.storyboard, out.upload_package
    parts = [out.concept.hook_line]
    for s in sb.scenes:
        parts += [s.visual, s.dialogue, s.caption]
    parts += [pkg.title, pkg.description, " ".join(pkg.hashtags)]
    return "\n".join(parts)


def quote_ok(quote: str, text: str) -> bool:
    """인용이 원고에 실제로 있는가 (공백·문장부호 무시, 4글자 이상)."""
    q = _squash(quote)
    return len(q) >= 4 and q in _squash(text)


# --- 채점 ------------------------------------------------------------------------
def _grade_llm(prompt: str) -> GradeLLM:
    config.require_aws_keys()
    return invoke_with_fallback(
        [config.GRADER_MODEL, *config.GRADER_MODEL_FALLBACKS],
        lambda m: chat(m, config.GRADER_TEMPERATURE, 4000).with_structured_output(GradeLLM),
        prompt,
        role="grader",
    )


def b1_targets(case: EvalCase) -> list[int]:
    n = len(case.sponsorship.promo_points)
    t = case.expected_trap
    skip = set(t.trap_points) if t and t.type in DROP_TRAPS else set()
    return [i for i in range(n) if i not in skip]


def grade(case: EvalCase, ch: ChannelProfile, out: PlanOutput) -> dict:
    sp = case.sponsorship
    text = output_text(out)
    items: dict[str, dict] = {}

    # 1) 코드 항목 (A1 A2 A3 B1 C1 C2 C3 C4 C5)
    targets = b1_targets(case)
    code = {i.code: i for i in run_checks(ch, sp, out, [sp.promo_points[i] for i in targets], []).items}

    # 2) 채점 AI
    trap = case.expected_trap
    prompt = PROMPT.format(
        channel=ch.model_dump_json(indent=1),
        points="\n".join(f"{i}: {sp.promo_points[i]}" for i in targets),
        output=out.model_dump_json(indent=1, exclude={"storyboard": {"style_sheet": True, "scenes": {"__all__": {"image_prompt"}}}}),
        opening=ch.signature_opening,
        ending=ch.signature_ending,
        concept=ch.concept,
        tone=", ".join(ch.tone_keywords),
        point_ids=", ".join(map(str, targets)),
        trap_part=TRAP_PART.format(type=trap.type, detail=trap.trap_detail, handling=trap.expected_handling) if trap else "",
    )
    llm: GradeLLM = _grade_llm(prompt)
    grader_model = next((c["model"] for c in reversed(get_usage_log()) if c["role"] == "grader"), config.GRADER_MODEL)

    for c in ("A1", "A3", "C1", "C2", "C4", "C5"):
        items[c] = {"passed": code[c].passed, "detail": code[c].detail, "by": "code"}

    # A2: 코드(그대로 포함) 또는 채점 AI(의미 같음 + 인용 확인)
    s = llm.signature
    llm_a2 = s.opening_present and s.ending_present and quote_ok(s.opening_quote, text) and quote_ok(s.ending_quote, text)
    items["A2"] = {
        "passed": code["A2"].passed or llm_a2,
        "detail": code["A2"].detail if code["A2"].passed else f"의미 판정: 오프닝 「{s.opening_quote}」 엔딩 「{s.ending_quote}」",
        "by": "code" if code["A2"].passed else "llm+quote",
    }

    # A4: 4점 이상 + 인용 확인
    c4 = llm.concept
    items["A4"] = {
        "passed": c4.score >= 4 and quote_ok(c4.quote, text),
        "detail": f"{c4.score}/5 · {c4.reason} · 근거 「{c4.quote}」" + ("" if quote_ok(c4.quote, text) else " (인용 확인 실패)"),
        "by": "llm+quote",
    }

    # B1: 포인트마다 코드 포함 판정 또는 채점 AI(반영 + 인용 확인)
    judged = {p.point_index: p for p in llm.points}
    missing = []
    for i in targets:
        code_hit = run_checks(ch, sp, out, [sp.promo_points[i]], []).items[3].passed  # B1 단일 포인트
        p = judged.get(i)
        llm_hit = bool(p and p.covered and quote_ok(p.quote, text))
        if not (code_hit or llm_hit):
            missing.append(sp.promo_points[i])
    items["B1"] = {
        "passed": not missing,
        "detail": f"포인트 {len(targets) - len(missing)}/{len(targets)}" + (f" · 빠짐: {missing}" if missing else ""),
        "by": "code+llm",
    }

    # C3: 자체 표시(코드) + 채점 AI 재확인 둘 다 30% 이하
    cap = load_rules()["product_exposure"]["max_ratio"]
    seen = {x.scene_no: x.product_visible for x in llm.scenes}
    total = sum(sc.seconds for sc in out.storyboard.scenes) or 1
    llm_prod = sum(sc.seconds for sc in out.storyboard.scenes if seen.get(sc.scene_no, sc.product_visible))
    items["C3"] = {
        "passed": code["C3"].passed and llm_prod / total <= cap,
        "detail": f"{code['C3'].detail} · 채점 AI 재확인 {llm_prod}/{total}초 = {llm_prod / total:.0%}",
        "by": "code+llm",
    }

    # T1: 함정 케이스만
    if trap:
        t = llm.trap
        need_quote = trap.type not in ("overflow_ratio",)
        ok = bool(t and t.handled and (quote_ok(t.quote, text) or not need_quote))
        items["T1"] = {
            "passed": ok,
            "detail": (f"{t.reason} · 근거 「{t.quote}」" if t else "채점 AI 판정 없음"),
            "by": "llm+quote",
        }

    return {"case_id": case.case_id, "grader_model": grader_model, "items": items, **scores(items)}


def scores(items: dict[str, dict]) -> dict:
    def avg(codes):
        vals = [items[c]["passed"] for c in codes if c in items]
        return round(sum(vals) / len(vals), 3) if vals else None

    return {
        "score": avg(list(items)),
        "group": {g: avg(codes) for g, codes in GROUPS.items()},
    }


if __name__ == "__main__":
    case_path, out_path = sys.argv[1], sys.argv[2]
    case = load_case(case_path)
    out = PlanOutput.model_validate_json(Path(out_path).read_text(encoding="utf-8"))
    result = grade(case, load_channel(case.channel_id), out)
    for code, it in result["items"].items():
        print(f"{'✅' if it['passed'] else '❌'} {code} [{it['by']}] {it['detail']}")
    print(f"\n점수 {result['score']} · 그룹 {json.dumps(result['group'], ensure_ascii=False)}")
