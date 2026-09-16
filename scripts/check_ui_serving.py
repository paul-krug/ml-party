#!/usr/bin/env python
"""Assert an INSTALLED mlparty serves the bundled SPA.

The test suite runs against a source checkout where `ui/dist` may not exist,
so the packaged-and-served path — the only one a `pip install` user ever
takes — was never exercised. Run this against an installed wheel:

    python scripts/check_ui_serving.py
"""
from __future__ import annotations

import re
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

import uvicorn

from mlparty.core import MlParty
from mlparty.http_api import UI_DIST, build_app

PORT = 7391


def get(path: str) -> tuple[int, bytes]:
    with urllib.request.urlopen(f"http://127.0.0.1:{PORT}{path}", timeout=10) as r:
        return r.status, r.read()


def main() -> int:
    if not (UI_DIST / "index.html").is_file():
        print(f"FAIL: no SPA at {UI_DIST}")
        return 1

    root = Path(tempfile.mkdtemp()) / ".mlparty"
    MlParty.init(root)
    server = uvicorn.Server(uvicorn.Config(build_app(root), host="127.0.0.1",
                                           port=PORT, log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(60):
        try:
            get("/api/health")
            break
        except OSError:
            time.sleep(0.5)
    else:
        print("FAIL: server never came up")
        return 1

    failures = []
    root_div = b'<div id="root"'
    status, body = get("/")
    if status != 200 or root_div not in body:
        failures.append(f"index: status={status}, root div present={root_div in body}")

    # the page must reference assets that are actually served, not 404s
    assets = re.findall(rb'(?:src|href)="(/assets/[^"]+)"', body)
    if not assets:
        failures.append("index references no /assets/* bundle")
    for asset in assets:
        try:
            a_status, a_body = get(asset.decode())
        except Exception as e:  # noqa: BLE001 - report, don't raise
            failures.append(f"asset {asset.decode()}: {e}")
            continue
        if a_status != 200 or not a_body:
            failures.append(f"asset {asset.decode()}: status={a_status}, {len(a_body)} bytes")

    if get("/api/health")[0] != 200:
        failures.append("api health not 200")

    for f in failures:
        print(f"FAIL: {f}")
    if failures:
        return 1
    print(f"ok: SPA served from {UI_DIST} with {len(assets)} asset(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
