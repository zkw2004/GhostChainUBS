from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Sequence, Tuple

from models.transaction import Transaction
from services.risk_engine import RiskEngine
from services.risk_parameters import RiskParameters

T0 = datetime(2026, 6, 8, 12, 0, 0, tzinfo=timezone.utc)
LOOKBACK_MINUTES = 24 * 60

Edge = Tuple[str, str]


@dataclass(frozen=True)
class Scenario:
    """One synthetic graph, scored from a clean engine on the last transaction."""

    name: str
    family: str
    transactions: Tuple[Transaction, ...]
    split: str


@dataclass
class ScenarioResult:
    scenario: Scenario
    score: float
    engine: RiskEngine


def make_transaction(
    tx_id: str,
    source: str,
    dest: str,
    minutes: int,
    amount: float = 100.0,
) -> Transaction:
    created = T0 + timedelta(minutes=minutes)
    return Transaction.from_dict(
        {
            "txId": tx_id,
            "fromUserId": source,
            "toUserId": dest,
            "amount": amount,
            "createdAt": created.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
    )


def _node(prefix: str, label: str) -> str:
    return f"{prefix}_{label}"


def _from_edges(
    name: str,
    family: str,
    split: str,
    prefix: str,
    edges: Sequence[Edge],
    minutes: Optional[Sequence[int]] = None,
) -> Scenario:
    if minutes is None:
        minutes = list(range(len(edges)))
    transactions = tuple(
        make_transaction(f"{prefix}_{name}_{index}", source, dest, minute)
        for index, ((source, dest), minute) in enumerate(zip(edges, minutes))
    )
    return Scenario(name=name, family=family, transactions=transactions, split=split)


def _noise_edges(prefix: str, count: int = 3) -> List[Edge]:
    labels = ("X", "Y", "M", "N", "P", "Q", "R", "S")
    edges = []
    for index in range(count):
        src = _node(prefix, labels[2 * index])
        dest = _node(prefix, labels[2 * index + 1])
        edges.append((src, dest))
    return edges


def isolated_scenario(split: str, prefix: str, noise: bool = False) -> Scenario:
    a, b = _node(prefix, "A"), _node(prefix, "B")
    edges: List[Edge] = _noise_edges(prefix) if noise else []
    edges.append((a, b))
    return _from_edges(f"{prefix}_isolated", "isolated", split, prefix, edges)


def extension_scenario(split: str, prefix: str, noise: bool = False) -> Scenario:
    a, b, c = _node(prefix, "A"), _node(prefix, "B"), _node(prefix, "C")
    edges: List[Edge] = _noise_edges(prefix) if noise else []
    edges.extend([(a, b), (b, c)])
    return _from_edges(f"{prefix}_extension", "extension", split, prefix, edges)


def chain_scenario(split: str, prefix: str, length: int = 5, noise: bool = False) -> Scenario:
    labels = [chr(ord("A") + index) for index in range(length)]
    nodes = [_node(prefix, label) for label in labels]
    edges: List[Edge] = _noise_edges(prefix) if noise else []
    edges.extend((nodes[index], nodes[index + 1]) for index in range(length - 1))
    return _from_edges(f"{prefix}_chain{length}", "chain", split, prefix, edges)


def convergence_scenario(
    split: str,
    prefix: str,
    extra_route: bool = False,
    long_branches: bool = False,
    noise: bool = False,
) -> Scenario:
    a = _node(prefix, "A")
    b = _node(prefix, "B")
    c = _node(prefix, "C")
    d = _node(prefix, "D")
    sink = _node(prefix, "Z")
    edges: List[Edge] = _noise_edges(prefix) if noise else []
    if long_branches:
        mid_b = _node(prefix, "B2")
        mid_c = _node(prefix, "C2")
        edges.extend([(a, b), (b, mid_b), (a, c), (c, mid_c), (mid_b, sink), (mid_c, sink)])
    else:
        edges.extend([(a, b), (a, c), (b, sink)])
        if extra_route:
            edges.append((a, d))
            edges.append((d, sink))
        edges.append((c, sink))
    name = f"{prefix}_convergence"
    if extra_route:
        name += "_tri"
    if long_branches:
        name += "_long"
    return _from_edges(name, "convergence", split, prefix, edges)


def cycle_scenario(split: str, prefix: str, length: int = 3, noise: bool = False) -> Scenario:
    labels = [chr(ord("A") + index) for index in range(length)]
    nodes = [_node(prefix, label) for label in labels]
    edges: List[Edge] = _noise_edges(prefix) if noise else []
    edges.extend((nodes[index], nodes[index + 1]) for index in range(length - 1))
    edges.append((nodes[-1], nodes[0]))
    return _from_edges(f"{prefix}_cycle{length}", "cycle", split, prefix, edges)


def return_scenario(split: str, prefix: str, noise: bool = False) -> Scenario:
    a, b, c, d = (
        _node(prefix, "A"),
        _node(prefix, "B"),
        _node(prefix, "C"),
        _node(prefix, "D"),
    )
    edges: List[Edge] = _noise_edges(prefix) if noise else []
    edges.extend([(a, b), (b, c), (c, d), (d, b)])
    return _from_edges(f"{prefix}_return", "return", split, prefix, edges)


def multiloop_scenario(split: str, prefix: str, third_loop: bool = False, noise: bool = False) -> Scenario:
    a, b, c, d, e = (
        _node(prefix, "A"),
        _node(prefix, "B"),
        _node(prefix, "C"),
        _node(prefix, "D"),
        _node(prefix, "E"),
    )
    edges: List[Edge] = _noise_edges(prefix) if noise else []
    edges.extend([(a, b), (b, c), (c, a), (b, d), (d, a)])
    if third_loop:
        edges.extend([(b, e), (e, a)])
    name = f"{prefix}_multiloop"
    if third_loop:
        name += "_tri"
    return _from_edges(name, "multiloop", split, prefix, edges)


def duplicate_scenario(split: str, prefix: str) -> Scenario:
    a, b = _node(prefix, "A"), _node(prefix, "B")
    edges = [(a, b), (a, b)]
    return _from_edges(f"{prefix}_duplicate", "duplicate", split, prefix, edges)


def expired_cycle_scenario(split: str, prefix: str) -> Scenario:
    a, b, c = _node(prefix, "A"), _node(prefix, "B"), _node(prefix, "C")
    edges = [(a, b), (b, c), (c, a)]
    minutes = [0, 1, LOOKBACK_MINUTES + 5]
    return _from_edges(
        f"{prefix}_expired_cycle",
        "expired_cycle",
        split,
        prefix,
        edges,
        minutes=minutes,
    )


def generate_scenarios(split: str, variants: int = 4) -> List[Scenario]:
    """Deterministic train/validation suites with renamed nodes and mild topology changes."""
    if split not in {"train", "val"}:
        raise ValueError("split must be 'train' or 'val'")

    scenarios: List[Scenario] = []
    tag = "tr" if split == "train" else "va"
    # Validation uses longer ordinary chains and more extra routes so we are
    # not scoring the exact same layouts we optimized on.
    chain_length = 4 if split == "train" else 6
    cycle_length = 3 if split == "train" else 4

    for index in range(variants):
        prefix = f"{tag}{index}"
        noise = index % 2 == 1
        scenarios.append(isolated_scenario(split, prefix, noise=noise))
        scenarios.append(extension_scenario(split, prefix, noise=noise))
        scenarios.append(chain_scenario(split, prefix, length=chain_length, noise=noise))
        scenarios.append(
            convergence_scenario(
                split,
                prefix,
                extra_route=(index % 3 == 0),
                long_branches=(split == "val" and index % 2 == 0),
                noise=noise,
            )
        )
        scenarios.append(cycle_scenario(split, prefix, length=cycle_length, noise=noise))
        scenarios.append(return_scenario(split, prefix, noise=noise))
        scenarios.append(
            multiloop_scenario(split, prefix, third_loop=(index == variants - 1), noise=noise)
        )
        scenarios.append(duplicate_scenario(split, prefix))
        scenarios.append(expired_cycle_scenario(split, prefix))
    return scenarios


def run_scenario(scenario: Scenario, params: RiskParameters) -> ScenarioResult:
    """Score one scenario from a fresh production RiskEngine. Does not touch HTTP state."""
    engine = RiskEngine(params)
    score = 0.0
    for transaction in scenario.transactions:
        score = engine.process_one(transaction)
    return ScenarioResult(scenario=scenario, score=score, engine=engine)


def representative_score(results: Sequence[ScenarioResult], family: str) -> Optional[float]:
    matched = [item.score for item in results if item.scenario.family == family]
    if not matched:
        return None
    return sum(matched) / len(matched)
