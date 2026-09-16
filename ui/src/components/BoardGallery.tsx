import { Link } from "react-router-dom";
import { BoardInfo, fmtDate } from "../api";

// the shared formatter, so a board and its run never disagree about when it
// happened — this one rendered local time while every other view showed UTC
const fmtWhen = fmtDate;

export default function BoardGallery({ boards, showCarrier = true }: {
  boards: BoardInfo[]; showCarrier?: boolean;
}) {
  if (boards.length === 0) return <div className="chart-empty">no boards yet</div>;
  return (
    <div className="artgrid">
      {boards.map((b) => (
        <a
          key={`${b.node_id}:${b.sha256}`}
          className="arttile boardcard"
          href={`#/board/${b.sha256}?name=${encodeURIComponent(b.title)}`}
        >
          <div className="tilethumb"><span className="tileicon">📊</span></div>
          <div className="tilename" title={b.title}>{b.title}</div>
          {showCarrier && (
            <div className="tilesize">
              on{" "}
              <Link
                to={b.node_type === "run" ? `/run/${b.node_id}` : `/experiment/${b.node_id}`}
                onClick={(e) => e.stopPropagation()}
              >
                {b.node_type === "experiment" ? `${b.node_title} (experiment)` : b.node_title}
              </Link>
            </div>
          )}
          <div className="tilesize">{fmtWhen(b.updated_at)}</div>
        </a>
      ))}
    </div>
  );
}
