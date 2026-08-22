from __future__ import annotations

import math
from typing import Optional, Set

from services.config import CFG, ScoringConfig
from services.graph_models import IdentitySignals, ScoreBreakdown, Signals
from services.reachability import BitsetReachability, bit, iter_bits, popcount
from services.windowed_graph import WindowedGraph


def extract_signals(
    graph: WindowedGraph,
    reach: BitsetReachability,
    src: int,
    dest: int,
) -> Signals:
    """Compute Phase 1 signals from the pre-insert graph plus the candidate edge.

    Does not mutate graph or reachability. Degrees, SCC size, and return
    multiplicity describe the structure the edge would create.
    """
    is_self_loop = src == dest
    is_repeat = graph.has_edge(src, dest)
    if is_self_loop:
        scc_mask = _post_insert_scc(reach, src, dest)
        return Signals(
            n_new=0,
            n_red=0,
            indeg_v_after=graph.in_degree(dest) + (0 if is_repeat else 1),
            outdeg_u_after=graph.out_degree(src) + (0 if is_repeat else 1),
            cycle_closed=True,
            cycle_len=1,
            scc_size=max(1, popcount(scc_mask)),
            ret_mult=_ret_mult(graph, dest, src, is_repeat, scc_mask),
            is_repeat_edge=is_repeat,
            is_self_loop=True,
        )

    up_mask = reach.ancestor_mask(src) | bit(src)
    down_mask = reach.descendant_mask(dest) | bit(dest)
    n_red = 0
    for walker in iter_bits(up_mask):
        n_red += popcount(reach.descendant_mask(walker) & down_mask)
    n_new = popcount(up_mask) * popcount(down_mask) - n_red
    if is_repeat:
        n_red = 0
        n_new = 0

    cycle_closed = bool(reach.descendant_mask(dest) & bit(src))
    cycle_len: Optional[int] = None
    if cycle_closed:
        distance = reach.shortest_path_len(dest, src)
        cycle_len = 1 + (distance if distance is not None else 0)

    scc_mask = _post_insert_scc(reach, src, dest)
    indeg = graph.in_degree(dest) + (0 if is_repeat else 1)
    outdeg = graph.out_degree(src) + (0 if is_repeat else 1)
    return Signals(
        n_new=n_new,
        n_red=n_red,
        indeg_v_after=indeg,
        outdeg_u_after=outdeg,
        cycle_closed=cycle_closed,
        cycle_len=cycle_len,
        scc_size=max(1, popcount(scc_mask)),
        ret_mult=_ret_mult(graph, dest, src, is_repeat, scc_mask),
        is_repeat_edge=is_repeat,
        is_self_loop=False,
    )


def extract_identity(
    graph: WindowedGraph,
    reach: BitsetReachability,
    src: int,
    dest: int,
    ip_address: Optional[str],
    device_id: Optional[str],
    cfg: ScoringConfig = CFG,
) -> IdentitySignals:
    """Identity anomalies in [0, 1]. Zero when there is no identity evidence."""
    upstream = set(iter_bits(reach.ancestor_mask(src))) | {src}
    local = graph.undirected_component(src) | graph.undirected_component(dest)

    shift_ip, drop_ip = _flow_anomaly(graph, upstream, ip_address, "ip", cfg)
    shift_dev, drop_dev = _flow_anomaly(graph, upstream, device_id, "device", cfg)
    shared_ip = _shared_disconnected(graph, local, ip_address, "ip", cfg)
    shared_dev = _shared_disconnected(graph, local, device_id, "device", cfg)

    shift = 1.0 - (1.0 - shift_ip) * (1.0 - shift_dev)
    drop = 1.0 - (1.0 - drop_ip) * (1.0 - drop_dev)
    share = 1.0 - (1.0 - shared_ip) * (1.0 - shared_dev)
    return IdentitySignals(shift=shift, drop=drop, share=share)


def _flow_anomaly(
    graph: WindowedGraph,
    upstream: Set[int],
    current: Optional[str],
    kind: str,
    cfg: ScoringConfig,
) -> tuple[float, float]:
    observed = graph.identities_on_nodes(upstream, kind)
    if current:
        if not observed:
            return 0.0, 0.0
        extra = 0 if current in observed else 1
        return _norm(float(len(observed) + extra - 1), cfg.CAP_IDENTITY), 0.0
    if observed:
        return 0.0, _norm(float(len(observed)), cfg.CAP_IDENTITY)
    return 0.0, 0.0


def _shared_disconnected(
    graph: WindowedGraph,
    local: Set[int],
    value: Optional[str],
    kind: str,
    cfg: ScoringConfig,
) -> float:
    if not value:
        return 0.0
    holders = (
        graph.ip_to_nodes.get(value, set())
        if kind == "ip"
        else graph.device_to_nodes.get(value, set())
    )
    foreign = set(holders) - local
    if not foreign:
        return 0.0
    components = 0
    remaining = set(foreign)
    while remaining:
        seed = remaining.pop()
        remaining -= graph.undirected_component(seed)
        components += 1
    return _norm(float(components), cfg.CAP_IDENTITY)


