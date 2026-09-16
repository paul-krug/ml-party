from datetime import UTC, datetime, timedelta

import pytest

from mlparty.contract import ContractViolation
from mlparty.core import MlParty
from mlparty.store import NodeNotFound

FAST_CAPTURE = {"python_exe": "/nonexistent/python"}  # skip slow pip-freeze in tests


@pytest.fixture
def mlp(tmp_path):
    src = tmp_path / "proj"
    src.mkdir()
    (src / "train.py").write_text("print('v1')\n")
    party = MlParty.init(src / ".mlparty")
    party.experiment_ensure("demo-project", "exp-a", "first experiment", created_by="test")
    return party


def _start(mlp, title="run", exp="exp-a", **over):
    args = {
        "experiment": exp, "title": title,
        "purpose": "check that the lifecycle works end to end",
        "hypothesis": "exploratory: does the pipeline hold together?",
        "parameters": {"lr": 0.001}, "created_by": "test",
        "source_root": mlp.store.root.parent, "confirm_snapshot": True,
    } | FAST_CAPTURE | over
    return mlp.run_start(**args)


def test_ensure_idempotent(mlp):
    a = mlp.experiment_ensure("demo-project", "exp-a")
    b = mlp.experiment_ensure("demo-project", "exp-a")
    assert a["id"] == b["id"]
    assert len(mlp.experiment_list("demo-project")) == 1
    assert mlp.git.repo_path(a["id"]).exists()


def test_run_start_captures_repro_tuple(mlp):
    out = _start(mlp)
    run = mlp.store.get_node(out["run_id"])
    assert run.status == "open"
    assert run.code_ref.commit_sha == out["commit"]["sha"]
    assert run.env_lock_ref == ".mlparty/env.lock"
    assert run.snapshot_report.included_files >= 1
    assert run.params_hash
    assert run.hardware is not None
    # env lock is readable back from the snapshot commit
    lock = mlp.git.read_file(run.experiment_id, run.code_ref.commit_sha, run.env_lock_ref)
    assert lock is not None and b"capture-failed" in lock  # fake python exe


def test_sweep_shares_one_commit(mlp):
    outs = [_start(mlp, title=f"sweep-{i}", parameters={"lr": 10 ** -i})
            for i in range(1, 4)]
    shas = {o["commit"]["sha"] for o in outs}
    assert len(shas) == 1                       # many runs -> one commit
    assert outs[0]["commit"]["new_commit"] is True
    assert outs[1]["commit"]["new_commit"] is False
    assert "identical" in outs[1]["hints"][0]   # assist-don't-assert hint
    # params stay distinguishable
    hashes = {mlp.store.get_node(o["run_id"]).params_hash for o in outs}
    assert len(hashes) == 3


def test_code_edit_new_commit_and_lineage(mlp, tmp_path):
    first = _start(mlp)
    (tmp_path / "proj" / "train.py").write_text("print('v2')\n")
    second = _start(mlp, derives_from=[first["run_id"]])
    assert second["commit"]["sha"] != first["commit"]["sha"]
    meta = mlp.git.commit_meta(mlp.store.get_node(second["run_id"]).experiment_id,
                               second["commit"]["sha"])
    assert meta["parents"] == [first["commit"]["sha"]]  # declared derivation -> git parent
    edges = mlp.store.edges_for(second["run_id"], "out", types=["derives-from"])
    assert edges and edges[0]["dst"] == first["run_id"]


def test_secret_params_redacted(mlp):
    out = _start(mlp, parameters={"lr": 0.1, "hf_token": "supersecret"})
    run = mlp.store.get_node(out["run_id"])
    assert run.parameters["hf_token"] == "[redacted]"
    assert "hf_token" in run.snapshot_report.redacted_keys
    assert "supersecret" not in (mlp.store.root / "journal.jsonl").read_text()


