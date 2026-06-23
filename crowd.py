"""Crowd gate: turn many overlapping human contributions into a sparse set of
high-information, well-argued, decorrelated signals — then aggregate.

Design (harness conventions)
----------------------------
* All nondeterminism lives behind interfaces (`Embedder`, `SoundnessJudge`) so the
  core is deterministic and unit-testable offline. Real LLM/embedding backends are
  drop-in replacements for the deterministic stubs.
* The scoring core (`js_divergence`, novelty, sparse selection, aggregation) is pure
  functions over plain Python — no network, no hidden state.
* Every admit/reject decision emits a structured `Decision` trace for observability.
* Two conjunctive gates: SOUNDNESS (is it valid + evidence-backed?) AND NOVELTY
  (is it decorrelated from what we already have?). Entropy selects/explores;
  it is never the arbiter — realised Brier (via `skill_fn`) governs long-run weight.
* Sparsity = de-redundancy: greedy novelty gating collapses viewpoint clusters to
  representatives, then a top-k cap keeps only the few non-zero "parameters".
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional, Protocol

# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #


from schemas import Contribution


@dataclass
class SoundnessVerdict:
    soundness: float          # 0..1 reasoning quality
    evidence_ok: bool         # passes the hard verifiable-evidence gate
    reasons: str = ""


@dataclass
class Decision:
    """Observable trace of what the gate did with one contribution."""
    contribution_id: str
    contributor_id: str
    soundness: Optional[float] = None
    evidence_ok: Optional[bool] = None
    novelty: Optional[float] = None
    admitted: bool = False
    weight: float = 0.0
    reason: str = ""


@dataclass
class GateResult:
    target_id: str
    prior_probability: float          # agent's own forecast before the crowd
    aggregate_probability: float      # crowd-adjusted forecast
    selected: list[str]               # contribution ids that became non-zero params
    decisions: list[Decision]

    def explain(self) -> str:
        lines = [f"target={self.target_id}  prior={self.prior_probability:.3f} "
                 f"-> aggregate={self.aggregate_probability:.3f}  "
                 f"({len(self.selected)} of {len(self.decisions)} admitted)"]
        for d in self.decisions:
            tag = f"ADMIT w={d.weight:.3f}" if d.admitted else f"REJECT[{d.reason}]"
            sc = f"snd={d.soundness}" if d.soundness is not None else "snd=-"
            nv = f"nov={d.novelty:.3f}" if d.novelty is not None else "nov=-"
            lines.append(f"  {tag:<22} {sc} {nv}  {d.contributor_id}")
        return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Interfaces (the harness seams)
# --------------------------------------------------------------------------- #


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class SoundnessJudge(Protocol):
    def score(self, c: Contribution, target_statement: str) -> SoundnessVerdict: ...


# --------------------------------------------------------------------------- #
# Deterministic default backends (offline, no API key)
# --------------------------------------------------------------------------- #

_TOKEN = re.compile(r"[a-z0-9]+")


class HashingEmbedder:
    """Deterministic bag-of-tokens hashing embedding. No network. Good for tests
    and a sane default; swap for a real embeddings API in production."""

    def __init__(self, dim: int = 256):
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            v = [0.0] * self.dim
            for tok in _TOKEN.findall(t.lower()):
                bucket = int.from_bytes(hashlib.md5(tok.encode()).digest()[:4], "big")
                v[bucket % self.dim] += 1.0
            out.append(_l2(v))
        return out


class HeuristicSoundnessJudge:
    """Deterministic, offline soundness proxy. Enforces the hard evidence gate and
    rewards structured reasoning over bare assertion. A reasonable default and the
    fixture backend for evals; LLMSoundnessJudge is the production backend."""

    CONNECTIVES = ("because", "therefore", "however", "since", "thus", "given",
                   "implies", "whereas", "consequently", "if", "so", "but")

    def score(self, c: Contribution, target_statement: str) -> SoundnessVerdict:
        evidence_ok = len(c.evidence_urls) > 0
        words = c.argument.split()
        length_score = min(1.0, len(words) / 60.0)
        conn = sum(c.argument.lower().count(k) for k in self.CONNECTIVES)
        reasoning_score = min(1.0, conn / 4.0)
        # bare assertions (no connectives, very short) score low
        soundness = round(0.5 * length_score + 0.5 * reasoning_score, 3)
        return SoundnessVerdict(
            soundness=soundness, evidence_ok=evidence_ok,
            reasons=f"len={len(words)} connectives={conn} evidence={len(c.evidence_urls)}")


class LLMSoundnessJudge:
    """Production backend: an LLM grades the argument against a strict rubric.

    Uses call_llm() for provider routing (Groq free tier → Anthropic → error).
    Web-search tool is omitted for Groq compatibility; evidence is assessed
    by URL-presence heuristic in the prompt instead.
    Kept behind the SoundnessJudge interface so the core stays testable without it.
    """

    def __init__(self, model: str | None = None):
        # None → call_llm() selects the best available model automatically
        self.model = model

    def score(self, c: Contribution, target_statement: str) -> SoundnessVerdict:
        try:
            from forecast import call_llm
        except ImportError:
            from .forecast import call_llm

        system = (
            "You are a strict argument quality judge. Grade contributions on a "
            "0..1 soundness rubric: valid logic, falsifiable claims, engagement "
            "with the strongest counterargument, and whether cited evidence URLs "
            "plausibly support the position. Be concise and objective."
        )
        user = (
            f"Claim under discussion: {target_statement}\n"
            f"Contributor's position: P(true)={c.probability}\n"
            f"Argument: {c.argument}\n"
            f"Evidence URLs provided: {c.evidence_urls}\n\n"
            "Return ONLY JSON (no code fences): "
            '{"soundness": 0.0..1.0, "evidence_ok": true|false, "reasons": "brief explanation"}'
        )
        text = call_llm(system, user, max_tokens=400, model=self.model)
        s, e = text.find("{"), text.rfind("}")
        data = json.loads(text[s:e + 1])
        return SoundnessVerdict(
            soundness=float(data.get("soundness", 0.0)),
            evidence_ok=bool(data.get("evidence_ok", False)),
            reasons=str(data.get("reasons", "")))


# --------------------------------------------------------------------------- #
# Pure scoring core (deterministic, fully unit-tested)
# --------------------------------------------------------------------------- #

_EPS = 1e-9
_LN2 = math.log(2.0)


def _l2(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v] if n > _EPS else v


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))  # inputs assumed L2-normalised


def _kl_bernoulli(p: float, q: float) -> float:
    p = min(1 - _EPS, max(_EPS, p))
    q = min(1 - _EPS, max(_EPS, q))
    return p * math.log(p / q) + (1 - p) * math.log((1 - p) / (1 - q))


def js_divergence(p: float, q: float) -> float:
    """Jensen-Shannon divergence between Bernoulli(p) and Bernoulli(q), in [0,1]."""
    m = 0.5 * (p + q)
    jsd = 0.5 * _kl_bernoulli(p, m) + 0.5 * _kl_bernoulli(q, m)
    return max(0.0, min(1.0, jsd / _LN2))


def novelty(prob: float, arg_vec: list[float], ensemble_prob: float,
            existing_vecs: list[list[float]], alpha: float = 0.4) -> float:
    """Marginal information of a contribution vs the current ensemble.
    Combines forecast divergence (how different the number is) with semantic
    novelty (how different the *reasoning* is). Both in [0,1]."""
    forecast_term = js_divergence(prob, ensemble_prob)
    if existing_vecs:
        sim = max(cosine(arg_vec, e) for e in existing_vecs)
        semantic_term = max(0.0, 1.0 - max(0.0, sim))
    else:
        semantic_term = 1.0
    return alpha * forecast_term + (1 - alpha) * semantic_term


def aggregate(prior_p: float, picks: list[tuple[float, float]],
              prior_weight: float = 1.0, extremize: float = 1.0) -> float:
    """Weighted combination of the prior (agent) forecast and selected (prob, weight)
    contributions. `extremize`>1 pushes the result away from 0.5 (crowds are often
    under-confident); =1 is off."""
    num = prior_p * prior_weight
    den = prior_weight
    for p, w in picks:
        num += p * w
        den += w
    p = num / den if den > _EPS else prior_p
    if extremize != 1.0:
        a = p ** extremize
        b = (1 - p) ** extremize
        p = a / (a + b + _EPS)
    return max(0.0, min(1.0, p))


# --------------------------------------------------------------------------- #
# The gate
# --------------------------------------------------------------------------- #


@dataclass
class GateConfig:
    tau_soundness: float = 0.5     # min reasoning quality to pass the validity gate
    tau_novelty: float = 0.25      # min marginal information to pass the diversity gate
    k: int = 5                     # sparsity cap: max non-zero contributions
    alpha: float = 0.4             # forecast-vs-semantic novelty mix
    skill_floor: float = 0.25      # min weight factor for cold-start contributors
    extremize: float = 1.0
    prior_weight: float = 1.0      # weight of the agent's own forecast


class CrowdGate:
    def __init__(self, embedder: Embedder, judge: SoundnessJudge,
                 skill_fn: Callable[[str], float] | None = None,
                 cfg: GateConfig | None = None):
        self.embedder = embedder
        self.judge = judge
        self.skill_fn = skill_fn or (lambda _cid: 0.5)  # neutral prior skill
        self.cfg = cfg or GateConfig()

    def process(self, target_statement: str, target_id: str, prior_p: float,
                prior_rationale: str, contributions: list[Contribution]) -> GateResult:
        cfg = self.cfg
        decisions: list[Decision] = []

        # 1. SOUNDNESS gate (cheap reject of noise + hard evidence requirement) ----
        survivors: list[tuple[Contribution, SoundnessVerdict]] = []
        for c in contributions:
            v = self.judge.score(c, target_statement)
            d = Decision(c.id, c.contributor_id, soundness=v.soundness,
                         evidence_ok=v.evidence_ok)
            if not v.evidence_ok:
                d.reason = "no_evidence"
                decisions.append(d)
                continue
            if v.soundness < cfg.tau_soundness:
                d.reason = "weak_argument"
                decisions.append(d)
                continue
            survivors.append((c, v))
            decisions.append(d)

        # process strongest arguments first so near-duplicates of them read as redundant
        survivors.sort(key=lambda cv: (-cv[1].soundness, cv[0].id))
        dmap = {d.contribution_id: d for d in decisions}

        # 2. NOVELTY gate (greedy de-redundancy = implicit viewpoint clustering) ---
        texts = [prior_rationale] + [c.argument for c, _ in survivors]
        vecs = self.embedder.embed(texts)
        prior_vec, surv_vecs = vecs[0], vecs[1:]

        existing_vecs = [prior_vec]
        ensemble = [prior_p]
        admitted: list[tuple[Contribution, SoundnessVerdict, float]] = []
        for (c, v), vec in zip(survivors, surv_vecs):
            ens_mean = sum(ensemble) / len(ensemble)
            nov = novelty(c.probability, vec, ens_mean, existing_vecs, cfg.alpha)
            dmap[c.id].novelty = round(nov, 4)
            if nov < cfg.tau_novelty:
                dmap[c.id].reason = "redundant"
                continue
            admitted.append((c, v, nov))
            existing_vecs.append(vec)
            ensemble.append(c.probability)

        # 3. SPARSE selection: keep top-k by quality x diversity; rest -> zero -----
        def quality(cv):
            c, v, nov = cv
            skill = max(cfg.skill_floor, self.skill_fn(c.contributor_id))
            return v.soundness * skill * (0.5 + 0.5 * nov)

        admitted.sort(key=lambda cv: -quality(cv))
        selected = admitted[: cfg.k]
        for c, _, _ in admitted[cfg.k:]:
            dmap[c.id].reason = "pruned_sparsity"

        # 4. weight + aggregate ----------------------------------------------------
        picks: list[tuple[float, float]] = []
        chosen_ids: list[str] = []
        for c, v, nov in selected:
            w = round(quality((c, v, nov)), 4)
            dmap[c.id].admitted = True
            dmap[c.id].weight = w
            dmap[c.id].reason = "admitted"
            picks.append((c.probability, w))
            chosen_ids.append(c.id)

        agg = aggregate(prior_p, picks, cfg.prior_weight, cfg.extremize)
        return GateResult(target_id, prior_p, round(agg, 4), chosen_ids,
                          list(decisions))


# --------------------------------------------------------------------------- #
# Persistence: store contributions, score them once the target resolves
# --------------------------------------------------------------------------- #


class ContributionStore:
    """Records contributions and, once a target prediction resolves, scores each
    contributor's forecast by Brier — that realised score is what `skill_fn` reads,
    so reputation is earned, never assumed."""

    def __init__(self, path: str | Path | None = None):
        from sqlmodel import create_engine
        if path is not None:
            # Ensure the directory exists
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            self.engine = create_engine(f"sqlite:///{path}", echo=False)
        else:
            from schemas import engine
            self.engine = engine
        from sqlmodel import SQLModel
        SQLModel.metadata.create_all(self.engine)

    def add(self, c: Contribution) -> None:
        from sqlmodel import Session
        with Session(self.engine) as session:
            session.add(c)
            session.commit()

    def list_for_target(self, target_id: str) -> list[Contribution]:
        from sqlmodel import Session, select
        with Session(self.engine) as session:
            statement = select(Contribution).where(Contribution.target_id == target_id)
            return list(session.exec(statement).all())

    def get_by_contributor(self, target_id: str, contributor_id: str) -> Contribution | None:
        from sqlmodel import Session, select
        with Session(self.engine) as session:
            statement = select(Contribution).where(
                Contribution.target_id == target_id,
                Contribution.contributor_id == contributor_id,
            )
            return session.exec(statement).first()

    def target_ids_with_contributions(self) -> list[str]:
        from sqlmodel import Session, select
        with Session(self.engine) as session:
            rows = session.exec(select(Contribution.target_id).distinct()).all()
            return list(rows)

    def _all_serialized(self) -> list[dict]:
        from sqlmodel import Session, select
        with Session(self.engine) as session:
            statement = select(Contribution)
            contributions = session.exec(statement).all()
            out = []
            for c in contributions:
                out.append({
                    "id": c.id,
                    "target_id": c.target_id,
                    "contributor_id": c.contributor_id,
                    "probability": c.probability,
                    "argument": c.argument,
                    "evidence_urls": c.evidence_urls,
                    "created_at": c.created_at.isoformat() if isinstance(c.created_at, datetime) else c.created_at,
                    "outcome": c.outcome,
                    "brier": c.brier
                })
            return out

    def resolve_target(self, target_id: str, outcome: bool) -> int:
        from sqlmodel import Session, select
        with Session(self.engine) as session:
            statement = select(Contribution).where(
                Contribution.target_id == target_id,
                Contribution.outcome == None
            )
            contributions = session.exec(statement).all()
            n = 0
            for c in contributions:
                c.outcome = outcome
                c.brier = (c.probability - (1.0 if outcome else 0.0)) ** 2
                session.add(c)
                n += 1
            session.commit()
        return n

    def contributor_skill(self, contributor_id: str, min_history: int = 3) -> float:
        """Map a contributor's Brier history to a skill factor in [0,1].
        Cold-start contributors get a neutral 0.5 (exploration); skill is only
        sharpened once they have a track record (exploitation)."""
        from sqlmodel import Session, select
        with Session(self.engine) as session:
            statement = select(Contribution).where(
                Contribution.contributor_id == contributor_id,
                Contribution.brier != None
            )
            contributions = session.exec(statement).all()
            briers = [c.brier for c in contributions]
        if len(briers) < min_history:
            return 0.5
        mean_b = sum(briers) / len(briers)
        return max(0.0, min(1.0, 1.0 - mean_b / 0.25))

    def skill_fn(self) -> Callable[[str], float]:
        return self.contributor_skill


def log_trace(result: GateResult, path: str | Path = "data/crowd_traces.jsonl") -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        f.write(json.dumps({
            "ts": datetime.now(timezone.utc).isoformat(),
            "target_id": result.target_id,
            "prior": result.prior_probability,
            "aggregate": result.aggregate_probability,
            "selected": result.selected,
            "decisions": [asdict(d) for d in result.decisions],
        }) + "\n")
