"""Run-control plane: registered action templates, audited invocation.

ml-party never becomes a scheduler — orchestration stays in the user's
scripts/slurm/k8s. What this module adds is the uniform, *audited* interface
agents use to drive them: users register **action templates** (shell
commands with typed placeholders — the allowlist), agents invoke them with
validated parameters (never free-form strings; every value is shell-quoted),
and every invocation is recorded in the knowledge graph as an `action` node
edged to the run it controls (who, what, when, outcome).

Trust model (v1, local): templates execute as the process user on the host
where the invoking surface runs — registration is therefore a local-surface
operation (CLI, MCP over stdio); the HTTP server only lists and invokes
(write-gated). Remote runners are a later phase.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from .contract import ContractViolation
from .ids import new_id
from .models import CustomNode, Edge, utcnow

OUTPUT_TAIL_BYTES = 4096

_PLACEHOLDER = re.compile(r"\{(\w+)\}")
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")

PARAM_TYPES = ("str", "int", "float", "choice")


class ActionParam(BaseModel):
    type: Literal["str", "int", "float", "choice"] = "str"
    choices: list[str] | None = None
    default: str | int | float | None = None
    required: bool = True
    help: str | None = None


class ActionTemplate(BaseModel):
    name: str
    command: str
    description: str
    cwd: str | None = None
    env: dict[str, str] = Field(default_factory=dict)
    params: dict[str, ActionParam] = Field(default_factory=dict)
    experiment: str | None = None  # optional scope hint (title or id)
    created_by: str = "unknown"
    created_at: str = ""


def _violation(field: str, reason: str) -> ContractViolation:
    return ContractViolation(invalid=[{"field": field, "reason": reason}])


class ActionStore:
    """Templates in `<root>/actions.json` — small, text, diffable, backed up
    with the store (same pattern as auth/users.json)."""

    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.path = self.root / "actions.json"

    def _load(self) -> dict:
        if not self.path.exists():
            return {"actions": []}
        return json.loads(self.path.read_text())

    def _save(self, data: dict) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2) + "\n")
        tmp.rename(self.path)

    def register(self, template: dict, created_by: str = "unknown") -> ActionTemplate:
        try:
            tpl = ActionTemplate(**{**template, "created_by": created_by,
                                    "created_at": utcnow().isoformat()})
        except ValidationError as e:
            raise _violation("template", str(e)) from e
        if not _NAME_RE.match(tpl.name):
            raise _violation("name", "lowercase letters/digits/-/_ only")
        if len(tpl.description.strip()) < 10:
            raise _violation("description",
                            "describe what this action does (≥10 chars) — "
                            "agents pick actions by this text")
        self._check_placeholders(tpl)
        data = self._load()
        if any(a["name"] == tpl.name for a in data["actions"]):
            raise _violation("name", f"action {tpl.name!r} already exists "
                                     "(remove it first to replace)")
        data["actions"].append(tpl.model_dump())
        self._save(data)
        return tpl

    def _check_placeholders(self, tpl: ActionTemplate) -> None:
        declared = set(tpl.params) | {"store_root"}
        used: set[str] = set(_PLACEHOLDER.findall(tpl.command))
        for v in tpl.env.values():
            used |= set(_PLACEHOLDER.findall(v))
        if tpl.cwd:
            used |= set(_PLACEHOLDER.findall(tpl.cwd))
        unknown = used - declared
        if unknown:
            raise _violation("params", f"placeholders {sorted(unknown)} are not "
                                       "declared in params")
        for pname, p in tpl.params.items():
            if p.type == "choice" and not p.choices:
                raise _violation("params", f"{pname}: choice type needs choices")

    def remove(self, name: str) -> None:
        data = self._load()
        hit = next((a for a in data["actions"] if a["name"] == name), None)
        if hit is None:
            raise _violation("name", f"no action {name!r}")
        data["actions"].remove(hit)
        self._save(data)

    def list(self) -> list[ActionTemplate]:
        return [ActionTemplate(**a) for a in self._load()["actions"]]

    def get(self, name: str) -> ActionTemplate:
        hit = next((a for a in self.list() if a.name == name), None)
        if hit is None:
            raise _violation("name", f"no action {name!r} — see action_list")
        return hit

    # ------------------------------------------------------------- rendering

    def render(self, tpl: ActionTemplate,
               params: dict[str, Any]) -> tuple[str, dict[str, str], str | None]:
        """Validate typed params and substitute. Command values are
        shell-quoted (the allowlist guarantee); env/cwd values are raw."""
        values: dict[str, str] = {"store_root": str(self.root.resolve())}
        unknown = set(params) - set(tpl.params)
        if unknown:
            raise _violation("params", f"unknown parameter(s) {sorted(unknown)}; "
                                       f"this action takes {sorted(tpl.params)}")
        missing = []
        for pname, spec in tpl.params.items():
            raw = params.get(pname, spec.default)
            if raw is None:
                if spec.required:
                    missing.append(pname)
                continue
            values[pname] = self._coerce(pname, spec, raw)
        if missing:
            raise ContractViolation(missing=missing)

        def subst(text: str, quote: bool) -> str:
            def repl(m: re.Match) -> str:
                val = values[m.group(1)]
                return shlex.quote(val) if quote else val
            return _PLACEHOLDER.sub(repl, text)

        command = subst(tpl.command, quote=True)
        env = {k: subst(v, quote=False) for k, v in tpl.env.items()}
        cwd = subst(tpl.cwd, quote=False) if tpl.cwd else None
        return command, env, cwd

    @staticmethod
    def _coerce(pname: str, spec: ActionParam, raw: Any) -> str:
        try:
            if spec.type == "int":
                if isinstance(raw, float) and raw != int(raw):
                    raise ValueError("not an integer")
                return str(int(raw))
            if spec.type == "float":
                return repr(float(raw))
            if spec.type == "choice":
                if str(raw) not in (spec.choices or []):
                    raise ValueError(f"must be one of {spec.choices}")
                return str(raw)
            if not isinstance(raw, (str, int, float)):
                raise TypeError("must be a scalar")
            return str(raw)
        except (TypeError, ValueError) as e:
            raise _violation("params", f"{pname}: {e}") from None


def invoke(party, name: str, params: dict[str, Any] | None = None,
           created_by: str = "unknown") -> dict:
    """Execute a registered action, recording the invocation as an `action`
    node in the graph. If the params include `run`, it must reference an
    existing run and the node is edged `x-controls` to it (restart choreo:
    pre-register the new run with run_start, then pass its id here).
    Returns immediately; the node's status/exit_code update when the
    process exits (poll with node_get)."""
    actions = ActionStore(party.store.root)
    tpl = actions.get(name)
    params = dict(params or {})

    target = None
    if "run" in params:
        target = party._resolve(str(params["run"]), "run")
        params["run"] = target.id
    command, env, cwd = actions.render(tpl, params)

    node = CustomNode(
        id=new_id(), type="action", title=f"invoke {name}",
        created_by=created_by,
        action=name, command=command, params=params,
        status="running", exit_code=None, output_tail=None,
    )
    party.store.create_node(node)
    if target is not None:
        party.store.add_edge(Edge(src=node.id, dst=target.id, type="x-controls",
                                  note=f"action {name}", created_by=created_by))

    log_dir = party.store.root / "actions"
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / f"{node.id}.log"

    # The command runs under a detached runner PROCESS (not a thread of this
    # one): the outcome gets recorded even when the invoking surface is a
    # short-lived CLI or a server that restarts mid-action.
    subprocess.Popen(
        [sys.executable, "-m", "mlparty.action_runner",
         str(party.store.root), node.id, str(log_path), "--", command],
        cwd=cwd, env={**os.environ, **env},
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    # give quick commands a beat so callers see the outcome inline
    deadline = time.time() + 1.5
    fresh = node
    while time.time() < deadline:
        fresh = party.store.get_node(node.id)
        if getattr(fresh, "status", None) == "exited":
            break
        time.sleep(0.1)
    out = {"invocation_id": node.id, "action": name, "command": command,
           "status": getattr(fresh, "status", "running"),
           "exit_code": getattr(fresh, "exit_code", None),
           "log": str(log_path)}
    if target is not None:
        out["run"] = target.id
    return out
