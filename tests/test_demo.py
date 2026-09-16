"""The packaged demo is the first thing a fresh install runs — it must
complete the contract, not just emit metrics."""
from mlparty.core import MlParty
from mlparty.demo import run_demo


def test_demo_completes_the_contract(tmp_path):
    root = tmp_path / ".mlparty"
    MlParty.init(root)

    run_id = run_demo(str(root), steps=3, sleep=0.0)

    party = MlParty.open(root)
    run = party.store.get_node(run_id)
    assert run.status == "finalized"
    assert run.result.verdict == "confirmed"
    records, _ = party.store.read_metrics(run_id)
    assert [r["name"] for r in records].count("loss") == 3
