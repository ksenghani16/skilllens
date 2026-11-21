# SkillLens

**Find, explain and verify regressions between two versions of an agent skill, using only free, local models.**

You edit a prompt or skill file. Some things get better, some get worse, and you only notice by accident.
SkillLens runs both versions on the same test cases, finds what got worse (ignoring normal run-to-run noise),
proposes which edit caused it, and then **proves it with a controlled experiment**: it puts that one edit back
and checks whether the failures go away.

```
old skill + new skill + test cases
        |
   [Runner]        run both versions k times on every case          (plain code)
        |
   [Comparator]    pass rate per case, noise-aware regression check (plain code + statistics)
        |
   [Behavior]      how did the outputs change? (length, JSON, failed checks)  (plain code)
        |
   [Investigator]  LLM agent: "which numbered change caused this?"  (structured JSON out)
        |
   [Verifier]      revert ONLY that change, re-run the failing cases, did they recover?
        |
   report.md + report.json + events.jsonl
```

Rule of thumb used throughout: **plain code wherever possible, an LLM only where judgment is needed.**

---

## 1. Quick start (Windows, PowerShell)

Requirements: Python 3.10+, [Ollama](https://ollama.com), optionally Docker.

```powershell
cd skilllens
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### Step A: try it with NO model installed (built-in simulated model)

```powershell
python -m pytest -q
python -m skilllens compare benchmarks/skills/unit_normalizer_v1.md benchmarks/skills/injected/b1_remove_fahrenheit_rule.md --cases benchmarks/cases/unit_normalizer_cases.json --mock
python -m skilllens evaluate --mock
```

`--mock` uses a tiny fake model that follows the demo skill. It proves the pipeline works end to end.
**Its results measure nothing about real models.**

### Step B: run with a real local model

```powershell
ollama pull qwen2.5:7b-instruct      # or any model you have: run `ollama list`
# if you use a different model, tell SkillLens:
$env:SKILLLENS_MODEL = "your-model-name"

python -m skilllens compare benchmarks/skills/unit_normalizer_v1.md benchmarks/skills/injected/b1_remove_fahrenheit_rule.md --cases benchmarks/cases/unit_normalizer_cases.json
```

Each run makes roughly `cases x repeats x 2` model calls (72 for the demo) plus a few for the investigator and
verifier. Expect a few minutes on a laptop. Everything is cached in `.cache/`, so running the same thing again is
instant. GPU support in Ollama depends on your hardware (check Ollama's current docs for Intel Arc); CPU works but is slower.

### Step C: measure the whole system (your headline result)

```powershell
python -m skilllens evaluate                      # all 4 modes on the injected-bug benchmark
python -m skilllens evaluate --modes full         # just the full system
```

Results land in `results/results.md` (table) and `results/results.csv`.

---

## 1.5 The web page (easiest way to use it)

```powershell
python -m skilllens serve
```

The terminal prints a one-time **API key** and the address (`http://127.0.0.1:8000`). Open the address, paste the key, and:

1. Pick an **example** (or paste your own old and new skill text).
2. Edit the **test cases** table: a message, and the answer the skill should give.
3. Tick **Demo mode** to try it without Ollama, or leave it unticked to use your local model.
4. Press **Compare the skills**. The "What is happening" panel lights up each stage of the flow as it runs, and the
   result shows which cases got worse, which lines changed, and the verified cause.

The three examples use a simple skill, a **Sentiment Labeler** (`examples/sentiment_v1.md`), that answers
`positive`, `negative` or `neutral`:
- *A rule was changed*: "complaints" now map to `neutral`, so negative messages get the wrong label.
- *The format rule was removed*: answers come back as `Positive.` instead of `positive`.
- *Only harmless rewording*: SkillLens should report **no regression**.

The same files work on the command line:

```powershell
python -m skilllens compare examples/sentiment_v1.md examples/sentiment_v2_rule_changed.md --cases examples/sentiment_cases.json
```

### Let the AI write the test cases

Press **Generate test cases with AI** (needs the old skill in the left box). What happens (`casegen.py`):
1. The model proposes about 15 realistic messages that exercise every rule in the skill. It writes **no answers**.
2. The **old** skill answers each message 3 times.
3. A message is kept only if the old skill answered it the same way every time. That answer becomes the expected answer
   (for JSON answers it checks each field, so spacing and key order do not matter).

So the tests mean "the new skill should behave like the old one". Always **read the expected answers**: if the old skill
was wrong somewhere, that mistake is locked into the test. It works best for short, fixed-format answers. The old-skill answers
are cached, so the later comparison reuses them for free (same repeats setting).

**Tip:** always fill in the **Example message** box before pressing Generate. It shows the AI what one valid input looks like
(for example `days=12 condition=unopened price=80 member=no`). Without it, a model may misread the skill and write the
skill's *answer words* as inputs ("full", "half"…), which makes useless tests. SkillLens now drops such echo cases and
shows a warning when there are few cases or all expected answers are the same.

### Another hard example: Refund Decider

`examples/refund_v1.md` / `refund_v2.md` with `refund_cases.json` (17 cases whose expected answers were computed by a small
program, not by a model). The new version has 5 edits: 3 harmless and 2 bugs (swapped rule order, changed boundary).
It is also in the examples dropdown with the cases already filled in.

### A harder example: Support Ticket Router

`examples/ticket_router_v1.md` routes a ticket to a team and a priority as JSON. `ticket_router_v2.md` has **5 edits**:

| edit | kind |
|---|---|
| c1 intro reworded | harmless |
| c2 tie-break "named first" becomes "named last" | **bug**: tickets that fit two teams (e.g. a double charge plus a crash) go to the wrong team |
| c3 legal tickets "always high" becomes "always medium" | **bug**: lawyer or legal tickets get the wrong priority |
| c4 `## Format` renamed | harmless |
| c5 extra bullet about double quotes | harmless |

Pick it in the examples list, press **Generate test cases with AI**, then **Compare**. Generated cases only catch a bug if some
case touches it: check the case table has tickets that fit two teams and tickets that mention a lawyer. If not, add rows by hand
(for example: "I was charged twice and now the app crashes", "My lawyer will contact you about this charge") and fill in the answers
the old skill gives. This example needs a real model; demo mode only understands the two simple skills.

To use your own skills with other kinds of answers (JSON, longer text), use the "Advanced: JSON test cases" option.
The page only talks to your own computer; nothing is sent to any outside service.

---

## 2. What the output looks like

Terminal:

```
RESULT: regression on 2 case(s): fahrenheit_72, fahrenheit_32
TOP CAUSE (confirmed): changes c3: ...
   removed: - temperature: Fahrenheit (F): K = (F - 32) * 5/9 + 273.15
   added:   (nothing)
```

Every run also creates a folder `runs/<id>/` that contains everything needed to understand it later:

| file | what it is |
|---|---|
| `report.md` / `report.json` | the human-readable and machine-readable result |
| `events.jsonl` | one JSON line per step with timings (your own tracing) |
| `config.json` | the settings used (API key is never written) |
| `skill_old.md`, `skill_new.md` | exact inputs, so the run can be reproduced |

---

## 3. How it works, in detail

### 3.1 Test cases (`cases.json`)
A case is an input plus **rule-based checks**. No LLM judges the answers, so scoring is deterministic.

```json
{"id": "fahrenheit_72", "input": "Convert 72 F",
 "checks": [{"type": "json_valid"},
            {"type": "json_field_close", "field": "value", "expected": 295.3722, "rel_tol": 0.005},
            {"type": "json_field_equals", "field": "unit", "expected": "K"}]}
```

Check types: `json_valid` (whole output is JSON, no extra prose), `json_field_equals`, `json_field_close`,
`contains`, `not_contains`, `regex`. A case passes when **all** its checks pass.
Why separate checks? `json_valid` fails when the *format* breaks, `json_field_close` fails when the *content*
breaks. The Investigator sees which kind failed, which is a strong clue.

### 3.2 Runner (`runner.py`)
Runs a skill version on every case `repeats` (k) times. The skill is the system prompt, the case is the user message.
LLMs are not deterministic, so each repeat uses a different seed. Same request again = served from cache.

### 3.3 Comparator (`compare.py`): noise-aware
- Pass rate per case = passes / k for each version.
- A case is **regressed** if its pass rate drops by at least `min_drop` (default 0.5). With k=3, one flip
  (a drop of 0.33) is treated as noise.
- A case is **flaky** if the *old* version was inconsistent on it. If more than 30% of cases are flaky the report warns you.
- A paired bootstrap gives a 95% interval for the overall change (informational).
- Honest limit: with k=3 the test is not very powerful. Use `--repeats 5` for more confidence.

### 3.4 Diffing (`diffing.py`)
Splits the difference between the two skill texts into numbered changes `c1, c2, ...`.
`apply_with_reverts(old, new, {"c2"})` returns the **new** skill with only change c2 put back to its old text.
This is what makes verification a real experiment.

### 3.5 Behavior analysis (`behavior.py`)
For regressed cases only: output length old vs new, how often the output is pure JSON, and the most common failed
checks. It gives the Investigator a summary instead of raw text. Plain code, no LLM.

### 3.6 Investigator (`agents/investigator.py`)
The first LLM step. It gets the numbered changes, the behavior summary and up to 4 failing examples, and must answer
with JSON naming the suspected change ids. Safety and reliability details:
- Case text is wrapped in `<case>` tags and the prompt says it is untrusted data (prompt-injection defense).
- Output is validated with Pydantic. Invalid JSON or unknown change ids are rejected and the model is asked again
  with the error message (`structured.py`, up to `investigator_attempts` tries).
- It only *points at* changes. It cannot modify anything.

### 3.7 Verifier (`agents/verifier.py`)
For each suspected cause: build a candidate skill (new version with only the blamed change reverted), re-run only the
regressed cases, and count how many recover. If at least `recovery_threshold` (default 50%) recover, the cause is
**confirmed**; otherwise **rejected**. If everything is rejected the report says "cause not found" instead of guessing.

### 3.8 Modes (for your ablation study)
| mode | what it does |
|---|---|
| `single_call` | one model call, no retries, no behavior summary, no verification (the baseline) |
| `investigator_only` | investigator with retries and behavior summary, no verification |
| `full` | investigator plus verifier, then a leave-one-out search if no cause was confirmed |
| `search_only` | no LLM investigator at all: test each change on its own (plain-code baseline) |

Comparing these on the benchmark answers "do agents actually help?" with numbers.
`search_only` is the important honest baseline: when the diff has only a few changes, simply trying each one
may beat asking a model. The investigator earns its place when there are many changes.

### 3.8.1 Two safeguards added after the first real-model run
A real 7B model once wrote a correct description ("the Fahrenheit rule was removed") but named the wrong change ids
(the harmless edits). Two fixes:
1. **Quote grounding** (`agents/investigator.py`): every cause must include an exact `quote` from the blamed change.
   Code checks that the quote really appears in the change ids it named. If not, the answer is rejected and the model
   is told which change actually contains the quote.
2. **Leave-one-out search** (`pipeline.py`): if nothing is confirmed, every change is reverted on its own and the
   regressed cases are re-run. No model guessing involved. It is skipped when there are more than
   `max_exhaustive_changes` changes.

### 3.9 Production features, where to find them
| feature | where |
|---|---|
| timeouts, retries with backoff (only for timeouts / 429 / 5xx) | `llm.py` |
| on-disk cache for reproducible, instant reruns | `llm.py` |
| strict schemas between components | `models.py` |
| validate-and-retry for model JSON | `structured.py` |
| JSONL event log per run, optional Langfuse | `tracing.py` |
| settings in one file, secrets from environment | `config.py`, `config.yaml` |
| API-key protected HTTP service, background jobs | `api.py` |
| path-safe run ids, request size limits | `api.py` |
| unit tests with a fake model, CI | `tests/`, `.github/workflows/tests.yml` |
| container, non-root user | `Dockerfile`, `docker-compose.yml` |

---

## 4. Use it on your own skill

1. Put your old and new skill files anywhere (e.g. `skills/my_skill_v1.md`, `skills/my_skill_v2.md`).
2. Write `skills/cases.json` with 15-30 cases and rule-based checks (see 3.1). Cases with a clearly checkable answer work best.
3. Run:
   ```powershell
   python -m skilllens compare skills/my_skill_v1.md skills/my_skill_v2.md --cases skills/cases.json
   ```
4. Add `--fail-on-regression` to exit with code 1 when a regression is found (useful in CI).

---

## 5. HTTP API

```powershell
$env:SKILLLENS_API_KEY = "a-long-random-string"
python -m skilllens serve              # http://127.0.0.1:8000  (docs at /docs)
```

- `POST /investigate` with JSON `{"old_skill": "...", "new_skill": "...", "cases": [...], "mode": "full"}` returns `{"run_id": ...}`
- `GET /runs/{run_id}` returns `{"state": "queued|running|done|failed", "report": {...}}`
- Every call needs the header `X-API-Key`. If `SKILLLENS_API_KEY` is not set, the server refuses all requests.

## 6. Docker

```powershell
copy .env.example .env      # then edit .env and set SKILLLENS_API_KEY
docker compose up --build
```

Only SkillLens runs in Docker. Ollama keeps running on your computer (so it can use your GPU) and the container
reaches it at `host.docker.internal:11434`. The port is bound to `127.0.0.1` so nothing outside your machine can reach it.

## 7. Other model backends (free hosted models)

SkillLens speaks the OpenAI chat format, so switching is only settings:

```powershell
$env:LLM_BASE_URL = "https://integrate.api.nvidia.com/v1"
$env:LLM_API_KEY  = "<your key>"          # never commit this
$env:SKILLLENS_MODEL = "<a model id from build.nvidia.com>"
```

Free hosted tiers are rate-limited (roughly tens of requests per minute) and can change or disappear, so keep local
Ollama as your reproducible default. Do not send private or employer data to a hosted free tier.

## 8. Optional: Langfuse tracing

```powershell
pip install langfuse
$env:LANGFUSE_PUBLIC_KEY = "..."; $env:LANGFUSE_SECRET_KEY = "..."; $env:LANGFUSE_HOST = "https://cloud.langfuse.com"
```

When the public key is set, `tracing.py` wraps the investigator, verifier and whole run with Langfuse's `observe`.
The SDK has changed names between versions, so check the current Langfuse docs if the import fails (SkillLens silently
falls back to its own JSONL log). Cloud Hobby keeps data for a limited time: copy your final results into the repo.

---

## 9. The evaluation benchmark (injected bugs)

`benchmarks/make_bugs.py` takes a good skill and creates "new" versions that each contain the same harmless edits
(rewording, a renamed header, an extra style bullet) plus **exactly one injected bug**, and one **control** with only harmless edits.
`benchmarks/manifest.json` records, for each, a `bug_marker`: a piece of text that appears in the true bad change.

`evaluate` reports, per mode:
- **detection rate**: bugs that the comparator flagged
- **cause accuracy**: top cause blames a change containing the bug marker
- **verified precision**: of causes the verifier confirmed, how many were right
- **false alarms**: control runs that were flagged (should be 0)
- **model calls**: cost

**To grow the benchmark to 20-30 bugs:** add entries to `BUGS` in `make_bugs.py` (delete a rule, change a number,
add a contradicting rule, reorder steps), add more skills and cases, then run `python benchmarks/make_bugs.py`.
Do this before looking at results, and write down in advance what counts as a correct cause.

> With `--mock`, the table shows the pipeline working, not model quality. Only runs on real models count as results.

## 10. Folder map

```
skilllens/
  models.py         data formats (Case, RunRecord, Change, Cause, Report ...)
  config.py         settings loader (config.yaml + environment)
  llm.py            model client: timeout, retry, cache, counters
  checks.py         rule-based scoring of outputs
  runner.py         runs a skill on all cases k times
  compare.py        noise-aware comparison + bootstrap
  diffing.py        numbered changes, revert-and-rebuild
  behavior.py       "how did outputs change" summary
  structured.py     validate-and-retry for JSON from the model
  agents/
    investigator.py  proposes which change caused the regression
    verifier.py      tests that claim by reverting it
  pipeline.py       the whole flow and the three modes
  report.py         report.json / report.md
  evaluate.py       benchmark harness
  casegen.py        AI-proposed test inputs, expected answers from the old skill
  mock.py           simulated model for demos and tests
  tracing.py        JSONL event log + optional Langfuse
  api.py            FastAPI service (also serves the web page)
  static/index.html the web page (no external libraries)
  cli.py            command line
benchmarks/         unit-normalizer demo skill, cases, bug generator, manifest
examples/           simple Sentiment Labeler skill, 3 edited versions, cases
tests/              39 unit and integration tests (fake model, no Ollama needed)
```

## 11. Troubleshooting

| problem | fix |
|---|---|
| `Connection refused` | Ollama is not running. Start it (`ollama serve`) and check `ollama list` |
| model not found | set `SKILLLENS_MODEL` to a name from `ollama list` |
| very slow | use a smaller model, lower `repeats`, or run fewer cases while developing |
| investigator keeps returning invalid JSON | try a larger or better instruction-following model; check `events.jsonl` for the rejected replies |
| "results are noisy" warning | raise `repeats`, lower `temperature` in `config.yaml` |
| Docker cannot reach Ollama | confirm `LLM_BASE_URL=http://host.docker.internal:11434/v1` in `.env` |
| wrong results after changing a skill | delete `.cache/` (it is keyed by the exact request, so this is rarely needed) |

## 12. Known limits (put these in your report)

- Small local models are weaker investigators than large ones. Measure it instead of assuming.
- Rule-based checks only cover what you can check by rule. LLM judges are possible but noisy.
- Reverting changes at the line level cannot find bugs that come from the *interaction* of two edits unless the investigator blames both.
- With few repeats the statistics are weak. The report says so when the baseline is flaky.
- The demo benchmark is small and written by you. Say so, and enlarge it.

## 13. Ideas for the next step

- A **negative control** in the verifier: also revert a random *unblamed* change and show it does not fix anything.
- A second skill domain in the benchmark, to show results are not tied to one skill.
- A CrewAI adapter: wrap `Investigator` and `Verifier` as CrewAI agents and compare against the plain-Python loop.
- A comparison of local 7B vs a larger hosted model as the investigator.

*Not medical or financial advice; the unit-conversion skill is only a toy example.*
