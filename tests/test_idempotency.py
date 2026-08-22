from tests.helpers import tx


def test_identical_payload_replay(engine):
    first = engine.score_batch([tx("dup", "A", "B")])[0]["riskScore"]
    nodes = engine.graph.live_node_count()
    edges = engine.graph.live_edge_count()
    water = engine.watermark.value
    second = engine.score_batch([tx("dup", "A", "B")])[0]["riskScore"]
    assert first == second
    assert engine.graph.live_node_count() == nodes
    assert engine.graph.live_edge_count() == edges
    assert engine.watermark.value == water


def test_conflicting_payload_returns_original(engine, caplog):
    first = engine.score_batch([tx("dup", "A", "B")])[0]["riskScore"]
    edges = engine.graph.live_edge_count()
    second = engine.score_batch([tx("dup", "A", "C")])[0]["riskScore"]
    assert second == first
    assert engine.graph.live_edge_count() == edges


def test_duplicate_inside_same_batch(engine):
    payload = tx("same", "A", "B")
    scores = engine.score_batch([payload, payload])
    assert scores[0]["riskScore"] == scores[1]["riskScore"]
    assert engine.graph.live_edge_count() == 1


def test_duplicate_after_reset_is_new(engine):
    engine.score_batch([tx("dup", "A", "B")])
    engine.reset()
    again = engine.score_batch([tx("dup", "A", "B")])[0]["riskScore"]
    assert again >= 0.0
    assert engine.graph.live_edge_count() == 1
