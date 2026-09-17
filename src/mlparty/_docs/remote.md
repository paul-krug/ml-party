# Remote tracking (spool-and-flush)

Track runs on one machine, store and watch them on another. Design
rationale: [the design document](design.md) §9. The model is
**spool-and-flush**: nothing ever writes to the network directly — every
writer uses a normal local store (the *spool*), and a flusher ships the
delta to the server. Offline runs, crashes, and lost connections lose
nothing; the spool keeps everything until it's shipped, and every shipment
is idempotent, so retrying is always safe.

**This page is about where a run's *data* lives, not where its *compute*
is.** To record that a run executes on a cluster or a queue — the job
system, its id, and a link back to the job — see
[run_set_compute](tracking.md#runs-that-execute-somewhere-else). The two are
independent and a remote job usually wants both: it flushes its data here,
and the run points back at it there.

## Server (machine S)

```bash
# authenticated mode — users, roles, per-user tokens:
mlp user add paul --role admin --root /srv/mlparty/.mlparty
mlp token create --user paul --name train-box --root /srv/mlparty/.mlparty
mlp serve --root /srv/mlparty/.mlparty

# or legacy single-token mode (trusted networks only — reads stay open):
mlp serve --root /srv/mlparty/.mlparty --generate-token
```

`mlp serve` is `mlp ui` plus the authenticated sync-ingest API — same web
viewer, same read API. With users configured, everything is login-gated:
humans sign into the web UI, sync clients authenticate with a per-user
token, and ingest needs the **writer** role (see {doc}`deploy` for
roles/administration). Keep it localhost-bound and tunnel over SSH, or put
TLS in front before exposing it; credentials ride on every request. A
server started with plain `mlp ui` refuses all sync writes.

## Client (machine C or L)

Point the spool store at the server in `store.toml`:

```toml
[sync]
url = "http://127.0.0.1:7327"     # or the tunneled/TLS address
token_file = "server_token"        # or token = "…", or ML_PARTY_TOKEN env
interval_seconds = 10
```

The token is either a per-user `mlp_…` token (auth mode — must belong to a
writer) or the legacy shared token; the client doesn't care which.

That's all. From then on:

- `mlparty.attach()` flushes in a **background thread** while the training
  runs (metrics appear in the server UI within ~one interval) and does a
  synchronous final flush at finalize/fail.
- `mlp sync` ships anything left over — after a crash, an offline run, or
  for stores nothing is attached to. Run it any time; it converges.
  Override ad hoc with `mlp sync --to URL --token …`.

## What ships, and why it's safe

| Stream | Addressing | Retry behavior |
| --- | --- | --- |
| journal events | ULID id per event | server dedupes; replays are no-ops |
| git snapshots | content (sha) + `refs/runs/*` | missing-negotiation; re-push skips |
| artifacts | content (sha256) | deduped on existence, hash-verified |
| metrics | byte offset per run | cursor advances only on ack; conflicts resume from the server's size |

Events are preserved verbatim — authorship (`created_by`) and timestamps
survive the hop; the git model applies (the event's `created_by` is the
*author*, the authenticated token user is the transport identity that
shipped it). Sync cursors live in the spool's `sync_state.json`; deleting
it merely causes a harmless full replay.

## Caveats

- One spool per run: two spools syncing *the same run's metrics* to one
  server is detected and refused (offset conflict) — knowledge-graph events
  from many spools merge fine.
- In legacy single-token mode the server trusts the token entirely and the
  read API is open — trusted networks only. Configure users for per-user
  identity and login-gated reads.
