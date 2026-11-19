"""Trace (T19) — 실행 과정을 기록한다.

- .env 에 LANGSMITH_API_KEY 가 있으면 LangSmith 로 보낸다 (프로젝트 이름: LANGSMITH_PROJECT, 기본 sponsored-shortform).
- 키가 없으면 로컬 파일 logs/trace_<시각>_<이름>.jsonl 에 한 줄씩 남긴다:
  노드 시작·끝, 모델 호출(모델 이름·걸린 시간·토큰 수), 도구 호출(검색어), 오류.

사용법: cfg = trace_config(cfg, name="N01") → graph.invoke(..., cfg)
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler

from app import config

LOG_DIR = config.ROOT / "logs"
DEFAULT_PROJECT = "sponsored-shortform"
NODES = {"precheck", "precheck_hitl", "research", "concept", "concept_hitl", "plan", "generate",
         "check", "revise", "final_hitl", "save"}


def langsmith_enabled() -> bool:
    return bool(config.LANGSMITH_API_KEY)


def setup_tracing() -> str:
    """Trace 방식을 정하고 이름을 돌려준다: 'langsmith' 또는 'local'."""
    if langsmith_enabled():
        os.environ["LANGSMITH_TRACING"] = "true"
        os.environ["LANGSMITH_API_KEY"] = config.LANGSMITH_API_KEY
        os.environ.setdefault("LANGSMITH_PROJECT", DEFAULT_PROJECT)
        return "langsmith"
    os.environ["LANGSMITH_TRACING"] = "false"
    return "local"


def _short(x: Any, n: int = 300) -> str:
    s = x if isinstance(x, str) else str(x)
    return s if len(s) <= n else s[:n] + "…"


class LocalTraceHandler(BaseCallbackHandler):
    """LangChain 콜백으로 노드·모델·도구 이벤트를 JSONL 파일에 쓴다."""

    raise_error = False

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._start: dict[UUID, tuple[float, str]] = {}
        self._lock = threading.Lock()

    def _write(self, event: str, **kw: Any) -> None:
        rec = {"time": datetime.now().isoformat(timespec="milliseconds"), "event": event, **kw}
        with self._lock, self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")

    def _done(self, run_id: UUID) -> tuple[float | None, str]:
        t0, name = self._start.pop(run_id, (None, ""))
        return (round(time.time() - t0, 2) if t0 else None), name

    # 노드 (LangGraph 노드는 chain 이벤트로 들어온다)
    def on_chain_start(self, serialized, inputs, *, run_id, metadata=None, **kw):
        node = (metadata or {}).get("langgraph_node")
        name = kw.get("name") or ""
        if node in NODES and name == node:
            self._start[run_id] = (time.time(), node)
            self._write("node_start", node=node)

    def on_chain_end(self, outputs, *, run_id, **kw):
        if run_id in self._start:
            sec, node = self._done(run_id)
            keys = sorted(outputs) if isinstance(outputs, dict) else []
            self._write("node_end", node=node, seconds=sec, updated=keys)

    def on_chain_error(self, error, *, run_id, **kw):
        if run_id in self._start:
            sec, node = self._done(run_id)
            if type(error).__name__ == "GraphInterrupt":  # HITL: 사람 답을 기다리는 정상 멈춤
                self._write("hitl_wait", node=node)
            else:
                self._write("node_error", node=node, seconds=sec, error=_short(error))

    # 모델
    def on_chat_model_start(self, serialized, messages, *, run_id, metadata=None, invocation_params=None, **kw):
        model = (invocation_params or {}).get("model_id") or (invocation_params or {}).get("model") or \
            (metadata or {}).get("ls_model_name", "?")
        self._start[run_id] = (time.time(), str(model))
        self._write("llm_start", model=model, node=(metadata or {}).get("langgraph_node"))

    def on_llm_end(self, response, *, run_id, **kw):
        sec, model = self._done(run_id)
        usage = {}
        try:
            msg = response.generations[0][0].message
            usage = dict(getattr(msg, "usage_metadata", None) or {})
        except Exception:
            pass
        self._write("llm_end", model=model, seconds=sec,
                    input_tokens=usage.get("input_tokens"), output_tokens=usage.get("output_tokens"))

    def on_llm_error(self, error, *, run_id, **kw):
        sec, model = self._done(run_id)
        self._write("llm_error", model=model, seconds=sec, error=_short(error))

    # 도구
    def on_tool_start(self, serialized, input_str, *, run_id, **kw):
        name = (serialized or {}).get("name") or kw.get("name", "tool")
        self._start[run_id] = (time.time(), name)
        self._write("tool_start", tool=name, input=_short(input_str))

    def on_tool_end(self, output, *, run_id, **kw):
        sec, name = self._done(run_id)
        self._write("tool_end", tool=name, seconds=sec, output_chars=len(str(output)))

    def on_tool_error(self, error, *, run_id, **kw):
        sec, name = self._done(run_id)
        self._write("tool_error", tool=name, seconds=sec, error=_short(error))


def trace_config(cfg: dict, name: str = "run", tags: list[str] | None = None) -> tuple[dict, str]:
    """그래프 실행 설정(cfg)에 Trace 를 붙인다. (새 cfg, 기록 위치 설명)을 돌려준다."""
    mode = setup_tracing()
    cfg = {**cfg, "run_name": f"협찬숏폼-{name}", "tags": [*(tags or []), name],
           "metadata": {**cfg.get("metadata", {}), "run": name}}
    if mode == "langsmith":
        return cfg, f"LangSmith 프로젝트 '{os.environ['LANGSMITH_PROJECT']}'"
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
    path = LOG_DIR / f"trace_{datetime.now():%Y%m%d_%H%M%S}_{safe}.jsonl"
    cfg["callbacks"] = [LocalTraceHandler(path)]
    return cfg, str(path)
