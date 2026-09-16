# ml-party — Design

> **The living design document** — when any other doc disagrees with
> this file, this file wins. User-facing how-to docs live in the
> `docs/` user guide; planning lives in the repo's GitHub Project.

---

## 1. Thesis

Every existing experiment tracker — W&B, MLflow, Neptune, Comet, Aim — is
human-dashboard-first: excellent at scalars-over-time and config dicts,
nearly silent about *why* a run exists and *how it relates* to the others.
The information that rots first is not the metrics — it's the **reasoning
and the lineage**. ml-party bets that AI agents are the interface that will
matter, so it is designed API-first for agents (usable by humans), and it
treats a run's **abstract, typed relationships, and reproducibility contract
as first-class data**.

**One-liner:** *a durable, agent-legible knowledge substrate for ML work — a
lab notebook that agents write and query — that also happens to be a full
local tracker.*

The motivating case study is lived: ml-party was born inside a real
research codebase that had accumulated dozens of cryptically named run
directories of uncertain reproducibility, and fought it with a
hand-rolled discipline of memory files, handoff docs, and `[[links]]`. ml-party is that discipline made
structural, enforced, and queryable — so it no longer depends on an agent
remembering to write a good handoff.

## 2. Principles

1. **System of record.** ml-party owns knowledge (intent, lineage, verdicts)
   and the reproducibility contract. Telemetry mirrors are optional adapters;
   **knowledge never lives primarily in a mirror target** (§10).
2. **Agents-first, humans always.** Every capability lands API/MCP-first and
   is mirrored in the CLI and web UI. The MCP server teaches its own
   workflow (§8.1).
3. **The write contract is the product** — not the graph visualization.
   Enforcement is mechanical: a run cannot be finalized without its required
   knowledge fields, and refusals are machine-readable.
4. **Meet users where they are; win where we're unique.** Instrumentation
   choice belongs to the user (mlparty, W&B, TensorBoard, several at once).
   We don't compete on charting primitives; the bet is agent-authored
   **boards** (§11.1).
5. **Orchestration is delegated, never owned.** Jobs run under slurm / k8s /
   user scripts; ml-party tracks them wherever they execute and (later)
   exposes an audited control surface over user-registered actions (§11.2).
6. **Multi-user-shaped, single-user first.** Every write carries an
   identity; the API is scoped so tenancy can be added without breaking
   shape; user management ships late.
7. **Local-first forever.** The remote mode (§9) is a sync/transport layer
   over the same journal-first store; a laptop with no server keeps full
   functionality.
8. **Knowledge is append-only; correction is an edge.** Nodes are never
   destructively edited. `supersedes` / `refutes` edges are the correction
   mechanism, and retrieval downranks corrected beliefs — enforcement
   produces completeness, not truth, so the correction story is structural.

## 3. Ontology

Fixed spine, extensible ribs: a small fixed core (so tools and cross-project
reasoning work) plus custom node types and `x-`-prefixed custom edges.

**Core node types:** `project → experiment → run`, plus `note` for distilled
knowledge (kinds: feedback / reference / insight). An experiment answers
**one question**; new question → new experiment. There is deliberately no
`sweep` core type — a sweep is N runs sharing a commit, grouped by
`params_hash` or a `part-of` edge.

**Every node carries:** ULID `id`, `type`, required human-legible `title`
(the anti-cryptic-run-name rule), derived `slug`, `tags`, `created_by`
(agent / human / `librarian` / `ingest`), timestamps, `schema_version`.

**Core edge vocabulary:** `derives-from`, `supersedes`, `compares-to`,
`produces`, `uses-data`, `part-of`, `confirms`, `refutes`,
`duplicate-of`. Every edge carries provenance (`created_by`, `created_at`,
optional `note`) so a librarian-asserted edge is distinguishable from an
author-asserted one.

**The run node** records the full execution:

- `status`: `open | finalized | failed | abandoned` (abandoned = silent
  death, stamped by a TTL janitor — different knowledge from a declared
  failure).
- `parameters` — the full config, **mandatory and separate from the code
  commit** (§5 explains why), canonicalized; `params_hash` indexed.
