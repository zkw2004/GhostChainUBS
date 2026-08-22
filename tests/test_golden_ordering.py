from tests.helpers import run, tx

EX1 = [("t1", "M", "A")]
EX2 = [("t1", "M", "A"), ("t2", "A", "C")]
EX3 = [("t1", "M", "A"), ("t2", "M", "H"), ("t3", "A", "S"), ("t4", "H", "S")]
EX4 = [("t1", "M", "A"), ("t2", "A", "C"), ("t3", "C", "O"), ("t4", "O", "A")]
EX5 = [("t1", "M", "A"), ("t2", "A", "C"), ("t3", "C", "M"), ("t4", "A", "N"), ("t5", "N", "M")]

EXPECTED_SIGNALS = {
    "EX1": dict(n_new=1, n_red=0, cycle_len=None, ret_mult=0, scc_size=1),
    "EX2": dict(n_new=2, n_red=0, cycle_len=None, ret_mult=0, scc_size=1),
    "EX3": dict(n_new=1, n_red=1, cycle_len=None, ret_mult=0, scc_size=1),
    "EX4": dict(n_new=6, n_red=6, cycle_len=3, ret_mult=1, scc_size=3),
    "EX5": dict(n_new=4, n_red=12, cycle_len=3, ret_mult=2, scc_size=4),
}

EXPECTED_SCORES = {
    "EX1": 0.043,
    "EX2": 0.068,
    "EX3": 0.182,
    "EX4": 0.726,
    "EX5": 0.835,
}


def _edges_to_tx(edges):
    return [tx(tid, frm, to, minutes=index) for index, (tid, frm, to) in enumerate(edges)]


def last_score(engine, edges):
    engine.reset()
    return run(engine, *_edges_to_tx(edges))[-1]


def last_signals(engine, edges):
    engine.reset()
    items = _edges_to_tx(edges)
    if len(items) > 1:
        run(engine, *items[:-1])
    last = items[-1]
    return engine.peek_signals(last["fromUserId"], last["toUserId"])


def test_signal_values_match_spec(engine):
    cases = [
        ("EX1", EX1),
        ("EX2", EX2),
        ("EX3", EX3),
        ("EX4", EX4),
        ("EX5", EX5),
    ]
    for name, edges in cases:
        signals = last_signals(engine, edges)
        expected = EXPECTED_SIGNALS[name]
        assert signals.n_new == expected["n_new"], name
        assert signals.n_red == expected["n_red"], name
        assert signals.cycle_len == expected["cycle_len"], name
        assert signals.ret_mult == expected["ret_mult"], name
        assert signals.scc_size == expected["scc_size"], name


def test_five_example_scores(engine):
    for name, edges in [
        ("EX1", EX1),
        ("EX2", EX2),
        ("EX3", EX3),
        ("EX4", EX4),
        ("EX5", EX5),
    ]:
        score = last_score(engine, edges)
        assert abs(score - EXPECTED_SCORES[name]) < 0.01, (name, score)


def test_required_inequalities(engine):
    s1 = last_score(engine, EX1)
    s2 = last_score(engine, EX2)
    s3 = last_score(engine, EX3)
    s4 = last_score(engine, EX4)
    s5 = last_score(engine, EX5)
    scores = [s1, s2, s3, s4, s5]
    assert s1 == min(scores)
    assert s2 > s1 + 0.01
    assert s3 > s2 + 0.05
    assert s4 > s3 + 0.05
    assert s4 - s2 > 0.30
    assert s5 - s4 > 0.05


def test_batch_matches_streaming(engine):
    items = _edges_to_tx(EX5)
    streamed = run(engine, *items)
    engine.reset()
    batched = [row["riskScore"] for row in engine.score_batch(items)]
    assert streamed == batched


def test_coherence_disjoint_components_identical(engine):
    a = last_score(engine, [("t1", "M", "A")])
    b = last_score(engine, [("t1", "X", "Y")])
    assert abs(a - b) < 1e-9


