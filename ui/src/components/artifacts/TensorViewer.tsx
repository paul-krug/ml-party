import { useEffect, useRef, useState } from "react";
import uPlot from "uplot";
import { TensorMeta, TensorRange, TensorSlice, api } from "../../api";
import { fmt } from "../dashboard/dash";

// compact viridis approximation (t ∈ [0,1] → rgb)
const STOPS: [number, number, number][] = [
  [68, 1, 84], [59, 82, 139], [33, 145, 140], [94, 201, 98], [253, 231, 37],
];
function viridis(t: number): [number, number, number] {
  const x = Math.max(0, Math.min(1, t)) * (STOPS.length - 1);
  const i = Math.min(STOPS.length - 2, Math.floor(x));
  const f = x - i;
  return [0, 1, 2].map((c) => Math.round(STOPS[i][c] + f * (STOPS[i + 1][c] - STOPS[i][c]))) as
    [number, number, number];
}

function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function Heatmap({ sl, fixedRange }: { sl: TensorSlice; fixedRange?: [number, number] }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const el = canvas.current;
    if (!el) return;
    const rows = sl.values as number[][];
    const h = rows.length, w = rows[0]?.length ?? 0;
    if (!h || !w) return;
    el.width = w;
    el.height = h;
    const ctx = el.getContext("2d")!;
    const img = ctx.createImageData(w, h);
    const lo = fixedRange?.[0] ?? sl.min ?? 0, hi = fixedRange?.[1] ?? sl.max ?? 1;
    const span = hi - lo || 1;
    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) {
        const v = rows[y][x];
        const o = (y * w + x) * 4;
        if (v == null || Number.isNaN(v)) {
          img.data[o] = img.data[o + 1] = img.data[o + 2] = 128;
          img.data[o + 3] = 60;
        } else {
          const [r, g, b] = viridis((v - lo) / span);
          img.data[o] = r; img.data[o + 1] = g; img.data[o + 2] = b;
          img.data[o + 3] = 255;
        }
      }
    }
    ctx.putImageData(img, 0, 0);
  }, [sl, fixedRange]);
  return (
    <div>
      <canvas ref={canvas} style={{
        width: "100%", maxWidth: 640, imageRendering: "pixelated",
        border: "1px solid var(--border)", borderRadius: 6,
      }} />
      <div className="muted small">
        {(sl.values as number[][]).length}×{(sl.values as number[][])[0]?.length} shown
        {(sl.steps[0] > 1 || sl.steps[1] > 1) && ` (strided ${sl.steps.join("×")})`}
        {" · "}
        {fixedRange
          ? <>scale {fmt(fixedRange[0])} (dark) → {fmt(fixedRange[1])} (bright) · slice min {fmt(sl.min)} · max {fmt(sl.max)}</>
          : <>min {fmt(sl.min)} (dark) → max {fmt(sl.max)} (bright)</>}
      </div>
    </div>
  );
}

function LinePlot({ sl, step0, fixedRange }: {
  sl: TensorSlice; step0: number; fixedRange?: [number, number];
}) {
  const holder = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = holder.current;
    if (!el) return;
    const ys = sl.values as number[];
    const xs = ys.map((_, i) => i * step0);
    const axisStyle = {
      stroke: cssVar("--muted"),
      grid: { stroke: cssVar("--grid"), width: 1 },
      ticks: { stroke: cssVar("--grid"), width: 1 },
    };
    const u = new uPlot({
      width: Math.min(el.clientWidth || 640, 900),
      height: 220,
      scales: {
        x: { time: false },
        y: fixedRange ? { range: () => fixedRange } : {},
      },
      axes: [{ label: "index", ...axisStyle }, { ...axisStyle }],
      series: [{ label: "index" },
               { label: "value", stroke: cssVar("--series-1"), width: 2, points: { show: false } }],
    }, [xs, ys], el);
    return () => u.destroy();
  }, [sl, step0, fixedRange]);
  return (
    <div>
      <div ref={holder} />
      <div className="muted small">
        {(sl.values as number[]).length} points{sl.steps[0] > 1 && ` (strided ×${sl.steps[0]})`}
        {" · "}min {fmt(sl.min)} · max {fmt(sl.max)}
      </div>
    </div>
  );
}

