import { useCallback, useEffect, useState } from "react";
import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { Me, TZ_CHANGED, api, getTzMode, localTzLabel, setTzMode } from "./api";
import { AuthCtx } from "./auth";
import BoardPage from "./pages/BoardPage";
import BoardsPage from "./pages/BoardsPage";
import LoginPage from "./pages/LoginPage";
import DiffPage from "./pages/DiffPage";
import ExperimentPage from "./pages/ExperimentPage";
import ExperimentsPage from "./pages/ExperimentsPage";
import GraphPage from "./pages/GraphPage";
import NodeDetail from "./pages/NodeDetail";
import Placeholder from "./pages/Placeholder";
import RunPage from "./pages/RunPage";
import SearchPage from "./pages/SearchPage";

export default function App() {
  const [store, setStore] = useState<string>("");
  const [auth, setAuth] = useState<Me | null>(null);
  const [tz, setTz] = useState(getTzMode());

  // fmtDate reads the preference at render time, so re-rendering the root
  // restamps every timestamp in the tree without remounting the pages
  useEffect(() => {
    const sync = () => setTz(getTzMode());
    window.addEventListener(TZ_CHANGED, sync);
    return () => window.removeEventListener(TZ_CHANGED, sync);
  }, []);

  const refreshMe = useCallback(() => {
    api.me().then(setAuth).catch(() => setAuth({ auth_enabled: false, user: null }));
  }, []);

  useEffect(() => {
    api.health().then((h) => setStore(h.store)).catch(() => setStore("(api unreachable)"));
    refreshMe();
    // any 401 (expired session, revoked token) drops us back to the login gate
    window.addEventListener("mlp:unauthorized", refreshMe);
    return () => window.removeEventListener("mlp:unauthorized", refreshMe);
  }, [refreshMe]);

  if (auth === null) return null;
  if (auth.auth_enabled && !auth.user) return <LoginPage onLogin={refreshMe} />;

  const logout = async () => {
    await api.logout();
    refreshMe();
  };

  return (
    <AuthCtx.Provider value={auth}>
    <div className="shell">
      <header className="topbar">
        <div className="brand">
          ml-<span>party</span>
        </div>
        <div className="store" title={store}>{store}</div>
        <button
          className="linkish tz-toggle"
          onClick={() => setTzMode(tz === "utc" ? "local" : "utc")}
          title={tz === "utc"
            ? `Times are shown in UTC — switch to your local zone (${localTzLabel()})`
            : `Times are shown in your local zone — switch to UTC`}
        >
          {tz === "utc" ? "UTC" : localTzLabel()}
        </button>
        {auth.user && (
          <div className="whoami">
            <span title={`role: ${auth.user.role}`}>{auth.user.username}</span>
            <button className="linkish" onClick={logout}>sign out</button>
          </div>
        )}
      </header>
      <aside className="sidebar">
        <div className="section">Workspace</div>
        <NavLink to="/experiments">Experiments</NavLink>
        <NavLink to="/boards">Boards</NavLink>
        <NavLink to="/data">Data</NavLink>
        <NavLink to="/models">Models</NavLink>
        <div className="section">Knowledge</div>
        <NavLink to="/search">Search</NavLink>
        <NavLink to="/graph">Graph</NavLink>
        <div className="section">Tools</div>
        <NavLink to="/diff">Compare runs</NavLink>
      </aside>
      <main className="content">
        <Routes>
          <Route path="/" element={<Navigate to="/experiments" replace />} />
          <Route path="/experiments" element={<ExperimentsPage />} />
          <Route path="/experiment/:id" element={<ExperimentPage />} />
          <Route path="/run/:id" element={<RunPage />} />
          <Route path="/board/:sha" element={<BoardPage />} />
          <Route path="/boards" element={<BoardsPage />} />
          <Route path="/node/:ref" element={<NodeDetail />} />
          <Route path="/graph" element={<GraphPage />} />
          <Route path="/search" element={<SearchPage />} />
          <Route path="/diff" element={<DiffPage />} />
          <Route
            path="/data"
            element={
              <Placeholder
                title="Data"
                text="Planned: datasets as first-class nodes, aggregated from the runs'
                      data_refs (uri + fingerprint) — which runs used which data, and
                      whether a dataset changed under a result. The refs are already
                      captured on every run today; this page will aggregate them."
              />
            }
          />
          <Route
            path="/models"
            element={
              <Placeholder
                title="Models"
                text="Planned: model registry over the artifact store — checkpoints are
                      already content-addressed artifacts on their runs; this page will
                      collect them into named, versioned models with lineage back to
                      the producing run."
              />
            }
          />
        </Routes>
      </main>
    </div>
    </AuthCtx.Provider>
  );
}
