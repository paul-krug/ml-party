import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { BoardInfo, Card, api, fmtDate, fmtDuration } from "../api";
import BoardGallery from "../components/BoardGallery";
import ArtifactsTab from "../components/artifacts/ArtifactsTab";
import { StatusChip, Tags, VerdictChip } from "../components/chips";
import { Copy, Crumbs } from "../components/shared";

const STATUSES = ["", "open", "finalized", "failed", "abandoned"];

export default function ExperimentPage() {
  const { id } = useParams<{ id: string }>();
  const nav = useNavigate();
  const [exp, setExp] = useState<Record<string, any> | null>(null);
  const [runs, setRuns] = useState<Card[]>([]);
  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");
  const [picked, setPicked] = useState<string[]>([]);
  const [boards, setBoards] = useState<BoardInfo[]>([]);

  const fetchRuns = useCallback(() => {
    api.nodes({ type: "run", experiment_id: id!, limit: "500" })
      .then(setRuns)
      .catch(console.error);
  }, [id]);

  useEffect(() => {
    api.node(id!).then((d) => setExp(d.node)).catch(console.error);
    api.boards(id!).then(setBoards).catch(console.error);
    fetchRuns();
  }, [id, fetchRuns]);

  // live view: refresh while anything is running
  const anyOpen = runs.some((r) => r.status === "open");
  useEffect(() => {
    if (!anyOpen) return;
    const t = setInterval(fetchRuns, 5000);
    return () => clearInterval(t);
  }, [anyOpen, fetchRuns]);

  const togglePick = (rid: string) =>
    setPicked((p) => (p.includes(rid) ? p.filter((x) => x !== rid) : [...p, rid].slice(-2)));

  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    runs.forEach((r) => { c[r.status ?? "?"] = (c[r.status ?? "?"] ?? 0) + 1; });
    return c;
  }, [runs]);

  const shown = runs.filter(
    (r) =>
      (!status || r.status === status) &&
      r.title.toLowerCase().includes(q.toLowerCase()),
  );

  if (!exp) return <div className="muted">loading…</div>;
  // boards render in the gallery above; the artifacts browser gets the rest
  const expFiles = (exp.artifacts ?? []).filter((a: any) => a.media_type !== "text/html");
  return (
    <div>
      <Crumbs parts={[{ to: "/experiments", label: "Experiments" }, { label: exp.title }]} />
      <h1>{exp.title}</h1>
      {exp.description && <p style={{ marginTop: 0 }}>{exp.description}</p>}
      <div className="metaline">
        created {fmtDate(exp.created_at)} by {exp.created_by} ·{" "}
        <span className="idmono">{exp.id}</span>
        <Copy text={exp.id} />
      </div>

      <div className="searchrow" style={{ marginTop: 14 }}>
        <input
          type="text"
          style={{ flex: 1, maxWidth: 360 }}
          placeholder="filter runs by name…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <select value={status} onChange={(e) => setStatus(e.target.value)}>
          {STATUSES.map((s) => (
            <option key={s || "all"} value={s}>
              {s ? `${s} (${counts[s] ?? 0})` : `all (${runs.length})`}
            </option>
          ))}
        </select>
        {picked.length === 2 && (
          <button
            className="primary"
            onClick={() => nav(`/diff?a=${picked[0]}&b=${picked[1]}`)}
          >
            compare selected
          </button>
        )}
        {anyOpen && <span className="muted small" style={{ alignSelf: "center" }}>auto-refreshing (runs open)</span>}
      </div>

      <div className="panel">
        <table className="data">
          <thead>
            <tr>
              <th></th>
              <th>Run</th>
              <th>Status</th>
              <th>Verdict</th>
              <th>Created</th>
              <th>Duration</th>
              <th>Tags</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((r) => (
              <tr key={r.id} className="rowlink" onClick={() => nav(`/run/${r.id}`)}>
                <td onClick={(e) => e.stopPropagation()}>
                  <input
                    type="checkbox"
                    title="select for compare"
                    checked={picked.includes(r.id)}
                    onChange={() => togglePick(r.id)}
                  />
                </td>
                <td>
                  <div><b>{r.title}</b></div>
                  <div className="idmono">{r.id}</div>
                </td>
                <td><StatusChip status={r.status} alive={r.alive} heartbeatAt={r.heartbeat_at} /></td>
                <td><VerdictChip verdict={r.verdict} /></td>
                <td className="num small">{fmtDate(r.created_at)}</td>
                <td className="num small">
                  {r.status === "open"
                    ? fmtDuration(r.started_at, null)
                    : fmtDuration(r.started_at, r.ended_at)}
                </td>
                <td><Tags tags={r.tags} /></td>
              </tr>
            ))}
          </tbody>
        </table>
        {shown.length === 0 && <div className="chart-empty">no runs match</div>}
      </div>

      {boards.length > 0 && (
        <>
          <h2 style={{ marginTop: 22 }}>Boards</h2>
          <div className="panel">
            <BoardGallery boards={boards} />
          </div>
        </>
      )}

      {expFiles.length > 0 && (
        <>
          <h2 style={{ marginTop: 22 }}>Experiment artifacts</h2>
          <ArtifactsTab artifacts={expFiles} />
        </>
      )}
    </div>
  );
}