- The **repro tuple**, auto-captured: `code_ref` (internal-git commit),
  `snapshot_report`, `project_git` (outer repo remote/HEAD/dirty),
  `invocation` (argv, cwd, entrypoint, allowlisted env — redacted),
  `env_lock_ref` (lockfile *inside* the snapshot commit), `data_refs`
  (`{uri, fingerprint, role}`), `seed`, `hardware`.
- `result` at finalize: `summary`, `verdict ∈ {confirmed, refuted,
  inconclusive}`, headline `metrics` (knowledge — indexed and searchable;
  the step *series* is telemetry in the per-run journal, not the graph),
  `surprises` (often the highest-value field).
- `reproduce` — exact re-run invocation, prefilled from the captured argv.
- `failure` on failed runs: `what_failed`, `failure_class ∈ {crash, oom,
  diverged, wrong-result, env, cancelled}`, optional why/traceback.

Concrete pydantic schemas: `src/mlparty/models.py` (the code is the
schema reference).

## 4. The write contract

**Pre-registration split** — intent is only honest before results exist:

- `run_start` requires: `title`, `purpose`, `hypothesis`, `parameters`.
  `"exploratory: <question>"` is a valid hypothesis — forcing fake
  falsifiable claims on exploratory runs would generate slop. A run that
  dies before finalize therefore still carries intent + config + repro
  tuple instead of becoming a mystery directory.
- `run_finalize` adds: `method`, `result` (summary / verdict / metrics —
  `metrics_note` may justify an empty dict / surprises), `reproduce`.
  Refusals are machine-readable `{missing: [...], invalid: [...]}` so an
  agent repairs in one round-trip.
- `run_fail` records the lighter floor: enough that *a future agent can
  decide whether to re-attempt without re-running it*.

Validation is **deterministic only** (presence, minimum content, resolvable
edge targets, enums). Semantic quality policing is the librarian's job,
never the write path's — a slow or flaky gate teaches agents to route
around the contract.

Because the contract's cost lands on the author and its value on a reader
weeks later, the write path gives value back: `run_start` returns hints
(tree-identical prior runs, stale open runs) and auto-captures everything
mechanically capturable, so the contract only demands what *only the author
knows*. Retro ingest (`provenance: retro`) relaxes only `code_ref` — retro
data must not weaken the live contract.

## 5. Code & reproducibility — the internal-git model

Each experiment owns a **bare internal git repository** (dulwich plumbing,
no working checkout). At `run_start` the actually-running source — including
uncommitted and project-gitignored files, where real ML scratch lives — is
snapshotted as a commit. Load-bearing invariants:

1. **A run is not a commit — a run *references* a commit.** Many runs → one
   commit is normal: a launch-arg sweep leaves the tree byte-identical, so
   runs share the commit and differ only in `parameters`. This is exactly
   why `parameters` is mandatory and separate — commit-only recording would
   collapse a sweep into one irreproducible blur.
2. **Commit identity = (tree, parents).** Same tree + same declared
   derivation → same commit (dedup); same tree + different declared parent →
   distinct commit sharing the tree objects (~free).
3. **Parentage follows declared derivation, not launch order.** Default is
   an **orphan root**; `derives_from` becomes the commit parent. The DAG
   never asserts false lineage — assist-don't-assert hints suggest edges,
   the author confirms them.
4. **The knowledge graph's `derives-from` edges are authoritative; the git
   DAG is a materialized view** (for diff/ancestry). Derived views can be
   regenerated; the authoritative store cannot.
5. **One ref per run** (`refs/runs/<run_id>`) — no shared branch tip, no ref
   races; this plus per-run metric journals and SQLite-WAL short
   transactions makes concurrency safe by construction.
6. **Nothing is captured that the user did not point at.** `source_root` is
   explicit: without it a run records *no* source. With it, and when the
   root is a git repo, the file set is what **git** reports (tracked plus
   untracked-but-unignored) — `.gitignore` is a boundary the user already
   drew, so the snapshot inherits it instead of second-guessing it with an
   extension allowlist. A non-git root has no such boundary, so it falls
   back to the allowlist walk *and* requires `confirm_snapshot`; so does any
   capture past `confirm_above_files` / `confirm_above_bytes`. A root at or
   above `$HOME` is refused outright. Secret-shaped filenames are denied and
   size caps apply in both modes, with a hard refusal listing offenders.
   The **snapshot report records what went in as well as what stayed out** —
   capture fails in two directions (silently dropping the file that
   mattered; silently absorbing files that were never meant to leave the
   machine), and only an auditable report catches both. `snapshot_preview()`
   answers the same question before anything is written. Known trap: run
   *outputs* inside the source tree bloat snapshots; exclude them in
   `store.toml`.
