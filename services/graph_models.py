from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Set, Tuple


@dataclass
class StoredTx:
    tx_id: str
    from_id: str
    to_id: str
    amount: float
    created_at: float
    ip_address: Optional[str]
    device_id: Optional[str]
    payload_hash: str
    score: float


@dataclass
class EdgeState:
    tx_times: list[float] = field(default_factory=list)
    total_amount: float = 0.0
    ip_seen: Set[str] = field(default_factory=set)
    device_seen: Set[str] = field(default_factory=set)
    ip_absent_count: int = 0
    device_absent_count: int = 0

    @property
    def multiplicity(self) -> int:
        return len(self.tx_times)


@dataclass
class NodeState:
    ips: dict[str, int] = field(default_factory=dict)
    devices: dict[str, int] = field(default_factory=dict)
    tx_missing_ip: int = 0
    tx_missing_device: int = 0
    total_in: float = 0.0
    total_out: float = 0.0


@dataclass(frozen=True)
class Signals:
    n_new: int
    n_red: int
    indeg_v_after: int
    outdeg_u_after: int
    cycle_closed: bool
    cycle_len: Optional[int]
    scc_size: int
    ret_mult: int
    is_repeat_edge: bool
    is_self_loop: bool


@dataclass(frozen=True)
class IdentitySignals:
    shift: float
    drop: float
    share: float


@dataclass(frozen=True)
class ScoreBreakdown:
    score: float
    raw: float
    s_reach: float
    s_red: float
    s_fan: float
    s_cycle: float
    s_loop: float
    s_scc: float
    s_id_shift: float
    s_id_drop: float
    s_id_share: float
    signals: Signals
    temporal_mult: float
