"""SQLite index over the journal: nodes, edges, FTS5, tree→commit dedup map.

Rebuildable from the journal at any time — never the source of truth. One
connection in WAL mode, writes serialized by a lock (safe for the MCP server
and HTTP viewer sharing a Store in one process; cross-process safety comes
from WAL + short transactions).
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
from pathlib import Path

from .models import (
    CustomNode,
    ExperimentNode,
    NodeBase,
    NoteNode,
    ProjectNode,
    RunNode,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL,
  title TEXT NOT NULL,
  slug TEXT,
  status TEXT,
  project_id TEXT,
  experiment_id TEXT,
  params_hash TEXT,
  created_by TEXT,
  created_at TEXT,
  updated_at TEXT,
  tags TEXT NOT NULL DEFAULT '[]',
  doc TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(type);
CREATE INDEX IF NOT EXISTS idx_nodes_exp ON nodes(experiment_id);
CREATE INDEX IF NOT EXISTS idx_nodes_params ON nodes(params_hash);

CREATE TABLE IF NOT EXISTS edges (
  src TEXT NOT NULL,
  dst TEXT NOT NULL,
  type TEXT NOT NULL,
  note TEXT,
  created_by TEXT,
  created_at TEXT,
  PRIMARY KEY (src, dst, type)
);
CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(dst);

CREATE VIRTUAL TABLE IF NOT EXISTS nodes_fts USING fts5(id UNINDEXED, title, text);

CREATE TABLE IF NOT EXISTS tree_commits (
  experiment_id TEXT NOT NULL,
  tree_sha TEXT NOT NULL,
  parents_key TEXT NOT NULL,
  commit_sha TEXT NOT NULL,
  PRIMARY KEY (experiment_id, tree_sha, parents_key)
);

CREATE TABLE IF NOT EXISTS journal_ids (
  id TEXT PRIMARY KEY
);
"""


def _artifact_terms(node: NodeBase) -> list[str]:
    """Carried artifacts are searchable through their carrying node: basename +
    note, plus a 'board' token for HTML so boards surface in graph_query.
    Containment is provenance — boards never become nodes or edges (§11.1)."""
    terms = []
    for a in getattr(node, "artifacts", []):
        name = a.original_path.rsplit("/", 1)[-1]
        board = "board" if (a.media_type or "") == "text/html" else ""
        terms.append(" ".join(t for t in (name, a.note or "", board) if t))
    return terms


def fts_text(node: NodeBase) -> str:
    parts: list[str] = [" ".join(node.tags)]
    if isinstance(node, RunNode):
        parts += [node.abstract.purpose, node.abstract.hypothesis, node.abstract.method or ""]
        if node.result:
            parts += [
                node.result.summary,
                node.result.surprises or "",
                " ".join(f"{k} {v}" for k, v in node.result.metrics.items()),
            ]
        if node.failure:
            parts += [node.failure.what_failed, node.failure.why or "",
                      node.failure.failure_class or ""]
        parts += [node.reproduce or "", node.status]
        if node.compute:
            # so "which run was jobpool 4711?" is answerable from the other end
            parts += [node.compute.system or "", node.compute.job_id or "",
                      node.compute.host or "", node.compute.note or ""]
    elif isinstance(node, NoteNode):
        parts += [node.kind, node.body]
    elif isinstance(node, (ProjectNode, ExperimentNode)):
        parts += [node.description or ""]
    elif isinstance(node, CustomNode):
        parts += [node.body or ""]
    parts += [a.text for a in node.annotations]
    parts += _artifact_terms(node)
    return "\n".join(p for p in parts if p)


def _fts_match_expr(query: str) -> str:
    tokens = re.findall(r"\w+", query.lower())
    return " OR ".join(f'"{t}"' for t in tokens)


