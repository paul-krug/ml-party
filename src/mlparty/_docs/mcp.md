# MCP setup & tools

ml-party's agent surface is an MCP server. It is **self-teaching**: the full
tracking workflow (orient → prior-art query → pre-register → env-handshake
launch → finalize → distill) is the canonical agent operating manual, served
by the `workflow_guide` tool. This page covers setup and the tool surface, and
[tracking.md](tracking.md) explains the contract itself.

Everything *else* about the package is served by the `help` tool: these guides
ship inside the wheel, so an agent that only ever ran `pip install mlparty` can
read them without a checkout or a browser. `help()` bare returns the topic
index plus every `mlp` command, the installed version, and the store root;
`help(topic)` returns a guide in full. The MCP surface is an agent's whole view
of ml-party, so anything it cannot pull from there, it does not know.

## How the workflow reaches the agent

Three channels exist and only one of them is reliable, which is why the manual
lives where it does:

| Channel | Reaches the agent? |
| --- | --- |
| `workflow_guide` / `help` **tools** | **Yes** — the manual and every guide, pulled on the agent's own initiative. Clients may defer tool *schemas*, but names stay visible. |
| **Tool responses** | **Yes, unconditionally** — every response carries a nudge to call `workflow_guide()` until it has been called. Nothing truncates or drops a response, so this is the backstop. |
| MCP `instructions` | Not guaranteed. Clients cap it (Claude Code at exactly 2048 chars, mid-word, silently) and **may drop it outright** — the spec calls it a hint clients *MAY* use. Kept short: a summary whose first line is *call `workflow_guide()`*. |
| `track_training` **prompt** | Only if you invoke it — prompts are user-triggered slash commands, so an agent cannot reach for one. |

So the connection text is a router, not the manual, and a test pins it under
budget. If you are writing an MCP server with a workflow to teach, this is the
trap: a long `instructions` string looks delivered and is not. The spec calls
the field *"a hint... MAY be added to the system prompt"* — a client may cap it
or ignore it outright and still be conformant, and capping is sound, since
server instructions are untrusted text entering the system prompt. Note the cap
applies **per tool description** too.

## One store, or one per project?

Decide this first: it shapes everything else. **A store is a notebook, not a
per-repo file.** It holds `project → experiment → run`, and retrieval spans
the whole store — so one store covering all your work lets an agent answer
*"what did I try for the vocoder last spring?"* from inside any project. A
store per repository splits that into islands which cannot see each other,
and makes the `project` node type pointless.

**The default: one personal store, registered globally.**

```bash
pip install mlparty
mlp init --root ~/.mlparty --no-mcp
export ML_PARTY_STORE=~/.mlparty      # so the `mlp` CLI finds it anywhere
```

`--no-mcp` is deliberate: it skips writing a `.mcp.json` into whatever
directory you happen to be standing in, because this store is registered
globally instead (next section). Each codebase you work in then becomes a
`project` inside that one graph, and the working directory stops mattering.

**A store per project** is right in three cases, and only those: the
notebook should travel with the repository; a team shares a served store for
one project; or a project's data must stay physically separate (different
disk, different backup policy, different machine).

```bash
cd /path/to/your/project
mlp init --root .mlparty        # store + ./.mcp.json, both here
```

The trade-off is that queries only ever see this project, and you repeat the
setup per repository. If you later want them joined, a spool store can flush
into a served one ({doc}`remote`) — but two local stores do not merge.

Mixed setups are fine: keep the personal store global, and register a
project-local store for the one repository that needs it with
`mlp connect --root <that store> --project <dir>`.

## Zero-terminal setup

```bash
mlp init --root .mlparty        # new store + MCP registration in ./.mcp.json
mlp connect --root <store>      # register an existing store in this project
mlp mcp-config --root <store>   # print the JSON snippet for other MCP clients
mlp serve-mcp --root <store>    # run the server by hand (stdio)
```

`mlp init` / `mlp connect` write (or merge into) the project's `.mcp.json` —
the project-scoped convention Claude Code and compatible clients read — so
an agent started in that directory picks the server up after a one-time
approval. From there, "use ml-party to track this run" is all an agent needs
to hear. Note: `.mcp.json` carries absolute paths — keep it out of git.

**Any other MCP client** works the same way through its own configuration:
`mlp mcp-config --root <store>` prints a standard `mcpServers` entry to
paste (Cursor's `.cursor/mcp.json`, and so on — a few clients use a
different top-level key, so check yours). Registering the store **globally**
rather than per-project is usually what you want: one store holds many
projects, and a global registration means it is there in every session
regardless of the directory.

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

## Tools (20)

| Tool | Purpose |
| --- | --- |
| `workflow_guide` | the full operating manual, plus which store you are serving and what is in it — an agent's first call |
| `help` | the package's own documentation — bare for the index (topics, every `mlp` command, version, store root, where to report a bug), or `help(topic)` for a guide in full |
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

The workflow guide tells agents to **ask you which directory holds the code**
before the first run they track, rather than picking one. That
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
