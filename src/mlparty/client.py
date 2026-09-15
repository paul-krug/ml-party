"""In-process client for training scripts — the second writer (§1.3).

The agent brackets the run over MCP (start → finalize); the training process
attaches with `mlparty.attach()` (reading ML_PARTY_STORE / ML_PARTY_RUN set
by the launcher) and streams telemetry to the per-run journal.

Split repro capture (three-machine world): the machine that runs the code is
the only honest witness to its environment, so attaching patches the *actual*
invocation and hardware onto the run and captures the runtime env lock from
`sys.executable` (in the background — pip freeze is slow; finalize/fail joins
it so a completed run always carries it). A heartbeat thread marks liveness
so the UI and janitor can tell running from silently dead.
"""
from __future__ import annotations

import os
import sys
import threading
import traceback as tb_mod
from pathlib import Path
from typing import Any

from .capture import capture_env_lock, capture_hardware, capture_invocation
from .core import MlParty

ENV_STORE = "ML_PARTY_STORE"
ENV_RUN = "ML_PARTY_RUN"
ENV_HEARTBEAT = "ML_PARTY_HEARTBEAT"

DEFAULT_HEARTBEAT_SECONDS = 15.0


class RunHandle:
    def __init__(self, party: MlParty, run_id: str, install_excepthook: bool = True,
                 heartbeat_seconds: float | None = None, capture_env: bool = True):
        self.party = party
        self.run_id = run_id
        self._closed = False
        self._stop = threading.Event()
        self.party.store.update_node(run_id, {
            "invocation": capture_invocation("client").model_dump(mode="json"),
            "hardware": capture_hardware(captured_by="attach").model_dump(mode="json"),
        })
        self._env_thread: threading.Thread | None = None
        if capture_env:
            self._env_thread = threading.Thread(
                target=self._capture_runtime_env, name="mlparty-envlock", daemon=True)
            self._env_thread.start()
        if heartbeat_seconds is None:
            heartbeat_seconds = float(os.environ.get(ENV_HEARTBEAT,
                                                     DEFAULT_HEARTBEAT_SECONDS))
        if heartbeat_seconds > 0:
            self.party.store.touch_heartbeat(run_id)
            threading.Thread(target=self._heartbeat_loop, args=(heartbeat_seconds,),
                             name="mlparty-heartbeat", daemon=True).start()
        self._sync = None
        self._sync_lock = threading.Lock()
        try:
            from . import sync as sync_mod
            self._sync = sync_mod.from_store(self.party.store)
        except Exception:  # noqa: S110, BLE001 — sync is best-effort, never kills training
            pass
        if self._sync is not None:
            threading.Thread(
                target=self._sync_loop,
                args=(self.party.store.config.sync_interval_seconds,),
                name="mlparty-sync", daemon=True).start()
        if install_excepthook:
            self._install_excepthook()

    def log_metric(self, name: str, value: float, step: int | None = None) -> None:
        self.party.run_log_metric(self.run_id, name, value, step)

    def log_artifact(self, path: Path | str, media_type: str | None = None,
                     note: str | None = None) -> dict:
        return self.party.run_log_artifact(self.run_id, path, media_type, note)

    def finalize(self, method: str, result: dict[str, Any], reproduce: str,
                 edges: list[dict] | None = None, tags: list[str] | None = None) -> dict:
        self._flush_env_capture()
        out = self.party.run_finalize(self.run_id, method=method, result=result,
                                      reproduce=reproduce, edges=edges, tags=tags,
                                      created_by="client")
        self._close()
        return out

    def fail(self, what_failed: str, failure_class: str | None = None,
             why: str | None = None, traceback: str | None = None) -> dict:
        self._flush_env_capture()
        out = self.party.run_fail(self.run_id, what_failed=what_failed,
                                  failure_class=failure_class, why=why,
                                  traceback=traceback)
        self._close()
        return out

    # ------------------------------------------------------------- internals

    def _close(self) -> None:
        self._closed = True
        self._stop.set()
        self._final_flush()

    def _final_flush(self) -> None:
        if self._sync is None:
            return
        try:
            with self._sync_lock:
                self._sync.flush()
        except Exception:  # noqa: S110, BLE001 — sync is best-effort; mlp sync ships leftovers
            pass

    def _sync_loop(self, interval: float) -> None:
        while not self._stop.wait(max(1.0, interval)):
            try:
                with self._sync_lock:
                    self._sync.flush()
            except Exception:  # noqa: S110, BLE001 — offline is normal; the spool keeps everything
                pass

    def _capture_runtime_env(self) -> None:
        try:
            lock = capture_env_lock(sys.executable)
            ref = self.party.store.put_artifact_bytes(
                lock, original_path=sys.executable, media_type="text/plain",
                note="runtime env lock (attach)")
            self.party.store.update_node(self.run_id, {
                "env_lock_runtime": ref.model_dump(mode="json"),
            })
        except Exception:  # noqa: S110, BLE001 — capture is best-effort, never kills training
            pass

    def _flush_env_capture(self, timeout: float = 90.0) -> None:
        if self._env_thread is not None and self._env_thread.is_alive():
            self._env_thread.join(timeout=timeout)

    def _heartbeat_loop(self, interval: float) -> None:
        while not self._stop.wait(interval):
            try:
                self.party.store.touch_heartbeat(self.run_id)
            except Exception:  # noqa: S110, BLE001 — liveness is best-effort, never kills training
                pass

    def _install_excepthook(self) -> None:
        prev = sys.excepthook

        def hook(exc_type, exc, tb):
            if not self._closed:
                try:
                    self.fail(
                        what_failed=f"unhandled {exc_type.__name__}: {exc}",
                        failure_class="crash",
                        traceback="".join(tb_mod.format_exception(exc_type, exc, tb))[-8000:],
                    )
                except Exception:  # noqa: S110, BLE001 — the excepthook must never raise
                    pass
            prev(exc_type, exc, tb)

        sys.excepthook = hook


def attach(run_id: str | None = None, store: Path | str | None = None,
           **kwargs: Any) -> RunHandle:
    """Attach to a run the agent already started (env-var handshake)."""
    root = store or os.environ.get(ENV_STORE)
    rid = run_id or os.environ.get(ENV_RUN)
    if not root or not rid:
        raise RuntimeError(
            f"no run to attach to — set {ENV_STORE} and {ENV_RUN}, or pass store=/run_id=")
    return RunHandle(MlParty.open(root), rid, **kwargs)


def start_run(store: Path | str, experiment: str, title: str, purpose: str,
              hypothesis: str, parameters: dict[str, Any], **kwargs: Any) -> RunHandle:
    """Start a run from inside the training process itself (agentless use)."""
    party = MlParty.open(store)
    handle_kwargs = {k: kwargs.pop(k) for k in
                     ("install_excepthook", "heartbeat_seconds", "capture_env")
                     if k in kwargs}
    out = party.run_start(experiment=experiment, title=title, purpose=purpose,
                          hypothesis=hypothesis, parameters=parameters,
                          created_by=kwargs.pop("created_by", "client"), **kwargs)
    return RunHandle(party, out["run_id"], **handle_kwargs)
