import pytest
from fastapi.testclient import TestClient

from mlparty.auth import AuthStore
from mlparty.core import MlParty
from mlparty.http_api import build_app


@pytest.fixture
def setup(tmp_path):
    src = tmp_path / "proj"
    src.mkdir()
    root = src / ".mlparty"
    party = MlParty.init(root)
    exp = party.experiment_ensure("p", "e", created_by="test")
    auth = AuthStore(root)
    auth.user_add("admin", "adminpass1", role="admin")
    auth.user_add("vera", "viewerpass", role="viewer")
    auth.user_add("will", "writerpass", role="writer")
    return party, auth, exp, build_app(root, write_token="legacy-token")


def login(app, username, password):
    c = TestClient(app)
    r = c.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200
    return c


def test_reads_gated_when_auth_enabled(setup):
    _, _, exp, app = setup
    c = TestClient(app)
    assert c.get("/api/nodes").status_code == 401
    assert c.get(f"/api/nodes/{exp['id']}").status_code == 401
    assert c.get("/api/boards").status_code == 401
    # open paths stay open: probes, login bootstrap, static helper
    assert c.get("/api/health").status_code == 200
    me = c.get("/api/auth/me").json()
    assert me == {"auth_enabled": True, "user": None}
    assert c.get("/boards-lib/mlparty.js").status_code == 200


def test_login_logout_flow(setup):
    _, _, _exp, app = setup
    c = TestClient(app)
    assert c.post("/api/auth/login",
                  json={"username": "vera", "password": "wrong"}).status_code == 401
    c = login(app, "vera", "viewerpass")
    assert c.get("/api/nodes").status_code == 200
    me = c.get("/api/auth/me").json()
    assert me["user"] == {"username": "vera", "role": "viewer"}
    c.post("/api/auth/logout")
    assert c.get("/api/nodes").status_code == 401


def test_roles_enforced(setup):
    _, _, exp, app = setup
    viewer = login(app, "vera", "viewerpass")
    writer = login(app, "will", "writerpass")

    r = viewer.post(f"/api/nodes/{exp['id']}/annotate", json={"text": "by ear: good"})
    assert r.status_code == 403
    r = writer.post(f"/api/nodes/{exp['id']}/annotate",
                    json={"text": "by ear: good", "created_by": "spoofed"})
    assert r.status_code == 200
    # created_by is the authenticated user, not what the body claimed
    node = writer.get(f"/api/nodes/{exp['id']}").json()["node"]
    assert node["annotations"][-1]["created_by"] == "will"

    assert viewer.post("/api/ingest/events", json={"events": []}).status_code == 403
    assert writer.post("/api/ingest/events", json={"events": []}).status_code == 200


def test_per_user_tokens_and_legacy_token_ignored(setup):
    _, auth, _, app = setup
    c = TestClient(app)
    # legacy single token is dead once users exist
    r = c.post("/api/ingest/events", json={"events": []},
               headers={"Authorization": "Bearer legacy-token"})
    assert r.status_code == 401

    tok = auth.token_create("will", "ci")["token"]
    hdr = {"Authorization": f"Bearer {tok}"}
    assert c.post("/api/ingest/events", json={"events": []}, headers=hdr).status_code == 200
    assert c.get("/api/nodes", headers=hdr).status_code == 200

    viewer_tok = auth.token_create("vera", "ro")["token"]
    r = c.post("/api/ingest/events", json={"events": []},
               headers={"Authorization": f"Bearer {viewer_tok}"})
    assert r.status_code == 403

    auth.token_revoke(auth.user_get("will")["tokens"][0]["id"])
    assert c.post("/api/ingest/events", json={"events": []}, headers=hdr).status_code == 401


def test_board_token_flow(setup):
    party, _, exp, app = setup
    ref = party.store.put_artifact_bytes(b"<html>board</html>", "b.html",
                                         media_type="text/html")
    anon = TestClient(app)
    viewer = login(app, "vera", "viewerpass")

    # only real users mint read tokens
    assert anon.get("/api/auth/board-token").status_code == 401
    bt = viewer.get("/api/auth/board-token").json()["token"]

    # ?bt= grants reads (fetch, SSE, board document, inline artifacts)…
    assert anon.get(f"/api/nodes?bt={bt}").status_code == 200
    assert anon.get(f"/boards/{ref.sha256}?bt={bt}").status_code == 200
    assert anon.get(f"/boards/{ref.sha256}").status_code == 401
    # …but never writes, and cannot mint another token
    assert anon.post(f"/api/nodes/{exp['id']}/annotate?bt={bt}",
                     json={"text": "nope"}).status_code == 401
    assert anon.post(f"/api/ingest/events?bt={bt}", json={"events": []}).status_code == 401
    assert anon.get(f"/api/auth/board-token?bt={bt}").status_code == 401


def test_no_users_means_pre_r6_behavior(tmp_path):
    src = tmp_path / "proj"
    src.mkdir()
    party = MlParty.init(src / ".mlparty")
    party.experiment_ensure("p", "e", created_by="test")
    app = build_app(src / ".mlparty", write_token="legacy-token")
    c = TestClient(app)
    assert c.get("/api/nodes").status_code == 200
    assert c.get("/api/auth/me").json() == {"auth_enabled": False, "user": None}
    assert c.post("/api/auth/login",
                  json={"username": "x", "password": "y"}).status_code == 400
    assert c.get("/api/auth/board-token").json() == {"token": None}
    assert c.post("/api/ingest/events", json={"events": []}).status_code == 401
    r = c.post("/api/ingest/events", json={"events": []},
               headers={"Authorization": "Bearer legacy-token"})
    assert r.status_code == 200


def test_login_backoff(setup, monkeypatch):
    from mlparty import http_api
    monkeypatch.setattr(http_api, "LOGIN_LOCK_SECONDS", 0.15)
    _, _, _, app = setup
    c = TestClient(app)
    bad = {"username": "vera", "password": "wrong"}
    for _ in range(5):
        assert c.post("/api/auth/login", json=bad).status_code == 401
    # locked now — even the CORRECT password is refused with Retry-After
    r = c.post("/api/auth/login", json={"username": "vera", "password": "viewerpass"})
    assert r.status_code == 429
    assert "retry-after" in r.headers
    # other users (and other client keys) are unaffected
    assert c.post("/api/auth/login",
                  json={"username": "will", "password": "writerpass"}).status_code == 200
    # lock expires -> success clears the counter
    import time as _time
    _time.sleep(0.2)
    r = c.post("/api/auth/login", json={"username": "vera", "password": "viewerpass"})
    assert r.status_code == 200
    assert c.post("/api/auth/login", json=bad).status_code == 401  # fresh count