def _post_insert_scc(reach: BitsetReachability, src: int, dest: int) -> int:
    up_mask = reach.ancestor_mask(src) | bit(src)
    down_mask = reach.descendant_mask(dest) | bit(dest)
    desc_after = reach.descendant_mask(dest)
    if up_mask & bit(dest):
        desc_after |= down_mask
    anc_after = reach.ancestor_mask(dest) | up_mask
    return (desc_after & anc_after) | bit(dest)


def _ret_mult(
    graph: WindowedGraph,
    dest: int,
    src: int,
    is_repeat: bool,
    scc_mask: int,
) -> int:
    preds = set(graph.predecessors(dest))
    if not is_repeat:
        preds.add(src)
    return sum(1 for pred in sorted(preds) if scc_mask & bit(pred))


def combine(
    signals: Signals,
    cfg: ScoringConfig = CFG,
    temporal_span: Optional[float] = None,
    identity: Optional[IdentitySignals] = None,
) -> ScoreBreakdown:
    """Map signals onto [0, 1) with a strictly monotone exponential."""
    s_reach = _norm(float(signals.n_new), cfg.CAP_REACH)
    s_red = _norm(float(signals.n_red), cfg.CAP_RED)
    if not signals.cycle_closed:
        s_red = min(s_red, cfg.DAG_RED_CAP)
    fan = max(0, signals.indeg_v_after - 1) + max(0, signals.outdeg_u_after - 1)
    s_fan = _norm(float(fan), cfg.CAP_FAN)

    if signals.is_self_loop:
        s_cycle = cfg.SELF_LOOP_CYCLE
        s_loop = 0.0
    elif signals.cycle_closed and signals.cycle_len is not None:
        floor = cfg.CYCLE_LEN_FLOOR
        s_cycle = cfg.CYCLE_BASE + cfg.CYCLE_TIGHTNESS * (
            floor / max(floor, float(signals.cycle_len))
        )
        s_loop = min(1.0, (float(signals.ret_mult) - 1) / cfg.LOOP_SCALE)
    else:
        s_cycle = 0.0
        s_loop = 0.0

    # SCC / return-multiplicity describe a ring this edge forms. An ordinary
    # attachment onto a node that already sits in a large SCC must not inherit
    # that ring's size — that was inflating join-the-component edges toward
    # cycle scores in the evaluator stream (e.g. txn-19, txn-43, txn-67).
    if signals.cycle_closed:
        s_scc = _norm(float(max(0, signals.scc_size - 1)), cfg.CAP_SCC)
    else:
        s_scc = 0.0
    if signals.is_repeat_edge:
        s_cycle *= cfg.REPEAT_EDGE_DAMPING
        s_loop *= cfg.REPEAT_EDGE_DAMPING
        s_scc *= cfg.REPEAT_EDGE_DAMPING

    s_reach = min(1.0, max(0.0, s_reach))
    s_red = min(1.0, max(0.0, s_red))
    s_fan = min(1.0, max(0.0, s_fan))
    s_cycle = min(1.0, max(0.0, s_cycle))
    s_loop = min(1.0, max(0.0, s_loop))
    s_scc = min(1.0, max(0.0, s_scc))

    temporal_mult = 1.0
    if cfg.ENABLE_TEMPORAL_MULTIPLIER and signals.cycle_closed and temporal_span is not None:
        temporal_mult = _clamp(
            cfg.TEMPORAL_MULT_MAX
            - cfg.TEMPORAL_SPAN_COEFF * (temporal_span / cfg.WINDOW_SECONDS),
            cfg.TEMPORAL_MULT_MIN,
            cfg.TEMPORAL_MULT_MAX,
        )
        s_cycle *= temporal_mult
        s_loop *= temporal_mult

    s_id_shift = 0.0
    s_id_drop = 0.0
    s_id_share = 0.0
    if identity is not None:
        s_id_shift = min(1.0, max(0.0, identity.shift))
        s_id_drop = min(1.0, max(0.0, identity.drop))
        s_id_share = min(1.0, max(0.0, identity.share))

    raw = (
        cfg.W_REACH * s_reach
        + cfg.W_RED * s_red
        + cfg.W_FAN * s_fan
        + cfg.W_CYCLE * s_cycle
        + cfg.W_LOOP * s_loop
        + cfg.W_SCC * s_scc
        + cfg.W_ID_SHIFT * s_id_shift
        + cfg.W_ID_DROP * s_id_drop
        + cfg.W_ID_SHARE * s_id_share
    )
    score = 1.0 - math.exp(-raw / cfg.SCALE)
    score = round(min(1.0, max(0.0, score)), cfg.SCORE_DECIMALS)
    return ScoreBreakdown(
        score=score,
        raw=raw,
        s_reach=s_reach,
        s_red=s_red,
        s_fan=s_fan,
        s_cycle=s_cycle,
        s_loop=s_loop,
        s_scc=s_scc,
        s_id_shift=s_id_shift,
        s_id_drop=s_id_drop,
        s_id_share=s_id_share,
        signals=signals,
        temporal_mult=temporal_mult,
    )


def _norm(value: float, cap: float) -> float:
    if value <= 0 or cap <= 0:
        return 0.0
    return math.log1p(value) / math.log1p(cap)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
