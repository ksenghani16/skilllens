"""Model client: talks to any OpenAI-compatible endpoint (Ollama, NVIDIA, ...).

Production features in one place:
  * timeouts            - a hung model cannot hang the run
  * retries + backoff   - only for transient errors (timeouts, 429, 5xx)
  * on-disk cache       - same request -> same answer; makes reruns instant and reproducible
  * call counters       - so every report can say how many model calls it used
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Protocol

import httpx
from tenacity import Retrying, retry_if_exception, stop_after_attempt, wait_exponential

from .config import Config


class LLM(Protocol):
    calls: int
    cache_hits: int

    def complete(self, messages: list[dict], *, temperature: float, seed: int,
                 json_mode: bool = False) -> str: ...


class LLMError(RuntimeError):
    pass


class EmptyResponse(LLMError):
    """The model returned nothing. Treated as transient (worth a retry)."""


def _is_transient(exc: BaseException) -> bool:
    if isinstance(exc, (httpx.TransportError, httpx.TimeoutException, EmptyResponse)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        return code == 429 or code >= 500
    return False


class OpenAICompatLLM:
    def __init__(self, cfg: Config, client: httpx.Client | None = None, use_cache: bool = True):
        self.cfg = cfg
        self.client = client or httpx.Client(timeout=cfg.timeout_s)
        self.use_cache = use_cache
        self.cache_dir = Path(cfg.cache_dir)
        if use_cache:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.calls = 0        # real network calls
        self.cache_hits = 0

    def complete(self, messages: list[dict], *, temperature: float, seed: int,
                 json_mode: bool = False) -> str:
        payload = {
            "model": self.cfg.model,
            "messages": messages,
            "temperature": temperature,
            "seed": seed,
            "stream": False,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        key = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
        cache_file = self.cache_dir / f"{key}.json"
        if self.use_cache and cache_file.exists():
            self.cache_hits += 1
            return json.loads(cache_file.read_text(encoding="utf-8"))["output"]

        text = ""
        for attempt in Retrying(
            stop=stop_after_attempt(self.cfg.max_retries),
            wait=wait_exponential(multiplier=self.cfg.retry_wait_s, max=10),
            retry=retry_if_exception(_is_transient),
            reraise=True,
        ):
            with attempt:
                text = self._post(payload)

        if self.use_cache:
            cache_file.write_text(json.dumps({"output": text}), encoding="utf-8")
        return text

    def _post(self, payload: dict) -> str:
        self.calls += 1
        resp = self.client.post(
            f"{self.cfg.base_url.rstrip('/')}/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {self.cfg.api_key}"},
        )
        resp.raise_for_status()
        data = resp.json()
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"unexpected response shape: {str(data)[:200]}") from exc
        if not text or not text.strip():
            raise EmptyResponse("model returned an empty response")
        return text
