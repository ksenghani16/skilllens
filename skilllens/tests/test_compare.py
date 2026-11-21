from skilllens.compare import compare, pass_rates
from skilllens.config import Config
from skilllens.models import RunRecord


def recs(label, case_id, outcomes):
    return [RunRecord(label=label, case_id=case_id, repeat=i, output="", passed=p)
            for i, p in enumerate(outcomes)]


def test_clear_regression_is_flagged():
    cfg = Config(bootstrap_samples=200)
    old = recs("old", "a", [True] * 3) + recs("old", "b", [True] * 3)
    new = recs("new", "a", [False] * 3) + recs("new", "b", [True] * 3)
    res = compare(old, new, cfg)
    assert res.regressed_ids == ["a"] and res.regression_detected


def test_single_flip_is_treated_as_noise():
    cfg = Config(bootstrap_samples=200)             # min_drop 0.5 -> one flip of three (0.33) is ignored
    old = recs("old", "a", [True] * 3)
    new = recs("new", "a", [True, True, False])
    res = compare(old, new, cfg)
    assert not res.regression_detected


def test_flaky_baseline_is_marked():
    cfg = Config(bootstrap_samples=200)
    old = recs("old", "a", [True, False, True])
    new = recs("new", "a", [False, False, False])
    res = compare(old, new, cfg)
    assert res.cases[0].flaky and res.old_flaky_rate == 1.0


def test_pass_rates():
    assert pass_rates(recs("x", "a", [True, False])) == {"a": 0.5}
