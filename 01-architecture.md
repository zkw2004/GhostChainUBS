# 01: Architecture

## Project layout

```
app/
  main.py            FastAPI app, routes, lifespan
  schemas.py         Pydantic request/response models
  config.py          ScoringConfig dataclass, ALL tunable constants
  engine.py          RiskEngine: orchestration, idempotency, ordering, reset
  graph.py           WindowedGraph: nodes, edges, expiry, degrees
  reachability.py    Bitset transitive closure + naive BFS reference
  scoring.py         Pure signal extraction and combination
  models.py          Transaction, EdgeState, ScoreBreakdown dataclasses
  timeutil.py        ISO 8601 parsing, watermark, window arithmetic
tests/
  test_api.py
  test_golden_ordering.py
  test_window.py
  test_idempotency.py
  test_properties.py
  test_reachability_differential.py
  test_performance.py
  conftest.py
scripts/
  smoke.sh
  replay.py          Feed a JSONL file of transactions, dump score breakdowns
Dockerfile
requirements.txt
.github/workflows/ci.yml
```

## Layering rules

```
main.py  ->  engine.py  ->  graph.py  ->  reachability.py
                        ->  scoring.py  (pure)
```

- `scoring.py` imports nothing from `engine` or `main`. It receives a read-only view of
  the graph plus the candidate edge and returns a `ScoreBreakdown`. This purity is what
  makes the golden tests fast and the model tunable.
- `graph.py` owns all mutation. Nothing else mutates state.
- `engine.py` is the only place that knows about the transaction log, idempotency, and
  batch ordering.

## Core data structures

### Node indexing

Entity ids are strings. Map them to dense integer indices so reachability can use bitsets.

```python
self._index: dict[str, int]      # entity id -> index
self._label: list[str]           # index -> entity id
self._free: list[int]            # recycled indices from fully expired nodes
```

Index recycling matters: over a long stream, entities churn. Without recycling the
bitset width grows without bound and violates the "memory bounded by the window"
requirement.

### Edges

```python
@dataclass
class EdgeState:
    tx_times: list[float]        # sorted event-time epoch seconds, one per live tx
    total_amount: float          # Phase 3 groundwork
    ip_seen: set[str]            # Phase 2 groundwork
    device_seen: set[str]        # Phase 2 groundwork
    ip_absent_count: int         # Phase 2: absence is an observable state
    device_absent_count: int

adj_out: dict[int, dict[int, EdgeState]]
adj_in:  dict[int, set[int]]
```

An edge exists while at least one of its transactions is inside the window. Multiple
transactions between the same pair collapse to one edge with a multiplicity.

### Expiry

```python
expiry_heap: list[tuple[float, str]]    # (createdAt, txId) min-heap
tx_by_id: dict[str, StoredTx]
```

On every ingest, pop from the heap while `created_at <= watermark - W`, remove the
transaction from its edge, delete the edge when empty, and free the node index when
a node has no live edges in either direction.

### Reachability

Two arrays of Python integers used as bitsets, width = number of live node indices.

```python
desc: list[int]    # desc[i] bit j set  <=>  j reachable from i (excluding i unless on a cycle)
anc:  list[int]    # anc[i]  bit j set  <=>  i reachable from j
```

`anc` is the transpose of `desc` and is maintained in parallel so that computing the
upstream cone of `u` is a single lookup instead of a reverse BFS.

**Insert** of edge `u -> v` (incremental transitive closure):

```
newly = (desc[v] | bit(v)) & ~(desc[u])
if newly == 0 and edge already existed: nothing changes
for each w in (anc[u] | bit(u)):
    desc[w] |= (desc[v] | bit(v))
for each x in (desc[v] | bit(v)):
    anc[x]  |= (anc[u] | bit(u))
```

Cost is `O(|A| * V / 64)` word operations.

**Delete** on expiry: incremental deletion of transitive closure is genuinely hard and
a common source of subtle bugs. Do not attempt it. Instead, mark the closure dirty and
**rebuild from scratch** whenever any edge expires. A rebuild is a BFS from every node,
`O(V * E / 64)` with bitsets, which for a 24 hour window of a few thousand entities is
low single digit milliseconds. Correctness beats cleverness here, and `TEMPORAL_DEVIATION`
is a scored dimension.

**Scale guard**: if live node count exceeds `config.MAX_BITSET_NODES` (default 8000),
fall back to per-transaction BFS mode. Bitsets at V = 8000 cost about 16 MB for both
arrays, which is acceptable. Beyond that, memory becomes the binding constraint.

### Naive reference

`reachability.py` also exports a dead simple BFS implementation with the same interface.
It is never used in production, only in the differential test that proves the bitset
engine correct. Keep it obviously correct rather than fast.

## Request lifecycle

```
POST /ghost-chains/transactions
  |
  1. Pydantic validation (permissive: extra="ignore", optionals default None)
  2. For each transaction, in request order:
       a. Idempotency check on txId
            hit + identical payload hash -> return stored score, no mutation
            hit + different payload      -> return stored score, no mutation, log conflict
       b. Parse createdAt to epoch seconds
       c. Advance watermark: watermark = max(watermark, created_at)
       d. Expire: pop everything with created_at <= watermark - W
       e. Snapshot pre-insert signals (this is the scoring input)
       f. Compute score from the pre-insert graph plus the candidate edge
       g. Insert the edge and update closure
       h. Store txId -> (score, payload hash)
  3. Return scores in input order
```

Step ordering matters. Expiry happens **before** scoring, so a transaction never sees
stale structure. Scoring happens **before** insertion, so the score measures the delta
the edge causes rather than the state it lands in. Both of these are directly testable.

## Concurrency

Guard all state mutation with a single `threading.Lock` (or run uvicorn with one worker
and rely on the asyncio single thread). The evaluator may send overlapping requests, and
interleaved mutation would break determinism. Route handlers should be `def`, not
`async def`, if you use a lock, so FastAPI runs them in the threadpool without blocking
the event loop. One worker process only: state is in memory and must not be sharded.

## Configuration

`app/config.py` holds a single frozen dataclass. Every constant referenced anywhere in
scoring or windowing lives here, loaded from environment variables with the documented
defaults so weights can be changed on a deployed instance without a rebuild.
