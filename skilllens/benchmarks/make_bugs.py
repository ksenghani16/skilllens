"""Generate the injected-bug benchmark from the good base skill.

Every "new" skill gets the same harmless edits (distractors), plus exactly ONE injected bug
(except the control, which has none). Add more bug functions to grow the benchmark to 20-30.

Run from the project root:  python benchmarks/make_bugs.py
"""
import json
from pathlib import Path

ROOT = Path(__file__).parent
BASE = ROOT / "skills" / "unit_normalizer_v1.md"
CASES = "benchmarks/cases/unit_normalizer_cases.json"


def distractors(text: str) -> str:
    """Harmless edits: rewording, a renamed header, an extra style bullet."""
    text = text.replace("You convert a quantity into SI base units and report it as JSON.",
                        "Your job is to convert a quantity into SI base units and report it as JSON.")
    text = text.replace("## Conversion rules", "## Rules")
    text = text.replace("## Style\n", "## Style\n- Keep the reply short.\n")
    return text


def drop_line(text: str, needle: str) -> str:
    return "".join(l for l in text.splitlines(keepends=True) if needle not in l)


BUGS = {
    "b1_remove_fahrenheit_rule": (lambda t: drop_line(t, "(F):"), "(F)"),
    "b2_wrong_pound_factor": (lambda t: t.replace("multiply by 0.45359237", "multiply by 2.2046"), "(lb)"),
    "b3_drop_json_only": (lambda t: t.replace("Return only the JSON object, with no other text. Use exactly this shape:",
                                              "Return the JSON object. Use exactly this shape:"), "Return only the JSON"),
    "b4_remove_unsupported_rule": (lambda t: drop_line(t, "unsupported unit"), "unsupported unit"),
}


def main() -> None:
    base = BASE.read_text(encoding="utf-8")
    out_dir = ROOT / "skills" / "injected"
    out_dir.mkdir(exist_ok=True)
    manifest = []

    (out_dir / "control_distractors_only.md").write_text(distractors(base), encoding="utf-8")
    manifest.append({"id": "control_distractors_only", "old_skill": "benchmarks/skills/unit_normalizer_v1.md",
                     "new_skill": "benchmarks/skills/injected/control_distractors_only.md",
                     "cases": CASES, "bug_marker": None, "expects_regression": False})

    for bug_id, (fn, marker) in BUGS.items():
        (out_dir / f"{bug_id}.md").write_text(fn(distractors(base)), encoding="utf-8")
        manifest.append({"id": bug_id, "old_skill": "benchmarks/skills/unit_normalizer_v1.md",
                         "new_skill": f"benchmarks/skills/injected/{bug_id}.md",
                         "cases": CASES, "bug_marker": marker, "expects_regression": True})

    (ROOT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"wrote {len(manifest)} benchmark entries")


if __name__ == "__main__":
    main()
