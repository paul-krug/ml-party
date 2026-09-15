const STATUS_COLOR: Record<string, string> = {
  open: "var(--series-1)",
  finalized: "var(--status-good)",
  failed: "var(--status-critical)",
  abandoned: "var(--muted)",
};

const VERDICT_COLOR: Record<string, string> = {
  confirmed: "var(--status-good)",
  refuted: "var(--status-critical)",
  inconclusive: "var(--status-warning)",
};

export function StatusChip({ status, alive, heartbeatAt }: {
  status?: string; alive?: boolean; heartbeatAt?: string | null;
}) {
  if (!status) return null;
  if (status === "open" && alive) {
    return (
      <span className="chip">
        <span className="dot pulse" style={{ background: "var(--status-good)" }} />
        open · live
      </span>
    );
  }
  if (status === "open" && heartbeatAt) {
    return (
      <span className="chip" title={`last heartbeat ${heartbeatAt}`}>
        <span className="dot" style={{ background: "var(--status-warning)" }} />
        open · stale
      </span>
    );
  }
  return (
    <span className="chip">
      <span className="dot" style={{ background: STATUS_COLOR[status] ?? "var(--muted)" }} />
      {status}
    </span>
  );
}

export function VerdictChip({ verdict }: { verdict?: string | null }) {
  if (!verdict) return null;
  return (
    <span className="chip">
      <span className="dot" style={{ background: VERDICT_COLOR[verdict] ?? "var(--muted)" }} />
      {verdict}
    </span>
  );
}

export function Tags({ tags }: { tags?: string[] }) {
  if (!tags?.length) return null;
  return (
    <span>
      {tags.map((t) => (
        <span key={t} className="tag">{t}</span>
      ))}
    </span>
  );
}
