"""Data formats. Every message between components is one of these Pydantic models.

Defining them first keeps the rest of the code simple: if data does not fit a
model, validation fails loudly instead of silently passing bad data along.
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

# ---------- test cases ----------


class Check(BaseModel):
    """One rule-based check applied to a model output."""

    type: Literal[
        "json_valid",        # whole output is strictly valid JSON (no extra prose)
        "contains",          # output contains `expected` (text)
        "not_contains",      # output does not contain `expected`
        "regex",             # output matches regex `expected`
        "json_field_equals", # JSON field `field` equals `expected`
        "json_field_close",  # JSON field `field` is within rel_tol of number `expected`
    ]
    field: Optional[str] = None      # dotted path, e.g. "value" or "result.unit"
    expected: Any = None
    rel_tol: float = 0.01

    def label(self) -> str:
        return f"{self.type}:{self.field}" if self.field else self.type


class Case(BaseModel):
    id: str
    input: str
    checks: list[Check] = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)


class RunRecord(BaseModel):
    """The result of running one skill version on one case once."""

    label: str            # "old", "new" or "candidate"
    case_id: str
    repeat: int
    output: str
    passed: bool
    failed_checks: list[str] = Field(default_factory=list)


# ---------- comparison ----------


class CaseComparison(BaseModel):
    case_id: str
    old_pass_rate: float
    new_pass_rate: float
    delta: float
    status: Literal["regressed", "improved", "unchanged"]
    flaky: bool = False   # the OLD version was inconsistent on this case (noisy baseline)


class ComparisonResult(BaseModel):
    cases: list[CaseComparison]
    mean_delta: float
    ci_low: float
    ci_high: float
    old_flaky_rate: float
    regression_detected: bool

    @property
    def regressed_ids(self) -> list[str]:
        return [c.case_id for c in self.cases if c.status == "regressed"]

    @property
    def improved_ids(self) -> list[str]:
        return [c.case_id for c in self.cases if c.status == "improved"]


# ---------- diff of two skill versions ----------


class Change(BaseModel):
    """One edited region between the old and new skill text."""

    id: str
    old_lines: list[str]
    new_lines: list[str]
    old_start: int
    new_start: int

    @property
    def text(self) -> str:
        return "\n".join(self.old_lines + self.new_lines)


# ---------- agent outputs ----------


class Cause(BaseModel):
    change_ids: list[str] = Field(min_length=1, max_length=5)
    description: str = Field(min_length=3)
    confidence: Literal["low", "medium", "high"] = "medium"
    quote: str = ""   # exact phrase copied from the blamed change; code checks it matches the ids


class InvestigatorOutput(BaseModel):
    causes: list[Cause] = Field(min_length=1, max_length=5)


class Verification(BaseModel):
    change_ids: list[str]
    tested_case_ids: list[str]
    recovered_case_ids: list[str]
    recovery_rate: float
    confirmed: bool


class CauseReport(BaseModel):
    cause: Cause
    blamed_changes: list[Change]
    verification: Optional[Verification] = None
    status: Literal["confirmed", "rejected", "unverified"]


# ---------- final report ----------


class Report(BaseModel):
    run_id: str
    mode: str
    model: str
    repeats: int
    regression_detected: bool
    mean_delta: float
    ci_low: float
    ci_high: float
    old_flaky_rate: float
    regressed_case_ids: list[str]
    improved_case_ids: list[str]
    case_results: list[CaseComparison] = Field(default_factory=list)
    behavior_summary: str = ""
    changes: list[Change] = Field(default_factory=list)
    causes: list[CauseReport] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    seconds: float = 0.0
    llm_calls: int = 0
    cache_hits: int = 0

    def top_cause(self) -> Optional[CauseReport]:
        """The best cause, or None. A cause the verifier rejected is never 'top'."""
        for c in self.causes:
            if c.status != "rejected":
                return c
        return None
