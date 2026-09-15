#!/usr/bin/env python
"""Tiny live-run demo: starts a REAL run through the full contract, streams a
decaying loss for a while (watch it live in the web UI or `mlp tail`), then
finalizes. Safe to run repeatedly; lands in project 'ml-party-demo'.

  .venv/bin/python scripts/demo_live_run.py --store .mlparty --steps 120 --sleep 0.25
"""
from __future__ import annotations

import argparse
import math
import time

from mlparty.client import start_run


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default=".mlparty")
    ap.add_argument("--steps", type=int, default=120)
    ap.add_argument("--sleep", type=float, default=0.25)
    args = ap.parse_args()

    from mlparty.core import MlParty
    MlParty.open(args.store).experiment_ensure(
        "ml-party-demo", "live-demo",
        "toy runs that exercise the live metric path end to end", created_by="demo")

    handle = start_run(
        args.store, experiment="live-demo",
        title=f"demo decay ({args.steps} steps)",
        purpose="exercise the live metric path end to end: client -> journal -> SSE -> chart",
        hypothesis="exploratory: does the live view track the writer in real time?",
        parameters={"steps": args.steps, "sleep_s": args.sleep, "decay": 0.97},
        source_root="scripts",
        created_by="demo",
    )
    print(f"run {handle.run_id} started — watch it at /#/node/{handle.run_id}")

    loss = 2.0
    for step in range(args.steps):
        loss = loss * 0.97 + 0.02 * math.sin(step / 5)
        handle.log_metric("loss", round(loss, 5), step=step)
        if step % 10 == 0:
            handle.log_metric("val_loss", round(loss * 1.15 + 0.05, 5), step=step)
        time.sleep(args.sleep)

    handle.finalize(
        method="synthetic exponential decay with a sine wobble, logged step by step "
               "through mlparty.client to exercise the live path",
        result={"summary": "loss decayed as constructed and the live stream tracked it; "
                           "this run exists so the UI has a real metric series to render",
                "verdict": "confirmed",
                "metrics": {"final_loss": round(loss, 5)}},
        reproduce=f"python scripts/demo_live_run.py --steps {args.steps} --sleep {args.sleep}",
    )
    print("finalized")


if __name__ == "__main__":
    main()
