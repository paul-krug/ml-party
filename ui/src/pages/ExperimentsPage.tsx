import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ExperimentSummary, api, fmtAgo, fmtDate } from "../api";

const STATUS_ORDER = ["open", "finalized", "failed", "abandoned"];

function StatusSummary({ statuses }: { statuses: Record<string, number> }) {
  const parts = STATUS_ORDER.filter((s) => statuses[s]).map((s) => `${statuses[s]} ${s}`);
  return <span className="muted small">{parts.join(" · ") || "—"}</span>;
}

export default function ExperimentsPage() {
  const nav = useNavigate();
  const [exps, setExps] = useState<ExperimentSummary[]>([]);
  const [q, setQ] = useState("");
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    api.experimentsSummary().then((d) => {
      setExps(d);
      setLoaded(true);
    }).catch(console.error);
  }, []);

  const shown = useMemo(
    () => exps.filter((e) => e.title.toLowerCase().includes(q.toLowerCase())),
    [exps, q],
  );

  return (
    <div>
      <h1>Experiments</h1>
      <div className="searchrow">
        <input
          type="text"
          style={{ flex: 1, maxWidth: 420 }}
          placeholder="filter experiments by name…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
      </div>
      <div className="panel">
        <table className="data">
          <thead>
            <tr>
              <th>Experiment</th>
              <th>Runs</th>
              <th>Latest run</th>
              <th>Last activity</th>
              <th>Created</th>
              <th>Created by</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((e) => (
              <tr key={e.id} className="rowlink" onClick={() => nav(`/experiment/${e.id}`)}>
                <td>
                  <div><b>{e.title}</b></div>
                  <div className="muted small">{e.one_liner}</div>
                </td>
                <td className="num">
                  {e.n_runs}
                  <div><StatusSummary statuses={e.statuses} /></div>
                </td>
                <td>{e.last_run ? e.last_run.title : <span className="muted">—</span>}</td>
                <td className="num small">{e.last_run ? fmtAgo(e.last_run.created_at) : "—"}</td>
                <td className="num small">{fmtDate(e.created_at)}</td>
                <td className="small">{e.created_by}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {loaded && shown.length === 0 && (
          <div className="chart-empty">
            {exps.length === 0
              ? "no experiments yet — an agent creates one with experiment_ensure"
              : "no experiment matches the filter"}
          </div>
        )}
      </div>
    </div>
  );
}
