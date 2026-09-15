"""Hybrid retrieval (DESIGN.md §7): BM25 via FTS5 (always
available, zero deps) + optional embeddings behind a swappable interface,
fused by reciprocal rank, then 1-hop typed graph expansion. Nodes with
incoming supersedes/refutes edges are downranked — the graph must not serve
stale beliefs at full confidence. Returns compact cards; agents drill down
with node_get.
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from .core import card
from .index import fts_text
from .models import parse_node
from .store import Store

RRF_K = 60
DOWNRANK = {"supersedes": 0.35, "refutes": 0.35, "duplicate-of": 0.5}
NEIGHBOR_DAMP = 0.55
KEY_EDGE_CAP = 5


# ----------------------------------------------------------- embedder plugin

class FastembedEmbedder:
    model_name = "BAAI/bge-small-en-v1.5"

    def __init__(self):
        from fastembed import TextEmbedding
        self._model = TextEmbedding(self.model_name)

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[float(x) for x in v] for v in self._model.embed(texts)]


def get_embedder(config) -> FastembedEmbedder | None:
    if config.embedder == "fastembed":
        try:
            return FastembedEmbedder()
        except ImportError:
            return None
    return None


def _ensure_embedding_table(store: Store) -> None:
    store.index._conn.execute(
        "CREATE TABLE IF NOT EXISTS embeddings "
        "(id TEXT PRIMARY KEY, model TEXT, doc_hash TEXT, vec TEXT)")


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


def _vector_rank(store: Store, embedder, query: str, limit: int) -> list[tuple[str, float]]:
    """Brute-force cosine over cached node embeddings — fine at lab-notebook
    scale; swap in an ANN index when N demands it."""
    _ensure_embedding_table(store)
    conn = store.index._conn
    stale: list[tuple[str, str, str]] = []
    for doc in store.index.list_nodes(limit=100_000):
        node = parse_node(doc)
        text = f"{node.title}\n{fts_text(node)}"
        doc_hash = hashlib.sha256(text.encode()).hexdigest()[:16]
        row = conn.execute("SELECT doc_hash FROM embeddings WHERE id = ? AND model = ?",
                           (node.id, embedder.model_name)).fetchone()
        if row is None or row["doc_hash"] != doc_hash:
            stale.append((node.id, doc_hash, text))
    if stale:
        vecs = embedder.embed([t for _, _, t in stale])
        with store.index._lock, conn:
            for (nid, doc_hash, _), vec in zip(stale, vecs):
                conn.execute("INSERT OR REPLACE INTO embeddings VALUES (?,?,?,?)",
                             (nid, embedder.model_name, doc_hash, json.dumps(vec)))
    qvec = embedder.embed([query])[0]
    scored = [
        (row["id"], _cosine(qvec, json.loads(row["vec"])))
        for row in conn.execute("SELECT id, vec FROM embeddings WHERE model = ?",
                                (embedder.model_name,)).fetchall()
    ]
    scored.sort(key=lambda x: -x[1])
    return scored[:limit]


# ------------------------------------------------------------------ the query

def _rrf(rankings: list[list[tuple[str, float]]]) -> dict[str, float]:
    fused: dict[str, float] = {}
    for ranking in rankings:
        for pos, (nid, _) in enumerate(ranking):
            fused[nid] = fused.get(nid, 0.0) + 1.0 / (RRF_K + pos)
    return fused


def query(store: Store, q: str, mode: str = "hybrid", type: str | None = None,
          experiment_id: str | None = None, status: str | None = None,
          tag: str | None = None, limit: int = 10) -> dict[str, Any]:
    origins: dict[str, set[str]] = {}
    rankings: list[list[tuple[str, float]]] = []

    if mode in ("hybrid", "lexical", "graph"):
        lex = store.index.fts_search(q, limit * 5)
        rankings.append(lex)
        for nid, _ in lex:
            origins.setdefault(nid, set()).add("lexical")

    embedder_used = False
    if mode in ("hybrid", "semantic"):
        embedder = get_embedder(store.config)
        if embedder is not None:
            vec = _vector_rank(store, embedder, q, limit * 5)
            rankings.append(vec)
            embedder_used = True
            for nid, _ in vec:
                origins.setdefault(nid, set()).add("semantic")
        elif mode == "semantic":
            return {"query": q, "mode": mode, "results": [],
                    "note": "no embedder configured (store.toml [retrieval].embedder)"}

    fused = _rrf(rankings)

    # 1-hop typed expansion from the strongest seeds
    seeds = sorted(fused.items(), key=lambda x: -x[1])[: limit * 2]
    for nid, score in seeds:
        for e in store.index.edges_for(nid, "both"):
            other = e["dst"] if e["src"] == nid else e["src"]
            damped = score * NEIGHBOR_DAMP
            if damped > fused.get(other, 0.0):
                fused[other] = damped
                origins.setdefault(other, set()).add(f"graph:{e['type']}")

    results = []
    for nid, score in sorted(fused.items(), key=lambda x: -x[1]):
        doc = store.index.get_node_doc(nid)
        if doc is None:
            continue
        if type and doc.get("type") != type:
            continue
        if experiment_id and doc.get("experiment_id") != experiment_id and doc["id"] != experiment_id:
            continue
        if status and doc.get("status") != status:
            continue
        if tag and tag not in doc.get("tags", []):
            continue
        node = parse_node(doc)
        c = card(node)

        corrections = store.index.edges_for(nid, "in", types=list(DOWNRANK))
        mult = min((DOWNRANK[e["type"]] for e in corrections), default=1.0)
        c["score"] = round(score * mult, 5)
        if corrections:
            c["corrected_by"] = [{"node": e["src"], "edge": e["type"]} for e in corrections]

        edges = store.index.edges_for(nid, "both")[:KEY_EDGE_CAP]
        key_edges = []
        for e in edges:
            other_id = e["dst"] if e["src"] == nid else e["src"]
            other = store.index.get_node_doc(other_id)
            key_edges.append({
                "type": e["type"],
                "direction": "out" if e["src"] == nid else "in",
                "node": other_id,
                "title": other["title"] if other else None,
            })
        c["key_edges"] = key_edges
        c["why"] = ", ".join(sorted(origins.get(nid, {"graph"})))
        results.append(c)

    results.sort(key=lambda r: -r["score"])
    out: dict[str, Any] = {"query": q, "mode": mode, "results": results[:limit]}
    if mode == "hybrid" and not embedder_used:
        out["note"] = "lexical + graph only (no embedder configured)"
    return out
