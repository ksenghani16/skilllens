import json
from pathlib import Path

from fastapi.testclient import TestClient

from skilllens.api import create_app
from skilllens.config import Config
from skilllens.evaluate import load_cases
from skilllens.mock import MockLLM
from skilllens.pipeline import run_investigation

ROOT = Path(__file__).resolve().parent.parent
EX = ROOT / "examples"
V1 = (EX / "sentiment_v1.md").read_text()
CASES = load_cases(EX / "sentiment_cases.json")


def cfg(tmp_path):
    return Config(bootstrap_samples=200, cache_dir=str(tmp_path / "c"), runs_dir=str(tmp_path / "r"))


def run(name, tmp_path, mode="full"):
    new = (EX / name).read_text()
    return run_investigation(V1, new, CASES, cfg(tmp_path), MockLLM(), mode=mode, run_dir=tmp_path / name)


def test_changed_rule_is_found(tmp_path):
    rep = run("sentiment_v2_rule_changed.md", tmp_path)
    assert rep.regression_detected and len(rep.regressed_case_ids) == 4
    top = rep.top_cause()
    assert top.status == "confirmed" and any("Complaints" in ch.text for ch in top.blamed_changes)


def test_removed_format_rule_is_found(tmp_path):
    rep = run("sentiment_v2_format_removed.md", tmp_path)
    assert rep.regression_detected
    top = rep.top_cause()
    assert top.status == "confirmed" and any("lowercase" in ch.text for ch in top.blamed_changes)


def test_harmless_rewording_is_not_flagged(tmp_path):
    assert not run("sentiment_v2_harmless.md", tmp_path).regression_detected


def test_report_has_per_case_results(tmp_path):
    rep = run("sentiment_v2_rule_changed.md", tmp_path)
    assert len(rep.case_results) == len(CASES)


def test_home_page_events_and_mock_flag(tmp_path, monkeypatch):
    monkeypatch.setenv("SKILLLENS_API_KEY", "k")

    def real_factory(_cfg):
        raise AssertionError("mock mode must not create a real model client")

    c = TestClient(create_app(Config(runs_dir=str(tmp_path / "runs"), bootstrap_samples=100), real_factory))
    page = c.get("/")
    assert page.status_code == 200 and "SkillLens" in page.text
    body = {"old_skill": V1, "new_skill": (EX / "sentiment_v2_rule_changed.md").read_text(),
            "cases": [json.loads(x.model_dump_json()) for x in CASES], "mock": True}
    h = {"X-API-Key": "k"}
    run_id = c.post("/investigate", headers=h, json=body).json()["run_id"]
    assert c.get(f"/runs/{run_id}", headers=h).json()["state"] == "done"
    events = c.get(f"/runs/{run_id}/events", headers=h).json()["events"]
    names = {e["component"] for e in events}
    assert {"runner.start", "runner.progress", "comparator", "behavior", "investigator.start", "verifier.result"} <= names
    assert c.get(f"/runs/{run_id}/events").status_code == 401
