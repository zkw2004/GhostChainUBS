import pytest
from fastapi.testclient import TestClient

from app.engine import RiskEngine
from app.main import app, engine as app_engine


@pytest.fixture
def engine():
    inst = RiskEngine()
    yield inst
    inst.reset()


@pytest.fixture
def client():
    app_engine.reset()
    with TestClient(app) as test_client:
        yield test_client
    app_engine.reset()
