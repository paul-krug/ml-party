import subprocess

import pytest

from mlparty.capture import capture_invocation, capture_project_git
from mlparty.gitstore import GitStore, SnapshotTooLarge, collect_files
from mlparty.redact import redact_mapping
from mlparty.store import Store


def make_source(tmp_path):
    src = tmp_path / "proj"
    (src / "pkg").mkdir(parents=True)
    (src / "train.py").write_text("print('train')\n")
    (src / "pkg" / "model.py").write_text("x = 1\n")
    (src / "config.yaml").write_text("lr: 0.001\n")
    (src / "data.bin").write_bytes(b"\x00" * 100)
    (src / ".env").write_text("OPENAI_API_KEY=xyz\n")
    (src / "__pycache__").mkdir()
    (src / "__pycache__" / "junk.pyc").write_bytes(b"junk")
    (src / "big.json").write_text("x" * 200)
    return src


@pytest.fixture
def cfg(tmp_path):
    return Store.init(tmp_path / "store").config


def test_collect_allowlist(tmp_path, cfg):
    src = make_source(tmp_path)
    files, report = collect_files(src, cfg)
    assert set(files) == {"train.py", "pkg/model.py", "config.yaml", "big.json"}
    assert report.included_files == 4
    assert any(".env" in e for e in report.excluded)
    assert any("data.bin" in e for e in report.excluded)
    # pruned dirs are not walked, so their contents don't flood the report
    assert not any("junk.pyc" in e for e in report.excluded)


def test_per_file_cap(tmp_path, cfg):
    src = make_source(tmp_path)
    cfg.per_file_cap_bytes = 150
    files, report = collect_files(src, cfg)
    assert "big.json" not in files
    assert any("big.json" in s for s in report.skipped_for_size)


def test_total_cap_refuses_listing_offenders(tmp_path, cfg):
    src = make_source(tmp_path)
    cfg.total_cap_bytes = 10
    with pytest.raises(SnapshotTooLarge) as ei:
        collect_files(src, cfg)
    assert ei.value.offenders[0][1] >= ei.value.offenders[-1][1]


def test_snapshot_commit_dedup_refs_diff(tmp_path, cfg):
    src = make_source(tmp_path)
    gs = GitStore(tmp_path / "repos")
    inject = {".mlparty/env.lock": b"# python 3.11\nsomepkg==1.0\n"}

    tree1, rep1 = gs.build_snapshot("exp1", src, cfg, inject=inject)
    tree2, _ = gs.build_snapshot("exp1", src, cfg, inject=inject)
    assert tree1 == tree2  # content-addressed: identical source -> identical tree
    assert rep1.included_files == 4

    c1 = gs.commit_tree("exp1", tree1, [], "run A")
    gs.set_run_ref("exp1", "runA", c1)

    (src / "train.py").write_text("print('train v2')\n")
    tree3, _ = gs.build_snapshot("exp1", src, cfg, inject=inject)
    assert tree3 != tree1
    c2 = gs.commit_tree("exp1", tree3, [c1], "run B")
    meta = gs.commit_meta("exp1", c2)
    assert meta["parents"] == [c1]
    assert meta["tree"] == tree3

    d = gs.diff("exp1", c1, c2)
    assert any((ch["new"] or ch["old"]) == "train.py" for ch in d["files"])
    assert "train v2" in d["patch"]
    assert d["patch_truncated"] is False

    assert gs.read_file("exp1", c1, ".mlparty/env.lock") == inject[".mlparty/env.lock"]
    assert gs.read_file("exp1", c1, "pkg/model.py") == b"x = 1\n"
    assert gs.read_file("exp1", c1, "no/such.file") is None


def test_redact():
    clean, keys = redact_mapping({
        "lr": 0.1,
        "hf_token": "abc",
        "nested": {"api_key": "x", "author": "paul"},
        "wandbApiKey": "y",
    })
    assert clean["lr"] == 0.1
    assert clean["hf_token"] == "[redacted]"
    assert clean["nested"]["api_key"] == "[redacted]"
    assert clean["nested"]["author"] == "paul"
    assert clean["wandbApiKey"] == "[redacted]"
    assert set(keys) == {"hf_token", "nested.api_key", "wandbApiKey"}


def test_capture_project_git(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    (repo / "a.txt").write_text("a")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t",
         "commit", "-qm", "init"],
        check=True,
    )
    ref = capture_project_git(repo)
    assert ref is not None and len(ref.head) == 40
    assert ref.dirty is False
    (repo / "b.txt").write_text("b")
    assert capture_project_git(repo).dirty is True

    notrepo = tmp_path / "notrepo"
    notrepo.mkdir()
    assert capture_project_git(notrepo) is None


def test_capture_invocation():
    inv = capture_invocation("client")
    assert inv.argv and inv.cwd
    assert inv.captured_by == "client"
