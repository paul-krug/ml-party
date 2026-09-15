import { useState } from "react";
import { ArtifactRec, api } from "../../api";
import { Copy } from "../shared";
import TensorViewer from "./TensorViewer";
import Viewer, { Group, basename, classify, ext, fmtBytes, mime } from "./viewers";

const GROUP_ORDER: Group[] = [
  "boards", "images", "audio", "video", "tensors", "checkpoints", "text", "other",
];
const GROUP_ICON: Record<Group, string> = {
  boards: "📊", images: "🖼", audio: "🔊", video: "🎬", tensors: "⊞",
  checkpoints: "⬢", text: "📄", other: "▦",
};

type GroupView = "grid" | "list";

function loadGroupViews(): Record<string, GroupView> {
  try {
    return JSON.parse(localStorage.getItem("mlp.artifacts.groupviews") ?? "{}");
  } catch {
    return {};
  }
}

function Tile({ a, selected, onClick }: {
  a: ArtifactRec; selected: boolean; onClick: () => void;
}) {
  const group = classify(a);
  const name = basename(a.original_path);
  let thumb;
  if (group === "images") {
    thumb = <img src={api.artifactInlineUrl(a.sha256, name, mime(a))} alt={name} loading="lazy" />;
  } else if (group === "video") {
    thumb = (
      <video src={api.artifactInlineUrl(a.sha256, name, mime(a))}
             preload="metadata" muted style={{ pointerEvents: "none" }} />
    );
  } else {
    thumb = <span className="tileicon">{GROUP_ICON[group]}</span>;
  }
  return (
    <button className={`arttile${selected ? " selected" : ""}`} onClick={onClick} title={a.original_path}>
      <span className="tilethumb">{thumb}</span>
      <span className="tilename">{name}</span>
      <span className="tilesize">{fmtBytes(a.size_bytes)}</span>
    </button>
  );
}

export default function ArtifactsTab({ artifacts }: { artifacts: ArtifactRec[] }) {
  const [pageView, setPageView] = useState<"groups" | "list">(
    () => (localStorage.getItem("mlp.artifacts.view") as "groups" | "list") ?? "groups");
  const [groupViews, setGroupViews] = useState<Record<string, GroupView>>(loadGroupViews);
  const [sel, setSel] = useState<ArtifactRec | null>(null);

  const setPageViewPersist = (v: "groups" | "list") => {
    setPageView(v);
    localStorage.setItem("mlp.artifacts.view", v);
  };
  const setGroupView = (g: Group, v: GroupView) => {
    const next = { ...groupViews, [g]: v };
    setGroupViews(next);
    localStorage.setItem("mlp.artifacts.groupviews", JSON.stringify(next));
  };

  if (artifacts.length === 0) {
    return (
      <div className="panel">
        <div className="chart-empty">
          no artifacts on this run — log them with run_log_artifact / handle.log_artifact
        </div>
      </div>
    );
  }

  const groups = new Map<Group, ArtifactRec[]>();
  for (const a of artifacts) {
    const g = classify(a);
    if (!groups.has(g)) groups.set(g, []);
    groups.get(g)!.push(a);
  }

  const row = (a: ArtifactRec) => (
    <tr key={a.sha256}
        className={sel?.sha256 === a.sha256 ? "selrow" : ""}
        onClick={() => setSel(sel?.sha256 === a.sha256 ? null : a)}
        style={{ cursor: "pointer" }}>
      <td>{a.original_path}</td>
      <td>{a.media_type ?? ext(a.original_path)}</td>
      <td className="num">{fmtBytes(a.size_bytes)}</td>
      <td><span className="idmono">{a.sha256.slice(0, 16)}</span><Copy text={a.sha256} /></td>
      <td className="small">{a.note}</td>
      <td onClick={(e) => e.stopPropagation()}>
        <a href={api.artifactUrl(a.sha256, basename(a.original_path))} download>download</a>
      </td>
    </tr>
  );

  const table = (items: ArtifactRec[]) => (
    <table className="data">
      <thead>
        <tr><th>original path</th><th>type</th><th>size</th><th>sha256</th><th>note</th><th></th></tr>
      </thead>
      <tbody>{items.map(row)}</tbody>
    </table>
  );

  const grid = (items: ArtifactRec[]) => (
    <div className="artgrid">
      {items.map((a) => (
        <Tile key={a.sha256} a={a} selected={sel?.sha256 === a.sha256}
              onClick={() => setSel(sel?.sha256 === a.sha256 ? null : a)} />
      ))}
    </div>
  );

  return (
    <>
      <div className="dashbar">
        <span className="setlabel">view</span>
        <span className="viewseg">
          <button className={pageView === "groups" ? "active" : ""}
                  title="group artifacts by media type"
                  onClick={() => setPageViewPersist("groups")}>▤ groups</button>
          <button className={pageView === "list" ? "active" : ""}
                  title="one flat table"
                  onClick={() => setPageViewPersist("list")}>☰ list</button>
        </span>
        <span className="muted small">click an artifact to preview it</span>
      </div>

      <div className={sel ? "artsplit" : undefined}>
        <div style={{ minWidth: 0 }}>
          {pageView === "list" ? (
            <div className="panel">{table(artifacts)}</div>
          ) : (
            GROUP_ORDER.filter((g) => groups.has(g)).map((g) => {
              const gv = groupViews[g] ?? "grid";
              return (
                <div className="panel" key={g}>
                  <div className="grouptop">
                    <h3 style={{ margin: 0 }}>{GROUP_ICON[g]} {g} ({groups.get(g)!.length})</h3>
                    <span className="viewseg small">
                      <button className={gv === "grid" ? "active" : ""} title="grid with previews"
                              onClick={() => setGroupView(g, "grid")}>⊞</button>
                      <button className={gv === "list" ? "active" : ""} title="detail rows"
                              onClick={() => setGroupView(g, "list")}>☰</button>
                    </span>
                  </div>
                  {gv === "grid" ? grid(groups.get(g)!) : table(groups.get(g)!)}
                </div>
              );
            })
          )}
        </div>

        {sel && (
          <div className="panel artinspector">
            <div className="paneltop">
              <span style={{ flex: 1, fontWeight: 600, fontSize: "13.5px", minWidth: 0,
                             overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                    title={sel.original_path}>
                {GROUP_ICON[classify(sel)]} {basename(sel.original_path)}
              </span>
              <span className="panelbtns">
                <a href={api.artifactUrl(sel.sha256, basename(sel.original_path))} download>
                  <button>download</button>
                </a>
                <button onClick={() => setSel(null)}>✕</button>
              </span>
            </div>
            <div className="muted small" style={{ marginBottom: 8 }}>
              {sel.original_path} · {fmtBytes(sel.size_bytes)}
              {sel.note && <> · {sel.note}</>}
            </div>
            <Viewer a={sel} tensor={(sha) => <TensorViewer sha256={sha} />} />
          </div>
        )}
      </div>
    </>
  );
}
