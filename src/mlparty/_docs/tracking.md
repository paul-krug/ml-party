# Tracking runs

How a run is tracked, what the contract demands, and how the training
process participates. For *why* it's designed this way, see
[the design document](design.md) (§4–5).

## The two writers

Every tracked run has two writers with disjoint jobs:

1. **The agent** (or you, via CLI/MCP) *brackets* the run: `run_start`
   before launch, `run_finalize` / `run_fail` after. This is where knowledge
   enters — intent, config, verdict.
2. **The training process** streams telemetry: it attaches with
   `mlparty.attach()` and logs metrics/artifacts directly. An agent never
   proxies 10k `log_metric` calls.

They meet through an environment handshake: the launcher sets

```
ML_PARTY_STORE=<store root>   ML_PARTY_RUN=<run_id from run_start>
```

and the training script carries a guarded attach that is **inert** when the
variables are unset — the script stays runnable standalone:

```python
try:
    import os, mlparty
    _mlp = mlparty.attach() if os.environ.get("ML_PARTY_RUN") else None
except Exception:
    _mlp = None

# in the loop / at evals:
if _mlp: _mlp.log_metric("loss", float(loss), step=step)
```

## The write contract

- **`run_start` pre-registers intent** (it is only honest before results
  exist): `title`, `purpose`, `hypothesis`, and the full `parameters` are
  required. `"exploratory: <question>"` is a valid hypothesis. Strongly
  recommended: `derives_from` (becomes real lineage), `source_root`,
  `python_exe`, `seed`, `data_refs`.
- **`run_finalize` requires** `method`, `result` (`summary`, `verdict ∈
  confirmed | refuted | inconclusive`, headline `metrics` — or a
  `metrics_note` justifying their absence, plus optional `surprises`), and
  `reproduce` (the exact re-run invocation).
- **Refusals are data, not errors**: an incomplete finalize returns
  `{missing: [...], invalid: [...]}` — fix the listed fields and call again.
- **`run_fail` is for declared failures** (`what_failed`, optional
  `failure_class`, `why`, `traceback`). A failure is knowledge; don't
  abandon what you can explain.
- Runs that die silently are stamped **`abandoned`** by the janitor
  (`mlp janitor`), driven by heartbeat age (below).

## What gets captured automatically

At `run_start` (the launcher's view): the outer git state, an env lock for
`python_exe`, hardware (`captured_by: "start"`) — and, **only if you pass
`source_root`**, a snapshot of the code.

Code capture is deliberately explicit, because a snapshot copies file
contents into the store and, on a served store, on to everyone who can read
it:

- **No `source_root` → no code is captured.** ml-party never guesses which
  directory to copy.
- **In a git repo**, the snapshot is what git tracks plus untracked files
  that are not ignored — your `.gitignore` decides what belongs to the
  project.
- **Outside a git repo** there is no such boundary, so the capture is
  refused until you pass `confirm_snapshot=True`; the refusal carries the
  file list to review. The same applies to unusually large captures
  (`confirm_above_files` / `confirm_above_bytes` in `store.toml`).
- Secret-shaped filenames (`.env`, `*.pem`, `id_rsa*`, …) are never
  captured, even when tracked, and a root at or above your home directory
  is refused outright.
- `mlp snapshot-preview <dir>` (or the `snapshot_preview` MCP tool) shows
  exactly what would be captured before anything is written — add
  `--experiment` to see only what changed since the last snapshot.

Read the returned `snapshot_report` both ways: was anything important
excluded, and did anything land in it that should not be in the store?

At `attach()` (the compute host — the honest witness, which may be a
different machine): the **actual** invocation (argv/cwd/env),
**actual** hardware (`captured_by: "attach"`), and the **runtime env lock**
from `sys.executable`, stored content-addressed as `env_lock_runtime` on the
run. The env-lock capture runs in a background thread (pip freeze is slow);
`finalize()`/`fail()` wait for it, so completed runs always carry it.
Unhandled exceptions auto-fail the run with the traceback.

## Heartbeats

`attach()` touches a heartbeat every 15 s in a daemon thread. Tune or
disable with `ML_PARTY_HEARTBEAT=<seconds>` (env) or
`mlparty.attach(heartbeat_seconds=...)` (`0` disables; `capture_env=False`
skips the runtime env lock). Open runs with a fresh heartbeat show as
**live** in the UI (90 s window); with a stale one as **stale**; the janitor
only abandons runs whose heartbeat (and metrics file, and start time) are
older than the TTL.

## RunHandle API

```python
h = mlparty.attach()                      # or mlparty.start_run(...) agentless
h.log_metric(name, value, step=None)      # streams to the live view
h.log_artifact(path, media_type=None, note=None)   # → sha256 CAS
h.finalize(method=..., result={...}, reproduce=...)
h.fail(what_failed=..., failure_class=..., why=...)
```

CLI mirror: `mlp status / runs / show <ref> / tail <run> / query "…" /
diff <a> <b> / janitor / rebuild-index`.
