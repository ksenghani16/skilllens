"""Runner: runs one skill version on every case, `repeats` times. Plain code, no agent."""
from __future__ import annotations

from .checks import run_checks
from .config import Config
from .llm import LLM
from .models import Case, RunRecord
from .tracing import RunLogger


def run_skill(llm: LLM, cfg: Config, skill_text: str, label: str, cases: list[Case],
              logger: RunLogger, repeats: int | None = None) -> list[RunRecord]:
    repeats = repeats or cfg.repeats
    records: list[RunRecord] = []
    with logger.span("runner", label=label, cases=len(cases), repeats=repeats):
        for done, case in enumerate(cases, 1):
            # The skill is the system prompt; the case input is the user message.
            messages = [
                {"role": "system", "content": skill_text},
                {"role": "user", "content": case.input},
            ]
            for r in range(repeats):
                # Different seed per repeat -> repeats can differ; same seed on rerun -> cached.
                output = llm.complete(messages, temperature=cfg.temperature, seed=cfg.seed + r)
                failed = run_checks(output, case.checks)
                records.append(RunRecord(label=label, case_id=case.id, repeat=r,
                                         output=output, passed=not failed, failed_checks=failed))
            logger.event("runner.progress", label=label, done=done, total=len(cases))
    return records
