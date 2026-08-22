# CLAUDE.md: Agent Instructions

You are implementing the Ghost Chains Phase 1 service. This file governs how you work.
The specification lives in `docs/`. Read `docs/00` through `docs/06` before writing code.

## Non-negotiable rules

1. **No pattern matching on the five examples.** Never write branches like
   `if is_cycle: return 0.9`. The evaluator explicitly rewards principled graph models
   and penalises implementations tuned to specific patterns. One continuous formula.
   The five examples are assertions about the formula's output, not inputs to its design.
2. **No wall clock anywhere in scoring.** Time is always event time derived from
   `createdAt`. Two identical input sequences run a week apart must produce byte
   identical scores. `datetime.now()` may appear only in logging.
3. **No randomness, no floating point iteration order dependence.** Iterate sorted
   collections where order could affect a sum.
4. **All tunable numbers live in one config object.** `app/config.py`. Zero magic
   numbers inside scoring logic. Diagnostics-driven retuning must be a config edit.
5. **Never raise on unexpected input.** Unknown fields, missing optional fields,
   duplicate ids, out-of-order timestamps, self-transfers, empty batches. All handled,
   none fatal. A 500 on any transaction loses the whole evaluation run.
6. **State reset must be total.** After `POST /ghost-chains/reset`, the process must be
   indistinguishable from a fresh start.
7. **Write the test before or with the code.** Every task in
   `docs/04-implementation-plan.md` names its tests. A task is not done until they pass.

## Definition of done for Phase 1

- [ ] All three endpoints respond correctly to the smoke-test curls in `docs/03`.
- [ ] All five golden ordering tests pass with the required margins.
- [ ] All property tests pass (range, determinism, independence, monotonicity).
- [ ] The fast reachability engine matches the naive BFS reference on 500 randomised
      graph sequences including expiry (differential test).
- [ ] 10,000 transactions process with p95 latency under 25 ms and stable memory.
- [ ] `pytest -q` is green and CI passes.
- [ ] Service is deployed, publicly reachable over HTTPS, and `GET /health` returns ok.

## Working order

Ship a deployed skeleton that returns `0.0` before writing any scoring code. The
earliness bonus applies per phase, and a reachable endpoint returning zeros is worth
more than an unreachable perfect scorer. See `docs/04` step 1.

## Style

- Type hints on every public function.
- Docstrings state the invariant the function maintains, not what the code says.
- Keep `scoring.py` pure: it takes a graph snapshot plus an edge and returns a
  breakdown object. No I/O, no mutation. This is what makes it testable.
- Log the full signal breakdown per transaction at DEBUG. You will need it for tuning.
