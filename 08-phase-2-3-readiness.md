# 08: Phase 2 and 3 Readiness

Phases are cumulative. A Phase 3 evaluation re-tests Phases 1 and 2. Build the hooks now
so later phases are additive rather than a rewrite.

## What is locked in

| Phase | Theme | Fields it will use |
|---|---|---|
| 2 | Shared devices and IPs (identity signal) | `ipAddress`, `deviceId` |
| 3 | Amount trails along flows (value signal) | `amount` |

## Capture everything from day one

Even though Phase 1 ignores them, store `amount`, `ipAddress`, and `deviceId` on every
transaction and aggregate them onto edges and nodes as you go. Retrofitting the
aggregation after the fact means replaying history you no longer have.

```python
@dataclass
class NodeState:
    ips: dict[str, int]          # ip -> count of transactions from this node
    devices: dict[str, int]
    tx_missing_ip: int
    tx_missing_device: int
    total_in: float
    total_out: float
```

Maintain reverse indices so shared-identity lookups are O(1) when Phase 2 arrives:

```python
ip_to_nodes: dict[str, set[int]]
device_to_nodes: dict[str, set[int]]
```

Both must honour the same 24 hour expiry as the graph. Decrement counts on expiry and
delete empty keys, or the memory bound is violated.

## Absence is a state, not a null

The Phase 1 brief flags this explicitly:

> a flow that carries a network address or device identifier on some legs and stops
> carrying it on a later connected leg. Absence on isolated transactions is not
> suspicious; absence where a connected flow previously carried the attribute may be an
> attempt to break the trail.

Model each identity field as a three-valued state per transaction: `present(value)`,
`absent`, or `unknown-at-this-layer`. Do not collapse absent into `None` and then treat
`None` as "no information". Track, per edge and per node:

- how many live transactions carried the attribute
- how many live transactions explicitly omitted it

That gives you the "flow previously carried it and now does not" signal directly, without
needing to reconstruct history. The predicate you will need in Phase 2 is roughly:

```
identity_drop(u -> v) =
    the upstream cone A contains at least one node with a live IP or device observation
    AND this transaction omits that attribute
```

Reserve a `s_identity_drop` slot in the signal set now so adding it is a config and
formula change rather than a plumbing change.

## Keep the signal set open

Structure `ScoreBreakdown` as an ordered mapping of `signal_name -> (value, weight)` so
new signals slot in without touching the combination code:

```python
raw = sum(weight * value for value, weight in breakdown.signals.values())
score = 1.0 - exp(-raw / cfg.SCALE)
```

Then Phase 2 adds `s_shared_device`, `s_shared_ip`, `s_identity_drop`, and Phase 3 adds
`s_amount_conservation`, `s_structuring`, `s_value_cycle`, with no change to `combine()`.

Recalibrate `SCALE` when a phase lands. Six more signals with the same `SCALE` will push
everything toward 1.0 and destroy the ranking spread at the top.

## Likely Phase 2 signals (speculative, do not implement yet)

- Two entities that never transact with each other but share a device or IP: a strong
  collusion signal, and it is a signal on *nodes* rather than edges, so it needs the
  reverse index.
- A cycle whose members share a small number of devices: near-certain single controller.
- Identity attribute disappearing partway along a connected flow (the drop signal above).

## Likely Phase 3 signals (speculative, do not implement yet)

- Amount conservation along a path: `X` in and roughly `X` minus a small cut out, hop
  after hop. Real commerce does not conserve value that tightly.
- Structuring: many transfers just under a round threshold.
- Value returning to origin: cycle where the amount returning is close to the amount sent.

Both lists exist to justify the data captured now, not to be built now. Phase 1 first.

## Cumulative regression discipline

When Phase 2 unlocks:

1. Tag the Phase 1 commit. Keep the Phase 1 golden tests running unchanged forever.
2. Add Phase 2 signals with weight 0, deploy, confirm scores are byte-identical to Phase 1.
3. Raise the new weights one at a time, re-running the Phase 1 golden and coherence suites
   after each.

"Extend your system without breaking what already works" is stated twice in the brief.
The Phase 1 test suite is the mechanism that enforces it.
