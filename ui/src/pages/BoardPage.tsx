import { useEffect, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { Crumbs } from "../components/shared";

export default function BoardPage() {
  const { sha } = useParams<{ sha: string }>();
  const [params] = useSearchParams();
  const name = params.get("name") ?? "board";
  const auth = useAuth();
  // sandboxed boards run in an opaque origin (no cookies) — under auth the
  // UI hands the board a short-lived read token via ?bt=
  const [bt, setBt] = useState<string | null | undefined>(
    auth.auth_enabled ? undefined : null);

  useEffect(() => {
    if (!auth.auth_enabled) return;
    api.boardToken().then((d) => setBt(d.token)).catch(() => setBt(null));
  }, [auth.auth_enabled, sha]);

  if (bt === undefined) return <div className="muted">loading…</div>;
  const src = `/boards/${sha}${bt ? `?bt=${encodeURIComponent(bt)}` : ""}`;
  return (
    <div className="boardpage">
      <Crumbs parts={[{ to: "/experiments", label: "Experiments" }, { label: name }]} />
      <div className="metaline" style={{ marginBottom: 8 }}>
        <span className="idmono">{sha?.slice(0, 16)}</span>
        {" · sandboxed board (own origin, read-only API, no external hosts) · "}
        <a href={src} target="_blank" rel="noreferrer">open in new tab ⇗</a>
      </div>
      <iframe
        className="boardframe"
        title={name}
        sandbox="allow-scripts allow-downloads"
        src={src}
      />
    </div>
  );
}
