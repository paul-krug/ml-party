export interface ComputeRef {
  system?: string | null;
  job_id?: string | null;
  url?: string | null;
  host?: string | null;
  note?: string | null;
  captured_by?: string | null;
}

export interface Card {
  id: string;
  type: string;
  title: string;
  slug: string;
  tags: string[];
  created_by: string;
  created_at: string;
  status?: string;
  verdict?: string | null;
  one_liner?: string;
  experiment_id?: string;
  project_id?: string;
  kind?: string;
  started_at?: string;
  ended_at?: string | null;
  heartbeat_at?: string | null;
  alive?: boolean;
  compute?: ComputeRef | null;
}

export interface ExperimentSummary extends Card {
  n_runs: number;
  statuses: Record<string, number>;
  last_run: { id: string; title: string; created_at: string } | null;
}

export interface EdgeRec {
  src: string;
  dst: string;
  type: string;
  note?: string | null;
  created_by?: string;
  created_at?: string;
}

export interface MetricRec {
  ts: string;
  name: string;
  value: number;
  step?: number;
}

export interface NodeDetailData {
  node: Record<string, any>;
  edges_out: EdgeRec[];
  edges_in: EdgeRec[];
  metric_series?: MetricRec[];
}

export interface QueryHit extends Card {
  score: number;
  why?: string;
  key_edges?: { type: string; direction: string; node: string; title: string | null }[];
  corrected_by?: { node: string; edge: string }[];
}

export interface GraphData {
  nodes: Card[];
  edges: EdgeRec[];
}

export interface CodeTree {
  files: { path: string; size: number }[];
  commit: string | null;
  note?: string;
}

async function get<T>(url: string): Promise<T> {
  const r = await fetch(url);
  if (r.status === 401) window.dispatchEvent(new Event("mlp:unauthorized"));
  if (!r.ok) throw new Error(`${r.status} ${r.statusText} — ${url}`);
  return r.json() as Promise<T>;
}

export interface Me {
  auth_enabled: boolean;
  user: { username: string; role: string } | null;
}

