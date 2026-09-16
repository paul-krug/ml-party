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
