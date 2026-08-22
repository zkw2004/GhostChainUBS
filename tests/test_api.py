from tests.helpers import tx


def test_health(client):
    response = client.get("/ghost-chains/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert client.get("/health").json() == {"status": "ok"}


def test_reset_echo(client):
    response = client.post("/ghost-chains/reset", json={"clearTransactions": True})
    assert response.status_code == 200
    assert response.json() == {"clearTransactions": True}
    skipped = client.post("/ghost-chains/reset", json={"clearTransactions": False})
    assert skipped.json() == {"clearTransactions": False}


def test_returns_one_score_per_transaction(client):
    response = client.post(
        "/ghost-chains/transactions",
        json={"transactions": [tx("t1", "M", "A")]},
    )
    assert response.status_code == 200
    body = response.json()["transactions"]
    assert len(body) == 1
    assert body[0]["txId"] == "t1"
    assert 0.0 <= body[0]["riskScore"] <= 1.0


def test_unknown_fields_ignored(client):
    payload = tx("u1", "M", "A", futureField=True, nested={"x": 1})
    response = client.post("/ghost-chains/transactions", json={"transactions": [payload]})
    assert response.status_code == 200
    assert response.json()["transactions"][0]["txId"] == "u1"


def test_missing_optionals_ok(client):
    payload = tx("o1", "M", "A")
    response = client.post("/ghost-chains/transactions", json={"transactions": [payload]})
    assert response.status_code == 200
    only_ip = tx("o2", "M", "B", minutes=1, ipAddress="203.0.113.4")
    only_dev = tx("o3", "M", "C", minutes=2, deviceId="dev_a")
    assert client.post("/ghost-chains/transactions", json={"transactions": [only_ip]}).status_code == 200
    assert client.post("/ghost-chains/transactions", json={"transactions": [only_dev]}).status_code == 200


def test_empty_batch(client):
    response = client.post("/ghost-chains/transactions", json={"transactions": []})
    assert response.status_code == 200
    assert response.json() == {"transactions": []}


def test_batch_order_preserved(client):
    batch = [tx(f"id{i}", f"A{i}", f"B{i}", minutes=i) for i in range(50)]
    response = client.post("/ghost-chains/transactions", json={"transactions": batch})
    body = response.json()["transactions"]
    assert [row["txId"] for row in body] == [item["txId"] for item in batch]
    assert all(0.0 <= row["riskScore"] <= 1.0 for row in body)


def test_malformed_transaction_does_not_abort_batch(client):
    batch = [
        tx("good1", "M", "A"),
        {"txId": "bad", "fromUserId": "X"},
        tx("good2", "A", "C", minutes=1),
    ]
    response = client.post("/ghost-chains/transactions", json={"transactions": batch})
    assert response.status_code == 200
    body = response.json()["transactions"]
    assert [row["txId"] for row in body] == ["good1", "bad", "good2"]
    assert body[1]["riskScore"] == 0.0
    assert body[2]["riskScore"] > body[0]["riskScore"]


def test_reset_isolates_state(client):
    first = client.post(
        "/ghost-chains/transactions",
        json={"transactions": [tx("t1", "M", "A"), tx("t2", "A", "C", minutes=1)]},
    ).json()["transactions"]
    client.post("/ghost-chains/reset", json={"clearTransactions": True})
    second = client.post(
        "/ghost-chains/transactions",
        json={"transactions": [tx("t1", "M", "A"), tx("t2", "A", "C", minutes=1)]},
    ).json()["transactions"]
    assert first == second
