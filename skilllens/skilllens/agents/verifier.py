"""Verifier: tests a proposed cause with a controlled experiment.

It builds a candidate skill = NEW version with only the blamed change(s) put back to the OLD text,
re-runs only the regressed cases, and checks whether they recover. The experiment is plain code;
the LLM only supplies the model outputs being scored.
"""
from __future__ import annotations

from ..compare import pass_rates
from ..config import Config
from ..diffing import apply_with_reverts
from ..llm import LLM
from ..models import Case, Cause, RunRecord, Verification
from ..runner import run_skill
from ..tracing import RunLogger, traced


class Verifier:
    def __init__(self, llm: LLM, cfg: Config, logger: RunLogger):
        self.llm, self.cfg, self.logger = llm, cfg, logger

    @traced("verifier")
    def verify(self, cause: Cause, old_skill: str, new_skill: str, regressed_cases: list[Case],
               old_records: list[RunRecord]) -> Verification:
        candidate = apply_with_reverts(old_skill, new_skill, set(cause.change_ids))
        with self.logger.span("verifier", change_ids=cause.change_ids, cases=len(regressed_cases)):
            cand_records = run_skill(self.llm, self.cfg, candidate, "candidate", regressed_cases, self.logger)
        old_rates, cand_rates = pass_rates(old_records), pass_rates(cand_records)

        recovered = [
            c.id for c in regressed_cases
            if (cand_rates.get(c.id, 0.0) - old_rates.get(c.id, 0.0)) > -self.cfg.min_drop + 1e-9
        ]
        rate = len(recovered) / len(regressed_cases) if regressed_cases else 0.0
        result = Verification(
            change_ids=cause.change_ids, tested_case_ids=[c.id for c in regressed_cases],
            recovered_case_ids=recovered, recovery_rate=rate,
            confirmed=rate >= self.cfg.recovery_threshold,
        )
        self.logger.event("verifier.result", **result.model_dump())
        return result
