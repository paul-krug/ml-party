"""Internal-git snapshot engine (DESIGN.md §5).

One bare repo per experiment under <store>/repos/<experiment_id>.git, built
with dulwich plumbing — no working checkout, no on-disk churn per run.
Commit identity = (tree, parents): the caller (core.run_start) deduplicates
via the store's tree→commit map before calling commit_tree(). Every run gets
its own ref (refs/runs/<run_id>) — no shared tip, no ref races.
"""
from __future__ import annotations

import fnmatch
import os
import time
from io import BytesIO
from pathlib import Path

from dulwich.diff_tree import tree_changes
from dulwich.objects import Blob, Commit, Tree
from dulwich.patch import write_tree_diff
from dulwich.repo import Repo

from .config import StoreConfig
from .models import SnapshotReport
from .store import safe_id

EXCLUDED_LIST_CAP = 200


class SnapshotTooLarge(Exception):
    def __init__(self, total_bytes: int, cap: int, offenders: list[tuple[str, int]]):
        self.total_bytes = total_bytes
        self.cap = cap
        self.offenders = offenders
        top = ", ".join(f"{p} ({s} B)" for p, s in offenders[:10])
        super().__init__(
            f"snapshot would be {total_bytes} bytes (cap {cap}); largest files: {top}"
        )


def _allowed(name: str, config: StoreConfig) -> bool:
    if any(fnmatch.fnmatch(name, p) for p in config.deny_patterns):
        return False
    if name in config.allow_names:
        return True
    return Path(name).suffix.lower() in config.allow_extensions


def collect_files(
    source_root: Path | str,
    config: StoreConfig,
    extra_exclude: set[Path] | None = None,
) -> tuple[dict[str, Path], SnapshotReport]:
    """Walk source_root applying the allowlist. Returns ({relpath: path}, report).

    Excluded-file lists in the report are capped (counts stay exact) so run
    nodes stay small; pruned directories (exclude_dirs) are not walked at all.
    """
    source_root = Path(source_root).resolve()
    extra_exclude = {Path(p).resolve() for p in (extra_exclude or set())}
    files: dict[str, Path] = {}
    excluded: list[str] = []
    excluded_count = 0
    skipped_size: list[str] = []
    total = 0

    for dirpath, dirnames, filenames in os.walk(source_root, topdown=True):
        dpath = Path(dirpath)
        dirnames[:] = [
            d for d in sorted(dirnames)
            if d not in config.exclude_dirs
            and not d.endswith(".egg-info")
            and (dpath / d).resolve() not in extra_exclude
            and not (dpath / d).is_symlink()
        ]
        for fname in sorted(filenames):
            fpath = dpath / fname
            rel = str(fpath.relative_to(source_root))
            if fpath.is_symlink():
                excluded_count += 1
                if len(excluded) < EXCLUDED_LIST_CAP:
                    excluded.append(f"{rel} (symlink)")
                continue
            if not _allowed(fname, config):
                excluded_count += 1
                if len(excluded) < EXCLUDED_LIST_CAP:
                    excluded.append(f"{rel} (not allowlisted)")
                continue
            size = fpath.stat().st_size
            if size > config.per_file_cap_bytes:
                skipped_size.append(f"{rel} ({size} bytes)")
                continue
            files[rel] = fpath
            total += size

    if total > config.total_cap_bytes:
        sizes = sorted(((r, p.stat().st_size) for r, p in files.items()), key=lambda x: -x[1])
        raise SnapshotTooLarge(total, config.total_cap_bytes, sizes)

    if excluded_count > len(excluded):
        excluded.append(f"... and {excluded_count - len(excluded)} more")
    report = SnapshotReport(
        included_files=len(files), included_bytes=total,
        excluded=excluded, skipped_for_size=skipped_size,
    )
    return files, report


