# 03: API Contract

Three endpoints. All must be reachable over public HTTPS. Deviating from these shapes
fails the evaluation regardless of scoring quality.

## `GET /ghost-chains/health`

Response `200`:

```json
{ "status": "ok" }
```

Must never depend on internal state. Must respond even if the graph is huge or a previous
request errored. Keep it a constant literal.

## `POST /ghost-chains/reset`

Request:

```json
{ "clearTransactions": true }
```

Response `200`:

```json
{ "clearTransactions": true }
```

Echo the field back exactly as received. Behaviour:

- Clear the transaction log, node index, edge map, expiry heap, closure bitsets, all caches.
- Reset the event-time watermark to `None`.
- Reset the free-index pool.
- The process must be indistinguishable from a cold start.

If `clearTransactions` is `false`, still echo it. Do not clear. (Nothing in the brief
requires this, but echoing faithfully is safer than assuming.)

## `POST /ghost-chains/transactions`

### Request

```json
{
  "transactions": [
    {
      "txId": "tx_meridian_001",
      "fromUserId": "meridian_holdings",
      "toUserId": "apex_logistics",
      "amount": 370.0,
      "createdAt": "2026-06-08T12:00:00Z",
      "ipAddress": "203.0.113.4",
      "deviceId": "dev_a91"
    }
  ]
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `txId` | string | yes | unique identifier |
| `fromUserId` | string | yes | sender entity |
| `toUserId` | string | yes | receiver entity |
| `amount` | number | yes | stored, unused in Phase 1 |
| `createdAt` | string | yes | ISO 8601 |
| `ipAddress` | string | no | stored, unused in Phase 1 |
| `deviceId` | string | no | stored, unused in Phase 1 |

Unknown fields must be ignored, not rejected. Pydantic model config:
`model_config = ConfigDict(extra="ignore")`.

### Response

```json
{
  "transactions": [
    { "txId": "tx_meridian_001", "riskScore": 0.043 }
  ]
}
```

- Same length and same order as the request array. Always.
- `riskScore` is a float in `[0.0, 1.0]`, rounded to 6 decimals.

### Processing rules

1. **Sequential.** Process the array in order. Transaction `i+1` sees the graph state
   including transaction `i`. Do not vectorise or parallelise.
2. **Order preserved.** Build the response array positionally, never by dict iteration.
3. **Idempotency.** Each `txId` is unique in the stream. If a `txId` arrives again with an
   identical payload, return the originally computed score and make zero state changes.
   Implement by storing a hash of the normalised payload alongside the score.
4. **Payload conflict.** If a known `txId` arrives with a *different* payload, the brief
   invites you to decide. Decision: return the original score, make no state change, log a
   warning with both payload hashes. Rationale in `docs/06-decisions.md` D-03. Determinism
   is worth more than accommodating a case the brief says should not occur.
5. **Never 500.** Any exception inside per-transaction processing must be caught, logged,
   and yield `riskScore: 0.0` for that transaction while the rest of the batch continues.
   A single crash loses the whole evaluation run.

### Validation failures

If the request body itself is unparseable, return `422` with FastAPI's default body. If
an individual transaction is missing a required field, do not fail the batch: score it
`0.0`, log, continue.

## Timestamp handling

```python
def parse_iso(s: str) -> float:
    s = s.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)   # naive means UTC
    return dt.timestamp()
```

Accept `Z`, explicit offsets, fractional seconds, and naive timestamps. Convert
everything to epoch seconds as a float immediately and never handle `datetime` objects
downstream.

## Event time, not wall clock

```
watermark = max(watermark, created_at_of_current_transaction)
edge is expired  <=>  created_at <= watermark - 86400
```

The watermark only advances, never retreats, so out-of-order arrival cannot un-expire
anything. See `docs/06-decisions.md` D-01 for the boundary decision and D-02 for
out-of-order arrival.

## Smoke tests

```bash
BASE=http://localhost:8080

curl -s $BASE/ghost-chains/health

curl -s -X POST $BASE/ghost-chains/reset \
  -H 'Content-Type: application/json' \
  -d '{"clearTransactions": true}'

curl -s -X POST $BASE/ghost-chains/transactions \
  -H 'Content-Type: application/json' \
  -d '{"transactions":[
    {"txId":"t1","fromUserId":"M","toUserId":"A","amount":370.0,"createdAt":"2026-06-08T12:00:00Z"},
    {"txId":"t2","fromUserId":"A","toUserId":"C","amount":100.0,"createdAt":"2026-06-08T12:01:00Z"},
    {"txId":"t3","fromUserId":"C","toUserId":"O","amount":100.0,"createdAt":"2026-06-08T12:02:00Z"},
    {"txId":"t4","fromUserId":"O","toUserId":"A","amount":100.0,"createdAt":"2026-06-08T12:03:00Z"}
  ]}'
```

Expected shape of the last response: four scores, strictly increasing, with `t4`
substantially above `t2`.

Also verify these do not fail:

```bash
# missing optionals, unknown field, duplicate txId, self transfer, empty batch
curl -s -X POST $BASE/ghost-chains/transactions -H 'Content-Type: application/json' \
  -d '{"transactions":[{"txId":"t5","fromUserId":"X","toUserId":"X","amount":1,"createdAt":"2026-06-08T12:04:00Z","futureField":123}]}'

curl -s -X POST $BASE/ghost-chains/transactions -H 'Content-Type: application/json' \
  -d '{"transactions":[]}'
```
