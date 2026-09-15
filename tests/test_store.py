import json

import pytest

from mlparty.ids import new_id
from mlparty.models import Abstract, Edge, ExperimentNode, ProjectNode, RunNode
from mlparty.store import NodeNotFound, Store


@pytest.fixture
def store(tmp_path):
    return Store.init(tmp_path / "store")


def _mk_graph(store):
    proj = store.create_node(ProjectNode(id=new_id(), title="proj"))
    exp = store.create_node(ExperimentNode(id=new_id(), title="exp", project_id=proj.id))
    run = store.create_node(RunNode(
        id=new_id(), title="run one", experiment_id=exp.id,
        abstract=Abstract(purpose="test the store layer thoroughly",
                          hypothesis="round trips will be lossless"),
        parameters={"lr": 0.001, "epochs": 3},
    ))
    store.add_edge(Edge(src=run.id, dst=exp.id, type="part-of", created_by="test"))
    return proj, exp, run


def test_create_get_roundtrip(store):
    _, exp, run = _mk_graph(store)
    assert store.get_node(run.id) == run
    assert store.get_node(exp.id) == exp
    with pytest.raises(NodeNotFound):
        store.get_node("nope")


def test_update_node_shallow(store):
    _, _, run = _mk_graph(store)
    updated = store.update_node(run.id, {"status": "failed", "tags": ["broken"]})
    assert updated.status == "failed"
    assert updated.tags == ["broken"]
    assert updated.abstract == run.abstract  # untouched fields survive
    assert updated.updated_at >= run.updated_at


def test_edge_target_check(store):
    _, _, run = _mk_graph(store)
    with pytest.raises(NodeNotFound):
        store.add_edge(Edge(src=run.id, dst="ghost", type="derives-from"))


def test_list_and_find(store):
    proj, exp, run = _mk_graph(store)
    assert [n.id for n in store.list_nodes(type="run")] == [run.id]
    assert [n.id for n in store.list_nodes(experiment_id=exp.id)] == [run.id]
    assert store.find_by_title("project", "proj").id == proj.id
    assert store.find_by_title("project", "ghost") is None
    store.update_node(run.id, {"tags": ["sweep"]})
    assert [n.id for n in store.list_nodes(tag="sweep")] == [run.id]


def test_edges_for_directions(store):
    _, exp, run = _mk_graph(store)
    out = store.edges_for(run.id, "out")
    assert len(out) == 1 and out[0]["dst"] == exp.id
    incoming = store.edges_for(exp.id, "in", types=["part-of"])
    assert len(incoming) == 1 and incoming[0]["src"] == run.id


def test_metrics_append_and_tail(store):
    _, _, run = _mk_graph(store)
    store.append_metric(run.id, "loss", 1.5, step=0)
    store.append_metric(run.id, "loss", 1.2, step=1)
    recs, offset = store.read_metrics(run.id)
    assert [r["value"] for r in recs] == [1.5, 1.2]
    # tail: nothing new
    recs2, offset2 = store.read_metrics(run.id, offset=offset)
    assert recs2 == [] and offset2 == offset
    # tail: one new record
    store.append_metric(run.id, "loss", 0.9, step=2)
    recs3, _ = store.read_metrics(run.id, offset=offset)
    assert len(recs3) == 1 and recs3[0]["step"] == 2


def test_artifact_cas_dedup(store, tmp_path):
    f1 = tmp_path / "a.bin"
    f1.write_bytes(b"checkpoint-bytes")
    f2 = tmp_path / "b.bin"
    f2.write_bytes(b"checkpoint-bytes")
    r1 = store.put_artifact(f1)
    r2 = store.put_artifact(f2)
    assert r1.sha256 == r2.sha256
    assert store.artifact_path(r1.sha256).read_bytes() == b"checkpoint-bytes"


def _index_dump(store):
    nodes = {n.id: n.model_dump(mode="json") for n in store.list_nodes(limit=10_000)}
    edges = sorted(store.index.all_edges(), key=lambda e: (e["src"], e["dst"], e["type"]))
    return nodes, edges


def test_rebuild_index_equivalence(store):
    _mk_graph(store)
    _, _, run2 = _mk_graph(store)
    store.update_node(run2.id, {"status": "finalized"})
    store.record_tree_commit("exp1", "tree1", "", "commit1")
    before = _index_dump(store)
    store.index.clear()
    assert store.list_nodes() == []
    n = store.rebuild_index()
    assert n >= 9
    assert _index_dump(store) == before
    assert store.index.tree_commit_get("exp1", "tree1", "") == "commit1"


def test_journal_is_source_of_truth(store):
    _mk_graph(store)
    events = list(store.journal.iter_events())
    assert [e["event"] for e in events[:3]] == ["node.created"] * 3
    assert events[3]["event"] == "edge.added"
    # journal lines are valid compact JSON
    raw = (store.root / "journal.jsonl").read_text().splitlines()
    assert all(json.loads(line) for line in raw)
