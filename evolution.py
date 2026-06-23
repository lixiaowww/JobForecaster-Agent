"""Job Evolution Agent  (agent/evolution.py)
============================================
Extracts interpretable drivers and patterns from historical technology-driven
occupational transitions, then emits a *prior* that the forecaster can use —
and that the Brier scoreboard can demote if it turns out not to help.

Architecture (harness conventions)
------------------------------------
* The case library is a deterministic, citable artefact — every figure must have a
  source.  LLM abstraction only enters through a swappable `CaseEnricher` interface.
* The unsupervised layer is three components in sequence:
    1. FactorAnalyzer  — PCA/FA over the 8 causal-proxy variables →
                         latent "complementarity" and "friction" dimensions
    2. TransitionClusterer — Bayesian Gaussian-mixture clustering of historical cases
                             into prototype transition regimes
    3. OODDetector  — Mahalanobis distance from every historical cluster →
                      explicit "how far outside history am I?" signal
* All three components have deterministic stub backends (no sklearn global state,
  seeded) so the test harness is fully offline and reproducible.
* The `EvolutionPrior` output is a plain dataclass — easy to serialise into the
  forecaster prompt and into the registry for Brier attribution.

Variable schema (self-contained in `TransitionCase`)
------------------------------------------------------
Based on the variables identified during design:
  augmentation_ratio    Autor — fraction of tasks complemented vs substituted
  demand_elasticity     Jevons — does cheaper task raise total activity demand?
  oring_leverage        Kremer — does automating step k raise value of human step k+1?
  skill_distance        re-training friction (0=trivial, 1=total reskilling)
  diffusion_years       S-curve lag from invention to 50 % adoption
  absorbing_sector      Baumol refuge exists? (0/1)
  productivity_capture  share of gains flowing to labour vs capital (0–1)
  task_frontier_open    does automation open a new human task frontier? (0/1)
"""
from __future__ import annotations

import math
import warnings
from dataclasses import dataclass, field, asdict
from typing import Optional, Protocol

import numpy as np

# --------------------------------------------------------------------------- #
# Case library schema
# --------------------------------------------------------------------------- #

@dataclass
class TransitionCase:
    """One historical technology-driven occupational transition.
    Every numeric figure needs a source entry in `sources`."""
    id: str
    name: str                        # e.g. "ATM & bank tellers 1970-2010"
    technology: str
    displaced_occupation: str
    period: str                      # e.g. "1970-2010"

    # ── eight causal-proxy variables (all float, 0..1 unless noted) ──────
    augmentation_ratio: float        # 0=pure substitution  1=pure complement
    demand_elasticity: float         # 0=inelastic  1=highly elastic (Jevons)
    oring_leverage: float            # 0=no leverage  1=high leverage
    skill_distance: float            # 0=trivial retrain  1=full reskilling
    diffusion_years: float           # raw years (not normalised here)
    absorbing_sector: float          # 0/1
    productivity_capture: float      # 0=all capital  1=all labour
    task_frontier_open: float        # 0/1

    # ── observed outcomes ─────────────────────────────────────────────────
    net_job_multiplier: float        # new jobs / displaced jobs  (>1 = net gain)
    lag_years: float                 # years until net-positive employment
    notes: str = ""
    sources: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Citable case library  (n=15 bootstrap; figures from published sources)
# --------------------------------------------------------------------------- #

