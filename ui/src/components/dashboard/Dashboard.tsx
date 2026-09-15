import { useEffect, useMemo, useRef, useState } from "react";
import { MetricRec, api } from "../../api";
import Panel from "./Panel";
import {
  DashConfig, PanelConfig, defaultConfig, defaultPanel, fmt, loadConfig, saveConfig,
} from "./dash";

interface StatTile { name: string; value: number; prev: number | null; step: number | null }

/** Latest logged value per metric (+ previous, for the trend arrow). */
function latestStats(records: MetricRec[]): { maxStep: number | null; tiles: StatTile[] } {
  const tiles = new Map<string, StatTile>();
  let maxStep: number | null = null;
  for (const r of records) {
    const t = tiles.get(r.name);
    tiles.set(r.name, {
      name: r.name, value: r.value, prev: t ? t.value : null, step: r.step ?? null,
    });
    if (r.step != null && (maxStep == null || r.step > maxStep)) maxStep = r.step;
  }
  return { maxStep, tiles: [...tiles.values()] };
}

function StatStrip({ records }: { records: MetricRec[] }) {
  const { maxStep, tiles } = latestStats(records);
  return (
    <div className="statstrip">
      {maxStep != null && (
        <div className="stattile">
          <span className="statlabel">step</span>
          <span className="statvalue">{maxStep}</span>
        </div>
      )}
      {tiles.map((t) => (
        <div className="stattile" key={t.name} title={t.step != null ? `at step ${t.step}` : undefined}>
          <span className="statlabel">{t.name}</span>
          <span className="statvalue">
            {fmt(t.value)}
            {t.prev != null && t.value !== t.prev && (
              <span className="stattrend">{t.value > t.prev ? "▲" : "▼"}</span>
            )}
          </span>
        </div>
      ))}
    </div>
  );
}

