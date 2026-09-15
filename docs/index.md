# ml-party

**An agent-native platform for ML experiment tracking and lineage/knowledge.**

A durable, agent-legible knowledge substrate for ML work — a lab notebook
that agents write (over MCP) and query, and that humans read live (CLI +
web UI) — that also happens to be a full local tracker: metrics, artifacts,
checkpoints, reproducibility, all stored locally.

Linux/macOS (Windows via WSL), Python ≥ 3.11, Node ≥ 20 for the one-time
web-UI build:

```bash
git clone https://github.com/paul-krug/ml-party && cd ml-party
python -m venv .venv && .venv/bin/pip install -e .
(cd ui && npm install && npm run build)     # web UI bundle, once

.venv/bin/mlp init --root .mlparty          # create a store (+ MCP registration)
.venv/bin/python scripts/demo_live_run.py & # a real run: contract + live metrics
.venv/bin/mlp ui                            # → http://127.0.0.1:7327
```

From there: agents pick up the MCP server automatically and it teaches them
the workflow ({doc}`mcp`); training scripts attach as the second writer
({doc}`tracking`); humans watch live in the web UI ({doc}`ui`); registered
actions let agents drive jobs, audited ({doc}`actions`).

```{toctree}
:maxdepth: 2
:caption: User guide

tracking
ui
boards
actions
mcp
remote
deploy
```

```{toctree}
:maxdepth: 1
:caption: Reference

api
design
changelog
```
