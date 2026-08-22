# 00: Problem Brief

## What the service does

An evaluator streams financial transactions into your HTTP service in batches. For each
transaction you return a risk score between 0.0 and 1.0 at the moment it is processed.
You never learn the correct answer. The evaluator compares your ordering against a
reference model and reports only which signal dimensions disagreed.

## The three things being graded

| Dimension | What it measures | Practical implication |
|---|---|---|
| Detection Quality | Does your ranking put more suspicious transactions above less suspicious ones | Optimise relative order, ignore absolute calibration |
| Structural Consistency | Do structurally related scenarios behave coherently | One principled formula, no per-pattern branches |
| Earliness bonus | Was a working system evaluated early in the phase window | Deploy a stub immediately, improve in place |

Absolute values are irrelevant. Multiplying every score by 0.7 changes nothing.
Reordering two transactions changes everything.

## The domain model

- **Entity**: any counterparty. Node in a directed graph. Called "user" in the API.
- **Transaction**: a transfer from one entity to another. Directed edge, timestamped.
- **Active window**: W = 24 hours. Only transactions inside the window exist as far as
  the graph is concerned. Expired transactions must be removed and must stop
  influencing scores.
- **Streaming**: score using only information available at that point in time. No
  lookahead, no batch reprocessing of history.

## Why circular flow is the signal

Money laundering has three stages, and the middle one, layering, is what leaves a graph
signature. Layering means moving funds through many hops to break the audit trail. Two
things follow from that:

1. **Redundant routing.** Legitimate commerce moves money along a path once. Layering
   creates multiple routes between the same origin and destination, because the point is
   to obscure, not to transact.
2. **Return flow.** Money that arrives back at an entity it has already passed through
   has accomplished nothing economically. Nobody pays their own supplier chain in a
   circle by accident. A cycle in the transaction graph is close to a definition of
   suspicious.

That gives the ladder of structural signal the brief describes:

```
isolated edge  <  extension  <  convergence  <  return path  <  multiple return paths
   nothing        one hop       redundancy       a cycle          a laundering ring
```

## The five reference examples

Assume all preceding transactions are already scored. The **last** transaction of each
example is the one being evaluated.

**Example 1: Isolated.** `Meridian -> Apex`.
First transaction between two unseen entities. No structure exists. Lowest score of all five.

**Example 2: Extension.** `Meridian -> Apex`, then `Apex -> Cascade`.
Funds move onward to a new counterparty. The reachable set grows in one direction. This
is what a normal supply chain payment looks like. Low.

**Example 3: Convergence.** `Meridian -> Apex`, `Meridian -> Horizon`, `Apex -> Sterling`,
then `Horizon -> Sterling`.
Meridian could already reach Sterling through Apex. Now it can reach Sterling a second
way, through Horizon. Note that this creates *fewer* newly reachable pairs than
Example 2 but must score higher. Any model that counts only new reachability gets this
backwards. Intermediate.

**Example 4: Return.** `Meridian -> Apex`, `Apex -> Cascade`, `Cascade -> Oakridge`,
then `Oakridge -> Apex`.
Oakridge sends funds back to Apex, which sat upstream of it. A cycle closes. Must be
meaningfully higher than Example 2.

**Example 5: Multi-loop.** `Meridian -> Apex`, `Apex -> Cascade`, `Cascade -> Meridian`,
`Apex -> Nimbus`, then `Nimbus -> Meridian`.
Meridian now receives funds back via two independent routes. Must be meaningfully higher
than Example 4.

## Required orderings (hard constraints)

```
score(Ex1) < score(Ex2)              Ex1 is the minimum of the five
score(Ex2) < score(Ex3) < score(Ex4)
score(Ex4) >> score(Ex2)             "meaningfully higher"
score(Ex5) >  score(Ex4)             "meaningfully higher"
```

Recommended enforced margins in tests: 0.05 between adjacent tiers, 0.30 for Ex4 over
Ex2, 0.05 for Ex5 over Ex4. See `docs/05-testing-strategy.md`.

## What the diagnostics tell you

When your ranking disagrees with the reference, you get categories and severities only:

```
STRUCTURAL_DEVIATION: Moderate, TEMPORAL_DEVIATION: Low
```

- `STRUCTURAL_DEVIATION`: your graph signal weighting is off. Retune weights.
- `TEMPORAL_DEVIATION`: window handling, expiry boundary, or event-time ordering is off.

Severity is relative magnitude of disagreement, not difficulty. Absence of a category
means agreement on that dimension. See `docs/07-tuning-diagnostics.md` for the response
playbook.

## Explicitly out of scope for Phase 1

- `ipAddress` and `deviceId` are **captured and stored** but do not affect the score yet.
  Phase 2 uses them. The brief warns that absence of an identity field on a leg of a flow
  that previously carried it will become a signal, so store presence and absence as
  distinct observable states from day one.
- `amount` is captured and stored but does not affect the score. Phase 3 uses it.
