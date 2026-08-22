#!/usr/bin/env bash
set -euo pipefail
BASE="${1:-http://localhost:8080}"

curl -sf "$BASE/ghost-chains/health"
echo

curl -sf -X POST "$BASE/ghost-chains/reset" \
  -H 'Content-Type: application/json' \
  -d '{"clearTransactions": true}'
echo

curl -sf -X POST "$BASE/ghost-chains/transactions" \
  -H 'Content-Type: application/json' \
  -d '{"transactions":[
    {"txId":"t1","fromUserId":"M","toUserId":"A","amount":370.0,"createdAt":"2026-06-08T12:00:00Z"},
    {"txId":"t2","fromUserId":"A","toUserId":"C","amount":100.0,"createdAt":"2026-06-08T12:01:00Z"},
    {"txId":"t3","fromUserId":"C","toUserId":"O","amount":100.0,"createdAt":"2026-06-08T12:02:00Z"},
    {"txId":"t4","fromUserId":"O","toUserId":"A","amount":100.0,"createdAt":"2026-06-08T12:03:00Z"}
  ]}'
echo

curl -sf -X POST "$BASE/ghost-chains/transactions" \
  -H 'Content-Type: application/json' \
  -d '{"transactions":[{"txId":"t5","fromUserId":"X","toUserId":"X","amount":1,"createdAt":"2026-06-08T12:04:00Z","futureField":123}]}'
echo

curl -sf -X POST "$BASE/ghost-chains/transactions" \
  -H 'Content-Type: application/json' \
  -d '{"transactions":[]}'
echo
