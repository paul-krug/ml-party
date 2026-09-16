"""Store configuration (store.toml): snapshot allowlist, caps, redaction."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_STORE_TOML = """\
# ml-party store configuration (DESIGN.md §5.6)

[snapshot]
# Allowlist: ONLY these files enter the internal git snapshot; everything else
# is artifact-or-ignored. Fails safe against accidental multi-GB commits.
allow_extensions = [
    ".py", ".sh", ".bash", ".toml", ".yaml", ".yml", ".json", ".md", ".txt",
    ".cfg", ".ini", ".lock", ".ipynb", ".jl", ".r", ".sql",
]
allow_names = [
    "Makefile", "Dockerfile", "justfile",
    ".gitignore", ".gitattributes", ".editorconfig", ".python-version",
]
# Deny wins over allow. Secrets never belong in a snapshot.
deny_patterns = [".env", ".env.*", "*.pem", "*secret*", "*credentials*"]
exclude_dirs = [
    ".git", ".mlparty", "__pycache__", ".venv", "venv", "node_modules",
    ".pytest_cache", ".ruff_cache", ".ipynb_checkpoints", "wandb",
    ".idea", ".vscode", ".egg-info",
]
per_file_cap_bytes = 5_000_000     # an oversized allowlisted file is data, not source
total_cap_bytes = 200_000_000      # hard refusal above this, listing offenders
# Above either threshold — or for any non-git root, where no .gitignore drew
# a boundary — run_start refuses until the caller passes confirm_snapshot.
confirm_above_files = 500
confirm_above_bytes = 25_000_000

[runs]
abandoned_ttl_hours = 72

[redact]
# Regexes merged with the built-in secret-key patterns (applied to parameter
# and captured-env KEYS; matching values are replaced with "[redacted]").
extra_patterns = []

[retrieval]
embedder = "none"                  # none | fastembed | api

[sync]
# Remote store to flush this (spool) store into (DESIGN.md §9). Writes always
# land locally first; a flusher ships them — `mlp sync` or the client lib's
# background thread. Token: inline, file path, or the ML_PARTY_TOKEN env var.
url = ""                           # e.g. "https://tracker.example.org:7327"
token = ""
token_file = ""
interval_seconds = 10
"""


@dataclass
class StoreConfig:
    allow_extensions: set[str] = field(default_factory=set)
    allow_names: set[str] = field(default_factory=set)
    deny_patterns: list[str] = field(default_factory=list)
    exclude_dirs: set[str] = field(default_factory=set)
    per_file_cap_bytes: int = 5_000_000
    total_cap_bytes: int = 200_000_000
    confirm_above_files: int = 500
    confirm_above_bytes: int = 25_000_000
    abandoned_ttl_hours: int = 72
    redact_extra_patterns: list[str] = field(default_factory=list)
    embedder: str = "none"
    sync_url: str = ""
    sync_token: str = ""
    sync_token_file: str = ""
    sync_interval_seconds: float = 10.0

    def resolve_sync_token(self, store_root: Path) -> str:
        import os
        if self.sync_token:
            return self.sync_token
        if self.sync_token_file:
            p = Path(self.sync_token_file)
            if not p.is_absolute():
                p = store_root / p
            return p.read_text().strip()
        return os.environ.get("ML_PARTY_TOKEN", "")

    @classmethod
    def load(cls, path: Path) -> StoreConfig:
        with open(path, "rb") as f:
            raw = tomllib.load(f)
        snap = raw.get("snapshot", {})
        return cls(
            allow_extensions={e.lower() for e in snap.get("allow_extensions", [])},
            allow_names=set(snap.get("allow_names", [])),
            deny_patterns=list(snap.get("deny_patterns", [])),
            exclude_dirs=set(snap.get("exclude_dirs", [])),
            per_file_cap_bytes=int(snap.get("per_file_cap_bytes", 5_000_000)),
            total_cap_bytes=int(snap.get("total_cap_bytes", 200_000_000)),
            confirm_above_files=int(snap.get("confirm_above_files", 500)),
            confirm_above_bytes=int(snap.get("confirm_above_bytes", 25_000_000)),
            abandoned_ttl_hours=int(raw.get("runs", {}).get("abandoned_ttl_hours", 72)),
            redact_extra_patterns=list(raw.get("redact", {}).get("extra_patterns", [])),
            embedder=str(raw.get("retrieval", {}).get("embedder", "none")),
            sync_url=str(raw.get("sync", {}).get("url", "")),
            sync_token=str(raw.get("sync", {}).get("token", "")),
            sync_token_file=str(raw.get("sync", {}).get("token_file", "")),
            sync_interval_seconds=float(raw.get("sync", {}).get("interval_seconds", 10)),
        )
