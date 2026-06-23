"""Offline eval harness for the job evolution agent.

No API key, no network.  Verifies:
  - Case library integrity (sources, variable bounds, outcome coverage)
  - Factor analysis: explained variance, loading signs, determinism
  - Cluster stability: bootstrap ARI above floor
  - OOD detector: calibration, known-inside vs known-outside discrimination
  - Conditional rules: direction correctness vs economic theory priors
  - EvolutionPrior: serialises cleanly, prompt context contains OOD warning

Run:  python tests/test_evolution.py
"""
import sys
from pathlib import Path

_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import numpy as np

from evolution import (
    CASE_LIBRARY, CURRENT_AI_SCENARIO, VARIABLE_NAMES,
    PCAReducer, BayesianGMMClusterer, OODDetector,
    build_prior, extract_conditional_rules, _normalise_diffusion,
    TransitionCase,
)


# ── helpers ─────────────────────────────────────────────────────────────────

def _build(n_boot=10):
    """Fast prior build for tests (fewer bootstrap iterations)."""
    return build_prior(n_bootstrap=n_boot)


# ── case library ────────────────────────────────────────────────────────────

def test_case_library_integrity():
    assert len(CASE_LIBRARY) >= 10, "need at least 10 cases"
    for c in CASE_LIBRARY:
        for vname in VARIABLE_NAMES:
            v = getattr(c, vname)
            if vname == "diffusion_years":
                assert v > 0, f"{c.id}: diffusion_years must be positive"
            else:
                assert 0.0 <= v <= 1.0, f"{c.id}.{vname}={v} outside [0,1]"
        assert len(c.sources) >= 1, f"{c.id}: must have ≥1 source"
        assert c.net_job_multiplier > 0, f"{c.id}: multiplier must be positive"
        assert c.lag_years >= 0, f"{c.id}: lag_years must be non-negative"
    net_gain = sum(1 for c in CASE_LIBRARY if c.net_job_multiplier > 1.0)
    net_loss  = len(CASE_LIBRARY) - net_gain
    assert net_gain >= 2 and net_loss >= 2, "library needs both net-gain and net-loss cases"
    print(f"ok  case library integrity ({len(CASE_LIBRARY)} cases, "
          f"{net_gain} net-gain, {net_loss} net-loss)")


# ── factor analysis ──────────────────────────────────────────────────────────

def test_factor_explained_variance():
    X = _normalise_diffusion(CASE_LIBRARY)
    r = PCAReducer(n_components=3).fit(X)
    evr = r.explained_variance_ratio()
    assert sum(evr) >= 0.55, f"3 factors should explain ≥55% variance, got {sum(evr):.2%}"
    print(f"ok  PCA explained variance: {[f'{v:.2%}' for v in evr]} "
          f"(total {sum(evr):.2%})")


def test_factor_loading_signs():
    """Augmentation_ratio and task_frontier_open should load together on
    the dominant 'complementarity' factor (same sign, high magnitude)."""
    X = _normalise_diffusion(CASE_LIBRARY)
    r = PCAReducer(n_components=3).fit(X)
    comps = r.components()  # (3, 8)
    aug_idx = VARIABLE_NAMES.index("augmentation_ratio")
    frontier_idx = VARIABLE_NAMES.index("task_frontier_open")
    # dominant factor
    f0 = comps[0]
    aug_load, frontier_load = f0[aug_idx], f0[frontier_idx]
    assert aug_load * frontier_load > 0, (
        "augmentation_ratio and task_frontier_open should load with same sign "
        f"on PC1 (got {aug_load:.3f}, {frontier_load:.3f})")
    print(f"ok  factor loading signs: augmentation_ratio={aug_load:.3f}, "
          f"task_frontier_open={frontier_load:.3f} (same sign on PC1)")


def test_pca_determinism():
    X = _normalise_diffusion(CASE_LIBRARY)
    a = PCAReducer(n_components=3).fit(X).transform(X)
    b = PCAReducer(n_components=3).fit(X).transform(X)
    assert np.allclose(np.abs(a), np.abs(b), atol=1e-8), \
        "PCA must be deterministic (sign flips OK, magnitudes must match)"
    print("ok  PCA determinism (sign-invariant)")


# ── clustering ───────────────────────────────────────────────────────────────

def test_cluster_count_reasonable():
    X = _normalise_diffusion(CASE_LIBRARY)
    r = PCAReducer(n_components=3).fit(X)
    Z = r.transform(X)
    cl = BayesianGMMClusterer(max_components=5).fit(Z)
    labels = cl.predict(Z)
    n_clusters = len(set(labels))
    assert 2 <= n_clusters <= 5, f"expected 2-5 clusters, got {n_clusters}"
    print(f"ok  Bayesian GMM found {n_clusters} clusters (DP prior working)")


def test_net_gain_loss_separation():
    """Clusters should not be random w.r.t. outcome: the mean net_job_multiplier
    should differ meaningfully across clusters."""
    X = _normalise_diffusion(CASE_LIBRARY)
    r = PCAReducer(n_components=3).fit(X)
    Z = r.transform(X)
    cl = BayesianGMMClusterer(max_components=5).fit(Z)
    labels = cl.predict(Z)
    per_cluster = {}
    for c, lbl in zip(CASE_LIBRARY, labels):
        per_cluster.setdefault(lbl, []).append(c.net_job_multiplier)
    means = [sum(v) / len(v) for v in per_cluster.values()]
    spread = max(means) - min(means)
    assert spread >= 0.3, (
        f"clusters should differ in mean net_job_multiplier by ≥0.3, got {spread:.3f}")
    print(f"ok  cluster outcome spread: max-min multiplier = {spread:.3f}")


