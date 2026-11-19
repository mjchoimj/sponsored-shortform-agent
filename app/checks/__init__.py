"""코드 검증 — 결과물을 rules.json 과 채널 프로필로 결정론적으로 판정한다 (LLM 없음).

Agent 내부 검사용이다. 최종 채점(eval/grader.py)은 이 결과에 채점 AI 판정을 더한다.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.checks.items import ALL_CHECKS, CheckContext
from app.schemas import ChannelProfile, PlanOutput, Sponsorship


class CheckItem(BaseModel):
    code: str  # A1, C2 ...
    name: str
    passed: bool
    detail: str


class CheckReport(BaseModel):
    items: list[CheckItem]

    @property
    def passed(self) -> bool:
        return all(i.passed for i in self.items)

    @property
    def failed(self) -> list[CheckItem]:
        return [i for i in self.items if not i.passed]

    def feedback(self) -> str:
        """수정 루프에 넘길 실패 이유."""
        return "\n".join(f"- {i.code} {i.name}: {i.detail}" for i in self.failed)


def run_checks(channel: ChannelProfile, sponsorship: Sponsorship, output: PlanOutput,
               video_points: list[str] | None = None,
               description_points: list[str] | None = None) -> CheckReport:
    ctx = CheckContext(
        channel=channel,
        sponsorship=sponsorship,
        output=output,
        video_points=list(sponsorship.promo_points if video_points is None else video_points),
        description_points=list(description_points or []),
    )
    items = []
    for code, name, fn in ALL_CHECKS:
        ok, detail = fn(ctx)
        items.append(CheckItem(code=code, name=name, passed=ok, detail=detail))
    return CheckReport(items=items)


__all__ = ["CheckItem", "CheckReport", "run_checks"]