7. **Env lock lives *in* the snapshot** (`.mlparty/env.lock` — part of the
   program, diffed and dedup'd); instance facts (hardware, seed, data
   fingerprints, metrics) live on the run node.
8. **Secrets hygiene.** Parameter/env values with secret-shaped keys
   (`*_KEY`, `*TOKEN*`, `*SECRET*`, …) are redacted before persist and the
   redactions noted in the report.

## 6. Storage — journal-first

The append-only **`journal.jsonl` is the store's source of truth**
(flock'd, fsync'd). SQLite (WAL + FTS5 + embedding cache) is a rebuildable
index over it. This buys crash-safety, model-swappable embeddings, "ship
missing events" sync (§9), and the librarian's event bus.

```
.mlparty/
  store.toml                       # allowlist, caps, embedder, redaction rules
  journal.jsonl                    # append-only event log — source of truth
  index.sqlite                     # nodes/edges/FTS5/vectors — rebuildable
  repos/<experiment_id>.git/       # bare internal repos; refs/runs/<run_id>
  runs/<run_id>/metrics.jsonl      # per-run telemetry journals (byte-offset tailed)
  artifacts/sha256/ab/cd/<hash>    # content-addressed artifact store
```

**Artifacts are a separate sha256 CAS** — not git, not LFS (git zlib-packs
binaries slowly for zero dedup gain on checkpoints; LFS drags in server
plumbing). Whole-file dedup; `ArtifactRef = {sha256, bytes, media_type,
original_path}`. Data itself lives anywhere — a `DataRef` stores
`uri + fingerprint`, never the bytes.

## 7. Retrieval

Tiered and swappable, offline-capable at every tier. Default = SQLite
FTS5/BM25 (zero extra deps); optional local embedder (fastembed / ONNX)
and API embedders behind one interface, with cached embeddings. Hybrid =
reciprocal-rank fusion of lexical + vector, then **1-hop typed graph
expansion** of seed hits, **downranking superseded/refuted nodes** (×0.35,
annotated `corrected_by`). Results are compact cards; agents drill down via
`node_get`, keeping query responses cheap in tokens.

## 8. Surfaces — thin frontends over one core

`MlParty` (core.py) is THE single API; the MCP server, the in-process
client, the `mlp` CLI, and the read-only HTTP+SSE API are thin frontends
over it.

### 8.1 MCP — the agent surface, self-teaching

13 tools (`project_ensure`, `experiment_ensure/list`, `run_start`,
`run_log_metric`, `run_log_artifact`, `run_finalize`, `run_fail`,
`note_create`, `node_get`, `node_annotate`, `graph_query`, `run_diff`).
Contract refusals return as data (`{ok: false, refusal: {...}}`), never as
protocol errors.

**Zero-terminal setup is a product requirement**: `mlp init` writes/merges
`./.mcp.json` so agents in the project pick the server up automatically;
the full workflow (prior-art query → pre-register → env-launch with
instrumentation snippet → finalize → distill) ships as the server's MCP
`instructions` and as a `track_training` prompt. "Use ml-party for this
run" is all a cold agent needs to hear — validated on unbriefed agents.

### 8.2 The two-writer architecture

An agent will not proxy 10k `log_metric` calls. The **agent brackets the
run over MCP** (start / finalize); the **training process is the second
writer**, streaming telemetry through the client lib: `mlparty.attach()`
picks up the `ML_PARTY_STORE` / `ML_PARTY_RUN` env handshake, logs
metrics/artifacts to the per-run journal, and auto-fails the run with the
traceback on an unhandled crash. No contention: the writers touch disjoint
files. Instrumentation is guarded (inert without `ML_PARTY_RUN`), so
scripts stay runnable standalone.

**Telemetry is optional; knowledge is mandatory.** If the step series goes
to another tool (or nowhere), the run still finalizes — `result.metrics`
headline numbers are required regardless of telemetry route. This seam
makes "metrics are up to the user" and "metrics are required" compatible.

### 8.3 Web UI

