"""Ask the model for JSON, validate it, and retry with the error message if it is wrong."""
from __future__ import annotations

from typing import Callable, Optional, Type, TypeVar

from pydantic import BaseModel

from .checks import lenient_json
from .llm import LLM
from .tracing import RunLogger

T = TypeVar("T", bound=BaseModel)


class StructuredOutputError(RuntimeError):
    pass


def parse_structured(llm: LLM, messages: list[dict], model_cls: Type[T], *, attempts: int, seed: int,
                     validate: Optional[Callable[[T], None]] = None,
                     logger: Optional[RunLogger] = None, component: str = "structured") -> T:
    msgs = list(messages)
    last_error = ""
    for i in range(max(1, attempts)):
        raw = llm.complete(msgs, temperature=0.0, seed=seed + i, json_mode=True)
        try:
            obj = lenient_json(raw)
            if obj is None:
                raise ValueError("the reply was not valid JSON")
            parsed = model_cls.model_validate(obj)   # pydantic's ValidationError is a ValueError
            if validate:
                validate(parsed)
            return parsed
        except ValueError as exc:
            last_error = str(exc)[:400]
            if logger:
                logger.event(f"{component}.rejected", attempt=i + 1, error=last_error)
            msgs = msgs + [
                {"role": "assistant", "content": raw},
                {"role": "user", "content": f"Your reply was rejected: {last_error}\n"
                                            "Reply again with ONLY a corrected JSON object."},
            ]
    raise StructuredOutputError(f"no valid output after {attempts} attempts: {last_error}")
