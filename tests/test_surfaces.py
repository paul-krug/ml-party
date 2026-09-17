import asyncio
import os
import subprocess
import sys
import textwrap

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from mlparty.core import MlParty
from mlparty.http_api import build_app
from mlparty.mcp_server import build_server

FAST = {"python_exe": "/nonexistent/python"}

EXPECTED_TOOLS = {
    "workflow_guide", "help",
    "project_ensure", "experiment_ensure", "experiment_list",
    "run_start", "run_log_metric", "run_log_artifact", "experiment_log_artifact",
    "run_finalize", "run_fail",
    "note_create", "node_get", "node_annotate", "graph_query", "run_diff",
    "action_list", "action_invoke", "action_register", "snapshot_preview",
    "run_set_compute",
}


@pytest.fixture
def proj(tmp_path):
    src = tmp_path / "proj"
    src.mkdir()
    (src / "train.py").write_text("print('hi')\n")
    party = MlParty.init(src / ".mlparty")
    party.experiment_ensure("p", "e", created_by="test")
    return src, party


def _start(party, title="run", **over):
    args = {
        "experiment": "e", "title": title,
        "purpose": "exercise the surfaces end to end",
        "hypothesis": "exploratory: do all frontends agree?",
        "parameters": {"lr": 0.001}, "created_by": "test",
        "source_root": party.store.root.parent, "confirm_snapshot": True,
    } | FAST | over
    return party.run_start(**args)


def test_http_endpoints(proj):
    src, party = proj
    out = _start(party)
    party.run_log_metric(out["run_id"], "loss", 1.0, step=0)
    c = TestClient(build_app(src / ".mlparty"))

    assert c.get("/api/health").json()["ok"]
    nodes = c.get("/api/nodes", params={"type": "run"}).json()
    assert nodes[0]["id"] == out["run_id"]

    node = c.get(f"/api/nodes/{out['run_id']}", params={"metrics": True}).json()
    assert node["node"]["status"] == "open"
    assert node["metric_series"][0]["value"] == 1.0

    m = c.get(f"/api/runs/{out['run_id']}/metrics").json()
    assert m["records"] and m["offset"] > 0
    m2 = c.get(f"/api/runs/{out['run_id']}/metrics", params={"offset": m["offset"]}).json()
    assert m2["records"] == []

    g = c.get("/api/graph").json()
    assert any(n["type"] == "run" for n in g["nodes"])
    assert g["edges"]
    assert c.get("/api/nodes/ghost").status_code == 404


def test_experiments_summary_and_code_endpoints(proj):
    src, party = proj
    out = _start(party, title="summary-run")
    c = TestClient(build_app(src / ".mlparty"))

    summary = c.get("/api/experiments/summary").json()
    assert summary[0]["n_runs"] == 1
    assert summary[0]["last_run"]["title"] == "summary-run"
    assert summary[0]["statuses"] == {"open": 1}

    tree = c.get(f"/api/runs/{out['run_id']}/code/tree").json()
    paths = [f["path"] for f in tree["files"]]
    assert "train.py" in paths and ".mlparty/env.lock" in paths
    assert tree["commit"] == out["commit"]["sha"]

    f = c.get(f"/api/runs/{out['run_id']}/code/file", params={"path": "train.py"}).json()
    assert "print" in f["content"] and f["truncated"] is False
    assert c.get(f"/api/runs/{out['run_id']}/code/file",
                 params={"path": "nope.py"}).status_code == 404

    run_card = c.get("/api/nodes", params={"type": "run"}).json()[0]
    assert run_card["started_at"] and run_card["ended_at"] is None


def test_annotate_and_artifact_download(proj, tmp_path):
    src, party = proj
    out = _start(party, title="annotate-me")
    c = TestClient(build_app(src / ".mlparty"))

    r = c.post(f"/api/nodes/{out['run_id']}/annotate",
               json={"text": "sounded better by ear", "created_by": "paul"})
    assert r.status_code == 200
    node = c.get(f"/api/nodes/{out['run_id']}").json()["node"]
    assert node["annotations"][0]["text"] == "sounded better by ear"
    assert node["annotations"][0]["created_by"] == "paul"
    assert c.post("/api/nodes/ghost/annotate", json={"text": "x" * 10}).status_code == 404
    assert c.post(f"/api/nodes/{out['run_id']}/annotate",
                  json={"text": "   "}).status_code == 422

    ckpt = tmp_path / "best.pt"
    ckpt.write_bytes(b"fake-checkpoint")
    ref = party.run_log_artifact(out["run_id"], ckpt)
    dl = c.get(f"/api/artifacts/{ref['sha256']}", params={"name": "best.pt"})
    assert dl.status_code == 200 and dl.content == b"fake-checkpoint"
    assert c.get(f"/api/artifacts/{'0' * 64}").status_code == 404


