# Quickstart

Written for an agent working in someone's project. `help()` reports the
installed version, the store root you are serving, and the `mlp` commands
available — read that first; this page is the narrative.

## Is there anything to look at yet?

`workflow_guide()` reports the store root and how many projects, experiments
and runs it holds. An empty store means nothing has been tracked here yet.

## Run the demo

A real tracked run — pre-registration, streaming metrics, finalize with a
verdict — that takes about 30 seconds and leaves a run to look at:

```bash
python -m mlparty.demo
```

Use **the interpreter ml-party is installed into**. If the user installed into
a project venv, that is `.venv/bin/python`, not the system `python`.

It writes to `$ML_PARTY_STORE`, falling back to `./.mlparty` in the current
directory. **Check which store it used**: if `ML_PARTY_STORE` is not exported
in the shell you run it from, the demo creates a *new* store where you are
standing rather than adding to the one the user watches. Pass `--store
<root>` to be certain, and tell the user which store the run landed in.

## Watch it live

```bash
mlp ui                      # → http://127.0.0.1:7327
```

Serves the store's web UI: live metric streams, artifacts, lineage, search,
run comparison. See [ui.md](ui.md).

## Track a real run

That is the contract, not a command — `workflow_guide()` is the manual:
query prior art, pre-register intent with `run_start` before launching, let
the training stream its own metrics, then `run_finalize` with a verdict.
[tracking.md](tracking.md) explains the two-writer design and how to
instrument a training script with `mlparty.attach()`.

## Inspect a store from the shell

```bash
mlp status                  # store summary
mlp runs                    # recent runs
mlp show <run-id>           # one node in full
mlp tail <run-id>           # follow a running job's metrics
mlp query "<text>"          # search the knowledge graph
```

`help()` lists every command with its help text, generated from the CLI
itself, so it cannot drift from what is installed.
