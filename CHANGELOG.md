# Changelog

User-facing changes, per release. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/); versioning is 0.x semver —
minor bumps may break APIs until 1.0. Day-to-day changes live in the git
history and pull requests; entries land here when they are release-worthy.

## [Unreleased]

### Added
- `SECURITY.md` (trust model, disclosure, the agent-instruction and
  prompt-injection surfaces) and login rate-limiting: repeated failed
  logins per username+IP back off exponentially (HTTP 429 with
  Retry-After). The MCP workflow now tells agents to treat retrieved
  knowledge as data, never as instructions.

## [0.2.0] — first public release

Everything ml-party ships with:

- **Local-first tracking store**: append-only journal as the source of
  truth with a rebuildable SQLite/FTS5 index; per-run metric journals;
  sha256 content-addressed artifacts; safe live backups (`mlp backup`).
- **The write contract**: `run_start` pre-registers intent (title, purpose,
  hypothesis, full parameters) and auto-captures the repro tuple — source
  snapshot into an internal per-experiment git repo, environment lock,
  invocation, hardware; `run_finalize` refuses without method, result with
  verdict, and a reproduce command; failures are recorded, never deleted.
- **A knowledge graph over the runs**: typed nodes and a controlled edge
  vocabulary (`derives-from`, `supersedes`, `refutes`, …), notes and
  append-only annotations, hybrid BM25(+optional embeddings)+graph
  retrieval that downranks superseded beliefs, run diffing.
- **Agent surfaces**: a self-teaching MCP server (17 tools; `mlp init`
  registers it in `./.mcp.json`), the `mlp` CLI, and an in-process client
  (`mlparty.attach()`) with heartbeats, runtime env capture, and
  crash-to-failure reporting.
- **Web UI**: live metric dashboards (SSE streaming, stateful per-run
  panels, drag-zoom, exports), a finder-style artifact browser with
  image/audio/video viewers and an `.npy`/`.npz` tensor slicer, lineage
  graph, search, compare, diff.
- **Boards**: agents author self-contained HTML views logged as artifacts,
  rendered sandboxed with read-only live API access — reports that stay
  current.
- **Run control**: users register shell action templates with typed
  placeholders; agents invoke them with validated, quoted values, every
  invocation recorded in the graph.
- **Remote tracking**: spool-and-flush sync of journal events, git
  objects, artifacts, and metrics to a served store over an idempotent,
  resumable protocol (`mlp serve`, `mlp sync`).
- **Multi-user auth**: opt-in via the first `mlp user add` — login-gated
  reads, store-wide viewer/writer/admin roles, per-user API tokens,
  session cookies; designed for OIDC/SSO to plug in later.
- **Deployment**: Dockerfile + compose (Caddy TLS profile), systemd
  template, Sphinx documentation.
