"""사전 점검 노드 + HITL ① (service.md "사전 점검").

- 코드 판정: 거절 카테고리, 포인트 개수 초과, rules.json 금지 표현(과장)
- LLM 판정: 모순, 채널 콘셉트 충돌, 길이·비율 초과, 과장 표현 고쳐 쓰기
- LLM 은 문제마다 '처리 방법(action)'만 고르고, 적용은 코드가 한다.
"""

from __future__ import annotations

from typing import Literal

from langgraph.types import interrupt
from pydantic import BaseModel, Field

from app.llm import gen_structured
from app.middleware import call_limit
from app.rules import find_forbidden, load_rules, max_points
from app.schemas import (
    ChannelProfile,
    IssueAction,
    PrecheckIssue,
    PrecheckResult,
    Sponsorship,
)
from app.state import PlanState


# --- LLM 출력 모양 --------------------------------------------------------------
class LLMIssue(BaseModel):
    type: Literal["overflow_length", "overflow_ratio", "contradiction", "concept_conflict", "exaggeration"]
    detail: str = Field(description="무엇이 문제인지 한 문장, 한국어")
    point_indices: list[int] = Field(description="처리할 포인트 번호(0부터). rewrite·split 은 1개만")
    action: IssueAction
    rewritten_point: str = Field(default="", description="rewrite·split 일 때 새 문장, 한국어")
    suggestion: str = Field(description="사용자에게 보여 줄 제안, 한국어 한 문장")


class LLMPrecheck(BaseModel):
    issues: list[LLMIssue] = Field(default_factory=list)


PROMPT = """너는 협찬 숏폼 기획 전에 광고주 요구를 점검하는 검토자다.
아래 채널 프로필과 협찬 정보를 보고, 다음 유형의 문제만 찾아라. 문제가 없으면 issues 를 빈 목록으로 둔다.
문제를 지어내지 마라. 확실한 것만 적는다.

[문제 유형과 처리 방법]
- overflow_length: 짧은 영상에 긴 과정(예: 설정 7단계 전부)을 보여 달라는 포인트 → action "split".
  rewritten_point 는 영상용으로 핵심 1~2단계만 담은 짧은 문장, 원문 전체는 설명란으로 간다.
- overflow_ratio: 제품 장면을 영상의 30%보다 많이 보여 달라는 요구 → action "drop" (노출 30% 규칙 우선).
- contradiction: 서로 동시에 참일 수 없는 두 포인트(예: "가장 저렴" + "프리미엄 최고급") →
  둘 중 채널 콘셉트와 제품 설명에 덜 맞는 쪽 하나만 point_indices 에 넣고 action "drop". detail 에 두 포인트를 모두 언급.
- concept_conflict: 채널 콘셉트·말투·avoid 와 정면으로 부딪히는 요구(예: 솔직 리뷰 채널에 "단점 금지",
  5분 출근 채널에 "15단계 파티 메이크업") → 채널 톤에 맞게 바꾼 문장으로 action "rewrite".
  원래 요구가 제품의 다른 활용법이라 설명란에 짧게 남길 가치가 있으면 "split"
  (영상은 채널 콘셉트에 맞는 사용법, 설명란에 원래 활용법). 단순 금지 요구(예: "단점 금지")는 "rewrite".
- rewritten_point 는 영상에서 다룰 '홍보 포인트 문장'으로 쓴다. "~해 주세요" 같은 지시문으로 쓰지 마라.
  예: 핸드크림에 "단점 금지" → "끈적임이 남으면 얇게 두 번 나눠 바르면 금방 흡수됨"
- exaggeration: 근거 없는 최상급·효능 단정·의약품 오인 표현 → action "rewrite", 규정에 맞는 완화 표현으로.

[규칙]
- 포인트 개수가 많은 것은 코드가 따로 처리하니 문제로 적지 마라.
- 한 포인트에는 문제 하나만 적는다. 같은 포인트가 drop 이면 다른 처리는 적지 않는다.
- 모든 문장은 한국어.

[채널 프로필]
{channel}

[협찬 정보]
제품: {product_name} ({category}), 영상 길이 {length_sec}초 (영상에 넣을 수 있는 포인트 최대 {cap}개)
제품 설명: {product_desc}
홍보 포인트:
{points}

[코드가 찾은 금지 표현 — 반드시 exaggeration 으로 다뤄라 (해당 포인트를 drop 하는 경우는 제외)]
{forbidden}
"""


# --- 코드 판정 -------------------------------------------------------------------
def _reject_reason(sp: Sponsorship) -> str:
    cats = load_rules()["categories"]
    if sp.category in cats["rejected"]:
        return cats["rejected_message"]
    if sp.category not in cats["supported"]:
        return f"'{sp.category}' 는 지원하지 않는 카테고리입니다. 지원: {', '.join(cats['supported'])}"
    return ""


