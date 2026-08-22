# 06: Decision Register

The brief deliberately leaves several points open ("be precise about boundary
conditions", "consider what should happen if", "left open, reason from the principle").
Each is decided here with a rationale and a config flag so it can be flipped in seconds
if diagnostics disagree.

---

## D-01: Window boundary inclusivity

**Question**: is a transaction created exactly 24 hours ago active or expired?

**Decision**: expired. `active <=> created_at > watermark - 86400`.

**Rationale**: "the most recent 24 hours" reads as a half-open interval
`(now - 24h, now]`. Half-open windows are the norm in stream processing because they make
each event belong to exactly one window.

**Flag**: `CFG.WINDOW_BOUNDARY_INCLUSIVE = False`. If `TEMPORAL_DEVIATION` appears after
the window logic is otherwise verified, flip this first. It is a one-character change with
a large behavioural footprint at boundaries, and it is the cheapest experiment available.

---

## D-02: Reference time for expiry

**Question**: wall clock or event time?

**Decision**: event time. `watermark = max(created_at seen since last reset)`, monotonic.

**Rationale**: the brief requires that identical inputs after a reset produce consistent
outputs. Wall clock makes that impossible, because a replay minutes later would expire
different edges. Event time also matches how the evaluator almost certainly replays a
synthetic dataset with timestamps unrelated to the current date.

**Consequence**: the watermark never retreats. A late-arriving transaction with an older
timestamp cannot resurrect expired edges.

---

## D-03: Duplicate `txId` with a different payload

**Question**: the brief says ids are unique and then asks what should happen if a payload
differs.

**Decision**: return the originally computed score, make no state change, log a warning
containing both payload hashes.

**Rationale**: three options were considered.
1. *Reject with an error*: violates "must not cause processing to fail" in spirit and
   risks aborting an evaluation run.
2. *Treat as a new transaction*: breaks the idempotency guarantee and makes replays
   non-deterministic, which is directly scored.
3. *Return the original score, no mutation*: preserves both idempotency and determinism.

Option 3 chosen. It is also the behaviour most likely to match a reference
implementation that keys purely on `txId`.

**Flag**: `CFG.CONFLICTING_PAYLOAD_MODE = "return_original"`.

---

## D-04: Repeated edge between the same pair

**Question**: `u -> v` already exists in the window and another transaction on the same
pair arrives.

**Decision**: no reachability delta (`n_new = n_red = 0`), cycle and SCC evidence retained
but multiplied by `REPEAT_EDGE_DAMPING = 0.50`.

**Rationale**: the principle is "increase in the graph's capacity to support recurring
flow". A duplicate edge adds no capacity, so the delta terms must be zero. But a repeated
transfer inside an existing ring is operationally what a laundering cycle looks like once
it is running, so zeroing everything would be wrong too. Damping the state-based evidence
splits the difference from the principle rather than from convenience.

**Consequence**: repeat of an ordinary edge scores near the floor, repeat inside a ring
scores moderately, which is the correct relative ordering.

---

## D-05: Self transfer

**Question**: `fromUserId == toUserId`.

**Decision**: no reachability delta, `s_cycle = SELF_LOOP_CYCLE = 0.50`, `s_loop = 0`,
`s_scc` computed normally.

**Rationale**: a length-1 loop is technically the tightest possible cycle, but in real
ledgers self-transfers are overwhelmingly internal bookkeeping rather than laundering.
Scoring it at full cycle weight would flood the top of the ranking with noise and hurt
the false positive objective the brief names explicitly. Scoring it at zero would ignore
a genuine structural oddity. Half weight is the defensible middle.

---

## D-06: Transaction that arrives already outside the window

**Question**: `created_at <= watermark - W` at arrival.

**Decision**: score it against the current graph, do not insert it into state.

**Rationale**: inserting it would trigger an immediate expiry and a closure rebuild for
zero effect on any subsequent score. Skipping the insert is observationally equivalent and
cheaper. The transaction still receives a score because the response array must be
full length.

---

## D-07: Scoring measures the delta, not the resulting state

**Question**: should the score be computed before or after the edge is inserted?

**Decision**: signals are computed against the pre-insert graph, except `indeg_v`,
`outdeg_u`, `scc_size`, and `ret_mult`, which are evaluated after insertion because they
describe the structure the edge just created.

**Rationale**: the brief says risk reflects "how the transaction *changes* the graph's
structural signal". Delta semantics. The four after-insert quantities are still delta
information: they are all zero or unchanged if the edge is a duplicate.

---

## D-08: Score normalisation family

**Question**: linear clamp, sigmoid, or exponential saturation?

**Decision**: `score = 1 - exp(-raw / SCALE)`.

**Rationale**: strictly monotone so ranking is exactly preserved; cannot exit `[0, 1)`
for any non-negative `raw`, so no clamping artifacts create ties at 1.0; compresses the
upper range, which leaves headroom for Phases 2 and 3 to add identity and value evidence
without every high-structure transaction already sitting at 0.99. A hard clamp would
create ties, and ties are the one thing a ranking metric punishes for free.

---

## D-09: Multiplicity of return paths, measured how?

**Question**: Example 5 needs "two independent return paths" to beat one, but the count
of distinct paths from `v` back to `u` is 1 in both Example 4 and Example 5.

**Decision**: measure `ret_mult` = number of in-neighbours of `v` that lie inside
`SCC(v)` after insertion.

**Rationale**: counting simple paths is exponential and, as noted, does not discriminate
these two cases anyway. In-edges from inside the strongly connected component counts how
many distinct ways flow re-enters `v` from the ring, which is precisely "multiple flows
have converged back toward the origin". Example 4 gives 1 (Oakridge only), Example 5
gives 2 (Cascade and Nimbus). Cheap, exact, and derived from the phrasing of the brief.

---

## D-10: Fan degrees measured on distinct counterparties

**Question**: should ten transactions from one sender count as in-degree 10 or 1?

**Decision**: 1. Degrees count distinct counterparties.

**Rationale**: fan-in as an AML signal means many *different* sources converging, which
is smurfing. Volume between one pair is a value signal, which belongs to Phase 3.
Keeping the two separate avoids double counting when Phase 3 lands.

---

## D-11: Deployment topology

**Decision**: single process, single uvicorn worker, no external store, all state in
memory guarded by one lock.

**Rationale**: state is inherently global and sequential. Multiple workers would shard
the graph and produce incoherent scores. If the host requires multiple replicas for
health checking, ensure sticky routing to one instance or scale to exactly one.

---

## Changing a decision

Change the flag, run the full suite, redeploy, trigger one evaluation, record the
diagnostic delta in `docs/07`. One variable per evaluation. Two simultaneous changes
produce an uninterpretable result and waste an evaluation slot.
