"""Render a Report as JSON and as readable Markdown."""
from __future__ import annotations

from pathlib import Path

from .models import Report


def to_markdown(rep: Report) -> str:
    out = [f"# SkillLens report `{rep.run_id}`", ""]
    out.append(f"- mode: **{rep.mode}**, model: `{rep.model}`, repeats per case: {rep.repeats}")
    out.append(f"- model calls: {rep.llm_calls} (cache hits: {rep.cache_hits}), time: {rep.seconds:.1f}s")
    out.append("")
    if not rep.regression_detected:
        out.append("## Result: no regression detected")
    else:
        out.append(f"## Result: regression detected on {len(rep.regressed_case_ids)} case(s)")
        out.append(f"- regressed cases: {', '.join(rep.regressed_case_ids)}")
    out.append(f"- mean pass-rate change: {rep.mean_delta:+.3f} (95% bootstrap interval "
               f"{rep.ci_low:+.3f} to {rep.ci_high:+.3f})")
    out.append(f"- share of cases where the OLD version was inconsistent: {rep.old_flaky_rate:.0%}")
    if rep.improved_case_ids:
        out.append(f"- improved cases: {', '.join(rep.improved_case_ids)}")
    if rep.behavior_summary:
        out += ["", "## How outputs changed", "```", rep.behavior_summary, "```"]
    if rep.causes:
        out += ["", "## Causes"]
        for i, c in enumerate(rep.causes, 1):
            out.append(f"### {i}. {c.status.upper()} - changes {', '.join(c.cause.change_ids)} "
                       f"(model confidence: {c.cause.confidence})")
            out.append(c.cause.description)
            for ch in c.blamed_changes:
                out.append(f"- `{ch.id}` removed: {' / '.join(ch.old_lines) or '(nothing)'}")
                out.append(f"  `{ch.id}` added: {' / '.join(ch.new_lines) or '(nothing)'}")
            if c.verification:
                v = c.verification
                out.append(f"- verification: {len(v.recovered_case_ids)} of {len(v.tested_case_ids)} regressed "
                           f"cases recovered when this change was reverted ({v.recovery_rate:.0%})")
    if rep.notes:
        out += ["", "## Notes"] + [f"- {n}" for n in rep.notes]
    return "\n".join(out) + "\n"


def write_report(rep: Report, run_dir: Path) -> None:
    (run_dir / "report.json").write_text(rep.model_dump_json(indent=2), encoding="utf-8")
    (run_dir / "report.md").write_text(to_markdown(rep), encoding="utf-8")
