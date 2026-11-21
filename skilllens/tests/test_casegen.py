import json
from pathlib import Path

from fastapi.testclient import TestClient

from skilllens.api import create_app
from skilllens.casegen import checks_from_output, generate_cases
from skilllens.checks import run_checks
from skilllens.config import Config
from skilllens.diffing import compute_changes
from skilllens.mock import MockLLM
from skilllens.models import Case
from skilllens.pipeline import run_investigation

ROOT = Path(__file__).resolve().parent.parent
EX = ROOT / "examples"
V1 = (EX / "sentiment_v1.md").read_text()


def cfg(tmp_path):
    return Config(bootstrap_samples=200, cache_dir=str(tmp_path / "c"), runs_dir=str(tmp_path / "r"))


def test_checks_from_json_and_text_outputs():
    from skilllens.models import Check
    checks = [Check(**c) for c in checks_from_output('{"team": "billing", "priority": "high"}')]
    assert run_checks('{"priority":"high","team":"billing"}', checks) == []        # spacing/order do not matter
    assert run_checks('{"team": "sales", "priority": "high"}', checks) == ["json_field_equals:team"]
    text = [Check(**c) for c in checks_from_output("positive")]
    assert run_checks("positive", text) == [] and run_checks("Positive.", text) != []


def test_generated_cases_catch_a_real_regression(tmp_path):
    c = cfg(tmp_path)
    out = generate_cases(MockLLM(), c, V1, n=10)
    assert len(out["cases"]) == 10 and len(out["expected"]) == 10
    cases = [Case.model_validate(x) for x in out["cases"]]
    new = (EX / "sentiment_v2_rule_changed.md").read_text()
    rep = run_investigation(V1, new, cases, c, MockLLM(), mode="full", run_dir=tmp_path / "run")
    assert rep.regression_detected and rep.top_cause().status == "confirmed"
    harmless = run_investigation(V1, (EX / "sentiment_v2_harmless.md").read_text(), cases, c, MockLLM(),
                                 mode="full", run_dir=tmp_path / "run2")
    assert not harmless.regression_detected


def test_unstable_inputs_are_dropped(tmp_path):
    class Flaky(MockLLM):
        def _convert(self, skill, user):
            return f"answer {self.calls}" if "Thank" in user or "love" in user else super()._convert(skill, user)
    out = generate_cases(Flaky(), cfg(tmp_path), V1, n=10)
    assert out["dropped_unstable"] >= 1
    assert all("answer" not in e for e in out["expected"])


def test_hard_example_has_five_separate_changes():
    ch = compute_changes((EX / "ticket_router_v1.md").read_text(), (EX / "ticket_router_v2.md").read_text())
    assert [c.id for c in ch] == ["c1", "c2", "c3", "c4", "c5"]
    assert any("named last" in c.text for c in ch) and any("medium priority" in c.text for c in ch)


def test_generate_endpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("SKILLLENS_API_KEY", "k")
    c = TestClient(create_app(Config(runs_dir=str(tmp_path / "r"), cache_dir=str(tmp_path / "c"))))
    h = {"X-API-Key": "k"}
    assert c.post("/generate-cases", json={"skill": V1, "mock": True}).status_code == 401
    r = c.post("/generate-cases", headers=h, json={"skill": V1, "n": 6, "mock": True})
    assert r.status_code == 200 and len(r.json()["cases"]) == 6


def test_echoed_answer_words_are_dropped_and_warned(tmp_path):
    class Echo(MockLLM):
        def _propose(self, user):
            return json.dumps({"inputs": ["positive", "negative", "neutral", "I love it", "Worst ever"]})

        def _convert(self, skill, user):
            return user.strip().lower() if user in ("positive", "negative", "neutral") else super()._convert(skill, user)

    out = generate_cases(Echo(), cfg(tmp_path), V1, n=10)
    assert [c["input"] for c in out["cases"]] == ["I love it", "Worst ever"]
    assert any("repeated an answer word" in w for w in out["warnings"])
    assert any("Only 2 usable" in w for w in out["warnings"])


def test_example_message_reaches_the_prompt(tmp_path):
    seen = []

    class Spy(MockLLM):
        def _propose(self, user):
            seen.append(user)
            return super()._propose(user)

    generate_cases(Spy(), cfg(tmp_path), V1, n=5, example="days=12 condition=unopened")
    assert "days=12 condition=unopened" in seen[0]
