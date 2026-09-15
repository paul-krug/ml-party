import time

import pytest
from fastapi.testclient import TestClient

from mlparty.actions import ActionStore
from mlparty.auth import AuthStore
from mlparty.contract import ContractViolation
from mlparty.core import MlParty
from mlparty.http_api import build_app

ECHO = {
    "name": "echo-msg",
    "description": "echo a message (test action)",
    "command": "echo {msg}",
    "params": {"msg": {"type": "str"}},
}


@pytest.fixture
def party(tmp_path):
    src = tmp_path / "proj"
    src.mkdir()
    p = MlParty.init(src / ".mlparty")
    p.experiment_ensure("p", "e", created_by="test")
    return p


def _wait_exited(party, node_id, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        node = party.store.get_node(node_id)
        if getattr(node, "status", None) == "exited":
            return node
        time.sleep(0.05)
    raise AssertionError("invocation never exited")


def test_register_validation(party):
    store = ActionStore(party.store.root)
    store.register(ECHO)
    with pytest.raises(ContractViolation, match="already exists"):
        store.register(ECHO)
    with pytest.raises(ContractViolation, match="not\\s+declared"):
        store.register({**ECHO, "name": "bad", "command": "echo {undeclared}"})
    with pytest.raises(ContractViolation, match="describe"):
        store.register({**ECHO, "name": "bad2", "description": "x"})
    with pytest.raises(ContractViolation, match="choice"):
        store.register({**ECHO, "name": "bad3",
                        "params": {"msg": {"type": "choice"}}})
    with pytest.raises(ContractViolation, match="lowercase"):
        store.register({**ECHO, "name": "Bad Name"})
    store.remove("echo-msg")
    assert store.list() == []
    with pytest.raises(ContractViolation, match="no action"):
        store.remove("echo-msg")


def test_render_quotes_hostile_values(party):
    store = ActionStore(party.store.root)
    store.register(ECHO)
    tpl = store.get("echo-msg")
    command, _, _ = store.render(tpl, {"msg": "hi; rm -rf / #"})
    assert command == "echo 'hi; rm -rf / #'"
    # typed validation
    store.register({"name": "typed", "description": "typed params test action",
                    "command": "echo {n} {x} {c}",
                    "params": {"n": {"type": "int"}, "x": {"type": "float"},
                               "c": {"type": "choice", "choices": ["a", "b"]}}})
    tpl = store.get("typed")
    command, _, _ = store.render(tpl, {"n": 3, "x": 0.5, "c": "a"})
    assert command == "echo 3 0.5 a"
    with pytest.raises(ContractViolation, match="n:"):
        store.render(tpl, {"n": "3.7", "x": 1, "c": "a"})
    with pytest.raises(ContractViolation, match="one of"):
        store.render(tpl, {"n": 1, "x": 1, "c": "z"})
    with pytest.raises(ContractViolation, match="missing"):
        store.render(tpl, {"n": 1})
    with pytest.raises(ContractViolation, match="unknown parameter"):
        store.render(tpl, {"n": 1, "x": 1, "c": "a", "extra": 1})


def test_invoke_records_graph_node(party):
    party.action_register(ECHO, created_by="test")
    out = party.action_invoke("echo-msg", {"msg": "hello world"}, created_by="agent")
    node = _wait_exited(party, out["invocation_id"])
    assert node.type == "action"
    doc = node.model_dump()
    assert doc["exit_code"] == 0
    assert "hello world" in doc["output_tail"]
    assert doc["created_by"] == "agent"

    # failing command records its outcome — a failure is knowledge
    party.action_register({"name": "fail", "description": "always fails (test)",
                           "command": "echo boom >&2; exit 3"}, created_by="test")
    out = party.action_invoke("fail")
    node = _wait_exited(party, out["invocation_id"])
    assert node.model_dump()["exit_code"] == 3
    assert "boom" in node.model_dump()["output_tail"]


def test_invoke_with_run_edges_and_env(party, tmp_path):
    run = party.run_start(
        experiment="e", title="controlled run",
        purpose="exercise run control end to end",
        hypothesis="exploratory: does the action edge to the run?",
        parameters={"lr": 0.1}, created_by="test",
        python_exe="/nonexistent/python")
    marker = tmp_path / "seen_env"
    party.action_register({
        "name": "start", "description": "write the injected env to a file",
        "command": f"echo $ML_PARTY_RUN > {marker}",
        "env": {"ML_PARTY_RUN": "{run}", "ML_PARTY_STORE": "{store_root}"},
        "params": {"run": {"type": "str"}},
    }, created_by="test")

    out = party.action_invoke("start", {"run": run["run_id"]})
    node = _wait_exited(party, out["invocation_id"])
    assert marker.read_text().strip() == run["run_id"]
    edges = party.store.edges_for(node.id, "out")
    assert [(e["type"], e["dst"]) for e in edges] == [("x-controls", run["run_id"])]

    # nonexistent run refused before anything executes
    from mlparty.store import NodeNotFound
    with pytest.raises(NodeNotFound):
        party.action_invoke("start", {"run": "01BOGUS"})


def test_http_surface_and_write_gating(party):
    party.action_register(ECHO, created_by="test")
    root = party.store.root

    # read-only `mlp ui` (no token): list works, invoke refused
    ui = TestClient(build_app(root))
    assert ui.get("/api/actions").json()[0]["name"] == "echo-msg"
    r = ui.post("/api/actions/invoke", json={"name": "echo-msg",
                                             "params": {"msg": "x"}})
    assert r.status_code == 403

    # legacy token mode: token invokes; boards never do
    served = TestClient(build_app(root, write_token="tok"))
    hdr = {"Authorization": "Bearer tok"}
    r = served.post("/api/actions/invoke", headers=hdr,
                    json={"name": "echo-msg", "params": {"msg": "x"}})
    assert r.status_code == 200
    r = served.post("/api/actions/invoke", headers={**hdr, "Origin": "null"},
                    json={"name": "echo-msg", "params": {"msg": "x"}})
    assert r.status_code == 403
    # machine-readable refusal on bad params
    r = served.post("/api/actions/invoke", headers=hdr,
                    json={"name": "echo-msg", "params": {}})
    assert r.status_code == 422 and r.json()["detail"]["missing"] == ["msg"]
    r = served.post("/api/actions/invoke", headers=hdr, json={"name": "nope"})
    assert r.status_code == 422

    # auth mode: viewer 403, writer invokes and is stamped as created_by
    auth = AuthStore(root)
    auth.user_add("admin", "adminpass1", role="admin")
    auth.user_add("vera", "viewerpass", role="viewer")
    auth.user_add("will", "writerpass", role="writer")
    app = build_app(root)
    vc, wc = TestClient(app), TestClient(app)
    vc.post("/api/auth/login", json={"username": "vera", "password": "viewerpass"})
    wc.post("/api/auth/login", json={"username": "will", "password": "writerpass"})
    assert vc.post("/api/actions/invoke",
                   json={"name": "echo-msg", "params": {"msg": "x"}}).status_code == 403
    r = wc.post("/api/actions/invoke",
                json={"name": "echo-msg", "params": {"msg": "x"},
                      "created_by": "spoofed"})
    assert r.status_code == 200
    node = _wait_exited(party, r.json()["invocation_id"])
    assert node.model_dump()["created_by"] == "will"


def test_invocations_survive_rebuild(party):
    party.action_register(ECHO, created_by="test")
    out = party.action_invoke("echo-msg", {"msg": "persistent"})
    _wait_exited(party, out["invocation_id"])
    party.store.rebuild_index()
    node = party.store.get_node(out["invocation_id"])
    assert node.type == "action"
    assert node.model_dump()["exit_code"] == 0
