# 02: Scoring Model

This is the heart of the submission. Implement it exactly, then tune only the weights in
`config.py` in response to diagnostics.

## The governing principle

> Risk reflects how much this single edge increases the graph's capacity to support
> recurring flow.

Everything below is a decomposition of that sentence. There are no special cases.

## Step 1: the two cones

Let `G` be the active graph **before** inserting edge `u -> v`.

```
A = ancestors(u) ∪ {u}      the upstream cone: everything that can reach u
D = descendants(v) ∪ {v}    the downstream cone: everything v can reach
```

With the bitset closure both are single lookups:

```python
A = anc[u] | bit(u)
D = desc[v] | bit(v)
```

Inserting the edge makes every ordered pair in `A × D` reachable.

## Step 2: split the product

```
n_red = | { (w,x) ∈ A × D : x was ALREADY reachable from w } |
n_new = |A| * |D| - n_red
```

Computed as:

```python
n_red = sum(popcount(desc_before[w] & D) for w in bits(A))
n_new = popcount(A) * popcount(D) - n_red
```

Note that `desc_before[w]` must exclude the effect of the new edge, hence "before".

**Why the split is the whole model.** `n_new` measures network expansion, which is what
ordinary commerce does. `n_red` measures redundant routing: a second way to get somewhere
you could already get. Redundancy has no commercial purpose and is the fingerprint of
layering. Weighting `n_red` above `n_new` is what makes convergence outrank extension
without any convergence-specific code.

Self-pairs `(w,w)` are included deliberately. A node appearing in its own descendant set
means it now sits on a cycle, so cycle formation shows up in `n_new` automatically.

## Step 3: the six signals

| Signal | Formula | Captures |
|---|---|---|
| `s_reach` | `log1p(n_new) / log1p(CAP_REACH)` | expansion of the network |
| `s_red` | `log1p(n_red) / log1p(CAP_RED)` | redundant routing, convergence |
| `s_fan` | `log1p(max(0,indeg_v-1) + max(0,outdeg_u-1)) / log1p(CAP_FAN)` | fan-in and fan-out concentration |
| `s_cycle` | `0.5 + 0.5 * (3 / max(3, cycle_len))` if a cycle closed else `0` | return flow, tighter loop is worse |
| `s_loop` | `min(1, (ret_mult - 1) / 2)` if a cycle closed else `0` | multiple independent return paths |
| `s_scc` | `log1p(max(0,\|SCC(v)\|-1)) / log1p(CAP_SCC)` | size of the ring formed |

Definitions:

- `indeg_v`, `outdeg_u`: distinct counterparties, measured **after** insertion.
- **cycle closed** iff `u ∈ desc_before[v]`, that is, `v` could already reach `u`.
- `cycle_len`: `1 + shortest_path_length_before(v -> u)` in edges. BFS on the pre-insert
  graph. The minimum meaningful value is 3 for a distinct-node cycle, which is why the
  formula floors at 3 and gives tight cycles the maximum of 1.0.
- `SCC(v)` after insertion, computed from bitsets as
  `{y : y ∈ desc[v] and v ∈ desc[y]} ∪ {v}` when `v` is on a cycle. Equivalently
  `desc[v] & anc[v] | bit(v)`.
- `ret_mult`: the number of in-neighbours of `v` that lie inside `SCC(v)`. This is the
  multi-loop discriminator. In Example 4 it is 1 (only Oakridge closes into Apex from
  inside the ring). In Example 5 it is 2 (both Cascade and Nimbus return into Meridian).

Each signal is clamped to `[0, 1]` after normalisation.

## Step 4: combine

```python
raw = (W_REACH * s_reach
     + W_RED   * s_red
     + W_FAN   * s_fan
     + W_CYCLE * s_cycle
     + W_LOOP  * s_loop
     + W_SCC   * s_scc)

score = 1.0 - exp(-raw / SCALE)
```

The exponential map is chosen for three reasons: it is strictly monotone in `raw` so
ranking is preserved exactly, it can never leave `[0, 1)` regardless of how large `raw`
grows, and it compresses the top end so later phases can add evidence without saturating.

Round to 6 decimal places on output for reproducibility.

## Default configuration

```python
CAP_REACH = 32.0
CAP_RED   = 32.0
CAP_FAN   = 8.0
CAP_SCC   = 16.0

W_REACH = 0.45
W_RED   = 1.10
W_FAN   = 0.30
W_CYCLE = 1.40
W_LOOP  = 1.60
W_SCC   = 0.60

SCALE   = 2.0

REPEAT_EDGE_DAMPING = 0.50     # see below
SELF_LOOP_CYCLE     = 0.50     # see below
```

Weight ordering is the part that encodes the domain knowledge:
`W_LOOP > W_CYCLE > W_RED > W_SCC > W_REACH > W_FAN`.
Keep that ordering when tuning. Change magnitudes, not the ordering, unless diagnostics
force it.

## Worked examples

Nodes abbreviated: M Meridian, A Apex, C Cascade, H Horizon, S Sterling, O Oakridge,
N Nimbus.

### Example 1: `M -> A` on an empty graph

```
A = {M}, D = {A}
pairs = 1, already reachable = 0     -> n_new = 1,  n_red = 0
cycle: A cannot reach M              -> no
indeg(A)=1, outdeg(M)=1              -> s_fan = 0
s_reach = log1p(1)/log1p(32) = 0.198
raw = 0.45 * 0.198 = 0.089
score = 1 - exp(-0.0445) = 0.043
```

### Example 2: `A -> C` after `M -> A`

