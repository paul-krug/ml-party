"""Core ontology (DESIGN.md §3): fixed spine, extensible ribs.

Nodes serialize to JSON documents; the journal holds them as the source of
truth and the SQLite index stores the same document for querying. Custom node
types fall back to `CustomNode` and inherit every common field.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

SCHEMA_VERSION = 1

CORE_EDGE_TYPES = frozenset({
    "derives-from", "supersedes", "compares-to", "produces",
    "uses-data", "part-of", "confirms", "refutes", "duplicate-of",
})

SUGGESTED_FAILURE_CLASSES = ("crash", "oom", "diverged", "wrong-result", "env", "cancelled")


def utcnow() -> datetime:
    return datetime.now(UTC)


class Edge(BaseModel):
    src: str
    dst: str
    type: str
    note: str | None = None
    created_by: str = "unknown"
    created_at: datetime = Field(default_factory=utcnow)

    @field_validator("type")
    @classmethod
    def _controlled_vocabulary(cls, v: str) -> str:
        if v in CORE_EDGE_TYPES or v.startswith("x-"):
            return v
        raise ValueError(
            f"edge type {v!r} not in controlled vocabulary {sorted(CORE_EDGE_TYPES)}; "
            "custom edge types must use the 'x-' prefix"
        )


class Abstract(BaseModel):
    purpose: str
    hypothesis: str
    method: str | None = None


class Result(BaseModel):
    summary: str
    verdict: Literal["confirmed", "refuted", "inconclusive"]
    metrics: dict[str, float] = Field(default_factory=dict)
    metrics_note: str | None = None
    surprises: str | None = None


class Failure(BaseModel):
    what_failed: str
    failure_class: str | None = None
    why: str | None = None
    traceback: str | None = None


class CommitRef(BaseModel):
    repo: str
    commit_sha: str
    tree_sha: str


class SnapshotReport(BaseModel):
    included_files: int = 0
    included_bytes: int = 0
    # What actually went in (capped; included_files keeps the exact count).
    # Without this the report can say what it left out but not what it took —
    # the only question that matters when checking for a leak.
    included: list[str] = Field(default_factory=list)
    source_mode: str | None = None  # 'git' | 'walk' | None (no source captured)
    excluded: list[str] = Field(default_factory=list)
    skipped_for_size: list[str] = Field(default_factory=list)
    redacted_keys: list[str] = Field(default_factory=list)
    note: str | None = None


class ProjectGitRef(BaseModel):
    remote: str | None = None
    head: str | None = None
    branch: str | None = None
    dirty: bool | None = None


class Invocation(BaseModel):
    argv: list[str] = Field(default_factory=list)
    cwd: str | None = None
    entrypoint: str | None = None
    env: dict[str, str] = Field(default_factory=dict)
    captured_by: str | None = None  # 'client' | 'agent'


class DataRef(BaseModel):
    uri: str
    fingerprint: str | None = None
    role: str | None = None


class GpuInfo(BaseModel):
    name: str | None = None
    vram_mb: int | None = None
    driver: str | None = None


class Hardware(BaseModel):
    host: str | None = None
    platform: str | None = None
    cpu: str | None = None
    ram_gb: float | None = None
    gpus: list[GpuInfo] = Field(default_factory=list)
    captured_by: str | None = None  # 'start' (launcher's view) | 'attach' (compute host)


class ComputeRef(BaseModel):
    """Where a run executes, when that is not the machine that started it.

    Deliberately scheduler-agnostic — a label, the job system's own handle,
    and a link that finds the job again. ml-party integrates with no job
    system and never polls one: this is a pointer the user (or an agent)
    follows, so `url` is the field that earns its keep.
    """
    system: str | None = None       # "jobpool", "slurm", "modal" — free text
    job_id: str | None = None       # the job system's own handle
    url: str | None = None          # where a human finds it again
    host: str | None = None         # the compute box, when known ahead of time
    note: str | None = None
    captured_by: str | None = None  # 'start' | 'agent' (registered later) | 'attach'


class ArtifactRef(BaseModel):
    sha256: str
    size_bytes: int
    media_type: str | None = None
    original_path: str
    note: str | None = None


class Annotation(BaseModel):
    text: str
    created_by: str = "unknown"
    created_at: datetime = Field(default_factory=utcnow)


class NodeBase(BaseModel):
    id: str
    type: str
    title: str
    slug: str = ""
    tags: list[str] = Field(default_factory=list)
    annotations: list[Annotation] = Field(default_factory=list)
    created_by: str = "unknown"
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    schema_version: int = SCHEMA_VERSION


class ProjectNode(NodeBase):
    type: Literal["project"] = "project"
    description: str | None = None


class ExperimentNode(NodeBase):
    type: Literal["experiment"] = "experiment"
    project_id: str
    description: str | None = None
    # cross-run artifacts (experiment-level boards, summary reports) — mirrors
    # RunNode.artifacts; boards stay artifacts, never nodes (DESIGN.md §11.1)
    artifacts: list[ArtifactRef] = Field(default_factory=list)


class NoteNode(NodeBase):
    type: Literal["note"] = "note"
    kind: Literal["feedback", "reference", "insight"] = "insight"
    body: str = ""


class RunNode(NodeBase):
    type: Literal["run"] = "run"
    experiment_id: str
    status: Literal["open", "finalized", "failed", "abandoned"] = "open"
    provenance: Literal["live", "retro"] = "live"
    abstract: Abstract
    parameters: dict[str, Any] = Field(default_factory=dict)
    params_hash: str = ""
    result: Result | None = None
    reproduce: str | None = None
    failure: Failure | None = None
    # repro tuple — auto-captured at run.start for live runs
    code_ref: CommitRef | None = None
    snapshot_report: SnapshotReport | None = None
    project_git: ProjectGitRef | None = None
    invocation: Invocation | None = None
    env_lock_ref: str | None = None
    # runtime env lock, captured by attach() on the compute host (CAS-stored);
    # env_lock_ref stays the launcher's view inside the snapshot commit
    env_lock_runtime: ArtifactRef | None = None
    data_refs: list[DataRef] = Field(default_factory=list)
    seed: int | None = None
    hardware: Hardware | None = None
    # where it runs, when that is not the machine that started it (§9); None
    # means "here". Declared at start, or registered once the job system
    # answers with a handle — hardware then arrives from the compute host.
    compute: ComputeRef | None = None
    started_at: datetime = Field(default_factory=utcnow)
    ended_at: datetime | None = None
    metrics_summary: dict[str, float] = Field(default_factory=dict)
    artifacts: list[ArtifactRef] = Field(default_factory=list)


class CustomNode(NodeBase):
    model_config = ConfigDict(extra="allow")
    body: str | None = None


_NODE_CLASSES: dict[str, type[NodeBase]] = {
    "project": ProjectNode,
    "experiment": ExperimentNode,
    "run": RunNode,
    "note": NoteNode,
}

Node = ProjectNode | ExperimentNode | RunNode | NoteNode | CustomNode


def parse_node(data: dict[str, Any]) -> NodeBase:
    cls = _NODE_CLASSES.get(data.get("type", ""), CustomNode)
    return cls.model_validate(data)


def dump_node(node: NodeBase) -> dict[str, Any]:
    return node.model_dump(mode="json")
