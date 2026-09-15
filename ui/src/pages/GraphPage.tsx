import { MarkerType, ReactFlow, type Edge, type Node } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import dagre from "dagre";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Card, EdgeRec, GraphData, TYPE_SLOT, api } from "../api";

const NODE_W = 230;
const NODE_H = 52;

function layout(cards: Card[], edgeRecs: EdgeRec[]): { nodes: Node[]; edges: Edge[] } {
  const ids = new Set(cards.map((c) => c.id));
  const usable = edgeRecs.filter((e) => ids.has(e.src) && ids.has(e.dst));

  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: "LR", nodesep: 22, ranksep: 90 });
  g.setDefaultEdgeLabel(() => ({}));
  cards.forEach((c) => g.setNode(c.id, { width: NODE_W, height: NODE_H }));
  usable.forEach((e) => g.setEdge(e.src, e.dst));
  dagre.layout(g);

  const nodes: Node[] = cards.map((c) => {
    const pos = g.node(c.id);
    return {
      id: c.id,
      position: { x: pos.x - NODE_W / 2, y: pos.y - NODE_H / 2 },
      data: {
        label: (
          <div
            className="rf-node"
            style={{ borderLeftColor: TYPE_SLOT[c.type] ?? "var(--muted)" }}
          >
            <div className="t">{c.title}</div>
            <div className="s">
              {c.type}
              {c.status ? ` · ${c.status}` : ""}
              {c.verdict ? ` · ${c.verdict}` : ""}
            </div>
          </div>
        ),
      },
      style: { width: NODE_W, padding: 0, border: "none", background: "transparent" },
    };
  });

  const edges: Edge[] = usable.map((e, i) => ({
    id: `${e.src}-${e.dst}-${e.type}-${i}`,
    source: e.src,
    target: e.dst,
    label: e.type,
    markerEnd: { type: MarkerType.ArrowClosed },
    style: { stroke: "var(--baseline)" },
    labelStyle: { fill: "var(--muted)", fontSize: 10 },
    labelBgStyle: { fill: "var(--surface)" },
  }));
  return { nodes, edges };
}

export default function GraphPage() {
  const nav = useNavigate();
  const [exps, setExps] = useState<Card[]>([]);
  const [sel, setSel] = useState("");
  const [hideStubs, setHideStubs] = useState(true);
  const [graph, setGraph] = useState<GraphData | null>(null);

  useEffect(() => {
    api.nodes({ type: "experiment" }).then(setExps).catch(console.error);
  }, []);
  useEffect(() => {
    api.graph(sel || undefined).then(setGraph).catch(console.error);
  }, [sel]);

  const { nodes, edges } = useMemo(() => {
    if (!graph) return { nodes: [], edges: [] };
    const cards = hideStubs
      ? graph.nodes.filter((c) => !c.tags?.includes("unreconstructed"))
      : graph.nodes;
    return layout(cards, graph.edges);
  }, [graph, hideStubs]);

  return (
    <div>
      <div className="searchrow">
        <select value={sel} onChange={(e) => setSel(e.target.value)}>
          <option value="">whole graph</option>
          {exps.map((e) => (
            <option key={e.id} value={e.id}>{e.title}</option>
          ))}
        </select>
        <label className="small" style={{ alignSelf: "center" }}>
          <input
            type="checkbox"
            checked={hideStubs}
            onChange={(e) => setHideStubs(e.target.checked)}
          />{" "}
          hide unreconstructed stubs
        </label>
        <span className="small muted" style={{ alignSelf: "center" }}>
          {Object.entries(TYPE_SLOT).map(([t, c]) => (
            <span key={t} className="chip" style={{ marginRight: 6 }}>
              <span className="dot" style={{ background: c }} /> {t}
            </span>
          ))}
        </span>
      </div>
      <div className="graphwrap">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodeClick={(_, node) => nav(`/node/${node.id}`)}
          fitView
          minZoom={0.1}
          proOptions={{ hideAttribution: true }}
          nodesDraggable={false}
          nodesConnectable={false}
          edgesFocusable={false}
        />
      </div>
    </div>
  );
}