def _forbidden_by_point(sp: Sponsorship) -> dict[int, list[dict]]:
    found = {}
    for i, p in enumerate(sp.promo_points):
        hits = find_forbidden(p, sp.category)
        if hits:
            found[i] = hits
    return found


def _fallback_rewrite(text: str, hits: list[dict]) -> str:
    for h in hits:
        repl = "" if h["suggestion"] == "(삭제)" else h["suggestion"]
        text = text.replace(h["word"], repl)
    return " ".join(text.split())


def _llm_issues(ch: ChannelProfile, sp: Sponsorship, forbidden: dict[int, list[dict]]) -> list[PrecheckIssue]:
    points = "\n".join(f"{i}. {p}" for i, p in enumerate(sp.promo_points))
    fb = "\n".join(
        f"{i}번: " + ", ".join(f"'{h['word']}'({h['reason']})" for h in hits) for i, hits in forbidden.items()
    ) or "(없음)"
    prompt = PROMPT.format(
        channel=ch.model_dump_json(indent=1),
        product_name=sp.product_name,
        category=sp.category,
        length_sec=sp.length_sec,
        cap=max_points(sp.length_sec),
        product_desc=sp.product_desc,
        points=points,
        forbidden=fb,
    )
    out: LLMPrecheck = gen_structured(LLMPrecheck, temperature=0).invoke(prompt)
    n = len(sp.promo_points)
    issues = []
    for it in out.issues:
        idx = [i for i in it.point_indices if 0 <= i < n]
        if not idx and it.action != "none":
            continue
        issues.append(PrecheckIssue(**it.model_dump(exclude={"point_indices"}), point_indices=idx, source="llm"))
    return issues


def _ensure_forbidden_covered(issues: list[PrecheckIssue], sp: Sponsorship, forbidden: dict[int, list[dict]]) -> None:
    """LLM 이 놓친 금지 표현은 코드가 직접 이슈로 넣는다."""
    handled = {i for it in issues if it.action in ("drop", "rewrite", "split") for i in it.point_indices}
    for i, hits in forbidden.items():
        if i in handled:
            continue
        words = ", ".join(h["word"] for h in hits)
        issues.append(
            PrecheckIssue(
                type="exaggeration",
                detail=f"{i}번 포인트에 금지 표현({words})이 있습니다.",
                point_indices=[i],
                action="rewrite",
                rewritten_point=_fallback_rewrite(sp.promo_points[i], hits),
                suggestion="규정에 맞는 표현으로 바꿉니다.",
                source="code",
            )
        )


def apply_issues(sp: Sponsorship, issues: list[PrecheckIssue]) -> tuple[list[str], list[str], list[PrecheckIssue]]:
    """제안대로 처리했을 때의 (영상 포인트, 설명란 포인트, 개수 초과 이슈) — 코드로 계산."""
    video: dict[int, str] = dict(enumerate(sp.promo_points))
    desc: list[str] = []
    dropped: set[int] = set()

    order = {"drop": 0, "move_to_description": 1, "split": 2, "rewrite": 3, "none": 4}
    for it in sorted(issues, key=lambda x: order[x.action]):
        if it.action == "drop":
            for i in it.point_indices:
                video.pop(i, None)
                dropped.add(i)
        elif it.action == "move_to_description":
            for i in it.point_indices:
                if i in video:
                    desc.append(sp.promo_points[i])
                    video.pop(i)
        elif it.action in ("rewrite", "split") and it.point_indices:
            i = it.point_indices[0]  # 고쳐 쓰기는 포인트 1개에만
            if i in video and it.rewritten_point.strip():
                video[i] = it.rewritten_point.strip()
                if it.action == "split":
                    desc.append(sp.promo_points[i])

    # 개수 초과: 광고주가 적은 순서를 우선순위로 보고 앞에서부터 상한까지만 영상에.
    cap = max_points(sp.length_sec)
    keep = sorted(video)[:cap]
    moved = sorted(video)[cap:]
    count_issue = []
    if moved:
        desc.extend(video[i] for i in moved)
        count_issue.append(
            PrecheckIssue(
                type="overflow_count",
                detail=f"{sp.length_sec}초 영상에 포인트 {len(video)}개는 많습니다 (상한 {cap}개).",
                point_indices=moved,
                action="move_to_description",
                suggestion=f"앞의 {cap}개만 영상에 넣고 나머지 {len(moved)}개는 설명란으로 보냅니다.",
                source="code",
            )
        )
    return [video[i] for i in keep], desc, count_issue


