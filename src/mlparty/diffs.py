"""run.diff: what actually changed between two runs — code (snapshot
commits), parameters, headline metrics, environment lock."""
from __future__ import annotations

import difflib
from typing import Any


def dict_delta(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    added = {k: b[k] for k in b.keys() - a.keys()}
    removed = {k: a[k] for k in a.keys() - b.keys()}
    changed = {k: {"a": a[k], "b": b[k]} for k in a.keys() & b.keys() if a[k] != b[k]}
    return {"added": added, "removed": removed, "changed": changed,
            "identical": not (added or removed or changed)}


def run_diff(party, ref_a: str, ref_b: str) -> dict[str, Any]:
    a = party._resolve(ref_a, "run")
    b = party._resolve(ref_b, "run")
    out: dict[str, Any] = {
        "run_a": {"id": a.id, "title": a.title, "status": a.status},
        "run_b": {"id": b.id, "title": b.title, "status": b.status},
        "params": dict_delta(a.parameters, b.parameters),
        "metrics": dict_delta(a.metrics_summary, b.metrics_summary),
    }

    if a.code_ref is None or b.code_ref is None:
        out["code"] = {"note": "missing code snapshot on at least one run (retro?)"}
    elif a.experiment_id != b.experiment_id:
        out["code"] = {"note": "runs belong to different experiments (separate repos); "
                               "cross-repo code diff not supported yet"}
    elif a.code_ref.commit_sha == b.code_ref.commit_sha:
        out["code"] = {"identical": True, "commit": a.code_ref.commit_sha,
                       "note": "same snapshot commit — params-only difference"}
    else:
        out["code"] = {"identical": False} | party.git.diff(
            a.experiment_id, a.code_ref.commit_sha, b.code_ref.commit_sha)

    env_a = env_b = None
    if a.code_ref and a.env_lock_ref:
        env_a = party.git.read_file(a.experiment_id, a.code_ref.commit_sha, a.env_lock_ref)
    if b.code_ref and b.env_lock_ref:
        env_b = party.git.read_file(b.experiment_id, b.code_ref.commit_sha, b.env_lock_ref)
    if env_a is not None and env_b is not None:
        if env_a == env_b:
            out["env"] = {"identical": True}
        else:
            lines = list(difflib.unified_diff(
                env_a.decode("utf-8", "replace").splitlines(),
                env_b.decode("utf-8", "replace").splitlines(),
                fromfile=f"env.lock@{a.id}", tofile=f"env.lock@{b.id}", lineterm=""))
            out["env"] = {"identical": False, "diff": "\n".join(lines[:400])}
    else:
        out["env"] = {"note": "env lock unavailable on at least one run"}
    return out
