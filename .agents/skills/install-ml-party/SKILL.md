---
name: install-ml-party
description: >-
  Install ml-party into the user's project and register its MCP server. Use
  when asked to "install ml-party", "set up ml-party", or to connect ml-party
  to this project. Covers the install, creating the store in the directory
  where the agent will actually find it, and the restart step — a newly
  registered MCP server cannot load into the session that registered it, so
  the user must be told.
---

# Install ml-party and register its MCP server

Goal: after this, the user restarts their session and their agent has the
ml-party tools. Two things make this fail in practice, and both are on you:
putting `.mcp.json` where the agent will not look, and not telling the user
that a restart is required.

## 1. Check the environment

- Python ≥ 3.11 (`python3 --version`). Linux or macOS; Windows needs WSL,
  because the store relies on POSIX file locking.
- Find the project directory **this session was started in** — normally the
  working directory. Everything below happens there. If the user names a
  different project, use that and remember it for step 3.

## 2. Install the package

Prefer the environment the user already works in:

```bash
python3 -m venv .venv && .venv/bin/pip install mlparty   # fresh project venv
# …or, into an existing environment:
pip install mlparty
```

The web UI ships prebuilt in the wheel — nothing to build, no Node required.

## 3. Reuse their store if they have one — do not fragment it

A store holds `project → experiment → run` and retrieval spans the whole
store, so **one store covering many projects is the useful shape**. A store
per repo splits the knowledge graph into islands that cannot see each other.
Check before creating anything:

- `$ML_PARTY_STORE`, then `~/.mlparty` — if either exists, that is their
  notebook. Register *it* for this project rather than making a new one:
  `mlp connect --root <that store> --project <this directory>`.
- Nothing yet? Create the personal store and register it once for every
  session, so the working directory stops mattering:

```bash
mlp init --root ~/.mlparty --no-mcp
mlp mcp-config --root ~/.mlparty      # the snippet to register, any client
```

Register it in **whatever client the user actually runs** — do not assume
Claude Code. `mlp mcp-config` prints a standard `mcpServers` entry; put it
in that client's MCP configuration, globally rather than per-project. If
they are on Claude Code, `claude mcp add -s user ml-party -- <abs-path>/mlp
serve-mcp --root ~/.mlparty` does the same thing without the paste. If you
do not know the client, print the snippet and say where it goes rather than
guessing at a config file.

Suggest they set `ML_PARTY_STORE=~/.mlparty` in their shell profile so the
`mlp` CLI finds it from anywhere.

Only make a **project-local** store (`cd <project> && mlp init --root
.mlparty`) if the user wants the notebook to travel with that repo, or a
team shares a served store. If you do, the directory is critical: `mlp init`
writes `.mcp.json` — the project convention Claude Code reads — into the
*current* directory, and a client reads it only from the directory it was
started in, so a store created in `$HOME` while the agent runs in a project
is invisible. For other clients, use `mlp mcp-config` and their own config
location instead.

Either way, report the absolute path of the store and of any `.mcp.json`.

## 4. Tell the user to restart — do not skip this

You cannot load the server into your own running session; the registration
takes effect only when a new session starts. Say so explicitly, in words
like:

> ml-party is installed and registered in `<path>/.mcp.json`. **Restart this
> session** for the MCP server to connect, and approve `ml-party` when
> prompted. You can check it with `/mcp` — it should list `ml-party`.

If it is missing after the restart, the cause is almost always that the
session started in a different directory than the one holding `.mcp.json`
(`claude mcp list` shows what was loaded).

## 5. Stop there

Do not start tracking runs in this session. After the restart the server
teaches its own workflow: the connection brief points at a `workflow_guide`
tool returning the full manual — including asking the user which directory may
be snapshotted, which is their decision to make, not one to pre-empt here.

Optional, if the user wants something to look at immediately:

```bash
.venv/bin/python -m mlparty.demo &   # a real run, streaming live metrics
.venv/bin/mlp ui                     # → http://127.0.0.1:7327
```
