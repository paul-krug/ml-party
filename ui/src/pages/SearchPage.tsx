import { FormEvent, useState } from "react";
import { Link } from "react-router-dom";
import { QueryHit, TYPE_SLOT, api } from "../api";

export default function SearchPage() {
  const [q, setQ] = useState("");
  const [mode, setMode] = useState("hybrid");
  const [type, setType] = useState("");
  const [hits, setHits] = useState<QueryHit[]>([]);
  const [note, setNote] = useState<string | undefined>();
  const [searched, setSearched] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!q.trim()) return;
    const out = await api.query(q, mode, type || undefined);
    setHits(out.results);
    setNote(out.note);
    setSearched(true);
  }

  return (
    <div>
      <h1>Search the knowledge graph</h1>
      <form className="searchrow" onSubmit={submit}>
        <input
          type="text"
          style={{ flex: 1, minWidth: 260 }}
          placeholder='e.g. "which model transferred best to TDS"'
          value={q}
          onChange={(e) => setQ(e.target.value)}
          autoFocus
        />
        <select value={mode} onChange={(e) => setMode(e.target.value)}>
          <option value="hybrid">hybrid</option>
          <option value="lexical">lexical</option>
          <option value="semantic">semantic</option>
          <option value="graph">graph</option>
        </select>
        <select value={type} onChange={(e) => setType(e.target.value)}>
          <option value="">any type</option>
          <option value="run">runs</option>
          <option value="note">notes</option>
          <option value="experiment">experiments</option>
        </select>
        <button className="primary" type="submit">search</button>
      </form>
      {note && <p className="muted small">{note}</p>}
      <div className="panel">
        {hits.map((h) => (
          <div className="hit" key={h.id}>
            <div>
              <span className="chip" style={{ marginRight: 8 }}>
                <span className="dot" style={{ background: TYPE_SLOT[h.type] ?? "var(--muted)" }} />
                {h.type}
              </span>
              <Link to={`/node/${h.id}`}><b>{h.title}</b></Link>{" "}
              <span className="score">score {h.score.toFixed(4)}</span>
            </div>
            {h.one_liner && <div>{h.one_liner}</div>}
            {h.corrected_by && h.corrected_by.length > 0 && (
              <div className="small" style={{ color: "var(--status-serious)" }}>
                ⚠ corrected by{" "}
                {h.corrected_by.map((c, i) => (
                  <span key={i}>
                    <Link to={`/node/${c.node}`}>{c.edge}</Link>{" "}
                  </span>
                ))}
              </div>
            )}
            <div className="why">
              via {h.why}
              {h.key_edges && h.key_edges.length > 0 && (
                <>
                  {" · "}
                  {h.key_edges.map((e, i) => (
                    <span key={i}>
                      {e.direction === "out" ? "→" : "←"} {e.type}{" "}
                      <Link to={`/node/${e.node}`}>{e.title ?? e.node.slice(0, 8)}</Link>
                      {i < h.key_edges!.length - 1 ? ", " : ""}
                    </span>
                  ))}
                </>
              )}
            </div>
          </div>
        ))}
        {searched && hits.length === 0 && <div className="chart-empty">no results</div>}
        {!searched && <div className="chart-empty">ask the lab notebook something</div>}
      </div>
    </div>
  );
}