def run_precheck(ch: ChannelProfile, sp: Sponsorship) -> PrecheckResult:
    reason = _reject_reason(sp)
    if reason:
        return PrecheckResult(rejected=True, reject_reason=reason)

    forbidden = _forbidden_by_point(sp)
    issues = _llm_issues(ch, sp, forbidden)
    _ensure_forbidden_covered(issues, sp, forbidden)
    video, desc, count_issue = apply_issues(sp, issues)
    return PrecheckResult(issues=issues + count_issue, video_points=video, description_points=desc)


# --- 그래프 노드 ------------------------------------------------------------------
def precheck_node(state: PlanState) -> dict:
    call_limit.reset()  # 새 실행 시작 → 호출 횟수 상한을 다시 센다
    return {"precheck": run_precheck(state["channel"], state["sponsorship"])}


ACCEPT = {"accept_suggestion", "accept", "1", "y", "yes", "네", "예", "수락"}
PROCEED = {"proceed", "2", "그대로", "원래대로"}
CANCEL = {"cancel", "3", "n", "no", "취소", "중단"}


def _clean(points) -> list[str]:
    out, seen = [], set()
    for p in points or []:
        t = " ".join(str(p).split())
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def apply_edit(video_points, description_points, length_sec: int) -> tuple[list[str], list[str], list[str]]:
    """사람이 직접 고친 포인트 정리 — 코드로 규칙을 지킨다.

    빈 줄·중복은 지우고, 영상 포인트가 길이별 상한을 넘으면 넘친 뒤쪽 포인트를 설명란 맨 앞으로 옮긴다.
    돌려주는 값: (영상 포인트, 설명란 포인트, 안내 문구)
    """
    video, desc = _clean(video_points), _clean(description_points)
    desc = [d for d in desc if d not in video]
    notes = []
    cap = max_points(length_sec)
    if len(video) > cap:
        moved = video[cap:]
        video = video[:cap]
        desc = moved + desc
        notes.append(f"{length_sec}초 영상은 포인트 {cap}개까지라서 {len(moved)}개를 설명란으로 옮겼습니다.")
    return video, desc, notes


def precheck_hitl_node(state: PlanState) -> dict:
    """HITL ① — 문제가 있으면 제안을 보여 주고 사용자 답을 받는다.

    state["confirm_points"] 가 참이면(웹 화면) 문제가 없어도 영상/설명란 포인트 구분을 보여 주고 확인받는다.
    답이 {"action": "edit", "video_points": [...], "description_points": [...]} 이면 사람이 고친 대로 쓴다.
    """
    pc = state["precheck"]
    sp = state["sponsorship"]
    if pc.rejected:
        return {"stopped": True, "stop_reason": pc.reject_reason}
    if not pc.issues and not state.get("confirm_points"):
        return {
            "precheck_decision": "proceed",
            "video_points": pc.video_points,
            "description_points": pc.description_points,
        }

    question = (
        "광고주 요구에서 아래 문제를 찾았습니다. 제안대로 처리할까요?" if pc.issues
        else "광고주 요구에서 문제는 찾지 못했어요. 영상에 넣을 포인트와 설명란으로 보낼 포인트를 확인해 주세요."
    )
    answer = interrupt(
        {
            "stage": "precheck",
            "question": question,
            "issues": [it.model_dump() for it in pc.issues],
            "proposal": {"video_points": pc.video_points, "description_points": pc.description_points},
            "original_points": list(sp.promo_points),
            "max_video_points": max_points(sp.length_sec),
            "category": sp.category,
            "options": {"accept_suggestion": "제안대로", "proceed": "원래 포인트 그대로", "cancel": "중단",
                        "edit": "직접 고치기"},
        }
    )
    if isinstance(answer, dict) and str(answer.get("action", "")).lower() == "edit":
        video, desc, notes = apply_edit(answer.get("video_points"), answer.get("description_points"), sp.length_sec)
        if video:
            return {"precheck_decision": "edit", "video_points": video, "description_points": desc,
                    "edit_notes": notes}
        answer = "accept_suggestion"  # 영상 포인트를 다 지웠으면 제안대로 진행
    a = str(answer).strip().lower()
    if a in CANCEL:
        return {"precheck_decision": "cancel", "stopped": True, "stop_reason": "사용자가 사전 점검 단계에서 중단했습니다."}
    if a in PROCEED:
        return {"precheck_decision": "proceed", "video_points": list(sp.promo_points), "description_points": []}
    # 그 밖의 답은 제안 수락으로 본다.
    return {
        "precheck_decision": "accept_suggestion",
        "video_points": pc.video_points,
        "description_points": pc.description_points,
    }
