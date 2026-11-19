"""검증 항목별 판정 함수. 각 함수는 (통과 여부, 근거 문장)을 돌려준다.

A1 말투 비율 · A2 시그니처 · A3 avoid · B1 포인트 · C1 광고 표시 · C2 금지 표현
C3 노출 ≤ 30% · C4 첫 씬 · C5 길이 합
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.rules import find_forbidden, load_rules
from app.schemas import ChannelProfile, PlanOutput, Sponsorship


@dataclass
class CheckContext:
    channel: ChannelProfile
    sponsorship: Sponsorship
    output: PlanOutput
    video_points: list[str]
    description_points: list[str]

    @property
    def script_lines(self) -> list[str]:
        """대사 + 자막 (말투·시그니처 판정 대상)."""
        lines = []
        for s in self.output.storyboard.scenes:
            lines += [s.dialogue, s.caption]
        return [l for l in lines if l and l.strip()]

    @property
    def all_text(self) -> str:
        pkg = self.output.upload_package
        return "\n".join(self.script_lines + [pkg.title, pkg.description, " ".join(pkg.hashtags)])


def _squash(text: str) -> str:
    """공백·문장부호를 지운 비교용 문자열."""
    return re.sub(r"[^0-9a-zA-Z가-힣]", "", text.lower())


def _bigrams(text: str) -> set[str]:
    s = _squash(text)
    return {s[i : i + 2] for i in range(len(s) - 1)}


def _containment(needle: str, haystack: str) -> float:
    """needle 의 두 글자 조각 중 haystack 에 있는 비율."""
    n = _bigrams(needle)
    return len(n & _bigrams(haystack)) / len(n) if n else 1.0


# --- A1 말투 -----------------------------------------------------------------------
HONORIFIC = ("요", "니다", "니까", "세요", "죠", "십시오", "시오")
# 반말 어미 (문장 끝 글자·조각). 명사로 끝나는 짧은 문구는 '중립'으로 빠진다.
CASUAL = (
    "야", "어", "아", "지", "네", "해", "돼", "봐", "줘", "와", "자", "래", "게", "냐", "니",
    "걸", "군", "구나", "거든", "잖아", "다", "라", "마", "까", "던데", "는데", "을걸", "더라",
)


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?…~])\s+|[\n]+|(?<=[.!?…])(?=\S)", text)
    return [p.strip() for p in parts if p and p.strip()]


def speech_of(sentence: str) -> str:
    """'존댓말' | '반말' | '중립'."""
    core = re.sub(r"[^가-힣0-9a-zA-Z]+$", "", sentence.strip())
    if not core or not re.search(r"[가-힣]$", core):
        return "중립"
    if core.endswith(HONORIFIC):
        return "존댓말"
    if core.endswith(("음", "함", "됨", "임", "기", "것")):  # 명사형 메모체
        return "중립"
    if core.endswith(CASUAL):
        return "반말"
    return "중립"


def check_a1(ctx: CheckContext) -> tuple[bool, str]:
    target = ctx.channel.speech_style
    other = "존댓말" if target == "반말" else "반말"
    sents = [s for line in ctx.script_lines for s in split_sentences(line)]
    hit = [s for s in sents if speech_of(s) == target]
    miss = [s for s in sents if speech_of(s) == other]
    judged = len(hit) + len(miss)
    if judged == 0:
        return True, "말투를 판정할 문장이 없음 (모두 중립)"
    ratio = len(hit) / judged
    need = 0.9
    detail = f"{target} 문장 {len(hit)}/{judged} = {ratio:.0%} (기준 {need:.0%})"
    if miss:
        detail += " · 어긋난 문장: " + " | ".join(miss[:3])
    return ratio >= need, detail


# --- A2 시그니처 · A3 avoid ----------------------------------------------------------
def check_a2(ctx: CheckContext) -> tuple[bool, str]:
    script = _squash(" ".join(ctx.script_lines))
    missing = [
        label for label, sig in (("오프닝", ctx.channel.signature_opening), ("엔딩", ctx.channel.signature_ending))
        if _squash(sig) not in script
    ]
    if missing:
        return False, f"{', '.join(missing)} 멘트 없음"
    return True, "오프닝·엔딩 멘트 모두 있음"


def check_a3(ctx: CheckContext) -> tuple[bool, str]:
    text = _squash(ctx.all_text)
    found = [a for a in ctx.channel.avoid if _squash(a) and _squash(a) in text]
    return (not found), (f"avoid 표현 발견: {found}" if found else "avoid 표현 0건")


# --- B1 포인트 -----------------------------------------------------------------------
VIDEO_MIN, DESC_MIN = 0.5, 0.7


def check_b1(ctx: CheckContext) -> tuple[bool, str]:
    script = " ".join(ctx.script_lines + [s.visual for s in ctx.output.storyboard.scenes])
    desc = ctx.output.upload_package.description
    missing = []
    for p in ctx.video_points:
        # 영상 포인트는 영상에 없더라도 설명란에 있으면 인정 (service.md B1)
        if _containment(p, script) < VIDEO_MIN and _containment(p, desc) < DESC_MIN:
            missing.append(f"영상: {p}")
    for p in ctx.description_points:
        if _containment(p, desc) < DESC_MIN and _containment(p, script) < VIDEO_MIN:
            missing.append(f"설명란: {p}")
    total = len(ctx.video_points) + len(ctx.description_points)
    if missing:
        return False, f"포인트 {total - len(missing)}/{total} 반영 · 빠짐: " + " | ".join(missing)
    return True, f"포인트 {total}/{total} 반영"


# --- C1 광고 표시 · C2 금지 표현 -------------------------------------------------------
def check_c1(ctx: CheckContext) -> tuple[bool, str]:
    ad = load_rules()["ad_disclosure"]
    pkg = ctx.output.upload_package
    first = pkg.description.strip().splitlines()[0] if pkg.description.strip() else ""
    where = [w for w, t in (("제목", pkg.title), ("설명란 첫 줄", first)) if any(a in t for a in ad["allowed"])]
    if where:
        return True, f"{', '.join(where)}에 광고 표시 있음"
    weak = [
        w for w in ad["fail_if_alone"]
        if re.search(rf"(?<![0-9a-zA-Z가-힣]){re.escape(w)}(?![0-9a-zA-Z가-힣])", f"{pkg.title}\n{first}", re.I)
    ]
    if weak:
        return False, f"인정되지 않는 표시만 있음: {weak}. 제목 또는 설명란 첫 줄에 [광고]·#광고 필요"
    return False, "제목·설명란 첫 줄에 광고 표시([광고]·#광고) 없음"


def check_c2(ctx: CheckContext) -> tuple[bool, str]:
    found = sorted({w["word"] for w in find_forbidden(ctx.all_text, ctx.sponsorship.category)})
    return (not found), (f"금지 표현 발견: {found}" if found else "금지 표현 0건")


# --- C3 노출 · C4 첫 씬 · C5 길이 -------------------------------------------------------
SPEC = re.compile(r"\d|SPF|\+")
MODEL_SUFFIX = {"라이트", "미니", "프로", "플러스", "맥스", "세트", "에디션"}


def product_terms(sp: Sponsorship) -> list[str]:
    """제품 이름에서 화면 설명에 나오면 '제품이 보인다'고 볼 단어: 브랜드(첫 단어) + 제품 종류(마지막 단어).

    예: '소리담 오픈형 무선 이어폰' → ['소리담', '이어폰']. 숫자·규격(1.7L, 3개입, SPF50+)은 건너뛴다.
    """
    words = [w for w in sp.product_name.split() if len(w) >= 2 and not SPEC.search(w)]
    while len(words) > 2 and words[-1] in MODEL_SUFFIX:  # '스마트워치 라이트' → '스마트워치'
        words.pop()
    return list(dict.fromkeys([words[0], words[-1]])) if words else []


def hidden_product_scenes(ctx: CheckContext) -> list[int]:
    """product_visible=false 인데 화면 설명(visual)에 제품이 나오는 씬 번호."""
    terms = product_terms(ctx.sponsorship)
    return [s.scene_no for s in ctx.output.storyboard.scenes
            if not s.product_visible and any(t in s.visual for t in terms)]


def check_c3(ctx: CheckContext) -> tuple[bool, str]:
    scenes = ctx.output.storyboard.scenes
    total = sum(s.seconds for s in scenes) or 1
    hidden = set(hidden_product_scenes(ctx))
    prod = sum(s.seconds for s in scenes if s.product_visible or s.scene_no in hidden)
    cap = load_rules()["product_exposure"]["max_ratio"]
    detail = f"제품 노출 {prod}/{total}초 = {prod / total:.0%} (상한 {cap:.0%})"
    if hidden:
        terms = ", ".join(product_terms(ctx.sponsorship))
        detail += (f" · 씬 {sorted(hidden)}은 '제품 없음'인데 화면 설명에 제품({terms})이 나와 노출로 셈."
                   " 이 씬들의 화면 설명에서 제품(손에 든 것·착용·옆에 둔 것 포함)을 빼고 사람·상황·결과만 보이게")
    return prod / total <= cap, detail


def check_c4(ctx: CheckContext) -> tuple[bool, str]:
    first = ctx.output.storyboard.scenes[0]
    hook_max = load_rules()["hook"]["max_sec"]
    probs = []
    if first.product_visible:
        probs.append("첫 씬에 제품이 나옴")
    if first.seconds > hook_max:
        probs.append(f"첫 씬이 {first.seconds}초 (훅 상한 {hook_max}초)")
    return (not probs), (" · ".join(probs) if probs else f"첫 씬 {first.seconds}초, 제품 없음")


def check_c5(ctx: CheckContext) -> tuple[bool, str]:
    total = sum(s.seconds for s in ctx.output.storyboard.scenes)
    target = ctx.sponsorship.length_sec
    return total == target, f"씬 합 {total}초 / 목표 {target}초"


ALL_CHECKS = [
    ("A1", "말투 일치", check_a1),
    ("A2", "시그니처 멘트", check_a2),
    ("A3", "avoid 위반", check_a3),
    ("B1", "포인트 반영", check_b1),
    ("C1", "광고 표시", check_c1),
    ("C2", "금지 표현", check_c2),
    ("C3", "제품 노출", check_c3),
    ("C4", "첫 씬", check_c4),
    ("C5", "길이", check_c5),
]
