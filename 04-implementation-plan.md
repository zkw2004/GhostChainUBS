# 04: Implementation Plan

Twelve tasks in dependency order. Each has a deliverable, an acceptance criterion, and
the tests that prove it. Do not start a task before its predecessor passes.

---

## Task 1: Deployed stub

**Do this before anything else.** The earliness bonus is per phase and a reachable
endpoint returning zeros beats an unreachable perfect scorer.

**Deliverable**
- FastAPI app with all three endpoints. `/transactions` returns `0.0` for every input.
- `Dockerfile` (python:3.11-slim, uvicorn, single worker, `PORT` from env).
- Deployed to Railway with a public HTTPS URL.
- URL registered with the coordinator.

**Accept when**: the three curls in `docs/03` succeed against the public URL.
**Tests**: `tests/test_api.py::test_health`, `::test_reset_echo`, `::test_returns_one_score_per_transaction`.

---

## Task 2: Schemas and permissive validation

**Deliverable** `app/schemas.py`
- `TransactionIn` with `extra="ignore"`, optionals defaulting to `None`.
- `TransactionsRequest`, `ScoreOut`, `TransactionsResponse`, `ResetRequest/Response`.

**Accept when**: a payload containing an unknown field, and one omitting both
`ipAddress` and `deviceId`, both process without error.
**Tests**: `test_api.py::test_unknown_fields_ignored`, `::test_missing_optionals_ok`.

---

## Task 3: Time utilities and the watermark

**Deliverable** `app/timeutil.py`
- `parse_iso(str) -> float` handling `Z`, offsets, fractional seconds, naive input.
- `Watermark` class: monotonic `advance(t)`, `cutoff()` returning `watermark - W`.

**Accept when**: all four timestamp formats parse identically; the watermark never
decreases when fed out-of-order input.
**Tests**: `test_window.py::test_parse_formats`, `::test_watermark_monotonic`.

---

## Task 4: Config object

**Deliverable** `app/config.py`
- Frozen dataclass with every constant from `docs/02` defaults section.
- `from_env()` classmethod reading `GC_W_RED`, `GC_W_CYCLE` etc.
- Module-level singleton `CFG`.

**Accept when**: `grep -nE '[0-9]\.[0-9]' app/scoring.py` returns nothing except
docstrings. No magic numbers outside config.
**Tests**: `test_properties.py::test_no_magic_numbers` (source scan).

---

## Task 5: Windowed graph, no reachability yet

**Deliverable** `app/graph.py`
- Node index with recycling, `adj_out` / `adj_in`, `EdgeState`.
- `add_transaction(tx)`, `expire(cutoff)`, `in_degree(n)`, `out_degree(n)`, `clear()`.
- Expiry heap. Edges die when their last live transaction expires. Node indices are
  freed when a node has no live edges.

**Accept when**: after inserting a transaction and advancing time past 24 hours, node
count, edge count, and bitset width all return to zero.
**Tests**: `test_window.py::test_edge_expires`, `::test_node_index_recycled`,
`::test_multi_tx_edge_survives_until_last_expires`.

---

## Task 6: Naive reachability reference

**Deliverable** `app/reachability.py::NaiveReachability`
- Plain BFS `descendants(n)`, `ancestors(n)`, `reaches(a,b)`, `shortest_path_len(a,b)`.
- Optimise for obviousness, not speed. This is the oracle.

**Accept when**: hand-checkable on the five examples.
**Tests**: `test_reachability_differential.py::test_naive_basic`.

---

## Task 7: Bitset reachability engine

**Deliverable** `app/reachability.py::BitsetReachability`
- `desc` and `anc` int arrays, incremental insert per `docs/01`.
- Full rebuild on any expiry (`mark_dirty()` then lazy rebuild before next query).
- Fallback to naive mode above `CFG.MAX_BITSET_NODES`.

**Accept when**: the differential test passes on 500 randomised sequences that include
expiry events.
**Tests**: `test_reachability_differential.py::test_matches_naive_random`,
`::test_matches_naive_with_expiry`.

---

## Task 8: Signal extraction

**Deliverable** `app/scoring.py::extract_signals(graph, u, v) -> Signals`
Pure function against the **pre-insert** graph. Returns:
`n_new, n_red, indeg_v_after, outdeg_u_after, cycle_closed, cycle_len, scc_size, ret_mult, is_repeat_edge, is_self_loop`.

**Accept when**: the raw signal values for all five examples match the summary table in
`docs/02` exactly (integers, no tolerance).
**Tests**: `test_golden_ordering.py::test_signal_values_match_spec` (parametrised over
the five examples).

---

## Task 9: Score combination

**Deliverable** `app/scoring.py::combine(signals, cfg) -> ScoreBreakdown`
- Six normalised signals, weighted sum, `1 - exp(-raw/SCALE)`, round to 6 dp.
- `ScoreBreakdown` carries every intermediate value for logging and tuning.
- Degenerate case handling from `docs/02`: repeat edge, self loop.

**Accept when**: the five scores match `docs/02` to within 0.01 **and** all required
inequalities hold with margins.
**Tests**: `test_golden_ordering.py::test_five_example_scores`,
`::test_required_inequalities`.

---

## Task 10: Engine, idempotency, batch ordering

**Deliverable** `app/engine.py::RiskEngine`
- `score_batch(list[TransactionIn]) -> list[float]` implementing the exact lifecycle in
  `docs/01` (idempotency, watermark, expire, score, insert, store).
- Payload hashing for the idempotency check.
- Single lock around all mutation.
- `reset()` restoring cold-start state.

**Accept when**: replaying the same batch twice returns identical scores and leaves node
and edge counts unchanged after the second replay.
**Tests**: `test_idempotency.py` (all), `test_api.py::test_batch_order_preserved`,
`::test_reset_isolates_state`.

---

## Task 11: Robustness pass

**Deliverable**
- Per-transaction try/except returning `0.0` on failure without aborting the batch.
- Structured logging of the full `ScoreBreakdown` at DEBUG level.
- `scripts/replay.py` reading JSONL and dumping a breakdown table to CSV.

**Accept when**: a batch containing a malformed transaction still returns a full-length,
correctly ordered response.
**Tests**: `test_api.py::test_malformed_transaction_does_not_abort_batch`.

---

## Task 12: Performance and CI

**Deliverable**
- `tests/test_performance.py`: 10,000 transactions over a synthetic 48 hour stream.
- `.github/workflows/ci.yml`: lint, type check, `pytest -q` on push and PR.

**Accept when**: p95 per-transaction latency under 25 ms, peak RSS under 512 MB, live
node count stops growing once the stream exceeds 24 hours of event time.
**Tests**: `test_performance.py::test_throughput`, `::test_memory_bounded_by_window`.

---

## Checkpoint gates

| Gate | Condition |
|---|---|
| G1 | Task 1 done. Register with the coordinator, trigger an evaluation, bank the earliness bonus. |
| G2 | Tasks 2 to 9 done. All golden tests green. Redeploy, re-evaluate, record diagnostics. |
| G3 | Tasks 10 to 12 done. Full suite green. Redeploy, re-evaluate. |
| G4 | Tune weights per `docs/07` using diagnostics from G2 and G3. Re-evaluate after each change, one variable at a time. |