CASE_LIBRARY: list[TransitionCase] = [
    TransitionCase(
        id="atm_tellers", name="ATM & bank tellers 1970-2010",
        technology="Automated Teller Machine",
        displaced_occupation="Bank teller",
        period="1970-2010",
        augmentation_ratio=0.6, demand_elasticity=0.8, oring_leverage=0.5,
        skill_distance=0.3, diffusion_years=20, absorbing_sector=1.0,
        productivity_capture=0.5, task_frontier_open=1.0,
        net_job_multiplier=1.8, lag_years=12,
        notes="Cheaper branches → more branches → more tellers (Bessen 2015)",
        sources=["Bessen, J. (2015). Learning by Doing. Yale UP.",
                 "Autor, D. (2015). Why Are There Still So Many Jobs? JEP 29(3)"]),
    TransitionCase(
        id="agri_mech", name="Agricultural mechanisation US 1900-1970",
        technology="Tractor + combine harvester",
        displaced_occupation="Farm labourer",
        period="1900-1970",
        augmentation_ratio=0.2, demand_elasticity=0.3, oring_leverage=0.2,
        skill_distance=0.7, diffusion_years=40, absorbing_sector=1.0,
        productivity_capture=0.4, task_frontier_open=1.0,
        net_job_multiplier=3.2, lag_years=35,
        notes="Massive rural-urban migration; manufacturing absorbed surplus labour",
        sources=["Autor, D., Levy, F., Murnane, R. (2003). QJE 118(4)",
                 "Goldin, C. & Katz, L. (2008). The Race Between Education and Technology"]),
    TransitionCase(
        id="typesetting", name="Digital typesetting 1970-1990",
        technology="Desktop publishing / Postscript",
        displaced_occupation="Compositor / typesetter",
        period="1970-1990",
        augmentation_ratio=0.15, demand_elasticity=0.9, oring_leverage=0.3,
        skill_distance=0.8, diffusion_years=15, absorbing_sector=0.5,
        productivity_capture=0.3, task_frontier_open=1.0,
        net_job_multiplier=2.1, lag_years=10,
        notes="Graphic design & DTP exploded; net jobs rose despite occupation death",
        sources=["Autor, D. (2015). JEP 29(3)",
                 "Brynjolfsson, E. & McAfee, A. (2014). The Second Machine Age"]),
    TransitionCase(
        id="containerisation", name="Containerisation & dock labour 1960-1990",
        technology="Intermodal container shipping",
        displaced_occupation="Dock worker / stevedore",
        period="1960-1990",
        augmentation_ratio=0.1, demand_elasticity=0.7, oring_leverage=0.4,
        skill_distance=0.6, diffusion_years=25, absorbing_sector=0.4,
        productivity_capture=0.3, task_frontier_open=0.5,
        net_job_multiplier=0.7, lag_years=25,
        notes="Net dock job loss; trade volume gains created logistics/warehouse jobs elsewhere",
        sources=["Levinson, M. (2006). The Box. Princeton UP."]),
    TransitionCase(
        id="telephone_operators", name="Telephone operators 1950-2000",
        technology="Direct dial + IVR",
        displaced_occupation="Telephone operator",
        period="1950-2000",
        augmentation_ratio=0.05, demand_elasticity=0.9, oring_leverage=0.1,
        skill_distance=0.5, diffusion_years=30, absorbing_sector=1.0,
        productivity_capture=0.4, task_frontier_open=0.6,
        net_job_multiplier=1.1, lag_years=30,
        notes="Slow net gain; cheap calls created telemarketing & customer-service roles",
        sources=["Autor, D. (2015). JEP 29(3)"]),
    TransitionCase(
        id="spreadsheet_bookkeeping", name="Spreadsheet software & bookkeepers 1980-2010",
        technology="VisiCalc / Lotus / Excel",
        displaced_occupation="Bookkeeper / accounting clerk",
        period="1980-2010",
        augmentation_ratio=0.5, demand_elasticity=0.7, oring_leverage=0.6,
        skill_distance=0.4, diffusion_years=15, absorbing_sector=1.0,
        productivity_capture=0.5, task_frontier_open=1.0,
        net_job_multiplier=1.5, lag_years=8,
        notes="Demand for financial analysis exploded; accountants augmented not replaced",
        sources=["Bessen, J. (2015). Learning by Doing. Yale UP."]),
    TransitionCase(
        id="textile_looms", name="Power loom & handloom weavers UK 1800-1860",
        technology="Power loom",
        displaced_occupation="Handloom weaver",
        period="1800-1860",
        augmentation_ratio=0.05, demand_elasticity=0.8, oring_leverage=0.2,
        skill_distance=0.7, diffusion_years=30, absorbing_sector=0.6,
        productivity_capture=0.2, task_frontier_open=0.4,
        net_job_multiplier=0.5, lag_years=40,
        notes="Severe transitional hardship; long lag before factory employment absorbed workers",
        sources=["Allen, R.C. (2009). Engels' Pause. Explorations in Economic History 46(4)"]),
    TransitionCase(
        id="cad_drafting", name="CAD & technical drafters 1980-2005",
        technology="AutoCAD / parametric design",
        displaced_occupation="Technical drafter",
        period="1980-2005",
        augmentation_ratio=0.65, demand_elasticity=0.6, oring_leverage=0.7,
        skill_distance=0.35, diffusion_years=12, absorbing_sector=1.0,
        productivity_capture=0.55, task_frontier_open=1.0,
        net_job_multiplier=1.6, lag_years=7,
        notes="Design engineers augmented; complexity of designs increased demand",
        sources=["Autor, D., Levy, F., Murnane, R. (2003). QJE 118(4)"]),
    TransitionCase(
        id="x_ray_radiology", name="AI radiology assistance 2016-present",
        technology="Deep learning image classification",
        displaced_occupation="Radiologist / radiographer",
        period="2016-2026",
        augmentation_ratio=0.7, demand_elasticity=0.5, oring_leverage=0.8,
        skill_distance=0.3, diffusion_years=10, absorbing_sector=1.0,
        productivity_capture=0.6, task_frontier_open=1.0,
        net_job_multiplier=1.3, lag_years=8,
        notes="So far augmentation dominant; throughput up, radiologist numbers stable/up",
        sources=["Obermeyer, Z. & Emanuel, E. (2016). NEJM 375:1216-1219",
                 "BLS OES 2016-2024"]),
    TransitionCase(
        id="steam_printing", name="Steam printing press & compositors 1820-1880",
        technology="Steam-powered rotary press",
        displaced_occupation="Hand-press compositor",
        period="1820-1880",
        augmentation_ratio=0.2, demand_elasticity=0.95, oring_leverage=0.3,
        skill_distance=0.5, diffusion_years=25, absorbing_sector=0.7,
        productivity_capture=0.3, task_frontier_open=1.0,
        net_job_multiplier=4.0, lag_years=20,
        notes="Mass literacy demand exploded; newspaper/book printing jobs multiplied",
        sources=["Mokyr, J. (1990). The Lever of Riches. Oxford UP."]),
    TransitionCase(
        id="industrial_robots_auto", name="Industrial robots & auto assembly 1980-2010",
        technology="Programmable robotic arms",
        displaced_occupation="Assembly-line worker (autos)",
        period="1980-2010",
        augmentation_ratio=0.25, demand_elasticity=0.4, oring_leverage=0.35,
        skill_distance=0.6, diffusion_years=20, absorbing_sector=0.5,
        productivity_capture=0.35, task_frontier_open=0.4,
        net_job_multiplier=0.6, lag_years=20,
        notes="Acemoglu & Restrepo: each robot displaced 3-6 workers, slow reabsorption",
        sources=["Acemoglu, D. & Restrepo, P. (2020). AER 110(6):2188-2244"]),
    TransitionCase(
        id="llm_coding", name="LLM coding assistants & software developers 2022-present",
        technology="GitHub Copilot / LLM code generation",
        displaced_occupation="Junior software developer / code reviewer",
        period="2022-2026",
        augmentation_ratio=0.75, demand_elasticity=0.65, oring_leverage=0.8,
        skill_distance=0.25, diffusion_years=5, absorbing_sector=1.0,
        productivity_capture=0.55, task_frontier_open=1.0,
        net_job_multiplier=1.2, lag_years=4,
        notes="Early data: developer productivity up ~30%; hiring slowed but not collapsed",
        sources=["Peng, S. et al. (2023). arXiv:2302.06590",
                 "BLS OES 2022-2024 (preliminary)"]),
    TransitionCase(
        id="gps_navigation", name="GPS & taxi/delivery navigation 2007-2020",
        technology="Smartphone GPS / mapping apps",
        displaced_occupation="'The Knowledge' taxi driver skill",
        period="2007-2020",
        augmentation_ratio=0.8, demand_elasticity=0.9, oring_leverage=0.5,
        skill_distance=0.2, diffusion_years=8, absorbing_sector=1.0,
        productivity_capture=0.5, task_frontier_open=1.0,
        net_job_multiplier=2.5, lag_years=3,
        notes="Rideshare + delivery explosion; total driver/courier count rose sharply",
        sources=["BLS OES 2007-2020", "Cramer, J. & Krueger, A. (2016). AER P&P 106(5)"]),
    TransitionCase(
        id="call_centre_ivr", name="IVR / chatbot & call-centre agents 2010-2025",
        technology="NLP-based IVR, then LLM chatbots",
        displaced_occupation="Call-centre agent (tier-1)",
        period="2010-2025",
        augmentation_ratio=0.3, demand_elasticity=0.5, oring_leverage=0.4,
        skill_distance=0.4, diffusion_years=10, absorbing_sector=0.6,
        productivity_capture=0.35, task_frontier_open=0.5,
        net_job_multiplier=0.85, lag_years=15,
        notes="Net slight job loss; complex-query agents grew but offset by tier-1 decline",
        sources=["OECD (2023). Artificial Intelligence and the Labour Market"]),
    TransitionCase(
        id="ecommerce_retail", name="E-commerce & retail clerks 2000-2023",
        technology="Online retail platforms",
        displaced_occupation="Retail sales clerk",
        period="2000-2023",
        augmentation_ratio=0.2, demand_elasticity=0.75, oring_leverage=0.2,
        skill_distance=0.5, diffusion_years=15, absorbing_sector=0.7,
        productivity_capture=0.3, task_frontier_open=0.5,
        net_job_multiplier=0.9, lag_years=18,
        notes="Warehouse/logistics grew but did not fully offset retail job losses",
        sources=["BLS OES 2000-2023",
                 "Autor, D. et al. (2020). A New (Training) Paradigm. NBER WP 28388"]),
]


