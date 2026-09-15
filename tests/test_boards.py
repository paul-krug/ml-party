from fastapi.testclient import TestClient

from mlparty.core import MlParty
from mlparty.http_api import build_app

BOARD_HTML = b"<!doctype html><html><body><h1>demo board</h1></body></html>"


def _setup(tmp_path):
    src = tmp_path / "proj"
    src.mkdir()
    party = MlParty.init(src / ".mlparty")
    party.experiment_ensure("p", "e", created_by="test")
    return party, TestClient(build_app(src / ".mlparty"))


def test_board_served_sandboxed(tmp_path):
    party, c = _setup(tmp_path)
    ref = party.store.put_artifact_bytes(BOARD_HTML, "report.html", media_type="text/html")

    r = c.get(f"/boards/{ref.sha256}")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    csp = r.headers["content-security-policy"]
    assert "sandbox allow-scripts" in csp
    assert "connect-src 'self'" in csp
    assert "demo board" in r.text

    assert c.get(f"/boards/{'0' * 64}").status_code == 404


def test_inline_serving_is_safelisted(tmp_path):
    party, c = _setup(tmp_path)
    ref = party.store.put_artifact_bytes(BOARD_HTML, "report.html", media_type="text/html")

    # html must NOT render inline on the UI origin, whatever the query claims
    r = c.get(f"/api/artifacts/{ref.sha256}",
              params={"inline": True, "media_type": "text/html"})
    assert r.headers["content-disposition"].startswith("attachment")
    assert r.headers["content-type"].startswith("application/octet-stream")

    # safe types stay inline, now with a sandbox CSP
    r = c.get(f"/api/artifacts/{ref.sha256}",
              params={"inline": True, "media_type": "image/png"})
    assert r.headers["content-disposition"].startswith("inline")
    assert r.headers["content-security-policy"] == "sandbox"


def test_cors_reads_allowed_for_boards_writes_not(tmp_path):
    party, c = _setup(tmp_path)
    exp = party.experiment_ensure("p", "e")

    # sandboxed (opaque-origin) GET gets CORS approval
    r = c.get(f"/api/nodes/{exp['id']}", headers={"Origin": "null"})
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == "*"

    # POST preflight from a board is NOT approved
    r = c.options(f"/api/nodes/{exp['id']}/annotate",
                  headers={"Origin": "null",
                           "Access-Control-Request-Method": "POST"})
    assert r.status_code == 400


def _start_run(party, title="run one"):
    return party.run_start(
        experiment="e", title=title, purpose="exercise boards end to end",
        hypothesis="exploratory: do boards surface?", parameters={"lr": 0.1},
        created_by="test", python_exe="/nonexistent/python")["run_id"]


def test_experiment_log_artifact_and_gallery(tmp_path):
    party, c = _setup(tmp_path)
    rid = _start_run(party)

    titled = tmp_path / "compare.html"
    titled.write_bytes(b"<html><head><title>WavLM comparison</title></head><body></body></html>")
    exp_ref = party.experiment_log_artifact("e", titled, media_type="text/html",
                                            note="tube vs e2e comparison")
    run_board = tmp_path / "report.html"
    run_board.write_bytes(BOARD_HTML)
    run_ref = party.run_log_artifact(rid, run_board, media_type="text/html")
    party.run_log_artifact(rid, run_board, media_type="text/plain")  # not a board

    exp_node = party.node_get("e")["node"]
    assert exp_node["artifacts"][0]["sha256"] == exp_ref["sha256"]

    boards = c.get("/api/boards").json()
    assert {(b["sha256"], b["node_type"]) for b in boards} == {
        (exp_ref["sha256"], "experiment"), (run_ref["sha256"], "run")}
    by_sha = {b["sha256"]: b for b in boards}
    assert by_sha[exp_ref["sha256"]]["title"] == "tube vs e2e comparison"  # note wins
    assert by_sha[run_ref["sha256"]]["title"] == "report.html"  # no note/<title>
    assert by_sha[run_ref["sha256"]]["experiment_id"] == exp_node["id"]

    per_exp = c.get("/api/boards", params={"experiment_id": exp_node["id"]}).json()
    assert len(per_exp) == 2  # the experiment's own board + its run's board
    assert c.get("/api/boards", params={"experiment_id": "nope"}).status_code == 404


def test_board_title_extracted_from_html(tmp_path):
    party, _ = _setup(tmp_path)
    titled = tmp_path / "b.html"
    titled.write_bytes(b"<html><head><title>  Ablation \n Story </title></head></html>")
    party.experiment_log_artifact("e", titled, media_type="text/html")
    assert party.board_list()[0]["title"] == "Ablation Story"


def test_boards_searchable_via_carrier_fts(tmp_path):
    party, _ = _setup(tmp_path)
    rid = _start_run(party)
    b = tmp_path / "fricative_gallery.html"
    b.write_bytes(BOARD_HTML)
    party.run_log_artifact(rid, b, media_type="text/html", note="fricative demo gallery")

    hits = party.graph_query("fricative gallery board", mode="lexical")["results"]
    assert hits and hits[0]["id"] == rid

    # survives an index rebuild (artifacts live on the node doc)
    party.store.rebuild_index()
    hits = party.graph_query("fricative gallery board", mode="lexical")["results"]
    assert hits and hits[0]["id"] == rid


def test_boards_lib_served_and_csp_admits_it(tmp_path):
    party, c = _setup(tmp_path)
    r = c.get("/boards-lib/mlparty.js")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/javascript")
    assert "window.mlparty" in r.text

    ref = party.store.put_artifact_bytes(BOARD_HTML, "b.html", media_type="text/html")
    csp = c.get(f"/boards/{ref.sha256}").headers["content-security-policy"]
    assert "script-src 'unsafe-inline' 'self'" in csp


def test_annotate_rejects_sandboxed_origin(tmp_path):
    party, c = _setup(tmp_path)
    exp = party.experiment_ensure("p", "e")
    r = c.post(f"/api/nodes/{exp['id']}/annotate",
               json={"text": "from a board"}, headers={"Origin": "null"})
    assert r.status_code == 403
    r = c.post(f"/api/nodes/{exp['id']}/annotate", json={"text": "from the viewer"})
    assert r.status_code == 200
