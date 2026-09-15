"""ml-party — agent-native ML experiment tracking and lineage/knowledge.

Layering (DESIGN.md §8): pydantic ontology models → journal-first
Store (JSONL source of truth + rebuildable SQLite index) → internal-git
snapshot engine → MlParty core API → three thin frontends (MCP server,
`mlp` CLI, in-process client lib) plus a read-only HTTP API for the viewer.
"""

__version__ = "0.1.0"

from .client import RunHandle, attach, start_run
from .core import MlParty

__all__ = ["MlParty", "RunHandle", "__version__", "attach", "start_run"]