`mlp ui` serves a Vite+React+TS SPA from FastAPI, localhost-bound (tunnel
over SSH, TensorBoard-style). Entity-first IA: experiments → runs → tabbed
run page (Overview | Metrics | Artifacts | Code), live SSE metric charts,
lineage DAG, search, compare, diff, annotate. Served SPA over a desktop
shell because the store lives beside the runs on a headless training box;
Tauri remains a packaging option once the remote API exists.

## 9. Remote mode — the three-machine architecture

Target scenario: the user's laptop **L** (agent lives here), a compute box
**C** (training runs here), a tracking server **S** (store + UI live here).
Local mode is the degenerate case L = C = S.

- **Split repro capture**: the machine that runs the code is the only
  honest witness to its environment. The agent's machine (L) captures the
  code snapshot + intent at `run_start`; `attach()` on the compute host (C)
  patches env lock, hardware, and invocation onto the run. More accurate
  locally too (the launcher shell ≠ the training interpreter).
- **Heartbeats**: the client lib heartbeats in a background thread;
  UI shows running/stale in near-real-time; the janitor uses heartbeat age,
  not mtime, to stamp `abandoned`.
- **Spool-and-flush**: there is deliberately **no RemoteStore
  class** — every writer writes to a local *spool* store (a normal store),
  and a flusher ships the delta to an `mlp serve` instance as three
  idempotent streams: ULID-keyed journal events (preserved verbatim —
  authorship and timestamps survive the hop), content-addressed git
  objects (missing-negotiation push, `refs/runs/*` only) and artifacts,
  and offset-addressed metric appends (cursor advances only on ack; a 409
  reports the server's size and the client resumes from there). Cursors
  live in `sync_state.json`; losing them merely causes a safe replay.
  Reads use the ordinary HTTP read API. Configure via `store.toml [sync]`
  (url + token/token_file/`ML_PARTY_TOKEN`); `mlparty.attach()` flushes in
  a background thread with a synchronous final flush at finalize/fail;
  `mlp sync` ships leftovers after crashes or offline runs.
- **Legacy token auth**: single shared bearer token per server
  (`mlp serve --token/--generate-token`, constant-time compare) but
  **identity-shaped** (token → `created_by` later), so multi-user auth
  changes keys, not shape. A token-less server (`mlp ui`) is read-only.
- **Interim bridge**: without a served store, MCP-over-SSH-stdio reaches one
  with zero new protocol.

## 10. Mirrors — the W&B ownership rule

One instrumentation, fan-out output (future adapter): `mlparty.log_metric()` optionally
mirrors to W&B/MLflow; finalize pushes the abstract/result into the mirror
run's summary. The rule that keeps the system of record coherent:
**telemetry may mirror anywhere; knowledge never lives primarily in the
mirror target.** Zero lock-in either direction; import/backfill from W&B is
a stretch goal.

## 11. Forward design (agreed direction, later phases)

### 11.1 Boards — agent-authored views *(the differentiator — shipped)*

HTML artifacts become first-class **boards**: rendered by the web UI in a
sandboxed iframe (CSP; boards are data, never trusted UI), listed per
run/experiment, and allowed to call the read-only API from inside the
sandbox. Incumbents render charts humans configure; ml-party's agents
*author whole live views* — comparison dashboards, audio/spectrogram
galleries — per experiment. This, not charting parity, is the UX bet.

**Settled: boards never enter the graph spine.** A board is not
a node and gets no `produces` edge — its provenance is already fully
expressed by *containment* (it sits in the `artifacts` list of the run or
experiment that produced it; experiments carry an `artifacts` field
mirroring runs for exactly this). Minting a board node type or edge would
grow the spine for a rendering/discovery concern. Discovery is solved
directly instead: every carried artifact's filename + note (plus a "board"
token for text/html) is indexed into the carrying node's FTS text, so
`graph_query` surfaces the carrier; browsing goes through the board gallery
(`/api/boards`, UI Boards page + per-experiment section). `produces` stays
reserved for true node→node provenance (e.g. a future dataset node).

### 11.2 Run-control plane *(shipped — local mode)*

Users register **action templates** (shell with typed placeholders —
start/stop/resume/requeue); agents invoke them with validated,
shell-quoted parameter values, never free-form strings. Orchestration
stays in slurm/k8s/scripts; ml-party is the uniform, *audited* interface
agents use. **Restart is never a mutation**: "restart with lr halved" = a
new run, `derives-from` the old, params delta explicit — taught by the MCP
workflow.

