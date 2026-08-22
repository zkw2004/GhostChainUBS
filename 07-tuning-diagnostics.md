# 07: Tuning and Diagnostics

The evaluator returns only categories and severities, never scores. Treat each
evaluation as one bit of information and spend it deliberately.

```
STRUCTURAL_DEVIATION: Moderate, TEMPORAL_DEVIATION: Low
```

An absent category means agreement on that dimension. Severity is the magnitude of
disagreement, computed dynamically, unrelated to test difficulty.

## The one rule

**One change per evaluation.** Two simultaneous changes make the result uninterpretable
and burn a slot you cannot get back. Record every run in the log at the bottom of this
file before making the next change.

---

## `TEMPORAL_DEVIATION` playbook

Fix this before touching structural weights. Temporal errors are correctness bugs, not
tuning problems, and a wrong window silently corrupts every structural signal downstream.

Work the list in order and stop at the first change:

1. **Verify event time.** Confirm no `datetime.now()` or `time.time()` reaches the
   scoring or expiry path. Grep for it.
2. **Verify expiry runs before scoring.** A transaction must never see structure that
   should already have expired. Add an assertion in the engine.
3. **Flip the boundary.** `CFG.WINDOW_BOUNDARY_INCLUSIVE` from `False` to `True`
   (D-01). Cheapest high-leverage experiment available.
4. **Check closure rebuild on expiry.** If the bitset closure is not rebuilt after edges
   die, expired paths keep contributing. The differential test in `docs/05` catches this,
   so if it is passing, skip.
5. **Only then** enable the cycle-tightness multiplier:
   `CFG.ENABLE_TEMPORAL_MULTIPLIER = True` (see `docs/02`, optional temporal refinement).
   This adds a genuine temporal signal rather than fixing a bug, so it is last.

---

## `STRUCTURAL_DEVIATION` playbook

Severity guides how far to move, and the tier ordering guides which weight to move.

| Severity | Weight adjustment step |
|---|---|
| Low | 10 to 15% on one weight |
| Moderate | 25 to 40% on one weight |
| High | reconsider the model, not the weights |

### Diagnosing which tier is wrong

You cannot see the reference scores, so reason from what each weight controls:

| Weight | Controls the gap between | Raise it if you suspect |
|---|---|---|
| `W_RED` | extension and convergence | convergence is ranked too close to plain extension |
| `W_CYCLE` | convergence and return | cycles are not separating enough from non-cycles |
| `W_LOOP` | return and multi-loop | rings are not separating from single loops |
| `W_SCC` | small rings and large rings | large laundering networks rank too low |
| `W_REACH` | isolated and extension | ordinary chains rank too flat at the bottom |
| `W_FAN` | ordinary flow and smurfing | fan-in bursts are not surfacing |
| `SCALE` | overall spread | scores are bunched near 0 or near 1 |

### Order of attempts

1. `SCALE`. If your live score distribution is bunched (check `scripts/replay.py`
   output on a synthetic stream), no weight change will help until the spread is right.
   Target: the middle 80% of ordinary transactions below 0.25, cycle-closing
   transactions above 0.60.
2. `W_RED`. It is the highest-leverage weight because the expansion versus redundancy
   split is the model's core claim.
3. `W_LOOP`, then `W_CYCLE`.
4. `W_SCC` and `W_FAN` last. They are refinements.

### Preserve the ordering invariant

```
W_LOOP > W_CYCLE > W_RED > W_SCC > W_REACH > W_FAN
```

If tuning wants to break this, the problem is a modelling error rather than a weight
error. Re-read `docs/02` and check the signal extraction first with
`test_golden_ordering.py::test_signal_values_match_spec`.

### High severity means stop tuning

High structural disagreement after the golden tests pass points at a missing signal, not
a mis-set weight. Candidates worth adding, in order of likely value:

1. **Path shortening.** The brief says "new *or shortened* paths". The current model
   scores new paths but not distance reduction. Add
   `s_short = fraction of pairs in A × D whose shortest distance strictly decreased`.
   This is the most defensible addition because it is named in the brief.
2. **Edge-disjoint return paths.** A stronger version of `ret_mult` using a max-flow
   computation between `v` and `u`. Expensive but exact.
3. **Betweenness of the new edge.** How many shortest paths now route through it.

Add at most one, behind a flag, with its own coherence tests.

---

## Regression protection

Any weight change must keep the full suite green, especially:

- `test_golden_ordering.py::test_required_inequalities`
- the twelve coherence cases in `docs/05` layer 2

If a tuning change breaks a coherence case, revert it. A weight set that improves one
evaluation but breaks structural coherence loses on the second scored dimension, which is
worth as much as the first.

---

## Evaluation log

Fill this in. It is the only record you have of what the diagnostics are telling you.

| Run | Timestamp | Change made | Structural | Temporal | Verdict |
|---|---|---|---|---|---|
| 1 | | baseline stub, all zeros | | | reference point |
| 2 | | full Phase 1 model, default weights | | | |
| 3 | | | | | |
| 4 | | | | | |
| 5 | | | | | |

Notes column conventions: record the exact config diff, not a description. Paste the
diagnostic string verbatim.
