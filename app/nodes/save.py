"""저장 노드 — outputs/{시각}_{제품명}/ 에 기획안.md · storyboard.json · check_report.json."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from app import config
from app.checks import CheckReport
from app.schemas import PlanOutput
from app.state import PlanState


def _safe(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|\s]+', "_", name).strip("_")[:40]


def _md(state: PlanState, report: CheckReport) -> str:
    out: PlanOutput = state["output"]
    ch, sp, c = state["channel"], state["sponsorship"], out.concept
    sb, pkg = out.storyboard, out.upload_package
    status = "✅ 검증 통과" if report.passed else "⚠️ 미통과 (최대 수정 후에도 실패한 항목 있음)"
    L = [
        f"# 협찬 숏폼 기획안 — {sp.product_name}",
        "",
        f"- 채널: {ch.channel_name} ({ch.speech_style}) · 길이 {sp.length_sec}초 · 카테고리 {sp.category}",
        f"- 상태: {status} · 수정 {state.get('revision', 0)}회 · 최종 승인: {'예' if state.get('approved') else '아니오'}",
        "",
        "## 기획안 요약",
        f"**{c.concept_no}안 · {c.title}** (훅: {c.hook_type})",
        "",
        f"> {c.hook_line}",
        "",
        c.summary,
        "",
        "영상 포인트: " + " / ".join(state.get("video_points", [])),
    ]
    if state.get("description_points"):
        L.append("설명란 포인트: " + " / ".join(state["description_points"]))
    if state.get("human_feedback"):
        L += ["", "반영한 수정 요청 (사람 검토):"] + [f"- {f}" for f in state["human_feedback"]]
    L += ["", "## 스토리보드", "", "| # | 초 | 제품 | 화면 | 대사 | 자막 |", "|---|---|---|---|---|---|"]
    cell = lambda t: t.replace("|", "\\|").replace("\n", " ")
    for s in sb.scenes:
        L.append(f"| {s.scene_no} | {s.seconds} | {'📦' if s.product_visible else ''} | {cell(s.visual)} | {cell(s.dialogue)} | {cell(s.caption)} |")
    L += ["", "## 체크 리포트", "", "| 항목 | 결과 | 근거 |", "|---|---|---|"]
    for i in report.items:
        L.append(f"| {i.code} {i.name} | {'✅' if i.passed else '❌'} | {cell(i.detail)} |")
    L += [
        "",
        "## 업로드 패키지",
        f"**제목**: {pkg.title}",
        "",
        "**설명란**",
        "```",
        pkg.description,
        "```",
        f"**해시태그**: {' '.join(pkg.hashtags)}",
        f"**광고 표시**: {pkg.ad_disclosure}",
        "",
        "> 권장: 플랫폼의 '유료 광고 포함' 표시를 켜고, 첫 씬 또는 마지막 씬 자막에 '유료광고 포함'을 넣으세요.",
        "",
        "이미지 프롬프트와 스타일 시트는 `storyboard.json` 에 있습니다.",
    ]
    return "\n".join(L) + "\n"


def save_outputs(state: PlanState, base: Path | None = None) -> Path:
    report: CheckReport = state["check_report"]
    out: PlanOutput = state["output"]
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    folder = (base or config.OUTPUTS_DIR) / f"{stamp}_{_safe(state['sponsorship'].product_name)}"
    folder.mkdir(parents=True, exist_ok=True)

    (folder / "기획안.md").write_text(_md(state, report), encoding="utf-8")
    storyboard = {
        "product": state["sponsorship"].product_name,
        "channel_id": state["channel"].channel_id,
        "length_sec": state["sponsorship"].length_sec,
        **json.loads(out.model_dump_json()),
    }
    (folder / "storyboard.json").write_text(json.dumps(storyboard, ensure_ascii=False, indent=2), encoding="utf-8")
    check = {
        "passed": report.passed,
        "unresolved": state.get("unresolved", False),
        "approved": state.get("approved", False),
        "revision": state.get("revision", 0),
        "final_action": state.get("final_action", ""),
        "human_feedback": state.get("human_feedback", []),
        "items": [i.model_dump() for i in report.items],
        "history": [[i.model_dump() for i in r.items] for r in state.get("check_history", [])],
        "precheck": json.loads(state["precheck"].model_dump_json()) if state.get("precheck") else None,
    }
    (folder / "check_report.json").write_text(json.dumps(check, ensure_ascii=False, indent=2), encoding="utf-8")
    return folder


def save_node(state: PlanState) -> dict:
    return {"output_dir": str(save_outputs(state))}