export default function TensorViewer({ sha256 }: { sha256: string }) {
  const [meta, setMeta] = useState<TensorMeta | null>(null);
  const [member, setMember] = useState<string | null>(null);
  const [mode, setMode] = useState<"line" | "heatmap">("heatmap");
  const [prefix, setPrefix] = useState<number[]>([]);
  const [sl, setSl] = useState<TensorSlice | null>(null);
  const [err, setErr] = useState("");
  const [normed, setNormed] = useState(true);
  const [range, setRange] = useState<TensorRange | null>(null);
  const [rangeErr, setRangeErr] = useState("");

  // top-level meta (npz → member list, npy → shape)
  useEffect(() => {
    setMeta(null); setMember(null); setSl(null); setErr("");
    api.tensorMeta(sha256)
      .then((m) => {
        if (m.kind === "npz") {
          if (m.members?.length) setMember(m.members[0]);
          setMeta(m);
        } else {
          setMeta(m);
        }
      })
      .catch((e) => setErr(String(e)));
  }, [sha256]);

  // member meta for npz
  const [shape, setShape] = useState<number[] | null>(null);
  const [dtype, setDtype] = useState("");
  useEffect(() => {
    if (!meta) return;
    if (meta.kind === "npy") {
      setShape(meta.shape ?? null);
      setDtype(meta.dtype ?? "");
      return;
    }
    if (!member) return;
    setShape(null); setSl(null); setErr("");
    api.tensorMeta(sha256, member)
      .then((m) => { setShape(m.shape ?? null); setDtype(m.dtype ?? ""); })
      .catch((e) => setErr(String(e)));
  }, [meta, member, sha256]);

  // default mode when a new tensor's shape arrives
  useEffect(() => {
    if (!shape) return;
    setMode(shape.length >= 2 ? "heatmap" : "line");
  }, [shape]);

  // whole-tensor range for the fixed ("normed") scale — fetched lazily
  useEffect(() => {
    setRange(null);
    setRangeErr("");
    if (!normed || !shape) return;
    api.tensorRange(sha256, member ?? undefined)
      .then(setRange)
      .catch((e) => { setRangeErr(String(e)); setNormed(false); });
  }, [normed, shape, sha256, member]);

  const fixedRange: [number, number] | undefined =
    normed && range && range.min != null && range.max != null
      ? [range.min, range.max === range.min ? range.min + 1 : range.max]
      : undefined;

  // keep the axis pickers in sync with the mode: line fixes one more
  // leading axis than heatmap — reuse existing indices, new axes start at 0
  useEffect(() => {
    if (!shape) return;
    const n = Math.max(0, shape.length - (mode === "heatmap" ? 2 : 1));
    setPrefix((p) => {
      if (p.length === n) return p;
      const next = p.slice(0, n);
      while (next.length < n) next.push(0);
      return next;
    });
  }, [shape, mode]);

  // fetch the slice; keep the previous frame while loading (smooth scrubbing)
  // and drop out-of-order responses
  const seq = useRef(0);
  useEffect(() => {
    if (!shape) return;
    const free = mode === "heatmap" ? 2 : 1;
    if (prefix.length !== Math.max(0, shape.length - free)) return;
    setErr("");
    const mySeq = ++seq.current;
    api.tensorSlice(sha256, prefix, member ?? undefined)
      .then((s) => { if (seq.current === mySeq) setSl(s); })
      .catch((e) => { if (seq.current === mySeq) { setSl(null); setErr(String(e)); } });
  }, [shape, mode, prefix, sha256, member]);

  if (err) return <div className="muted small">tensor viewer: {err}</div>;
  if (!meta || !shape) return <div className="muted small">reading tensor header…</div>;

  const free = mode === "heatmap" ? 2 : 1;
  const nFixed = Math.max(0, shape.length - free);

  return (
    <div>
      <div className="setrow" style={{ marginBottom: 8 }}>
        {meta.kind === "npz" && (
          <>
            <span className="setlabel">member</span>
            <select value={member ?? ""} onChange={(e) => setMember(e.target.value)}>
              {meta.members?.map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          </>
        )}
        <span className="setlabel">shape</span>
        <span className="idmono">({shape.join(", ")})</span>
        <span className="setlabel">{dtype}</span>
        {shape.length >= 2 && (
          <>
            <span className="setlabel">view</span>
            <select value={mode} onChange={(e) => setMode(e.target.value as "line" | "heatmap")}>
              <option value="heatmap">heatmap (last 2 axes)</option>
              <option value="line">line (last axis)</option>
            </select>
          </>
        )}
        <label title="on: color scale / y-axis fixed to the whole tensor's min/max, so ranges stay constant while sliding · off: each slice auto-scales">
          <input type="checkbox" checked={normed}
                 onChange={(e) => setNormed(e.target.checked)} /> normed
        </label>
        {normed && !range && !rangeErr && <span className="muted small">scanning range…</span>}
        {normed && range && !range.exact && (
          <span className="muted small"
                title="tensor too large for a full scan — range estimated from an even sample">
            ≈sampled
          </span>
        )}
        {rangeErr && <span className="muted small">range unavailable — per-slice scaling</span>}
      </div>
      {nFixed > 0 && (
        <div className="axisrows">
          {Array.from({ length: nFixed }, (_, i) => {
            const setAxis = (raw: number) => {
              const v = Math.max(0, Math.min(shape[i] - 1, raw || 0));
              setPrefix((p) => p.map((x, j) => (j === i ? v : x)));
            };
            return (
              <div className="axisrow" key={i}>
                <span className="setlabel axislabel">axis {i}</span>
                <input
                  type="range" min={0} max={shape[i] - 1} step={1}
                  value={prefix[i] ?? 0}
                  disabled={shape[i] < 2}
                  onChange={(e) => setAxis(Number(e.target.value))}
                />
                <input
                  className="rangeinput axisnum"
                  type="number" min={0} max={shape[i] - 1}
                  value={prefix[i] ?? 0}
                  onChange={(e) => setAxis(Number(e.target.value))}
                />
                <span className="muted small axismax">/ {shape[i] - 1}</span>
              </div>
            );
          })}
        </div>
      )}
      {!sl && <div className="muted small">loading slice…</div>}
      {sl && sl.shape.length === 2 && <Heatmap sl={sl} fixedRange={fixedRange} />}
      {sl && sl.shape.length === 1 && (
        <LinePlot sl={sl} step0={sl.steps[0]} fixedRange={fixedRange} />
      )}
    </div>
  );
}
