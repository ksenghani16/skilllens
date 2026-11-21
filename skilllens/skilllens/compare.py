"""Comparator: noise-aware comparison of old vs new pass rates. Plain code + statistics."""
from __future__ import annotations

import random
from collections import defaultdict

from .config import Config
from .models import CaseComparison, ComparisonResult, RunRecord


def pass_rates(records: list[RunRecord]) -> dict[str, float]:
    by_case: dict[str, list[bool]] = defaultdict(list)
    for r in records:
        by_case[r.case_id].append(r.passed)
    return {cid: sum(v) / len(v) for cid, v in by_case.items()}


def paired_bootstrap(deltas: list[float], samples: int, seed: int) -> tuple[float, float, float]:
    """Mean of per-case deltas with a 95% bootstrap interval (resampling cases)."""
    if not deltas:
        return 0.0, 0.0, 0.0
    rng = random.Random(seed)
    n = len(deltas)
    means = sorted(sum(deltas[rng.randrange(n)] for _ in range(n)) / n for _ in range(samples))
    lo = means[int(0.025 * samples)]
    hi = means[min(samples - 1, int(0.975 * samples))]
    return sum(deltas) / n, lo, hi


def compare(old: list[RunRecord], new: list[RunRecord], cfg: Config) -> ComparisonResult:
    old_rates, new_rates = pass_rates(old), pass_rates(new)
    cases: list[CaseComparison] = []
    for cid in old_rates:
        o, n = old_rates[cid], new_rates.get(cid, 0.0)
        delta = n - o
        if delta <= -cfg.min_drop + 1e-9:
            status = "regressed"
        elif delta >= cfg.min_drop - 1e-9:
            status = "improved"
        else:
            status = "unchanged"
        cases.append(CaseComparison(case_id=cid, old_pass_rate=o, new_pass_rate=n, delta=delta,
                                    status=status, flaky=0.0 < o < 1.0))
    mean, lo, hi = paired_bootstrap([c.delta for c in cases], cfg.bootstrap_samples, cfg.seed)
    flaky_rate = sum(c.flaky for c in cases) / len(cases) if cases else 0.0
    return ComparisonResult(
        cases=cases, mean_delta=mean, ci_low=lo, ci_high=hi, old_flaky_rate=flaky_rate,
        regression_detected=any(c.status == "regressed" for c in cases),
    )