```
A = {M, A}, D = {C}
pairs = (M,C),(A,C) = 2, none previously reachable  -> n_new = 2, n_red = 0
s_reach = log1p(2)/log1p(32) = 0.314
raw = 0.141
score = 0.068
```

### Example 3: `H -> S` after `M->A`, `M->H`, `A->S`

```
A = {M, H}, D = {S}
(M,S) already reachable via M->A->S   -> n_red = 1
(H,S) new                             -> n_new = 1
indeg(S) after = 2, outdeg(H) after = 1 -> s_fan = log1p(1)/log1p(8) = 0.315
s_reach = 0.198, s_red = 0.198
raw = 0.45*0.198 + 1.10*0.198 + 0.30*0.315 = 0.402
score = 0.182
```

This is the case that breaks naive models. Example 3 creates fewer new reachable pairs
than Example 2 (1 versus 2) yet must rank higher. Only the redundancy term achieves that.

### Example 4: `O -> A` after `M->A`, `A->C`, `C->O`

```
A = {M, A, C, O}, D = {A, C, O}       12 pairs
already reachable: (M,A)(M,C)(M,O)(A,C)(A,O)(C,O)  -> n_red = 6
new: (A,A)(C,A)(C,C)(O,A)(O,C)(O,O)                -> n_new = 6
cycle: A reaches O before, so O->A closes one. shortest A->C->O = 2 edges, len = 3
s_cycle = 0.5 + 0.5*(3/3) = 1.0
SCC after = {A, C, O}, size 3         -> s_scc = log1p(2)/log1p(16) = 0.388
ret_mult = in-neighbours of A inside SCC = {O} = 1  -> s_loop = 0
indeg(A) after = 2 (M, O), outdeg(O) after = 1      -> s_fan = 0.315
raw = 0.45*0.556 + 1.10*0.556 + 0.30*0.315 + 1.40*1.0 + 0 + 0.60*0.388 = 2.590
score = 0.726
```

### Example 5: `N -> M` after `M->A`, `A->C`, `C->M`, `A->N`

```
A = {A, M, C, N}, D = {M, A, C, N}    16 pairs
M, A, C already form a cycle, so all pairs among them are reachable, plus each reaches N
  -> n_red = 12
N reaches nothing before -> (N,M)(N,A)(N,C)(N,N) new -> n_new = 4
cycle: M reaches N before, so N->M closes one. shortest M->A->N = 2 edges, len = 3
s_cycle = 1.0
SCC after = {M, A, C, N}, size 4      -> s_scc = log1p(3)/log1p(16) = 0.489
ret_mult = in-neighbours of M inside SCC = {C, N} = 2  -> s_loop = min(1, 1/2) = 0.5
s_fan = 0.315
raw = 0.45*0.460 + 1.10*0.734 + 0.30*0.315 + 1.40*1.0 + 1.60*0.5 + 0.60*0.489 = 3.601
score = 0.835
```

### Summary table

| Example | n_new | n_red | cycle_len | ret_mult | SCC | raw | score |
|---|---|---|---|---|---|---|---|
| 1 Isolated | 1 | 0 | - | - | 1 | 0.089 | **0.043** |
| 2 Extension | 2 | 0 | - | - | 1 | 0.141 | **0.068** |
| 3 Convergence | 1 | 1 | - | - | 1 | 0.402 | **0.182** |
| 4 Return | 6 | 6 | 3 | 1 | 3 | 2.590 | **0.726** |
| 5 Multi-loop | 4 | 12 | 3 | 2 | 4 | 3.601 | **0.835** |

Every required inequality holds with room to spare. Reproduce this table as a unit test
with tolerance 0.01 so any weight change surfaces immediately.

## Degenerate cases

The brief leaves these open and says to reason from the principle. Reason applied:

### Repeated edge (`u -> v` already live in the window)

A duplicate edge adds no new routing capacity, so it should not earn the full redundancy
term. But it is not innocent either: repeated flow inside an existing ring is exactly what
a laundering cycle looks like in operation.

```
if edge already exists:
    n_red = 0
    n_new = 0
    cycle, loop, scc terms are computed as normal but multiplied by REPEAT_EDGE_DAMPING
```

Consequence: a repeat of an ordinary edge scores near the floor, and a repeat of an edge
inside an established ring scores moderately. Both are defensible from the principle.

### Self transfer (`u == v`)

An entity paying itself is normally a booking artifact, not laundering. Treat as a cycle
of length 1 with reduced weight and no reachability delta:

```
n_new = n_red = 0
s_cycle = SELF_LOOP_CYCLE (0.5)
s_loop  = 0
s_scc   = computed normally
```

### Transaction already outside the window on arrival

`created_at <= watermark - W`. Score it against the current graph, then do **not** insert
it, because it would be expired immediately anyway. Inserting and instantly expiring it
would be equivalent in state but would burn a rebuild.

### Empty batch

Return `{"transactions": []}` with status 200.

## Optional temporal refinement (leave OFF by default)

Phase 1 is a structural phase but the diagnostics vocabulary includes
`TEMPORAL_DEVIATION`. The primary meaning of that category is window and ordering
correctness, so fix that first. If, and only if, `TEMPORAL_DEVIATION` persists after the
window logic is verified correct, enable a cycle-tightness multiplier:

```python
span = watermark - (oldest edge timestamp in the closing cycle)
temporal_mult = clamp(1.20 - 0.30 * (span / W), 0.90, 1.20)
# applied to the cycle and loop evidence only
```

A ring that completes in minutes is more suspicious than one that completes over twenty
hours. Gate it behind `config.ENABLE_TEMPORAL_MULTIPLIER = False` and A/B it against
diagnostics rather than shipping it blind.
