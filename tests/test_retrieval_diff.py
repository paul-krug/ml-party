import pytest

from mlparty.core import MlParty

FAST = {"python_exe": "/nonexistent/python"}


@pytest.fixture
def party(tmp_path):
    src = tmp_path / "proj"
    src.mkdir()
    (src / "train.py").write_text("lr = 0.001\n")
    p = MlParty.init(src / ".mlparty")
    p.experiment_ensure("speech", "inversion", created_by="test")
    return p, src


def _start(p, title, purpose, hypothesis="exploratory: what happens?", params=None, **over):
    return p.run_start(
        experiment="inversion", title=title, purpose=purpose, hypothesis=hypothesis,
        parameters=params or {"lr": 0.001}, created_by="test",
        **({"source_root": p.store.root.parent, "confirm_snapshot": True} | FAST | over))


def _finalize(p, run_id, summary, verdict="confirmed", metrics=None, **over):
    return p.run_finalize(
        run_id,
        method="trained the model on the standard dataset for the usual schedule",
        result={"summary": summary, "verdict": verdict,
                "metrics": metrics or {"wer": 0.1}},
        reproduce="python train.py", created_by="test", **over)


def test_lexical_query_finds_and_ranks(party):
    p, _ = party
    a = _start(p, "band anchors", "test whether band anchors improve TDS transfer")
    _finalize(p, a["run_id"], "band anchors clearly improved transfer to TDS synthesis",
              metrics={"wer_tds": 0.21})
    b = _start(p, "baseline", "plain baseline without any anchor weighting")
    _finalize(p, b["run_id"], "baseline transfer stayed poor on TDS")

    out = p.graph_query("band anchors TDS transfer")
    ids = [r["id"] for r in out["results"]]
    assert a["run_id"] in ids
    assert ids.index(a["run_id"]) < ids.index(b["run_id"])
    top = out["results"][0]
    assert top["why"] and "score" in top


def test_graph_expansion_pulls_neighbors(party):
    p, _ = party
    a = _start(p, "anchor run", "test band anchor weighting on the kiel corpus")
    _finalize(p, a["run_id"], "anchors worked nicely on the kiel corpus")
    p.note_create("anchor recipe", "band-anchor weighting recipe distilled from the run",
                  kind="insight", edges=[{"dst": a["run_id"], "type": "derives-from"}],
                  created_by="test")
    # query hits the run; the note arrives via 1-hop expansion
    out = p.graph_query("kiel corpus anchors", type="note")
    assert any(r["title"] == "anchor recipe" for r in out["results"])
    assert any("graph" in r["why"] for r in out["results"])


def test_superseded_runs_downranked(party):
    p, _ = party
    old = _start(p, "old anchor result", "measure anchor gain on TDS the first time")
    _finalize(p, old["run_id"], "anchor gain looked huge on TDS transfer")
    new = _start(p, "corrected anchor result",
                 "remeasure anchor gain after fixing the stale plot bug")
    _finalize(p, new["run_id"], "anchor gain on TDS is real but smaller than first thought",
              edges=[{"dst": old["run_id"], "type": "supersedes",
                      "note": "first measurement used a stale plot"}])

    out = p.graph_query("anchor gain TDS")
    by_id = {r["id"]: r for r in out["results"]}
    assert by_id[old["run_id"]]["score"] < by_id[new["run_id"]]["score"]
    assert by_id[old["run_id"]]["corrected_by"][0]["node"] == new["run_id"]


def test_semantic_mode_without_embedder_says_so(party):
    p, _ = party
    out = p.graph_query("anything", mode="semantic")
    assert out["results"] == [] and "no embedder" in out["note"]


def test_run_diff_params_only_and_code_change(party):
    p, src = party
    a = _start(p, "sweep-a", "sweep the learning rate downward", params={"lr": 0.01})
    b = _start(p, "sweep-b", "sweep the learning rate downward", params={"lr": 0.001})
    _finalize(p, a["run_id"], "higher lr diverged early in training", verdict="refuted",
              metrics={"wer": 0.5})
    _finalize(p, b["run_id"], "lower lr converged and reached a decent error rate",
              metrics={"wer": 0.1})

    d = p.run_diff(a["run_id"], b["run_id"])
    assert d["code"]["identical"] is True                       # same snapshot commit
    assert d["params"]["changed"]["lr"] == {"a": 0.01, "b": 0.001}
    assert d["metrics"]["changed"]["wer"] == {"a": 0.5, "b": 0.1}
    assert d["env"]["identical"] is True

    (src / "train.py").write_text("lr = 0.0005  # edited\n")
    c = _start(p, "edited", "check the edited config file changes the tree")
    d2 = p.run_diff(a["run_id"], c["run_id"])
    assert d2["code"]["identical"] is False
    assert "train.py" in d2["code"]["patch"]
