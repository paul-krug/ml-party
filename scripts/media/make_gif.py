#!/usr/bin/env python
"""Regenerate the README hero GIF (.github/media/mlparty.gif) end to end.

Fully self-contained: seeds a synthetic demo store in a temp dir, serves the
real web UI against it, records the narrative slides (scripts/media/slides/)
and three live UI scenes with a headless browser, and assembles everything
with cross-fades into one GIF. Rerun it whenever the UI or the story changes.

    pip install -e .[dev-media]   # playwright, imageio-ffmpeg, numpy
    (cd ui && npm install && npm run build)
    python scripts/media/make_gif.py [--out .github/media/mlparty.gif]

Uses the system chromium by default (CHROMIUM env overrides); the UI bundle
must be built. Takes ~3 minutes; everything happens in a temp directory.
"""
from __future__ import annotations

import argparse
import functools
import http.server
import json
import math
import os
import random
import re
import shutil
import struct
import subprocess
import tempfile
import threading
import time
import zlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent.parent
SLIDES = Path(__file__).resolve().parent / "slides"
UI_PORT, SLIDE_PORT = 7362, 7363
FADE = 0.5
CROP = "crop=1230:650:210:44"  # content area of the 1440x810 viewport

# ------------------------------------------------------------------ seeding

def _png(path: Path, arr: np.ndarray) -> None:
    h, w, _ = arr.shape
    raw = b"".join(b"\x00" + arr[i].tobytes() for i in range(h))

    def chunk(tag: bytes, data: bytes) -> bytes:
        c = tag + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c))

    path.write_bytes(b"\x89PNG\r\n\x1a\n"
                     + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def _viridis(x: np.ndarray) -> np.ndarray:
    stops = np.array([[68, 1, 84], [33, 145, 140], [253, 231, 37]], float)
    x = np.clip(x, 0, 1) * 2
    i = np.minimum(x.astype(int), 1)
    f = (x - i)[..., None]
    return ((1 - f) * stops[i] + f * stops[i + 1]).astype(np.uint8)


BOARD_HTML = """<!doctype html><html><head><meta charset="utf-8">
<title>LR &amp; augmentation sweep — live report</title>
<script src="/boards-lib/mlparty.js"></script>
<style>
 body{font:14px/1.5 system-ui,sans-serif;margin:0;padding:26px 30px;
      background:#14161a;color:#e6e8eb;max-width:960px}
 h1{font-size:19px;margin:0 0 2px} .sub{color:#9aa2ad;font-size:12.5px;margin-bottom:18px}
 table{border-collapse:collapse;width:100%} th,td{text-align:left;padding:7px 10px;
      border-bottom:1px solid #2a2f36} th{color:#9aa2ad;font-size:11.5px;text-transform:uppercase}
 td.num{font-variant-numeric:tabular-nums} .best td{background:rgba(90,200,130,.08)}
 .v{font-size:11.5px;padding:1px 8px;border-radius:9px}
 .confirmed{background:#1e3a2a;color:#7fd49a}.refuted{background:#3a1e1e;color:#d47f7f}
 .open{background:#1e2c3a;color:#7fb5d4}
 .bar{height:7px;background:#2a2f36;border-radius:4px;overflow:hidden}
 .bar>div{height:100%;background:#5ac882}
 .note{color:#9aa2ad;font-size:12px;margin-top:16px}
</style></head><body>
<h1>LR &amp; augmentation sweep</h1>
<div class="sub">live report — numbers re-fetched from the store on every open</div>
<table><thead><tr><th>run</th><th>verdict</th><th>val_acc</th><th></th></tr></thead>
<tbody id="tb"></tbody></table>
<div class="note">Written by the tracking agent as an experiment board. The winning
recipe (cosine schedule) is the new default; heavy augmentation underfits at this
budget. Bars scale between 85% and the sweep best.</div>
<script>
(async () => {
  const runs = await mlparty.api("/api/nodes?type=run&experiment_id=__EXP__&limit=50");
  const rows = [];
  for (const r of runs) {
    const d = await mlparty.node(r.id);
    rows.push({t: d.node.title, v: d.node.result?.verdict ?? d.node.status,
               a: d.node.metrics_summary?.val_acc ?? null});
  }
  rows.sort((x, y) => (y.a ?? 0) - (x.a ?? 0));
  const best = rows[0].a;
  document.getElementById("tb").innerHTML = rows.map((r, i) => `
    <tr${i === 0 ? ' class="best"' : ""}><td>${r.t}</td>
    <td><span class="v ${r.v}">${r.v}</span></td>
    <td class="num">${r.a != null ? (100 * r.a).toFixed(1) + "%" : "—"}</td>
    <td style="width:200px"><div class="bar"><div style="width:${
      r.a ? Math.max(4, 100 * (r.a - 0.85) / (best - 0.85)) : 0}%"></div></div></td></tr>`
  ).join("");
})();
</script></body></html>"""


def seed(root: Path) -> dict:
    """Synthetic 'resnet-cifar10 sweep' store: 3 finalized runs (one refuted),
    one open+live run, artifacts (images/tensors/checkpoint), a note with
    edges, and an experiment-level board. Entirely fabricated data."""
    from mlparty.core import MlParty

    random.seed(7)
    np.random.seed(7)
    files = root / "files"
    files.mkdir(parents=True)
    store = root / ".mlparty"

    yy, xx = np.mgrid[0:224, 0:224] / 224.0
    def blob(cx, cy, s):
        return np.exp(-(((xx - cx) ** 2 + (yy - cy) ** 2) / s))
    _png(files / "confusion_matrix.png",
         _viridis(np.kron(np.random.rand(10, 10) * 0.25 + np.eye(10) * 0.7,
                          np.ones((22, 22)))[:220, :220]))
    _png(files / "loss_landscape.png",
         _viridis(blob(.3, .35, .04) * .9 + blob(.7, .6, .12) * .5
                  + np.random.rand(224, 224) * .08))
    _png(files / "saliency_overlay.png",
         _viridis(blob(.5, .45, .02) + blob(.42, .6, .01) * .7
                  + np.random.rand(224, 224) * .05))

    t = np.linspace(0, 4 * math.pi, 64)
    g64 = np.exp(-(((np.mgrid[0:64, 0:64][1] / 64 - .5) ** 2
                    + (np.mgrid[0:64, 0:64][0] / 64 - .5) ** 2) / .12))
    maps = np.stack([np.outer(np.sin(t * f / 8 + p), np.cos(t * f / 9)) * g64
                     for f, p in zip(range(1, 17), np.random.rand(16) * 6)])
    np.save(files / "feature_maps.npy", maps.astype(np.float32))
    np.save(files / "attention.npy",
            (np.random.rand(8, 128, 128) ** 3
             * np.kron(g64, np.ones((2, 2)))[None]).astype(np.float32))
    (files / "best.pt").write_bytes(np.random.bytes(3 * 1024 * 1024))
    (files / "train_log.txt").write_text("\n".join(
        f"epoch {e:03d}  train_loss {2.1 * math.exp(-e / 18) + 0.12:.4f}"
        f"  val_acc {min(0.93, 0.42 + e * 0.011):.4f}" for e in range(48)))
    (files / "config.json").write_text(json.dumps(
        {"model": "resnet18", "lr": 0.1, "schedule": "cosine", "epochs": 48,
         "batch_size": 128, "augment": ["crop", "flip"], "seed": 7}, indent=2))

    party = MlParty.init(store)
    party.project_ensure("vision-demo", "demo project for the README", created_by="agent")
    exp = party.experiment_ensure(
        "vision-demo", "resnet-cifar10 lr & augmentation sweep",
        "which schedule/augmentation recipe gives the best val accuracy "
        "for the resnet baseline?", created_by="agent")

    def curves(n, floor, wobble, acc_cap):
        tr, va, ac, lr = [], [], [], []
        for s in range(n):
            e = s / n
            tr.append(2.2 * math.exp(-e * 4.2) + floor + random.gauss(0, wobble))
            if s % 25 == 0:
                va.append((s, 2.3 * math.exp(-e * 3.6) + floor + 0.06
                           + random.gauss(0, wobble)))
                ac.append((s, min(acc_cap, 0.35 + (acc_cap - 0.3)
                                  * (1 - math.exp(-e * 3))) + random.gauss(0, 0.006)))
            lr.append(0.05 * (1 + math.cos(math.pi * e)) / 2 + 0.001)
        return tr, va, ac, lr

    def make_run(title, purpose, hypo, params, floor, cap, verdict, summary,
                 derives=None, steps=1200):
        out = party.run_start(experiment=exp["id"], title=title, purpose=purpose,
                              hypothesis=hypo, parameters=params,
                              derives_from=derives or [], seed=7, created_by="agent",
                              python_exe="/nonexistent/python", source_root=str(files))
        rid = out["run_id"]
        tr, va, ac, lr = curves(steps, floor, 0.015, cap)
        for s, v in enumerate(tr):
            party.store.append_metric(rid, "train_loss", round(v, 5), s)
            party.store.append_metric(rid, "lr", round(lr[s], 6), s)
        for s, v in va:
            party.store.append_metric(rid, "val_loss", round(v, 5), s)
        for s, v in ac:
            party.store.append_metric(rid, "val_acc", round(v, 5), s)
        best = max(v for _, v in ac)
        party.run_finalize(
            rid, method="48 epochs on the standard split; single consumer GPU; "
            "mixed precision; metrics logged per step via mlparty.attach()",
            result={"summary": summary.format(acc=100 * best), "verdict": verdict,
                    "metrics": {"val_acc": round(best, 4),
                                "final_train_loss": round(tr[-1], 4)}},
            reproduce=f"python train.py --config configs/{title.split()[0]}.yaml --seed 7",
            created_by="agent")
        now = datetime.now(UTC)
        party.store.update_node(rid, {
            "started_at": (now - timedelta(minutes=48)).isoformat(),
            "ended_at": (now - timedelta(minutes=7)).isoformat()})
        return rid

    r1 = make_run("resnet18 baseline", "establish the reference accuracy for the sweep",
                  "exploratory: where does the plain recipe land?",
                  {"model": "resnet18", "lr": 0.1, "schedule": "step",
                   "augment": "basic", "epochs": 48, "batch_size": 128},
                  0.16, 0.905, "confirmed",
                  "plain step-schedule recipe lands at {acc:.1f}% val accuracy — "
                  "the bar every sweep arm has to beat")
    r2 = make_run("resnet18 + cosine lr", "test the cosine schedule against the baseline",
                  "cosine annealing should add ~1pt val_acc by avoiding the "
                  "late-epoch step cliff",
                  {"model": "resnet18", "lr": 0.1, "schedule": "cosine",
                   "augment": "basic", "epochs": 48, "batch_size": 128},
                  0.12, 0.928, "confirmed",
                  "cosine schedule lifts val accuracy to {acc:.1f}% at identical "
                  "budget — adopting it as the new default", derives=[r1])
    r3 = make_run("resnet18 + heavy augmentation",
                  "test whether aggressive augmentation stacks with the cosine schedule",
                  "randaugment+cutmix on top of cosine should add another point",
                  {"model": "resnet18", "lr": 0.1, "schedule": "cosine",
                   "augment": "randaugment+cutmix", "epochs": 48, "batch_size": 128},
                  0.19, 0.897, "refuted",
                  "heavy augmentation UNDERPERFORMS at this budget ({acc:.1f}%) — "
                  "the model underfits; would need 3x epochs to pay off", derives=[r2])

    for name, mt, note in [("confusion_matrix.png", "image/png", "best epoch, val split"),
                           ("loss_landscape.png", "image/png", "2D slice around the minimum"),
                           ("saliency_overlay.png", "image/png", None),
                           ("feature_maps.npy", None, "conv3 activations, 16 channels"),
                           ("attention.npy", None, None),
                           ("best.pt", None, "best val_acc checkpoint"),
                           ("train_log.txt", "text/plain", None),
                           ("config.json", "application/json", None)]:
        party.run_log_artifact(r2, files / name, media_type=mt, note=note)

    party.note_create("cosine schedule is the new default",
                      "The sweep settles it: cosine annealing beats the step schedule "
                      "at identical budget, and heavy augmentation does not stack at "
                      "48 epochs (underfits). Default recipe going forward: resnet18 "
                      "+ cosine + basic augmentation.", kind="insight",
                      edges=[{"dst": r2, "type": "confirms"},
                             {"dst": r3, "type": "refutes"}], created_by="agent")

    out = party.run_start(experiment=exp["id"], title="resnet34 + cosine lr",
                          purpose="check whether the cosine win transfers to the "
                          "deeper model",
                          hypothesis="resnet34 should reach ~93.5% with the same recipe",
                          parameters={"model": "resnet34", "lr": 0.1,
                                      "schedule": "cosine", "augment": "basic",
                                      "epochs": 48, "batch_size": 128},
                          derives_from=[r2], seed=7, created_by="agent",
                          python_exe="/nonexistent/python", source_root=str(files))
    r4 = out["run_id"]
    tr, va, ac, lr = curves(700, 0.10, 0.015, 0.935)
    for s, v in enumerate(tr):
        party.store.append_metric(r4, "train_loss", round(v, 5), s)
        party.store.append_metric(r4, "lr", round(lr[s], 6), s)
    for s, v in va[:24]:
        party.store.append_metric(r4, "val_loss", round(v, 5), s)
    for s, v in ac[:24]:
        party.store.append_metric(r4, "val_acc", round(v, 5), s)
    party.store.update_node(r4, {"started_at": (
        datetime.now(UTC) - timedelta(minutes=26)).isoformat()})
    party.store.touch_heartbeat(r4)

    board = root / "sweep_report.html"
    board.write_text(BOARD_HTML.replace("__EXP__", exp["id"]))
    ref = party.experiment_log_artifact(exp["id"], board, media_type="text/html",
                                        note="LR & augmentation sweep — live report")
    return {"party": party, "exp": exp["id"], "r2": r2, "r4": r4,
            "board": ref["sha256"]}

# ---------------------------------------------------------------- recording

def chromium_path() -> str:
    for cand in (os.environ.get("CHROMIUM"), shutil.which("chromium"),
                 shutil.which("chromium-browser"), shutil.which("google-chrome")):
        if cand:
            return cand
    raise SystemExit("no chromium found — set CHROMIUM=/path/to/chromium")


def banner(pg, title: str, sub: str = "") -> None:
    pg.evaluate("""([t, s]) => {
      let b = document.getElementById('gifbanner');
      if (!b) {
        b = document.createElement('div'); b.id = 'gifbanner';
        Object.assign(b.style, {position: 'fixed', left: '50%', bottom: '146px',
          transform: 'translateX(-50%)', zIndex: 99999, padding: '13px 26px',
          background: 'rgba(9,11,15,0.93)', border: '1px solid rgba(110,160,255,0.4)',
          borderRadius: '12px', color: '#eef2f7', whiteSpace: 'nowrap',
          font: '600 27px/1.25 system-ui,sans-serif', textAlign: 'center',
          boxShadow: '0 6px 30px rgba(0,0,0,0.55)', transition: 'opacity 0.7s',
          opacity: '0', pointerEvents: 'none'});
        document.body.appendChild(b);
      }
      b.innerHTML = t + (s ? '<div style="font:400 15px/1.4 system-ui,sans-serif;' +
        'color:#9aa2ad;margin-top:3px">' + s + '</div>' : '');
      requestAnimationFrame(() => { b.style.opacity = '1'; });
    }""", [title, sub])


def record_all(ids: dict, out: Path) -> None:
    from playwright.sync_api import sync_playwright

    base = f"http://127.0.0.1:{UI_PORT}"
    party = ids["party"]
    stop = threading.Event()

    def feeder() -> None:
        records, _ = party.store.read_metrics(ids["r4"])
        step = max((r.get("step") or 0) for r in records) + 1
        while not stop.is_set():
            for _ in range(3):
                target = 0.06 * math.exp(-(step - 700) / 900) + 0.095
                loss = target + abs(random.gauss(0, 0.008))
                party.store.append_metric(ids["r4"], "train_loss", round(loss, 5), step)
                party.store.append_metric(ids["r4"], "lr", 0.001, step)
                if step % 25 == 0:
                    party.store.append_metric(ids["r4"], "val_loss",
                                              round(loss + 0.09, 5), step)
                    party.store.append_metric(
                        ids["r4"], "val_acc",
                        round(min(0.936, 0.86 + step / 14000)
                              + random.gauss(0, 0.003), 5), step)
                step += 1
            party.store.touch_heartbeat(ids["r4"])
            time.sleep(0.1)

    threading.Thread(target=feeder, daemon=True).start()

    def dash(pg):
        pg.goto(f"{base}/#/run/{ids['r4']}")
        pg.wait_for_timeout(600)
        pg.click("div.tabs >> text=metrics")
        pg.wait_for_timeout(500)
        banner(pg, "View the dashboard — live",
               "metrics stream in over SSE while the training writes them")
        pg.wait_for_timeout(6200)

    def art(pg):
        pg.goto(f"{base}/#/run/{ids['r2']}")
        pg.wait_for_timeout(500)
        pg.click("div.tabs >> text=artifacts")
        pg.wait_for_timeout(500)
        banner(pg, "Browsing logged artifacts",
               "images, checkpoints — and .npy tensors sliced right in the browser")
        pg.click("text=feature_maps.npy")
        pg.wait_for_timeout(700)
        pg.evaluate("() => window.scrollTo({top: 130, behavior: 'smooth'})")
        pg.wait_for_timeout(500)
        for v in list(range(16)) + [8]:
            pg.evaluate("""(v) => {
                const el = document.querySelector('input[type=range]');
                const set = Object.getOwnPropertyDescriptor(
                    window.HTMLInputElement.prototype, 'value').set;
                set.call(el, String(v));
                el.dispatchEvent(new Event('input', {bubbles: true}));
            }""", v)
            pg.wait_for_timeout(260)
        pg.wait_for_timeout(400)

    def board(pg):
        pg.goto(f"{base}/#/board/{ids['board']}?name=sweep%20report")
        pg.wait_for_timeout(1400)
        banner(pg, "Boards — agent-authored live reports",
               "self-contained HTML views over the read-only API")
        pg.wait_for_timeout(3000)

    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=chromium_path(), headless=True,
                              args=["--no-sandbox", "--headless=new"])
        for name, ms in [("slide1", 5200), ("slide2", 5800),
                         ("slide3", 5800), ("slide5", 6200)]:
            ctx = b.new_context(viewport={"width": 1230, "height": 650},
                                color_scheme="dark", record_video_dir=str(out),
                                record_video_size={"width": 1230, "height": 650})
            pg = ctx.new_page()
            pg.goto(f"http://127.0.0.1:{SLIDE_PORT}/{name}.html")
            pg.wait_for_timeout(ms)
            ctx.close()
            Path(pg.video.path()).rename(out / f"{name}.webm")
            print(f"  {name} recorded")
        for name, fn in [("dash", dash), ("art", art), ("board", board)]:
            ctx = b.new_context(viewport={"width": 1440, "height": 810},
                                color_scheme="dark", record_video_dir=str(out),
                                record_video_size={"width": 1440, "height": 810})
            pg = ctx.new_page()
            fn(pg)
            ctx.close()
            Path(pg.video.path()).rename(out / f"{name}.webm")
            print(f"  {name} recorded")
        b.close()
    stop.set()

