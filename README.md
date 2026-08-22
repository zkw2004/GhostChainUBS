# Ghost Chains — Phase 1

Real-time AML transaction risk scoring. Directed graph, 24-hour lookback, structural signals only.

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

This repo implements the service with Flask + Gunicorn for Heroku. Ignore FastAPI / Railway notes in the spec pack if they conflict with the running code here.

## Run locally

```bash
python3 -m pip install -r requirements.txt
python3 app.py
```

Smoke test (default `http://localhost:8080`):

```bash
curl -s http://localhost:8080/ghost-chains/health

curl -s -X POST http://localhost:8080/ghost-chains/reset \
  -H 'Content-Type: application/json' \
  -d '{"clearTransactions": true}'

curl -s -X POST http://localhost:8080/ghost-chains/transactions \
  -H 'Content-Type: application/json' \
  -d '{
    "transactions": [
      {
        "txId": "tx_meridian_001",
        "fromUserId": "meridian_holdings",
        "toUserId": "apex_logistics",
        "amount": 370.0,
        "createdAt": "2026-06-08T12:00:00Z"
      }
    ]
  }'
```

Tests:

```bash
python3 -m unittest discover -s tests -v
```

## Deploy on Heroku

State is in-memory, so the Procfile pins **one worker**. Do not raise `--workers`.

```bash
heroku login
heroku create your-ghost-chains-app
git init
git add .
git commit -m "Phase 1 risk scoring service"
git push heroku master
```

If the default branch is `main`:

```bash
git push heroku main
```

Confirm:

```bash
curl -s https://your-ghost-chains-app.herokuapp.com/ghost-chains/health
```

Register that public base URL with the coordinator.
