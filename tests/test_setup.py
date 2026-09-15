import asyncio
import json

from typer.testing import CliRunner

from mlparty.cli import app
from mlparty.core import MlParty
from mlparty.mcp_server import WORKFLOW, build_server

runner = CliRunner()


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
    r = runner.invoke(app, ["mcp-config", "--root", str(tmp_path / "s")])
    snippet = json.loads(r.output)
    assert snippet["mcpServers"]["ml-party"]["args"][0] == "serve-mcp"


def test_server_is_self_teaching(tmp_path):
    MlParty.init(tmp_path / ".mlparty")
    server = build_server(tmp_path / ".mlparty")
    # the workflow brief rides in the connection instructions
    for needle in ("run_start", "ML_PARTY_RUN", "mlparty.attach()", "run_finalize",
                   "verdict", "graph_query", "run_fail"):
        assert needle in WORKFLOW, needle
    assert server.instructions == WORKFLOW
    # and as an invokable prompt
    prompts = asyncio.run(server.list_prompts())
    assert [p.name for p in prompts] == ["track_training"]
    msg = asyncio.run(server.get_prompt("track_training", {"description": "tube run"}))
    text = str(msg)
    assert "tube run" in text and "run_start" in text