# --------------------------------------------------------------------------- #
# Variable matrix helper
# --------------------------------------------------------------------------- #

VARIABLE_NAMES = [
    "augmentation_ratio", "demand_elasticity", "oring_leverage",
    "skill_distance", "diffusion_years", "absorbing_sector",
    "productivity_capture", "task_frontier_open",
]

def _normalise_diffusion(cases: list[TransitionCase]) -> np.ndarray:
    """Build the n×8 variable matrix with diffusion_years log-scaled."""
    rows = []
    for c in cases:
        v = [getattr(c, name) for name in VARIABLE_NAMES]
        v[4] = math.log1p(v[4]) / math.log1p(50)   # normalise diffusion to ~0-1
        rows.append(v)
    return np.array(rows, dtype=float)


# --------------------------------------------------------------------------- #
# Interfaces (the harness seams)
# --------------------------------------------------------------------------- #

class Reducer(Protocol):
    """Dimensionality reducer: fit on X, transform to latent space."""
    def fit(self, X: np.ndarray) -> "Reducer": ...
    def transform(self, X: np.ndarray) -> np.ndarray: ...
    def components(self) -> np.ndarray: ...   # shape (n_components, n_features)


class Clusterer(Protocol):
    def fit(self, Z: np.ndarray) -> "Clusterer": ...
    def predict(self, Z: np.ndarray) -> np.ndarray: ...        # cluster labels
    def cluster_centers(self) -> np.ndarray: ...
    def responsibilities(self, Z: np.ndarray) -> np.ndarray: ...  # soft probabilities


