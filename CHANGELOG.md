# Changelog

User-facing changes, per release. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/); versioning is 0.x semver —
minor bumps may break APIs until 1.0. Day-to-day changes live in the git
history and pull requests; entries land here when they are release-worthy.

## [Unreleased]

## [0.2.4] — 2026-09-16

### Added
- An [install skill](.agents/skills/install-ml-party/SKILL.md) an agent can
  follow to set ml-party up in someone's project: reuse an existing store
  rather than fragmenting the graph, put `.mcp.json` where the agent will
  actually read it, and tell the user to restart the session.
- Copy buttons on the docs site's code blocks (`sphinx-copybutton`); GitHub
  already renders them for README code fences.

### Changed
- Install instructions rewritten around **one store holding many projects**,
  registered globally, instead of a store per repository — retrieval spans a
  store, so a store per repo splits the knowledge graph into islands. Two
  clear paths (let an agent install it, or do it yourself) replace the old
  single block, and registration is described for any MCP client rather than
  Claude Code alone. The per-project variant, and when it is worth the
  trade-off, moved into the [MCP setup
  guide](https://paul-krug.github.io/ml-party/mcp.html#one-store-or-one-per-project).
- `mlp mcp-config` explains where to paste its output (on stderr, so the
  JSON on stdout stays pipeable).

### Fixed
- `python -m mlparty.demo` honours `ML_PARTY_STORE` like the rest of the
  CLI, instead of always defaulting to `./.mlparty`.

## [0.2.3] — 2026-09-16

### Fixed
- **Code snapshots no longer capture files you did not point at.**
  Previously a run with no `source_root` snapshotted the whole directory
  holding the store, and collection was a filesystem walk that never
  consulted git — so unrelated files (personal notes, agent conversation
  logs) could be copied into a run and, through sync, into a shared store.

### Changed
- **Breaking:** `run_start` without `source_root` now records **no** code
  snapshot instead of guessing a directory. Env lock, hardware, invocation
  and outer-git provenance are still captured automatically.
- Inside a git repository the snapshot is now what **git** reports —
  tracked files plus untracked-but-unignored ones — so `.gitignore` decides
  what belongs to the project. The extension allowlist no longer applies
  there, which also means tracked `.cpp`/`.cu`/`.rs` sources are captured
  at last. Secret-shaped filenames stay denied, tracked or not.
- A non-git `source_root`, or a capture above `confirm_above_files` /
  `confirm_above_bytes`, now requires `confirm_snapshot=True`; the refusal
  carries a preview of exactly what would be captured. A `source_root` at
  or above `$HOME` is refused outright.
- `snapshot_report` now records the files that were **included**, not only
  those excluded.

- Agents are now instructed to **ask which directory to capture** before the
  first tracked run in a project, show the file list from `snapshot_preview`
  before anything is written, and point out that `.gitignore` is what keeps a
  file out — so the choice is made knowingly instead of defaulted into.
  `source_root` is documented in the README and MCP guide too; it was
  previously mentioned only in passing, despite deciding what leaves your
  machine.
- `mlp init` / `mlp connect` now print where `.mcp.json` was written and how
  to make it take effect — agents read it from the directory they are
  *started* in, and need a one-time approval — plus how to verify (`/mcp`,
  `claude mcp list`). Previously they claimed agents "pick it up
  automatically", which quietly assumed both.

### Added
- `snapshot_preview()` — core API, `snapshot_preview` MCP tool, and
  `mlp snapshot-preview <dir>` — shows what a capture would take without
  writing anything, plus the delta (added / modified / removed) against the
  snapshot already stored for an experiment.

## [0.2.2] — 2026-09-16

### Fixed
- **Hardware capture on macOS**: total RAM was read only from
  `/proc/meminfo`, so every run tracked on a Mac recorded no RAM at all —
  silently, since the read was already fault-tolerant. Falls back to
  `sysctl hw.memsize`. macOS is now covered by CI (Python 3.11 and 3.14)
  instead of assumed.

### Added
- Repository-level security policy: SECURITY.md documents the
  agent-instruction supply chain (instruction files are read by AI agents
  as direction, so editing them is a prompt-injection vector) and the
  gates against it; `CONTRIBUTING.md` states that PRs from outside
  contributors touching those paths are closed automatically, enforced by
  a new guard workflow plus CODEOWNERS.

## [0.2.1] — 2026-09-16

### Added
- The live demo run ships with the package: `python -m mlparty.demo`
  (previously a repo-only script), so a `pip install mlparty` has a real
  run to watch immediately — the documented quickstart now works as
  written from the released wheel.

## [0.2.0] — 2026-09-16, first public release

Everything ml-party ships with:

- **Security posture**: `SECURITY.md` (trust model, disclosure, the
  agent-instruction and prompt-injection surfaces) and login
  rate-limiting: repeated failed logins per username+IP back off
  exponentially (HTTP 429 with Retry-After). The MCP workflow tells
  agents to treat retrieved knowledge as data, never as instructions.

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