def test_bootstrap_stability_above_floor():
    prior = _build(n_boot=20)
    assert prior.bootstrap_stability >= 0.2, (
        f"bootstrap ARI {prior.bootstrap_stability:.3f} below floor 0.2 — "
        "clusters are too unstable to trust")
    print(f"ok  bootstrap stability ARI = {prior.bootstrap_stability:.3f}")


# ── OOD detector ────────────────────────────────────────────────────────────

def test_ood_training_points_inside():
    """All training cases should be inside the historical envelope."""
    X = _normalise_diffusion(CASE_LIBRARY)
    r = PCAReducer(n_components=3).fit(X)
    Z = r.transform(X)
    cl = BayesianGMMClusterer(max_components=5).fit(Z)
    labels = cl.predict(Z)
    det = OODDetector(threshold_percentile=90).fit(Z, labels)
    # At 90th pct threshold, at most 10% of training points should fire OOD
    ood_flags = [det.score(Z[i])["is_ood"] for i in range(len(Z))]
    ood_rate = sum(ood_flags) / len(ood_flags)
    assert ood_rate <= 0.15, f"OOD rate on training data = {ood_rate:.0%} (expect ≤15%)"
    print(f"ok  OOD training-set rate = {ood_rate:.0%} (≤15% threshold)")


def test_ood_extreme_scenario_fires():
    """A scenario far outside all historical cases should fire the OOD flag."""
    extreme = {v: 0.99 for v in VARIABLE_NAMES}   # all maxed out — unprecedented
    import math
    X = _normalise_diffusion(CASE_LIBRARY)
    r = PCAReducer(n_components=3).fit(X)
    Z = r.transform(X)
    cl = BayesianGMMClusterer(max_components=5).fit(Z)
    labels = cl.predict(Z)
    det = OODDetector(threshold_percentile=90).fit(Z, labels)
    extreme_vec = np.array([
        extreme[v] if v != "diffusion_years"
        else math.log1p(extreme[v]) / math.log1p(50)
        for v in VARIABLE_NAMES
    ]).reshape(1, -1)
    z_ext = r.transform(extreme_vec)[0]
    score = det.score(z_ext)
    assert score["is_ood"], f"extreme scenario should fire OOD: {score}"
    print(f"ok  extreme scenario fires OOD (ratio={score['ood_ratio']:.2f})")


# ── conditional rules ────────────────────────────────────────────────────────

def test_conditional_rules_directions():
    import re as _re
    rules = extract_conditional_rules(CASE_LIBRARY)

    # augmentation_ratio multiplier rule
    aug_rule = next((r for r in rules if "augmentation_ratio" in r and "multiplier" in r), None)
    assert aug_rule is not None, "augmentation_ratio multiplier rule missing"
    m = _re.search(r"multiplier\s+([\d.]+)\s+vs\s+([\d.]+)", aug_rule)
    assert m, f"could not parse multiplier values from: {aug_rule}"
    high_m, low_m = float(m.group(1)), float(m.group(2))
    assert high_m > low_m, (
        f"high augmentation should -> higher multiplier: {high_m:.2f} vs {low_m:.2f}")

    # net-gain discriminator rule: net-gain cases should have higher aug ratio
    disc_rule = next((r for r in rules if "strongest discriminator" in r), None)
    assert disc_rule is not None, "discriminator rule missing"
    dm = _re.search(r"augmentation_ratio=([\d.]+).*?mean=([\d.]+)", disc_rule)
    assert dm, f"could not parse discriminator rule: {disc_rule}"
    gain_aug, loss_aug = float(dm.group(1)), float(dm.group(2))
    assert gain_aug > loss_aug, (
        f"net-gain should have higher aug_ratio: {gain_aug:.2f} vs {loss_aug:.2f}")

    assert any("CAUTION" in r for r in rules)
    print(f"ok  conditional rules: high_aug multiplier {high_m:.2f} > low {low_m:.2f}; "
          f"net-gain aug_ratio {gain_aug:.2f} > net-loss {loss_aug:.2f}")


# ── end-to-end prior + prompt ─────────────────────────────────────────────────

def test_prior_builds_and_serialises():
    prior = _build(n_boot=10)
    assert prior.clusters, "should have at least one cluster"
    assert prior.nearest_cluster is not None
    assert 0.0 <= prior.bootstrap_stability <= 1.0
    assert len(prior.factor_loadings) == prior.n_factors * len(VARIABLE_NAMES)
    prompt = prior.to_prompt_context()
    assert "OOD signal" in prompt
    assert "Nearest historical regime" in prompt
    assert "CAUTION" in prompt
    print(f"ok  prior builds and serialises: {len(prior.clusters)} clusters, "
          f"prompt={len(prompt)} chars")


def test_cluster_names_are_distinct_and_english():
    prior = _build(n_boot=10)
    names = [c.name for c in prior.clusters]
    assert len(names) == len(set(names)), f"duplicate cluster names: {names}"
    for name in names:
        assert "·" in name, f"expected structured label, got {name!r}"
        assert not any("\u4e00" <= ch <= "\u9fff" for ch in name), name
    print(f"ok  cluster names distinct: {names}")


def test_ood_warning_in_prompt_when_ood():
    """If the current scenario is OOD, the prompt context must say so explicitly."""
    prior = _build(n_boot=10)
    prompt = prior.to_prompt_context()
    if prior.current_scenario_ood["is_ood"]:
        assert "widen confidence intervals" in prompt
        print("ok  OOD warning appears in prompt (scenario is OOD)")
    else:
        assert "within historical envelope" in prompt
        print("ok  OOD not fired for current scenario (within envelope)")


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
    print(f"\nALL {len(fns)} EVOLUTION AGENT TESTS PASSED")


if __name__ == "__main__":
    main()
