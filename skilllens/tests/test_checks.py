from skilllens.checks import lenient_json, run_checks, strict_json
from skilllens.models import Check


def test_strict_vs_lenient_json():
    prose = 'Sure! Here you go:\n{"value": 2}'
    assert strict_json(prose)[0] is False
    assert lenient_json(prose) == {"value": 2}
    assert strict_json('{"value": 2}')[0] is True


def test_checks_pass_and_fail():
    checks = [
        Check(type="json_valid"),
        Check(type="json_field_close", field="value", expected=100, rel_tol=0.01),
        Check(type="json_field_equals", field="unit", expected="m"),
    ]
    assert run_checks('{"value": 100.5, "unit": "m"}', checks) == []
    failed = run_checks('{"value": 150, "unit": "kg"}', checks)
    assert failed == ["json_field_close:value", "json_field_equals:unit"]
    assert "json_valid" in run_checks("not json", checks)


def test_text_checks():
    assert run_checks("hello world", [Check(type="contains", expected="world")]) == []
    assert run_checks("hello", [Check(type="not_contains", expected="hello")]) == ["not_contains"]
    assert run_checks("abc123", [Check(type="regex", expected=r"\d+")]) == []
