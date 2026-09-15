import { useEffect, useMemo, useState } from "react";
import { BoardInfo, api } from "../api";
import BoardGallery from "../components/BoardGallery";

export default function BoardsPage() {
  const [boards, setBoards] = useState<BoardInfo[] | null>(null);
  const [q, setQ] = useState("");

  useEffect(() => {
    api.boards().then(setBoards).catch(console.error);
  }, []);

  const shown = useMemo(() => {
    if (!boards) return [];
    const needle = q.toLowerCase();
    return boards.filter(
      (b) =>
        b.title.toLowerCase().includes(needle) ||
        b.node_title.toLowerCase().includes(needle),
    );
  }, [boards, q]);

  if (!boards) return <div className="muted">loading…</div>;
  return (
    <div>
      <h1>Boards</h1>
      <p className="muted" style={{ marginTop: 0 }}>
        Agent-authored live views — HTML artifacts rendered sandboxed, attached
        to the run or experiment that produced them.
      </p>
      <div className="searchrow">
        <input
          type="text"
          style={{ flex: 1, maxWidth: 360 }}
          placeholder="filter boards…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
      </div>
      <div className="panel" style={{ marginTop: 12 }}>
        <BoardGallery boards={shown} />
      </div>
    </div>
  );
}
