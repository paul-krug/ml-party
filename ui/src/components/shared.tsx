import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { EdgeRec, api } from "../api";
import { useAuth } from "../auth";

const titleCache = new Map<string, Promise<string>>();
export function nodeTitle(id: string): Promise<string> {
  if (!titleCache.has(id)) {
    titleCache.set(
      id,
      api.node(id).then((d) => (d.node.title as string) ?? id).catch(() => id),
    );
  }
  return titleCache.get(id)!;
}

export function Copy({ text }: { text: string }) {
  const [ok, setOk] = useState(false);
  return (
    <button
      className="copybtn"
      title={`copy: ${text}`}
      onClick={(e) => {
        e.stopPropagation();
        navigator.clipboard.writeText(text).then(() => {
          setOk(true);
          setTimeout(() => setOk(false), 1200);
        });
      }}
    >
      {ok ? "✓ copied" : "copy"}
    </button>
  );
}

export function Crumbs({ parts }: { parts: { to?: string; label: string }[] }) {
  return (
    <div className="crumbs">
      {parts.map((p, i) => (
        <span key={i}>
          {p.to ? <Link to={p.to}>{p.label}</Link> : p.label}
          {i < parts.length - 1 && " / "}
        </span>
      ))}
    </div>
  );
}

export function EdgeRow({ edge, direction }: { edge: EdgeRec; direction: "out" | "in" }) {
  const other = direction === "out" ? edge.dst : edge.src;
  const [title, setTitle] = useState(other);
  useEffect(() => {
    nodeTitle(other).then(setTitle);
  }, [other]);
  return (
    <tr>
      <td className="small muted">{direction === "out" ? "→" : "←"}</td>
      <td><span className="tag">{edge.type}</span></td>
      <td><Link to={`/node/${other}`}>{title}</Link></td>
      <td className="small muted">{edge.note}</td>
    </tr>
  );
}

export function AnnotateForm({ nodeId, onDone }: { nodeId: string; onDone: () => void }) {
  const auth = useAuth();
  const [text, setText] = useState("");
  const [who, setWho] = useState(localStorage.getItem("mlparty.user") ?? "");
  const [busy, setBusy] = useState(false);

  async function submit() {
    if (!text.trim()) return;
    setBusy(true);
    try {
      // under auth the server stamps the session user as author
      await api.annotate(nodeId, text.trim(), who.trim() || "human");
      if (who.trim()) localStorage.setItem("mlparty.user", who.trim());
      setText("");
      onDone();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="annotate">
      <textarea
        rows={2}
        placeholder="add an observation (by-ear verdicts, corrections, context) — append-only"
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
      <div className="searchrow" style={{ marginTop: 6, marginBottom: 0 }}>
        {auth.user ? (
          <span className="muted small" style={{ alignSelf: "center" }}>
            as {auth.user.username}
          </span>
        ) : (
          <input
            type="text"
            style={{ width: 140 }}
            placeholder="your name"
            value={who}
            onChange={(e) => setWho(e.target.value)}
          />
        )}
        <button className="primary" disabled={busy || !text.trim()} onClick={submit}>
          annotate
        </button>
      </div>
    </div>
  );
}

export function KV({ obj }: { obj: Record<string, unknown> }) {
  const entries = Object.entries(obj ?? {});
  if (!entries.length) return <div className="muted small">empty</div>;
  return (
    <dl className="kv">
      {entries.map(([k, v]) => (
        <span key={k} style={{ display: "contents" }}>
          <dt>{k}</dt>
          <dd>{typeof v === "object" ? JSON.stringify(v) : String(v)}</dd>
        </span>
      ))}
    </dl>
  );
}
