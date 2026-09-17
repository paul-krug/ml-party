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
- **`run_set_compute` records where a run executes** when that is not this
  machine (below) — not part of the contract, but the difference between a
  remote job you can find again and one you cannot.
- **`run_fail` is for declared failures** (`what_failed`, optional
  `failure_class`, `why`, `traceback`). A failure is knowledge; don't
  abandon what you can explain.
- Runs that die silently are stamped **`abandoned`** by the janitor
  (`mlp janitor`), driven by heartbeat age (below).

## What gets captured automatically

At `run_start` (the launcher's view): the outer git state, an env lock for
`python_exe`, hardware (`captured_by: "start"`) — and, **only if you pass
`source_root`**, a snapshot of the code. Hardware capture is skipped entirely
when you declare remote compute *in the same call* (below): this machine's
specs are not that run's specs.

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

## Runs that execute somewhere else

If you submit the job to a cluster, a queue, or a cloud box instead of
starting it here, record **where it went** so the run stays a way back to
the job:

```python
party.run_set_compute(run_id, system="jobpool", job_id="4711",
                      url="https://jobs.internal/j/4711")
```

Same call over MCP (`run_set_compute`), or as `compute={...}` on
`run_start` when you already know. `system` / `job_id` / `url` / `host` /
`note` — at least one of the first three, and a `url` needs a scheme
(`https://…`, `ssh://…`) because it becomes a link in the web UI. Fields
given replace, fields omitted keep, so call it again as more becomes known:
usually the job id only exists *after* the submit command returns, which is
why this is a separate call from `run_start`.

The launcher can do it instead of you, over the same env handshake that
carries the run id — set these on the **job's** environment and `attach()`
records them from the compute host itself:

```
ML_PARTY_COMPUTE_SYSTEM=jobpool   ML_PARTY_COMPUTE_JOB_ID=4711
ML_PARTY_COMPUTE_URL=https://jobs.internal/j/4711
```

Two things this deliberately is **not**: ml-party neither submits the job
nor polls it, so `status` still comes from `run_finalize` / `run_fail` (or
the janitor), and the reference works for any job system, including one it
has never heard of. And it is unrelated to
[remote *tracking*](remote.md) — that ships a run's data to a store on
another machine, this records where the run's *compute* is. A remote run
usually wants both: the job needs `ML_PARTY_STORE` to reach a store, and
the store needs a way back to the job.

**Hardware depends on when you declare it.** Pass `compute` to `run_start`
and nothing is captured — the run carries no hardware until `attach()` records
the compute host's. Call `run_set_compute` *afterwards* and whatever
`run_start` already captured stays: it is this machine, labelled
`captured_by: "start"`, and the UI shows it as *(launcher's view)* until
`attach()` replaces it. Nothing is deleted after the fact, so a run that never
attaches keeps an honestly-labelled launcher reading rather than losing the
record. Either way, hardware tagged `"start"` on a remote run is the machine
that *submitted* the job, not the one that ran it.

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