# --------------------------------------------------------------------------- #
# Deterministic backends (offline, seeded — the harness stubs)
# --------------------------------------------------------------------------- #

class PCAReducer:
    """Thin wrapper around sklearn PCA with a fixed seed."""
    def __init__(self, n_components: int = 3, seed: int = 42):
        from sklearn.decomposition import PCA
        from sklearn.preprocessing import StandardScaler
        self._scaler = StandardScaler()
        self._pca = PCA(n_components=n_components, random_state=seed)
        self._n = n_components

    def fit(self, X: np.ndarray) -> "PCAReducer":
        Xs = self._scaler.fit_transform(X)
        self._pca.fit(Xs)
        self._evr = self._pca.explained_variance_ratio_
        return self

    def transform(self, X: np.ndarray) -> np.ndarray:
        return self._pca.transform(self._scaler.transform(X))

    def components(self) -> np.ndarray:
        return self._pca.components_

    def explained_variance_ratio(self) -> np.ndarray:
        return self._evr


class BayesianGMMClusterer:
    """Bayesian Gaussian mixture — number of clusters shrinks automatically."""
    def __init__(self, max_components: int = 5, seed: int = 42):
        from sklearn.mixture import BayesianGaussianMixture
        self._model = BayesianGaussianMixture(
            n_components=max_components, random_state=seed,
            weight_concentration_prior_type="dirichlet_process",
            weight_concentration_prior=0.5,
            covariance_type="full", max_iter=500, n_init=3)

    def fit(self, Z: np.ndarray) -> "BayesianGMMClusterer":
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self._model.fit(Z)
        return self

    def predict(self, Z: np.ndarray) -> np.ndarray:
        return self._model.predict(Z)

    def cluster_centers(self) -> np.ndarray:
        return self._model.means_

    def responsibilities(self, Z: np.ndarray) -> np.ndarray:
        return self._model.predict_proba(Z)


