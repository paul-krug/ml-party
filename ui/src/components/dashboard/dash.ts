import type uPlot from "uplot";
import { MetricRec } from "../../api";

export type ChartType = "line" | "scatter" | "bar";
export type XAxisKind = "step" | "time" | "reltime" | "metric";

export interface XAxis {
  kind: XAxisKind;
  metric?: string; // when kind === "metric"
}

export type Range = [number | null, number | null] | null;

export interface PanelConfig {
  id: string;
  title: string;
  series: string[];
  chartType: ChartType;
  xAxis: XAxis;
  logY: boolean;
  smooth: boolean;
  xRange: Range;
  yRange: Range;
  wide: boolean;
}

export interface DashConfig {
  v: 1;
  columns: 1 | 2 | 3;
  auto: boolean; // append a default panel when a new metric name appears
  stats?: boolean; // big-number strip at the top (default on)
  panels: PanelConfig[];
}

export function fmt(v: number | null): string {
  if (v == null || Number.isNaN(v)) return "—";
  if (v !== 0 && (Math.abs(v) < 1e-3 || Math.abs(v) >= 1e6)) return v.toExponential(3);
  return String(Math.round(v * 1e5) / 1e5);
}

let seq = 0;
export function panelId(): string {
  return `p${Date.now().toString(36)}${(seq++).toString(36)}`;
}

export function defaultPanel(name: string): PanelConfig {
  return {
    id: panelId(), title: name, series: [name], chartType: "line",
    xAxis: { kind: "step" }, logY: false, smooth: false,
    xRange: null, yRange: null, wide: false,
  };
}

export function defaultConfig(names: string[]): DashConfig {
  return { v: 1, columns: 2, auto: true, panels: names.map(defaultPanel) };
}

const KEY = (runId: string) => `mlp.dash.${runId}`;

export function loadConfig(runId: string): DashConfig | null {
  try {
    const raw = localStorage.getItem(KEY(runId));
    if (!raw) return null;
    const cfg = JSON.parse(raw) as DashConfig;
    return cfg?.v === 1 && Array.isArray(cfg.panels) ? cfg : null;
  } catch {
    return null;
  }
}

export function saveConfig(runId: string, cfg: DashConfig): void {
  try {
    localStorage.setItem(KEY(runId), JSON.stringify(cfg));
  } catch {
    /* storage full/unavailable — dashboard still works, just not remembered */
  }
}

// ------------------------------------------------------------- series building

interface Point { step: number; ts: number; value: number }

function group(records: MetricRec[]): Map<string, Point[]> {
  const by = new Map<string, Point[]>();
  for (const r of records) {
    let pts = by.get(r.name);
    if (!pts) by.set(r.name, (pts = []));
    pts.push({
      step: r.step ?? pts.length,
      ts: Date.parse(r.ts) / 1000,
      value: r.value,
    });
  }
  return by;
}

function ema(col: (number | null)[], alpha: number): (number | null)[] {
  let acc: number | null = null;
  return col.map((v) => {
    if (v == null) return acc;
    acc = acc == null ? v : alpha * acc + (1 - alpha) * v;
    return acc;
  });
}

export interface PanelData {
  data: uPlot.AlignedData;
  labels: string[];
  xLabel: string;
  isTime: boolean;
}

/** Align the panel's series into uPlot columns for the configured x-axis. */
export function buildPanelData(records: MetricRec[], cfg: PanelConfig): PanelData | null {
  const by = group(records);
  const labels = cfg.series.filter((n) => by.has(n));
  if (!labels.length) return null;

  const ax = cfg.xAxis;
  let xLabel = "step";
  let isTime = false;
  let xOf: (p: Point) => number | null;

  if (ax.kind === "time") {
    xLabel = "time";
    isTime = true;
    xOf = (p) => p.ts;
  } else if (ax.kind === "reltime") {
    xLabel = "elapsed (s)";
    let t0 = Infinity;
    for (const n of labels) for (const p of by.get(n)!) t0 = Math.min(t0, p.ts);
    xOf = (p) => p.ts - t0;
  } else if (ax.kind === "metric" && ax.metric) {
    xLabel = ax.metric;
    const xm = new Map<number, number>();
    for (const p of by.get(ax.metric) ?? []) xm.set(p.step, p.value);
    xOf = (p) => xm.get(p.step) ?? null;
  } else {
    xOf = (p) => p.step;
  }

  // per-series (x → y), then union of x's
  const maps = labels.map((n) => {
    const m = new Map<number, number>();
    for (const p of by.get(n)!) {
      const x = xOf(p);
      if (x != null && Number.isFinite(x)) m.set(x, p.value);
    }
    return m;
  });
  const xs = [...new Set(maps.flatMap((m) => [...m.keys()]))].sort((a, b) => a - b);
  if (!xs.length) return null;

  let cols = maps.map((m) => xs.map((x) => m.get(x) ?? null));
  if (cfg.smooth && cfg.chartType === "line") cols = cols.map((c) => ema(c, 0.9));
  if (cfg.logY) cols = cols.map((c) => c.map((v) => (v != null && v > 0 ? v : null)));

  return { data: [xs, ...cols] as uPlot.AlignedData, labels, xLabel, isTime };
}

