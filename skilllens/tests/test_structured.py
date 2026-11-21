import pytest

from skilllens.models import InvestigatorOutput
from skilllens.structured import StructuredOutputError, parse_structured


class Scripted:
    """Fake LLM that returns scripted replies one after another."""
    calls = 0
    cache_hits = 0

    def __init__(self, replies):
        self.replies = list(replies)
        self.seen = []

    def complete(self, messages, *, temperature, seed, json_mode=False):
        self.seen.append(messages)
        return self.replies.pop(0)


GOOD = '{"causes": [{"change_ids": ["c1"], "description": "rule removed", "confidence": "high"}]}'


def test_retries_with_error_feedback_then_succeeds():
    llm = Scripted(["not json at all", GOOD])
    out = parse_structured(llm, [{"role": "user", "content": "go"}], InvestigatorOutput, attempts=3, seed=0)
    assert out.causes[0].change_ids == ["c1"]
    assert "rejected" in llm.seen[1][-1]["content"]      # the retry told the model what was wrong


def test_validator_rejects_unknown_ids():
    def validate(o):
        if "c9" in o.causes[0].change_ids:
            raise ValueError("unknown id")
    bad = GOOD.replace("c1", "c9")
    llm = Scripted([bad, GOOD])
    out = parse_structured(llm, [{"role": "user", "content": "go"}], InvestigatorOutput,
                           attempts=2, seed=0, validate=validate)
    assert out.causes[0].change_ids == ["c1"]


def test_gives_up_after_attempts():
    llm = Scripted(["nope", "nope"])
    with pytest.raises(StructuredOutputError):
        parse_structured(llm, [{"role": "user", "content": "go"}], InvestigatorOutput, attempts=2, seed=0)
