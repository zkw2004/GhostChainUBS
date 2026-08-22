# Ghost Chains — Phase 1

Real-time AML transaction risk scoring. Directed graph, 24-hour lookback, structural signals only.

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
