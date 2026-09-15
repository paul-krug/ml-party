import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Card, api } from "../api";

function DeltaTable({ title, delta }: { title: string; delta: any }) {
  if (!delta) return null;
  const rows: { key: string; a: string; b: string; kind: string }[] = [];
  Object.entries(delta.changed ?? {}).forEach(([k, v]: [string, any]) =>
    rows.push({ key: k, a: String(v.a), b: String(v.b), kind: "changed" }));
  Object.entries(delta.removed ?? {}).forEach(([k, v]) =>
    rows.push({ key: k, a: String(v), b: "—", kind: "only in A" }));
  Object.entries(delta.added ?? {}).forEach(([k, v]) =>
    rows.push({ key: k, a: "—", b: String(v), kind: "only in B" }));
  return (
    <div className="panel">
      <h3>{title}</h3>
      {delta.identical ? (
        <div className="muted small">identical</div>
      ) : (
        <table className="data">
          <thead><tr><th>key</th><th>run A</th><th>run B</th><th></th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.key}>
                <td>{r.key}</td>
                <td className="num">{r.a}</td>
                <td className="num">{r.b}</td>
                <td className="muted small">{r.kind}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

export default function DiffPage() {
  const [sp] = useSearchParams();
  const [runs, setRuns] = useState<Card[]>([]);
  const [a, setA] = useState(sp.get("a") ?? "");
  const [b, setB] = useState(sp.get("b") ?? "");
  const [diff, setDiff] = useState<any>(null);

  useEffect(() => {
    api.nodes({ type: "run", limit: "500" }).then(setRuns).catch(console.error);
  }, []);

  useEffect(() => {
    if (a && b && a !== b) {
      api.diff(a, b).then(setDiff).catch(console.error);
    } else {
      setDiff(null);
    }
  }, [a, b]);

  const pick = (v: string, set: (s: string) => void, other: string) => (
    <select value={v} onChange={(e) => set(e.target.value)} style={{ maxWidth: 420 }}>
      <option value="">pick a run…</option>
      {runs.map((r) => (
        <option key={r.id} value={r.id} disabled={r.id === other}>
          {r.title}
        </option>
      ))}
    </select>
  );

  return (
    <div>
      <h1>Diff two runs</h1>
      <div className="searchrow">
        {pick(a, setA, b)}
        <span style={{ alignSelf: "center" }} className="muted">vs</span>
        {pick(b, setB, a)}
      </div>
      {diff && (
        <>
          <p className="small">
            A = <Link to={`/node/${diff.run_a.id}`}>{diff.run_a.title}</Link> ·{" "}
            B = <Link to={`/node/${diff.run_b.id}`}>{diff.run_b.title}</Link>
          </p>
          <DeltaTable title="Parameters" delta={diff.params} />
          <DeltaTable title="Headline metrics" delta={diff.metrics} />
          <div className="panel">
            <h3>Code</h3>
            {diff.code?.identical ? (
              <div className="muted small">{diff.code.note ?? "identical snapshot commit"}</div>
            ) : diff.code?.note ? (
              <div className="muted small">{diff.code.note}</div>
            ) : (
              <>
                <div className="small" style={{ marginBottom: 6 }}>
                  {diff.code.files?.map((f: any, i: number) => (
                    <span key={i} className="tag">{f.type}: {f.new ?? f.old}</span>
                  ))}
                </div>
                <pre style={{ maxHeight: 420, overflowY: "auto" }}>{diff.code.patch}</pre>
                {diff.code.patch_truncated && <div className="muted small">patch truncated</div>}
              </>
            )}
          </div>
          <div className="panel">
            <h3>Environment lock</h3>
            {diff.env?.identical ? (
              <div className="muted small">identical</div>
            ) : diff.env?.diff ? (
              <pre style={{ maxHeight: 300, overflowY: "auto" }}>{diff.env.diff}</pre>
            ) : (
              <div className="muted small">{diff.env?.note}</div>
            )}
          </div>
        </>
      )}
      {!diff && <div className="panel chart-empty">pick two different runs to compare</div>}
    </div>
  );
}
