import pytest
from pydantic import ValidationError

from mlparty.ids import new_id, params_hash, slugify
from mlparty.models import (
    Abstract,
    CustomNode,
    Edge,
    NoteNode,
    RunNode,
    dump_node,
    parse_node,
)


def test_edge_vocabulary():
    Edge(src="a", dst="b", type="derives-from")
    Edge(src="a", dst="b", type="x-my-custom")
    with pytest.raises(ValidationError):
        Edge(src="a", dst="b", type="my-custom")


def test_node_roundtrip():
    run = RunNode(
        id=new_id(), title="tube b2 full train", experiment_id="exp1",
        abstract=Abstract(purpose="p" * 30, hypothesis="h" * 30),
        parameters={"lr": 1e-3},
    )
    doc = dump_node(run)
    back = parse_node(doc)
    assert isinstance(back, RunNode)
    assert back == run

    note = NoteNode(id=new_id(), title="note", kind="feedback", body="b")
    assert parse_node(dump_node(note)) == note


def test_custom_node_fallback():
    doc = dump_node(CustomNode(id=new_id(), type="sweep", title="my sweep"))
    back = parse_node(doc)
    assert isinstance(back, CustomNode)
    assert back.type == "sweep"


def test_params_hash_order_independent():
    assert params_hash({"a": 1, "b": 2}) == params_hash({"b": 2, "a": 1})
    assert params_hash({"a": 1}) != params_hash({"a": 2})


def test_slugify():
    s = slugify("Tube B2 -- full TRAIN!", "01ABCDEFGHJKMNPQRSTVWXYZ99")
    assert s.startswith("tube-b2-full-train-")
    assert s.endswith("z99")
