/* ml-party board helper — served at /boards-lib/mlparty.js (same host as the
 * read-only API, so `<script src="/boards-lib/mlparty.js">` passes the board
 * CSP). Optional sugar over fetch(); everything it does can be done by hand.
 * Boards remain read-only: there are deliberately no write helpers here. */
(function () {
  "use strict";

  // Under auth (R6) the UI passes a short-lived read token to the sandboxed
  // board via ?bt= (opaque origins carry no cookies). Attach it everywhere.
  const BT = new URLSearchParams(window.location.search).get("bt");

  function withToken(path) {
    if (!BT) return path;
    return path + (path.includes("?") ? "&" : "?") + "bt=" + encodeURIComponent(BT);
  }

  async function api(path) {
    const r = await fetch(withToken(path), { headers: { accept: "application/json" } });
    if (!r.ok) throw new Error("ml-party API " + r.status + " on " + path);
    return r.json();
  }

  const mlparty = {
    api,

    /** Full node document + edges: node(ref) -> {node, edges_out, edges_in}. */
    node: (ref, opts) =>
      api("/api/nodes/" + encodeURIComponent(ref) +
          (opts && opts.metrics ? "?metrics=true" : "")),

    /** Metric records for a run: [{ts, name, value, step?}, ...].
     *  Optionally filtered to one series with {name}. */
    metrics: async (runId, opts) => {
      const q = new URLSearchParams();
      if (opts && opts.name) q.set("name", opts.name);
      const d = await api("/api/runs/" + encodeURIComponent(runId) +
                          "/metrics" + (q.size ? "?" + q : ""));
      return d.records;
    },

    /** Knowledge-graph search: query("wavlm ablation", {type: "run"}). */
    query: (q, opts) => {
      const p = new URLSearchParams({ q });
      for (const k of ["mode", "type", "limit"])
        if (opts && opts[k] != null) p.set(k, String(opts[k]));
      return api("/api/query?" + p);
    },

    /** Board gallery: boards({experiment_id}) -> [{sha256, title, ...}]. */
    boards: (opts) => {
      const p = new URLSearchParams();
      if (opts && opts.experiment_id) p.set("experiment_id", opts.experiment_id);
      return api("/api/boards" + (p.size ? "?" + p : ""));
    },

    /** src= URL for embedding a stored artifact (img/audio/video). */
    artifactUrl: (sha256, mediaType, name) => {
      const p = new URLSearchParams({ inline: "true" });
      if (mediaType) p.set("media_type", mediaType);
      if (name) p.set("name", name);
      return withToken("/api/artifacts/" + sha256 + "?" + p);
    },

    /** Live-tail a run's metrics over SSE. onRecord({ts, name, value, step?})
     *  per record; optional onEnd({status}) when the run leaves 'open'.
     *  Returns a stop() function. */
    stream: (runId, onRecord, onEnd) => {
      const es = new EventSource(withToken(
        "/api/runs/" + encodeURIComponent(runId) + "/metrics/stream"));
      es.onmessage = (ev) => onRecord(JSON.parse(ev.data));
      es.addEventListener("end", (ev) => {
        es.close();
        if (onEnd) onEnd(JSON.parse(ev.data));
      });
      return () => es.close();
    },
  };

  window.mlparty = mlparty;
})();
