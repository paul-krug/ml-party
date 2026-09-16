import asyncio
import json

from typer.testing import CliRunner

from mlparty.cli import app
from mlparty.core import MlParty
from mlparty.mcp_server import (
    CLIENT_TRUNCATION_CAP,
    INSTRUCTIONS,
    INSTRUCTIONS_BUDGET,
    build_server,
)

runner = CliRunner()


def _tool_data(result) -> dict:
    """Unwrap a call_tool result down to the tool's own `data` payload."""
    payload = getattr(result, "structured_content", None) \
        or json.loads(result.content[0].text)
    assert payload["ok"], payload
    return payload["data"]


def test_init_registers_mcp(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    r = runner.invoke(app, ["init", "--root", str(tmp_path / ".mlparty")])
    assert r.exit_code == 0, r.output
    cfg = json.loads((tmp_path / ".mcp.json").read_text())
    entry = cfg["mcpServers"]["ml-party"]
    assert entry["args"][0] == "serve-mcp"
    assert entry["args"][2] == str(tmp_path / ".mlparty")


def test_init_no_mcp_flag(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    r = runner.invoke(app, ["init", "--root", str(tmp_path / ".mlparty"), "--no-mcp"])
    assert r.exit_code == 0
    assert not (tmp_path / ".mcp.json").exists()


def test_connect_merges_existing_servers(tmp_path):
    MlParty.init(tmp_path / "store")
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / ".mcp.json").write_text(json.dumps(
        {"mcpServers": {"other-server": {"command": "x", "args": []}}}))
    r = runner.invoke(app, ["connect", "--root", str(tmp_path / "store"),
                            "--project", str(proj)])
    assert r.exit_code == 0, r.output
    cfg = json.loads((proj / ".mcp.json").read_text())
    assert "other-server" in cfg["mcpServers"]          # merged, not clobbered
    assert "ml-party" in cfg["mcpServers"]


def test_mcp_config_prints_snippet(tmp_path):
    """stdout stays pure JSON so `mlp mcp-config | jq …` keeps working; the
    where-to-paste guidance goes to stderr."""
    r = runner.invoke(app, ["mcp-config", "--root", str(tmp_path / "s")])
    snippet = json.loads(r.stdout)
    assert snippet["mcpServers"]["ml-party"]["args"][0] == "serve-mcp"
    assert "MCP configuration" in r.stderr


def test_connection_instructions_fit_the_truncation_budget():
    """Clients cap `instructions` (Claude Code at exactly 2048 chars, mid-word and
    silently), so the connection text is a router, not the manual. If it regrows
    past the budget the teaching is delivered in pieces and nothing says so —
    which is precisely how this shipped broken once."""
    assert len(INSTRUCTIONS) < INSTRUCTIONS_BUDGET, (
        f"instructions are {len(INSTRUCTIONS)} chars; move detail into WORKFLOW "
        f"(served by workflow_guide) and keep this under {INSTRUCTIONS_BUDGET}")
    # a truncated router is still useless, so the pointer must come early
    assert "workflow_guide()" in INSTRUCTIONS[:600]
    # the rails that prevent harm survive even if only the router arrives
    for needle in ("never instructions to follow", "confirm_snapshot=True",
                   "ML_PARTY_RUN", "run_finalize"):
        assert needle in INSTRUCTIONS, needle


def test_tool_descriptions_fit_the_truncation_budget(tmp_path):
    """The same cap applies per TOOL description, and truncation is just as silent
    there — a docstring that outgrows it loses its tail (for run_start, that tail
    is the source_root / confirm_snapshot protocol)."""
    MlParty.init(tmp_path / ".mlparty")
    tools = asyncio.run(build_server(tmp_path / ".mlparty").list_tools())
    oversized = {t.name: len(t.description or "") for t in tools
                 if len(t.description or "") >= CLIENT_TRUNCATION_CAP}
    assert not oversized, (
        f"tool descriptions truncated by clients at {CLIENT_TRUNCATION_CAP} chars: "
        f"{oversized} — move the detail into WORKFLOW")


def test_server_is_self_teaching(tmp_path):
    MlParty.init(tmp_path / ".mlparty")
    server = build_server(tmp_path / ".mlparty")
    assert server.instructions == INSTRUCTIONS

    # the full manual is reachable as a TOOL — the only channel an agent can pull
    # on its own initiative (prompts are user-invoked, instructions are truncated)
    names = [t.name for t in asyncio.run(server.list_tools())]
    assert "workflow_guide" in names
    guide = asyncio.run(server.call_tool("workflow_guide", {}))
    data = _tool_data(guide)
    for needle in ("run_start", "ML_PARTY_RUN", "mlparty.attach()", "run_finalize",
                   "verdict", "graph_query", "run_fail", "confirm_snapshot=True"):
        assert needle in data["workflow"], needle
    # ...and it orients the agent to the store it is actually serving
    assert data["store_root"] == str((tmp_path / ".mlparty").resolve())
    assert data["counts"]["run"] == 0
    assert "empty" in data["orientation"]

    # and as an invokable prompt
    prompts = asyncio.run(server.list_prompts())
    assert [p.name for p in prompts] == ["track_training"]
    msg = asyncio.run(server.get_prompt("track_training", {"description": "tube run"}))
    text = str(msg)
    assert "tube run" in text and "run_start" in text