// ------------------------------------------------------------- decimation

const DECIMATE_ABOVE = 4000; // points; below this uPlot just draws everything
const TARGET_BUCKETS = 2000; // ≈ 2 points per px on a wide plot

function sliceToRange(data: uPlot.AlignedData, xRange: Range): uPlot.AlignedData {
  if (!xRange) return data;
  const xs = data[0] as number[];
  const lo = xRange[0] ?? -Infinity;
  const hi = xRange[1] ?? Infinity;
  let a = xs.findIndex((x) => x >= lo);
  if (a < 0) a = xs.length;
  let b = xs.length;
  while (b > 0 && xs[b - 1] > hi) b--;
  a = Math.max(0, a - 1); // one point of margin so lines run off-screen
  b = Math.min(xs.length, b + 1);
  return data.map((col) => (col as (number | null)[]).slice(a, b)) as uPlot.AlignedData;
}

/** Min/max-envelope decimation for plotting: visually lossless (every
 *  extreme survives), automatic (pixel-density-based, not a user knob),
 *  and re-resolving — it runs on the visible x-range, so zooming in
 *  always recovers full detail. Never used for CSV export or stats. */
export function decimateForPlot(data: uPlot.AlignedData, xRange: Range): uPlot.AlignedData {
  data = sliceToRange(data, xRange);
  const xs = data[0] as number[];
  if (xs.length <= DECIMATE_ABOVE) return data;
  const cols = data.slice(1) as (number | null)[][];
  const x0 = xs[0];
  const span = (xs[xs.length - 1] - x0) || 1;
  const outX: number[] = [];
  const outCols: (number | null)[][] = cols.map(() => []);

  const flush = (start: number, end: number) => {
    if (start >= end) return;
    const xa = xs[start], xb = xs[end - 1];
    const two = xb > xa;
    outX.push(xa);
    if (two) outX.push(xb);
    cols.forEach((col, ci) => {
      let mn: number | null = null, mx: number | null = null, iMn = -1, iMx = -1;
      for (let i = start; i < end; i++) {
        const v = col[i];
        if (v == null) continue;
        if (mn == null || v < mn) { mn = v; iMn = i; }
        if (mx == null || v > mx) { mx = v; iMx = i; }
      }
      const out = outCols[ci];
      if (mn == null || mx == null) {
        out.push(null);
        if (two) out.push(null);
      } else if (!two) {
        out.push(mx);
      } else if (iMn <= iMx) {
        out.push(mn, mx); // extremes in order of occurrence
      } else {
        out.push(mx, mn);
      }
    });
  };

  let bucketStart = 0;
  let bucket = 0;
  for (let i = 0; i < xs.length; i++) {
    const b = Math.min(TARGET_BUCKETS - 1,
                       Math.floor(((xs[i] - x0) / span) * TARGET_BUCKETS));
    if (b !== bucket) {
      flush(bucketStart, i);
      bucketStart = i;
      bucket = b;
    }
  }
  flush(bucketStart, xs.length);
  return [outX, ...outCols] as uPlot.AlignedData;
}

export interface SeriesStats { name: string; last: number | null; min: number; max: number }

export function seriesStats(pd: PanelData): SeriesStats[] {
  return pd.labels.map((name, i) => {
    const col = pd.data[i + 1] as (number | null)[];
    let last: number | null = null, min = Infinity, max = -Infinity;
    for (const v of col) {
      if (v == null) continue;
      last = v;
      if (v < min) min = v;
      if (v > max) max = v;
    }
    return { name, last, min: min === Infinity ? NaN : min, max: max === -Infinity ? NaN : max };
  });
}

// ------------------------------------------------------------- exports

function download(url: string, filename: string): void {
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
}

export function buildCsvText(pd: PanelData): string {
  const header = [pd.xLabel, ...pd.labels].join(",");
  const xs = pd.data[0] as number[];
  const rows = xs.map((x, i) =>
    [x, ...pd.labels.map((_, s) => (pd.data[s + 1] as (number | null)[])[i] ?? "")].join(","));
  return header + "\n" + rows.join("\n") + "\n";
}

export function makePngBlob(u: uPlot): Promise<Blob | null> {
  return new Promise((resolve) => u.ctx.canvas.toBlob(resolve, "image/png"));
}

export function exportCsv(pd: PanelData, filename: string): void {
  const blob = new Blob([buildCsvText(pd)], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  download(url, filename);
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}

export function exportPng(u: uPlot, filename: string): void {
  makePngBlob(u).then((blob) => {
    if (!blob) return;
    const url = URL.createObjectURL(blob);
    download(url, filename);
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  });
}

export async function copyCsv(pd: PanelData): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(buildCsvText(pd));
    return true;
  } catch {
    return false;
  }
}

export async function copyPng(u: uPlot): Promise<boolean> {
  try {
    const blob = await makePngBlob(u);
    if (!blob) return false;
    await navigator.clipboard.write([new ClipboardItem({ "image/png": blob })]);
    return true;
  } catch {
    return false;
  }
}

export function safeName(s: string): string {
  return s.replace(/[^\w.-]+/g, "_").slice(0, 60) || "panel";
}