class Index:
    def __init__(self, path: Path):
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._lock = threading.Lock()

    # --- writes ---

    def upsert_node(self, node: NodeBase) -> None:
        doc = node.model_dump(mode="json")
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO nodes "
                "(id, type, title, slug, status, project_id, experiment_id, params_hash,"
                " created_by, created_at, updated_at, tags, doc) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    node.id, node.type, node.title, node.slug,
                    doc.get("status"), doc.get("project_id"), doc.get("experiment_id"),
                    doc.get("params_hash"),
                    node.created_by, doc.get("created_at"), doc.get("updated_at"),
                    json.dumps(node.tags), json.dumps(doc, default=str),
                ),
            )
            self._conn.execute("DELETE FROM nodes_fts WHERE id = ?", (node.id,))
            self._conn.execute(
                "INSERT INTO nodes_fts (id, title, text) VALUES (?,?,?)",
                (node.id, node.title, fts_text(node)),
            )

    def add_edge(self, edge: dict) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO edges (src, dst, type, note, created_by, created_at) "
                "VALUES (?,?,?,?,?,?)",
                (edge["src"], edge["dst"], edge["type"], edge.get("note"),
                 edge.get("created_by"), edge.get("created_at")),
            )

    def tree_commit_put(self, experiment_id: str, tree_sha: str, parents_key: str,
                        commit_sha: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO tree_commits VALUES (?,?,?,?)",
                (experiment_id, tree_sha, parents_key, commit_sha),
            )

    def record_event(self, event_id: str | None) -> None:
        if not event_id:
            return
        with self._lock, self._conn:
            self._conn.execute("INSERT OR IGNORE INTO journal_ids (id) VALUES (?)", (event_id,))

    def has_event(self, event_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM journal_ids WHERE id = ?", (event_id,)).fetchone()
        return row is not None

    def clear(self) -> None:
        with self._lock, self._conn:
            for table in ("nodes", "edges", "nodes_fts", "tree_commits", "journal_ids"):
                self._conn.execute(f"DELETE FROM {table}")

    # --- reads ---

    def get_node_doc(self, node_id: str) -> dict | None:
        row = self._conn.execute("SELECT doc FROM nodes WHERE id = ?", (node_id,)).fetchone()
        return json.loads(row["doc"]) if row else None

    def edges_for(self, node_id: str, direction: str = "both",
                  types: list[str] | None = None) -> list[dict]:
        clauses, args = [], []
        if direction in ("out", "both"):
            clauses.append("src = ?")
            args.append(node_id)
        if direction in ("in", "both"):
            clauses.append("dst = ?")
            args.append(node_id)
        sql = f"SELECT * FROM edges WHERE ({' OR '.join(clauses)})"
        if types:
            sql += f" AND type IN ({','.join('?' * len(types))})"
            args += types
        return [dict(r) for r in self._conn.execute(sql, args).fetchall()]

    def all_edges(self) -> list[dict]:
        return [dict(r) for r in self._conn.execute("SELECT * FROM edges").fetchall()]

    def list_nodes(self, type: str | None = None, project_id: str | None = None,
                   experiment_id: str | None = None, status: str | None = None,
                   tag: str | None = None, params_hash: str | None = None,
                   limit: int = 500) -> list[dict]:
        clauses, args = ["1=1"], []
        for col, val in (("type", type), ("project_id", project_id),
                         ("experiment_id", experiment_id), ("status", status),
                         ("params_hash", params_hash)):
            if val is not None:
                clauses.append(f"{col} = ?")
                args.append(val)
        if tag is not None:
            clauses.append("tags LIKE ?")
            args.append(f'%"{tag}"%')
        sql = (f"SELECT doc FROM nodes WHERE {' AND '.join(clauses)} "
               f"ORDER BY created_at DESC LIMIT ?")
        args.append(limit)
        return [json.loads(r["doc"]) for r in self._conn.execute(sql, args).fetchall()]

    def count_by_type(self) -> dict[str, int]:
        return {r["type"]: r["n"] for r in self._conn.execute(
            "SELECT type, COUNT(*) AS n FROM nodes GROUP BY type").fetchall()}

    def find_by_title(self, type: str, title: str) -> dict | None:
        row = self._conn.execute(
            "SELECT doc FROM nodes WHERE type = ? AND title = ? LIMIT 1", (type, title)
        ).fetchone()
        return json.loads(row["doc"]) if row else None

    def fts_search(self, query: str, limit: int = 20) -> list[tuple[str, float]]:
        """Lexical BM25 search. Returns (node_id, score), higher score = better."""
        expr = _fts_match_expr(query)
        if not expr:
            return []
        rows = self._conn.execute(
            "SELECT id, bm25(nodes_fts) AS rank FROM nodes_fts WHERE nodes_fts MATCH ? "
            "ORDER BY rank LIMIT ?",
            (expr, limit),
        ).fetchall()
        return [(r["id"], -float(r["rank"])) for r in rows]

    def tree_commit_get(self, experiment_id: str, tree_sha: str,
                        parents_key: str) -> str | None:
        row = self._conn.execute(
            "SELECT commit_sha FROM tree_commits WHERE experiment_id = ? AND tree_sha = ? "
            "AND parents_key = ?",
            (experiment_id, tree_sha, parents_key),
        ).fetchone()
        return row["commit_sha"] if row else None

    def runs_by_tree(self, experiment_id: str, tree_sha: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT doc FROM nodes WHERE type = 'run' AND experiment_id = ?", (experiment_id,)
        ).fetchall()
        docs = [json.loads(r["doc"]) for r in rows]
        return [d for d in docs if (d.get("code_ref") or {}).get("tree_sha") == tree_sha]
