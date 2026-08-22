from __future__ import annotations

import os
from dataclasses import dataclass


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    return default if raw is None else float(raw)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return default if raw is None else int(raw)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_str(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class ScoringConfig:
    """Every tunable constant. Change weights here (or via GC_* env vars)."""

    WINDOW_SECONDS: float = 86400.0
    # Inclusive matches "the most recent 24 hours": an edge at exactly W is still live.
    # The v8 exclusive hardcode made hf-temporal01-tx6 look like a cold extension.
    WINDOW_BOUNDARY_INCLUSIVE: bool = True
    MAX_BITSET_NODES: int = 8000
    ENABLE_TEMPORAL_MULTIPLIER: bool = False
    CONFLICTING_PAYLOAD_MODE: str = "return_original"

    CAP_REACH: float = 32.0
    CAP_RED: float = 32.0
    CAP_FAN: float = 8.0
    CAP_SCC: float = 16.0
    CAP_IDENTITY: float = 8.0

    W_REACH: float = 0.45
    W_RED: float = 1.10
    W_FAN: float = 0.30
    W_CYCLE: float = 1.40
    W_LOOP: float = 1.60
    W_SCC: float = 0.60
    W_ID_SHIFT: float = 0.50
    W_ID_DROP: float = 0.40
    W_ID_SHARE: float = 0.20

    SCALE: float = 2.0
    REPEAT_EDGE_DAMPING: float = 0.65
    SELF_LOOP_CYCLE: float = 0.25
    # Raw n_red grows with |A|×|D| and saturates on any large DAG bridge. A
    # non-cycle must not be allowed to spend the full redundancy budget — that
    # is what pushed txn-30/35/54 into the cycle band (0.53–0.55). Past the knee
    # the tail keeps them ordered instead of tied flat.
    DAG_RED_CAP: float = 0.25
    DAG_RED_TAIL: float = 0.10

    CYCLE_LEN_FLOOR: float = 3.0
    CYCLE_BASE: float = 0.5
    CYCLE_TIGHTNESS: float = 0.5
    LOOP_SCALE: float = 2.0

    TEMPORAL_MULT_MAX: float = 1.20
    TEMPORAL_MULT_MIN: float = 0.90
    TEMPORAL_SPAN_COEFF: float = 0.30

    SCORE_DECIMALS: int = 6

    @classmethod
    def from_env(cls) -> "ScoringConfig":
        base = cls()
        return cls(
            WINDOW_SECONDS=_env_float("GC_WINDOW_SECONDS", base.WINDOW_SECONDS),
            WINDOW_BOUNDARY_INCLUSIVE=_env_bool(
                "GC_WINDOW_BOUNDARY_INCLUSIVE", base.WINDOW_BOUNDARY_INCLUSIVE
            ),
            MAX_BITSET_NODES=_env_int("GC_MAX_BITSET_NODES", base.MAX_BITSET_NODES),
            ENABLE_TEMPORAL_MULTIPLIER=_env_bool(
                "GC_ENABLE_TEMPORAL_MULTIPLIER", base.ENABLE_TEMPORAL_MULTIPLIER
            ),
            CONFLICTING_PAYLOAD_MODE=_env_str(
                "GC_CONFLICTING_PAYLOAD_MODE", base.CONFLICTING_PAYLOAD_MODE
            ),
            CAP_REACH=_env_float("GC_CAP_REACH", base.CAP_REACH),
            CAP_RED=_env_float("GC_CAP_RED", base.CAP_RED),
            CAP_FAN=_env_float("GC_CAP_FAN", base.CAP_FAN),
            CAP_SCC=_env_float("GC_CAP_SCC", base.CAP_SCC),
            CAP_IDENTITY=_env_float("GC_CAP_IDENTITY", base.CAP_IDENTITY),
            W_REACH=_env_float("GC_W_REACH", base.W_REACH),
            W_RED=_env_float("GC_W_RED", base.W_RED),
            W_FAN=_env_float("GC_W_FAN", base.W_FAN),
            W_CYCLE=_env_float("GC_W_CYCLE", base.W_CYCLE),
            W_LOOP=_env_float("GC_W_LOOP", base.W_LOOP),
            W_SCC=_env_float("GC_W_SCC", base.W_SCC),
            W_ID_SHIFT=_env_float("GC_W_ID_SHIFT", base.W_ID_SHIFT),
            W_ID_DROP=_env_float("GC_W_ID_DROP", base.W_ID_DROP),
            W_ID_SHARE=_env_float("GC_W_ID_SHARE", base.W_ID_SHARE),
            SCALE=_env_float("GC_SCALE", base.SCALE),
            REPEAT_EDGE_DAMPING=_env_float(
                "GC_REPEAT_EDGE_DAMPING", base.REPEAT_EDGE_DAMPING
            ),
            SELF_LOOP_CYCLE=_env_float("GC_SELF_LOOP_CYCLE", base.SELF_LOOP_CYCLE),
            DAG_RED_CAP=_env_float("GC_DAG_RED_CAP", base.DAG_RED_CAP),
            DAG_RED_TAIL=_env_float("GC_DAG_RED_TAIL", base.DAG_RED_TAIL),
            CYCLE_LEN_FLOOR=_env_float("GC_CYCLE_LEN_FLOOR", base.CYCLE_LEN_FLOOR),
            CYCLE_BASE=_env_float("GC_CYCLE_BASE", base.CYCLE_BASE),
            CYCLE_TIGHTNESS=_env_float("GC_CYCLE_TIGHTNESS", base.CYCLE_TIGHTNESS),
            LOOP_SCALE=_env_float("GC_LOOP_SCALE", base.LOOP_SCALE),
            TEMPORAL_MULT_MAX=_env_float("GC_TEMPORAL_MULT_MAX", base.TEMPORAL_MULT_MAX),
            TEMPORAL_MULT_MIN=_env_float("GC_TEMPORAL_MULT_MIN", base.TEMPORAL_MULT_MIN),
            TEMPORAL_SPAN_COEFF=_env_float(
                "GC_TEMPORAL_SPAN_COEFF", base.TEMPORAL_SPAN_COEFF
            ),
            SCORE_DECIMALS=_env_int("GC_SCORE_DECIMALS", base.SCORE_DECIMALS),
        )


CFG = ScoringConfig.from_env()
