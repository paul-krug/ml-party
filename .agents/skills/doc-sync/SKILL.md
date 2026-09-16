---
name: doc-sync
description: >-
  Audit and update the documentation a change touches — run before every PR.
  Use whenever a change adds, renames, or removes public API, MCP tools, or CLI
  commands; changes install/run instructions or documented behavior; alters the
  storage or security model; or moves files. Two steps: (1) audit which
  surfaces reference the change and how they went stale (README, docs/,
  DESIGN.md, SECURITY.md, AGENTS.md, CHANGELOG, MCP instructions, CLI help,
  docstrings); (2) update them, verified against the code — not from memory.
---

# doc-sync — audit & update the docs a change touches

Docs here are read by two audiences that both act on them: **humans**
following instructions literally, and **agents** navigating the repo or
driving the MCP server. Stale docs do not merely age — they actively
mislead, and an agent will follow them off a cliff without hesitating.
So docs are updated **with** the change, in the same PR, never deferred.

Two steps, always in order: **(1) audit** what's affected, then **(2) update**
what the audit flagged. The audit is cheap and always runs, including on
changes you expect to be doc-free. If there genuinely is no doc footprint
(test-only change, internal refactor with no behavior/API/instruction
change), record **"no doc impact"** and stop — that's a complete, valid
result.

## Step 1 — Audit

Scope the change first: `git diff --stat main...HEAD`. From the diff, list
what actually changed in kind — **public API** (anything exported from
`mlparty`), **MCP tools** (names, arguments, workflow semantics), **CLI
commands/flags**, **HTTP endpoints**, **install or run instructions**,
**storage/journal/security behavior**, **file moves**. Then walk the table:

| Surface | Where | Check |
|---|---|---|
| README | `README.md` | quickstart (does it still work verbatim?), feature bullets, links, requirements |
| User guide | `docs/*.md` | commands, flags, described behavior, screenshots/paths |
| Landing page | `docs/index.md` | the install block — it duplicates README's quickstart by design; both move together |
| Design doc | `DESIGN.md` | ontology, contract, storage model, surfaces, status markers ("shipped"/"planned") |
| Security | `SECURITY.md` | trust model, new attack surface, known-limitations list |
| Agent guide | `AGENTS.md` | runbook commands, conventions, gotchas, doc map |
| Changelog | `CHANGELOG.md` | a line under `[Unreleased]` if the change is user-visible |
| MCP workflow | `src/mlparty/mcp_server.py` | **the workflow text agents execute** — tool names, arguments, required fields. Detail belongs in `WORKFLOW` (served by the `workflow_guide` tool); `INSTRUCTIONS` is only the connection router and must stay under `INSTRUCTIONS_BUDGET`, since clients truncate it silently |
| CLI help | `src/mlparty/cli.py` | command and option help strings |
| Docstrings | changed modules | public surfaces only; module `__init__` architectural docstrings |
| API reference | `docs/api.md` | autodoc targets still exist under those names |
| Packaging | `pyproject.toml`, `Dockerfile`, `compose.yaml` | dependencies, extras, entry points, bundled package data |

Useful greps: `grep -rn "<OldName>" --include=*.py --include=*.md .` for a
rename; `grep -rn "pip install\|mlp <command>" README.md docs/` for
instruction drift.

Produce a short table — `file → what's stale → how to fix`. That table is
the audit output and doubles as the PR checklist, even when it comes back
empty.

## Step 2 — Update

1. **Verify against the code, never memory.** Signatures, flags, defaults,
   endpoint paths, and file layouts must match what the code does right
   now. Nothing aspirational: docs describe what ships, not what is
   planned (plans live in the GitHub Project).
2. **Rehearse instructions you changed.** Anything a reader would type is
   verified by typing it — install steps in a fresh venv, CLI commands
   against a scratch store. An install path that was never run is a guess.
3. **Touch only what the audit flagged.** No opportunistic rewrites; they
   bury the real change in review.
4. **Respect the single source of truth.** Each question has one owner (see
   the doc map in `AGENTS.md`) — link across, never restate. In the Sphinx
   tree, `design.md` and `changelog.md` are include shims over the
   repo-root files; edit the root file, never the shim.
5. **Mind the two install paths.** The released package (`pip install
   mlparty`, UI bundled in the wheel) and the from-source checkout (editable
   install + `npm run build`) are different instructions for different
   readers. A change to one is usually a change to both.
6. **Treat MCP instruction text as code.** It is what every connected agent
   reads before acting; a renamed tool or a changed required field that
   misses it breaks agents silently, with no error to trace.

Verify mechanically before the PR:

```bash
.venv/bin/python -m sphinx -b html docs docs/_build   # docs build (CI-gated)
.venv/bin/ruff check src tests scripts
.venv/bin/python -m pytest tests/ -q
```

## Output

For the PR description: the audit table, what was updated, and an explicit
"no doc impact" for surfaces checked and found current. **Stale docs block
the PR** — the change isn't done until the audit comes back clean.