# ---------------------------------------------------------------- assembly

def ffmpeg_exe() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def duration(path: Path) -> float:
    out = subprocess.run([ffmpeg_exe(), "-i", str(path)],
                         capture_output=True, text=True, check=False)
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", out.stderr)
    h, mnt, s = m.groups()
    return int(h) * 3600 + int(mnt) * 60 + float(s)


def assemble(vids: Path, gif: Path) -> None:
    segs = [(vids / "slide1.webm", 0.0, False), (vids / "slide2.webm", 0.0, False),
            (vids / "slide3.webm", 0.0, False), (vids / "dash.webm", 1.9, True),
            (vids / "art.webm", 1.7, True), (vids / "board.webm", 1.6, True),
            (vids / "slide5.webm", 0.0, False)]
    durs, filters = [], []
    for i, (path, trim, crop) in enumerate(segs):
        durs.append(duration(path) - trim)
        ops = ([CROP] if crop else []) + [
            f"trim=start={trim}", "setpts=PTS-STARTPTS", "fps=30",
            "scale=1000:-1:flags=lanczos", "format=yuv420p"]
        filters.append(f"[{i}:v]{','.join(ops)}[v{i}]")
    prev, total = "v0", durs[0]
    for i in range(1, len(segs)):
        off = total - FADE
        filters.append(f"[{prev}][v{i}]xfade=transition=fade:"
                       f"duration={FADE}:offset={off:.3f}[x{i}]")
        total = off + durs[i]
        prev = f"x{i}"
    filters.append(f"[{prev}]fps=10,split[s0][s1]")
    filters.append("[s0]palettegen=stats_mode=diff[p]")
    filters.append("[s1][p]paletteuse=dither=bayer:bayer_scale=4:"
                   "diff_mode=rectangle[gif]")
    cmd = [ffmpeg_exe(), "-y", "-loglevel", "error"]
    for path, _, _ in segs:
        cmd += ["-i", str(path)]
    cmd += ["-filter_complex", ";".join(filters), "-map", "[gif]", str(gif)]
    subprocess.run(cmd, check=True)
    print(f"  {gif} ({gif.stat().st_size / 1e6:.1f} MB, ~{total:.0f}s)")

