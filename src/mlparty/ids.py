import hashlib
import json
import re
from typing import Any

from ulid import ULID


def new_id() -> str:
    return str(ULID())


def slugify(title: str, node_id: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:48] or "node"
    return f"{base}-{node_id[-4:].lower()}"


def params_hash(parameters: dict[str, Any]) -> str:
    blob = json.dumps(parameters, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]
