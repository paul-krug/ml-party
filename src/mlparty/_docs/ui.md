# The web UI

```bash
mlp ui --root <store>        # serves on 127.0.0.1:7327
```

Localhost-bound by design; from another machine, tunnel like TensorBoard:
`ssh -L 7327:localhost:7327 <box>`. Read-only except append-only
annotations. On a served store with users configured ({doc}`deploy`), the
UI shows a sign-in page first; annotations are then authored as the
signed-in user (writer role required), and the top bar carries your
username and a sign-out link. Pages: **Experiments** (landing, run aggregates) →
**experiment** (runs table, boards, experiment artifacts) → **run** (tabs:
Overview | Metrics | Artifacts | Code), plus **Boards** (the gallery of all
agent-authored boards — see {doc}`boards`), Graph (lineage DAG), Search,
and Diff.

**Timestamps are UTC by default and always carry their zone** — a store can be
served to people in several zones, and an unlabelled local time makes two
viewers read the same run differently. The `UTC` button in the top bar switches
every timestamp to your own zone (and back); the choice is remembered in the
browser, per viewer. Runs are *stored* in UTC either way, so the switch only
changes what you read.

Open runs show a liveness chip driven by the client's heartbeat: a pulsing
**open · live** while the training process is breathing, **open · stale**
(hover for the last-seen time) when it stopped, plain **open** for runs with
no liveness data.

## The metrics dashboard

The run page's Metrics tab is a configurable dashboard, **stateful per run**:
layout, series selection, chart types, toggles, and zoom are stored in your
browser (localStorage) and restored whenever you come back to the run.

- **Default layout**: one panel per logged metric, in a 1/2/3-column grid
  (columns switcher in the top bar). New metric names appearing mid-run get
  a panel automatically until you start curating the layout — after that
  they're listed as *unplotted* instead of disturbing it. **reset layout**
  regenerates the default.
- **Stat strip**: big-number tiles above the grid with the latest value per
  metric (plus a step tile and a subtle trend arrow), updating live —
  at-a-glance training status. Toggle with **stats**.
- **Panels**: drag the `⠿` handle to reorder (drop target highlights),
  `⛶` for full width, `✕` to remove, editable title, and a footer with
  `last / min / max` per series.
- **Panel editor (`⚙`)**: choose any set of series for the panel; chart type
  **line / scatter / bar**; x-axis = **step**, **wall time**, **elapsed**,
  or **another metric** (series joined on step — plot anything vs anything,
  e.g. `val_loss` vs `lr`); log-y; EMA smoothing; and exact numeric min/max
  for both axes.
- **Zoom**: drag a rectangle on any plot (the selection is visualized) to
  zoom both axes; double-click or `⟲` restores. Zoom is per-panel. On a
  live run, a zoomed panel's axes are **pinned** — streaming data keeps
  arriving but never resets your view; un-zoomed panels keep following new
  data.
- **Crosshair sync**: hovering one panel shows the cursor on every panel
  with the same x-axis, with per-panel value readouts.
- **Export**: per panel, **png** (the rendered plot) and **csv** (the
  panel's series, always full resolution). **Left-click downloads;
  right-click copies to the clipboard** (the image itself for png, the
  values as text for csv) — paste straight into a chat, doc, or sheet.

### Decimation (automatic)

Series above ~4k visible points render as a **min/max envelope** (~2k
buckets, ≈2 points per pixel): every bucket keeps its minimum *and*
maximum, so rare spikes always survive — a fixed-rate subsample would
silently drop them. It re-resolves on zoom: decimation runs over the
visible x-range, so zooming into any region recovers full detail
automatically. There is deliberately no rate knob — the correct bucket
count is a function of plot width, not preference. Stats and CSV export
always use the full-resolution data; a footer note ("envelope of N pts")
marks when a panel is rendering the envelope.

## The artifacts tab

Finder-style view controls on two levels, both remembered:

- **Page-wide**: `▤ groups` (default — artifacts grouped by media type:
  images, audio, video, tensors, checkpoints, text, other; grouping uses
  the logged `media_type`, falling back to the file extension) or
  `☰ list` (one flat table).
- **Per group**: `⊞ grid` (default — content-first tiles: image groups show
  actual thumbnails, videos their first frame, everything else an icon
  tile) or `☰` detail rows.

Clicking an artifact — tile or row — opens an **inspector pane on the
right** (the gallery stays visible beside it; it stacks below on narrow
windows):

- **Images** render inline; **audio** and **video** get players.
- **Text/CSV/JSON** files show a (truncated) text preview.
- **Tensors** (`.npy`, and `.npz` member-by-member) open the tensor viewer:
  slide through the leading axes with per-axis faders (the plot scrubs
  live) and view the remaining axes as a **line plot** (last axis) or
  **heatmap** (last two, viridis-colored). The **normed** checkbox (default
  on) fixes the color scale / y-axis to the whole tensor's min/max so the
  range stays constant while sliding; off, each slice auto-scales. The
  whole-tensor range is scanned exactly below 32 MiB and estimated from an
  even sample above (marked ≈sampled).
  Reading is pure-Python on the server (no numpy/torch dependency), seeks
  directly to the requested slice, and strides large slices down to display
  resolution — a multi-GB array is never loaded whole. Plain numeric
  C-order arrays only; `.npz` members larger than 32 MiB can't be sliced
  (zip entries aren't seekable).
- **Checkpoints** (`.pt`, `.ckpt`, `.safetensors`) are download-only:
  loading them requires the training framework (and unpickling untrusted
  checkpoints server-side would be unsafe). Prefer logging inspection
  tensors as `.npy`/`.npz` alongside the checkpoint.

## Live streaming

Open runs stream metrics over SSE (`/api/runs/<id>/metrics/stream`); the
dashboard batches updates (250 ms) and the stream ends itself when the run
leaves `open`.
