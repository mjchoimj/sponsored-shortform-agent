"""평가 실행 — 20세트 × (Agent, 기준선)을 돌리고 채점해 점수표를 낸다.

HITL 은 케이스 파일에 적힌 응답을 자동으로 넣는다. 이미 결과가 있으면 다시 만들지 않는다(이어서 실행 가능).
    python -m eval.run_eval                     # 전체
    python -m eval.run_eval --cases N01,F04     # 일부만
    python -m eval.run_eval --workers 3         # 동시에 3건
    python -m eval.run_eval --fresh             # 기존 결과 무시하고 새로
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from langgraph.types import Command

from app import config
from app.graph import build_graph
from app.llm import get_usage_log, start_usage_log
from app.tracing import trace_config
from app.schemas import EvalCase, PlanOutput, load_case, load_channel
from eval.baseline import run_baseline
from eval.grader import GROUPS, grade

RESULTS = config.EVAL_DIR / "results"
SYSTEMS = ("agent", "baseline")


def run_agent(case: EvalCase) -> tuple[PlanOutput | None, dict]:
    graph = build_graph()
    cfg = {"configurable": {"thread_id": str(uuid.uuid4())}}
    cfg, trace_where = trace_config(cfg, name=f"eval-{case.case_id}", tags=["eval", case.channel_id])
    answers = {h.stage: h.answer for h in case.hitl_responses}
    out = graph.invoke({"channel": load_channel(case.channel_id), "sponsorship": case.sponsorship}, cfg)
    while "__interrupt__" in out:
        stage = out["__interrupt__"][0].value["stage"]
        out = graph.invoke(Command(resume=answers.get(stage, "accept_suggestion")), cfg)
    meta = {
        "stopped": out.get("stopped", False),
        "revision": out.get("revision", 0),
        "unresolved": out.get("unresolved", False),
        "precheck_types": sorted({i.type for i in out["precheck"].issues}) if out.get("precheck") else [],
        "output_dir": out.get("output_dir"),
        "trace": trace_where,
    }
    return out.get("output"), meta


def _path(system: str, kind: str, case_id: str) -> Path:
    return RESULTS / system / kind / f"{case_id}.json"


def produce(system: str, case: EvalCase, fresh: bool) -> PlanOutput | None:
    p = _path(system, "output", case.case_id)
    if p.exists() and not fresh:
        return PlanOutput.model_validate_json(p.read_text(encoding="utf-8"))
    meta = {}
    if system == "agent":
        out, meta = run_agent(case)
    else:
        out = run_baseline(load_channel(case.channel_id), case.sponsorship)
    if out is None:
        return None
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(out.model_dump_json(indent=2), encoding="utf-8")
    if meta:
        _path(system, "meta", case.case_id).parent.mkdir(parents=True, exist_ok=True)
        _path(system, "meta", case.case_id).write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def evaluate(system: str, case: EvalCase, fresh: bool) -> dict:
    gp = _path(system, "grade", case.case_id)
    if gp.exists() and not fresh:
        return json.loads(gp.read_text(encoding="utf-8"))
    start_usage_log()
    out = produce(system, case, fresh)
    gen_calls = get_usage_log()
    if out is None:
        result = {"case_id": case.case_id, "items": {}, "score": 0.0, "group": {g: 0.0 for g in GROUPS}, "error": "결과 없음"}
    else:
        result = grade(case, load_channel(case.channel_id), out)
    result["system"] = system
    grader_calls = [c for c in get_usage_log() if c["role"] == "grader"]
    gen_calls = [c for c in gen_calls if c["role"] == "gen"]
    result["models"] = {
        "gen": sorted({c["model"] for c in gen_calls}) or ["(이전 실행 결과 재사용 — 기록 없음)"],
        "gen_regions": sorted({c["region"] for c in gen_calls}),
        "grader_regions": sorted({c["region"] for c in grader_calls}),
        "gen_calls": len(gen_calls),
        "gen_fallbacks": sum(1 for c in gen_calls if c["fallback_from"]),
        "grader": sorted({c["model"] for c in grader_calls}),
        "grader_fallbacks": sum(1 for c in grader_calls if c["fallback_from"]),
    }
    gp.parent.mkdir(parents=True, exist_ok=True)
    gp.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 3) if xs else None


def summarize(results: list[dict]) -> dict:
    table = {}
    for system in SYSTEMS:
        rs = [r for r in results if r["system"] == system]
        table[system] = {
            "전체": _mean([r["score"] for r in rs]),
            **{g: _mean([r["group"].get(g) for r in rs]) for g in GROUPS},
            "케이스 수": len(rs),
        }
    return table


def _short(model: str) -> str:
    for key, name in (("haiku-4-5", "Haiku 4.5"), ("sonnet-4-6", "Sonnet 4.6"), ("sonnet-4-5", "Sonnet 4.5"),
                      ("nova-2-lite", "Nova 2 Lite"), ("nova-lite", "Nova Lite")):
        if key in model:
            return name
    return model


def print_table(table: dict, results: list[dict]) -> str:
    names = {"전체": "전체", "A": "A 채널 톤", "B": "B 포인트 반영", "C": "C 규정·구성", "T1": "T1 함정 탐지"}
    fmt = lambda v: "—" if v is None else f"{v:.3f}"
    lines = ["| | Agent | 기준선 |", "|---|---|---|"]
    for k, label in names.items():
        lines.append(f"| {label} | {fmt(table['agent'][k])} | {fmt(table['baseline'][k])} |")
    a, b = table["agent"]["전체"], table["baseline"]["전체"]
    ok = a is not None and b is not None and a >= 0.9 and a > b
    lines.append("")
    lines.append(f"성공 기준(Agent ≥ 0.9 이고 기준선보다 높음): {'달성' if ok else '미달'}")
    lines += ["", "| 케이스 | Agent | 기준선 | Agent 실패 항목 | 생성 모델 (Agent / 기준선) | 채점 모델 (Agent / 기준선) |", "|---|---|---|---|---|---|"]
    by = {(r["system"], r["case_id"]): r for r in results}
    for cid in sorted({r["case_id"] for r in results}):
        ra, rb = by.get(("agent", cid)), by.get(("baseline", cid))
        fails = [c for c, it in (ra or {}).get("items", {}).items() if not it["passed"]]
        m = lambda r, k: ", ".join(_short(x) for x in (r or {}).get("models", {}).get(k, [])) or "?"
        lines.append(
            f"| {cid} | {fmt(ra and ra['score'])} | {fmt(rb and rb['score'])} | {', '.join(fails) or '-'} "
            f"| {m(ra, 'gen')} / {m(rb, 'gen')} | {m(ra, 'grader')} / {m(rb, 'grader')} |"
        )
    text = "\n".join(lines)
    print(text)
    return text


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    logging.basicConfig(level=logging.WARNING)
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default="", help="쉼표로 구분한 케이스 ID (예: N01,F04)")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--fresh", action="store_true")
    args = ap.parse_args()

    paths = sorted((config.EVAL_DIR / "cases").glob("*.json"))
    cases = [load_case(p) for p in paths]
    if args.cases:
        want = {c.strip() for c in args.cases.split(",")}
        cases = [c for c in cases if c.case_id in want]

    jobs = [(s, c) for c in cases for s in SYSTEMS]
    print(f"평가 시작: 케이스 {len(cases)}개 × {SYSTEMS} = {len(jobs)}건 (동시 {args.workers})")
    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(evaluate, s, c, args.fresh): (s, c.case_id) for s, c in jobs}
        for f in as_completed(futs):
            s, cid = futs[f]
            try:
                r = f.result()
                results.append(r)
                print(f"  ✔ {cid} {s:8s} 점수 {r['score']}")
            except Exception as e:
                print(f"  ✘ {cid} {s:8s} 오류: {e}")
                traceback.print_exc()

    table = summarize(results)
    print()
    text = print_table(table, results)
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "summary.json").write_text(json.dumps({"table": table, "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    (RESULTS / "summary.md").write_text(text + "\n", encoding="utf-8")
    print(f"\n저장: {RESULTS / 'summary.md'}")


if __name__ == "__main__":
    main()