def test_sse_stream_ends_for_terminal_run(proj):
    src, party = proj
    out = _start(party)
    party.run_fail(out["run_id"], "died early for the SSE test")
    c = TestClient(build_app(src / ".mlparty"))
    with c.stream("GET", f"/api/runs/{out['run_id']}/metrics/stream") as r:
        body = "".join(r.iter_text())
    assert "event: end" in body and "failed" in body


def test_mcp_tools_registered_and_refusals_are_data(proj):
    src, _party = proj
    server = build_server(src / ".mlparty")
    tools = asyncio.run(server.list_tools())
    assert {t.name for t in tools} == EXPECTED_TOOLS
    # a contract refusal comes back as structured data, not an exception
    res = asyncio.run(server.call_tool("run_start", {
        "experiment": "e", "title": "t", "purpose": "short", "hypothesis": "short",
        "parameters": {},
    }))
    text = str(res)
    assert "refusal" in text and "purpose" in text
    # a successful start echoes the store root back: an agent otherwise has no
    # way to see WHICH store it just wrote into, and stores are per-machine
    ok = asyncio.run(server.call_tool("run_start", {
        "experiment": "e", "title": "echo check",
        "purpose": "check the store root is echoed to the agent",
        "hypothesis": "exploratory: does run_start orient the caller?",
        "parameters": {"lr": 1}, "source_root": str(src), "confirm_snapshot": True,
    }))
    assert str((src / ".mlparty").resolve()) in str(ok)


def test_client_attach_toy_training(proj):
    src, party = proj
    out = _start(party)
    script = src / "toy.py"
    script.write_text(textwrap.dedent("""
        import mlparty
        h = mlparty.attach()
        for step in range(3):
            h.log_metric("loss", 1.0 / (step + 1), step=step)
        h.finalize(
            method="toy loop for the e2e test, three steps of decreasing fake loss",
            result={"summary": "loss decreased monotonically across all three steps",
                    "verdict": "confirmed", "metrics": {"final_loss": 0.333}},
            reproduce="python toy.py",
        )
    """))
    env = os.environ | {"ML_PARTY_STORE": str(src / ".mlparty"),
                        "ML_PARTY_RUN": out["run_id"],
                        "ML_PARTY_COMPUTE_SYSTEM": "jobpool",
                        "ML_PARTY_COMPUTE_JOB_ID": "4711",
                        "ML_PARTY_COMPUTE_URL": "https://jobs.internal/j/4711"}
    r = subprocess.run([sys.executable, str(script)], env=env,
                       capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr

    run = party.store.get_node(out["run_id"])
    assert run.status == "finalized"
    assert run.invocation.captured_by == "client"
    assert any("toy.py" in a for a in run.invocation.argv)
    records, _ = party.store.read_metrics(out["run_id"])
    assert len(records) == 3

    # split repro capture: the training process is the honest witness
    assert run.hardware.captured_by == "attach"
    # ...including about where it runs, when the launcher passed the handshake
    assert run.compute.system == "jobpool" and run.compute.job_id == "4711"
    assert run.compute.captured_by == "attach"
    assert run.env_lock_runtime is not None  # finalize joins the capture thread
    lock = party.store.artifact_path(run.env_lock_runtime.sha256).read_bytes()
    assert lock.startswith(b"# Python")
    assert party.store.heartbeat_at(out["run_id"]) is not None


def test_client_excepthook_fails_run_with_traceback(proj):
    src, party = proj
    out = _start(party)
    script = src / "crash.py"
    script.write_text(
        "import mlparty\nh = mlparty.attach(capture_env=False)\nraise ValueError('boom')\n")
    env = os.environ | {"ML_PARTY_STORE": str(src / ".mlparty"),
                        "ML_PARTY_RUN": out["run_id"]}
    r = subprocess.run([sys.executable, str(script)], env=env,
                       capture_output=True, text=True, check=False)
    assert r.returncode != 0

    run = party.store.get_node(out["run_id"])
    assert run.status == "failed"
    assert run.failure.failure_class == "crash"
    assert "boom" in run.failure.traceback


def test_run_liveness_in_api(proj):
    src, party = proj
    out = _start(party)
    c = TestClient(build_app(src / ".mlparty"))

    before = c.get("/api/nodes", params={"type": "run"}).json()[0]
    assert before["heartbeat_at"] is None and before["alive"] is False

    party.store.touch_heartbeat(out["run_id"])
    after = c.get("/api/nodes", params={"type": "run"}).json()[0]
    assert after["alive"] is True and after["heartbeat_at"] is not None

    node = c.get(f"/api/nodes/{out['run_id']}").json()["node"]
    assert node["alive"] is True


def test_cli_basics(proj):
    from mlparty.cli import app as cli_app
    src, party = proj
    out = _start(party, title="cli-run")
    runner = CliRunner()
    root = str(src / ".mlparty")
    r = runner.invoke(cli_app, ["runs", "--root", root])
    assert out["run_id"] in r.output
    r = runner.invoke(cli_app, ["status", "--root", root])
    assert "run" in r.output and r.exit_code == 0
