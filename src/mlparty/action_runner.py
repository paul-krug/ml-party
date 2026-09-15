"""Detached action runner: executes ONE action command and records its
outcome on the invocation node. A separate process (not a thread) so the
outcome is recorded even when the invoking surface — a short-lived CLI, a
restarting server — exits first.

Invoked by actions.invoke() as:
    python -m mlparty.action_runner <store_root> <node_id> <log_path> -- <command>
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from .actions import OUTPUT_TAIL_BYTES
from .models import utcnow
from .store import Store


def main(argv: list[str]) -> int:
    sep = argv.index("--")
    store_root, node_id, log_path = argv[:sep]
    command = argv[sep + 1]

    with open(log_path, "wb") as log:
        # shell=True is the design: the registered template IS the allowlist,
        # and every substituted value was shlex-quoted by actions.render()
        code = subprocess.call(command, shell=True,
                               stdout=log, stderr=subprocess.STDOUT)
    try:
        data = Path(log_path).read_bytes()
    except OSError:
        data = b""
    tail = data[-OUTPUT_TAIL_BYTES:].decode("utf-8", errors="replace")
    Store(store_root).update_node(node_id, {
        "status": "exited", "exit_code": code, "output_tail": tail,
        "ended_at": utcnow().isoformat(),
    })
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