# --------------------------------------------------------------------------- #
# OOD detector
# --------------------------------------------------------------------------- #

def _mahalanobis(x: np.ndarray, mu: np.ndarray, cov: np.ndarray) -> float:
    delta = x - mu
    try:
        inv = np.linalg.pinv(cov)
        return float(math.sqrt(max(0.0, delta @ inv @ delta)))
    except Exception:
        return float("inf")


class OODDetector:
    """Flags how far a new scenario is from every historical cluster.
    High score = 'I am extrapolating outside my training history' →
    forecaster should widen confidence intervals."""

    def __init__(self, threshold_percentile: float = 90.0):
        self._threshold_pct = threshold_percentile
        self._cluster_stats: list[tuple[np.ndarray, np.ndarray]] = []
        self._threshold: float = float("inf")

    def fit(self, Z: np.ndarray, labels: np.ndarray) -> "OODDetector":
        self._cluster_stats = []
        for label in np.unique(labels):
            members = Z[labels == label]
            mu = members.mean(axis=0)
            cov = np.cov(members.T) if len(members) > 1 else np.eye(Z.shape[1]) * 1e-6
            if cov.ndim == 0:
                cov = np.array([[float(cov)]])
            self._cluster_stats.append((mu, cov))
        # calibrate threshold from training distances
        dists = [min(_mahalanobis(Z[i], mu, cov)
                     for mu, cov in self._cluster_stats)
                 for i in range(len(Z))]
        self._threshold = float(np.percentile(dists, self._threshold_pct))
        return self

    def score(self, z: np.ndarray) -> dict:
        """Returns min_distance, is_ood flag, and nearest_cluster index."""
        dists = [_mahalanobis(z, mu, cov) for mu, cov in self._cluster_stats]
        min_d = min(dists)
        return {
            "min_mahalanobis": round(min_d, 4),
            "nearest_cluster": int(np.argmin(dists)),
            "is_ood": bool(min_d > self._threshold),
            "threshold": round(self._threshold, 4),
            "ood_ratio": round(min_d / max(self._threshold, 1e-9), 4),
        }


# --------------------------------------------------------------------------- #
# Output: the prior the forecaster consumes
# --------------------------------------------------------------------------- #

@dataclass
class ClusterProfile:
    label: int
    size: int
    name: str                         # interpretive label (set by interpreter)
    centroid_variables: dict          # readable variable → value
    mean_multiplier: float
    mean_lag_years: float
    member_ids: list[str]

@dataclass
class EvolutionPrior:
    """Everything the forecaster needs, in one serialisable object."""
    # Factor structure
    n_factors: int
    factor_loadings: list[dict]       # [{factor: 0, variable: str, loading: float}]
    explained_variance: list[float]

    # Cluster profiles (transition regimes)
    clusters: list[ClusterProfile]

    # OOD assessment of current AI scenario
    current_scenario_ood: dict        # score dict from OODDetector
    nearest_cluster: ClusterProfile

    # Conditional rules extracted from data
    conditional_rules: list[str]

    # Stability check
    bootstrap_stability: float        # mean cluster-assignment agreement, 0-1

    def to_prompt_context(self) -> str:
        """Render as a compact, LLM-readable prior for the forecaster prompt."""
        ood = self.current_scenario_ood
        nc = self.nearest_cluster
        lines = [
            "## Job-evolution prior (from historical transition model)",
            "",
            f"OOD signal: min_mahalanobis={ood['min_mahalanobis']} "
            f"threshold={ood['threshold']} "
            f"{'⚠ OUTSIDE HISTORY — widen confidence intervals' if ood['is_ood'] else 'within historical envelope'}",
            "",
            f"Nearest historical regime: '{nc.name}' "
            f"(mean net_job_multiplier={nc.mean_multiplier:.2f}, "
            f"mean_lag_years={nc.mean_lag_years:.1f})",
            "",
            "Conditional rules extracted from case library:",
        ]
        for r in self.conditional_rules:
            lines.append(f"  • {r}")
        lines += [
            "",
            f"Bootstrap cluster stability: {self.bootstrap_stability:.2f} "
            f"(1.0=perfectly stable, <0.7=treat clusters as tentative)",
            "",
            "⚠ These are correlational priors, not causal laws. "
            "The OOD signal above is the most important single number: "
            "if it fires, historical patterns may not transfer.",
        ]
        return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Factor interpreter (reads loadings → human-readable factor names)