export default function Dashboard({ runId, live }: { runId: string; live: boolean }) {
  const [records, setRecords] = useState<MetricRec[]>([]);
  const [done, setDone] = useState(false);
  const [cfg, setCfg] = useState<DashConfig | null>(null);
  const [themeRev, setThemeRev] = useState(0);
  const [dragId, setDragId] = useState<string | null>(null);
  const [overId, setOverId] = useState<string | null>(null);
  const cfgRef = useRef(cfg);
  cfgRef.current = cfg;

  // ---- data: full history + live tail over SSE (server streams from offset 0)
  useEffect(() => {
    let es: EventSource | null = null;
    let cancelled = false;
    setRecords([]);
    setDone(false);
    if (live) {
      es = new EventSource(`/api/runs/${runId}/metrics/stream`);
      const buf: MetricRec[] = [];
      let flush: number | null = null;
      es.onmessage = (ev) => {
        buf.push(JSON.parse(ev.data) as MetricRec);
        flush ??= window.setTimeout(() => {
          flush = null;
          if (!cancelled) setRecords((prev) => [...prev, ...buf.splice(0)]);
        }, 250);
      };
      es.addEventListener("end", () => {
        setDone(true);
        es?.close();
      });
      es.onerror = () => es?.close();
    } else {
      api.metrics(runId).then((m) => {
        if (!cancelled) setRecords(m.records);
      });
    }
    return () => {
      cancelled = true;
      es?.close();
    };
  }, [runId, live]);

  const names = useMemo(
    () => [...new Set(records.map((r) => r.name))],
    [records],
  );

  // ---- config lifecycle: restore per run; auto-append panels for new metrics
  useEffect(() => {
    setCfg(loadConfig(runId));
  }, [runId]);

  useEffect(() => {
    if (!names.length) return;
    setCfg((c) => {
      if (c == null) return defaultConfig(names);
      if (!c.auto) return c;
      const plotted = new Set(c.panels.flatMap((p) => p.series));
      const fresh = names.filter((n) => !plotted.has(n));
      return fresh.length
        ? { ...c, panels: [...c.panels, ...fresh.map(defaultPanel)] }
        : c;
    });
  }, [names]);

  useEffect(() => {
    if (cfg) saveConfig(runId, cfg);
  }, [runId, cfg]);

  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onTheme = () => setThemeRev((r) => r + 1);
    mq.addEventListener("change", onTheme);
    // a handle click that never becomes a drag must disarm draggable again
    const onUp = () => setDragId(null);
    window.addEventListener("mouseup", onUp);
    return () => {
      mq.removeEventListener("change", onTheme);
      window.removeEventListener("mouseup", onUp);
    };
  }, []);

  if (records.length === 0) {
    return (
      <div className="panel">
        <div className="chart-empty">
          {live ? "waiting for the first metric…" : "no metric series recorded for this run"}
        </div>
      </div>
    );
  }
  if (!cfg) return null;

  const patchPanel = (id: string, next: PanelConfig | null) =>
    setCfg((c) => c && {
      ...c,
      auto: next == null ? false : c.auto,
      panels: next == null
        ? c.panels.filter((p) => p.id !== id)
        : c.panels.map((p) => (p.id === id ? next : p)),
    });

  const dropOn = (targetId: string) => {
    const src = dragId;
    setDragId(null);
    setOverId(null);
    if (!src || src === targetId) return;
    setCfg((c) => {
      if (!c) return c;
      const srcIdx = c.panels.findIndex((p) => p.id === src);
      const dstIdx = c.panels.findIndex((p) => p.id === targetId);
      if (srcIdx < 0 || dstIdx < 0) return c;
      const panels = [...c.panels];
      const [dragged] = panels.splice(srcIdx, 1);
      // insert at the target's ORIGINAL index: after removal this lands the
      // dragged panel in the target's slot whether moving forward or back
      panels.splice(dstIdx, 0, dragged);
      return { ...c, panels };
    });
  };

  const unplotted = names.filter(
    (n) => !cfg.panels.some((p) => p.series.includes(n)));

  return (
    <div>
      <div className="dashbar">
        <span className="setlabel">columns</span>
        {([1, 2, 3] as const).map((n) => (
          <button key={n} className={cfg.columns === n ? "active" : ""}
                  onClick={() => setCfg({ ...cfg, columns: n })}>{n}</button>
        ))}
        <button onClick={() => setCfg({
          ...cfg,
          auto: false,
          panels: [...cfg.panels, { ...defaultPanel(unplotted[0] ?? names[0]) }],
        })}>+ add panel</button>
        <button title="one panel per metric, defaults"
                onClick={() => setCfg(defaultConfig(names))}>reset layout</button>
        <button className={(cfg.stats ?? true) ? "active" : ""}
                title="big-number strip with the latest logged values"
                onClick={() => setCfg({ ...cfg, stats: !(cfg.stats ?? true) })}>stats</button>
        {unplotted.length > 0 && (
          <span className="muted small">unplotted: {unplotted.join(", ")}</span>
        )}
        {live && !done && <span className="muted small">live — streaming via SSE</span>}
      </div>
      {(cfg.stats ?? true) && <StatStrip records={records} />}
      <div className="dashgrid" style={{ gridTemplateColumns: `repeat(${cfg.columns}, minmax(0, 1fr))` }}>
        {cfg.panels.map((p) => (
          <div
            key={p.id}
            className={`dashcell${p.wide ? " wide" : ""}${overId === p.id && dragId !== p.id ? " dropover" : ""}`}
            draggable={dragId === p.id}
            onDragStart={(e) => e.dataTransfer.setData("text/plain", p.id)}
            onDragEnd={() => { setDragId(null); setOverId(null); }}
            onDragOver={(e) => {
              if (!dragId) return;
              e.preventDefault();
              setOverId(p.id);
            }}
            onDragLeave={(e) => {
              // dragleave also fires when crossing into a child — only clear
              // the highlight when truly leaving the cell
              if (!e.currentTarget.contains(e.relatedTarget as Node)) {
                setOverId((o) => (o === p.id ? null : o));
              }
            }}
            onDrop={(e) => { e.preventDefault(); dropOn(p.id); }}
          >
            <Panel
              records={records}
              cfg={p}
              allNames={names}
              themeRev={themeRev}
              onChange={(next) => patchPanel(p.id, next)}
              onRemove={() => patchPanel(p.id, null)}
              onHandleDown={() => setDragId(p.id)}
            />
          </div>
        ))}
      </div>
    </div>
  );
}
