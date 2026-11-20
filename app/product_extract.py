"""쇼핑몰 상품 설명 → 협찬 입력 초안 (웹 화면의 '붙여넣기로 채우기').

사용자가 상품 상세페이지 글을 복사해 붙이면,
- AI 가 제품명 · 카테고리 · 제품 설명 · 추천 홍보 포인트를 정리하고, 포인트마다 원문 근거 문장을 인용한다.
- 코드가 근거 인용이 원문에 실제로 있는지 확인해 없는 포인트(지어낸 특징)는 뺀다.
- 카테고리가 rules.json 목록에 없으면 비워 두고 사람이 고르게 한다.
결과는 '초안'이다. 사람이 화면에서 확인·수정한 뒤 기획을 시작한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from app.llm import gen_structured
from app.middleware import call_limit
from app.rules import find_forbidden, load_rules

MAX_SOURCE_CHARS = 12000  # 너무 긴 붙여넣기는 앞부분만 쓴다
MAX_POINTS = 5
MAX_DESC_CHARS = 600
QUOTE_MIN_OVERLAP = 0.8  # 인용이 원문과 글자 단위로 이만큼 겹치면 '원문에 있음'


# --- AI 출력 모양 ----------------------------------------------------------------
class ExtractedPoint(BaseModel):
    point: str = Field(description="홍보 포인트 한 문장, 한국어, 40자 이내")
    quote: str = Field(description="이 포인트의 근거가 된 원문 문장을 원문에서 그대로 복사")


class ProductDraft(BaseModel):
    product_name: str = Field(description="제품 이름 (브랜드 + 제품명)")
    category: str = Field(description="카테고리 목록 중 하나를 그대로")
    product_desc: str = Field(description="제품 설명: 스펙·구성·가격 등 사실 정보, 한국어 2~4문장")
    points: list[ExtractedPoint] = Field(description="영상에서 강조할 만한 특징 3~5개")


PROMPT = """너는 협찬 숏폼 기획을 돕는 정리 담당이다. 아래는 쇼핑몰 상품 상세페이지에서 복사한 글이다.
이 글만 보고 협찬 입력 초안을 만든다.

[규칙]
- 원문에 있는 사실만 쓴다. 원문에 없는 기능·수치·효과를 지어내지 마라.
- product_name: 브랜드와 제품명.
- category: 다음 중 하나를 그대로 고른다 → {categories}
- product_desc: 스펙·구성·용량·무게처럼 확인할 수 있는 사실 위주로 2~4문장.
  원문에 가격이 있으면 반드시 넣는다 (할인가가 있으면 판매가 기준, 예: "판매가 23,900원").
- points: 짧은 영상에서 시청자에게 보여 주기 좋은 특징 3~5개, 중요한 순서대로.
  · 한 포인트에 특징 하나, 40자 이내 한 문장.
  · quote 에는 그 포인트의 근거가 된 원문 문장을 원문 그대로(글자 하나 바꾸지 말고) 복사한다.
- 배송·교환·환불·쿠폰·리뷰 이벤트 안내는 포인트로 쓰지 않는다.
- 모든 글은 한국어.

[상세페이지 글]
{source}
"""


# --- 결과 -----------------------------------------------------------------------
@dataclass
class ExtractResult:
    product_name: str
    category: str  # 목록에 없으면 ""
    product_desc: str
    points: list[str]
    quotes: list[str]  # points 와 같은 순서의 근거 인용
    dropped: list[str] = field(default_factory=list)  # 원문에서 근거를 못 찾아 뺀 포인트
    notes: list[str] = field(default_factory=list)  # 사용자에게 보여 줄 안내


def _squash(text: str) -> str:
    return re.sub(r"[^0-9a-zA-Z가-힣]", "", text.lower())


def _bigrams(text: str) -> set[str]:
    s = _squash(text)
    return {s[i:i + 2] for i in range(len(s) - 1)}


def quote_in_source(quote: str, source: str) -> bool:
    """인용이 원문에 있는가 (공백·문장부호 무시). 완전히 같지 않으면 두 글자 조각이 80% 이상 겹쳐야 한다."""
    q = _squash(quote)
    if len(q) < 4:  # 너무 짧은 인용은 근거로 인정하지 않는다
        return False
    if q in _squash(source):
        return True
    qb = _bigrams(quote)
    return len(qb & _bigrams(source)) / len(qb) >= QUOTE_MIN_OVERLAP


def categories() -> list[str]:
    cats = load_rules()["categories"]
    return cats["supported"] + cats["rejected"]


def verify(draft: ProductDraft, source: str) -> ExtractResult:
    """AI 초안을 코드로 확인한다: 근거 없는 포인트 빼기, 카테고리 확인, 길이 제한."""
    notes: list[str] = []
    category = draft.category.strip()
    if category not in categories():
        notes.append(f"카테고리 '{category}' 는 목록에 없어요. 직접 골라 주세요.")
        category = ""

    points, quotes, dropped, seen = [], [], [], set()
    for p in draft.points:
        text = " ".join(p.point.split())
        if not text or _squash(text) in seen:
            continue
        if not quote_in_source(p.quote, source):
            dropped.append(text)
            continue
        seen.add(_squash(text))
        points.append(text)
        quotes.append(" ".join(p.quote.split()))
    points, quotes = points[:MAX_POINTS], quotes[:MAX_POINTS]
    if dropped:
        notes.append(f"원문에서 근거를 찾지 못한 포인트 {len(dropped)}개는 뺐어요.")
    if not points:
        notes.append("근거가 확인된 포인트가 없어요. 포인트를 직접 적어 주세요.")

    if category:
        hits = sorted({h["word"] for p in points for h in find_forbidden(p, category)})
        if hits:
            notes.append(f"광고 규정 금지 표현이 있어요({', '.join(hits)}). 기획을 시작하면 사전 점검에서 고쳐 쓰자고 제안해요.")

    desc = " ".join(draft.product_desc.split())
    if len(desc) > MAX_DESC_CHARS:
        desc = desc[:MAX_DESC_CHARS].rstrip() + "…"
    return ExtractResult(
        product_name=" ".join(draft.product_name.split()),
        category=category,
        product_desc=desc,
        points=points,
        quotes=quotes,
        dropped=dropped,
        notes=notes,
    )


def extract_from_text(source: str) -> ExtractResult:
    """붙여 넣은 상세페이지 글 → 확인을 거친 입력 초안."""
    source = source.strip()
    if len(source) < 20:
        raise ValueError("붙여 넣은 글이 너무 짧아요. 상품 설명 부분을 더 복사해 주세요.")
    truncated = len(source) > MAX_SOURCE_CHARS
    source = source[:MAX_SOURCE_CHARS]
    call_limit.reset()  # 기획 실행과 따로 센다
    draft: ProductDraft = gen_structured(ProductDraft, temperature=0).invoke(
        PROMPT.format(categories=", ".join(categories()), source=source)
    )
    result = verify(draft, source)
    if truncated:
        result.notes.insert(0, f"글이 길어서 앞부분 {MAX_SOURCE_CHARS:,}자만 읽었어요.")
    return result
