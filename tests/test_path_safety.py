"""Ids and hashes become filesystem path segments — traversal must die at
the store/gitstore path builders, and surface as 4xx over HTTP."""
import pytest
from fastapi.testclient import TestClient

from mlparty.core import MlParty
from mlparty.http_api import build_app
from mlparty.store import StoreError, safe_id, safe_sha256

TOKEN = "test-token-123"

GOOD_SHA = "a" * 64


def test_safe_id_accepts_real_ids():
    assert safe_id("01M2JV1FZX8QRST0ABCDEFGHJK") == "01M2JV1FZX8QRST0ABCDEFGHJK"
    assert safe_id("exp_1-b") == "exp_1-b"


@pytest.mark.parametrize("bad", ["..", ".", "a/b", "a\\b", "", "x" * 129, "a.b", "../x"])
def test_safe_id_rejects_traversal(bad):
    with pytest.raises(StoreError):
        safe_id(bad)


@pytest.mark.parametrize("bad", ["..", "", "A" * 64, "a" * 63, "a" * 64 + "a", "..%2fx"])
def test_safe_sha256_rejects_non_hex(bad):
    with pytest.raises(StoreError):
        safe_sha256(bad)


def test_store_path_builders_reject(tmp_path):
    party = MlParty.init(tmp_path / ".mlparty")
    with pytest.raises(StoreError):
        party.store.run_dir("..")
    with pytest.raises(StoreError):
        party.store.artifact_path("..")
    with pytest.raises(StoreError):
        party.git.repo_path("../../evil")
    assert party.store.heartbeat_at("..") is None
    assert not (tmp_path / "metrics.jsonl").exists()


def test_http_ingest_rejects_traversal_ids(tmp_path):
    MlParty.init(tmp_path / ".mlparty")
    c = TestClient(build_app(tmp_path / ".mlparty", write_token=TOKEN))
    c.headers["Authorization"] = f"Bearer {TOKEN}"

    r = c.post("/api/ingest/metrics/%2e%2e", json={"expected_offset": 0, "chunk": ""})
    assert r.status_code in (404, 422)
    r = c.post("/api/ingest/heartbeat/%2e%2e")
    assert r.status_code in (404, 422)
    r = c.put("/api/ingest/artifacts/not-a-sha", content=b"x")
    assert r.status_code == 422
    r = c.post("/api/ingest/git/%2e%2e/missing", json={"shas": []})
    assert r.status_code in (404, 422)
    r = c.get(f"/api/artifacts/{GOOD_SHA}")
    assert r.status_code == 404  # valid shape, simply not present
    assert not (tmp_path / "metrics.jsonl").exists()
    assert not (tmp_path / "evil.git").exists()
