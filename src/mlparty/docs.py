"""The package's own documentation, readable by agents.

The markdown under `_docs/` ships in the wheel, so an agent that only ever
did `pip install mlparty` can still read the guides. The docs site renders
these same files through include stubs in `docs/` — one source of truth, no
second copy to drift.
"""
from __future__ import annotations

import re
from importlib import resources

PACKAGE = "mlparty._docs"

# reading order for a cold agent: what to do, then the contract, then surfaces
ORDER = ["quickstart", "tracking", "mcp", "ui", "boards", "actions", "remote", "deploy"]


def _summarize(text: str) -> tuple[str, str]:
    """(title, one-line summary) taken from the document itself."""
    title, summary, body = "", "", text.lstrip()
    if body.startswith("# "):
        title, _, body = body[2:].partition("\n")
    for para in body.split("\n\n"):
        para = " ".join(para.split())
        if para and not para.startswith(("```", "|", "#", "*(")):
            summary = re.split(r"(?<=[.!?]) ", para)[0]
            break
    return title.strip(), summary


def topics() -> dict[str, str]:
    """Available topic -> one-line summary, in reading order."""
    found = {}
    for res in resources.files(PACKAGE).iterdir():
        if res.name.endswith(".md"):
            found[res.name[:-3]] = _summarize(res.read_text(encoding="utf-8"))[1]
    return {name: found[name] for name in ORDER if name in found} | {
        name: summary for name, summary in sorted(found.items()) if name not in ORDER}


def read(topic: str) -> str | None:
    """The full text of one topic, or None if there is no such topic."""
    if topic not in topics():           # never join an unvalidated name onto a path
        return None
    return resources.files(PACKAGE).joinpath(f"{topic}.md").read_text(encoding="utf-8")


def project_urls() -> dict[str, str]:
    """Homepage / Issues / Documentation / Changelog, from package metadata.

    The canonical answer to "where do I report this?". Without it an agent
    infers the repository from directories on disk, and a stale clone of a
    predecessor repo is indistinguishable from the real one.
    """
    from importlib.metadata import PackageNotFoundError, metadata

    try:
        entries = metadata("mlparty").get_all("Project-URL") or []
    except PackageNotFoundError:
        return {}
    out = {}
    for entry in entries:
        label, _, url = entry.partition(",")
        out[label.strip().lower()] = url.strip()
    return out


def cli_commands() -> dict[str, str]:
    """Every `mlp` command with its help text, read off the CLI itself."""
    from .cli import app  # local: cli imports the server, not vice versa

    out = {}
    for cmd in app.registered_commands:
        name = cmd.name or (cmd.callback.__name__.replace("_", "-") if cmd.callback else "")
        help_text = cmd.help or (cmd.callback.__doc__ or "" if cmd.callback else "")
        out[name] = " ".join(help_text.split())
    return dict(sorted(out.items()))
