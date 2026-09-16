# Security

## Reporting a vulnerability

Please use GitHub's **"Report a vulnerability"** (Security tab → private
advisory) rather than a public issue. Private reporting is enabled on the
repository; you will get an acknowledgement on a best-effort basis (this
is a small project, not a staffed security team).

## Trust model

Full deployment guidance lives in [docs/deploy.md](docs/deploy.md); the
short version:

- **Local store** (`mlp ui`, MCP over stdio, the in-process client): one
  trust domain — the OS user. Anyone who can run code as you can read and
  write your store; ml-party adds no boundary there by design.
- **Served store** (`mlp serve`): authentication activates with the first
  `mlp user add` — reads require a viewer login, writes a writer, user
  management an admin (store-wide roles). Passwords are scrypt-hashed,
  sessions are HMAC-signed httpOnly cookies, per-user API tokens are
  stored hashed, and login attempts are rate-limited. **Credentials must
  never cross plain HTTP beyond localhost** — deploy behind TLS.
- **Legacy single-token mode** (no users configured): the read API is
  open and one shared token gates ingest — trusted networks only.

## Who can define agent-executable behavior

Run-control **action templates are literal shell** — they are the
allowlist agents drive jobs through. Registration is deliberately **not
exposed over the HTTP API**: adding or changing a template requires access
to the store host (CLI, or MCP running on that machine) — treat it as an
admin operation. Agents and remote writers can only *invoke* templates,
with typed, validated, shell-quoted parameter values — parameters carry
data, never commands. The MCP server's own instructions ship from the
installed package, not from the store: store writers cannot alter them.

## Knowledge is data, not instructions

ml-party's knowledge graph is what agents read back later — which makes it
a prompt-injection surface: anyone with **writer** access adds text
(notes, annotations, run descriptions) that a future agent will retrieve.
Grant writer access accordingly. Every write carries an authenticated
`created_by`, so provenance is always attributable, and the MCP server
instructs agents to treat retrieved content strictly as data. Boards
(agent-authored HTML) render in a sandboxed opaque origin with a strict
CSP — no external hosts, read-only API access, no cookies — and inline
artifact serving is safelisted to non-executing media types.

## Threat model: the agent-instruction supply chain

The section above covers injection at **runtime** — untrusted text
arriving in a store that an agent later reads back. This one covers the
other direction: injection through **the repository itself**.

ml-party is built to be worked on by AI coding agents as well as humans,
so it ships files that an agent reads as **authoritative direction**, not
as inert documentation:

- [`AGENTS.md`](AGENTS.md) — the canonical agent entry point (conventions,
  runbook, gotchas).
- [`CLAUDE.md`](CLAUDE.md) — imports `AGENTS.md`.
- Everything under [`.agents/`](.agents/) — above all the skills at
  `.agents/skills/<name>/SKILL.md`, which are procedures an agent
  *executes* step by step.
- The MCP server's instruction text in
  [`src/mlparty/mcp_server.py`](src/mlparty/mcp_server.py) — this one
  travels **in the wheel** to every agent connected to any ml-party
  store, so its blast radius is every user, not just contributors.

**The risk.** A pull request editing one of these is a prompt-injection
vector. Text merged into `AGENTS.md` or a `SKILL.md` can direct a
maintainer's — or another contributor's — agent to do something harmful
the next time it runs: exfiltrate credentials, run arbitrary commands,
weaken a later review, quietly disable a check. The payload never has to
execute in CI to do damage; it runs inside whatever agent reads the file,
on whatever machine that agent is trusted on. That is a supply-chain
attack on *the people and agents who work on the repo*.

`.github/**` is the same class of risk by a different route:
[`release.yml`](.github/workflows/release.yml) publishes to PyPI under
this project's trusted-publisher identity, so a merged edit there can ship
a malicious wheel to every user under the maintainer's name — with no
token to steal and no secret to revoke.

## The gate suite

Defense is layered, and each gate names where it is enforced so the rule
and its enforcement cannot drift apart.

1. **Merging requires write access.** Only maintainers can merge, so an
   outside PR is a *proposal*; the real risk is a maintainer being talked
   into merging a poisoned diff. Gates 2–4 exist to make that hard.

2. **Automatic flag + close.**
   [`.github/workflows/agent-instruction-guard.yml`](.github/workflows/agent-instruction-guard.yml)
   labels every PR touching an instruction or gate path, and
   **automatically closes** one that comes from outside the maintainers,
   pointing at [`CONTRIBUTING.md`](CONTRIBUTING.md). Because the policy is
   documented, such a PR is either a mistake or an attack — either way a
   maintainer must open that conversation deliberately. Changes to
   `mcp_server.py` are flagged loudly but never auto-closed: legitimate
   feature work lands there.

3. **Declared code ownership.** [`.github/CODEOWNERS`](.github/CODEOWNERS)
   claims the instruction paths *and* `.github/**`, so the gates cannot be
   edited open in the same PR that attacks them. Honest caveat: CODEOWNERS
   only blocks a merge when branch protection has "Require review from
   Code Owners" on, and that is **off today** — with a single maintainer
   it would block every PR, since nobody can approve their own. It becomes
   enforceable the moment a second maintainer exists.

4. **Repository content is data, not instructions.** When an agent reviews
   a PR — including a PR to the instruction files — the diff is material
   to evaluate, never commands to obey. AI review of these paths is
   advisory; a human makes the merge decision.

5. **Branch protection.** `main` takes no direct pushes from anyone,
   admins included; all eight checks must pass and the branch must be
   current before a merge is possible.

## Code snapshots are a data-exposure surface

A run's code snapshot copies file *contents* into the store, and a served
store shows them to everyone with viewer access — so what a snapshot
collects is a privacy decision, not just a reproducibility one. Captures
are therefore explicit and bounded: no `source_root` means no code is
captured; inside a git repo the boundary is what git tracks (your
`.gitignore` is honoured); outside one, or past the size thresholds, the
capture is refused until the caller passes `confirm_snapshot` after
reviewing the file list; a root at or above `$HOME` is refused outright;
and secret-shaped filenames are denied even when tracked. Preview any
capture with `mlp snapshot-preview <dir>` before it is written.

## Known limitations (0.x)

- Roles are store-wide (no per-project scoping yet); OIDC/SSO is planned
  but not shipped — accounts are per-deployment.
- Actions execute as the serving process's user on its host.
- The login rate limiter is in-memory (per process); a restart clears it.
- Read endpoints send permissive CORS headers (sandboxed boards live in an
  opaque origin and need them). With auth **enabled** this is harmless —
  cross-origin requests carry no credentials. With auth **off**, any
  website open in a browser that can reach the server may read store data;
  keep no-auth servers strictly on localhost, or add users.