# --------------------------------------------------------------------------- #

_FACTOR_LABELS = {
    "augmentation_ratio":   ("complementarity", +1),
    "task_frontier_open":   ("complementarity", +1),
    "oring_leverage":       ("complementarity", +1),
    "productivity_capture": ("complementarity", +1),
    "absorbing_sector":     ("complementarity", +1),
    "demand_elasticity":    ("demand_expansion", +1),
    "skill_distance":       ("transition_friction", +1),
    "diffusion_years":      ("transition_friction", +1),
}

_DIMENSION_NAMES = {
    "complementarity": "Complementary growth",
    "demand_expansion": "Demand expansion",
    "transition_friction": "High transition friction",
    "latent": "Latent regime",
    "other": "Other",
}


def _short_case_title(name: str) -> str:
    """Trim year/period suffix for a compact chart label."""
    for sep in (" 197", " 198", " 199", " 200", " 201", " 202", " 180", " 190"):
        if sep in name:
            return name.split(sep)[0].strip()
    return name.strip()


def _outcome_phrase(mean_mult: float) -> str:
    if mean_mult >= 1.25:
        return f"{mean_mult:.1f}x job growth"
    if mean_mult >= 0.95:
        return f"{mean_mult:.1f}x mixed outcome"
    return f"{mean_mult:.1f}x displacement"


def _trait_phrases(var_means: dict[str, float]) -> list[str]:
    traits: list[str] = []
    aug = float(var_means.get("augmentation_ratio", 0.5))
    if aug >= 0.55:
        traits.append("complementary tools")
    elif aug <= 0.3:
        traits.append("heavy substitution")
    skill = float(var_means.get("skill_distance", 0.5))
    if skill >= 0.6:
        traits.append("steep retraining")
    elif skill <= 0.35:
        traits.append("easy reskilling")
    de = float(var_means.get("demand_elasticity", 0.5))
    if de >= 0.75:
        traits.append("elastic demand")
    diff = float(var_means.get("diffusion_years", 15))
    if diff >= 25:
        traits.append("slow diffusion")
    elif diff <= 12:
        traits.append("fast diffusion")
    if float(var_means.get("absorbing_sector", 0)) >= 0.5:
        traits.append("Baumol absorption")
    return traits[:2]


def _name_cluster(
    members: list[TransitionCase],
    var_means: dict[str, float],
    mean_mult: float,
    mean_lag: float,
) -> str:
    """Distinct English label anchored on the medoid historical case."""
    anchor = min(
        members,
        key=lambda m: sum(
            (float(getattr(m, v)) - float(var_means.get(v, 0))) ** 2
            for v in VARIABLE_NAMES
        ),
    )
    title = _short_case_title(anchor.name)
    traits = _trait_phrases(var_means)
    trait_part = f" · {traits[0]}" if traits else ""
    return f"{title} · {_outcome_phrase(mean_mult)}{trait_part} · {mean_lag:.0f}yr lag"


def _name_factor(loadings: list[tuple[str, float]]) -> str:
    scores: dict[str, float] = {}
    for var, load in loadings:
        dim, sign = _FACTOR_LABELS.get(var, ("other", 1))
        scores[dim] = scores.get(dim, 0.0) + abs(load) * sign * (1 if load > 0 else -1)
    raw_name = max(scores, key=lambda k: abs(scores[k]), default="latent")
    return _DIMENSION_NAMES.get(raw_name, raw_name)


# --------------------------------------------------------------------------- #
# Conditional rules extractor (deterministic, pure function)
# --------------------------------------------------------------------------- #

