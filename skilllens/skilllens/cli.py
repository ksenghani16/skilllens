"""Command line: compare two skills, evaluate on the benchmark, or start the API."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import load_config
from .evaluate import evaluate, load_cases
from .llm import OpenAICompatLLM
from .mock import MockLLM
from .pipeline import MODES, run_investigation


def _make_llm(cfg, mock: bool):
    if mock:
        print("[mock] using the built-in simulated model: results measure nothing about real models\n")
        return MockLLM()
    return OpenAICompatLLM(cfg)


def cmd_compare(args) -> int:
    cfg = load_config(args.config)
    if args.repeats:
        cfg = cfg.model_copy(update={"repeats": args.repeats})
    old = Path(args.old).read_text(encoding="utf-8")
    new = Path(args.new).read_text(encoding="utf-8")
    cases = load_cases(args.cases)
    rep = run_investigation(old, new, cases, cfg, _make_llm(cfg, args.mock), mode=args.mode,
                            run_dir=Path(args.out) if args.out else None)
    print(f"run id: {rep.run_id}   mode: {rep.mode}   model calls: {rep.llm_calls}   time: {rep.seconds:.1f}s")
    if not rep.regression_detected:
        print("RESULT: no regression detected")
    else:
        print(f"RESULT: regression on {len(rep.regressed_case_ids)} case(s): {', '.join(rep.regressed_case_ids)}")
        top = rep.top_cause()
        if top:
            print(f"TOP CAUSE ({top.status}): changes {', '.join(top.cause.change_ids)}: {top.cause.description}")
            for ch in top.blamed_changes:
                print(f"   removed: {' / '.join(ch.old_lines) or '(nothing)'}")
                print(f"   added:   {' / '.join(ch.new_lines) or '(nothing)'}")
        else:
            print("No cause survived verification (cause not found).")
    for n in rep.notes:
        print("note:", n)
    run_dir = Path(args.out) if args.out else Path(cfg.runs_dir) / rep.run_id
    print(f"full report: {run_dir / 'report.md'}")
    # exit code 1 on regression so CI can fail the pull request
    return 1 if rep.regression_detected and args.fail_on_regression else 0


def cmd_evaluate(args) -> int:
    cfg = load_config(args.config)
    modes = tuple(args.modes) if args.modes else MODES
    _, md = evaluate(args.manifest, cfg, _make_llm(cfg, args.mock), modes=modes, out_dir=args.out)
    print("\n" + md)
    return 0


def cmd_serve(args) -> int:
    import os
    import secrets

    import uvicorn
    if not os.getenv("SKILLLENS_API_KEY"):
        os.environ["SKILLLENS_API_KEY"] = secrets.token_urlsafe(16)
        print(f"\nAPI key for this session (paste it into the page): {os.environ['SKILLLENS_API_KEY']}")
    print(f"Open http://{args.host}:{args.port} in your browser\n")
    uvicorn.run("skilllens.api:create_app", factory=True, host=args.host, port=args.port)
    return 0


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="skilllens", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("compare", help="find and explain a regression between two skill files")
    c.add_argument("old"); c.add_argument("new")
    c.add_argument("--cases", required=True, help="JSON file with test cases")
    c.add_argument("--mode", choices=MODES, default="full")
    c.add_argument("--repeats", type=int)
    c.add_argument("--out", help="run folder (default: runs/<id>)")
    c.add_argument("--config")
    c.add_argument("--mock", action="store_true", help="use the built-in simulated model")
    c.add_argument("--fail-on-regression", action="store_true", help="exit 1 if a regression is found (for CI)")
    c.set_defaults(fn=cmd_compare)

    e = sub.add_parser("evaluate", help="measure SkillLens on the injected-bug benchmark")
    e.add_argument("--manifest", default="benchmarks/manifest.json")
    e.add_argument("--modes", nargs="+", choices=MODES)
    e.add_argument("--out", default="results")
    e.add_argument("--config")
    e.add_argument("--mock", action="store_true")
    e.set_defaults(fn=cmd_evaluate)

    s = sub.add_parser("serve", help="start the HTTP API")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.set_defaults(fn=cmd_serve)

    args = p.parse_args(argv)
    sys.exit(args.fn(args))


if __name__ == "__main__":
    main()
