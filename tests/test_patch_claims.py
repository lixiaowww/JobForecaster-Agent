"""Brier-scored claims over the query agent's self-mutations (offline, HR-1).

The property most of these tests exist to protect: the agent must not be able
to earn a good track record from its own writing. Every positive verdict has
to come from evidence that (a) is external to the KB and (b) did not exist
when the patch was applied.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import pytest

from registry import Registry
from schemas import JobFeedback, PatchClaim, Prediction, Status, brier_score
from services import provenance
from services.job_query_agent import claims as qa
from services.job_query_agent import evidence as ev

NOW = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)


def _cfg(**over):
    base = {
        "enabled": True,
        "horizon_days": 30,
        "min_satisfied_searches": 3,
        "reformulation_window_minutes": 10,
        "gate": {"enabled": True, "min_resolved": 5, "max_mean_brier": 0.35,
                 "warn_mean_brier": 0.25, "min_sim_penalty": 0.05,
                 "max_outstanding": 25},
    }
    base.update(over)
    return {"auto_apply": {"enabled": True, "min_sim_after": 0.55}, "claims": base}


def _claim(store=None, *, cid="p1", ctype="alias_patch", conf=0.8,
           created=NOW, res_date=date(2026, 3, 31), query="data engineer",
           target="tech_data_eng"):
    c = PatchClaim(
        id=cid, patch_type=ctype, query=query, target_id=target,
        statement="s", resolution_criteria="c", confidence=conf,
        created_at=created, resolution_date=res_date,
    )
    if store is not None:
        store.add(c)
    return c


# --- shared Brier definition ------------------------------------------------
def test_brier_score_is_shared_and_ambiguous_scores_none():
    assert brier_score(0.8, True) == pytest.approx(0.04)
    assert brier_score(0.8, False) == pytest.approx(0.64)
    # An unjudgeable claim must neither help nor hurt a track record.
    assert brier_score(0.8, None) is None

    p = Prediction(statement="x", rationale="r", confidence=0.8,
                   horizon="2026-Q4", resolution_date=date(2026, 12, 31),
                   resolution_criteria="c")
    c = _claim(conf=0.8)
    p.resolve(True, "why")
    c.resolve(True, "why")
    assert p.brier == c.brier          # same formula, both ledgers


# --- staking ----------------------------------------------------------------
def test_stake_is_lower_for_the_type_with_no_external_anchor():
    """kb_profile_new invents both the answer and the key — it must stake less."""
    anchored = qa.stake_confidence(
        "alias_patch", sim_after=0.80, min_sim=0.55, expected_id="tech_data_eng")
    invented = qa.stake_confidence(
        "kb_profile_new", sim_after=0.56, min_sim=0.55)
    assert invented < anchored
    assert 0.05 <= invented <= 0.95 and 0.05 <= anchored <= 0.95


def test_stake_rewards_headroom_not_bare_threshold_clearance():
    bare = qa.stake_confidence("alias_patch", sim_after=0.55, min_sim=0.55)
    clear = qa.stake_confidence("alias_patch", sim_after=0.95, min_sim=0.55)
    assert clear > bare


def test_build_claim_ignores_non_applied_and_unknown_types():
    cfg = _cfg()
    assert qa.build_claim({"auto_applied": False, "patch_id": "p", "type": "alias_patch"},
                          agent_cfg=cfg, query="q") is None
    assert qa.build_claim({"auto_applied": True, "type": "alias_patch"},
                          agent_cfg=cfg, query="q") is None
    assert qa.build_claim({"auto_applied": True, "patch_id": "p", "type": "weird"},
                          agent_cfg=cfg, query="q") is None


def test_build_claim_dates_the_claim_by_horizon():
    c = qa.build_claim(
        {"auto_applied": True, "patch_id": "px", "type": "alias_patch",
         "sim_after": 0.7, "best_id_after": "tech_data_eng"},
        agent_cfg=_cfg(horizon_days=14), query="data engineer",
        today=date(2026, 3, 1),
    )
    assert c is not None
    assert c.resolution_date == date(2026, 3, 15)
    assert c.status == Status.open and c.brier is None


# --- storage ----------------------------------------------------------------
def test_store_is_idempotent_per_patch_id(isolated_db):
    store = qa.ClaimStore(engine=isolated_db)
    assert store.add(_claim()) is not None
    assert store.add(_claim()) is None          # same patch_id, no duplicate
    assert len(store.load()) == 1


def test_ambiguous_claims_still_count_as_outstanding(isolated_db):
    """Otherwise an unfalsifiable patch is not merely unpunished — it is free."""
    store = qa.ClaimStore(engine=isolated_db)
    c = _claim(store)
    c.resolve(None, "no evidence")
    store.update(c)
    assert store.resolved() == []               # carries no Brier
    assert len(store.outstanding()) == 1        # but still counts against the cap


# --- evidence is post-patch only -------------------------------------------
def test_evidence_ignores_searches_that_predate_the_patch(tmp_path):
    """The searches that motivated a patch cannot also be its proof."""
    log = tmp_path / "log.jsonl"
    rows = [
        {"ts": (NOW - timedelta(days=2)).isoformat(), "query": "data engineer",
         "source": "radar"},
        {"ts": (NOW + timedelta(days=1)).isoformat(), "query": "data engineer",
         "source": "radar"},
    ]
    log.write_text("\n".join(json.dumps(r) for r in rows))
    satisfied, _ = ev.search_behaviour("data engineer", since=NOW, log_path=log)
    assert satisfied.count == 1                 # only the post-patch one


def test_reformulation_is_detected_within_the_window(tmp_path):
    log = tmp_path / "log.jsonl"
    rows = [
        {"ts": (NOW + timedelta(days=1)).isoformat(), "query": "data engineer",
         "source": "radar"},
        {"ts": (NOW + timedelta(days=1, minutes=2)).isoformat(),
         "query": "analytics engineer", "source": "radar"},
    ]
    log.write_text("\n".join(json.dumps(r) for r in rows))
    satisfied, reformed = ev.search_behaviour(
        "data engineer", since=NOW, log_path=log, window_minutes=10)
    assert reformed.count == 1 and satisfied.count == 0


def test_bls_presence_is_skipped_not_refuted_when_unavailable():
    """An unavailable source must read as 'no evidence', never as either verdict."""
    sig = ev.bls_presence({"id": "x", "title": "T"})
    assert sig.found is False and sig.strength == "skipped"
    sig = ev.bls_presence({"id": "x", "soc_code": "15-2051", "bls_employment": 120000})
    assert sig.found is True and sig.strength == "strong"


# --- judging ----------------------------------------------------------------
def test_no_evidence_resolves_ambiguous_never_true(tmp_path, isolated_db):
    """The core anti-tautology property of the whole module."""
    outcome, why, payload = qa.judge_claim(
        _claim(), agent_cfg=_cfg(), jobs_by_id={},
        log_path=tmp_path / "empty.jsonl",
        ledger_path=tmp_path / "ledger.jsonl", engine=isolated_db,
    )
    assert outcome is None
    assert payload["verdict_basis"] == "insufficient"
    assert brier_score(0.8, outcome) is None


def test_rollback_resolves_false(tmp_path, isolated_db):
    ledger = tmp_path / "ledger.jsonl"
    pid = provenance.record_patch(
        subsystem="job_query_agent", patch_type="alias_patch",
        reason="test", target_id="tech_data_eng", path=ledger)
    provenance.mark_reverted(pid, reason="regressed", path=ledger)

    outcome, why, payload = qa.judge_claim(
        _claim(cid=pid), agent_cfg=_cfg(), jobs_by_id={},
        log_path=tmp_path / "empty.jsonl", ledger_path=ledger, engine=isolated_db,
    )
    assert outcome is False and payload["verdict_basis"] == "rollback"


def test_reformulations_outweighing_satisfaction_resolves_false(tmp_path, isolated_db):
    log = tmp_path / "log.jsonl"
    rows = [
        {"ts": (NOW + timedelta(days=1)).isoformat(), "query": "data engineer",
         "source": "radar"},
        {"ts": (NOW + timedelta(days=1, minutes=1)).isoformat(),
         "query": "ml engineer", "source": "radar"},
    ]
    log.write_text("\n".join(json.dumps(r) for r in rows))
    outcome, why, payload = qa.judge_claim(
        _claim(), agent_cfg=_cfg(), jobs_by_id={}, log_path=log,
        ledger_path=tmp_path / "l.jsonl", engine=isolated_db,
    )
    assert outcome is False and payload["verdict_basis"] == "reformulation"


def test_weak_behavioural_evidence_can_confirm_but_is_labelled_weak(tmp_path, isolated_db):
    log = tmp_path / "log.jsonl"
    rows = [
        {"ts": (NOW + timedelta(days=i)).isoformat(), "query": "data engineer",
         "source": "radar"}
        for i in range(1, 4)
    ]
    log.write_text("\n".join(json.dumps(r) for r in rows))
    outcome, why, payload = qa.judge_claim(
        _claim(), agent_cfg=_cfg(), jobs_by_id={}, log_path=log,
        ledger_path=tmp_path / "l.jsonl", engine=isolated_db,
    )
    assert outcome is True and payload["verdict_basis"] == "weak"


def test_human_feedback_after_the_patch_is_strong_corroboration(tmp_path, isolated_db):
    from sqlmodel import Session

    with Session(isolated_db) as s:
        s.add(JobFeedback(job_title="Data Engineer", industry="Tech",
                          status="employed", confidence=0.7,
                          created_at=NOW + timedelta(days=3)))
        s.add(JobFeedback(job_title="Data Engineer", industry="Tech",
                          status="employed", confidence=0.7,
                          created_at=NOW - timedelta(days=3)))   # pre-patch, ignored
        s.commit()

    jobs = {"tech_data_eng": {"id": "tech_data_eng", "title": "Data Engineer"}}
    outcome, why, payload = qa.judge_claim(
        _claim(), agent_cfg=_cfg(), jobs_by_id=jobs,
        log_path=tmp_path / "empty.jsonl", ledger_path=tmp_path / "l.jsonl",
        engine=isolated_db,
    )
    assert outcome is True and payload["verdict_basis"] == "strong"
    fb = next(s for s in payload["signals"] if s["name"] == "feedback_corroboration")
    assert fb["count"] == 1                     # only the post-patch row counted


def test_resolve_due_claims_scores_and_persists(tmp_path, isolated_db):
    store = qa.ClaimStore(engine=isolated_db)
    ledger = tmp_path / "ledger.jsonl"
    pid = provenance.record_patch(subsystem="job_query_agent",
                                  patch_type="alias_patch", reason="t", path=ledger)
    provenance.mark_reverted(pid, reason="regressed", path=ledger)
    _claim(store, cid=pid, conf=0.9, res_date=date(2026, 1, 1))

    summary = qa.resolve_due_claims(
        {}, agent_cfg=_cfg(), jobs_by_id={}, log_path=tmp_path / "e.jsonl",
        ledger_path=ledger, engine=isolated_db, today=date(2026, 2, 1),
    )
    assert summary["judged"] == 1 and summary["false"] == 1
    stored = store.get(pid)
    assert stored.status == Status.resolved_false
    assert stored.brier == pytest.approx(0.81)   # staked 0.9, was wrong


# --- the return path into the gate -----------------------------------------
def test_gate_allows_while_there_is_no_track_record(isolated_db):
    ok, why, override = qa.gate_verdict(
        "alias_patch", cfg={}, agent_cfg=_cfg(), engine=isolated_db)
    assert ok and override is None and "no track record" in why


def test_gate_suspends_a_type_that_has_been_confidently_wrong(isolated_db):
    store = qa.ClaimStore(engine=isolated_db)
    for i in range(6):
        c = _claim(store, cid=f"bad{i}", conf=0.9)
        c.resolve(False, "wrong")
        store.update(c)

    ok, why, _ = qa.gate_verdict(
        "alias_patch", cfg={}, agent_cfg=_cfg(), engine=isolated_db)
    assert ok is False and "auto-apply suspended" in why


def test_gate_raises_the_similarity_bar_in_the_warning_band(isolated_db):
    store = qa.ClaimStore(engine=isolated_db)
    # conf 0.55 wrong → brier 0.3025, inside (warn 0.25, max 0.35]
    for i in range(6):
        c = _claim(store, cid=f"warn{i}", conf=0.55)
        c.resolve(False, "wrong")
        store.update(c)

    ok, why, override = qa.gate_verdict(
        "alias_patch", cfg={}, agent_cfg=_cfg(), engine=isolated_db)
    assert ok is True and override == pytest.approx(0.60)


def test_gate_blocks_when_claims_pile_up_unconfirmed(isolated_db):
    """Silence must be expensive: Brier alone cannot see unresolved claims."""
    store = qa.ClaimStore(engine=isolated_db)
    for i in range(4):
        _claim(store, cid=f"open{i}")
    cfg = _cfg()
    cfg["claims"]["gate"]["max_outstanding"] = 3

    ok, why, _ = qa.gate_verdict(
        "alias_patch", cfg={}, agent_cfg=cfg, engine=isolated_db)
    assert ok is False and "outstanding" in why


def test_gate_is_off_unless_explicitly_enabled():
    ok, why, _ = qa.gate_verdict("alias_patch", cfg={}, agent_cfg={})
    assert ok is True and "disabled" in why


def test_gate_fails_open_on_error():
    """A bug here may only make the agent more conservative, never wedge it."""
    class Boom:
        def __getattr__(self, name):
            raise RuntimeError("db exploded")

    ok, why, _ = qa.gate_verdict(
        "alias_patch", cfg={}, agent_cfg=_cfg(), engine=Boom())
    assert ok is True and "failing open" in why


def test_can_auto_apply_honours_the_track_record_veto(isolated_db):
    from services.job_query_agent.apply import can_auto_apply
    from services.job_query_agent.propose import CalibrationProposal

    store = qa.ClaimStore(engine=isolated_db)
    for i in range(6):
        c = _claim(store, cid=f"bad{i}", conf=0.95)
        c.resolve(False, "wrong")
        store.update(c)

    proposal = CalibrationProposal(
        proposal_id="p1", type="alias_patch", query="data engineer",
        target_id="tech_data_eng", payload={"aliases": ["data engineer"]},
        evidence={"sim": 0.3},
    )
    agent_cfg = {
        **_cfg(),
        "auto_apply": {"enabled": True, "types": ["alias_patch"], "min_sim_after": 0.55},
        "_cfg": {},
    }
    # Route the gate at the test database rather than the production one.
    orig = qa.store_for
    qa.store_for = lambda cfg, engine=None: qa.ClaimStore(engine=isolated_db)
    try:
        ok, reason = can_auto_apply(
            proposal, sim_before=0.3, sim_after=0.9,
            best_id_after="tech_data_eng", agent_cfg=agent_cfg,
            expected_id="tech_data_eng",
        )
    finally:
        qa.store_for = orig
    assert ok is False and reason.startswith("track record:")


# --- isolation from the public forecasting track record ---------------------
def test_patch_claims_do_not_contaminate_the_forecaster_scoreboard(isolated_db):
    """The public Brier must stay an AI-economy Brier."""
    reg = Registry(engine=isolated_db)
    reg.add_many([Prediction(
        statement="AI capex grows", rationale="r", confidence=0.7,
        horizon="2026-Q4", resolution_date=date(2026, 12, 31),
        resolution_criteria="c")])
    before = reg.scoreboard()

    store = qa.ClaimStore(engine=isolated_db)
    for i in range(5):
        c = _claim(store, cid=f"c{i}", conf=0.9)
        c.resolve(False, "wrong")
        store.update(c)

    after = reg.scoreboard()
    assert after == before
    assert qa.claim_scoreboard({}, engine=isolated_db)["resolved"] == 5


# --- end-to-end wiring through the calibration cycle ------------------------
def _sandbox_cfg(tmp_path):
    kb = [
        {"id": "tech_data_eng", "title": "Data Engineer", "industry": "Tech",
         "category": "growing", "description": "Builds data pipelines.",
         "required_skills": ["SQL"], "skill_vector": [0.5] * 8, "sensitivity": {},
         "base_demand_trend": 0.1, "displacement_risk": 0.2,
         "sources": ["BLS"], "transition_targets": []},
        {"id": "health_rn", "title": "Registered Nurse", "industry": "Healthcare",
         "category": "resilient", "description": "Patient care.",
         "required_skills": ["Triage"], "skill_vector": [0.5] * 8, "sensitivity": {},
         "base_demand_trend": 0.1, "displacement_risk": 0.1,
         "sources": ["BLS"], "transition_targets": []},
    ]
    (tmp_path / "kb.json").write_text(json.dumps(kb))
    (tmp_path / "seed.json").write_text(json.dumps(
        [{"query": "etl developer", "expected_id": "tech_data_eng"}]))
    (tmp_path / "config.yaml").write_text("model: x\n")
    return {
        "database_path": str(tmp_path / "test.db"),
        "_config_path": str(tmp_path / "config.yaml"),
        "job_radar": {"kb_path": str(tmp_path / "kb.json")},
        "job_query_agent": {
            "traces_path": str(tmp_path / "traces.jsonl"),
            "provenance_path": str(tmp_path / "ledger.jsonl"),
            "transition_eval_cache_path": str(tmp_path / "transition_cache.json"),
            "discover": {"include_core": False, "include_seed": True,
                         "seed_path": str(tmp_path / "seed.json"),
                         "include_feedback_titles": False,
                         "include_search_log": False, "include_variants": False},
            "evaluate": {"fail_on_weak_core": False},
            "review": {"pending_dir": str(tmp_path / "pending")},
            "coverage_enrichment": {"enabled": False},
            "auto_apply": {"enabled": True, "types": ["alias_patch", "title_alias"],
                           "min_sim_after": 0.55, "max_rounds": 2,
                           "kb_profile_new": {"enabled": False}},
            "claims": {"enabled": True, "horizon_days": 30,
                       "gate": {"enabled": True, "min_resolved": 5}},
        },
    }


def test_calibration_cycle_stakes_a_claim_on_every_auto_applied_patch(tmp_path):
    from services.job_query_agent.loop import run_calibration_cycle

    cfg = _sandbox_cfg(tmp_path)
    summary = run_calibration_cycle(cfg, write_traces=False, dry_run=False)

    assert summary["auto_applied"] >= 1
    assert len(summary["claims_staked"]) == summary["auto_applied"]

    store = qa.ClaimStore(cfg["database_path"])
    staked = store.load()
    assert {c.id for c in staked} == {s["claim_id"] for s in summary["claims_staked"]}
    for c in staked:
        assert c.source == "seed"          # discovery provenance carried through
        assert c.status == Status.open
        assert c.resolution_date == date.today() + timedelta(days=30)
        assert 0.05 <= c.confidence <= 0.95
        assert c.query and c.target_id and c.statement


def test_dry_run_cycle_stakes_nothing(tmp_path):
    from services.job_query_agent.loop import run_calibration_cycle

    cfg = _sandbox_cfg(tmp_path)
    summary = run_calibration_cycle(cfg, write_traces=False, dry_run=True)
    assert summary["claims_staked"] == []
    assert qa.ClaimStore(cfg["database_path"]).load() == []