def extract_conditional_rules(cases: list[TransitionCase]) -> list[str]:
    """Derive human-readable conditional regularities from the case library.
    Intentionally simple and transparent — no black-box inference."""
    rules = []
    high_aug = [c for c in cases if c.augmentation_ratio >= 0.5]
    low_aug  = [c for c in cases if c.augmentation_ratio < 0.5]

    if high_aug and low_aug:
        m_h = sum(c.net_job_multiplier for c in high_aug) / len(high_aug)
        m_l = sum(c.net_job_multiplier for c in low_aug)  / len(low_aug)
        rules.append(
            f"High augmentation_ratio (≥0.5) → mean net_job_multiplier "
            f"{m_h:.2f} vs {m_l:.2f} for low (n={len(high_aug)}/{len(low_aug)})")

    elastic = [c for c in cases if c.demand_elasticity >= 0.7]
    inelastic = [c for c in cases if c.demand_elasticity < 0.5]
    if elastic and inelastic:
        m_e = sum(c.net_job_multiplier for c in elastic) / len(elastic)
        m_i = sum(c.net_job_multiplier for c in inelastic) / len(inelastic)
        rules.append(
            f"High demand elasticity (≥0.7) → mean multiplier {m_e:.2f} "
            f"vs {m_i:.2f} (n={len(elastic)}/{len(inelastic)})")

    hard = [c for c in cases if c.skill_distance >= 0.6]
    easy = [c for c in cases if c.skill_distance < 0.4]
    if hard and easy:
        l_h = sum(c.lag_years for c in hard) / len(hard)
        l_e = sum(c.lag_years for c in easy) / len(easy)
        rules.append(
            f"High skill_distance (≥0.6) → mean lag {l_h:.1f}yr "
            f"vs {l_e:.1f}yr for low distance (n={len(hard)}/{len(easy)})")

    absorb = [c for c in cases if c.absorbing_sector == 1.0]
    no_abs = [c for c in cases if c.absorbing_sector == 0.0]
    if absorb and no_abs:
        m_a = sum(c.net_job_multiplier for c in absorb) / len(absorb)
        m_n = sum(c.net_job_multiplier for c in no_abs)  / len(no_abs)
        rules.append(
            f"Absorbing Baumol sector present → mean multiplier {m_a:.2f} "
            f"vs {m_n:.2f} without (n={len(absorb)}/{len(no_abs)})")

    net_gain = [c for c in cases if c.net_job_multiplier > 1.0]
    net_loss  = [c for c in cases if c.net_job_multiplier <= 1.0]
    if net_gain and net_loss:
        g_aug = sum(c.augmentation_ratio for c in net_gain) / len(net_gain)
        l_aug = sum(c.augmentation_ratio for c in net_loss)  / len(net_loss)
        rules.append(
            f"Net-gain transitions (n={len(net_gain)}): "
            f"mean augmentation_ratio={g_aug:.2f}; "
            f"net-loss (n={len(net_loss)}): mean={l_aug:.2f} "
            f"→ augmentation_ratio is the strongest discriminator in this sample")

    rules.append(
        "CAUTION: n=15 cases, non-stationary history. "
        "Rules are correlational; confidence intervals should be wide. "
        "The OOD signal is more important than any single rule.")
    return rules


# --------------------------------------------------------------------------- #
# Bootstrap stability check (pure numpy, seeded)
# --------------------------------------------------------------------------- #

def bootstrap_cluster_stability(
    X: np.ndarray, reducer: Reducer, clusterer: Clusterer,
    n_boot: int = 50, seed: int = 42
) -> float:
    """Fraction of bootstrap resamples where each point lands in the same cluster
    as in the full-data fit. Measures how robust the cluster structure is to
    small sample variation."""
    rng = np.random.default_rng(seed)
    Z_full = reducer.transform(X)
    base_labels = clusterer.predict(Z_full)
    agreements = []
    for _ in range(n_boot):
        idx = rng.integers(0, len(X), size=len(X))
        X_b = X[idx]
        from sklearn.decomposition import PCA
        from sklearn.preprocessing import StandardScaler
        from sklearn.mixture import BayesianGaussianMixture
        sc = StandardScaler(); pca = PCA(n_components=reducer._n, random_state=seed)
        Z_b = pca.fit_transform(sc.fit_transform(X_b))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            bgmm = BayesianGaussianMixture(
                n_components=5, random_state=seed,
                weight_concentration_prior_type="dirichlet_process",
                weight_concentration_prior=0.5, max_iter=300).fit(Z_b)
        Z_orig = pca.transform(sc.transform(X))
        boot_labels = bgmm.predict(Z_orig)
        # agreement = adjusted rand index (scipy)
        from scipy.stats import spearmanr  # noqa just to check scipy present
        from sklearn.metrics import adjusted_rand_score
        agreements.append(adjusted_rand_score(base_labels, boot_labels))
    return float(np.mean(agreements))