export const api = {
  health: () => get<{ ok: boolean; store: string }>("/api/health"),
  nodes: (params: Record<string, string>) =>
    get<Card[]>(`/api/nodes?${new URLSearchParams(params)}`),
  node: (ref: string, metrics = false) =>
    get<NodeDetailData>(`/api/nodes/${encodeURIComponent(ref)}?metrics=${metrics}`),
  experimentsSummary: () => get<ExperimentSummary[]>("/api/experiments/summary"),
  graph: (experimentId?: string) =>
    get<GraphData>(`/api/graph${experimentId ? `?experiment_id=${experimentId}` : ""}`),
  query: (q: string, mode: string, type?: string) =>
    get<{ results: QueryHit[]; note?: string }>(
      `/api/query?${new URLSearchParams({ q, mode, limit: "20", ...(type ? { type } : {}) })}`),
  metrics: (runId: string, offset = 0) =>
    get<{ records: MetricRec[]; offset: number }>(
      `/api/runs/${runId}/metrics?offset=${offset}`),
  codeTree: (runId: string) => get<CodeTree>(`/api/runs/${runId}/code/tree`),
  codeFile: (runId: string, path: string) =>
    get<{ path: string; size: number; truncated: boolean; content: string }>(
      `/api/runs/${runId}/code/file?path=${encodeURIComponent(path)}`),
  diff: (a: string, b: string) =>
    get<Record<string, any>>(`/api/diff?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`),
  annotate: async (ref: string, text: string, createdBy: string) => {
    const r = await fetch(`/api/nodes/${encodeURIComponent(ref)}/annotate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, created_by: createdBy }),
    });
    if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
    return r.json();
  },
  artifactUrl: (sha256: string, name?: string) =>
    `/api/artifacts/${sha256}${name ? `?name=${encodeURIComponent(name)}` : ""}`,
  artifactInlineUrl: (sha256: string, name: string, mediaType: string) =>
    `/api/artifacts/${sha256}?${new URLSearchParams({ name, media_type: mediaType, inline: "true" })}`,
  tensorMeta: (sha256: string, member?: string) =>
    get<TensorMeta>(`/api/artifacts/${sha256}/tensor${member ? `?member=${encodeURIComponent(member)}` : ""}`),
  tensorSlice: (sha256: string, prefix: number[], member?: string) =>
    get<TensorSlice>(`/api/artifacts/${sha256}/tensor/slice?${new URLSearchParams({
      prefix: prefix.join(","), ...(member ? { member } : {}) })}`),
  tensorRange: (sha256: string, member?: string) =>
    get<TensorRange>(`/api/artifacts/${sha256}/tensor/range${member ? `?member=${encodeURIComponent(member)}` : ""}`),
  boards: (experimentId?: string) =>
    get<BoardInfo[]>(`/api/boards${experimentId ? `?experiment_id=${encodeURIComponent(experimentId)}` : ""}`),
  me: () => get<Me>("/api/auth/me"),
  login: async (username: string, password: string) => {
    const r = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    if (!r.ok) throw new Error(r.status === 401 ? "invalid username or password"
                                                : `${r.status} ${r.statusText}`);
    return r.json();
  },
  logout: async () => {
    await fetch("/api/auth/logout", { method: "POST" });
  },
  boardToken: () => get<{ token: string | null }>("/api/auth/board-token"),
};

export interface BoardInfo {
  sha256: string;
  title: string;
  note: string | null;
  original_path: string;
  size_bytes: number;
  node_id: string;
  node_type: "run" | "experiment";
  node_title: string;
  experiment_id: string | null;
  updated_at: string;
}

export interface TensorRange {
  min: number | null;
  max: number | null;
  exact: boolean;
  sampled_fraction?: number;
}

export interface TensorMeta {
  kind: "npy" | "npz";
  members?: string[];
  member?: string | null;
  shape?: number[];
  dtype?: string;
}

export interface TensorSlice {
  shape: number[];
  steps: number[];
  values: number[] | number[][];
  min: number | null;
  max: number | null;
}

export interface ArtifactRec {
  sha256: string;
  size_bytes: number;
  media_type?: string | null;
  original_path: string;
  note?: string | null;
}

export const TYPE_SLOT: Record<string, string> = {
  run: "var(--series-1)",
  note: "var(--series-2)",
  experiment: "var(--series-3)",
  project: "var(--series-4)",
};

/* Timestamps are stored UTC and shown UTC by default — a store can be served to
 * people in several zones, and an unlabelled local time makes two viewers read
 * the same run differently. The zone is always named, and this preference flips
 * every timestamp in the UI to the viewer's own zone. */
export type TzMode = "utc" | "local";

const TZ_KEY = "mlp:tz";
const TZ_EVENT = "mlp:tz-changed";

let tzMode: TzMode = readTzMode();

function readTzMode(): TzMode {
  try {
    return localStorage.getItem(TZ_KEY) === "local" ? "local" : "utc";
  } catch {                      // private mode / storage disabled
    return "utc";
  }
}

export function getTzMode(): TzMode {
  return tzMode;
}

export function setTzMode(mode: TzMode): void {
  tzMode = mode;
  try {
    localStorage.setItem(TZ_KEY, mode);
  } catch { /* preference just does not persist */ }
  window.dispatchEvent(new Event(TZ_EVENT));
}

export const TZ_CHANGED = TZ_EVENT;

/** The viewer's zone abbreviation (CEST, PDT, …) for labelling local times. */
export function localTzLabel(d: Date = new Date()): string {
  const part = new Intl.DateTimeFormat(undefined, { timeZoneName: "short" })
    .formatToParts(d).find((p) => p.type === "timeZoneName");
  return part?.value ?? "local";
}

const pad = (n: number) => String(n).padStart(2, "0");

/** ISO-ish and sortable, always carrying its zone: "2026-09-16 18:45 UTC". */
export function fmtDate(iso?: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso.slice(0, 16).replace("T", " ");
  if (tzMode === "utc") return `${d.toISOString().slice(0, 16).replace("T", " ")} UTC`;
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} `
    + `${pad(d.getHours())}:${pad(d.getMinutes())} ${localTzLabel(d)}`;
}

export function fmtAgo(iso?: string | null): string {
  if (!iso) return "";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  if (s < 86400 * 30) return `${Math.floor(s / 86400)}d ago`;
  return iso.slice(0, 10);
}

export function fmtDuration(start?: string | null, end?: string | null): string {
  if (!start) return "";
  const ms = (end ? new Date(end).getTime() : Date.now()) - new Date(start).getTime();
  if (ms < 0) return "";
  const s = Math.floor(ms / 1000);
  const label =
    s < 60 ? `${s}s`
    : s < 3600 ? `${Math.floor(s / 60)}m ${s % 60}s`
    : s < 86400 ? `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`
    : `${Math.floor(s / 86400)}d ${Math.floor((s % 86400) / 3600)}h`;
  return end ? label : `running · ${label}`;
}
