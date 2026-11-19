"""같은 제품 × 다른 채널 비교표 (T21) — 점수와 별도로, 채널마다 결과가 어떻게 달라졌는지 나란히 보여 준다.

평가 결과(eval/results/{agent,baseline}/output/)에서 제품 이름이 같은 케이스끼리 묶어
콘셉트 훅 유형 · 첫 대사(1번 씬) · 제목을 표로 만든다.
    python -m eval.compare        → eval/results/compare.md
"""

from __future__ import annotations

import sys
from collections import defaultdict

from app import config
from app.schemas import PlanOutput, load_case, load_channel

RESULTS = config.EVAL_DIR / "results"


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ").strip()


def build() -> str:
    cases = [load_case(p) for p in sorted((config.EVAL_DIR / "cases").glob("*.json"))]
    groups: dict[str, list] = defaultdict(list)
    for c in cases:
        groups[c.sponsorship.product_name].append(c)
    pairs = {k: v for k, v in groups.items() if len({c.channel_id for c in v}) > 1}

    lines = ["# 같은 제품 × 다른 채널 비교표", "",
             "점수 외 참고용. 같은 협찬 제품이 채널에 따라 훅·첫 대사·제목이 어떻게 달라지는지 본다.", ""]
    for product, cs in pairs.items():
        lines += [f"## {product}", ""]
        for system, label in (("agent", "Agent"), ("baseline", "기준선")):
            lines += [f"**{label}**", "", "| 케이스 | 채널 (콘셉트·말투) | 훅 유형 | 첫 대사 (1번 씬) | 제목 |", "|---|---|---|---|---|"]
            for c in cs:
                ch = load_channel(c.channel_id)
                p = RESULTS / system / "output" / f"{c.case_id}.json"
                if not p.exists():
                    lines.append(f"| {c.case_id} | {ch.channel_name} | (결과 없음) | | |")
                    continue
                out = PlanOutput.model_validate_json(p.read_text(encoding="utf-8"))
                first = out.storyboard.scenes[0].dialogue if out.storyboard.scenes else ""
                lines.append(
                    f"| {c.case_id} | {_cell(ch.channel_name)} ({_cell(ch.concept)} · {ch.speech_style}) "
                    f"| {_cell(out.concept.hook_type)} | {_cell(first)} | {_cell(out.upload_package.title)} |"
                )
            lines.append("")
    return "\n".join(lines)


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    text = build()
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "compare.md").write_text(text + "\n", encoding="utf-8")
    print(text)
    print(f"\n저장: {RESULTS / 'compare.md'}")


if __name__ == "__main__":
    main()
