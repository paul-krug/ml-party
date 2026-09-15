# Deployment

How to run an ml-party server for real. The short version is a decision
tree; every path ends at the same server (`mlp serve` = web UI + read API +
authenticated sync ingest on one port).

> **The rule that overrides everything:** credentials — passwords, session
> cookies, API tokens — must never cross plain HTTP beyond localhost.
> Anything reachable by others goes behind TLS (the `tls` profile, or your
> own proxy). And exposing a server beyond a trusted network requires
> **auth mode** (users configured): legacy single-token mode leaves the
> read API open and belongs on trusted networks (SSH tunnel, VPN) only.

## Auth: users, roles, tokens

Create the first user and the served store switches to authenticated mode —
login required for everything, the legacy `--token` ignored:

```bash
mlp user add paul --role admin --root /srv/mlparty/.mlparty    # prompts for a password
mlp user add kim --role viewer --root ...                      # viewer | writer | admin
mlp token create --user paul --name laptop-sync --root ...     # printed ONCE
```

Roles are store-wide: **viewer** reads, **writer** reads + writes
(annotations, sync ingest), **admin** additionally manages users (CLI).
Humans sign in through the web UI (sessions survive server restarts;
a password reset via `mlp user set-password` invalidates that user's
sessions). Machines — training boxes, sync clients, CI — use per-user
tokens: put one in the spool store's `[sync]` config exactly like the
legacy token. `mlp token revoke <id>` cuts one off without touching the
user. A store with **no** users behaves as before: open reads, single
`ML_PARTY_TOKEN` gating ingest — fine for localhost and tunnels, nothing
more.

SSO note: the identity layer is built for it (see DESIGN.md §12) — OIDC
(Entra ID first) plugs in as a second way to sign in, on top of the same
users, roles, and tokens. Until it lands, accounts are per-deployment.

## Decision tree

- **Just me, one box** → `mlp serve` (or `mlp ui` if you don't need sync)
  as a systemd user service; reach it via `ssh -L 7327:localhost:7327`.
  Template: [deploy/mlparty-server.service](https://github.com/paul-krug/ml-party/blob/main/deploy/mlparty-server.service).
- **A team on a trusted network / VPN** → Docker compose + users
  (binds 127.0.0.1 on the host; expose via the VPN interface or tunnel).
- **Reachable beyond a trusted network** → compose with the `tls` profile
  (Caddy, automatic Let's Encrypt certificates) **and users configured** —
  never the legacy token.

## Docker

```bash
docker build -t ml-party .
docker run -d --name mlparty --restart unless-stopped \
    -p 127.0.0.1:7327:7327 \
    -v mlparty-data:/data \
    -e ML_PARTY_TOKEN="$(openssl rand -base64 32)" \
    ml-party

# switch it to auth mode (takes effect immediately, no restart):
docker exec -it mlparty mlp user add paul --role admin --root /data
```

The entrypoint initializes the store on first boot and refuses to start
with no auth at all (neither users on the volume nor `ML_PARTY_TOKEN`).
The container runs non-root and sees only the `/data` volume. Health:
`docker inspect --format='{{.State.Health.Status}}' mlparty`.

## Compose

```bash
export ML_PARTY_TOKEN="$(openssl rand -base64 32)"   # or put it in .env

docker compose up -d                                  # localhost:7327 (tunnel access)
DOMAIN=tracker.example.org docker compose --profile tls up -d   # public, HTTPS
```

The `tls` profile adds Caddy: certificates are obtained and renewed
automatically for `$DOMAIN`; only ports 80/443 are public and the server
container is not directly exposed. Clients then use
`url = "https://tracker.example.org"` in their `store.toml [sync]`.

**Using nginx instead**: terminate TLS as usual and proxy to
`127.0.0.1:7327` — but disable response buffering or live metric streams
(SSE) will stall:

```nginx
location / {
    proxy_pass http://127.0.0.1:7327;
    proxy_buffering off;          # REQUIRED for /api/runs/*/metrics/stream
    proxy_set_header Host $host;
}
```

## Backup & restore

```bash
mlp backup /backups/mlparty-$(date +%F) --root /path/to/store
```

Safe while runs are writing: the journal is copied first, and since content
(artifacts, git objects) is always written before the journal event that
references it, the snapshot's journal only references content the copy
contains. A torn trailing journal line (append caught mid-write) is
tolerated on replay. Users and hashed tokens (`auth/`) are included;
`index.sqlite` (rebuildable) and `sync_state.json` (client-side cursors)
are deliberately excluded. Backups contain credential hashes and the
session-signing secret — protect the destination accordingly.

Restore: point at the copy and rebuild the index — that's all.

```bash
mlp rebuild-index --root /backups/mlparty-2026-08-29
mlp serve --root /backups/mlparty-2026-08-29 ...
```

For the Docker volume, run the same through the image:
`docker exec mlparty mlp backup /data-backup --root /data` with a second
volume mounted, or plainly rsync the named volume's directory — the
journal-first ordering is what the `mlp backup` command exists to get right.

## Security model

The trust boundaries, the agent-instruction surface (action templates,
knowledge-graph content), and vulnerability reporting are summarized in
[SECURITY.md](https://github.com/paul-krug/ml-party/blob/main/SECURITY.md).

## Who needs access to what

Only the admin touches Docker/systemd (the docker socket is
root-equivalent — never put ordinary users or service accounts in the
`docker` group) and manages accounts (`mlp user`). Everyone else — humans
and agents — interacts with the server exclusively through its URL:
browser login for the UI, a personal `[sync]` token for shipping runs,
MCP for agents pointed at a spool store.
