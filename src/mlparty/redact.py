"""Secrets hygiene: parameter/env keys matching secret patterns are redacted
before anything persists (DESIGN.md §5.8).

Matching is segment-based ("hf_token" → {"hf", "token"}) so snake/kebab/camel
keys match without false positives like "author" matching "auth".
"""
from __future__ import annotations

import re
from typing import Any

SECRET_SEGMENTS = frozenset({
    "token", "secret", "secrets", "password", "passwd", "credential",
    "credentials", "apikey", "bearer",
})
KEY_QUALIFIERS = frozenset({"api", "private", "access", "ssh", "aws", "hf", "deploy"})

REDACTED = "[redacted]"

_SPLIT = re.compile(r"[^a-z0-9]+")
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def _is_secret_key(key: str, extra: list[re.Pattern]) -> bool:
    segs = set(_SPLIT.split(_CAMEL.sub("_", str(key)).lower())) - {""}
    if segs & SECRET_SEGMENTS:
        return True
    if "key" in segs and segs & KEY_QUALIFIERS:
        return True
    return any(p.search(str(key)) for p in extra)


def redact_mapping(
    data: dict[str, Any], extra_patterns: list[str] | None = None
) -> tuple[dict[str, Any], list[str]]:
    """Return (copy with secret-keyed values replaced, redacted key paths)."""
    extra = [re.compile(p) for p in (extra_patterns or [])]
    redacted: list[str] = []

    def walk(d: dict[str, Any], prefix: str) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for k, v in d.items():
            path = f"{prefix}.{k}" if prefix else str(k)
            if _is_secret_key(k, extra):
                out[k] = REDACTED
                redacted.append(path)
            elif isinstance(v, dict):
                out[k] = walk(v, path)
            else:
                out[k] = v
        return out

    return walk(data, ""), redacted
