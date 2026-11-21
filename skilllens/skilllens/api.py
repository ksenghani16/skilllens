"""FastAPI service. Long runs are background jobs: POST returns a run id, GET polls status.

Security: every request needs the X-API-Key header, matching the SKILLLENS_API_KEY environment
variable. If that variable is not set the service refuses all requests (it never runs open).
"""
from __future__ import annotations

import json
import os
import re
import secrets
import uuid
from pathlib import Path
from typing import Callable, Optional

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .config import Config, load_config
from .llm import LLM, OpenAICompatLLM
from .mock import MockLLM
from .casegen import generate_cases
from .models import Case
from .structured import StructuredOutputError
from .pipeline import MODES, run_investigation

_RUN_ID = re.compile(r"^[a-f0-9]{12}$")


class GenerateRequest(BaseModel):
    skill: str = Field(max_length=50_000)
    n: int = Field(default=10, ge=3, le=30)
    repeats: Optional[int] = Field(default=None, ge=1, le=10)
    mock: bool = False
    example: str = Field(default="", max_length=300)   # optional: one valid input, to show the format


class InvestigateRequest(BaseModel):
    old_skill: str = Field(max_length=50_000)
    new_skill: str = Field(max_length=50_000)
    cases: list[Case] = Field(min_length=1, max_length=200)
    mode: str = "full"
    repeats: Optional[int] = Field(default=None, ge=1, le=10)
    mock: bool = False   # use the built-in simulated model (demo mode, no Ollama needed)


def create_app(cfg: Optional[Config] = None, llm_factory: Optional[Callable[[Config], LLM]] = None) -> FastAPI:
    cfg = cfg or load_config()

    def default_factory(c: Config) -> LLM:
        return MockLLM() if os.getenv("SKILLLENS_MOCK") == "1" else OpenAICompatLLM(c)

    make_llm = llm_factory or default_factory
    app = FastAPI(title="SkillLens", version="0.1.0")

    def require_key(x_api_key: Optional[str] = Header(default=None)) -> None:
        expected = os.getenv("SKILLLENS_API_KEY")
        if not expected:
            raise HTTPException(503, "Server is not configured: set SKILLLENS_API_KEY")
        if not secrets.compare_digest(x_api_key or "", expected):
            raise HTTPException(401, "Invalid API key")

    def write_status(run_dir: Path, state: str, error: str = "") -> None:
        (run_dir / "status.json").write_text(json.dumps({"state": state, "error": error}), encoding="utf-8")

    def job(run_id: str, req: InvestigateRequest) -> None:
        run_dir = Path(cfg.runs_dir) / run_id
        write_status(run_dir, "running")
        try:
            run_cfg = cfg.model_copy(update={"repeats": req.repeats} if req.repeats else {})
            llm = MockLLM() if req.mock else make_llm(run_cfg)
            run_investigation(req.old_skill, req.new_skill, req.cases, run_cfg, llm,
                              mode=req.mode, run_dir=run_dir, run_id=run_id)
            write_status(run_dir, "done")
        except Exception as exc:   # report any failure in the status file instead of losing it
            write_status(run_dir, "failed", f"{type(exc).__name__}: {exc}"[:500])

    @app.get("/", include_in_schema=False)
    def home() -> FileResponse:
        return FileResponse(Path(__file__).parent / "static" / "index.html")

    @app.get("/healthz")
    def healthz() -> dict:
        return {"ok": True}

    @app.post("/investigate", status_code=202, dependencies=[Depends(require_key)])
    def investigate(req: InvestigateRequest, background: BackgroundTasks) -> dict:
        if req.mode not in MODES:
            raise HTTPException(422, f"mode must be one of {MODES}")
        run_id = uuid.uuid4().hex[:12]
        run_dir = Path(cfg.runs_dir) / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        write_status(run_dir, "queued")
        background.add_task(job, run_id, req)
        return {"run_id": run_id, "status_url": f"/runs/{run_id}"}

    @app.get("/runs/{run_id}", dependencies=[Depends(require_key)])
    def get_run(run_id: str) -> dict:
        if not _RUN_ID.match(run_id):          # blocks path tricks like ../
            raise HTTPException(400, "bad run id")
        run_dir = Path(cfg.runs_dir) / run_id
        status_file = run_dir / "status.json"
        if not status_file.exists():
            raise HTTPException(404, "run not found")
        status = json.loads(status_file.read_text(encoding="utf-8"))
        report_file = run_dir / "report.json"
        if status["state"] == "done" and report_file.exists():
            status["report"] = json.loads(report_file.read_text(encoding="utf-8"))
        return status

    @app.post("/generate-cases", dependencies=[Depends(require_key)])
    def generate(req: GenerateRequest) -> dict:
        run_cfg = cfg.model_copy(update={"repeats": req.repeats} if req.repeats else {})
        llm = MockLLM() if req.mock else make_llm(run_cfg)
        try:
            return generate_cases(llm, run_cfg, req.skill, n=req.n, example=req.example)
        except StructuredOutputError as exc:
            raise HTTPException(502, f"The model did not return usable test inputs: {exc}"[:400])
        except Exception as exc:   # e.g. Ollama not running
            raise HTTPException(502, f"Model call failed: {type(exc).__name__}: {exc}"[:400])

    @app.get("/runs/{run_id}/events", dependencies=[Depends(require_key)])
    def get_events(run_id: str) -> dict:
        if not _RUN_ID.match(run_id):
            raise HTTPException(400, "bad run id")
        f = Path(cfg.runs_dir) / run_id / "events.jsonl"
        if not f.exists():
            return {"events": []}
        return {"events": [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]}

    return app
