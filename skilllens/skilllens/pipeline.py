"""The whole investigation, step by step.

  Runner -> Comparator -> (Behavior) -> Investigator -> Verifier -> Report

Modes (used for the ablation study in your evaluation):
  single_call       : one model call, no retries, no behavior summary, no verification
  investigator_only : investigator (with retries + behavior summary), no verification
  full              : investigator + verifier, then a leave-one-out search if nothing was confirmed
  search_only       : no LLM investigator at all; test each change on its own (plain-code baseline)
"""
from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Optional

from .agents.investigator import Investigator
from .agents.verifier import Verifier
from .behavior import summarize_behavior
from .compare import compare
from .config import Config
from .diffing import compute_changes
from .llm import LLM
from .models import Case, Cause, CauseReport, Report
from .report import write_report
from .runner import run_skill
from .structured import StructuredOutputError
from .tracing import RunLogger, traced

MODES = ("single_call", "investigator_only", "full", "search_only")
_STATUS_ORDER = {"confirmed": 0, "unverified": 1, "rejected": 2}
_CONF_ORDER = {"high": 0, "medium": 1, "low": 2}


@traced("skilllens_run")
def run_investigation(old_skill: str, new_skill: str, cases: list[Case], cfg: Config, llm: LLM,
                      mode: str = "full", run_dir: Optional[Path] = None,
                      run_id: Optional[str] = None) -> Report:
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    run_id = run_id or uuid.uuid4().hex[:12]
    run_dir = Path(run_dir) if run_dir else Path(cfg.runs_dir) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    logger = RunLogger(run_dir)
    (run_dir / "config.json").write_text(cfg.model_dump_json(indent=2, exclude={"api_key"}), encoding="utf-8")
    (run_dir / "skill_old.md").write_text(old_skill, encoding="utf-8")
    (run_dir / "skill_new.md").write_text(new_skill, encoding="utf-8")

    t0, calls0, hits0 = time.time(), llm.calls, llm.cache_hits
    notes: list[str] = []

    # 1) Runner: both versions, k repeats per case
    old_rec = run_skill(llm, cfg, old_skill, "old", cases, logger)
    new_rec = run_skill(llm, cfg, new_skill, "new", cases, logger)

    # 2) Comparator
    cmp = compare(old_rec, new_rec, cfg)
    logger.event("comparator", regressed=cmp.regressed_ids, mean_delta=cmp.mean_delta,
                 ci=[cmp.ci_low, cmp.ci_high], old_flaky_rate=cmp.old_flaky_rate)
    if cmp.old_flaky_rate > 0.3:
        notes.append("More than 30% of cases were inconsistent on the OLD version: results are noisy. "
                     "Increase `repeats` or lower the temperature.")

    def finish(report: Report) -> Report:
        report.seconds = time.time() - t0
        report.llm_calls = llm.calls - calls0
        report.cache_hits = llm.cache_hits - hits0
        write_report(report, run_dir)
        return report

    base = dict(run_id=run_id, mode=mode, model=cfg.model, repeats=cfg.repeats,
                regression_detected=cmp.regression_detected, mean_delta=cmp.mean_delta,
                ci_low=cmp.ci_low, ci_high=cmp.ci_high, old_flaky_rate=cmp.old_flaky_rate,
                regressed_case_ids=cmp.regressed_ids, improved_case_ids=cmp.improved_ids,
                case_results=cmp.cases)

    if not cmp.regression_detected:
        notes.append("No case dropped by the configured minimum. Nothing to investigate.")
        return finish(Report(**base, notes=notes))

    changes = compute_changes(old_skill, new_skill)
    if not changes:
        notes.append("The two skill texts are identical, so the flagged drop is noise, not a change.")
        return finish(Report(**base, notes=notes))

    # 3) Behavior analysis (skipped in the single-call baseline)
    behavior = "" if mode in ("single_call", "search_only") else summarize_behavior(old_rec, new_rec, cmp.regressed_ids)
    logger.event("behavior", changes=len(changes))

    case_map = {c.id: c for c in cases}
    change_map = {c.id: c for c in changes}
    regressed_cases = [case_map[i] for i in cmp.regressed_ids]
    verifier = Verifier(llm, cfg, logger)
    reports: list[CauseReport] = []

    # 4) Investigator (not used in search_only mode)
    if mode != "search_only":
        attempts = 1 if mode == "single_call" else cfg.investigator_attempts
        investigator = Investigator(llm, cfg, logger, attempts=attempts)
        found = None
        try:
            found = investigator.investigate(changes, cmp.regressed_ids, case_map, old_rec, new_rec, behavior)
        except StructuredOutputError as exc:
            notes.append(f"Investigator failed to produce valid output: {exc}")
            if mode != "full":
                return finish(Report(**base, behavior_summary=behavior, changes=changes, notes=notes))

        # 5) Verifier: test each proposed cause with a controlled revert
        for cause in (found.causes[: cfg.max_causes] if found else []):
            blamed = [change_map[i] for i in cause.change_ids]
            if mode == "full":
                ver = verifier.verify(cause, old_skill, new_skill, regressed_cases, old_rec)
                reports.append(CauseReport(cause=cause, blamed_changes=blamed, verification=ver,
                                           status="confirmed" if ver.confirmed else "rejected"))
            else:
                reports.append(CauseReport(cause=cause, blamed_changes=blamed, status="unverified"))

    # 6) Leave-one-out search: if nothing is confirmed, test every change on its own.
    #    Plain code, no model guessing. Cheap when the diff is small.
    if mode in ("full", "search_only") and not any(r.status == "confirmed" for r in reports):
        if len(changes) > cfg.max_exhaustive_changes:
            notes.append(f"Too many changes ({len(changes)}) for exhaustive search "
                         f"(limit {cfg.max_exhaustive_changes}).")
        else:
            already = {tuple(r.cause.change_ids) for r in reports}
            logger.event("search.start", changes=len(changes))
            for ch in changes:
                if (ch.id,) in already:
                    continue
                cause = Cause(change_ids=[ch.id], confidence="low", quote=(ch.old_lines + ch.new_lines or [""])[0][:60],
                              description="Found by leave-one-out search: reverting only this change "
                                          "restored the regressed cases.")
                ver = verifier.verify(cause, old_skill, new_skill, regressed_cases, old_rec)
                if ver.confirmed:
                    reports.append(CauseReport(cause=cause, blamed_changes=[ch], verification=ver,
                                               status="confirmed"))
            if any(r.status == "confirmed" for r in reports):
                if mode == "full":
                    notes.append("The investigator's suggestion was rejected; the cause was found by "
                                 "leave-one-out search instead.")

    reports.sort(key=lambda r: (
        _STATUS_ORDER[r.status],
        -(r.verification.recovery_rate if r.verification else 0.0),
        _CONF_ORDER[r.cause.confidence],
    ))
    if mode in ("full", "search_only") and not any(r.status == "confirmed" for r in reports):
        notes.append("Regression detected, but no proposed cause survived verification. Cause not found.")
    return finish(Report(**base, behavior_summary=behavior, changes=changes, causes=reports, notes=notes))
