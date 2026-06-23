"""Offline eval harness for the crowd gate.

Runs with no API key and no network: the LLM judge and embeddings are replaced by
the deterministic `HeuristicSoundnessJudge` and `HashingEmbedder`. Verifies both
the pure scoring math and the end-to-end gating behaviour against fixtures.

Run:  python tests/test_crowd.py     (or: python -m pytest tests/test_crowd.py)
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from crowd import (  # noqa: E402
    Contribution, CrowdGate, GateConfig, HashingEmbedder, HeuristicSoundnessJudge,
    ContributionStore, js_divergence, aggregate, novelty, cosine,
)

# --- fixtures --------------------------------------------------------------- #
TARGET = "US data-center AI capex exceeds $400B in 2026"
PRIOR_P = 0.7
PRIOR_RATIONALE = ("Hyperscaler capital expenditure keeps rising because compute "
                   "demand from large models compounds; therefore capex should exceed "
                   "the threshold as buildout continues across cloud providers.")

ECHO = Contribution(
    id="c_echo", target_id="t1", contributor_id="u_echo", probability=0.7,
    # a restatement of the consensus thesis (same viewpoint). The offline test
    # embedder is lexical, so this is worded close to PRIOR_RATIONALE; a real
    # embeddings backend flags paraphrase too, not just shared vocabulary.
    argument=("Hyperscaler capital expenditure keeps rising because compute demand "
              "from large models compounds; therefore capex will exceed the threshold "
              "as buildout continues across cloud providers, since order books remain "
              "full and given announced budgets the rising trend should clearly hold."),
    evidence_urls=["http://example.com/earnings"])

DISSENT_A = Contribution(
    id="c_dissentA", target_id="t1", contributor_id="u_grid", probability=0.35,
    argument=("However, an energy and power-grid bottleneck will cap deployments, "
              "because interconnection queues and transformer shortages mean physical "
              "buildout lags announced budgets, so realized spending falls short."),
    evidence_urls=["http://example.com/grid-report"])

DISSENT_B = Contribution(  # near-duplicate of A -> should collapse
    id="c_dissentB", target_id="t1", contributor_id="u_grid2", probability=0.33,
    argument=("However, power-grid and energy bottlenecks will cap deployments, "
              "because interconnection queues and transformer shortages mean buildout "
              "lags budgets, so realized spending falls short of plans."),
    evidence_urls=["http://example.com/grid2"])

NOISE = Contribution(
    id="c_noise", target_id="t1", contributor_id="u_troll", probability=0.1,
    argument="No. Wrong. Bubble.", evidence_urls=["http://example.com/x"])

NO_EVIDENCE = Contribution(
    id="c_noev", target_id="t1", contributor_id="u_eloquent", probability=0.4,
    argument=("The market will correct because valuations are stretched, however "
              "depreciation schedules imply writedowns, therefore reported capex "
              "may be revised downward as utilization disappoints over the year."),
    evidence_urls=[])


def _gate(k=5):
    return CrowdGate(HashingEmbedder(), HeuristicSoundnessJudge(),
                     cfg=GateConfig(k=k))


def _run(contribs, k=5):
    return _gate(k).process(TARGET, "t1", PRIOR_P, PRIOR_RATIONALE, contribs)


# --- pure math tests -------------------------------------------------------- #
def test_js_divergence_properties():
    assert abs(js_divergence(0.5, 0.5)) < 1e-9            # identical -> 0
    assert js_divergence(0.99, 0.01) > 0.9                # opposite -> ~1
    assert abs(js_divergence(0.2, 0.8) - js_divergence(0.8, 0.2)) < 1e-9  # symmetric
    print("ok  js_divergence properties")


def test_aggregate_bounds_and_direction():
    # one strong dissent at 0.3 should pull a 0.7 prior downward
    out = aggregate(0.7, [(0.3, 1.0)], prior_weight=1.0)
    assert 0.3 < out < 0.7
    # no contributions -> unchanged
    assert abs(aggregate(0.7, []) - 0.7) < 1e-9
    # always in [0,1]
    assert 0.0 <= aggregate(0.9, [(0.95, 5.0)], extremize=2.0) <= 1.0
    print("ok  aggregate bounds + direction")


def test_cosine_self_is_one():
    v = HashingEmbedder().embed(["energy grid transformer shortage"])[0]
    assert abs(cosine(v, v) - 1.0) < 1e-6
    print("ok  cosine self-similarity")


# --- behavioural gate tests ------------------------------------------------- #
def test_no_evidence_rejected():
    res = _run([NO_EVIDENCE])
    d = {x.contribution_id: x for x in res.decisions}["c_noev"]
    assert not d.admitted and d.reason == "no_evidence"
    print("ok  eloquent-but-unsourced rejected at evidence gate")


def test_noise_rejected():
    res = _run([NOISE])
    d = {x.contribution_id: x for x in res.decisions}["c_noise"]
    assert not d.admitted and d.reason == "weak_argument"
    print("ok  short contrarian noise rejected at soundness gate")


def test_echo_rejected_as_redundant():
    res = _run([ECHO])
    d = {x.contribution_id: x for x in res.decisions}["c_echo"]
    assert not d.admitted and d.reason == "redundant"
    print("ok  consensus echo rejected as redundant (low entropy)")


def test_well_argued_dissent_admitted_and_moves_forecast():
    res = _run([DISSENT_A])
    d = {x.contribution_id: x for x in res.decisions}["c_dissentA"]
    assert d.admitted and d.weight > 0
    assert res.aggregate_probability < PRIOR_P  # dissent pulled it down
    print(f"ok  well-argued dissent admitted, forecast {PRIOR_P} -> "
          f"{res.aggregate_probability}")


def test_near_duplicate_dissent_collapses():
    res = _run([DISSENT_A, DISSENT_B])
    dd = {x.contribution_id: x for x in res.decisions}
    assert dd["c_dissentA"].admitted
    assert not dd["c_dissentB"].admitted and dd["c_dissentB"].reason == "redundant"
    print("ok  near-duplicate dissent collapsed to one representative (sparsity)")


def test_full_mix_selects_only_informative():
    res = _run([ECHO, DISSENT_A, DISSENT_B, NOISE, NO_EVIDENCE])
    assert res.selected == ["c_dissentA"]
    reasons = {x.contribution_id: x.reason for x in res.decisions}
    assert reasons["c_echo"] == "redundant"
    assert reasons["c_noise"] == "weak_argument"
    assert reasons["c_noev"] == "no_evidence"
    assert reasons["c_dissentB"] == "redundant"
    print("ok  full mix -> 1 of 5 admitted; the rest correctly rejected")


def test_sparsity_cap():
    # three genuinely distinct, well-argued views; k=2 keeps only two
    extra = Contribution(
        id="c_demand", target_id="t1", contributor_id="u_demand", probability=0.9,
        argument=("Moreover, enterprise adoption accelerates because inference demand "
                  "compounds, therefore providers over-provision capacity, thus pushing "
                  "spend above the threshold even if some projects slip."),
        evidence_urls=["http://example.com/adoption"])
    res = _run([DISSENT_A, extra, NO_EVIDENCE, NOISE], k=1)
    assert len(res.selected) == 1
    print("ok  sparsity cap k enforced (only k non-zero parameters)")


def test_determinism():
    a = _run([ECHO, DISSENT_A, DISSENT_B, NOISE])
    b = _run([ECHO, DISSENT_A, DISSENT_B, NOISE])
    assert a.aggregate_probability == b.aggregate_probability
    assert a.selected == b.selected
    print("ok  deterministic across runs")


def test_track_record_skill():
    with tempfile.TemporaryDirectory() as tmp:
        store = ContributionStore(Path(tmp) / "c.jsonl")
        # cold start -> neutral
        assert store.contributor_skill("u_new") == 0.5
        # a sharp contributor: confident-and-right across 3 targets
        for i in range(3):
            store.add(Contribution(id=f"s{i}", target_id=f"t{i}",
                                   contributor_id="u_sharp", probability=0.9,
                                   argument="x", evidence_urls=["u"]))
            store.resolve_target(f"t{i}", True)
        assert store.contributor_skill("u_sharp") > 0.9
        # a poorly calibrated one
        for i in range(3):
            store.add(Contribution(id=f"b{i}", target_id=f"q{i}",
                                   contributor_id="u_bad", probability=0.1,
                                   argument="x", evidence_urls=["u"]))
            store.resolve_target(f"q{i}", True)
        assert store.contributor_skill("u_bad") < 0.2
    print("ok  contributor skill earned from realised Brier (cold-start neutral)")


def main():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
    print(f"\nALL {len(fns)} CROWD-GATE TESTS PASSED")


if __name__ == "__main__":
    main()
