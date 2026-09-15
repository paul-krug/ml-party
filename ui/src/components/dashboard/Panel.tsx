import { useEffect, useRef, useState } from "react";
import uPlot from "uplot";
import "uplot/dist/uPlot.min.css";
import { MetricRec } from "../../api";
import {
  PanelConfig, PanelData, buildPanelData, copyCsv, copyPng, decimateForPlot, exportCsv,
  exportPng, fmt, safeName, seriesStats,
} from "./dash";

const SLOT_VARS = [
  "--series-1", "--series-2", "--series-3", "--series-4",
  "--series-5", "--series-6", "--series-7", "--series-8",
];

function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function RangeInput({ value, placeholder, onCommit }: {
  value: number | null; placeholder: string; onCommit: (v: number | null) => void;
}) {
  const [text, setText] = useState(value == null ? "" : String(value));
  useEffect(() => setText(value == null ? "" : String(value)), [value]);
  const commit = () => {
    const t = text.trim();
    if (t === "") return onCommit(null);
    const v = Number(t);
    if (Number.isFinite(v)) onCommit(v);
  };
  return (
    <input
      className="rangeinput" value={text} placeholder={placeholder}
      onChange={(e) => setText(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => e.key === "Enter" && commit()}
    />
  );
}

export default function Panel({ records, cfg, allNames, themeRev, onChange, onRemove, onHandleDown }: {
  records: MetricRec[];
  cfg: PanelConfig;
  allNames: string[];
  themeRev: number;
  onChange: (cfg: PanelConfig) => void;
  onRemove: () => void;
  onHandleDown: () => void;
}) {
  const holder = useRef<HTMLDivElement>(null);
  const plot = useRef<uPlot | null>(null);
  const structKey = useRef("");
  const pdRef = useRef<PanelData | null>(null);
  const cfgRef = useRef(cfg);
  cfgRef.current = cfg;
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;
  const [settings, setSettings] = useState(false);
  const [copied, setCopied] = useState<"png" | "csv" | null>(null);

  const flashCopied = (kind: "png" | "csv", ok: boolean) => {
    if (!ok) return;
    setCopied(kind);
    setTimeout(() => setCopied((c) => (c === kind ? null : c)), 1200);
  };

  const pd = buildPanelData(records, cfg);
  pdRef.current = pd;
  const plotData = pd ? decimateForPlot(pd.data, cfg.xRange) : null;
  const decimated = pd != null && plotData != null &&
    (plotData[0] as number[]).length < (pd.data[0] as number[]).length;
  const zoomed = cfg.xRange != null || cfg.yRange != null;
  const height = cfg.wide ? 340 : 240;

  useEffect(() => {
    const el = holder.current;
    if (!el || !pd || !plotData) return;

    const key = [
      pd.labels.join("|"), cfg.chartType, cfg.logY, cfg.smooth,
      cfg.xAxis.kind, cfg.xAxis.metric ?? "", pd.isTime,
      JSON.stringify(cfg.xRange), JSON.stringify(cfg.yRange),
      cfg.wide, themeRev,
    ].join("·");

    if (plot.current && structKey.current === key) {
      // data-only update; fixed ranges (zoom / manual) survive because the
      // scale range functions below clamp to the config, not the data
      plot.current.setData(plotData, !zoomed);
      return;
    }

    plot.current?.destroy();
    structKey.current = key;

    const [xr0, xr1] = cfg.xRange ?? [null, null];
    const [yr0, yr1] = cfg.yRange ?? [null, null];
    const axisStyle = {
      stroke: cssVar("--muted"),
      grid: { stroke: cssVar("--grid"), width: 1 },
      ticks: { stroke: cssVar("--grid"), width: 1 },
    };
    const scatter = cfg.chartType === "scatter" || cfg.xAxis.kind === "metric";
    const bars = cfg.chartType === "bar";

    const opts: uPlot.Options = {
      width: el.clientWidth || 600,
      height,
      scales: {
        x: {
          time: pd.isTime,
          range: (_u, dMin, dMax) => [xr0 ?? dMin, xr1 ?? dMax],
        },
        y: {
          ...(cfg.logY ? { distr: 3 as const } : {}),
          range: (_u, dMin, dMax) =>
            cfg.logY && (yr0 == null || yr1 == null)
              ? uPlot.rangeLog(yr0 ?? dMin, yr1 ?? dMax, 10, true)
              : [yr0 ?? dMin, yr1 ?? dMax],
        },
      },
      cursor: {
        focus: { prox: 24 },
        drag: { x: true, y: true, uni: 30, dist: 6, setScale: false },
        // sync ONLY the crosshair across panels sharing an x-axis — never
        // drag events, or a zoom on one panel replays on all of them
        sync: {
          key: `mlp-dash:${cfg.xAxis.kind === "metric" ? `m:${cfg.xAxis.metric}` : cfg.xAxis.kind}`,
          filters: { pub: (type: string) => type === "mousemove" || type === "mouseleave" },
        },
      },
      legend: { live: true },
      hooks: {
        setSelect: [
          (u) => {
            // synced-in events carry no source mouse event — never zoom on those
            if (u.cursor.event == null) {
              u.setSelect({ left: 0, top: 0, width: 0, height: 0 }, false);
              return;
            }
            if (u.select.width < 6 && u.select.height < 6) return;
            const c = cfgRef.current;
            const next = { ...c };
            if (u.select.width >= 6) {
              next.xRange = [
                u.posToVal(u.select.left, "x"),
                u.posToVal(u.select.left + u.select.width, "x"),
              ];
            }
            if (u.select.height >= 6) {
              next.yRange = [
                u.posToVal(u.select.top + u.select.height, "y"),
                u.posToVal(u.select.top, "y"),
              ];
            }
            u.setSelect({ left: 0, top: 0, width: 0, height: 0 }, false);
            onChangeRef.current(next);
          },
        ],
        ready: [
          (u) => {
            u.over.addEventListener("dblclick", () => {
              const c = cfgRef.current;
              if (c.xRange || c.yRange) {
                onChangeRef.current({ ...c, xRange: null, yRange: null });
              }
            });
          },
        ],
      },
      axes: [{ label: pd.xLabel, ...axisStyle }, { ...axisStyle }],
      series: [
        { label: pd.xLabel },
        ...pd.labels.map((n, i) => ({
          label: n,
          stroke: cssVar(SLOT_VARS[i % SLOT_VARS.length]),
          fill: bars ? cssVar(SLOT_VARS[i % SLOT_VARS.length]) + "55" : undefined,
          width: 2,
          paths: bars
            ? uPlot.paths.bars!({ size: [0.6, 100] })
            : scatter
              ? () => null
              : undefined,
          points: { show: scatter, size: 6 },
        })),
      ],
    };
    plot.current = new uPlot(opts, plotData, el);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [records, cfg, themeRev]);

  useEffect(() => {
    const el = holder.current;
    if (!el) return;
    const ro = new ResizeObserver(() => {
      if (plot.current && el.clientWidth > 0) {
        plot.current.setSize({ width: el.clientWidth, height });
      }
    });
    ro.observe(el);
    return () => {
      ro.disconnect();
      plot.current?.destroy();
      plot.current = null;
      structKey.current = "";
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [height]);

  const set = (patch: Partial<PanelConfig>) => onChange({ ...cfg, ...patch });
  const stats = pd ? seriesStats(pd) : [];

  return (
    <div className="panel dashpanel">
      <div className="paneltop">
        <span className="draghandle" title="drag to reorder"
              onMouseDown={onHandleDown}>⠿</span>
        <input
          className="paneltitle"
          value={cfg.title}
          onChange={(e) => set({ title: e.target.value })}
          title="panel title"
        />
        <span className="panelbtns">
          {zoomed && (
            <button title="reset zoom (or double-click the plot)"
                    onClick={() => set({ xRange: null, yRange: null })}>⟲</button>
          )}
          <button title="settings" className={settings ? "active" : ""}
                  onClick={() => setSettings((s) => !s)}>⚙</button>
          <button title={cfg.wide ? "normal width" : "full width"}
                  onClick={() => set({ wide: !cfg.wide })}>{cfg.wide ? "⊟" : "⛶"}</button>
          <button title="click: download PNG · right-click: copy image to clipboard"
                  disabled={!pd}
                  onClick={() => plot.current && exportPng(plot.current, `${safeName(cfg.title)}.png`)}
                  onContextMenu={(e) => {
                    e.preventDefault();
                    if (plot.current) copyPng(plot.current).then((ok) => flashCopied("png", ok));
                  }}>{copied === "png" ? "✓" : "png"}</button>
          <button title="click: download CSV · right-click: copy values to clipboard"
                  disabled={!pd}
                  onClick={() => pd && exportCsv(pd, `${safeName(cfg.title)}.csv`)}
                  onContextMenu={(e) => {
                    e.preventDefault();
                    if (pd) copyCsv(pd).then((ok) => flashCopied("csv", ok));
                  }}>{copied === "csv" ? "✓" : "csv"}</button>
          <button title="remove panel" onClick={onRemove}>✕</button>
        </span>
      </div>

      {settings && (
        <div className="panelsettings">
          <div className="setrow">
            <span className="setlabel">series</span>
            <span className="setchecks">
              {allNames.map((n) => (
                <label key={n}>
                  <input
                    type="checkbox"
                    checked={cfg.series.includes(n)}
                    onChange={(e) => set({
                      series: e.target.checked
                        ? [...cfg.series, n]
                        : cfg.series.filter((s) => s !== n),
                    })}
                  /> {n}
                </label>
              ))}
            </span>
          </div>
          <div className="setrow">
            <span className="setlabel">type</span>
            <select value={cfg.chartType}
                    onChange={(e) => set({ chartType: e.target.value as PanelConfig["chartType"] })}>
              <option value="line">line</option>
              <option value="scatter">scatter</option>
              <option value="bar">bar</option>
            </select>
            <span className="setlabel">x-axis</span>
            <select
              value={cfg.xAxis.kind === "metric" ? `m:${cfg.xAxis.metric}` : cfg.xAxis.kind}
              onChange={(e) => {
                const v = e.target.value;
                set({
                  xAxis: v.startsWith("m:")
                    ? { kind: "metric", metric: v.slice(2) }
                    : { kind: v as "step" | "time" | "reltime" },
                  xRange: null, yRange: null,
                });
              }}
            >
              <option value="step">step</option>
              <option value="time">wall time</option>
              <option value="reltime">elapsed</option>
              {allNames.map((n) => (
                <option key={n} value={`m:${n}`}>vs {n}</option>
              ))}
            </select>
            <label><input type="checkbox" checked={cfg.logY}
                          onChange={(e) => set({ logY: e.target.checked })} /> log y</label>
            <label><input type="checkbox" checked={cfg.smooth}
                          onChange={(e) => set({ smooth: e.target.checked })} /> smooth</label>
          </div>
          <div className="setrow">
            <span className="setlabel">x range</span>
            <RangeInput value={cfg.xRange?.[0] ?? null} placeholder="auto"
                        onCommit={(v) => set({ xRange: v == null && cfg.xRange?.[1] == null ? null : [v, cfg.xRange?.[1] ?? null] })} />
            <RangeInput value={cfg.xRange?.[1] ?? null} placeholder="auto"
                        onCommit={(v) => set({ xRange: v == null && cfg.xRange?.[0] == null ? null : [cfg.xRange?.[0] ?? null, v] })} />
            <span className="setlabel">y range</span>
            <RangeInput value={cfg.yRange?.[0] ?? null} placeholder="auto"
                        onCommit={(v) => set({ yRange: v == null && cfg.yRange?.[1] == null ? null : [v, cfg.yRange?.[1] ?? null] })} />
            <RangeInput value={cfg.yRange?.[1] ?? null} placeholder="auto"
                        onCommit={(v) => set({ yRange: v == null && cfg.yRange?.[0] == null ? null : [cfg.yRange?.[0] ?? null, v] })} />
          </div>
        </div>
      )}

      {!pd && <div className="chart-empty">no data for this panel's series yet</div>}
      <div ref={holder} />
      {pd && (
        <div className="panelstats">
          {stats.map((s) => (
            <span key={s.name}>
              <b>{s.name}</b> last {fmt(s.last)} · min {fmt(s.min)} · max {fmt(s.max)}
            </span>
          ))}
          {decimated && (
            <span className="muted" title="rendering a min/max envelope; zoom in for full detail — stats and CSV use all points">
              envelope of {(pd.data[0] as number[]).length} pts
            </span>
          )}
        </div>
      )}
    </div>
  );
}
