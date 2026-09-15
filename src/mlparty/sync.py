"""Spool-and-flush sync client (DESIGN.md §9).

Writes always land in the local (spool) store first; this module ships them
to a remote `mlp serve` instance as three idempotent streams — ULID-keyed
journal events, content-addressed git objects / artifacts, offset-addressed
metrics. Cursors persist in <root>/sync_state.json, advanced only after the
server acks, so a crash or lost response can only cause a re-send, never a
loss — and every re-send is safe by construction.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import httpx

from .gitstore import GitStore
from .store import Store

EVENT_BATCH = 500
METRIC_CHUNK_BYTES = 1 << 20


class SyncError(Exception):
    pass


class SyncClient:
    def __init__(self, store: Store, url: str, token: str,
                 http: httpx.Client | None = None):
        self.store = store
        self.git = GitStore(store.root / "repos")
        self.url = url.rstrip("/")
        self.http = http if http is not None else httpx.Client(
            base_url=self.url, timeout=30.0,
            headers={"Authorization": f"Bearer {token}"})
        self._state_path = store.root / "sync_state.json"
        self._state = self._load_state()

    # ------------------------------------------------------------- state

    def _server_key(self) -> str:
        return hashlib.sha256(self.url.encode()).hexdigest()[:16]

    def _load_state(self) -> dict[str, Any]:
        try:
            all_state = json.loads(self._state_path.read_text())
        except (OSError, ValueError):
            all_state = {}
        return all_state.setdefault(self._server_key(), {
            "url": self.url, "journal_offset": 0, "metrics": {},
            "artifacts": [], "git_refs": {},
        })

    def _save_state(self) -> None:
        try:
            all_state = json.loads(self._state_path.read_text())
        except (OSError, ValueError):
            all_state = {}
        all_state[self._server_key()] = self._state
        tmp = self._state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(all_state, indent=1))
        tmp.rename(self._state_path)

    # ------------------------------------------------------------- streams

    def _post(self, path: str, payload: dict) -> dict:
        r = self.http.post(path, json=payload)
        if r.status_code == 409:
            return r.json().get("detail", {}) | {"conflict": True}
        if r.status_code >= 400:
            raise SyncError(f"{path}: HTTP {r.status_code} {r.text[:200]}")
        return r.json()

    def flush_events(self) -> int:
        sent = 0
        while True:
            events, new_offset = self.store.journal.read_from(self._state["journal_offset"])
            if not events:
                return sent
            for i in range(0, len(events), EVENT_BATCH):
                self._post("/api/ingest/events", {"events": events[i:i + EVENT_BATCH]})
            sent += len(events)
            self._state["journal_offset"] = new_offset
            self._save_state()

    def flush_metrics(self) -> int:
        sent = 0
        runs_dir = self.store.root / "runs"
        if not runs_dir.exists():
            return 0
        for run_dir in sorted(runs_dir.iterdir()):
            mpath = run_dir / "metrics.jsonl"
            if not mpath.exists():
                continue
            run_id = run_dir.name
            cursor = int(self._state["metrics"].get(run_id, 0))
            size = mpath.stat().st_size
            while cursor < size:
                with open(mpath, "rb") as f:
                    f.seek(cursor)
                    chunk = f.read(METRIC_CHUNK_BYTES)
                if chunk and not chunk.endswith(b"\n"):
                    nl = chunk.rfind(b"\n")
                    if nl == -1:
                        break  # partial line still being written
                    chunk = chunk[: nl + 1]
                out = self._post(f"/api/ingest/metrics/{run_id}",
                                 {"expected_offset": cursor, "chunk": chunk.decode("utf-8")})
                if out.get("conflict"):
                    server_size = int(out.get("size", 0))
                    if server_size > size:
                        raise SyncError(
                            f"server metrics for {run_id} are longer than local — "
                            "two spools syncing the same run?")
                    # resuming from the server's size is only sound if the
                    # server file is a byte-prefix of ours — prove it
                    server_sha = out.get("sha256")
                    if server_sha is not None:
                        with open(mpath, "rb") as f:
                            local_sha = hashlib.sha256(f.read(server_size)).hexdigest()
                        if local_sha != server_sha:
                            raise SyncError(
                                f"server metrics for {run_id} diverged from the spool "
                                f"(prefix hash mismatch at {server_size} bytes) — "
                                "refusing to resume; inspect/reset the server copy")
                    cursor = server_size
                else:
                    cursor += len(chunk)
                    sent += 1
                self._state["metrics"][run_id] = cursor
                self._save_state()
        return sent

    def flush_artifacts(self) -> int:
        done = set(self._state["artifacts"])
        cas = self.store.root / "artifacts" / "sha256"
        sent = 0
        if not cas.exists():
            return 0
        for path in sorted(cas.rglob("*")):
            if not path.is_file() or path.suffix == ".tmp":
                continue
            sha = path.name
            if sha in done:
                continue
            r = self.http.put(f"/api/ingest/artifacts/{sha}", content=path.read_bytes())
            if r.status_code >= 400:
                raise SyncError(f"artifact {sha}: HTTP {r.status_code} {r.text[:200]}")
            done.add(sha)
            sent += 1
            self._state["artifacts"] = sorted(done)
            self._save_state()
        return sent

    def flush_git(self) -> int:
        pushed = 0
        repos = self.store.root / "repos"
        if not repos.exists():
            return 0
        for repo_dir in sorted(repos.glob("*.git")):
            exp_id = repo_dir.name.removesuffix(".git")
            repo = self.git.ensure_repo(exp_id)
            ref_state: dict = self._state["git_refs"].setdefault(exp_id, {})
            for refname, sha in repo.get_refs().items():
                ref = refname.decode()
                if not ref.startswith("refs/runs/"):
                    continue
                commit = sha.decode()
                if ref_state.get(ref) == commit:
                    continue
                shas = self.git.reachable_objects(exp_id, commit)
                missing = self._post(f"/api/ingest/git/{exp_id}/missing",
                                     {"shas": shas})["missing"]
                objects = self.git.export_objects(exp_id, missing) if missing else []
                self._post(f"/api/ingest/git/{exp_id}",
                           {"objects": objects, "refs": {ref: commit}})
                ref_state[ref] = commit
                pushed += 1
                self._save_state()
        return pushed

    def flush_heartbeats(self) -> None:
        for doc in self.store.index.list_nodes(type="run", status="open", limit=1000):
            if self.store.heartbeat_at(doc["id"]) is not None:
                try:
                    self._post(f"/api/ingest/heartbeat/{doc['id']}", {})
                except SyncError:
                    pass  # liveness forwarding is best-effort

    def flush(self) -> dict:
        """One full pass; safe to call repeatedly / concurrently with writes."""
        out = {
            "events": self.flush_events(),
            "git_refs": self.flush_git(),
            "artifacts": self.flush_artifacts(),
            "metric_chunks": self.flush_metrics(),
        }
        self.flush_heartbeats()
        return out

    def close(self) -> None:
        self.http.close()


def from_store(store: Store, url: str | None = None,
               token: str | None = None) -> SyncClient | None:
    """Build a SyncClient from the store's [sync] config (overridable);
    returns None when no remote is configured."""
    cfg = store.config
    url = url or cfg.sync_url
    if not url:
        return None
    token = token or cfg.resolve_sync_token(Path(store.root))
    if not token:
        raise SyncError(f"sync url {url} configured but no token "
                        "(store.toml [sync] token/token_file or ML_PARTY_TOKEN)")
    return SyncClient(store, url, token)
