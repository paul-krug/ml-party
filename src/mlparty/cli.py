"""`mlp` CLI: the human mirror of the core API, plus store service commands."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import typer

from .core import MlParty, card
from .store import Store


def _mlp_bin() -> str:
    candidate = Path(sys.executable).with_name("mlp")
    return str(candidate) if candidate.exists() else "mlp"


def _mcp_server_entry(store_root: Path) -> dict:
    return {
        "command": _mlp_bin(),
        "args": ["serve-mcp", "--root", str(store_root.resolve())],
    }


def _mcp_next_steps(project_dir: Path) -> str:
    """Registration only takes effect for an agent started in this directory,
    after a one-time approval — so say both, and say how to check."""
    return (
        f"\nNEXT: start your agent from this directory — it only reads .mcp.json\n"
        f"  from the directory it is started in:\n"
        f"      cd {project_dir} && claude\n"
        f"  Approve 'ml-party' when prompted, then verify with /mcp.\n"
        f"  Not listed? `claude mcp list` shows what was loaded; `mlp mcp-config`\n"
        f"  prints the snippet for other MCP clients."
    )


def _register_mcp(project_dir: Path, store_root: Path) -> Path:
    """Write/merge the ml-party server into the project's .mcp.json — the
    zero-terminal registration path Claude Code (and compatible agents) read."""
    cfg_path = project_dir / ".mcp.json"
    data: dict = {}
    if cfg_path.exists():
        try:
            data = json.loads(cfg_path.read_text() or "{}")
        except json.JSONDecodeError as e:
            raise typer.BadParameter(f"{cfg_path} exists but is not valid JSON: {e}") from e
    data.setdefault("mcpServers", {})["ml-party"] = _mcp_server_entry(store_root)
    cfg_path.write_text(json.dumps(data, indent=2) + "\n")
    return cfg_path

app = typer.Typer(help="ml-party — agent-native experiment tracking",
                  no_args_is_help=True, pretty_exceptions_enable=False)

RootOpt = typer.Option(None, "--root", "-r", help="store root (default: $ML_PARTY_STORE or ./.mlparty)")


def _root(root: str | None) -> Path:
    return Path(root or os.environ.get("ML_PARTY_STORE") or ".mlparty")


def _party(root: str | None) -> MlParty:
    return MlParty.open(_root(root))


def _echo_json(data) -> None:
    typer.echo(json.dumps(data, indent=2, default=str))


@app.command()
def init(root: str | None = RootOpt,
         no_mcp: bool = typer.Option(False, "--no-mcp",
                                     help="skip MCP registration in ./.mcp.json")):
    """Create a new store AND register the MCP server for agents in this project."""
    store = Store.init(_root(root))
    typer.echo(f"initialized ml-party store at {store.root}")
    if not no_mcp:
        cfg = _register_mcp(Path.cwd(), store.root)
        typer.echo(f"registered the MCP server in {cfg}")
        typer.echo(_mcp_next_steps(cfg.parent))


@app.command()
def connect(root: str | None = RootOpt,
            project: str = typer.Option(".", "--project",
                                        help="project directory whose agents should see the store")):
    """Register an EXISTING store's MCP server in a project's .mcp.json."""
    store = Store(_root(root))  # validates the store exists
    cfg = _register_mcp(Path(project).resolve(), store.root)
    typer.echo(f"registered MCP server for store {store.root} in {cfg}")
    typer.echo(_mcp_next_steps(cfg.parent))


@app.command("mcp-config")
def mcp_config(root: str | None = RootOpt):
    """Print the MCP server config snippet for manual registration in any client."""
    # JSON on stdout so it stays pipeable; guidance on stderr.
    typer.echo(json.dumps({"mcpServers": {"ml-party": _mcp_server_entry(_root(root))}},
                          indent=2))
    typer.echo(
        "\nPaste this entry into your agent's MCP configuration — e.g. Claude Code's\n"
        ".mcp.json (project) or `claude mcp add -s user`, Cursor's .cursor/mcp.json.\n"
        "Some clients use a different top-level key; check your client's docs.\n"
        "Registering it globally rather than per-project makes ml-party available in\n"
        "every session. Restart the session afterwards for it to connect.",
        err=True)


@app.command("snapshot-preview")
def snapshot_preview(source_root: str = typer.Argument(..., help="directory a run would snapshot"),
                     experiment: str | None = typer.Option(None, "--experiment", "-e",
                                                           help="also diff against this "
                                                                "experiment's last snapshot"),
                     root: str | None = RootOpt):
    """Show exactly what a run would capture from a directory — before it does."""
    out = _party(root).snapshot_preview(source_root, experiment=experiment)
    typer.echo(f"{out['included_files']} file(s), {out['included_bytes']} bytes "
               f"from {out['source_root']} (mode: {out['source_mode']})")
    for f in out["files"]:
        typer.echo(f"  {f}")
    if out["files_truncated"]:
        typer.echo("  … list truncated")
    if out["needs_confirmation"]:
        typer.echo(f"needs confirmation: {out['needs_confirmation']}")
    delta = out.get("delta")
    if delta and delta.get("compared_to"):
        if delta["unchanged"]:
            typer.echo(f"identical to {delta['compared_to']['id']} — nothing new would be stored")
        else:
            typer.echo(f"vs {delta['compared_to']['id']}: +{delta['added_count']} "
                       f"~{delta['modified_count']} -{delta['removed_count']}")


@app.command()
def status(root: str | None = RootOpt):
    """Store overview: node counts, open runs."""
    party = _party(root)
    for t in ("project", "experiment", "run", "note"):
        n = len(party.store.list_nodes(type=t, limit=10_000))
        typer.echo(f"{t:12s} {n}")
    open_runs = party.store.list_nodes(type="run", status="open", limit=100)
    for r in open_runs:
        typer.echo(f"open run: {r.id}  {r.title}")


@app.command()
def runs(experiment: str | None = typer.Argument(None), status: str | None = None,
         root: str | None = RootOpt):
    """List runs (optionally for one experiment / status)."""
    party = _party(root)
    exp_id = party._resolve(experiment, "experiment").id if experiment else None
    for n in party.store.list_nodes(type="run", experiment_id=exp_id, status=status):
        c = card(n)
        typer.echo(f"{n.id}  [{c['status']:9s}] {c.get('verdict') or '-':12s} {n.title}")


@app.command()
def show(ref: str, metrics: bool = False, root: str | None = RootOpt):
    """Show one node (by id or title) with edges."""
    _echo_json(_party(root).node_get(ref, include_metrics=metrics))


@app.command()
def tail(run: str, interval: float = 1.0, root: str | None = RootOpt):
    """Live-stream a run's metrics (the proto-live-view)."""
    party = _party(root)
    node = party._resolve(run, "run")
    offset = 0
    while True:
        records, offset = party.store.read_metrics(node.id, offset)
        for r in records:
            typer.echo(json.dumps(r))
        status_now = party.store.get_node(node.id).status
        if status_now != "open" and not records:
            typer.echo(f"# run {node.id} is {status_now}")
            break
        time.sleep(interval)


