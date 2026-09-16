"""The package's docs must ship in the wheel and be reachable over MCP.

An agent that only ever ran `pip install mlparty` has no repo and no website
— the MCP surface is its entire view of the package. Before these existed it
could learn the tracking contract and nothing else: not the demo, not the UI,
not how to instrument a script.
"""
import asyncio
import json

from mlparty import docs
from mlparty.core import MlParty
from mlparty.mcp_server import build_server


def _call(server, name, args=None):
    result = asyncio.run(server.call_tool(name, args or {}))
    return getattr(result, "structured_content", None) \
        or json.loads(result.content[0].text)


def test_docs_ship_inside_the_package():
    """They live under src/mlparty/_docs precisely so package-data carries them;
    back in docs/ they were repo-only and invisible to an installed package."""
    topics = docs.topics()
    assert {"quickstart", "tracking", "mcp", "ui", "boards", "actions",
            "remote", "deploy"} <= set(topics)
    assert next(iter(topics)) == "quickstart"       # reading order for a cold agent
    for name, summary in topics.items():
        assert summary and not summary.startswith("#"), name
        assert docs.read(name).lstrip().startswith("# "), name


def test_unknown_topic_cannot_escape_the_docs_directory():
    assert docs.read("../../../etc/passwd") is None
    assert docs.read("nope") is None


def test_cli_commands_are_introspected_not_transcribed():
    """Generated from the Typer app, so the list cannot drift from what is
    installed — the failure mode a hand-written command table always hits."""
    commands = docs.cli_commands()
    for expected in ("init", "ui", "serve-mcp", "status", "runs", "sync"):
        assert expected in commands, expected
    assert commands["ui"], "each command carries its help text"


def test_help_reports_where_to_file_a_bug(tmp_path):
    """A real agent asked to file an issue found no repo in the package, searched
    the disk, hit a stale clone of a renamed predecessor and reported against it.
    The canonical URL was in the installed metadata all along — state the fact and
    the agent stops guessing."""
    urls = docs.project_urls()
    assert urls["issues"].startswith("https://github.com/")
    assert "homepage" in urls and "documentation" in urls

    MlParty.init(tmp_path / ".mlparty")
    index = _call(build_server(tmp_path / ".mlparty"), "help")["data"]
    assert index["project_urls"]["issues"] == urls["issues"]
    assert "disk" in index["reporting_a_bug"]      # warns off the filesystem guess


def test_help_tool_serves_the_index_and_the_topics(tmp_path):
    MlParty.init(tmp_path / ".mlparty")
    server = build_server(tmp_path / ".mlparty")

    index = _call(server, "help")["data"]
    assert index["version"] and index["version"] != "0.1.0"   # was hardcoded, stale
    assert index["store_root"] == str((tmp_path / ".mlparty").resolve())
    assert "quickstart" in index["topics"] and index["cli_commands"]["ui"]

    page = _call(server, "help", {"topic": "quickstart"})["data"]
    assert "mlparty.demo" in page["text"]        # the thing an agent could not find
    assert "ML_PARTY_STORE" in page["text"]      # ...or that it lands in the wrong store

    missing = _call(server, "help", {"topic": "does-not-exist"})
    assert not missing["ok"] and "quickstart" in missing["topics"]


def test_version_is_derived_from_package_metadata():
    """Hardcoding it meant `mlparty.__version__` reported 0.1.0 from 0.2.0 on."""
    import mlparty
    assert mlparty.__version__ not in ("0.1.0", "")
