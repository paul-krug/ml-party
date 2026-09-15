import { useEffect, useState } from "react";
import { Navigate, useParams } from "react-router-dom";
import { NodeDetailData, api, fmtDate } from "../api";
import { AnnotateForm, Crumbs, EdgeRow } from "../components/shared";
import { Tags } from "../components/chips";

/** Universal resolver: /node/:ref (used by graph, search, edge links) sends
 *  runs and experiments to their entity pages and renders notes/projects
 *  in place. */
export default function NodeDetail() {
  const { ref } = useParams<{ ref: string }>();
  const [data, setData] = useState<NodeDetailData | null>(null);
  const [err, setErr] = useState("");
  const [rev, setRev] = useState(0);

  useEffect(() => {
    setErr("");
    api.node(ref!).then(setData).catch((e) => setErr(String(e)));
  }, [ref, rev]);

  if (err) return <div className="panel">not found: {err}</div>;
  if (!data) return <div className="muted">loading…</div>;
  const n = data.node;

  if (n.type === "run") return <Navigate to={`/run/${n.id}`} replace />;
  if (n.type === "experiment") return <Navigate to={`/experiment/${n.id}`} replace />;

  return (
    <div>
      <Crumbs parts={[{ to: "/search", label: "Knowledge" }, { label: n.title }]} />
      <h1>{n.title}</h1>
      <div className="metaline">
        {n.type}{n.kind ? ` · ${n.kind}` : ""} · created {fmtDate(n.created_at)} by {n.created_by}
      </div>
      <Tags tags={n.tags} />

      {n.body && (
        <div className="panel" style={{ marginTop: 12 }}>
          <h3>{n.kind ?? n.type}</h3>
          <pre style={{ maxHeight: 480, overflowY: "auto" }}>{n.body}</pre>
        </div>
      )}
      {n.description && (
        <div className="panel" style={{ marginTop: 12 }}>
          <h3>Description</h3>
          <p style={{ margin: 0 }}>{n.description}</p>
        </div>
      )}

      {(data.edges_out.length > 0 || data.edges_in.length > 0) && (
        <div className="panel">
          <h3>Edges</h3>
          <table className="data">
            <tbody>
              {data.edges_out.map((e, i) => <EdgeRow key={`o${i}`} edge={e} direction="out" />)}
              {data.edges_in.map((e, i) => <EdgeRow key={`i${i}`} edge={e} direction="in" />)}
            </tbody>
          </table>
        </div>
      )}

      <div className="panel">
        <h3>Annotations</h3>
        {(n.annotations ?? []).map((a: any, i: number) => (
          <p key={i} style={{ margin: "4px 0" }}>
            {a.text}{" "}
            <span className="muted small">— {a.created_by}, {fmtDate(a.created_at)}</span>
          </p>
        ))}
        <AnnotateForm nodeId={n.id} onDone={() => setRev((r) => r + 1)} />
      </div>
    </div>
  );
}
