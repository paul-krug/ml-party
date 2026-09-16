# Boards

A **board** is a custom HTML page written by an agent (or you) and stored as
an artifact: a results report, a demo gallery with audio/images, a
comparison dashboard, a notebook-style writeup — anything a page can be.
Boards are not screenshots: a board can **fetch the read-only API at view
time**, so it renders current data whenever it's opened.

## Creating one

No special command — a board is an HTML artifact on a run or an experiment:

```python
h.log_artifact("report.html", media_type="text/html", note="Ablation report")
# over MCP: run_log_artifact(run, path, media_type="text/html", note=...)
# cross-run views hang on the experiment instead:
#          experiment_log_artifact(experiment, path, media_type="text/html", note=...)
```

Run boards are one-run views; experiment boards are the home for cross-run
comparisons and summaries that outlive any single run. Either way the web UI
renders the board full-page at `#/board/<sha256>` (bookmarkable) and lists
it in the **board gallery** — the Boards page in the sidebar, the Boards
section of the owning experiment, and the boards group of the run's
Artifacts tab. Boards are content-addressed and immutable — updating one
means logging a new version; old versions stay addressable forever.

**Give it a title.** The gallery names a board by its `note`, falling back
to the HTML `<title>`, then the filename — pass `note="<human title>"` when
logging. Boards are also searchable: the title/filename is indexed into the
owning node's search text, so `graph_query("ablation board")` surfaces the
run or experiment that carries it.

## The board contract

A board renders inside a sandboxed iframe with a strict CSP: it gets its
own opaque origin, read-only API access, and **no network beyond this
host**. Write within these rules:

1. **Self-contained.** Inline all CSS and JS. External hosts (CDN scripts,
   fonts, trackers) are CSP-blocked — a reference to one simply won't load.
   This is also the durability rule: a board must render unchanged years
   later. The one loadable script is the host's own optional helper:

   ```html
   <script src="/boards-lib/mlparty.js"></script>
   ```

   which defines `window.mlparty` — `node(ref)`, `metrics(runId, {name})`,
   `query(q, {type, limit})`, `boards({experiment_id})`,
   `artifactUrl(sha, mediaType)`, and `stream(runId, onRecord, onEnd)` for
   SSE live-tailing (returns a stop function). It is served by the same
   host (never a CDN), so it passes the CSP and keeps boards durable.
2. **Reference store content by address.** Other artifacts embed via the
   inline endpoint:
   ```html
   <img src="/api/artifacts/<sha256>?inline=true&media_type=image/png">
   <audio controls src="/api/artifacts/<sha256>?inline=true&media_type=audio/wav">
   ```
3. **Fetch live data from the read-only API.**
   `/api/nodes/<id>`, `/api/runs/<id>/metrics`, `/api/query?q=…`, the SSE
   stream `/api/runs/<id>/metrics/stream` — all reachable via `fetch()` /
   `EventSource` from inside the sandbox. This is what makes a board a live
   view instead of a frozen export.
4. **Read-only by construction.** Write endpoints reject requests from the
   sandbox. Don't design a board that wants to write; that's what the agent
   itself is for.

## Boards under authentication

On a login-gated server ({doc}`deploy`), the sandbox's opaque origin
carries no session cookie — so the UI hands the board iframe a
**short-lived read-only token** via `?bt=` in its URL. The helper attaches
it to every request automatically; if you build URLs by hand (e.g. a bare
`<img src="/api/artifacts/…">`), read it from `location.search` and append
it, or use `mlparty.artifactUrl(...)`, which does. The token can only
read: writes and minting further tokens are rejected.

## Security model

Boards are data, never trusted UI. Enforcement is server-side and applies
even when a board URL is opened directly: the response carries
`Content-Security-Policy: sandbox allow-scripts; … connect-src 'self'`, so
the page always runs in an opaque origin, cannot read the viewer UI's
storage, cannot reach external hosts, and cannot write to the store.
Relatedly, `/api/artifacts` inline rendering is safelisted to media types
that can't execute (images, audio, video, plain text) — HTML renders *only*
through the sandboxed `/boards/<sha256>` route.

## Boards and the knowledge graph

Boards deliberately do **not** become graph nodes and get no `produces`
edges: a board's provenance is already fully expressed by containment — it
sits in the `artifacts` list of the run or experiment that produced it.
Discovery goes through the gallery (`/api/boards`) and through search (the
board's title/filename is indexed into the carrying node's search text).
This keeps the graph spine reserved for knowledge claims and lineage.
