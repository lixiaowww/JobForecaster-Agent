"""The orchestrator that wires the whole loop together.

One cycle =
  1. RESOLVE  any predictions whose date has passed -> judge -> score (feedback)
  2. INGEST   fresh AI + economic signals
  3. PRIOR    job-evolution prior (PCA/GMM/OOD) from configured scenario
  4. FORECAST new falsifiable predictions, calibrated by track record + prior
  5. DEDUP    against the registry
  5b. CROWD   process contributions via CrowdGate (sparse aggregate)
  6. PUBLISH  (or queue for human review)
"""
from __future__ import annotations

import time

try:
    import evolution as ev
    import forecast as fc
    import ingest as ing
    import publish as pub
    from registry import Registry
except ImportError:
    from . import evolution as ev
    from . import forecast as fc
    from . import ingest as ing
    from . import publish as pub
    from .registry import Registry


def _build_evolution_prior(cfg: dict) -> str:
    """Build evolution prior prompt context. Pure aside from seeded GMM bootstrap."""
    ev_cfg = cfg.get("evolution", {})
    scenario = ev_cfg.get("scenario") or ev.CURRENT_AI_SCENARIO
    n_boot = int(ev_cfg.get("n_bootstrap", 50))
    prior = ev.build_prior(current_scenario=scenario, n_bootstrap=n_boot)
    return prior.to_prompt_context()


def run_cycle(cfg: dict) -> dict:
    if cfg.get("mock_llm"):
        fc.set_mock_mode(True)
    reg = Registry(cfg.get("database_path"))
    model = cfg["model"]
    sources = ing.default_sources()

    # 1. resolve due predictions -----------------------------------------
    due = reg.due()
    print(f"[resolve] {len(due)} prediction(s) due")
    if due:
        fresh_for_judging = ing.gather_signals(sources, max_total=30)
        for p in due:
            outcome, why = fc.judge_prediction(
                p, fresh_for_judging, model=model)
            p.resolve(outcome, why)
            reg.update(p)
            if p.outcome is not None:
                try:
                    from services.crowd_service import resolve_contributions_for_prediction
                    n = resolve_contributions_for_prediction(p.id, p.outcome)
                    if n:
                        print(f"  - [crowd] scored {n} contribution(s)")
                except Exception as e:
                    print(f"  - [crowd] resolve error: {e}")
            print(f"  - {p.status.value}: {p.statement[:80]}")

    # 2. ingest -----------------------------------------------------------
    signals = ing.gather_signals(sources, max_total=cfg.get("max_signals", 40))
    print(f"[ingest] {len(signals)} signal(s)")

    # 3. evolution prior --------------------------------------------------
    evolution_prior = _build_evolution_prior(cfg)
    ood_line = evolution_prior.splitlines()[2] if evolution_prior else ""
    print(f"[evolution] {ood_line}")

    # 4. forecast (calibrated by track record + evolution prior) ----------
    track = reg.track_record_summary()
    preds = fc.generate_predictions(
        signals, track, model=model,
        max_predictions=cfg.get("max_predictions", 6),
        evolution_prior=evolution_prior)
    print(f"[forecast] {len(preds)} candidate prediction(s)")

    # 5. dedup + persist --------------------------------------------------
    new_preds = reg.add_many(preds)
    print(f"[registry] {len(new_preds)} new after dedup")

    # 5b. crowd gate on open predictions with contributions -----------------
    if cfg.get("crowd", {}).get("enabled", True):
        try:
            from services.crowd_service import process_open_prediction_crowds
            n_crowd = process_open_prediction_crowds(cfg, reg)
            print(f"[crowd] {n_crowd} prediction(s) with contributions processed")
        except Exception as e:
            print(f"[crowd] processing error: {e}")

    # 6. publish ----------------------------------------------------------
    sb = reg.scoreboard()
    md = pub.render_markdown(new_preds, sb)
    html = pub.render_html(md)
    publishers = build_publishers(cfg)
    pub.publish_or_queue(publishers, md, html, new_preds,
                         require_review=cfg.get("require_review", True))

    return {"new": len(new_preds), "resolved": len(due), "scoreboard": sb}


def build_publishers(cfg: dict) -> list:
    out = []
    pc = cfg.get("publish", {})
    if pc.get("file", {}).get("enabled"):
        out.append(pub.FilePublisher(pc["file"].get("out_dir", "site")))
    if pc.get("webhook", {}).get("url"):
        out.append(pub.WebhookPublisher(pc["webhook"]["url"]))
    if pc.get("git", {}).get("repo_dir"):
        out.append(pub.GitPublisher(pc["git"]["repo_dir"],
                                    pc["git"].get("branch", "main")))
    return out or [pub.FilePublisher("site")]


def run_loop(cfg: dict):
    interval = cfg.get("interval_seconds", 86400)
    print(f"[loop] running every {interval}s. Ctrl-C to stop.")
    while True:
        try:
            run_cycle(cfg)
        except Exception as e:
            print(f"[loop] cycle error: {e}")
        time.sleep(interval)
