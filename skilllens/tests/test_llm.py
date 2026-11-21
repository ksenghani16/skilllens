import httpx

from skilllens.config import Config
from skilllens.llm import OpenAICompatLLM


def make(tmp_path, handler):
    cfg = Config(cache_dir=str(tmp_path), retry_wait_s=0, max_retries=3)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return OpenAICompatLLM(cfg, client=client)


MSG = [{"role": "user", "content": "hi"}]


def test_retries_transient_error_then_caches(tmp_path):
    n = {"calls": 0}

    def handler(request):
        n["calls"] += 1
        if n["calls"] == 1:
            return httpx.Response(500)
        return httpx.Response(200, json={"choices": [{"message": {"content": "hello"}}]})

    llm = make(tmp_path, handler)
    assert llm.complete(MSG, temperature=0, seed=1) == "hello"
    assert n["calls"] == 2                       # 1 failure + 1 success
    assert llm.complete(MSG, temperature=0, seed=1) == "hello"
    assert n["calls"] == 2 and llm.cache_hits == 1   # second request served from cache


def test_different_seed_is_a_different_request(tmp_path):
    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": "x"}}]})

    llm = make(tmp_path, handler)
    llm.complete(MSG, temperature=0, seed=1)
    llm.complete(MSG, temperature=0, seed=2)
    assert llm.calls == 2 and llm.cache_hits == 0


def test_client_error_is_not_retried(tmp_path):
    n = {"calls": 0}

    def handler(request):
        n["calls"] += 1
        return httpx.Response(400)

    llm = make(tmp_path, handler)
    try:
        llm.complete(MSG, temperature=0, seed=1)
    except httpx.HTTPStatusError:
        pass
    assert n["calls"] == 1