@app.command()
def query(q: str, mode: str = "hybrid", type: str | None = None, limit: int = 10,
          root: str | None = RootOpt):
    """Search the knowledge graph."""
    out = _party(root).graph_query(q, mode=mode, type=type, limit=limit)
    for hit in out["results"]:
        typer.echo(f"{hit['score']:6.3f}  {hit['id']}  [{hit['type']}] {hit['title']}")
        if hit.get("one_liner"):
            typer.echo(f"        {hit['one_liner']}")
        if hit.get("why"):
            typer.echo(f"        via: {hit['why']}")


@app.command()
def diff(run_a: str, run_b: str, root: str | None = RootOpt):
    """Diff two runs: code, params, metrics, env."""
    _echo_json(_party(root).run_diff(run_a, run_b))


@app.command()
def sync(root: str | None = RootOpt,
         to: str | None = typer.Option(None, "--to", help="server URL (default: store.toml [sync].url)"),
         token: str | None = typer.Option(None, "--token", envvar="ML_PARTY_TOKEN")):
    """Flush this (spool) store to a remote `mlp serve` instance — journal
    events, git snapshots, artifacts, metrics. Idempotent; run it any time."""
    from . import sync as sync_mod
    party = _party(root)
    client = sync_mod.from_store(party.store, url=to, token=token)
    if client is None:
        raise typer.BadParameter("no server: pass --to or set [sync] url in store.toml")
    try:
        out = client.flush()
    finally:
        client.close()
    typer.echo(json.dumps(out))


@app.command()
def backup(dest: str, root: str | None = RootOpt):
    """Copy the store's durable state to DEST (safe while runs are live).
    Restore: point --root at the copy and run `mlp rebuild-index`."""
    out = _party(root).store.backup(dest)
    typer.echo(json.dumps(out))


