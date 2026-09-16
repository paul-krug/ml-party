# Run control (actions)

ml-party never becomes a scheduler — your trainings are started by your
scripts, slurm, k8s, whatever you already use. What it adds is the uniform,
**audited** interface agents (and humans) drive them through: you register
**action templates** — shell commands with typed placeholders — and from
then on those templates are the *only* commands invokable through ml-party.
Agents fill in parameter values; they never compose commands. Every value
is validated against its declared type and shell-quoted, and every
invocation lands in the knowledge graph: who invoked what, on which run,
with which parameters, and how it exited.

## Registering a template

```bash
mlp action register --file start-train.json
```

```json
{
  "name": "start-train",
  "description": "launch a tube-model training with the given learning rate",
  "command": "nohup python train.py --lr {lr} > train.log 2>&1 &",
  "cwd": "/home/me/project",
  "env": {"ML_PARTY_RUN": "{run}", "ML_PARTY_STORE": "{store_root}"},
  "params": {
    "lr":  {"type": "float", "help": "learning rate"},
    "run": {"type": "str", "help": "pre-registered run id (run_start first)"}
  }
}
```

Placeholders `{name}` must be declared in `params` (types: `str`, `int`,
`float`, `choice` with `choices`; optional `default`, `required: false`,
`help`). `{store_root}` is builtin. Values are shell-quoted into `command`;
`env` and `cwd` get raw substitution. `mlp action list` / `remove` manage
the set. Registration is a **local-surface** operation (CLI, or the MCP
tool on your own machine) — the HTTP server only lists and invokes.

## Invoking

```bash
mlp action invoke start-train -p lr=0.001 -p run=01M17...
```

Over MCP: `action_list` → `action_invoke(name, params)`. Over HTTP:
`GET /api/actions`, `POST /api/actions/invoke` — invocation is
**write-class** (writer role under auth, the ingest token otherwise, and
never from a sandboxed board).

The command runs on the host where the invoking surface lives, as that
process's user, under a small detached runner process — so it outlives the
caller, and the outcome is recorded even when the invoker was a one-shot
CLI or a server that restarted mid-action.
Invocation returns an **`action` node id** immediately; the node carries
the rendered command, parameters, and — once the process exits —
`exit_code` and the output tail (full log at `<store>/actions/<id>.log`).
Poll with `mlp show <id>` / `node_get`. If the params include `run`, the
node is edged `x-controls` to that run — the run page's graph shows every
control action ever taken on it.

## Restart is never a mutation

"Restart with lr halved" does **not** touch the old run:

1. `node_get` the old run for its config,
2. `run_start` a **new** run with `derives_from=[old]` and the changed
   parameters stated,
3. `action_invoke("start-train", {run: <new id>, lr: 0.0005})` — the
   template's `env` hands `ML_PARTY_RUN` to the training so it attaches to
   the right run.

The graph then answers, forever: which config ran, what changed, and why.
The MCP server teaches agents this choreography.

## Security model

- **Templates are the allowlist.** Registering one defines shell that runs
  on the host — a human decision. Parameters carry data, never commands:
  typed, validated, quoted.
- Invocation requires write access; boards (opaque origins) are rejected
  outright.
- Actions execute where the server/CLI runs. Remote execution on other
  compute hosts (a small runner installed there) is a planned later phase —
  templates will only ever execute where they were installed.