Settled in the build: **templates are the allowlist** and live in
`<root>/actions.json` (server-side ops config like auth, backed up, not
knowledge); registration is a local-surface operation while the HTTP
server only lists (read) and invokes (write-class: writer role / ingest
token; never a sandboxed board). **Invocations are `action` nodes** — the
`CustomNode` extension mechanism, no spine growth — carrying the rendered
command, params, exit code and output tail, edged `x-controls` to the run
they control; they replay from the journal and sync like any node.
Execution is host-local and detached (outlives the caller); the **remote
runner** (execute on a different compute host than the server; templates
only ever execute where they were installed) is the deferred second half.

### 11.3 The librarian *(post-1.0)*

The first *resident* agent: consumes the event journal (its trigger bus),
proposes dedup / supersedes / summary notes — **additive-only**, never
edits or deletes, writes with `created_by: librarian` + confidence. Its
prerequisites (journal, edge provenance) are already in the core design.

### 11.4 Vision

ml-party grows from a lab notebook into an **ML-workflow-oriented harness
for AI agents**: MCP gives agents hands, the knowledge graph gives them
memory, boards give them a voice, the control plane gives them agency over
jobs, and the journal gives resident agents their trigger bus. The
discipline: the core stays a clean substrate; agents plug in as clients
and hooks, never as a bundled runtime.

## 12. Identity & auth *(shipped)*

Auth is **off until the first user exists** (`mlp user add`); a store
without users behaves as if auth did not exist — `mlp ui` locally, the legacy
single `--token` gating ingest on a served store. Once users exist, the
served store is login-gated end to end: reads need a viewer, writes a
writer, user management an admin (store-wide roles; per-project scoping is
a later, additive layer). The legacy token is then ignored.

**The layer splits in two, deliberately.** Credential *verification* is one
pluggable step; everything else — user records, roles, sessions, per-user
API tokens, `created_by` stamping — is the shared **identity substrate**
every authenticator feeds into. The three SSO-proofing guardrails:

1. Users are keyed by an **internal ULID**, never username/email, and carry
   an `identities` list — `(provider: password)` today; an OIDC identity
   (**Entra ID is the first planned provider**) is appended later, so one
   human can hold both.
2. `authenticate_password()` is a **sibling-shaped function**: an OIDC
   callback lands next to it and issues the same sessions. Never a rework.
3. The password hash is a **nullable field** — SSO-provisioned users simply
   never have one. Roles live on the user record (IdP-group mapping is a
   later additive feature).

Mechanics: users + hashed tokens in `<root>/auth/users.json` (small, text,
diffable, backed up with the store); passwords scrypt-hashed (stdlib — zero
new dependencies); sessions are stateless HMAC-signed httpOnly cookies (a
restart logs nobody out; a password reset invalidates that user's
sessions); machine access via `mlp_…` bearer tokens (`mlp token create`,
shown once, stored hashed) — machines can't SSO, so tokens are permanent
infrastructure, not a stopgap. `created_by` on server writes is the
authenticated principal, not what the request claimed (git's author-vs-
committer split: journal events keep their claimed author; the token user
is the verified transport identity). Sandboxed boards run in opaque origins
that carry no cookies, so the UI mints a **short-lived signed read-only
token** (`?bt=`) for the iframe; boards-lib attaches it transparently, and
it can neither write nor mint successors. MCP/stdio and the in-process
client are local, same-trust-domain surfaces — authentication there is the
OS user, not a login.

## 13. Stack

Python 3.11+ · pydantic v2 (every schema is a model) · SQLite WAL + FTS5 ·
dulwich (pure-Python git plumbing; snapshot trees are small, speed is
irrelevant) · official `mcp` SDK · FastAPI + uvicorn (HTTP/SSE) · typer
(`mlp`) · Vite + React + TS (UI) · pytest + ruff. Nothing in ml-party is
performance-bound; the ecosystem (MCP SDK, git plumbing, ML tooling) is
Python-native.

---

*Validated 2026-08 on a private research corpus: the acceptance queries
answer correctly; a real GPU training was tracked live end-to-end; a
cold, unbriefed agent drove the MCP tools correctly.*