def test_coherence_locality(engine):
    empty = last_score(engine, [("t1", "M", "A")])
    engine.reset()
    filler = [tx(f"n{i}", f"X{i}", f"Y{i}", minutes=i) for i in range(8)]
    run(engine, *filler)
    dense = engine.score_batch([tx("t1", "M", "A", minutes=20)])[0]["riskScore"]
    assert abs(empty - dense) < 1e-9


def test_coherence_shorter_cycle_higher(engine):
    short_edges = [("t1", "A", "B"), ("t2", "B", "C"), ("t3", "C", "A")]
    long_edges = [
        ("t1", "A", "B"),
        ("t2", "B", "C"),
        ("t3", "C", "D"),
        ("t4", "D", "E"),
        ("t5", "E", "F"),
        ("t6", "F", "A"),
    ]
    short_sig = last_signals(engine, short_edges)
    long_sig = last_signals(engine, long_edges)
    assert short_sig.cycle_len is not None and long_sig.cycle_len is not None
    assert short_sig.cycle_len < long_sig.cycle_len
    from app.config import CFG
    from app.scoring import combine

    short_cycle = combine(short_sig, CFG).s_cycle
    long_cycle = combine(long_sig, CFG).s_cycle
    assert short_cycle > long_cycle + 0.01


def test_coherence_more_return_paths_higher(engine):
    two = last_score(
        engine,
        [
            ("t1", "A", "B"),
            ("t2", "B", "C"),
            ("t3", "C", "A"),
            ("t4", "B", "D"),
            ("t5", "D", "A"),
        ],
    )
    three = last_score(
        engine,
        [
            ("t1", "A", "B"),
            ("t2", "B", "C"),
            ("t3", "C", "A"),
            ("t4", "B", "D"),
            ("t5", "D", "A"),
            ("t6", "B", "E"),
            ("t7", "E", "A"),
        ],
    )
    assert three > two + 0.01


def test_coherence_fan_in(engine):
    fan2 = last_score(
        engine,
        [("t1", "A", "Z"), ("t2", "B", "Z")],
    )
    fan5 = last_score(
        engine,
        [
            ("t1", "A", "Z"),
            ("t2", "B", "Z"),
            ("t3", "C", "Z"),
            ("t4", "D", "Z"),
            ("t5", "E", "Z"),
        ],
    )
    assert fan5 > fan2 + 0.01


def test_coherence_chain_monotonic(engine):
    edges = [("t1", "A", "B"), ("t2", "B", "C"), ("t3", "C", "D"), ("t4", "D", "E")]
    engine.reset()
    scores = run(engine, *_edges_to_tx(edges))
    for left, right in zip(scores, scores[1:]):
        assert right > left


def test_coherence_repeat_ordinary_lower(engine):
    engine.reset()
    first = engine.score_batch([tx("a", "M", "A")])[0]["riskScore"]
    second = engine.score_batch([tx("b", "M", "A", minutes=1)])[0]["riskScore"]
    assert second < first


def test_coherence_self_loop_between_isolated_and_cycle(engine):
    isolated = last_score(engine, [("t1", "M", "A")])
    self_loop = last_score(engine, [("t1", "X", "X")])
    cycle = last_score(
        engine,
        [("t1", "A", "B"), ("t2", "B", "C"), ("t3", "C", "A")],
    )
    assert isolated < self_loop < cycle


def test_coherence_expired_cycle_drops(engine):
    closing = last_score(
        engine,
        [("t1", "A", "B"), ("t2", "B", "C"), ("t3", "C", "A")],
    )
    engine.reset()
    run(
        engine,
        tx("t1", "A", "B", minutes=0),
        tx("t2", "B", "C", minutes=1),
        tx("t3", "C", "A", minutes=2),
    )
    late = engine.score_batch(
        [tx("t4", "C", "A", minutes=24 * 60 + 5)]
    )[0]["riskScore"]
    assert late + 0.2 < closing


def test_coherence_diamond_beats_tree(engine):
    diamond = last_score(
        engine,
        [("t1", "M", "A"), ("t2", "M", "H"), ("t3", "A", "S"), ("t4", "H", "S")],
    )
    tree = last_score(
        engine,
        [("t1", "M", "A"), ("t2", "M", "H"), ("t3", "A", "S"), ("t4", "H", "T")],
    )
    assert diamond > tree + 0.01
