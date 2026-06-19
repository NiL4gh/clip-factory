"""Regression tests for the post-strategy hang.

Root cause: /api/results returned the full word_timestamps array (1-2 MB for
long videos), which was polled every 2s and stampeded a flaky tunnel into a
total stall. word_timestamps must be served by a separate, on-demand endpoint
so the frequently-polled /api/results payload stays small.
"""
import sys
sys.argv = ["test"]

from fastapi.testclient import TestClient
from server.main import app, _state

client = TestClient(app)


def _seed_state_with_big_timestamps(n=5000):
    _state["is_strategizing"] = False
    _state["is_rendering"] = False
    _state["current_url"] = "https://youtu.be/test123"
    _state["clips"] = [{"title": "TEST CLIP", "start_time": 1.0, "end_time": 5.0}]
    _state["word_timestamps"] = [
        {"word": f"w{i}", "start": i * 0.3, "end": i * 0.3 + 0.2} for i in range(n)
    ]


def test_results_excludes_word_timestamps():
    """The polled /api/results must NOT carry the heavy word_timestamps blob."""
    _seed_state_with_big_timestamps()
    resp = client.get("/api/results")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "done"
    assert data["clips"], "clips should still be present"
    # The whole point of the fix: word_timestamps is gone from this payload.
    assert "word_timestamps" not in data or not data["word_timestamps"], (
        "word_timestamps must not be returned by /api/results (causes the hang)"
    )


def test_word_timestamps_available_via_dedicated_endpoint():
    """The sentence-exclusion feature still gets its data, just on demand."""
    _seed_state_with_big_timestamps(n=4321)
    resp = client.get("/api/word_timestamps")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["word_timestamps"]) == 4321
    assert data["word_timestamps"][0]["word"] == "w0"
