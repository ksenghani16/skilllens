"""Evaluation harness: measures how good SkillLens is on a benchmark of injected bugs.

For every manifest entry and every mode it records:
  detected      - did the comparator flag a regression?
  cause_correct - does the top cause blame a change containing the known bug marker?
Then it aggregates per mode (detection rate, cause accuracy, verified precision, false alarms).
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

from .config import Config
from .llm import LLM
from .models import Case
from .pipeline import MODES, run_investigation


class EvalRow(BaseModel):
    entry_id: str
    mode: str
    expects_regression: bool
    detected: bool
    top_status: str          # confirmed / unverified / none
    cause_correct: Optional[bool]
    seconds: float
    llm_calls: int


def load_cases(path: str | Path) -> list[Case]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    items = data["cases"] if isinstance(data, dict) else data
    return [Case.model_validate(c) for c in items]


def evaluate(manifest_path: str, cfg: Config, llm: LLM, modes: tuple[str, ...] = MODES,
             out_dir: str = "results") -> tuple[list[EvalRow], str]:
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rows: list[EvalRow] = []

    for entry in manifest:
        old = Path(entry["old_skill"]).read_text(encoding="utf-8")
        new = Path(entry["new_skill"]).read_text(encoding="utf-8")
        cases = load_cases(entry["cases"])
        for mode in modes:
            rep = run_investigation(old, new, cases, cfg, llm, mode=mode,
                                    run_dir=out / "runs" / f"{entry['id']}__{mode}", run_id=f"{entry['id']}__{mode}")
            top = rep.top_cause()
            correct: Optional[bool] = None
            if entry["expects_regression"] and top is not None:
                marker = entry["bug_marker"]
                correct = any(marker in ch.text for ch in top.blamed_changes)
            rows.append(EvalRow(entry_id=entry["id"], mode=mode, expects_regression=entry["expects_regression"],
                                detected=rep.regression_detected, top_status=top.status if top else "none",
                                cause_correct=correct, seconds=round(rep.seconds, 1), llm_calls=rep.llm_calls))
            print(f"  {entry['id']:<30} {mode:<18} detected={rep.regression_detected} correct={correct}")

    with (out / "results.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(EvalRow.model_fields))
        w.writeheader()
        for r in rows:
            w.writerow(r.model_dump())

    md = summarize(rows, cfg.model)
    (out / "results.md").write_text(md, encoding="utf-8")
    return rows, md


def summarize(rows: list[EvalRow], model: str) -> str:
    lines = [f"# SkillLens evaluation (model: `{model}`)", "",
             "| mode | bugs | detection rate | cause accuracy | verified precision | false alarms | model calls |",
             "|---|---|---|---|---|---|---|"]
    for mode in sorted({r.mode for r in rows}, key=lambda m: MODES.index(m)):
        rs = [r for r in rows if r.mode == mode]
        bugs = [r for r in rs if r.expects_regression]
        ctrl = [r for r in rs if not r.expects_regression]
        det = sum(r.detected for r in bugs)
        correct = sum(bool(r.cause_correct) for r in bugs)
        confirmed = [r for r in bugs if r.top_status == "confirmed"]
        prec = f"{sum(bool(r.cause_correct) for r in confirmed)}/{len(confirmed)}" if confirmed else "n/a"
        fa = f"{sum(r.detected for r in ctrl)}/{len(ctrl)}" if ctrl else "n/a"
        calls = sum(r.llm_calls for r in rs)
        lines.append(f"| {mode} | {len(bugs)} | {det}/{len(bugs)} | {correct}/{len(bugs)} | {prec} | {fa} | {calls} |")
    lines += ["", "Cause accuracy counts a bug as solved only if the top cause blames a change containing the "
                  "known bug marker. Verified precision: among top causes the verifier confirmed, how many were right. "
                  "Model calls only count real calls (cached calls are free), so later modes look cheaper than they are."]
    return "\n".join(lines) + "\n"
