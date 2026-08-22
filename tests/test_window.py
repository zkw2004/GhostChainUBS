from datetime import datetime, timedelta, timezone

from app.engine import RiskEngine
from app.graph import WindowedGraph
from app.models import StoredTx
from app.timeutil import Watermark, parse_iso
from tests.helpers import run, tx


def test_parse_formats():
    zulu = parse_iso("2026-06-08T12:00:00Z")
    offset = parse_iso("2026-06-08T20:00:00+08:00")
    fractional = parse_iso("2026-06-08T12:00:00.000Z")
    naive = parse_iso("2026-06-08T12:00:00")
    assert zulu == offset
    assert zulu == fractional
    assert zulu == naive


def test_watermark_monotonic():
    mark = Watermark(86400.0, inclusive=False)
    mark.advance(100.0)
    mark.advance(50.0)
    mark.advance(120.0)
    assert mark.value == 120.0
    mark.advance(90.0)
    assert mark.value == 120.0


def test_window_boundary_exclusive():
    mark = Watermark(86400.0, inclusive=False)
    mark.advance(86400.0)
    assert mark.is_expired(0.0) is True
    assert mark.is_expired(1.0) is False
    later = Watermark(86400.0, inclusive=False)
    later.advance(86400.0 + 1.0)
    assert later.is_expired(0.0) is True
    assert later.is_expired(1.0) is True


def test_edge_expires(engine):
    run(engine, tx("t1", "A", "B"), tx("t2", "B", "C", minutes=1))
    assert engine.graph.live_edge_count() == 2
    engine.score_batch([tx("late", "X", "Y", minutes=24 * 60 + 2)])
    assert engine.graph.has_edge(engine.graph.index_of("A") or -1, engine.graph.index_of("B") or -1) is False


def test_multi_tx_edge_survives_until_last_expires(engine):
    run(engine, tx("e1", "A", "B"), tx("e2", "A", "B", minutes=60))
    src = engine.graph.index_of("A")
    dest = engine.graph.index_of("B")
    assert engine.graph.has_edge(src, dest)
    engine.score_batch([tx("probe", "X", "Y", minutes=24 * 60 + 1)])
    src = engine.graph.index_of("A")
    dest = engine.graph.index_of("B")
    assert src is not None and dest is not None
    assert engine.graph.has_edge(src, dest)
    engine.score_batch([tx("probe2", "P", "Q", minutes=25 * 60 + 1)])
    assert engine.graph.index_of("A") is None


def test_node_index_recycled():
    graph = WindowedGraph()
    stored = StoredTx(
        tx_id="t1",
        from_id="A",
        to_id="B",
        amount=1.0,
        created_at=0.0,
        ip_address=None,
        device_id=None,
        payload_hash="h",
        score=0.0,
    )
    graph.add_transaction(stored)
    assert graph.capacity() >= 2
    graph.expire(10.0)
    assert graph.live_node_count() == 0
    assert graph.capacity() == 0


def test_expired_cycle_no_longer_contributes(engine):
    isolated = run(engine, tx("iso", "M", "A"))[0]
    engine.reset()
    run(
        engine,
        tx("t1", "A", "B"),
        tx("t2", "B", "C", minutes=1),
        tx("t3", "C", "A", minutes=2),
    )
    late = engine.score_batch([tx("t4", "C", "A", minutes=24 * 60 + 5)])[0]["riskScore"]
    assert abs(late - isolated) < 0.05
