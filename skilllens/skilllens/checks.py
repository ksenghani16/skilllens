"""Rule-based scoring of model outputs. No LLM judge, so scoring is deterministic."""
from __future__ import annotations

import json
import re
from typing import Any, Optional

from .models import Check

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.I)


def strict_json(text: str) -> tuple[bool, Any]:
    """True only if the WHOLE output is JSON (no prose before/after)."""
    try:
        return True, json.loads(text.strip())
    except (ValueError, TypeError):
        return False, None


def lenient_json(text: str) -> Optional[Any]:
    """Find a JSON object even if the model wrapped it in prose or a code fence."""
    ok, val = strict_json(text)
    if ok:
        return val
    try:
        return json.loads(_FENCE.sub("", text.strip()))
    except ValueError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except ValueError:
            return None
    return None


def _get_field(obj: Any, path: str) -> tuple[bool, Any]:
    cur = obj
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return False, None
    return True, cur


def _passes(output: str, check: Check) -> bool:
    t = check.type
    if t == "json_valid":
        return strict_json(output)[0]
    if t == "contains":
        return str(check.expected) in output
    if t == "not_contains":
        return str(check.expected) not in output
    if t == "regex":
        return re.search(str(check.expected), output) is not None
    obj = lenient_json(output)
    if obj is None or not check.field:
        return False
    found, value = _get_field(obj, check.field)
    if not found:
        return False
    if t == "json_field_equals":
        return value == check.expected
    if t == "json_field_close":
        try:
            return abs(float(value) - float(check.expected)) <= check.rel_tol * abs(float(check.expected))
        except (TypeError, ValueError):
            return False
    return False


def run_checks(output: str, checks: list[Check]) -> list[str]:
    """Return the labels of the checks that FAILED (empty list = case passed)."""
    return [c.label() for c in checks if not _passes(output, c)]
