"""Best-effort capture of the repro tuple's mechanical parts.

Everything here degrades gracefully: capture failures are recorded as
placeholder content, never raised — the contract only hard-requires what
only the author knows. `python_exe` lets an agent point env-lock capture at
the interpreter the training run will actually use (the MCP server's own
env is usually not the training env).
"""
from __future__ import annotations

import os
import platform
import shutil
import socket
import subprocess
import sys
from pathlib import Path

from .models import GpuInfo, Hardware, Invocation, ProjectGitRef

ENV_ALLOWLIST = (
    "CUDA_VISIBLE_DEVICES", "PYTHONPATH", "CONDA_DEFAULT_ENV",
    "VIRTUAL_ENV", "OMP_NUM_THREADS",
)

ENV_LOCK_PATH = ".mlparty/env.lock"

# The launcher's answer to "where is this job?", handed to the training process
# over the same env handshake as the run id — so any job system (jobpool,
# slurm, k8s, a submit script) can name itself without ml-party knowing it.
COMPUTE_ENV = {
    "system": "ML_PARTY_COMPUTE_SYSTEM",
    "job_id": "ML_PARTY_COMPUTE_JOB_ID",
    "url": "ML_PARTY_COMPUTE_URL",
}


def _run(cmd: list[str], timeout: int = 30) -> str | None:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        return out.stdout if out.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def capture_env_lock(python_exe: str | None = None) -> bytes:
    exe = python_exe or sys.executable
    ver = (_run([exe, "--version"]) or "python unknown").strip()
    header = f"# {ver}\n# platform: {platform.platform()}\n# exe: {exe}\n"
    freeze = _run([exe, "-m", "pip", "freeze", "--disable-pip-version-check"], timeout=60)
    if freeze is None:
        return (header + "# capture-failed: pip freeze unavailable\n").encode()
    return (header + freeze).encode()


def _total_ram_gb() -> float | None:
    """Physical RAM, by whatever the platform offers: /proc on Linux,
    sysctl on macOS. None when neither answers."""
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal"):
                    return round(int(line.split()[1]) / 1024 / 1024, 1)
    except OSError:
        pass
    if sys.platform == "darwin":
        out = _run(["sysctl", "-n", "hw.memsize"], timeout=5)
        if out and out.strip().isdigit():
            return round(int(out.strip()) / 1024**3, 1)
    return None


def capture_hardware(captured_by: str | None = None) -> Hardware:
    gpus = []
    smi = _run(
        ["nvidia-smi", "--query-gpu=name,memory.total,driver_version",
         "--format=csv,noheader,nounits"],
        timeout=10,
    )
    if smi:
        for line in smi.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 3:
                try:
                    vram = int(float(parts[1]))
                except ValueError:
                    vram = None
                gpus.append(GpuInfo(name=parts[0], vram_mb=vram, driver=parts[2]))
    ram_gb = _total_ram_gb()
    return Hardware(
        host=socket.gethostname(), platform=platform.platform(),
        cpu=platform.processor() or platform.machine(), ram_gb=ram_gb, gpus=gpus,
        captured_by=captured_by,
    )


def capture_compute() -> dict[str, str]:
    """Whatever the launcher declared about the job. Empty when it said
    nothing — an unset handshake means "this machine"."""
    return {field: value.strip() for field, var in COMPUTE_ENV.items()
            if (value := os.environ.get(var, "")).strip()}


def capture_project_git(source_root: Path | str) -> ProjectGitRef | None:
    if not shutil.which("git"):
        return None
    root = str(source_root)

    def git(*args: str) -> str | None:
        return _run(["git", "-C", root, *args], timeout=10)

    head = git("rev-parse", "HEAD")
    if head is None:
        return None
    status = git("status", "--porcelain")
    return ProjectGitRef(
        remote=(git("remote", "get-url", "origin") or "").strip() or None,
        head=head.strip(),
        branch=(git("branch", "--show-current") or "").strip() or None,
        dirty=bool(status.strip()) if status is not None else None,
    )


def capture_invocation(captured_by: str = "client") -> Invocation:
    return Invocation(
        argv=list(sys.argv),
        cwd=os.getcwd(),
        entrypoint=sys.argv[0] if sys.argv else None,
        env={k: v for k, v in os.environ.items() if k in ENV_ALLOWLIST},
        captured_by=captured_by,
    )
