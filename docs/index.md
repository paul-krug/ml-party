# ml-party

**An agent-native platform for ML experiment tracking and lineage/knowledge.**

A durable, agent-legible knowledge substrate for ML work — a lab notebook
that agents write (over MCP) and query, and that humans read live (CLI +
web UI) — that also happens to be a full local tracker: metrics, artifacts,
checkpoints, reproducibility, all stored locally.

Linux/macOS (Windows via WSL), Python ≥ 3.11. The web UI ships prebuilt in
the wheel:

```bash
pip install mlparty
mlp init --root ~/.mlparty --no-mcp         # one store holds all your projects
export ML_PARTY_STORE=~/.mlparty            # put this in your shell profile

python -m mlparty.demo &                    # a real run: contract + live metrics
mlp ui                                      # → http://127.0.0.1:7327
```

Then register the store with your agent — one command for Claude Code, a
snippet to paste for any other MCP client — and restart the session:
{doc}`mcp`. That page also covers [one store versus one per
project](mcp.md#one-store-or-one-per-project), which is worth deciding
before you accumulate runs.

To develop against a checkout instead, see
[From source](https://github.com/paul-krug/ml-party#from-source) (adds Node
≥ 20 for the UI build).

From there: the MCP server teaches agents the workflow ({doc}`mcp`);
training scripts attach as the second writer ({doc}`tracking`); humans watch
live in the web UI ({doc}`ui`); registered actions let agents drive jobs,
audited ({doc}`actions`).

```{toctree}
:maxdepth: 2
:caption: User guide

quickstart
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
