# Ghost Chains — Phase 1

Real-time AML transaction risk scoring. Directed graph, 24-hour event-time window, structural signals only.

The service follows the spec pack in this repo (`CLAUDE.md` and `00`–`08`). Scoring is the redundancy-vs-expansion model in `02-scoring-model.md`, not pattern-specific branches.

## Specification

| File | Purpose |
|---|---|
| [CLAUDE.md](CLAUDE.md) | Agent rules and definition of done |
| [00-problem-brief.md](00-problem-brief.md) | Challenge restatement |
| [01-architecture.md](01-architecture.md) | Modules and request lifecycle |
| [02-scoring-model.md](02-scoring-model.md) | Scoring mathematics |
| [03-api-contract.md](03-api-contract.md) | Endpoint behaviour |
| [04-implementation-plan.md](04-implementation-plan.md) | Task list |
| [05-testing-strategy.md](05-testing-strategy.md) | Test plan |
| [06-decisions.md](06-decisions.md) | Decision register |
| [07-tuning-diagnostics.md](07-tuning-diagnostics.md) | Evaluator diagnostics |
| [08-phase-2-3-readiness.md](08-phase-2-3-readiness.md) | Later-phase hooks |

## Run locally

```bash
python3 -m pip install -r requirements.txt -r requirements-dev.txt
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8080 --workers 1
```

```bash
bash scripts/smoke.sh http://localhost:8080
python3 -m pytest -q -m "not slow"
```

Weights live in `app/config.py` and can be overridden with `GC_W_RED`, `GC_W_CYCLE`, and the other `GC_*` environment variables.

## Deploy on Heroku

State is in-memory. The Procfile pins **one uvicorn worker**.

```bash
git push heroku master
curl -s https://ghost-chains-app-71754905796a.herokuapp.com/ghost-chains/health
```
