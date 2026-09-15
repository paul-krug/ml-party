"""MlParty core API — the single implementation behind every frontend
(MCP server, `mlp` CLI, in-process client lib, HTTP viewer). MCP is plumbing;
this is the surface it exposes.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from . import capture
from .contract import ContractViolation, validate_fail, validate_finalize, validate_start
from .gitstore import GitStore
from .ids import new_id, params_hash
from .models import (
    Abstract,
    Annotation,
    CommitRef,
    DataRef,
    Edge,
    ExperimentNode,
    Failure,
    Invocation,
    NodeBase,
    NoteNode,
    ProjectNode,
    Result,
    RunNode,
    utcnow,
)
from .redact import redact_mapping
from .store import NodeNotFound, Store


def _first_sentence(text: str, cap: int = 140) -> str:
    text = " ".join((text or "").split())
    for stop in (". ", "! ", "? "):
        idx = text.find(stop)
        if 0 < idx < cap:
            return text[: idx + 1]
    return text[:cap]


def card(node: NodeBase) -> dict[str, Any]:
    c: dict[str, Any] = {
        "id": node.id, "type": node.type, "title": node.title, "slug": node.slug,
        "tags": node.tags, "created_by": node.created_by,
        "created_at": node.created_at.isoformat(),
    }
    if isinstance(node, RunNode):
        c |= {
            "status": node.status, "experiment_id": node.experiment_id,
            "verdict": node.result.verdict if node.result else None,
            "one_liner": _first_sentence(node.abstract.purpose),
            "started_at": node.started_at.isoformat(),
            "ended_at": node.ended_at.isoformat() if node.ended_at else None,
        }
    elif isinstance(node, NoteNode):
        c |= {"kind": node.kind, "one_liner": _first_sentence(node.body)}
    elif isinstance(node, ExperimentNode):
        c |= {"project_id": node.project_id,
              "one_liner": _first_sentence(node.description or "")}
    elif isinstance(node, ProjectNode):
        c |= {"one_liner": _first_sentence(node.description or "")}
    else:
        c |= {"one_liner": _first_sentence(getattr(node, "body", "") or "")}
    return c


class MlParty:
    def __init__(self, store: Store):
        self.store = store
        self.git = GitStore(store.root / "repos")

    @classmethod
    def open(cls, root: Path | str) -> MlParty:
        return cls(Store(root))

    @classmethod
    def init(cls, root: Path | str) -> MlParty:
        return cls(Store.init(root))

    # ---------------------------------------------------------------- resolve

    def _resolve(self, ref: str, expected_type: str | None = None) -> NodeBase:
        try:
            node = self.store.get_node(ref)
        except NodeNotFound:
            node = None
            if expected_type:
                node = self.store.find_by_title(expected_type, ref)
            if node is None:
                raise NodeNotFound(
                    f"no node {ref!r}"
                    + (f" of type {expected_type!r}" if expected_type else "")
                ) from None
        if expected_type and node.type != expected_type:
            raise NodeNotFound(f"{ref!r} is a {node.type}, expected {expected_type}")
        return node

    def _resolve_any(self, ref: str) -> NodeBase:
        try:
            return self.store.get_node(ref)
        except NodeNotFound:
            for t in ("run", "experiment", "note", "project"):
                node = self.store.find_by_title(t, ref)
                if node is not None:
                    return node
            raise

    # ---------------------------------------------------- projects/experiments

    def project_ensure(self, name: str, description: str | None = None,
                       created_by: str = "unknown") -> dict:
        node = self.store.find_by_title("project", name)
        if node is None:
            node = self.store.create_node(ProjectNode(
                id=new_id(), title=name, description=description, created_by=created_by))
        return card(node)

    def experiment_ensure(self, project: str, name: str, description: str | None = None,
                          created_by: str = "unknown") -> dict:
        proj_card = self.project_ensure(project, created_by=created_by)
        existing = [
            n for n in self.store.list_nodes(type="experiment", project_id=proj_card["id"])
            if n.title == name
        ]
        if existing:
            return card(existing[0])
        node = self.store.create_node(ExperimentNode(
            id=new_id(), title=name, project_id=proj_card["id"],
            description=description, created_by=created_by))
        self.git.ensure_repo(node.id)
        self.store.add_edge(Edge(src=node.id, dst=proj_card["id"], type="part-of",
                                 created_by=created_by))
        return card(node)

    def experiment_list(self, project: str | None = None) -> list[dict]:
        filters: dict[str, Any] = {"type": "experiment"}
        if project:
            filters["project_id"] = self._resolve(project, "project").id
        return [card(n) for n in self.store.list_nodes(**filters)]

    # ------------------------------------------------------------------- runs

    def run_start(
        self,
        experiment: str,
        title: str,
        purpose: str,
        hypothesis: str,
        parameters: dict[str, Any],
        derives_from: list[str] | None = None,
        data_refs: list[dict] | None = None,
        seed: int | None = None,
        tags: list[str] | None = None,
        created_by: str = "unknown",
        source_root: Path | str | None = None,
        python_exe: str | None = None,
        planned_command: str | None = None,
    ) -> dict:
        validate_start(title, purpose, hypothesis, parameters)
        exp = self._resolve(experiment, "experiment")
        root = Path(source_root) if source_root else self.store.root.parent

        clean_params, redacted = redact_mapping(
            parameters, self.store.config.redact_extra_patterns)

        parent_runs = [self._resolve(r, "run") for r in (derives_from or [])]
        parents = [p.code_ref.commit_sha for p in parent_runs if p.code_ref]

        run_id = new_id()
        env_lock = capture.capture_env_lock(python_exe)
        tree_sha, report = self.git.build_snapshot(
            exp.id, root, self.store.config,
            inject={capture.ENV_LOCK_PATH: env_lock},
            extra_exclude={self.store.root},
        )
        report.redacted_keys = redacted

        # hints BEFORE this run is inserted: assist, don't assert (§2.1)
        hints: list[str] = []
        same_tree = self.store.index.runs_by_tree(exp.id, tree_sha)
        if same_tree:
            names = ", ".join(f"{d['title']} ({d['id']})" for d in same_tree[:5])
            hints.append(
                f"source tree identical to {len(same_tree)} prior run(s): {names} — "
                "params-only difference? consider derives-from / compares-to edges")
        stale = self.store.index.list_nodes(type="run", experiment_id=exp.id, status="open")
        if stale:
            hints.append(f"{len(stale)} run(s) still open in this experiment: "
                         + ", ".join(d["id"] for d in stale[:5]))

        parents_key = ",".join(sorted(parents))
        commit_sha = self.store.index.tree_commit_get(exp.id, tree_sha, parents_key)
        new_commit = commit_sha is None
        if new_commit:
            commit_sha = self.git.commit_tree(exp.id, tree_sha, parents,
                                              f"run {run_id}: {title}")
            self.store.record_tree_commit(exp.id, tree_sha, parents_key, commit_sha)
        self.git.set_run_ref(exp.id, run_id, commit_sha)

        invocation = None
        if planned_command:
            invocation = Invocation(argv=[planned_command], cwd=str(root),
                                    captured_by="agent")

        run = RunNode(
            id=run_id, title=title, experiment_id=exp.id,
            abstract=Abstract(purpose=purpose, hypothesis=hypothesis),
            parameters=clean_params, params_hash=params_hash(clean_params),
            data_refs=[DataRef(**d) for d in (data_refs or [])],
            seed=seed, tags=tags or [], created_by=created_by,
            code_ref=CommitRef(repo=f"repos/{exp.id}.git",
                               commit_sha=commit_sha, tree_sha=tree_sha),
            snapshot_report=report,
            project_git=capture.capture_project_git(root),
            invocation=invocation,
            env_lock_ref=capture.ENV_LOCK_PATH,
            hardware=capture.capture_hardware(captured_by="start"),
        )
        self.store.create_node(run)
        for parent in parent_runs:
            self.store.add_edge(Edge(src=run.id, dst=parent.id, type="derives-from",
                                     created_by=created_by))
        return {
            "run_id": run.id,
            "run": card(run),
            "commit": {"sha": commit_sha, "tree": tree_sha, "new_commit": new_commit},
            "snapshot_report": report.model_dump(),
            "hints": hints,
        }

    def run_log_metric(self, run: str, name: str, value: float,
                       step: int | None = None) -> dict:
        node = self._resolve(run, "run")
        return self.store.append_metric(node.id, name, value, step)

    def _log_artifact_onto(self, node: NodeBase, path: Path | str,
                           media_type: str | None, note: str | None) -> dict:
        ref = self.store.put_artifact(path, media_type, note)
        artifacts = [a.model_dump(mode="json") for a in node.artifacts] + [ref.model_dump()]
        self.store.update_node(node.id, {"artifacts": artifacts})
        return ref.model_dump()

    def run_log_artifact(self, run: str, path: Path | str, media_type: str | None = None,
                         note: str | None = None) -> dict:
        return self._log_artifact_onto(self._resolve(run, "run"), path, media_type, note)

    def experiment_log_artifact(self, experiment: str, path: Path | str,
                                media_type: str | None = None,
                                note: str | None = None) -> dict:
        """Cross-run artifacts (experiment-level boards, summary reports)."""
        return self._log_artifact_onto(self._resolve(experiment, "experiment"),
                                       path, media_type, note)

    def run_finalize(self, run: str, method: str, result: dict, reproduce: str,
                     edges: list[dict] | None = None, tags: list[str] | None = None,
                     created_by: str = "unknown") -> dict:
        node = self._resolve(run, "run")
        try:
            result_obj = Result(**result) if result else None
        except (ValidationError, TypeError) as e:
            raise ContractViolation(invalid=[{"field": "result", "reason": str(e)}]) from e

        resolved_edges = self._resolve_edges(node.id, edges, created_by)
        validate_finalize(node, method, result_obj, reproduce)

        abstract = node.abstract.model_dump() | {"method": method}
        updated = self.store.update_node(node.id, {
            "abstract": abstract,
            "result": result_obj.model_dump(),
            "reproduce": reproduce,
            "status": "finalized",
            "ended_at": utcnow().isoformat(),
            "metrics_summary": dict(result_obj.metrics),
            "tags": sorted(set(node.tags) | set(tags or [])),
        })
        for e in resolved_edges:
            self.store.add_edge(e)
        return card(updated)

    def run_fail(self, run: str, what_failed: str, failure_class: str | None = None,
                 why: str | None = None, traceback: str | None = None) -> dict:
        node = self._resolve(run, "run")
        validate_fail(node, what_failed)
        failure = Failure(what_failed=what_failed, failure_class=failure_class,
                          why=why, traceback=traceback)
        updated = self.store.update_node(node.id, {
            "failure": failure.model_dump(),
            "status": "failed",
            "ended_at": utcnow().isoformat(),
        })
        return card(updated)

    def _resolve_edges(self, src: str, edges: list[dict] | None,
                       created_by: str) -> list[Edge]:
        resolved = []
        for e in edges or []:
            dst_ref = e.get("dst") or e.get("target")
            if not dst_ref or not e.get("type"):
                raise ContractViolation(invalid=[{
                    "field": "edges", "reason": "each edge needs 'dst' and 'type'"}])
            try:
                dst = self._resolve_any(dst_ref)
            except NodeNotFound:
                raise ContractViolation(invalid=[{
                    "field": "edges",
                    "reason": f"edge target {dst_ref!r} does not exist"}]) from None
            try:
                resolved.append(Edge(src=src, dst=dst.id, type=e["type"],
                                     note=e.get("note"), created_by=created_by))
            except ValidationError as ve:
                raise ContractViolation(invalid=[{
                    "field": "edges", "reason": str(ve)}]) from ve
        return resolved

    # ------------------------------------------------------------- notes/nodes

    def note_create(self, title: str, body: str, kind: str = "insight",
                    edges: list[dict] | None = None, tags: list[str] | None = None,
                    created_by: str = "unknown") -> dict:
        if not body or len(body.strip()) < 10:
            raise ContractViolation(missing=[] if body else ["body"],
                                    invalid=[] if not body else [
                                        {"field": "body", "reason": "needs at least 10 chars"}])
        node = self.store.create_node(NoteNode(
            id=new_id(), title=title, body=body, kind=kind,  # type: ignore[arg-type]
            tags=tags or [], created_by=created_by))
        for e in self._resolve_edges(node.id, edges, created_by):
            self.store.add_edge(e)
        return card(node)

    def node_get(self, ref: str, include_metrics: bool = False) -> dict:
        node = self._resolve_any(ref)
        out: dict[str, Any] = {
            "node": node.model_dump(mode="json"),
            "edges_out": self.store.edges_for(node.id, "out"),
            "edges_in": self.store.edges_for(node.id, "in"),
        }
        if include_metrics and node.type == "run":
            records, _ = self.store.read_metrics(node.id)
            out["metric_series"] = records
        return out

    def node_annotate(self, ref: str, text: str, edges: list[dict] | None = None,
                      created_by: str = "unknown") -> dict:
        node = self._resolve_any(ref)
        annotations = [a.model_dump(mode="json") for a in node.annotations]
        annotations.append(Annotation(text=text, created_by=created_by).model_dump(mode="json"))
        updated = self.store.update_node(node.id, {"annotations": annotations})
        for e in self._resolve_edges(node.id, edges, created_by):
            self.store.add_edge(e)
        return card(updated)

    # ---------------------------------------------------------------- retrieval

    def graph_query(self, query: str, mode: str = "hybrid", type: str | None = None,
                    experiment: str | None = None, status: str | None = None,
                    tag: str | None = None, limit: int = 10) -> dict:
        from . import retrieval
        experiment_id = self._resolve(experiment, "experiment").id if experiment else None
        return retrieval.query(self.store, query, mode=mode, type=type,
                               experiment_id=experiment_id, status=status,
                               tag=tag, limit=limit)

    def run_diff(self, run_a: str, run_b: str) -> dict:
        from . import diffs
        return diffs.run_diff(self, run_a, run_b)

    # ------------------------------------------------------------------- boards

    def _board_title(self, ref) -> str:
        if ref.note:
            return ref.note
        path = self.store.artifact_path(ref.sha256)
        try:
            head = path.open("rb").read(4096).decode("utf-8", errors="replace")
            m = re.search(r"<title[^>]*>(.*?)</title>", head, re.IGNORECASE | re.DOTALL)
            if m and m.group(1).strip():
                return " ".join(m.group(1).split())
        except OSError:
            pass
        return ref.original_path.rsplit("/", 1)[-1]

    def board_list(self, experiment: str | None = None) -> list[dict]:
        """Boards (text/html artifacts) across the store, newest carrier first.
        With `experiment`: that experiment's own boards + its runs' boards."""
        if experiment is not None:
            exp = self._resolve(experiment, "experiment")
            carriers: list[NodeBase] = [exp, *self.store.list_nodes(
                type="run", experiment_id=exp.id, limit=10_000)]
        else:
            carriers = [*self.store.list_nodes(type="experiment", limit=10_000),
                        *self.store.list_nodes(type="run", limit=10_000)]
        boards = []
        for node in carriers:
            exp_id = node.id if node.type == "experiment" else getattr(
                node, "experiment_id", None)
            for ref in getattr(node, "artifacts", []):
                if (ref.media_type or "") != "text/html":
                    continue
                boards.append({
                    "sha256": ref.sha256,
                    "title": self._board_title(ref),
                    "note": ref.note,
                    "original_path": ref.original_path,
                    "size_bytes": ref.size_bytes,
                    "node_id": node.id,
                    "node_type": node.type,
                    "node_title": node.title,
                    "experiment_id": exp_id,
                    "updated_at": node.updated_at.isoformat(),
                })
        boards.sort(key=lambda b: b["updated_at"], reverse=True)
        return boards

    # ------------------------------------------------------------ run control

    def action_register(self, template: dict, created_by: str = "unknown") -> dict:
        from .actions import ActionStore
        return ActionStore(self.store.root).register(template, created_by).model_dump()

    def action_list(self) -> list[dict]:
        from .actions import ActionStore
        return [t.model_dump() for t in ActionStore(self.store.root).list()]

    def action_remove(self, name: str) -> dict:
        from .actions import ActionStore
        ActionStore(self.store.root).remove(name)
        return {"removed": name}

    def action_invoke(self, name: str, params: dict | None = None,
                      created_by: str = "unknown") -> dict:
        from .actions import invoke
        return invoke(self, name, params, created_by)

    # ------------------------------------------------------------------ janitor

    def janitor(self, ttl_hours: int | None = None) -> list[str]:
        """Mark silent open runs `abandoned` (distinct from declared `failed`)."""
        ttl = ttl_hours if ttl_hours is not None else self.store.config.abandoned_ttl_hours
        cutoff = utcnow() - timedelta(hours=ttl)
        abandoned = []
        for doc in self.store.index.list_nodes(type="run", status="open", limit=10_000):
            if datetime.fromisoformat(doc["started_at"]) > cutoff:
                continue
            hb = self.store.heartbeat_at(doc["id"])
            if hb is not None and hb > cutoff:
                continue
            mpath = self.store.root / "runs" / doc["id"] / "metrics.jsonl"
            if mpath.exists() and datetime.fromtimestamp(mpath.stat().st_mtime, tz=UTC) > cutoff:
                continue
            self.store.update_node(doc["id"], {"status": "abandoned",
                                               "ended_at": utcnow().isoformat()})
            abandoned.append(doc["id"])
        return abandoned
