"""What a run captures, and what it must never capture.

Reported by the first external user: running the packaged demo in a working
directory swept personal notes and agent conversation files into the run's
code snapshot — and, through sync, into anything the store is served to.
"""
import subprocess

import pytest

from mlparty.core import MlParty
from mlparty.gitstore import SnapshotNeedsConfirmation, UnsafeSourceRoot, check_source_root

FAST = {"python_exe": "/nonexistent/python"}


def _git(path, *args):
    subprocess.run(["git", "-C", str(path), *args], check=True,
                   capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path):
    """A realistic project: a git repo whose .gitignore excludes private notes."""
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "train.py").write_text("print('train')\n")
    (proj / "kernel.cu").write_text("// cuda\n")
    (proj / ".gitignore").write_text("memory/\nnotes.md\n")
    (proj / "memory").mkdir()
    (proj / "memory" / "MEMORY.md").write_text("my private notes\n")
    (proj / "notes.md").write_text("personal\n")
    _git(proj, "init", "-q")
    _git(proj, "config", "user.email", "t@example.com")
    _git(proj, "config", "user.name", "t")
    _git(proj, "add", "train.py", "kernel.cu", ".gitignore")
    _git(proj, "commit", "-qm", "initial")
    party = MlParty.init(proj / ".mlparty")
    party.experiment_ensure("p", "e", created_by="test")
    return proj, party


def _start(party, proj, **over):
    return party.run_start(
        experiment="e", title="a run", purpose="check what the snapshot captures",
        hypothesis="exploratory: does it respect gitignore?", parameters={"lr": 0.1},
        created_by="test", source_root=proj, **(FAST | over))


def test_gitignored_files_are_never_captured(repo):
    proj, party = repo
    out = _start(party, proj)
    included = party.store.get_node(out["run_id"]).snapshot_report.included
    assert "train.py" in included
    assert "kernel.cu" in included, "tracked sources outside the old allowlist belong in"
    assert "memory/MEMORY.md" not in included
    assert "notes.md" not in included


def test_untracked_but_unignored_file_is_captured(repo):
    proj, party = repo
    (proj / "brand_new.py").write_text("print('not committed yet')\n")
    out = _start(party, proj)
    included = party.store.get_node(out["run_id"]).snapshot_report.included
    assert "brand_new.py" in included


def test_tracked_secret_is_still_denied(repo):
    proj, party = repo
    (proj / ".env").write_text("HF_TOKEN=supersecret\n")
    _git(proj, "add", "-f", ".env")
    out = _start(party, proj)
    report = party.store.get_node(out["run_id"]).snapshot_report
    assert ".env" not in report.included
    assert any(".env" in e for e in report.excluded)


def test_no_source_root_captures_no_source(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "private.md").write_text("should never be captured\n")
    party = MlParty.init(proj / ".mlparty")
    party.experiment_ensure("p", "e", created_by="test")
    out = party.run_start(
        experiment="e", title="no source", purpose="a run that names no source root",
        hypothesis="exploratory: is anything captured?", parameters={"lr": 0.1},
        created_by="test", **FAST)
    run = party.store.get_node(out["run_id"])
    assert run.snapshot_report.included_files == 0
    assert run.snapshot_report.included == []
    assert any("no source_root" in h for h in out["hints"])


def test_non_git_root_requires_confirmation(tmp_path):
    proj = tmp_path / "loose"
    proj.mkdir()
    (proj / "train.py").write_text("print('x')\n")
    (proj / "private.md").write_text("personal\n")
    party = MlParty.init(proj / ".mlparty")
    party.experiment_ensure("p", "e", created_by="test")

    with pytest.raises(SnapshotNeedsConfirmation) as ei:
        _start(party, proj)
    assert "not a git repository" in ei.value.reason
    assert "private.md" in ei.value.preview["files"]  # the user sees it BEFORE it is stored

    out = _start(party, proj, confirm_snapshot=True)
    assert party.store.get_node(out["run_id"]).snapshot_report.included_files == 2


def test_home_directory_is_refused():
    with pytest.raises(UnsafeSourceRoot):
        check_source_root("~")


def test_preview_reports_delta_against_a_stored_snapshot(repo):
    proj, party = repo
    _start(party, proj)

    same = party.snapshot_preview(proj, experiment="e")
    assert same["delta"]["unchanged"] is True

    (proj / "train.py").write_text("print('edited')\n")
    (proj / "extra.py").write_text("print('new')\n")
    changed = party.snapshot_preview(proj, experiment="e")
    assert changed["delta"]["modified"] == ["train.py"]
    assert changed["delta"]["added"] == ["extra.py"]
    assert changed["delta"]["unchanged"] is False


def test_preview_does_not_write_anything(repo):
    proj, party = repo
    before = len(party.store.list_nodes(type="run", limit=100))
    out = party.snapshot_preview(proj, experiment="e")
    assert out["source_mode"] == "git"
    assert len(party.store.list_nodes(type="run", limit=100)) == before
