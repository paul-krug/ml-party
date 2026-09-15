"""Read-only HTTP API + SSE metric streams — the seam the web viewer consumes.

Same core API as MCP, no write endpoints (the MVP UI is a viewer),
localhost-only by convention (`mlp ui` binds 127.0.0.1; tunnel over SSH for
remote boxes — the TensorBoard pattern).
"""
from __future__ import annotations

import asyncio
import json
import os
import secrets
import time
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import npyview
from .auth import AuthStore, role_at_least
from .contract import ContractViolation
from .core import MlParty, card
from .models import utcnow
from .store import NodeNotFound, StoreError


class AnnotateBody(BaseModel):
    text: str
    created_by: str = "human"


class LoginBody(BaseModel):
    username: str
    password: str


class InvokeBody(BaseModel):
    name: str
    params: dict = {}
    created_by: str = "human"


class EventsBody(BaseModel):
    events: list[dict]


class MetricsChunkBody(BaseModel):
    expected_offset: int
    chunk: str


class GitObjectsBody(BaseModel):
    objects: list[dict] = []
    refs: dict[str, str] = {}


class MissingBody(BaseModel):
    shas: list[str]

# SPA location: ML_PARTY_UI_DIST env > repo checkout (ui/dist) > the
# copy bundled into release wheels (mlparty/ui_dist)
def _default_ui_dist() -> Path:
    env = os.environ.get("ML_PARTY_UI_DIST")
    if env:
        return Path(env)
    repo = Path(__file__).resolve().parent.parent.parent / "ui" / "dist"
    return repo if repo.exists() else Path(__file__).resolve().parent / "ui_dist"


UI_DIST = _default_ui_dist()


ALIVE_WINDOW_SECONDS = 90.0

INLINE_SAFE_PREFIXES = ("image/", "audio/", "video/")
INLINE_SAFE_EXACT = frozenset({"text/plain", "text/csv", "application/json"})

# script-src 'self' admits exactly one non-inline script: this host's own
# /boards-lib/mlparty.js helper. External hosts stay blocked by default-src.
BOARD_CSP = (
    "sandbox allow-scripts; default-src 'none'; "
    "script-src 'unsafe-inline' 'self'; style-src 'unsafe-inline'; "
    "img-src 'self' data: blob:; media-src 'self'; connect-src 'self'; "
    "font-src 'self' data:"
)

BOARDS_LIB = Path(__file__).resolve().parent / "static" / "mlparty.js"


SESSION_COOKIE = "mlp_session"

# in-memory login backoff: after LOGIN_MAX_FAILS consecutive failures per
# (username, client-ip), lock for LOGIN_LOCK_SECONDS, doubling per failure
LOGIN_MAX_FAILS = 5
LOGIN_LOCK_SECONDS = 30.0

# reachable without auth even when it is enabled: health (probes), the login
# flow itself, and the boards helper JS (static code, no data)
OPEN_PATHS = frozenset({
    "/api/health", "/api/auth/login", "/api/auth/logout", "/api/auth/me",
    "/boards-lib/mlparty.js",
})


