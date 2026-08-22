# 05: Testing Strategy

Five layers. Every one is required before the submission counts as done.

```
1. Golden ordering       does the model rank correctly
2. Structural coherence  does it generalise beyond the five examples
3. Unit / contract       do the mechanics work
4. Property / differential  is it correct under randomisation
5. Load                  does it survive the stream
```

## Shared fixtures (`tests/conftest.py`)

```python
BASE = datetime(2026, 6, 8, 12, 0, 0, tzinfo=timezone.utc)

def tx(txid, frm, to, minutes=0, amount=100.0, **kw):
    return {
        "txId": txid, "fromUserId": frm, "toUserId": to, "amount": amount,
        "createdAt": (BASE + timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z"),
        **kw,
    }

def run(engine, *transactions) -> list[float]:
    """Feed transactions one per batch, return the score of each."""
```

Always feed sequences one transaction per batch in the golden tests. That proves the
streaming path, not just the in-batch path. Add one test that feeds the same sequence as
a single batch and asserts identical scores.

---

## Layer 1: Golden ordering

The five reference examples, encoded as inequalities with margins, not as expected values.

```python
EX1 = [("t1","M","A")]
EX2 = [("t1","M","A"), ("t2","A","C")]
EX3 = [("t1","M","A"), ("t2","M","H"), ("t3","A","S"), ("t4","H","S")]
EX4 = [("t1","M","A"), ("t2","A","C"), ("t3","C","O"), ("t4","O","A")]
EX5 = [("t1","M","A"), ("t2","A","C"), ("t3","C","M"), ("t4","A","N"), ("t5","N","M")]
```

Score the **last** transaction of each sequence, each on a freshly reset engine.

| Assertion | Margin | Source |
|---|---|---|
| `s1 == min(s1..s5)` | strict | "Example 1 should receive the lowest risk score of the five" |
| `s2 > s1` | 0.01 | extension beats isolation |
| `s3 > s2` | 0.05 | convergence is stronger than extension |
| `s4 > s3` | 0.05 | "not necessarily as suspicious as a return path" |
| `s4 - s2 > 0.30` | hard | "meaningfully higher" |
| `s5 - s4 > 0.05` | hard | "meaningfully higher" |

Also assert exact signal integers against the `docs/02` summary table
(`n_new`, `n_red`, `cycle_len`, `ret_mult`, `scc_size`). Signals failing is a different
bug from weights failing, and you want the test to tell you which.

---

## Layer 2: Structural coherence

This is the layer that protects the second scored dimension. Each case is derived from
the principle, not from the brief's examples. All are relative assertions.

| # | Scenario | Assertion |
|---|---|---|
| C1 | Two disjoint components, `M->A` in one and `X->Y` in the other | identical scores |
| C2 | Same edge inserted into an empty graph vs into a dense unrelated graph | identical scores (locality) |
| C3 | Cycle of length 3 vs cycle of length 6, both otherwise identical | 3-cycle scores higher |
| C4 | 2 return paths into a node vs 3 return paths | 3 scores higher |
| C5 | Fan-in of 2 into a node vs fan-in of 5 | 5 scores higher |
| C6 | Long chain `A->B->C->D->E` | scores increase monotonically along the chain |
| C7 | Repeat of an ordinary edge | scores below its first occurrence |
| C8 | Repeat of an edge inside an established ring | scores above C7 and below a fresh cycle closure |
| C9 | Self transfer `X->X` on an empty graph | scores above isolated, below any real cycle |
| C10 | Edge that closes a cycle vs the same edge after the cycle path expired | the second scores much lower |
| C11 | Diamond `M->A->S`, `M->H->S` (convergence) vs tree `M->A->S`, `M->H->T` | diamond scores higher |
| C12 | Adding an edge into a large SCC vs into a 3-node SCC | large SCC scores higher |

Write each as `assert score_a > score_b + 0.01` so failures name the violated principle.

---

## Layer 3: Unit and contract

