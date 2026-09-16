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

**If the server does not show up**, it is almost always one of two things:

1. **The agent was started somewhere else.** A project-scoped `.mcp.json` is
   read from the directory the agent starts in — not the directory you ran
   `mlp init` in, if those differ. `cd` to the directory holding `.mcp.json`
   and start the agent there.
2. **The approval prompt was never answered.** Project MCP servers need a
   one-time approval; until then the server stays inactive.

Verify with `/mcp` inside Claude Code (it lists active servers), or
`claude mcp list` from the shell. To register the store for an agent that
runs elsewhere, use `mlp connect --project <that directory>`, or paste the
`mlp mcp-config` snippet into that client's own configuration.

## Tools (18)

| Tool | Purpose |
| --- | --- |
| `project_ensure`, `experiment_ensure`, `experiment_list` | get-or-create hierarchy; an experiment answers **one question** |
| `run_start` | pre-register intent + auto-capture; returns `run_id`, `snapshot_report`, hints |
| `snapshot_preview` | what a code snapshot of a directory would capture, and the delta vs the last one — before anything is written |
| `run_log_metric`, `run_log_artifact` | telemetry from the agent side (the training process usually streams instead — see tracking.md) |
| `experiment_log_artifact` | cross-run artifacts on the experiment — experiment-level boards, summary reports (see boards.md) |
| `action_list`, `action_invoke`, `action_register` | run control through registered templates — audited, typed, quoted (see actions.md) |
| `run_finalize`, `run_fail` | close the contract; refusals return as data |
| `note_create`, `node_annotate` | distilled knowledge; append-only corrections |
| `node_get`, `graph_query`, `run_diff` | retrieval: full nodes, hybrid ranked search, code/param/metric deltas |

Contract refusals come back as `{ok: false, refusal: {missing, invalid}}` —
repairable in one round-trip, never a protocol error.

## Code capture is asked for, never assumed

The server's instructions tell agents to **ask you which directory holds the
code** before the first run they track, rather than picking one. That
directory is `source_root`, and it is the only thing that gets snapshotted:

- The agent calls `snapshot_preview` and shows you the file list **before**
  anything is written.
- Files your `.gitignore` excludes are never captured — that is the lever
  for keeping something out, and it is one you already use.
- No `source_root` at all means the run records no code. Nothing is ever
  captured silently.
- Outside a git repo, or for an unusually large capture, `run_start` refuses
  until the agent has shown you the list and you agree (`confirm_snapshot`).
  Agents are instructed never to set that flag on their own.

Once you have settled on a directory, later runs from it need no new
permission; the preview's delta reports what changed.