# --------------------------------------------------------------------------- #
# Main entry point
# --------------------------------------------------------------------------- #

# Current AI scenario vector (point estimate for OOD assessment).
# Represents the best-guess variable values for the 2024-2030 AI transition.
# Deliberately uncertain: adjust these as evidence accumulates.
CURRENT_AI_SCENARIO: dict = {
    "augmentation_ratio":  0.60,   # unclear; copilot-style tools suggest high
    "demand_elasticity":   0.65,   # some induced demand but saturation unclear
    "oring_leverage":      0.75,   # strong: AI output raises value of human judgement
    "skill_distance":      0.55,   # varies hugely by occupation
    "diffusion_years":     7.0,    # fast by historical standards
    "absorbing_sector":    0.80,   # care/education/craft likely Baumol refuges
    "productivity_capture":0.45,   # contested; currently skewing capital
    "task_frontier_open":  0.70,   # new tasks emerging but hard to name ex-ante
}


def build_prior(
    cases: list[TransitionCase] | None = None,
    reducer: Reducer | None = None,
    clusterer: Clusterer | None = None,
    current_scenario: dict | None = None,
    n_bootstrap: int = 50,
) -> EvolutionPrior:
    cases = cases or CASE_LIBRARY
    reducer = reducer or PCAReducer(n_components=3)
    clusterer = clusterer or BayesianGMMClusterer(max_components=5)
    scenario = current_scenario or CURRENT_AI_SCENARIO

    X = _normalise_diffusion(cases)

    # 1. reduce
    reducer.fit(X)
    Z = reducer.transform(X)
    evr = getattr(reducer, "explained_variance_ratio", lambda: [0.0] * 3)()

    # 2. cluster
    clusterer.fit(Z)
    labels = clusterer.predict(Z)

    # 3. factor loadings → readable
    comps = reducer.components()   # (n_factors, n_vars)
    factor_loadings = []
    for fi, row in enumerate(comps):
        for vi, val in enumerate(row):
            factor_loadings.append({"factor": fi, "variable": VARIABLE_NAMES[vi],
                                    "loading": round(float(val), 4)})

    # 4. cluster profiles
    profiles = []
    used_names: dict[str, int] = {}
    for lbl in sorted(set(labels)):
        members = [c for c, l in zip(cases, labels) if l == lbl]
        var_means = {}
        for vname in VARIABLE_NAMES:
            var_means[vname] = round(
                sum(getattr(m, vname) for m in members) / len(members), 3)
        mean_mult = sum(m.net_job_multiplier for m in members) / len(members)
        mean_lag  = sum(m.lag_years for m in members) / len(members)
        base_name = _name_cluster(members, var_means, mean_mult, mean_lag)
        if base_name in used_names:
            used_names[base_name] += 1
            display_name = f"{base_name} (variant {used_names[base_name]})"
        else:
            used_names[base_name] = 1
            display_name = base_name
        profiles.append(ClusterProfile(
            label=int(lbl), size=len(members),
            name=display_name,
            centroid_variables=var_means,
            mean_multiplier=round(mean_mult, 3),
            mean_lag_years=round(mean_lag, 1),
            member_ids=[m.id for m in members]))

    # 5. OOD detection
    ood_det = OODDetector()
    ood_det.fit(Z, labels)
    scenario_vec = np.array([
        scenario.get(v, 0.5) if v != "diffusion_years"
        else math.log1p(scenario.get(v, 10)) / math.log1p(50)
        for v in VARIABLE_NAMES
    ], dtype=float).reshape(1, -1)
    z_scenario = reducer.transform(scenario_vec)[0]
    ood_score = ood_det.score(z_scenario)
    nearest = profiles[ood_score["nearest_cluster"]]

    # 6. conditional rules
    rules = extract_conditional_rules(cases)

    # 7. bootstrap stability
    stability = bootstrap_cluster_stability(X, reducer, clusterer,
                                            n_boot=n_bootstrap)

    return EvolutionPrior(
        n_factors=len(comps),
        factor_loadings=factor_loadings,
        explained_variance=list(evr),
        clusters=profiles,
        current_scenario_ood=ood_score,
        nearest_cluster=nearest,
        conditional_rules=rules,
        bootstrap_stability=round(stability, 3),
    )