def test_finalize_happy_path(mlp):
    out = _start(mlp)
    mlp.run_log_metric(out["run_id"], "loss", 0.5, step=1)
    finalized = mlp.run_finalize(
        out["run_id"],
        method="trained a tiny model for one step to exercise the pipeline",
        result={"summary": "pipeline held together, loss logged and readable",
                "verdict": "confirmed", "metrics": {"loss": 0.5}},
        reproduce="python train.py --lr 1e-3",
        created_by="test",
    )
    assert finalized["status"] == "finalized"
    run = mlp.store.get_node(out["run_id"])
    assert run.abstract.method.startswith("trained")
    assert run.metrics_summary == {"loss": 0.5}
    assert run.ended_at is not None
    # terminal: cannot finalize again
    with pytest.raises(ContractViolation):
        mlp.run_finalize(out["run_id"], method="x" * 30,
                         result={"summary": "y" * 30, "verdict": "confirmed",
                                 "metrics": {"a": 1.0}},
                         reproduce="python train.py")


def test_finalize_refusal_lists_missing(mlp):
    out = _start(mlp)
    with pytest.raises(ContractViolation) as ei:
        mlp.run_finalize(out["run_id"], method="", result=None, reproduce="")
    d = ei.value.to_dict()
    assert "method" in d["missing"] and "result" in d["missing"] and "reproduce" in d["missing"]


def test_finalize_rejects_ghost_edge_target(mlp):
    out = _start(mlp)
    with pytest.raises(ContractViolation) as ei:
        mlp.run_finalize(out["run_id"], method="m" * 30,
                         result={"summary": "s" * 30, "verdict": "confirmed",
                                 "metrics": {"a": 1.0}},
                         reproduce="python x.py",
                         edges=[{"dst": "ghost-node", "type": "compares-to"}])
    assert any("ghost-node" in i["reason"] for i in ei.value.to_dict()["invalid"])


def test_fail_path(mlp):
    out = _start(mlp)
    failed = mlp.run_fail(out["run_id"], "CUDA OOM on batch 3 with batch_size=64",
                          failure_class="oom", why="21GB > 24GB on full utterance")
    assert failed["status"] == "failed"
    run = mlp.store.get_node(out["run_id"])
    assert run.failure.failure_class == "oom"


def test_note_and_annotate_and_get(mlp):
    out = _start(mlp)
    note = mlp.note_create("frozen-net gradients", "let frozen-net gradients flow by default",
                           kind="feedback",
                           edges=[{"dst": out["run_id"], "type": "x-learned-from"}],
                           created_by="test")
    got = mlp.node_get(note["id"])
    assert got["edges_out"][0]["dst"] == out["run_id"]
    mlp.node_annotate(out["run_id"], "later turned out premise was stale", created_by="test")
    run_doc = mlp.node_get(out["run_id"])["node"]
    assert run_doc["annotations"][0]["text"].startswith("later")


def test_janitor_abandons_stale_open_runs(mlp):
    out = _start(mlp)
    old = (datetime.now(UTC) - timedelta(hours=100)).isoformat()
    mlp.store.update_node(out["run_id"], {"started_at": old})
    fresh = _start(mlp, title="fresh")
    abandoned = mlp.janitor()
    assert out["run_id"] in abandoned
    assert mlp.store.get_node(out["run_id"]).status == "abandoned"
    assert mlp.store.get_node(fresh["run_id"]).status == "open"


def test_janitor_respects_heartbeat(mlp):
    old = (datetime.now(UTC) - timedelta(hours=100)).isoformat()

    beating = _start(mlp, title="beating")
    mlp.store.update_node(beating["run_id"], {"started_at": old})
    mlp.store.touch_heartbeat(beating["run_id"])

    flatlined = _start(mlp, title="flatlined")
    mlp.store.update_node(flatlined["run_id"], {"started_at": old})
    stale_hb = (datetime.now(UTC) - timedelta(hours=50)).isoformat()
    mlp.store.heartbeat_path(flatlined["run_id"]).write_text(stale_hb)

    abandoned = mlp.janitor(ttl_hours=24)
    assert beating["run_id"] not in abandoned
    assert flatlined["run_id"] in abandoned
    assert mlp.store.get_node(beating["run_id"]).status == "open"


def test_resolve_by_title_and_missing(mlp):
    _start(mlp, title="named-run")
    assert mlp._resolve("named-run", "run").title == "named-run"
    with pytest.raises(NodeNotFound):
        mlp._resolve("ghost", "run")
