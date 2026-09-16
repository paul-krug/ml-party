"""A real run through the full contract, streaming live metrics.

Ships with the package so a fresh install has something to watch:
`python -m mlparty.demo --store .mlparty`. Safe to run repeatedly; lands
in project 'ml-party-demo'.
"""
from __future__ import annotations

import argparse
import math
import os
import time

from .client import start_run
from .core import MlParty


def run_demo(store: str = ".mlparty", steps: int = 120, sleep: float = 0.25) -> str:
    MlParty.open(store).experiment_ensure(
        "ml-party-demo", "live-demo",
        "toy runs that exercise the live metric path end to end", created_by="demo")

    handle = start_run(
        store, experiment="live-demo",
        title=f"demo decay ({steps} steps)",
        purpose="exercise the live metric path end to end: client -> journal -> SSE -> chart",
        hypothesis="exploratory: does the live view track the writer in real time?",
        parameters={"steps": steps, "sleep_s": sleep, "decay": 0.97},
        created_by="demo",
    )
    print(f"run {handle.run_id} started — watch it at /#/node/{handle.run_id}")

    loss = 2.0
    for step in range(steps):
        loss = loss * 0.97 + 0.02 * math.sin(step / 5)
        handle.log_metric("loss", round(loss, 5), step=step)
        if step % 10 == 0:
            handle.log_metric("val_loss", round(loss * 1.15 + 0.05, 5), step=step)
        time.sleep(sleep)

    handle.finalize(
        method="synthetic exponential decay with a sine wobble, logged step by step "
               "through mlparty.client to exercise the live path",
        result={"summary": "loss decayed as constructed and the live stream tracked it; "
                           "this run exists so the UI has a real metric series to render",
                "verdict": "confirmed",
                "metrics": {"final_loss": round(loss, 5)}},
        reproduce=f"python -m mlparty.demo --steps {steps} --sleep {sleep}",
    )
    print("finalized")
    return handle.run_id


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--store", default=os.environ.get("ML_PARTY_STORE", ".mlparty"),
                    help="store root (default: $ML_PARTY_STORE or ./.mlparty)")
    ap.add_argument("--steps", type=int, default=120)
    ap.add_argument("--sleep", type=float, default=0.25)
    args = ap.parse_args()
    run_demo(args.store, args.steps, args.sleep)


if __name__ == "__main__":
    main()
