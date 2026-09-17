"""The write contract (DESIGN.md §4).

Pre-registration at run.start: title/purpose/hypothesis/parameters — honest
before the run exists. Finalize adds method/result/reproduce. All checks are
deterministic (presence, minimum content, enums); semantic quality policing
belongs to the librarian, never the write path. Refusals are machine-readable
so an agent repairs in one round-trip.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from .models import Result, RunNode

MIN_TITLE = 3
MIN_INTENT = 15       # purpose / hypothesis: one honest sentence
MIN_TEXT = 20         # method / result.summary
MIN_REPRODUCE = 5
MIN_WHAT_FAILED = 10
EXPLORATORY_PREFIX = "exploratory:"

COMPUTE_FIELDS = ("system", "job_id", "url", "host", "note")
# A compute url is rendered as a link in the web UI and handed to humans, so
# the scheme is an allowlist: script-bearing schemes (javascript:, data:) never
# enter the store. Anything a person can actually follow is welcome.
COMPUTE_URL_SCHEMES = ("http", "https", "ssh", "sftp", "ftp", "ftps",
                       "s3", "gs", "abfss", "file")


class ContractViolation(Exception):
    def __init__(self, missing: list[str] | None = None,
                 invalid: list[dict[str, str]] | None = None):
        self.missing = missing or []
        self.invalid = invalid or []
        parts = []
        if self.missing:
            parts.append(f"missing: {', '.join(self.missing)}")
        if self.invalid:
            parts.append("invalid: " + "; ".join(f"{i['field']} ({i['reason']})"
                                                 for i in self.invalid))
        super().__init__("contract violation — " + " | ".join(parts))

    def to_dict(self) -> dict[str, Any]:
        return {"missing": self.missing, "invalid": self.invalid}


def _check_text(field: str, value: str | None, min_len: int,
                missing: list, invalid: list) -> None:
    if value is None or not str(value).strip():
        missing.append(field)
    elif len(str(value).strip()) < min_len:
        invalid.append({"field": field, "reason": f"needs at least {min_len} characters"})


def validate_start(title: str | None, purpose: str | None, hypothesis: str | None,
                   parameters: Any) -> None:
    missing: list[str] = []
    invalid: list[dict[str, str]] = []
    _check_text("title", title, MIN_TITLE, missing, invalid)
    _check_text("purpose", purpose, MIN_INTENT, missing, invalid)

    hyp = (hypothesis or "").strip()
    if not hyp:
        missing.append("hypothesis")
    elif hyp.lower().startswith(EXPLORATORY_PREFIX):
        if len(hyp) < len(EXPLORATORY_PREFIX) + 5:
            invalid.append({"field": "hypothesis",
                            "reason": "'exploratory:' needs the question being explored"})
    elif len(hyp) < MIN_INTENT:
        invalid.append({"field": "hypothesis",
                        "reason": f"needs at least {MIN_INTENT} characters, or "
                                  f"'exploratory: <question>' for exploratory runs"})

    if parameters is None:
        missing.append("parameters")
    elif not isinstance(parameters, dict):
        invalid.append({"field": "parameters", "reason": "must be a mapping (the full config)"})

    if missing or invalid:
        raise ContractViolation(missing, invalid)


def validate_finalize(run: RunNode, method: str | None, result: Result | None,
                      reproduce: str | None) -> None:
    missing: list[str] = []
    invalid: list[dict[str, str]] = []

    if run.status != "open":
        invalid.append({"field": "status",
                        "reason": f"run is '{run.status}' — only open runs can be finalized"})
    _check_text("method", method, MIN_TEXT, missing, invalid)
    _check_text("reproduce", reproduce, MIN_REPRODUCE, missing, invalid)

    if result is None:
        missing.append("result")
    else:
        _check_text("result.summary", result.summary, MIN_TEXT, missing, invalid)
        if not result.metrics and not (result.metrics_note or "").strip():
            invalid.append({"field": "result.metrics",
                            "reason": "empty metrics need result.metrics_note explaining why"})

    if run.provenance == "live" and run.code_ref is None:
        invalid.append({"field": "code_ref",
                        "reason": "live run has no code snapshot — repro tuple incomplete"})

    if missing or invalid:
        raise ContractViolation(missing, invalid)


def validate_compute(compute: Any) -> dict[str, str]:
    """A compute reference has to point somewhere: at least one of system /
    job_id / url, and a url a human can actually follow. Returns the cleaned
    mapping (blanks dropped, whitespace stripped)."""
    missing: list[str] = []
    invalid: list[dict[str, str]] = []

    if not isinstance(compute, dict):
        raise ContractViolation(invalid=[{
            "field": "compute",
            "reason": f"must be a mapping with keys {', '.join(COMPUTE_FIELDS)}"}])

    unknown = sorted(set(compute) - set(COMPUTE_FIELDS) - {"captured_by"})
    if unknown:
        invalid.append({"field": "compute",
                        "reason": f"unknown key(s) {', '.join(unknown)} — "
                                  f"keys are {', '.join(COMPUTE_FIELDS)}; put anything "
                                  "else in note"})

    clean = {k: str(v).strip() for k in COMPUTE_FIELDS
             if (v := compute.get(k)) is not None and str(v).strip()}

    if not any(clean.get(k) for k in ("system", "job_id", "url")):
        missing.append("compute.system / compute.job_id / compute.url "
                       "(at least one — a reference has to identify the job)")

    url = clean.get("url")
    if url:
        scheme = urlsplit(url).scheme.lower()
        if not scheme:
            invalid.append({"field": "compute.url",
                            "reason": "needs a scheme, e.g. https://…"})
        elif scheme not in COMPUTE_URL_SCHEMES:
            invalid.append({"field": "compute.url",
                            "reason": f"scheme {scheme!r} is not one a link can "
                                      f"safely carry — use one of "
                                      f"{', '.join(COMPUTE_URL_SCHEMES)}"})

    if missing or invalid:
        raise ContractViolation(missing, invalid)
    return clean


def validate_fail(run: RunNode, what_failed: str | None) -> None:
    missing: list[str] = []
    invalid: list[dict[str, str]] = []
    if run.status != "open":
        invalid.append({"field": "status",
                        "reason": f"run is '{run.status}' — only open runs can be failed"})
    _check_text("what_failed", what_failed, MIN_WHAT_FAILED, missing, invalid)
    if missing or invalid:
        raise ContractViolation(missing, invalid)
