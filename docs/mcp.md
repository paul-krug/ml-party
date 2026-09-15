# MCP setup & tools

ml-party's agent surface is an MCP server. It is **self-teaching**: the full
tracking workflow (prior-art query → pre-register → env-handshake launch →
finalize → distill) ships as the server's MCP `instructions` and as a
`track_training` prompt — the server text is the canonical agent operating
manual; this page covers setup and the tool surface, and
[docs/tracking.md](tracking.md) explains the contract itself.

## Zero-terminal setup

```bash
mlp init --root .mlparty        # new store + MCP registration in ./.mcp.json
mlp connect --root <store>      # register an existing store in this project
mlp mcp-config --root <store>   # print the JSON snippet for other MCP clients
mlp serve-mcp --root <store>    # run the server by hand (stdio)
```

`mlp init` / `mlp connect` write (or merge into) the project's `.mcp.json`,
so any MCP-aware agent started in the project picks the server up after a
one-time approval. From there, "use ml-party to track this run" is all an
agent needs to hear. Note: `.mcp.json` carries absolute paths — keep it out
of git.

## Tools (17)

| Tool | Purpose |
| --- | --- |
| `project_ensure`, `experiment_ensure`, `experiment_list` | get-or-create hierarchy; an experiment answers **one question** |
| `run_start` | pre-register intent + auto-capture; returns `run_id`, `snapshot_report`, hints |
| `run_log_metric`, `run_log_artifact` | telemetry from the agent side (the training process usually streams instead — see tracking.md) |
| `experiment_log_artifact` | cross-run artifacts on the experiment — experiment-level boards, summary reports (see boards.md) |
| `action_list`, `action_invoke`, `action_register` | run control through registered templates — audited, typed, quoted (see actions.md) |
| `run_finalize`, `run_fail` | close the contract; refusals return as data |
| `note_create`, `node_annotate` | distilled knowledge; append-only corrections |
| `node_get`, `graph_query`, `run_diff` | retrieval: full nodes, hybrid ranked search, code/param/metric deltas |

Contract refusals come back as `{ok: false, refusal: {missing, invalid}}` —
repairable in one round-trip, never a protocol error.
