"""Observability: a JSONL event log per run, plus optional Langfuse tracing.

The JSONL file is the source of truth. Langfuse is optional and only switches on
when LANGFUSE_PUBLIC_KEY is set, so tests and offline runs never need it.
"""
from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Optional


class RunLogger:
    def __init__(self, run_dir: Optional[Path]):
        self.path: Optional[Path] = None
        if run_dir is not None:
            run_dir.mkdir(parents=True, exist_ok=True)
            self.path = run_dir / "events.jsonl"

    def event(self, component: str, **data) -> None:
        if self.path is None:
            return
        row = {"ts": round(time.time(), 3), "component": component, **data}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, default=str) + "\n")

    @contextmanager
    def span(self, component: str, **data):
        t0 = time.time()
        self.event(f"{component}.start", **data)
        try:
            yield
        finally:
            self.event(f"{component}.end", seconds=round(time.time() - t0, 3), **data)


def _load_observe() -> Optional[Callable]:
    if not os.getenv("LANGFUSE_PUBLIC_KEY"):
        return None
    try:
        from langfuse import observe  # SDK names change between versions: check the Langfuse docs
        return observe
    except Exception:
        return None


_observe = _load_observe()


def traced(name: str):
    """Decorator: sends the function to Langfuse if configured, otherwise does nothing."""
    def deco(fn):
        return _observe(name=name)(fn) if _observe else fn
    return deco
