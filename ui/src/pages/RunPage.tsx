import { useEffect, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { CodeTree, NodeDetailData, api, fmtDate, fmtDuration } from "../api";
import ArtifactsTab from "../components/artifacts/ArtifactsTab";
import Dashboard from "../components/dashboard/Dashboard";
import { ComputeChip, StatusChip, Tags, VerdictChip } from "../components/chips";
import { AnnotateForm, Copy, Crumbs, EdgeRow, KV, nodeTitle } from "../components/shared";

const TABS = ["overview", "metrics", "artifacts", "code"] as const;

function Overview({ data, reload }: { data: NodeDetailData; reload: () => void }) {
  const n = data.node;
  return (
    <>
      <div className="panel">
        <h3>Abstract</h3>
        <dl className="kv">
          <dt>purpose</dt><dd>{n.abstract?.purpose}</dd>
          <dt>hypothesis</dt><dd>{n.abstract?.hypothesis}</dd>
          {n.abstract?.method && (<><dt>method</dt><dd>{n.abstract.method}</dd></>)}
        </dl>
      </div>

      {n.result && (
        <div className="panel">
          <h3>Result</h3>
          <p style={{ marginTop: 0 }}>{n.result.summary}</p>
          {n.result.surprises && (
            <p className="small"><b>surprises:</b> {n.result.surprises}</p>
          )}
          {Object.keys(n.result.metrics ?? {}).length > 0 && (
            <table className="data" style={{ maxWidth: 460 }}>
              <thead><tr><th>metric</th><th>value</th></tr></thead>
              <tbody>
                {Object.entries(n.result.metrics).map(([k, v]) => (
                  <tr key={k}><td>{k}</td><td className="num">{String(v)}</td></tr>
                ))}
              </tbody>
            </table>
          )}
          {n.result.metrics_note && (
            <p className="muted small">metrics note: {n.result.metrics_note}</p>
          )}
        </div>
      )}

      {n.failure && (
        <div className="panel">
          <h3>Failure</h3>
          <dl className="kv">
            <dt>what failed</dt><dd>{n.failure.what_failed}</dd>
            {n.failure.failure_class && (<><dt>class</dt><dd>{n.failure.failure_class}</dd></>)}
            {n.failure.why && (<><dt>why</dt><dd>{n.failure.why}</dd></>)}
          </dl>
          {n.failure.traceback && <pre>{n.failure.traceback}</pre>}
        </div>
      )}

      <div className="panel">
        <h3>Parameters</h3>
        <KV obj={n.parameters} />
        <div className="muted small" style={{ marginTop: 6 }}>
          params_hash <span className="idmono">{n.params_hash}</span>
        </div>
      </div>

      <div className="panel">
        <h3>Reproduce</h3>
        {n.reproduce ? (
          <>
            <pre>{n.reproduce}</pre>
            <Copy text={n.reproduce} />
          </>
        ) : (
          <div className="muted small">not finalized — no reproduce recorded yet</div>
        )}
        <dl className="kv" style={{ marginTop: 8 }}>
          {n.code_ref && (
            <>
              <dt>snapshot commit</dt>
              <dd>
                <span className="idmono">{n.code_ref.commit_sha?.slice(0, 12)}</span>
                {" "}(see the Code tab)
              </dd>
            </>
          )}
          {n.env_lock_ref && (
            <><dt>env lock</dt><dd><code>{n.env_lock_ref}</code> inside the snapshot</dd></>
          )}
          {n.seed != null && (<><dt>seed</dt><dd>{n.seed}</dd></>)}
          {n.project_git && (
            <>
              <dt>project git</dt>
              <dd>
                {n.project_git.head?.slice(0, 12)} on {n.project_git.branch}
                {n.project_git.dirty ? " (dirty)" : ""}
                {n.project_git.remote && ` · ${n.project_git.remote}`}
              </dd>
            </>
          )}
          {n.compute && (
            <>
              <dt>compute</dt>
              <dd>
                {[n.compute.system, n.compute.job_id && `job ${n.compute.job_id}`,
                  n.compute.host].filter(Boolean).join(" · ") || "runs elsewhere"}
                {n.compute.url && (
                  <>
                    {" · "}
                    {/^https?:\/\//i.test(n.compute.url)
                      ? <a href={n.compute.url} target="_blank" rel="noopener noreferrer">
                          {n.compute.url}
                        </a>
                      : <code>{n.compute.url}</code>}
                  </>
                )}
                {n.compute.note && <div className="muted small">{n.compute.note}</div>}
              </dd>
            </>
          )}
          {n.hardware?.host && (
            <>
              <dt>hardware</dt>
              <dd>
                {n.hardware.host} ·{" "}
                {n.hardware.gpus?.map((g: any) => `${g.name} ${g.vram_mb}MB`).join(", ") ||
                  "no GPU recorded"}
                {n.hardware.ram_gb ? ` · ${n.hardware.ram_gb} GB RAM` : ""}
                {n.hardware.captured_by === "start" && (
                  <span className="muted small"> (launcher's view)</span>
                )}
              </dd>
            </>
          )}
          {!n.hardware?.host && n.compute && (
            <>
              <dt>hardware</dt>
              <dd className="muted">
                not recorded — arrives when the job attaches on the compute host
              </dd>
            </>
          )}
          {n.invocation?.argv?.length > 0 && (
            <>
              <dt>invocation</dt>
              <dd>
                <code>{n.invocation.argv.join(" ")}</code>{" "}
                <span className="muted small">({n.invocation.captured_by})</span>
              </dd>
            </>
          )}
          {n.data_refs?.length > 0 && (
            <>
              <dt>data</dt>
              <dd>{n.data_refs.map((d: any) => `${d.uri}${d.role ? ` (${d.role})` : ""}`).join("; ")}</dd>
            </>
          )}
        </dl>
      </div>

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
        <AnnotateForm nodeId={n.id} onDone={reload} />
      </div>
    </>
  );
}

function CodeTab({ runId, snapshotReport }: { runId: string; snapshotReport: any }) {
  const [tree, setTree] = useState<CodeTree | null>(null);
  const [sel, setSel] = useState("");
  const [file, setFile] = useState<{ content: string; truncated: boolean } | null>(null);

  useEffect(() => {
    api.codeTree(runId).then(setTree).catch(console.error);
  }, [runId]);

  useEffect(() => {
    if (!sel) return;
    setFile(null);
    api.codeFile(runId, sel).then(setFile).catch(console.error);
  }, [runId, sel]);

  if (!tree) return <div className="muted">loading…</div>;
  if (tree.note && !tree.files.length) return <div className="panel muted">{tree.note}</div>;

  return (
    <>
      <div className="metaline" style={{ marginBottom: 10 }}>
        snapshot commit <span className="idmono">{tree.commit?.slice(0, 12)}</span>
        {snapshotReport && (
          <>
            {" · "}{snapshotReport.included_files} files,{" "}
            {(snapshotReport.included_bytes / 1024).toFixed(0)} KiB
            {snapshotReport.skipped_for_size?.length > 0 &&
              ` · ${snapshotReport.skipped_for_size.length} skipped for size`}
            {snapshotReport.redacted_keys?.length > 0 &&
              ` · redacted params: ${snapshotReport.redacted_keys.join(", ")}`}
            {snapshotReport.note && ` · ${snapshotReport.note}`}
          </>
        )}
      </div>
      <div className="codegrid">
        <div className="panel filelist">
          {tree.files.map((f) => (
            <button
              key={f.path}
              className={sel === f.path ? "active" : ""}
              onClick={() => setSel(f.path)}
            >
              <span>{f.path}</span>
              <span className="sz">{(f.size / 1024).toFixed(1)}k</span>
            </button>
          ))}
        </div>
        <div className="panel" style={{ minWidth: 0 }}>
          {!sel && <div className="chart-empty">pick a file to view the snapshotted source</div>}
          {sel && !file && <div className="muted">loading {sel}…</div>}
          {sel && file && (
            <>
              <h3>{sel}</h3>
              <pre style={{ maxHeight: "58vh", overflowY: "auto" }}>{file.content}</pre>
              {file.truncated && <div className="muted small">truncated view</div>}
            </>
          )}
        </div>
      </div>
    </>
  );
}

export default function RunPage() {
  const { id } = useParams<{ id: string }>();
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") ?? "overview") as (typeof TABS)[number];
  const [data, setData] = useState<NodeDetailData | null>(null);
  const [expTitle, setExpTitle] = useState("");
  const [err, setErr] = useState("");
  const [rev, setRev] = useState(0);

  useEffect(() => {
    api.node(id!).then((d) => {
      setData(d);
      const expId = d.node.experiment_id as string;
      if (expId) nodeTitle(expId).then(setExpTitle);
    }).catch((e) => setErr(String(e)));
  }, [id, rev]);

  if (err) return <div className="panel">not found: {err}</div>;
  if (!data) return <div className="muted">loading…</div>;
  const n = data.node;
  const nArtifacts = n.artifacts?.length ?? 0;

  return (
    <div>
      <Crumbs
        parts={[
          { to: "/experiments", label: "Experiments" },
          { to: `/experiment/${n.experiment_id}`, label: expTitle || "…" },
          { label: n.title },
        ]}
      />
      <h1>
        {n.title} <StatusChip status={n.status} alive={n.alive} heartbeatAt={n.heartbeat_at} />{" "}
        <VerdictChip verdict={n.result?.verdict} /> <ComputeChip compute={n.compute} />
      </h1>
      <div className="metaline">
        <span className="idmono">{n.id}</span>
        <Copy text={n.id} />
        {" · "}started {fmtDate(n.started_at)} by {n.created_by}
        {" · "}{n.status === "open" ? fmtDuration(n.started_at, null) : fmtDuration(n.started_at, n.ended_at)}
        {n.provenance === "retro" && <span className="tag" style={{ marginLeft: 8 }}>retro</span>}
      </div>
      <Tags tags={n.tags} />

      <div className="tabs">
        {TABS.map((t) => (
          <button
            key={t}
            className={tab === t ? "active" : ""}
            onClick={() => setParams(t === "overview" ? {} : { tab: t })}
          >
            {t === "artifacts" ? `artifacts (${nArtifacts})` : t}
          </button>
        ))}
      </div>

      {tab === "overview" && <Overview data={data} reload={() => setRev((r) => r + 1)} />}

      {tab === "metrics" && (
        <>
          <Dashboard runId={n.id} live={n.status === "open"} />
          {Object.keys(n.result?.metrics ?? {}).length > 0 && (
            <div className="panel">
              <h3>Headline metrics (from the result)</h3>
              <table className="data" style={{ maxWidth: 460 }}>
                <tbody>
                  {Object.entries(n.result.metrics).map(([k, v]) => (
                    <tr key={k}><td>{k}</td><td className="num">{String(v)}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      {tab === "artifacts" && <ArtifactsTab artifacts={n.artifacts ?? []} />}

      {tab === "code" && <CodeTab runId={n.id} snapshotReport={n.snapshot_report} />}
    </div>
  );
}
