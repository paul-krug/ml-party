# Agent guide

Canonical entry point for any AI agent or contributor working **on this
repo**. (If you are an agent *using* ml-party to track runs, this is the
wrong document — the MCP server teaches you its own workflow; see
[docs/mcp.md](docs/mcp.md).)

## What this is

Agent-native ML experiment tracking + lineage/knowledge substrate. Package
`mlparty`, CLI `mlp`. Read in this order when starting fresh:

1. This file — conventions and runbook.
2. [DESIGN.md](DESIGN.md) — the living design document (ontology, contract,
   internal-git model, storage, surfaces, remote mode). **Wins over every
   other doc on disagreement.**
3. The repo's **GitHub Project** — what ships when.

## Doc map — single source of truth per question

| Question | Owner |
| --- | --- |
| Why is the system shaped this way? Invariants? | [DESIGN.md](DESIGN.md) |
| How do I use it? (users + operating agents) | [docs/](docs/) — [tracking.md](docs/tracking.md), [ui.md](docs/ui.md), [mcp.md](docs/mcp.md) |
| What ships when? | the repo's GitHub Project |
| What changed? | [CHANGELOG.md](CHANGELOG.md) |

**The doc-sync rule: every feature commit updates the docs it touches —
before push, not as a later pass.** New user-visible behavior lands with its
`docs/` section in the same push; design/invariant changes update DESIGN.md;
notable changes get a CHANGELOG line under `[Unreleased]`. Never duplicate
prose across these files — link instead; docs/ describes what the code
*does* (plans live in the GitHub Project only).

## Environment & commands

- Python: repo-local `.venv` (≥3.11).
- Node ≥ 20 for UI builds (`cd ui && npm install` once).

```bash
.venv/bin/python -m pytest tests/ -q          # full suite, ~10 s
.venv/bin/ruff check src tests scripts        # lint gate (CI-enforced)
cd ui && npm run build                        # UI bundle
.venv/bin/python -m sphinx -b html docs docs/_build             # docs site
```

`docs/` is a Sphinx (MyST) source tree: the guide pages are plain markdown,
`api.md` autodocs the public surface, `design.md`/`changelog.md` are include
shims over the repo-root files (never duplicate their content). The docs
build is CI-gated.


## Conventions

- **Features develop on branches and land via PR to `main`** — merge only
  on green CI (ruff + pytest 3.11–3.14 + UI build + docs build + docker
  smoke); squash-merge single-purpose PRs. Small, single-purpose commits
  with conventional-commit-ish prefixes (`feat(ui):`, `fix:`, `docs:`).
  Branch protection enforcement is queued on the repo going public
  (plan-gated on private free repos — see issue #9).
- 0.x semver, tags at phase completion, CHANGELOG under `[Unreleased]` as
  you go.
- Store writes are journal-first and knowledge is append-only — never add a
  write path that mutates nodes destructively or bypasses the journal.
- Tests: pass `python_exe="/nonexistent/python"` to `run_start` to skip the
  slow pip-freeze; MCP list/call helpers are async (`asyncio.run`).

## Gotchas (cost real time — do not re-hit)

- Never `pkill -f` a pattern contained in your own command line (kills the
  shell). Kill the UI by port (`fuser -k 7327/tcp`) or restart the service.
- Backticks in `git commit -m "..."` get shell-expanded — use
  `git commit -F - <<'MSG'` heredocs.
- mcp SDK 2.0: `from mcp.server import MCPServer` (FastMCP is gone).
- fastembed returns numpy float32 — cast to Python floats before json.dumps.
- `git add -A` sweeps build caches — add artifacts to .gitignore first.
