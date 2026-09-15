"""Backup/restore — journal-first copy, torn-tail tolerance."""
import pytest

from mlparty.core import MlParty
from mlparty.store import Store, StoreError

FAST = {"python_exe": "/nonexistent/python"}


def _populated(tmp_path):
    src = tmp_path / "proj"
    src.mkdir()
    (src / "train.py").write_text("print('v1')\n")
    party = MlParty.init(src / ".mlparty")
    party.experiment_ensure("p", "e", created_by="test")
    out = party.run_start(
        experiment="e", title="backed-up run", purpose="exercise backup and restore",
        hypothesis="exploratory: does a restored store rebuild identically?",
        parameters={"lr": 0.1}, created_by="test", source_root=src, **FAST)
    rid = out["run_id"]
    party.run_log_metric(rid, "loss", 0.5, step=0)
    ckpt = tmp_path / "best.pt"
    ckpt.write_bytes(b"weights")
    party.run_log_artifact(rid, ckpt)
    return party, rid


def test_backup_restore_roundtrip(tmp_path):
    party, rid = _populated(tmp_path)
    out = party.store.backup(tmp_path / "bak")
    assert out["files"] > 5 and out["bytes"] > 0
    # nothing rebuildable/client-side leaks into the backup
    assert not (tmp_path / "bak" / "index.sqlite").exists()
    assert not (tmp_path / "bak" / "sync_state.json").exists()

    restored = Store(tmp_path / "bak")
    restored.rebuild_index()
    r = MlParty(restored)
    run = r.store.get_node(rid)
    assert run.title == "backed-up run" and run.status == "open"
    records, _ = r.store.read_metrics(rid)
    assert records[0]["value"] == 0.5
    assert r.store.artifact_path(run.artifacts[0].sha256).read_bytes() == b"weights"
    assert r.git.read_file(run.experiment_id, run.code_ref.commit_sha,
                           "train.py") == b"print('v1')\n"
    # identical graph on both sides
    orig = {n.id for n in party.store.list_nodes()}
    assert {n.id for n in r.store.list_nodes()} == orig


def test_backup_refuses_nonempty_dest(tmp_path):
    party, _ = _populated(tmp_path)
    dest = tmp_path / "bak"
    dest.mkdir()
    (dest / "existing").write_text("x")
    with pytest.raises(StoreError, match="not empty"):
        party.store.backup(dest)


def test_torn_journal_tail_tolerated_mid_corruption_loud(tmp_path):
    party, rid = _populated(tmp_path)
    jpath = party.store.root / "journal.jsonl"

    # torn FINAL line (backup caught an append mid-write): rebuild works
    original = jpath.read_text()
    jpath.write_text(original + '{"v":1,"id":"TORN","ts":"2026')
    n = party.store.rebuild_index()
    assert n > 0
    assert party.store.get_node(rid).title == "backed-up run"

    # torn line in the MIDDLE is corruption and must stay loud
    lines = original.splitlines()
    lines[1] = lines[1][: len(lines[1]) // 2]
    jpath.write_text("\n".join(lines) + "\n")
    with pytest.raises(ValueError):
        party.store.rebuild_index()