# --------------------------------------------------------------------- main

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(REPO / ".github/media/mlparty.gif"))
    args = ap.parse_args()

    ui_dist = REPO / "ui" / "dist"
    if not ui_dist.exists():
        raise SystemExit("ui/dist missing — build it: cd ui && npm install && npm run build")

    import uvicorn

    from mlparty.http_api import build_app

    with tempfile.TemporaryDirectory(prefix="mlparty-gif-") as tmp:
        root = Path(tmp)
        print("seeding demo store…")
        ids = seed(root)

        os.environ["ML_PARTY_UI_DIST"] = str(ui_dist)
        server = uvicorn.Server(uvicorn.Config(
            build_app(root / ".mlparty"), host="127.0.0.1", port=UI_PORT,
            log_level="warning"))
        threading.Thread(target=server.run, daemon=True).start()
        handler = functools.partial(http.server.SimpleHTTPRequestHandler,
                                    directory=str(SLIDES))
        slide_srv = http.server.ThreadingHTTPServer(("127.0.0.1", SLIDE_PORT), handler)
        threading.Thread(target=slide_srv.serve_forever, daemon=True).start()
        while not server.started:
            time.sleep(0.05)

        vids = root / "videos"
        vids.mkdir()
        print("recording…")
        record_all(ids, vids)
        print("assembling…")
        assemble(vids, Path(args.out))

        server.should_exit = True
        slide_srv.shutdown()


if __name__ == "__main__":
    main()
