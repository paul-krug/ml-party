"""Append-only JSONL event journal — the store's source of truth.

Every graph mutation is one JSON line: {"v", "id", "ts", "event", "data"}.
The SQLite index is a rebuildable view over this file. Appends take an
exclusive flock so concurrent writers (agent via MCP, training process via
the client lib) interleave without tearing lines.

The ULID `id` is the sync idempotency key (DESIGN.md §9): remote ingest
dedupes on it, so replaying a journal into a server is always safe.
"""
from __future__ import annotations

import fcntl
import json
import os
from collections.abc import Iterator
from pathlib import Path

from .ids import new_id
from .models import utcnow

JOURNAL_VERSION = 1


def locked_append(path: Path, line: str) -> None:
    with open(path, "a", encoding="utf-8") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


class Journal:
    def __init__(self, path: Path):
        self.path = Path(path)

    def append(self, event: str, data: dict) -> dict:
        record = {"v": JOURNAL_VERSION, "id": new_id(), "ts": utcnow().isoformat(),
                  "event": event, "data": data}
        self.append_record(record)
        return record

    def append_record(self, record: dict) -> None:
        """Append a pre-built record verbatim (sync ingest preserves the
        original event id/ts from the source journal)."""
        locked_append(self.path, json.dumps(record, separators=(",", ":"), default=str) + "\n")

    def iter_events(self) -> Iterator[dict]:
        """All complete events. A torn FINAL line is tolerated (a backup or
        crash can catch an append mid-write; append-only means only the tail
        can ever be torn) — corruption anywhere else stays a loud error."""
        if not self.path.exists():
            return
        with open(self.path, encoding="utf-8") as f:
            lines = [ln for ln in f.read().splitlines() if ln.strip()]
        for i, line in enumerate(lines):
            try:
                yield json.loads(line)
            except ValueError:
                if i == len(lines) - 1:
                    return
                raise

    def read_from(self, offset: int) -> tuple[list[dict], int]:
        """Complete records from a byte offset; returns (records, new_offset).
        Same contract as metrics tailing — the flusher's cursor."""
        if not self.path.exists():
            return [], 0
        with open(self.path, "rb") as f:
            f.seek(offset)
            chunk = f.read()
            new_offset = f.tell()
        if chunk and not chunk.endswith(b"\n"):
            last_nl = chunk.rfind(b"\n")
            if last_nl == -1:
                return [], offset
            new_offset = offset + last_nl + 1
            chunk = chunk[: last_nl + 1]
        return [json.loads(x) for x in chunk.decode("utf-8").splitlines() if x], new_offset