@app.command("rebuild-index")
def rebuild_index(root: str | None = RootOpt):
    """Rebuild the SQLite index from the journal (source of truth)."""
    n = _party(root).store.rebuild_index()
    typer.echo(f"replayed {n} journal events")


@app.command()
def janitor(ttl_hours: int | None = None, root: str | None = RootOpt):
    """Mark silent open runs as abandoned."""
    marked = _party(root).janitor(ttl_hours)
    typer.echo(f"abandoned: {marked or 'none'}")


@app.command("serve-mcp")
def serve_mcp(root: str | None = RootOpt):
    """Run the MCP server on stdio (register this in your agent's MCP config)."""
    from .mcp_server import build_server
    build_server(_root(root)).run(transport="stdio")


@app.command()
def demo(root: str | None = RootOpt, steps: int = 120, sleep: float = 0.25):
    """Run the live demo — a real tracked run (pre-registration, streaming metrics,
    finalize with a verdict) in about 30 seconds. Watch it with `mlp ui`."""
    from .demo import run_demo

    store = _root(root)
    typer.echo(f"demo run -> store {Path(store).resolve()}", err=True)
    typer.echo(run_demo(str(store), steps=steps, sleep=sleep))


@app.command()
def ui(root: str | None = RootOpt, host: str = "127.0.0.1", port: int = 7327):
    """Serve the read-only HTTP API + web viewer (tunnel via ssh -L for remote)."""
    import uvicorn

    from .http_api import UI_DIST, build_app
    if not UI_DIST.exists():
        typer.echo("note: web UI bundle not found — serving the API only. "
                   "Build it once: cd ui && npm install && npm run build", err=True)
    uvicorn.run(build_app(_root(root)), host=host, port=port)


@app.command()
def serve(root: str | None = RootOpt, host: str = "127.0.0.1", port: int = 7327,
          token: str | None = typer.Option(
              None, "--token", envvar="ML_PARTY_TOKEN",
              help="legacy single bearer token enabling /api/ingest/* "
                   "(ignored once users exist — see `mlp user add`)"),
          generate_token: bool = typer.Option(
              False, "--generate-token",
              help="generate a legacy token, store it at <root>/server_token, print it")):
    """Serve the full store server: viewer + read API + authenticated sync
    ingest. With users configured (`mlp user add`), logins and per-user
    tokens gate everything; otherwise the legacy single token gates ingest.
    Expose beyond localhost only behind TLS (see docs)."""
    import secrets as _secrets

    import uvicorn

    from .auth import AuthStore
    from .http_api import build_app
    store_root = _root(root)
    auth = AuthStore(store_root)
    if auth.enabled:
        if token or generate_token:
            typer.echo("note: users exist — per-user auth is active and "
                       "--token/--generate-token are ignored", err=True)
        token = None
    else:
        if generate_token:
            token = _secrets.token_urlsafe(32)
            token_path = store_root / "server_token"
            token_path.write_text(token + "\n")
            token_path.chmod(0o600)
            typer.echo(f"token written to {token_path}:\n{token}")
        if not token:
            raise typer.BadParameter(
                "no auth configured: create users (mlp user add) or pass "
                "--token / ML_PARTY_TOKEN / --generate-token")
    uvicorn.run(build_app(store_root, write_token=token), host=host, port=port)


user_app = typer.Typer(help="Manage server users (auth activates once the "
                            "first user exists)", no_args_is_help=True)
token_app = typer.Typer(help="Manage per-user API tokens", no_args_is_help=True)
app.add_typer(user_app, name="user")
app.add_typer(token_app, name="token")


def _auth(root: str | None):
    from .auth import AuthStore
    return AuthStore(_root(root))


def _auth_guard(fn, *args, **kwargs):
    from .auth import AuthError
    try:
        return fn(*args, **kwargs)
    except AuthError as e:
        raise typer.BadParameter(str(e)) from None


@user_app.command("add")
def user_add(username: str,
             role: str = typer.Option("writer", help="viewer | writer | admin"),
             email: str | None = typer.Option(None),
             password: str | None = typer.Option(
                 None, help="omit to be prompted; '-' reads stdin"),
             root: str | None = RootOpt):
    """Create a user. The FIRST user must be an admin and switches the served
    store to authenticated mode (login required, legacy token ignored)."""
    if password == "-":
        password = sys.stdin.readline().rstrip("\n")
    if not password:
        password = typer.prompt("password", hide_input=True, confirmation_prompt=True)
    if len(password) < 8:
        raise typer.BadParameter("password needs at least 8 characters")
    out = _auth_guard(_auth(root).user_add, username, password, role=role, email=email)
    _echo_json(out)


