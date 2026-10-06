from __future__ import annotations

from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app


def _fake_db():
    class _Session:
        def execute(self, *a, **kw):
            class _Result:
                def all(self):
                    return []
            return _Result()
        def close(self):
            pass
    yield _Session()


app.dependency_overrides[get_db] = _fake_db
client = TestClient(app)


def test_health_returns_ok():
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["db"] == "connected"
