"""Tests for the failure seen on a real 7B model: the investigator described the right edit
but named the wrong change ids."""
import json
from pathlib import Path

from skilllens.agents.investigator import Investigator
from skilllens.config import Config
from skilllens.diffing import compute_changes
from skilllens.evaluate import load_cases
from skilllens.mock import MockLLM
from skilllens.models import RunRecord
from skilllens.pipeline import run_investigation
from skilllens.tracing import RunLogger

ROOT = Path(__file__).resolve().parent.parent
OLD = (ROOT / "benchmarks/skills/unit_normalizer_v1.md").read_text()
NEW = (ROOT / "benchmarks/skills/injected/b1_remove_fahrenheit_rule.md").read_text()
CASES = load_cases(ROOT / "benchmarks/cases/unit_normalizer_cases.json")


def cfg(tmp_path):
    return Config(bootstrap_samples=200, cache_dir=str(tmp_path / "c"), runs_dir=str(tmp_path / "r"))


def fahrenheit_change():
    return next(c for c in compute_changes(OLD, NEW) if "Fahrenheit" in c.text)


class MislabelingThenFixed(MockLLM):
    """First reply: quote is from the Fahrenheit change but ids point elsewhere. Second reply: fixed."""
    def __init__(self):
        super().__init__()
        self.replies = 0

    def _investigate(self, user):
        self.replies += 1
        quote = "Fahrenheit (F): K = (F - 32)"
        ids = ["c1"] if self.replies == 1 else [fahrenheit_change().id]
        return json.dumps({"causes": [{"change_ids": ids, "quote": quote,
                                       "description": "The Fahrenheit rule was removed.", "confidence": "high"}]})


def test_quote_mismatch_is_rejected_then_corrected(tmp_path):
    changes = compute_changes(OLD, NEW)
    rec = lambda label, passed: [RunRecord(label=label, case_id="fahrenheit_72", repeat=0,
                                           output="x", passed=passed, failed_checks=[] if passed else ["json_valid"])]
    llm = MislabelingThenFixed()
    inv = Investigator(llm, cfg(tmp_path), RunLogger(None), attempts=3)
    out = inv.investigate(changes, ["fahrenheit_72"], {c.id: c for c in CASES}, rec("old", True), rec("new", False), "")
    assert llm.replies == 2                                   # first answer was rejected by the code check
    assert out.causes[0].change_ids == [fahrenheit_change().id]


class SelfConsistentButWrong(MockLLM):
    """Blames a harmless edit (c1) with a matching quote, so only the verifier can catch it."""
    def _investigate(self, user):
        return json.dumps({"causes": [{"change_ids": ["c1"], "quote": "Your job is to convert",
                                       "description": "Rewording broke it.", "confidence": "high"}]})


def test_wrong_cause_is_rejected_and_leave_one_out_finds_real_cause(tmp_path):
    rep = run_investigation(OLD, NEW, CASES, cfg(tmp_path), SelfConsistentButWrong(), mode="full",
                            run_dir=tmp_path / "run")
    top = rep.top_cause()
    assert top is not None and top.status == "confirmed"
    assert top.blamed_changes[0].id == fahrenheit_change().id
    assert any("leave-one-out" in n for n in rep.notes)
    assert rep.causes[-1].status == "rejected" or any(c.status == "rejected" for c in rep.causes)


def test_investigator_only_has_no_safety_net(tmp_path):
    rep = run_investigation(OLD, NEW, CASES, cfg(tmp_path), SelfConsistentButWrong(), mode="investigator_only",
                            run_dir=tmp_path / "run2")
    assert rep.top_cause().blamed_changes[0].id == "c1"       # confidently wrong, nothing catches it


def test_search_only_needs_no_investigator(tmp_path):
    llm = MockLLM()
    rep = run_investigation(OLD, NEW, CASES, cfg(tmp_path), llm, mode="search_only", run_dir=tmp_path / "run3")
    top = rep.top_cause()
    assert top.status == "confirmed" and "Fahrenheit" in top.blamed_changes[0].text
