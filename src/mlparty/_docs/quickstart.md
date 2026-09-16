# Quickstart

Run the demo, watch it live, and inspect a store — the commands for the things
people ask for first. Written for an agent working in someone's project;
`help()` reports the installed version, the store root you are serving, and
every `mlp` command.

## Run everything from the INSTALLED package

You are talking to an installed ml-party. Run its commands — `mlp demo`,
`mlp ui` — and ignore any ml-party checkout you find on disk. **A checkout is
not the package**: it may be an older release, an unmerged branch, a fork, or a
renamed predecessor, and nothing about it looks wrong from the outside. Running
`scripts/…` out of one is how you end up executing code that has nothing to do
with the version the user installed. If `mlp` is not on PATH, use the
interpreter ml-party is installed into (`.venv/bin/mlp`, or
`.venv/bin/python -m mlparty.demo`).

## Is there anything to look at yet?

`workflow_guide()` reports the store root and how many projects, experiments
and runs it holds. An empty store means nothing has been tracked here yet.

## Run the demo

A real tracked run — pre-registration, streaming metrics, finalize with a
verdict — that takes about 30 seconds and leaves a run to look at:

```bash
mlp demo                      # or: python -m mlparty.demo
```

It writes to `$ML_PARTY_STORE`, falling back to `./.mlparty` in the current
directory, and prints the store root it chose. **Check that root**: if
`ML_PARTY_STORE` is not exported in the shell you run it from, the demo creates
a *new* store where you are standing rather than adding to the one the user
watches. Pass `--root <store>` to be certain, and tell the user where the run
landed.

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