class GitStore:
    def __init__(self, repos_dir: Path | str):
        self.repos_dir = Path(repos_dir)

    def repo_path(self, experiment_id: str) -> Path:
        return self.repos_dir / f"{safe_id(experiment_id, 'experiment id')}.git"

    def ensure_repo(self, experiment_id: str) -> Repo:
        path = self.repo_path(experiment_id)
        if path.exists():
            return Repo(str(path))
        path.mkdir(parents=True, exist_ok=True)
        return Repo.init_bare(str(path))

    def build_snapshot(
        self,
        experiment_id: str,
        source_root: Path | str,
        config: StoreConfig,
        inject: dict[str, bytes] | None = None,
        extra_exclude: set[Path] | None = None,
    ) -> tuple[str, SnapshotReport]:
        """Write blobs + trees for the current working tree; returns (tree_sha, report).

        `inject` adds generated files (e.g. `.mlparty/env.lock`) into the tree
        without touching disk. No commit is created here — dedup on
        (tree, parents) happens in the caller before commit_tree().
        """
        repo = self.ensure_repo(experiment_id)
        files, report = collect_files(source_root, config, extra_exclude)

        root: dict = {}

        def insert(rel: str, mode: int, blob_id: bytes) -> None:
            parts = rel.split("/")
            node = root
            for part in parts[:-1]:
                node = node.setdefault(part.encode(), {})
            node[parts[-1].encode()] = (mode, blob_id)

        for rel, fpath in files.items():
            blob = Blob.from_string(fpath.read_bytes())
            repo.object_store.add_object(blob)
            mode = 0o100755 if (fpath.stat().st_mode & 0o111) else 0o100644
            insert(rel, mode, blob.id)
        for rel, data in (inject or {}).items():
            blob = Blob.from_string(data)
            repo.object_store.add_object(blob)
            insert(rel, 0o100644, blob.id)

        def build(node: dict) -> bytes:
            tree = Tree()
            for name, entry in node.items():
                if isinstance(entry, dict):
                    tree.add(name, 0o040000, build(entry))
                else:
                    mode, blob_id = entry
                    tree.add(name, mode, blob_id)
            repo.object_store.add_object(tree)
            return tree.id

        return build(root).decode(), report

    def commit_tree(self, experiment_id: str, tree_sha: str, parents: list[str],
                    message: str) -> str:
        repo = self.ensure_repo(experiment_id)
        commit = Commit()
        commit.tree = tree_sha.encode()
        commit.parents = [p.encode() for p in sorted(parents)]
        commit.author = commit.committer = b"ml-party <mlparty@local>"
        commit.author_time = commit.commit_time = int(time.time())
        commit.author_timezone = commit.commit_timezone = 0
        commit.encoding = b"UTF-8"
        commit.message = message.encode()
        repo.object_store.add_object(commit)
        return commit.id.decode()

    def set_run_ref(self, experiment_id: str, run_id: str, commit_sha: str) -> None:
        repo = self.ensure_repo(experiment_id)
        repo.refs[f"refs/runs/{run_id}".encode()] = commit_sha.encode()

    def commit_meta(self, experiment_id: str, commit_sha: str) -> dict:
        repo = self.ensure_repo(experiment_id)
        c = repo[commit_sha.encode()]
        return {
            "tree": c.tree.decode(),
            "parents": [p.decode() for p in c.parents],
            "message": c.message.decode(errors="replace"),
            "time": c.commit_time,
        }

    def diff(self, experiment_id: str, commit_a: str, commit_b: str,
             max_patch_bytes: int = 200_000) -> dict:
        repo = self.ensure_repo(experiment_id)
        tree_a = repo[commit_a.encode()].tree
        tree_b = repo[commit_b.encode()].tree
        changes = [
            {
                "type": ch.type,
                "old": ch.old.path.decode() if ch.old.path else None,
                "new": ch.new.path.decode() if ch.new.path else None,
            }
            for ch in tree_changes(repo.object_store, tree_a, tree_b)
        ]
        buf = BytesIO()
        write_tree_diff(buf, repo.object_store, tree_a, tree_b)
        patch = buf.getvalue()
        return {
            "files": changes,
            "patch": patch[:max_patch_bytes].decode("utf-8", errors="replace"),
            "patch_truncated": len(patch) > max_patch_bytes,
        }

    def list_tree(self, experiment_id: str, commit_sha: str) -> list[dict]:
        """Flat file listing of a snapshot commit: [{path, size}]."""
        repo = self.ensure_repo(experiment_id)
        try:
            root = repo[commit_sha.encode()].tree
        except KeyError:
            return []
        files: list[dict] = []

        def walk(tree_id: bytes, prefix: str) -> None:
            for entry in repo[tree_id].iteritems():
                path = f"{prefix}{entry.path.decode()}"
                if entry.mode & 0o040000:
                    walk(entry.sha, path + "/")
                else:
                    files.append({"path": path, "size": len(repo[entry.sha].data)})

        walk(root, "")
        return sorted(files, key=lambda f: f["path"])

    # ------------------------------------------------------------- sync

    def reachable_objects(self, experiment_id: str, commit_sha: str) -> list[str]:
        """All object shas reachable from a commit (commit + trees + blobs +
        parent commits) — the client's have-list for a push."""
        repo = self.ensure_repo(experiment_id)
        seen: list[str] = []
        stack = [commit_sha.encode()]
        visited: set[bytes] = set()
        while stack:
            sha = stack.pop()
            if sha in visited:
                continue
            visited.add(sha)
            try:
                obj = repo[sha]
            except KeyError:
                continue
            seen.append(sha.decode())
            if obj.type_name == b"commit":
                stack.append(obj.tree)
                stack.extend(obj.parents)
            elif obj.type_name == b"tree":
                stack.extend(entry.sha for entry in obj.iteritems())
        return seen

    def missing_objects(self, experiment_id: str, shas: list[str]) -> list[str]:
        repo = self.ensure_repo(experiment_id)
        return [s for s in shas if s.encode() not in repo.object_store]

    def export_objects(self, experiment_id: str, shas: list[str]) -> list[dict]:
        """Loose-object export: [{sha, type, raw(base64)}]."""
        import base64
        repo = self.ensure_repo(experiment_id)
        out = []
        for s in shas:
            obj = repo[s.encode()]
            out.append({"sha": s, "type": obj.type_name.decode(),
                        "raw": base64.b64encode(obj.as_raw_string()).decode()})
        return out

    def import_objects(self, experiment_id: str, objects: list[dict]) -> int:
        """Import loose objects; sha-verified by dulwich on construction."""
        import base64

        from dulwich.objects import ShaFile
        repo = self.ensure_repo(experiment_id)
        n = 0
        for o in objects:
            obj = ShaFile.from_raw_string(
                {"blob": Blob, "tree": Tree, "commit": Commit}[o["type"]].type_num,
                base64.b64decode(o["raw"]))
            if obj.id.decode() != o["sha"]:
                raise ValueError(f"object {o['sha']} content hash mismatch")
            if obj.id not in repo.object_store:
                repo.object_store.add_object(obj)
                n += 1
        return n

    def read_file(self, experiment_id: str, commit_sha: str, path: str) -> bytes | None:
        repo = self.ensure_repo(experiment_id)
        try:
            obj = repo[repo[commit_sha.encode()].tree]
            for part in path.split("/"):
                _, sha = obj[part.encode()]
                obj = repo[sha]
            return obj.data
        except KeyError:
            return None