### `test_api.py`
- `/health` returns `{"status":"ok"}`.
- `/reset` echoes `clearTransactions`.
- Response length and order match the request for a 50-transaction batch with shuffled ids.
- Every score satisfies `0.0 <= s <= 1.0`.
- Unknown field ignored.
- Both optionals absent, only `ipAddress` present, only `deviceId` present: all succeed.
- Empty batch returns `{"transactions": []}`.
- Malformed transaction inside a good batch yields `0.0` for that one and correct scores
  for the rest, still full length, status 200.
- Reset between two identical sequences produces identical score vectors.

### `test_window.py`
- Timestamp parsing: `Z`, `+08:00`, fractional seconds, naive. All equivalent where they
  should be.
- Watermark is monotonic under out-of-order input.
- Boundary triple: an edge at exactly `W`, at `W - 1s`, and at `W + 1s` relative to the
  watermark. Assert the documented D-01 behaviour (exactly `W` old is **expired**).
- An expired cycle no longer contributes: build a cycle, advance the watermark past 24
  hours with a filler transaction, then re-close the cycle. The score must drop to the
  isolated-edge tier.
- Multi-transaction edge survives until its last transaction expires.
- Node indices are recycled: after everything expires, the bitset width returns to zero.

### `test_idempotency.py`
- Same `txId`, identical payload, submitted twice: second returns the first score, and
  node count, edge count, and watermark are unchanged.
- Same `txId`, different payload: returns the original score, no mutation, warning logged.
- Duplicate appearing inside the same batch as its original.
- Duplicate after a reset is treated as brand new.

---

## Layer 4: Property and differential

Use `hypothesis`.

```python
@given(seq=graph_sequences())
def test_score_always_in_range(seq): ...

@given(seq=graph_sequences())
def test_deterministic_after_reset(seq):
    a = run(engine, seq); engine.reset(); b = run(engine, seq)
    assert a == b            # exact equality, not approximate

@given(seq_a=graph_sequences(alphabet="ABCDE"), seq_b=graph_sequences(alphabet="VWXYZ"))
def test_disjoint_components_independent(seq_a, seq_b):
    """Interleaving a disjoint component must not change any score in seq_a."""

@given(seq=graph_sequences())
def test_cycle_closing_edge_never_scores_below_non_cycle_twin(seq): ...
```

### Differential test (the important one)

```python
@given(ops=graph_operation_sequences(include_expiry=True))
def test_bitset_matches_naive(ops):
    fast, slow = BitsetReachability(), NaiveReachability()
    for op in ops:
        apply(op, fast); apply(op, slow)
        for a, b in all_pairs(nodes):
            assert fast.reaches(a, b) == slow.reaches(a, b)
```

Run at least 500 examples with graphs of 3 to 20 nodes and interleaved expiry events.
Incremental transitive closure plus deletion is the single most likely source of a silent
correctness bug in this system, and a wrong closure produces wrong scores that look
plausible. This test is not optional.

---

## Layer 5: Load

```python
def test_throughput():
    """10k transactions across 48 event-hours, 2000 entities, mixed patterns."""
    # assert p95 latency < 25ms, p99 < 100ms

def test_memory_bounded_by_window():
    """Live node and edge counts plateau once event time exceeds 24h."""
    # sample counts every 1000 transactions; assert the last 3 samples differ by < 10%
```

Generate the synthetic stream with a fixed seed. Mix: 70% random ordinary edges, 15%
chains, 10% fan-in bursts, 5% deliberate cycles. Assert that the mean score of the cycle
group exceeds the mean score of the ordinary group by a wide margin. That is a
poor-man's AUC and it catches regressions the golden tests miss.

---

## CI

```yaml
# .github/workflows/ci.yml
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: pip install -r requirements.txt -r requirements-dev.txt
      - run: ruff check app tests
      - run: mypy app
      - run: pytest -q --maxfail=1
```

Mark the load tests `@pytest.mark.slow` and run them on a nightly schedule plus manual
dispatch, not on every push.

## Manual verification before every evaluation run

```bash
bash scripts/smoke.sh https://your-app.up.railway.app
```

The script must exercise: health, reset, the four-transaction cycle sequence, missing
optionals, unknown fields, a duplicate, and an empty batch. Never trigger an evaluation
without running it first.
