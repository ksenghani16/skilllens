from pathlib import Path

from skilllens.config import Config
from skilllens.evaluate import load_cases
from skilllens.mock import MockLLM
from skilllens.pipeline import run_investigation

ROOT = Path(__file__).resolve().parent.parent
OLD = (ROOT / "benchmarks/skills/unit_normalizer_v1.md").read_text()
CASES = load_cases(ROOT / "benchmarks/cases/unit_normalizer_cases.json")


def run(name, mode, tmp_path):
    new = (ROOT / f"benchmarks/skills/injected/{name}.md").read_text()
    cfg = Config(bootstrap_samples=200, cache_dir=str(tmp_path / "c"), runs_dir=str(tmp_path / "r"))
    return run_investigation(OLD, new, CASES, cfg, MockLLM(), mode=mode, run_dir=tmp_path / name)


def test_control_has_no_false_alarm(tmp_path):
    rep = run("control_distractors_only", "full", tmp_path)
    assert not rep.regression_detected and rep.causes == []


def test_fahrenheit_bug_is_found_and_verified(tmp_path):
    rep = run("b1_remove_fahrenheit_rule", "full", tmp_path)
    assert rep.regression_detected
    assert set(rep.regressed_case_ids) == {"fahrenheit_72", "fahrenheit_32"}
    top = rep.top_cause()
    assert top.status == "confirmed" and top.verification.recovery_rate == 1.0
    assert any("(F)" in ch.text for ch in top.blamed_changes)


def test_all_injected_bugs_found(tmp_path):
    for name, marker in [("b2_wrong_pound_factor", "(lb)"), ("b3_drop_json_only", "Return only the JSON"),
                         ("b4_remove_unsupported_rule", "unsupported unit")]:
        rep = run(name, "full", tmp_path)
        top = rep.top_cause()
        assert rep.regression_detected, name
        assert top is not None and any(marker in ch.text for ch in top.blamed_changes), name


def test_modes_differ_in_verification(tmp_path):
    full = run("b1_remove_fahrenheit_rule", "full", tmp_path)
    inv = run("b1_remove_fahrenheit_rule", "investigator_only", tmp_path)
    assert full.causes[0].verification is not None
    assert inv.causes[0].status == "unverified" and inv.causes[0].verification is None


def test_run_folder_contains_evidence(tmp_path):
    run("b1_remove_fahrenheit_rule", "full", tmp_path)
    folder = tmp_path / "b1_remove_fahrenheit_rule"
    for name in ["report.json", "report.md", "events.jsonl", "config.json", "skill_old.md", "skill_new.md"]:
        assert (folder / name).exists(), name
    assert "api_key" not in (folder / "config.json").read_text()     # secrets never written to disk
