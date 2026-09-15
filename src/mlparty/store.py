"""Store facade: journal-first writes, SQLite-indexed reads.

Write path: append the event to journal.jsonl (fsync'd, flock'd), then apply
it to the index. A crash between the two leaves the index stale, never wrong
— `rebuild_index()` replays the journal. Per-run metric series live in
runs/<id>/metrics.jsonl (append-only, live-tailable); artifacts live in a
sha256 CAS.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import DEFAULT_STORE_TOML, StoreConfig
from .ids import slugify
from .index import Index
from .journal import Journal, locked_append
from .models import ArtifactRef, Edge, NodeBase, dump_node, parse_node, utcnow


class StoreError(Exception):
    pass


class NodeNotFound(StoreError):
    pass


# ids and hashes become path segments under the store root — reject anything
# that could traverse ('.', '..', separators) before it touches the filesystem
_SAFE_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")
_SHA256_HEX = re.compile(r"[0-9a-f]{64}")


def safe_id(value: str, what: str = "id") -> str:
    if not _SAFE_ID.fullmatch(value or ""):
        raise StoreError(f"invalid {what} {value!r}")
    return value


def safe_sha256(value: str) -> str:
    if not _SHA256_HEX.fullmatch(value or ""):
        raise StoreError(f"invalid sha256 {value!r}")
    return value


class Store:
    def __init__(self, root: Path | str):
        self.root = Path(root)
        if not (self.root / "store.toml").exists():
            raise StoreError(
                f"no ml-party store at {self.root} — create one with `mlp init` / Store.init()"
            )
        self.config = StoreConfig.load(self.root / "store.toml")
        self.journal = Journal(self.root / "journal.jsonl")
        self.index = Index(self.root / "index.sqlite")

    @classmethod
    def init(cls, root: Path | str) -> Store:
        root = Path(root)
        root.mkdir(parents=True, exist_ok=True)
        for sub in ("repos", "runs", "artifacts"):
            (root / sub).mkdir(exist_ok=True)
        cfg = root / "store.toml"
        if not cfg.exists():
            cfg.write_text(DEFAULT_STORE_TOML)
        (root / "journal.jsonl").touch()
        return cls(root)

    # ------------------------------------------------------------- graph writes

    def create_node(self, node: NodeBase) -> NodeBase:
        if not node.slug:
            node.slug = slugify(node.title, node.id)
        doc = dump_node(node)
        rec = self.journal.append("node.created", doc)
        self.index.upsert_node(node)
        self.index.record_event(rec["id"])
        return node

    def update_node(self, node_id: str, fields: dict[str, Any]) -> NodeBase:
        """Shallow update: top-level keys are replaced wholesale."""
        doc = self.index.get_node_doc(node_id)
        if doc is None:
            raise NodeNotFound(node_id)
        fields = {**fields, "updated_at": utcnow().isoformat()}
        doc.update(fields)
        node = parse_node(doc)
        rec = self.journal.append("node.updated", {"id": node_id, "fields": fields})
        self.index.upsert_node(node)
        self.index.record_event(rec["id"])
        return node

    def add_edge(self, edge: Edge, *, check_targets: bool = True) -> Edge:
        if check_targets:
            for nid in (edge.src, edge.dst):
                if self.index.get_node_doc(nid) is None:
                    raise NodeNotFound(nid)
        data = edge.model_dump(mode="json")
        rec = self.journal.append("edge.added", data)
        self.index.add_edge(data)
        self.index.record_event(rec["id"])
        return edge

    def record_tree_commit(self, experiment_id: str, tree_sha: str, parents_key: str,
                           commit_sha: str) -> None:
        rec = self.journal.append("gitmap.recorded", {
            "experiment_id": experiment_id, "tree_sha": tree_sha,
            "parents_key": parents_key, "commit_sha": commit_sha,
        })
        self.index.tree_commit_put(experiment_id, tree_sha, parents_key, commit_sha)
        self.index.record_event(rec["id"])

    # ------------------------------------------------------------- reads

    def get_node(self, node_id: str) -> NodeBase:
        doc = self.index.get_node_doc(node_id)
        if doc is None:
            raise NodeNotFound(node_id)
        return parse_node(doc)

    def list_nodes(self, **filters: Any) -> list[NodeBase]:
        return [parse_node(d) for d in self.index.list_nodes(**filters)]

    def find_by_title(self, type: str, title: str) -> NodeBase | None:
        doc = self.index.find_by_title(type, title)
        return parse_node(doc) if doc else None

    def edges_for(self, node_id: str, direction: str = "both",
                  types: list[str] | None = None) -> list[dict]:
        return self.index.edges_for(node_id, direction, types)

    # ------------------------------------------------------------- rebuild

    def _apply_event(self, ev: dict) -> None:
        data = ev["data"]
        if ev["event"] == "node.created":
            self.index.upsert_node(parse_node(data))
        elif ev["event"] == "node.updated":
            doc = self.index.get_node_doc(data["id"])
            if doc is not None:
                doc.update(data["fields"])
                self.index.upsert_node(parse_node(doc))
        elif ev["event"] == "edge.added":
            self.index.add_edge(data)
        elif ev["event"] == "gitmap.recorded":
            self.index.tree_commit_put(data["experiment_id"], data["tree_sha"],
                                       data["parents_key"], data["commit_sha"])
        self.index.record_event(ev.get("id"))

    def rebuild_index(self) -> int:
        """Replay the journal into a fresh index. Returns events applied."""
        self.index.clear()
        n = 0
        for ev in self.journal.iter_events():
            n += 1
            self._apply_event(ev)
        return n

    # ------------------------------------------------------------- sync ingest

    def ingest_events(self, events: list[dict]) -> dict:
        """Apply journal events shipped from another store (DESIGN.md §9).

        Idempotent by construction: events are deduped on their ULID id, so
        replaying a client journal (after a crash, a lost ack, `mlp sync`)
        is always safe. Events are preserved verbatim in this journal —
        original id/ts/authorship survive the hop."""
        applied = skipped = 0
        for ev in events:
            eid = ev.get("id")
            if not eid or not isinstance(ev.get("event"), str) or "data" not in ev:
                raise StoreError("malformed event: needs id, event, data")
            if self.index.has_event(eid):
                skipped += 1
                continue
            self.journal.append_record(ev)
            self._apply_event(ev)
            applied += 1
        return {"applied": applied, "skipped": skipped}

    def append_metrics_chunk(self, run_id: str, expected_offset: int, chunk: str) -> dict:
        """Offset-addressed metric append for sync: the client only advances
        its cursor after an ack, so a retry either matches the current size
        (appended) or conflicts (client verifies + resumes from `size`).

        The size check happens UNDER the append flock — a duplicate delivery
        (client timeout + retry racing the original request) must conflict,
        never interleave. On conflict the current file's sha256 is returned
        so the client can prove its local prefix matches before resuming."""
        path = self.metrics_path(run_id)
        data = (chunk if chunk.endswith("\n") else chunk + "\n") if chunk else ""
        with open(path, "a+", encoding="utf-8") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                size = os.fstat(f.fileno()).st_size
                if expected_offset != size:
                    f.seek(0)
                    digest = hashlib.sha256(f.read(size).encode()).hexdigest()
                    return {"ok": False, "size": size, "sha256": digest}
                if data:
                    f.seek(0, 2)
                    f.write(data)
                    f.flush()
                    os.fsync(f.fileno())
                return {"ok": True, "size": size + len(data.encode())}
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    # ------------------------------------------------------------- metrics

    def run_dir(self, run_id: str) -> Path:
        d = self.root / "runs" / safe_id(run_id, "run id")
        d.mkdir(parents=True, exist_ok=True)
        return d

    def metrics_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "metrics.jsonl"

    def append_metric(self, run_id: str, name: str, value: float,
                      step: int | None = None) -> dict:
        rec: dict[str, Any] = {"ts": utcnow().isoformat(), "name": name, "value": float(value)}
        if step is not None:
            rec["step"] = int(step)
        locked_append(self.metrics_path(run_id), json.dumps(rec, separators=(",", ":")) + "\n")
        return rec

    def read_metrics(self, run_id: str, offset: int = 0,
                     name: str | None = None) -> tuple[list[dict], int]:
        """Read metric records from a byte offset; returns (records, new_offset).

        The offset contract makes live tailing (CLI `mlp tail`, HTTP SSE) a
        simple poll loop over an append-only file.
        """
        path = self.metrics_path(run_id)
        if not path.exists():
            return [], 0
        with open(path, "rb") as f:
            f.seek(offset)
            chunk = f.read()
            new_offset = f.tell()
        # only consume complete lines; leave a partial trailing line for the next poll
        if chunk and not chunk.endswith(b"\n"):
            last_nl = chunk.rfind(b"\n")
            if last_nl == -1:
                return [], offset
            new_offset = offset + last_nl + 1
            chunk = chunk[: last_nl + 1]
        records = []
        for line in chunk.decode("utf-8").splitlines():
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except ValueError:
                continue  # a torn line must never take the whole read path down
        if name is not None:
            records = [r for r in records if r.get("name") == name]
        return records, new_offset

    # ------------------------------------------------------------- artifacts CAS

    def put_artifact(self, src: Path | str, media_type: str | None = None,
                     note: str | None = None) -> ArtifactRef:
        src = Path(src)
        h = hashlib.sha256()
        size = 0
        with open(src, "rb") as f:
            while chunk := f.read(1 << 20):
                h.update(chunk)
                size += len(chunk)
        digest = h.hexdigest()
        dest = self.root / "artifacts" / "sha256" / digest[:2] / digest[2:4] / digest
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_suffix(".tmp")
            shutil.copy2(src, tmp)
            tmp.rename(dest)
        return ArtifactRef(sha256=digest, size_bytes=size, media_type=media_type,
                           original_path=str(src), note=note)

    def put_artifact_bytes(self, data: bytes, original_path: str,
                           media_type: str | None = None,
                           note: str | None = None) -> ArtifactRef:
        digest = hashlib.sha256(data).hexdigest()
        dest = self.root / "artifacts" / "sha256" / digest[:2] / digest[2:4] / digest
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_suffix(".tmp")
            tmp.write_bytes(data)
            tmp.rename(dest)
        return ArtifactRef(sha256=digest, size_bytes=len(data), media_type=media_type,
                           original_path=original_path, note=note)

    def artifact_path(self, sha256: str) -> Path:
        safe_sha256(sha256)
        return self.root / "artifacts" / "sha256" / sha256[:2] / sha256[2:4] / sha256

    # ------------------------------------------------------------- backup

    def backup(self, dest: Path | str) -> dict:
        """Copy everything durable to `dest` — safe while writers are live.

        Order matters: the journal is copied FIRST. Content (artifacts, git
        objects) is always written before the journal event referencing it,
        so journal-first yields a snapshot whose journal only references
        content that the later-copied stores already contain. Skipped:
        index.sqlite (rebuildable), sync_state.json (client-side cursors).
        Restore = point mlparty at the copy and run `mlp rebuild-index`."""
        dest = Path(dest)
        dest.mkdir(parents=True, exist_ok=True)
        if any(dest.iterdir()):
            raise StoreError(f"backup destination {dest} is not empty")
        files = 0
        total = 0
        for name in ("store.toml", "journal.jsonl", "actions.json"):
            src = self.root / name
            if src.exists():
                shutil.copy2(src, dest / name)
                files += 1
                total += src.stat().st_size
        for sub in ("runs", "artifacts", "repos", "auth"):
            src_dir = self.root / sub
            if not src_dir.exists():
                continue
            for src in src_dir.rglob("*"):
                if not src.is_file() or src.suffix == ".tmp":
                    continue
                rel = src.relative_to(self.root)
                out = dest / rel
                out.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, out)
                files += 1
                total += src.stat().st_size
        return {"dest": str(dest), "files": files, "bytes": total}

    # ------------------------------------------------------------- heartbeats

    def heartbeat_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "heartbeat"

    def touch_heartbeat(self, run_id: str) -> None:
        self.heartbeat_path(run_id).write_text(utcnow().isoformat())

    def heartbeat_at(self, run_id: str) -> datetime | None:
        """Last heartbeat as a datetime, or None if the run never heartbeat."""
        try:
            path = self.root / "runs" / safe_id(run_id, "run id") / "heartbeat"
            return datetime.fromisoformat(path.read_text().strip())
        except (OSError, ValueError, StoreError):
            return None
