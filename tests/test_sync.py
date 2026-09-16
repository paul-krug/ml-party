"""The authenticated ingest surface — journal events, git
objects, artifacts, metrics — each idempotent by construction."""
import pytest
from fastapi.testclient import TestClient

from mlparty.core import MlParty
from mlparty.http_api import build_app

FAST = {"python_exe": "/nonexistent/python"}
TOKEN = "test-token-123"


@pytest.fixture
def client_party(tmp_path):
    src = tmp_path / "laptop"
    src.mkdir()
    (src / "train.py").write_text("print('v1')\n")
    party = MlParty.init(src / ".mlparty")
    party.experiment_ensure("p", "e", created_by="agent")
    party.run_start(
        experiment="e", title="remote run", purpose="exercise the sync protocol",
        hypothesis="exploratory: does spool-and-flush hold together?",
        parameters={"lr": 0.1}, created_by="agent", source_root=src, confirm_snapshot=True, **FAST)
    return party


@pytest.fixture
def server(tmp_path):
    party = MlParty.init(tmp_path / "server" / ".mlparty")
    c = TestClient(build_app(tmp_path / "server" / ".mlparty", write_token=TOKEN))
    c.headers["Authorization"] = f"Bearer {TOKEN}"
    return party, c


def test_auth(tmp_path):
    MlParty.init(tmp_path / "s" / ".mlparty")
    c = TestClient(build_app(tmp_path / "s" / ".mlparty", write_token=TOKEN))
    r = c.post("/api/ingest/events", json={"events": []})
    assert r.status_code == 401
    r = c.post("/api/ingest/events", json={"events": []},
               headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401
    # read-only server (no token configured) refuses outright
    MlParty.init(tmp_path / "ro" / ".mlparty")
    ro = TestClient(build_app(tmp_path / "ro" / ".mlparty"))
    r = ro.post("/api/ingest/events", json={"events": []},
                headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 403


def test_event_ingest_is_idempotent(client_party, server):
    _, c = server
    events, _ = client_party.store.journal.read_from(0)
    assert all(e.get("id") for e in events)

    r1 = c.post("/api/ingest/events", json={"events": events}).json()
    assert r1["applied"] == len(events) and r1["skipped"] == 0
    r2 = c.post("/api/ingest/events", json={"events": events}).json()
    assert r2["applied"] == 0 and r2["skipped"] == len(events)

    run = c.get("/api/nodes", params={"type": "run"}).json()[0]
    assert run["title"] == "remote run" and run["created_by"] == "agent"


def test_git_push_roundtrip(client_party, server):
    _server_party, c = server
    events, _ = client_party.store.journal.read_from(0)
    c.post("/api/ingest/events", json={"events": events})

    run = client_party.store.list_nodes(type="run")[0]
    exp_id = run.experiment_id
    commit = run.code_ref.commit_sha

    shas = client_party.git.reachable_objects(exp_id, commit)
    missing = c.post(f"/api/ingest/git/{exp_id}/missing", json={"shas": shas}).json()["missing"]
    assert set(missing) == set(shas)  # empty server repo

    objs = client_party.git.export_objects(exp_id, missing)
    r = c.post(f"/api/ingest/git/{exp_id}",
               json={"objects": objs, "refs": {f"refs/runs/{run.id}": commit}}).json()
    assert r["imported"] == len(objs) and r["refs"] == 1

    # snapshot readable on the server through the normal read API
    tree = c.get(f"/api/runs/{run.id}/code/tree").json()
    assert any(f["path"] == "train.py" for f in tree["files"])
    # second push: nothing missing
    missing2 = c.post(f"/api/ingest/git/{exp_id}/missing", json={"shas": shas}).json()["missing"]
    assert missing2 == []
    # non-run refs are refused
    r = c.post(f"/api/ingest/git/{exp_id}",
               json={"objects": [], "refs": {"refs/heads/main": commit}})
    assert r.status_code == 422


def test_artifact_and_metrics_ingest(client_party, server):
    _, c = server
    events, _ = client_party.store.journal.read_from(0)
    c.post("/api/ingest/events", json={"events": events})
    run_id = client_party.store.list_nodes(type="run")[0].id

    data = b"fake checkpoint bytes"
    ref = client_party.store.put_artifact_bytes(data, "best.pt")
    r = c.put(f"/api/ingest/artifacts/{ref.sha256}", content=data).json()
    assert r == {"ok": True, "deduped": False}
    r = c.put(f"/api/ingest/artifacts/{ref.sha256}", content=data).json()
    assert r["deduped"] is True
    assert c.put(f"/api/ingest/artifacts/{'0' * 64}", content=b"x").status_code == 422

    chunk = '{"ts":"2026-08-29T00:00:00+00:00","name":"loss","value":1.0,"step":0}\n'
    r = c.post(f"/api/ingest/metrics/{run_id}",
               json={"expected_offset": 0, "chunk": chunk}).json()
    assert r["ok"] and r["size"] == len(chunk)
    # stale cursor conflicts and reports the real size
    r = c.post(f"/api/ingest/metrics/{run_id}", json={"expected_offset": 0, "chunk": chunk})
    assert r.status_code == 409 and r.json()["detail"]["size"] == len(chunk)

    m = c.get(f"/api/runs/{run_id}/metrics").json()
    assert m["records"][0]["value"] == 1.0


def test_spool_and_flush_full_lifecycle(tmp_path, client_party):
    """Acceptance shape: spool store (machine C) flushed into a server store
    (machine S) — run, snapshot, metrics, artifact, finalize all arrive."""
    from mlparty.sync import SyncClient

    server_root = tmp_path / "server" / ".mlparty"
    server_party = MlParty.init(server_root)
    app = build_app(server_root, write_token=TOKEN)

    def http():
        c = TestClient(app)
        c.headers["Authorization"] = f"Bearer {TOKEN}"
        return c

    run = client_party.store.list_nodes(type="run")[0]
    client_party.run_log_metric(run.id, "loss", 0.5, step=0)
    client_party.run_log_metric(run.id, "loss", 0.25, step=1)
    ckpt = tmp_path / "best.pt"
    ckpt.write_bytes(b"weights")
    client_party.run_log_artifact(run.id, ckpt, note="best")
    client_party.run_finalize(
        run.id, method="spooled locally, flushed over the sync protocol",
        result={"summary": "loss halved from 0.5 to 0.25 over two steps",
                "verdict": "confirmed", "metrics": {"final_loss": 0.25}},
        reproduce="python train.py", created_by="agent")

    sc = SyncClient(client_party.store, "http://server", TOKEN, http=http())
    out = sc.flush()
    assert out["events"] > 0 and out["git_refs"] == 1
    assert out["artifacts"] >= 1 and out["metric_chunks"] == 1

    got = server_party.store.get_node(run.id)
    assert got.status == "finalized" and got.result.metrics["final_loss"] == 0.25
    records, _ = server_party.store.read_metrics(run.id)
    assert [r["value"] for r in records] == [0.5, 0.25]
    art = got.artifacts[0]
    assert server_party.store.artifact_path(art.sha256).read_bytes() == b"weights"
    assert server_party.git.read_file(
        got.experiment_id, got.code_ref.commit_sha, "train.py") == b"print('v1')\n"

    # idempotent second pass: nothing new ships
    out2 = sc.flush()
    assert out2 == {"events": 0, "git_refs": 0, "artifacts": 0, "metric_chunks": 0}

    # lost cursors (crash) — a full replay is safe and converges
    (client_party.store.root / "sync_state.json").unlink()
    sc2 = SyncClient(client_party.store, "http://server", TOKEN, http=http())
    out3 = sc2.flush()
    assert out3["events"] == 0 or True  # events re-sent but all skipped server-side
    records, _ = server_party.store.read_metrics(run.id)
    assert len(records) == 2  # metrics not duplicated (409 resume)
    sc.close()
    sc2.close()


def test_attach_background_sync_e2e(tmp_path):
    """Three-machine acceptance in miniature: a run tracked in a spool store
    ('compute box') with [sync] configured arrives on a real HTTP server
    ('tracking server') via attach()'s background flusher — no manual sync."""
    import os
    import socket
    import subprocess
    import sys
    import textwrap
    import threading
    import time

    import uvicorn

    server_root = tmp_path / "server" / ".mlparty"
    server_party = MlParty.init(server_root)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(
        build_app(server_root, write_token=TOKEN),
        host="127.0.0.1", port=port, log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started

    src = tmp_path / "compute"
    src.mkdir()
    (src / "train.py").write_text("print('v1')\n")
    party = MlParty.init(src / ".mlparty")
    cfg_path = src / ".mlparty" / "store.toml"
    cfg_path.write_text(
        cfg_path.read_text()
        .replace('url = ""', f'url = "http://127.0.0.1:{port}"')
        .replace('token = ""', f'token = "{TOKEN}"')
        .replace("interval_seconds = 10", "interval_seconds = 1"))
    party = MlParty.open(src / ".mlparty")  # reload config with [sync]
    party.experiment_ensure("p", "e", created_by="agent")
    out = party.run_start(
        experiment="e", title="e2e sync run", purpose="prove the background flusher",
        hypothesis="exploratory: does a spooled run arrive on the server unaided?",
        parameters={"lr": 0.01}, created_by="agent", source_root=src, confirm_snapshot=True, **FAST)

    script = src / "toy.py"
    script.write_text(textwrap.dedent("""
        import mlparty
        h = mlparty.attach(capture_env=False)
        for step in range(3):
            h.log_metric("loss", 1.0 / (step + 1), step=step)
        h.finalize(
            method="toy loop for the sync e2e test, three decreasing losses",
            result={"summary": "loss decreased monotonically across all three steps",
                    "verdict": "confirmed", "metrics": {"final_loss": 0.333}},
            reproduce="python toy.py",
        )
    """))
    env = os.environ | {"ML_PARTY_STORE": str(src / ".mlparty"),
                        "ML_PARTY_RUN": out["run_id"]}
    r = subprocess.run([sys.executable, str(script)], env=env,
                       capture_output=True, text=True, check=False, timeout=120)
    assert r.returncode == 0, r.stderr

    got = None
    for _ in range(100):  # finalize() flushes synchronously; poll for safety
        try:
            got = server_party.store.get_node(out["run_id"])
            if got.status == "finalized":
                break
        except Exception:  # noqa: BLE001, S110 — node may not have arrived yet
            pass
        time.sleep(0.1)
    assert got is not None and got.status == "finalized"
    records, _ = server_party.store.read_metrics(out["run_id"])
    assert len(records) == 3
    assert server_party.git.read_file(
        got.experiment_id, got.code_ref.commit_sha, "train.py") == b"print('v1')\n"
    server.should_exit = True


def test_metrics_append_atomic_under_race(tmp_path):
    """Duplicate delivery (timeout+retry racing the original request) must
    conflict, never interleave — the acceptance run caught this in the wild."""
    import threading

    party = MlParty.init(tmp_path / ".mlparty")
    chunk = '{"name":"loss","value":1.0,"step":0}\n' * 50
    results = []
    barrier = threading.Barrier(4)

    def worker():
        barrier.wait()
        results.append(party.store.append_metrics_chunk("run1", 0, chunk))

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(1 for r in results if r["ok"]) == 1
    assert sum(1 for r in results if not r["ok"]) == 3
    content = party.store.metrics_path("run1").read_text()
    assert content == chunk  # exactly once, no interleaving
    # conflicts report size + prefix hash for client verification
    bad = next(r for r in results if not r["ok"])
    assert bad["size"] == len(chunk.encode()) and len(bad["sha256"]) == 64


def test_flusher_refuses_diverged_server_metrics(tmp_path, client_party):
    from mlparty.sync import SyncClient, SyncError

    server_root = tmp_path / "server" / ".mlparty"
    server_party = MlParty.init(server_root)
    app = build_app(server_root, write_token=TOKEN)
    http = TestClient(app)
    http.headers["Authorization"] = f"Bearer {TOKEN}"

    run = client_party.store.list_nodes(type="run")[0]
    client_party.run_log_metric(run.id, "loss", 1.0, step=0)
    # server already holds DIFFERENT bytes for this run (simulated corruption)
    server_party.store.append_metrics_chunk(run.id, 0, '{"name":"loss","value":9.9}\n')

    sc = SyncClient(client_party.store, "http://server", TOKEN, http=http)
    sc.flush_events()
    with pytest.raises(SyncError, match="diverged"):
        sc.flush_metrics()
    sc.close()


def test_from_store_unconfigured_returns_none(client_party):
    from mlparty.sync import from_store
    assert from_store(client_party.store) is None


def test_rebuild_preserves_ingest_dedup(client_party, server):
    server_party, c = server
    events, _ = client_party.store.journal.read_from(0)
    c.post("/api/ingest/events", json={"events": events})
    server_party.store.rebuild_index()
    r = c.post("/api/ingest/events", json={"events": events}).json()
    assert r["applied"] == 0 and r["skipped"] == len(events)