def build_app(root: Path | str, write_token: str | None = None) -> FastAPI:
    """Read-only viewer app by default; pass `write_token` (mlp serve) to
    enable the authenticated /api/ingest/* sync surface (DESIGN.md §9).

    Once users exist (`mlp user add`), per-user auth takes over — reads
    require a viewer session/token, writes a writer, and the legacy single
    `write_token` is ignored. A store without users behaves as before."""
    party = MlParty.open(root)
    auth = AuthStore(root)
    login_guard: dict[str, tuple[int, float]] = {}

    def gate(request: Request) -> None:
        """Global read gate: with auth enabled, every route outside OPEN_PATHS
        needs at least a read principal. Write routes add their own checks."""
        if request.url.path not in OPEN_PATHS:
            require_read(request)

    app = FastAPI(title="ml-party", docs_url="/api/docs",
                  dependencies=[Depends(gate)])

    @app.exception_handler(StoreError)
    def store_error(_request: Request, exc: StoreError) -> JSONResponse:
        return JSONResponse(status_code=404 if isinstance(exc, NodeNotFound) else 422,
                            content={"detail": str(exc)})

    # --- principals: session cookie (humans), mlp_ bearer token (machines),
    # --- signed read token (sandboxed boards; header or ?bt= for SSE/media)

    def bearer(request: Request) -> str:
        return request.headers.get("authorization", "").removeprefix("Bearer ").strip()

    def current_user(request: Request) -> dict | None:
        token = bearer(request)
        if token.startswith("mlp_"):
            return auth.authenticate_token(token)
        return auth.verify_session(request.cookies.get(SESSION_COOKIE))

    def has_read_token(request: Request) -> bool:
        candidate = request.query_params.get("bt") or bearer(request)
        return auth.verify_read_token(candidate)

    def require_read(request: Request) -> None:
        if not auth.enabled:
            return
        if current_user(request) is None and not has_read_token(request):
            raise HTTPException(401, "authentication required")

    def require_role(request: Request, minimum: str) -> dict:
        user = current_user(request)
        if user is None:
            raise HTTPException(401, "authentication required")
        if not role_at_least(user["role"], minimum):
            raise HTTPException(403, f"needs the {minimum} role")
        return user

    def require_ingest(request: Request) -> None:
        """Writer user when auth is on; the legacy single token otherwise."""
        if auth.enabled:
            require_role(request, "writer")
            return
        if write_token is None:
            raise HTTPException(403, "this server is read-only (start with mlp serve --token)")
        given = bearer(request)
        if not given or not secrets.compare_digest(given, write_token):
            raise HTTPException(401, "invalid or missing bearer token")

    # Sandboxed boards run in an opaque origin, so their fetch()/EventSource
    # calls are cross-origin and need CORS approval — granted for READS only.
    # Writes stay unapproved here and are additionally 403'd on Origin: null.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    def with_liveness(c: dict) -> dict:
        """Enrich an open run's card with heartbeat state (live vs stale)."""
        if c.get("type") == "run" and c.get("status") == "open":
            hb = party.store.heartbeat_at(c["id"])
            c["heartbeat_at"] = hb.isoformat() if hb else None
            age = (utcnow() - hb).total_seconds() if hb else None
            c["alive"] = age is not None and age < ALIVE_WINDOW_SECONDS
        return c

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True, "store": str(party.store.root)}

    # --------------------------------------------------------------------- auth

    @app.get("/api/auth/me")
    def auth_me(request: Request) -> dict:
        """UI bootstrap: is auth on, and who am I? Open by design."""
        user = current_user(request)
        return {"auth_enabled": auth.enabled,
                "user": {"username": user["username"], "role": user["role"]}
                if user else None}

    @app.post("/api/auth/login")
    def auth_login(body: LoginBody, response: Response, request: Request) -> dict:
        if not auth.enabled:
            raise HTTPException(400, "auth is not enabled on this store (no users)")
        client = request.client.host if request.client else "?"
        key = f"{body.username.strip().lower()}|{client}"
        now = time.monotonic()
        fails, locked_until = login_guard.get(key, (0, 0.0))
        if now < locked_until:
            raise HTTPException(429, "too many failed attempts — try again later",
                                headers={"Retry-After": str(int(locked_until - now) + 1)})
        user = auth.authenticate_password(body.username, body.password)
        if user is None:
            fails += 1
            lock = (LOGIN_LOCK_SECONDS * 2 ** (fails - LOGIN_MAX_FAILS)
                    if fails >= LOGIN_MAX_FAILS else 0.0)
            if len(login_guard) > 5000:  # bound memory under spray attempts
                for k in [k for k, (_, u) in login_guard.items() if u < now]:
                    login_guard.pop(k, None)
            login_guard[key] = (fails, now + min(lock, 3600.0))
            raise HTTPException(401, "invalid username or password")
        login_guard.pop(key, None)
        response.set_cookie(
            SESSION_COOKIE, auth.issue_session(user),
            httponly=True, samesite="lax", path="/")
        return {"user": {"username": user["username"], "role": user["role"]}}

    @app.post("/api/auth/logout")
    def auth_logout(response: Response) -> dict:
        response.delete_cookie(SESSION_COOKIE, path="/")
        return {"ok": True}

    @app.get("/api/auth/board-token")
    def auth_board_token(request: Request) -> dict:
        """Short-lived read-only token for sandboxed boards (opaque origins
        carry no cookies). Only real users may mint one — a board cannot use
        its own token to renew itself indefinitely."""
        if not auth.enabled:
            return {"token": None}
        require_role(request, "viewer")
        return {"token": auth.issue_read_token()}

    @app.get("/api/nodes")
    def nodes(type: str | None = None, experiment_id: str | None = None,
              status: str | None = None, tag: str | None = None,
              limit: int = 200) -> list[dict]:
        return [with_liveness(card(n)) for n in party.store.list_nodes(
            type=type, experiment_id=experiment_id, status=status, tag=tag, limit=limit)]

    @app.get("/api/graph")
    def graph(experiment_id: str | None = None, limit: int = 1000) -> dict:
        """Nodes + edges in one payload — feeds the lineage DAG view."""
        nodes = party.store.list_nodes(experiment_id=experiment_id, limit=limit)
        if experiment_id:
            # include the experiment node itself for context
            try:
                nodes.append(party.store.get_node(experiment_id))
            except NodeNotFound:
                pass
        ids = {n.id for n in nodes}
        edges = [e for e in party.store.index.all_edges()
                 if e["src"] in ids or e["dst"] in ids]
        return {"nodes": [card(n) for n in nodes], "edges": edges}

    @app.get("/api/experiments/summary")
    def experiments_summary() -> list[dict]:
        """Experiment cards enriched with run aggregates — feeds the landing page."""
        out = []
        for e in party.store.list_nodes(type="experiment", limit=1000):
            runs = party.store.index.list_nodes(type="run", experiment_id=e.id, limit=10_000)
            statuses: dict[str, int] = {}
            for r in runs:
                statuses[r.get("status", "?")] = statuses.get(r.get("status", "?"), 0) + 1
            last = runs[0] if runs else None  # list_nodes orders created_at DESC
            out.append(card(e) | {
                "n_runs": len(runs),
                "statuses": statuses,
                "last_run": {"id": last["id"], "title": last["title"],
                             "created_at": last["created_at"]} if last else None,
            })
        out.sort(key=lambda x: (x["last_run"] or {}).get("created_at") or x["created_at"],
                 reverse=True)
        return out

    @app.get("/api/runs/{run_id}/code/tree")
    def code_tree(run_id: str) -> dict:
        try:
            node = party.store.get_node(run_id)
        except NodeNotFound:
            raise HTTPException(404) from None
        code_ref = getattr(node, "code_ref", None)
        if code_ref is None:
            return {"files": [], "commit": None, "note": "no code snapshot on this run"}
        exp_id = getattr(node, "experiment_id", "")
        return {"files": party.git.list_tree(exp_id, code_ref.commit_sha),
                "commit": code_ref.commit_sha, "tree": code_ref.tree_sha}

    @app.get("/api/runs/{run_id}/code/file")
    def code_file(run_id: str, path: str, max_bytes: int = 200_000) -> dict:
        try:
            node = party.store.get_node(run_id)
        except NodeNotFound:
            raise HTTPException(404) from None
        code_ref = getattr(node, "code_ref", None)
        if code_ref is None:
            raise HTTPException(404, "no code snapshot on this run")
        data = party.git.read_file(getattr(node, "experiment_id", ""),
                                   code_ref.commit_sha, path)
        if data is None:
            raise HTTPException(404, f"no file {path!r} in the snapshot")
        return {"path": path, "size": len(data), "truncated": len(data) > max_bytes,
                "content": data[:max_bytes].decode("utf-8", errors="replace")}

    @app.get("/api/nodes/{ref}")
    def node(ref: str, metrics: bool = False) -> dict:
        try:
            out = party.node_get(ref, include_metrics=metrics)
        except NodeNotFound:
            raise HTTPException(404, f"no node {ref!r}") from None
        out["node"] = with_liveness(out["node"])
        return out

    @app.post("/api/nodes/{ref}/annotate")
    def annotate(ref: str, body: AnnotateBody, request: Request) -> dict:
        """The viewer's single write operation: append-only annotations
        (observations, by-ear verdicts, corrections) — never edits."""
        if request.headers.get("origin") == "null":
            raise HTTPException(403, "writes are not allowed from sandboxed boards")
        created_by = body.created_by
        if auth.enabled:
            # authenticated created_by: the session user is the author
            created_by = require_role(request, "writer")["username"]
        if not body.text.strip():
            raise HTTPException(422, "empty annotation")
        try:
            return party.node_annotate(ref, body.text.strip(), created_by=created_by)
        except NodeNotFound:
            raise HTTPException(404, f"no node {ref!r}") from None

    @app.get("/api/artifacts/{sha256}")
    def artifact(sha256: str, name: str | None = None, media_type: str | None = None,
                 inline: bool = False) -> FileResponse:
        path = party.store.artifact_path(sha256)
        if not path.exists():
            raise HTTPException(404, "artifact not in the store")
        mt = media_type or "application/octet-stream"
        # inline serving is safelisted: never render markup (html/svg-as-doc/…)
        # on this origin — that would hand a logged artifact the UI's origin.
        # Boards render HTML through the sandboxed /boards/<sha> route instead.
        safe = mt.startswith(INLINE_SAFE_PREFIXES) or mt in INLINE_SAFE_EXACT
        if inline and not safe:
            inline = False
            mt = "application/octet-stream"
        headers = ({"Content-Security-Policy": "sandbox",
                    "X-Content-Type-Options": "nosniff"} if inline else None)
        return FileResponse(
            path, filename=name or sha256, media_type=mt,
            content_disposition_type="inline" if inline else "attachment",
            headers=headers)

    @app.get("/boards/{sha256}")
    def board(sha256: str) -> FileResponse:
        """Serve an HTML artifact as a sandboxed board: opaque origin (CSP
        sandbox), inline resources only, network access limited to this
        host's read-only API. Boards are data, never trusted UI."""
        path = party.store.artifact_path(sha256)
        if not path.exists():
            raise HTTPException(404, "board not in the store")
        return FileResponse(
            path, media_type="text/html", content_disposition_type="inline",
            headers={"Content-Security-Policy": BOARD_CSP,
                     "X-Content-Type-Options": "nosniff"})

    @app.get("/api/actions")
    def actions_list() -> list[dict]:
        return party.action_list()

    @app.post("/api/actions/invoke")
    def actions_invoke(body: InvokeBody, request: Request) -> dict:
        """Run control is write-class: executes on the server host, so it
        needs a writer (auth mode) / the ingest token (legacy) — and never
        a sandboxed board."""
        if request.headers.get("origin") == "null":
            raise HTTPException(403, "run control is not allowed from sandboxed boards")
        require_ingest(request)
        created_by = body.created_by
        if auth.enabled:
            created_by = current_user(request)["username"]
        try:
            return party.action_invoke(body.name, body.params, created_by=created_by)
        except ContractViolation as e:
            raise HTTPException(422, e.to_dict()) from None
        except NodeNotFound as e:
            raise HTTPException(404, str(e)) from None

    @app.get("/api/boards")
    def boards(experiment_id: str | None = None) -> list[dict]:
        """Board gallery: text/html artifacts across the store (or one
        experiment's own + its runs'), with best-effort titles."""
        try:
            return party.board_list(experiment_id)
        except NodeNotFound:
            raise HTTPException(404, f"no experiment {experiment_id!r}") from None

    @app.get("/boards-lib/mlparty.js")
    def boards_lib() -> FileResponse:
        """The optional board JS helper — same-host, so `<script src>` passes
        the board CSP ('self'); never a CDN."""
        return FileResponse(BOARDS_LIB, media_type="text/javascript",
                            headers={"Cache-Control": "no-cache"})

    @app.get("/api/artifacts/{sha256}/tensor")
    def tensor_meta(sha256: str, member: str | None = None) -> dict:
        path = party.store.artifact_path(sha256)
        if not path.exists():
            raise HTTPException(404, "artifact not in the store")
        try:
            return npyview.tensor_meta(path, member)
        except npyview.NpyError as e:
            raise HTTPException(422, str(e)) from None

    @app.get("/api/artifacts/{sha256}/tensor/range")
    def tensor_full_range(sha256: str, member: str | None = None) -> dict:
        path = party.store.artifact_path(sha256)
        if not path.exists():
            raise HTTPException(404, "artifact not in the store")
        try:
            return npyview.tensor_full_range(path, member)
        except npyview.NpyError as e:
            raise HTTPException(422, str(e)) from None

    @app.get("/api/artifacts/{sha256}/tensor/slice")
    def tensor_slice(sha256: str, prefix: str = "", member: str | None = None) -> dict:
        path = party.store.artifact_path(sha256)
        if not path.exists():
            raise HTTPException(404, "artifact not in the store")
        try:
            idx = [int(p) for p in prefix.split(",") if p.strip() != ""]
        except ValueError:
            raise HTTPException(422, "prefix must be comma-separated integers") from None
        try:
            return npyview.tensor_slice(path, idx, member)
        except npyview.NpyError as e:
            raise HTTPException(422, str(e)) from None

    # ------------------------------------------------------------- sync ingest
    # Three idempotent streams (DESIGN.md §9): ULID-keyed journal events,
    # content-addressed git objects / artifacts, offset-addressed metrics.

    @app.post("/api/ingest/events")
    def ingest_events(body: EventsBody, request: Request) -> dict:
        require_ingest(request)
        try:
            return party.store.ingest_events(body.events)
        except StoreError as e:
            raise HTTPException(422, str(e)) from None

    @app.post("/api/ingest/metrics/{run_id}")
    def ingest_metrics(run_id: str, body: MetricsChunkBody, request: Request) -> dict:
        require_ingest(request)
        out = party.store.append_metrics_chunk(run_id, body.expected_offset, body.chunk)
        if not out["ok"]:
            raise HTTPException(409, detail=out)
        return out

    @app.post("/api/ingest/heartbeat/{run_id}")
    def ingest_heartbeat(run_id: str, request: Request) -> dict:
        require_ingest(request)
        party.store.touch_heartbeat(run_id)
        return {"ok": True}

    @app.put("/api/ingest/artifacts/{sha256}")
    async def ingest_artifact(sha256: str, request: Request) -> dict:
        require_ingest(request)
        if party.store.artifact_path(sha256).exists():
            return {"ok": True, "deduped": True}
        data = await request.body()
        ref = party.store.put_artifact_bytes(data, original_path=f"sync:{sha256}")
        if ref.sha256 != sha256:
            party.store.artifact_path(ref.sha256).unlink(missing_ok=True)
            raise HTTPException(422, f"content hashes to {ref.sha256}, not {sha256}")
        return {"ok": True, "deduped": False}

    @app.post("/api/ingest/git/{experiment_id}/missing")
    def git_missing(experiment_id: str, body: MissingBody, request: Request) -> dict:
        require_ingest(request)
        return {"missing": party.git.missing_objects(experiment_id, body.shas)}

    @app.post("/api/ingest/git/{experiment_id}")
    def git_ingest(experiment_id: str, body: GitObjectsBody, request: Request) -> dict:
        require_ingest(request)
        try:
            imported = party.git.import_objects(experiment_id, body.objects)
        except (ValueError, KeyError) as e:
            raise HTTPException(422, f"bad git object: {e}") from None
        for refname, sha in body.refs.items():
            if not refname.startswith("refs/runs/"):
                raise HTTPException(422, "only refs/runs/* may be pushed")
            party.git.set_run_ref(experiment_id, refname.removeprefix("refs/runs/"), sha)
        return {"imported": imported, "refs": len(body.refs)}

    @app.get("/api/query")
    def query(q: str, mode: str = "hybrid", type: str | None = None,
              limit: int = 10) -> dict:
        return party.graph_query(q, mode=mode, type=type, limit=limit)

    @app.get("/api/diff")
    def diff(a: str, b: str) -> dict:
        try:
            return party.run_diff(a, b)
        except NodeNotFound:
            raise HTTPException(404, "run not found") from None

    @app.get("/api/runs/{run_id}/metrics")
    def metrics(run_id: str, offset: int = 0, name: str | None = None) -> dict:
        records, new_offset = party.store.read_metrics(run_id, offset, name)
        return {"records": records, "offset": new_offset}

    @app.get("/api/runs/{run_id}/metrics/stream")
    async def stream(run_id: str, poll_seconds: float = 1.0) -> StreamingResponse:
        """SSE live tail of a run's metric journal; ends when the run leaves 'open'."""
        async def gen():
            offset = 0
            while True:
                records, offset = party.store.read_metrics(run_id, offset)
                for r in records:
                    yield f"data: {json.dumps(r)}\n\n"
                try:
                    status = party.store.get_node(run_id).status
                except NodeNotFound:
                    break
                if status != "open" and not records:
                    yield f"event: end\ndata: {json.dumps({'status': status})}\n\n"
                    break
                await asyncio.sleep(poll_seconds)

        return StreamingResponse(gen(), media_type="text/event-stream")

    if UI_DIST.exists():
        app.mount("/", StaticFiles(directory=UI_DIST, html=True), name="ui")
    return app