@user_app.command("list")
def user_list(root: str | None = RootOpt):
    _echo_json(_auth(root).user_list())


@user_app.command("remove")
def user_remove(username: str, root: str | None = RootOpt):
    _auth_guard(_auth(root).user_remove, username)
    typer.echo(f"removed {username}")


@user_app.command("set-role")
def user_set_role(username: str, role: str, root: str | None = RootOpt):
    _echo_json(_auth_guard(_auth(root).user_set_role, username, role))


@user_app.command("set-password")
def user_set_password(username: str,
                      password: str | None = typer.Option(
                          None, help="omit to be prompted; '-' reads stdin"),
                      root: str | None = RootOpt):
    """Reset a password (also invalidates the user's existing sessions)."""
    if password == "-":
        password = sys.stdin.readline().rstrip("\n")
    if not password:
        password = typer.prompt("password", hide_input=True, confirmation_prompt=True)
    if len(password) < 8:
        raise typer.BadParameter("password needs at least 8 characters")
    _auth_guard(_auth(root).user_set_password, username, password)
    typer.echo(f"password set for {username}")


@token_app.command("create")
def token_create(user: str = typer.Option(..., help="username or user id"),
                 name: str = typer.Option(..., help="what this token is for, "
                                          "e.g. 'laptop-sync'"),
                 root: str | None = RootOpt):
    """Mint a per-user API token (printed ONCE — only its hash is stored).
    Use it as the [sync] token in spool stores and for programmatic access."""
    out = _auth_guard(_auth(root).token_create, user, name)
    typer.echo(out["token"])
    typer.echo(f"(token id {out['id']} for {out['user']} — shown once, store it now)",
               err=True)


@token_app.command("list")
def token_list(root: str | None = RootOpt):
    users = _auth(root).user_list()
    _echo_json([{"user": u["username"], **t} for u in users for t in u["tokens"]])


@token_app.command("revoke")
def token_revoke(token_id: str, root: str | None = RootOpt):
    _auth_guard(_auth(root).token_revoke, token_id)
    typer.echo(f"revoked {token_id}")


action_app = typer.Typer(help="Run-control action templates: registered "
                              "shell with typed placeholders — the allowlist "
                              "agents invoke through", no_args_is_help=True)
app.add_typer(action_app, name="action")


@action_app.command("register")
def action_register(file: str = typer.Option(
                        ..., "--file", "-f",
                        help="JSON template file ('-' reads stdin): {name, "
                             "description, command, params?, env?, cwd?}"),
                    root: str | None = RootOpt):
    """Register an action template. Example template:

    {"name": "start-train", "description": "launch a tube training run",
     "command": "nohup python train.py --lr {lr} >/dev/null 2>&1 &",
     "cwd": "/home/me/proj",
     "env": {"ML_PARTY_RUN": "{run}", "ML_PARTY_STORE": "{store_root}"},
     "params": {"lr": {"type": "float"}, "run": {"type": "str"}}}
    """
    raw = sys.stdin.read() if file == "-" else Path(file).read_text()
    try:
        template = json.loads(raw)
    except json.JSONDecodeError as e:
        raise typer.BadParameter(f"not valid JSON: {e}") from None
    from .contract import ContractViolation
    try:
        _echo_json(_party(root).action_register(template, created_by="human"))
    except ContractViolation as e:
        raise typer.BadParameter(str(e)) from None


@action_app.command("list")
def action_list(root: str | None = RootOpt):
    _echo_json(_party(root).action_list())


@action_app.command("remove")
def action_remove(name: str, root: str | None = RootOpt):
    from .contract import ContractViolation
    try:
        _party(root).action_remove(name)
    except ContractViolation as e:
        raise typer.BadParameter(str(e)) from None
    typer.echo(f"removed {name}")


ParamOpt = typer.Option([], "--param", "-p", help="name=value (repeatable)")


@action_app.command("invoke")
def action_invoke(name: str,
                  param: list[str] = ParamOpt,
                  root: str | None = RootOpt):
    """Invoke a registered action; prints the invocation node id (watch it
    with `mlp show <id>`)."""
    params: dict = {}
    for p in param:
        if "=" not in p:
            raise typer.BadParameter(f"--param needs name=value, got {p!r}")
        k, v = p.split("=", 1)
        params[k] = v
    from .contract import ContractViolation
    try:
        _echo_json(_party(root).action_invoke(name, params, created_by="human"))
    except ContractViolation as e:
        raise typer.BadParameter(str(e)) from None


if __name__ == "__main__":
    app()
