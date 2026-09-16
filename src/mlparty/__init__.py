"""ml-party — agent-native ML experiment tracking and lineage/knowledge.

Layering (DESIGN.md §8): pydantic ontology models → journal-first
Store (JSONL source of truth + rebuildable SQLite index) → internal-git
snapshot engine → MlParty core API → three thin frontends (MCP server,
`mlp` CLI, in-process client lib) plus a read-only HTTP API for the viewer.
"""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _version

try:                                    # single source of truth: pyproject
    __version__ = _version("mlparty")
except PackageNotFoundError:            # a source tree that was never installed
    __version__ = "0.0.0+unknown"

from .client import RunHandle, attach, start_run
from .core import MlParty

__all__ = ["MlParty", "RunHandle", "__version__", "attach", "start_run"]
