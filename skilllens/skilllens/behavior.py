"""Behavior analysis: describe HOW outputs changed on the regressed cases. Plain code."""
from __future__ import annotations

from collections import Counter

from .checks import strict_json
from .models import RunRecord


def summarize_behavior(old: list[RunRecord], new: list[RunRecord], regressed_ids: list[str]) -> str:
    ids = set(regressed_ids)
    o = [r for r in old if r.case_id in ids]
    n = [r for r in new if r.case_id in ids]
    if not o or not n:
        return "No regressed cases to describe."

    def avg_len(rs): return sum(len(r.output) for r in rs) / len(rs)
    def json_rate(rs): return sum(strict_json(r.output)[0] for r in rs) / len(rs)
    def failed(rs):
        c = Counter(f for r in rs for f in r.failed_checks)
        return dict(c.most_common(4))

    lines = [
        f"Regressed cases: {len(ids)}",
        f"Average output length (old -> new): {avg_len(o):.0f} -> {avg_len(n):.0f} characters",
        f"Outputs that are pure JSON (old -> new): {json_rate(o):.0%} -> {json_rate(n):.0%}",
        f"Most common failed checks, old version: {failed(o) or 'none'}",
        f"Most common failed checks, new version: {failed(n) or 'none'}",
    ]
    return "\n".join(lines)
