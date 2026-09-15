import pytest

from mlparty.contract import ContractViolation, validate_finalize, validate_start
from mlparty.ids import new_id
from mlparty.models import Abstract, CommitRef, Result, RunNode

GOOD_START = {
    "title": "tube b2",
    "purpose": "test whether band anchors improve TDS transfer",
    "hypothesis": "band-anchor weighting will reduce WER on TDS synthesis",
    "parameters": {"lr": 1e-3},
}


def _run(status="open", provenance="live", with_code=True):
    return RunNode(
        id=new_id(), title="r", experiment_id="e", status=status, provenance=provenance,
        abstract=Abstract(purpose="p" * 20, hypothesis="h" * 20),
        parameters={},
        code_ref=CommitRef(repo="r", commit_sha="c", tree_sha="t") if with_code else None,
    )


@pytest.mark.parametrize("field,value,expect_missing,expect_invalid", [
    ("title", None, ["title"], []),
    ("title", "ab", [], ["title"]),
    ("purpose", "", ["purpose"], []),
    ("purpose", "too short", [], ["purpose"]),
    ("hypothesis", None, ["hypothesis"], []),
    ("hypothesis", "short", [], ["hypothesis"]),
    ("hypothesis", "exploratory:", [], ["hypothesis"]),
    ("parameters", None, ["parameters"], []),
    ("parameters", "not-a-dict", [], ["parameters"]),
])
def test_start_refusals(field, value, expect_missing, expect_invalid):
    payload = {**GOOD_START, field: value}
    with pytest.raises(ContractViolation) as ei:
        validate_start(**payload)
    assert ei.value.missing == expect_missing
    assert [i["field"] for i in ei.value.invalid] == expect_invalid


def test_start_accepts_good_and_exploratory():
    validate_start(**GOOD_START)
    validate_start(**{**GOOD_START, "hypothesis": "exploratory: what does the loss do?"})


def _good_result(**over):
    return Result(**({"summary": "worked well, WER dropped by half on the eval set",
                      "verdict": "confirmed", "metrics": {"wer": 0.048}} | over))


def test_finalize_good():
    validate_finalize(_run(), "trained the CNN on kiel data for 200 epochs",
                      _good_result(), "python train.py --lr 1e-3")


@pytest.mark.parametrize("kwargs,bad_field", [
    ({"method": "short"}, "method"),
    ({"reproduce": ""}, "reproduce"),
    ({"result": None}, "result"),
])
def test_finalize_refusals(kwargs, bad_field):
    args = {"method": "trained the CNN on kiel data for 200 epochs",
            "result": _good_result(), "reproduce": "python train.py"}
    args.update(kwargs)
    with pytest.raises(ContractViolation) as ei:
        validate_finalize(_run(), **args)
    assert bad_field in ei.value.missing or bad_field in [i["field"] for i in ei.value.invalid]


def test_finalize_empty_metrics_needs_note():
    with pytest.raises(ContractViolation) as ei:
        validate_finalize(_run(), "m" * 30, _good_result(metrics={}), "python x.py")
    assert any(i["field"] == "result.metrics" for i in ei.value.invalid)
    # with a note it passes
    validate_finalize(_run(), "m" * 30,
                      _good_result(metrics={}, metrics_note="qualitative listening test only"),
                      "python x.py")


def test_finalize_terminal_states_refused():
    for status in ("finalized", "failed", "abandoned"):
        with pytest.raises(ContractViolation) as ei:
            validate_finalize(_run(status=status), "m" * 30, _good_result(), "python x.py")
        assert any(i["field"] == "status" for i in ei.value.invalid)


def test_finalize_live_run_needs_code_ref_but_retro_does_not():
    with pytest.raises(ContractViolation):
        validate_finalize(_run(with_code=False), "m" * 30, _good_result(), "python x.py")
    validate_finalize(_run(provenance="retro", with_code=False), "m" * 30,
                      _good_result(), "python x.py")


def test_violation_is_machine_readable():
    try:
        validate_start(None, "short", None, None)
    except ContractViolation as e:
        d = e.to_dict()
        assert set(d) == {"missing", "invalid"}
        assert "title" in d["missing"] and "hypothesis" in d["missing"]
        assert d["invalid"][0]["field"] == "purpose"
