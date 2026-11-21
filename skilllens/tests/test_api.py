from fastapi.testclient import TestClient

from skilllens.api import create_app
from skilllens.config import Config
from skilllens.mock import MockLLM

OLD = '# S\nReturn only the JSON object.\n- length: foot (ft): multiply by 0.3048 to get m\n'
NEW = '# S\nReturn only the JSON object.\n'
CASES = [{"id": "ft", "input": "Convert 3 ft", "checks": [
    {"type": "json_valid"}, {"type": "json_field_close", "field": "value", "expected": 0.9144}]}]


def client(tmp_path, monkeypatch, key="secret"):
    if key:
        monkeypatch.setenv("SKILLLENS_API_KEY", key)
    else:
        monkeypatch.delenv("SKILLLENS_API_KEY", raising=False)
    cfg = Config(runs_dir=str(tmp_path / "runs"), cache_dir=str(tmp_path / "c"), bootstrap_samples=100)
    return TestClient(create_app(cfg, lambda c: MockLLM()))


def test_refuses_without_server_key(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch, key=None)
    assert c.post("/investigate", json={}).status_code == 503


def test_rejects_wrong_key(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    r = c.post("/investigate", headers={"X-API-Key": "wrong"},
               json={"old_skill": OLD, "new_skill": NEW, "cases": CASES})
    assert r.status_code == 401


def test_full_flow_and_path_safety(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    h = {"X-API-Key": "secret"}
    r = c.post("/investigate", headers=h, json={"old_skill": OLD, "new_skill": NEW, "cases": CASES})
    assert r.status_code == 202
    run_id = r.json()["run_id"]
    got = c.get(f"/runs/{run_id}", headers=h).json()
    assert got["state"] == "done" and got["report"]["regression_detected"] is True
    assert c.get("/runs/..%2F..%2Fetc", headers=h).status_code in (400, 404)
    assert c.get("/healthz").json() == {"ok": True}
