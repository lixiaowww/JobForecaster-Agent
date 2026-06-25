#!/usr/bin/env python3
"""CLI entrypoint.

  python run.py once       # run a single cycle
  python run.py once --mock  # offline cycle (deterministic LLM stub)
  python run.py loop       # run forever on the configured interval
  python run.py resolve    # only resolve + score due predictions
  python run.py score      # print the calibration scoreboard
  python run.py approve    # publish whatever is queued in ./pending (review gate)
  python run.py once --config config.ci.yaml   # CI / auto-publish profile
  python run.py calibrate-jobs       # BLS → KB displacement risk overlay
  python run.py calibrate-jobs --dry-run
  python run.py export               # dump live registry rows → predictions_live.jsonl
  python run.py export --out path.jsonl
  python run.py verify-export        # assert DB live state == committed JSONL (HR-11)
  python run.py warmup               # import predictions_live.jsonl → DB (cache-miss recovery)
  python run.py warmup --src path.jsonl
  python run.py query-agent audit    # Phase 9: job search calibration audit (CI)
  python run.py query-agent once     # audit + queue proposals (non-auto)
  python run.py query-agent run      # discover → evaluate → auto-apply safe fixes
  python run.py query-agent run --dry-run
  python run.py query-agent apply    # merge approved pending/job_calibration/*.json
  python run.py query-agent ingest-logs path.jsonl  # merge HF/Radar search export
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

# Canonical project root — never insert /home/sean (symlink collision)
_here = Path(__file__).resolve().parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))
sys.path = [p for p in sys.path if p != '/home/sean']

import forecast as fc
import ingest as ing
import loop as orchestrator
import publish as pub
from registry import Registry


def load_config(path: str | None = None) -> dict:
    load_dotenv()
    cfg_path = Path(path or os.environ.get("FORECASTER_CONFIG", "config.yaml"))
    if not cfg_path.is_file():
        raise FileNotFoundError(f"Config not found: {cfg_path}")
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    cfg.setdefault("database_path", "data/forecaster.db")
    cfg.setdefault("model", "claude-sonnet-4-6")
    cfg.setdefault("require_review", True)
    cfg.setdefault("evolution", {"n_bootstrap": 50})
    cfg.setdefault("mock_llm", False)
    cfg["_config_path"] = str(cfg_path.resolve())
    return cfg


def _apply_mock_llm(cfg: dict) -> None:
    if cfg.get("mock_llm"):
        fc.set_mock_mode(True)
        print("[mock] FORECAST_MOCK_LLM enabled — deterministic LLM stub")


def cmd_score(cfg):
    print(json.dumps(Registry(cfg["database_path"]).scoreboard(), indent=2))


def cmd_resolve(cfg):
    reg = Registry(cfg["database_path"])
    due = reg.due()
    if not due:
        print("nothing due")
        return
    signals = ing.gather_signals(ing.default_sources(), max_total=30)
    for p in due:
        outcome, why = fc.judge_prediction(p, signals, model=cfg.get("model"))
        p.resolve(outcome, why)
        reg.update(p)
        print(f"{p.status.value}: {p.statement[:80]}")


def cmd_calibrate_jobs(cfg, *, dry_run: bool = False):
    from services.job_market import run_calibration

    result = run_calibration(cfg, dry_run=dry_run)
    print(json.dumps(result, indent=2))


def cmd_warmup(cfg, src_path: str = "data/predictions_live.jsonl"):
    """Import a committed JSONL back into the DB.

    Used in CI to recover the track record when the Actions cache has expired.
    Idempotent: predictions already in the DB are silently skipped (dedup on fingerprint).
    """
    from services.dashboard_seed import _load_live_rows

    path = Path(src_path)
    if not path.is_file():
        print(f"warmup: {src_path} not found — nothing to import")
        return
    rows = _load_live_rows(path)
    if not rows:
        print("warmup: file empty — nothing to import")
        return
    reg = Registry(cfg["database_path"])
    added = reg.add_many(rows)
    print(f"warmup: imported {len(added)} new prediction(s) from {src_path}")


def cmd_export(cfg, out_path: str = "data/predictions_live.jsonl", seed_path: str | None = None):
    """Dump live-only predictions to JSONL (HR-11: seed stays in predictions_seed.json)."""
    from services.track_record import partition_by_origin, seed_prediction_ids

    reg = Registry(cfg["database_path"])
    seed_ids = seed_prediction_ids(seed_path)
    _, live = partition_by_origin(reg.load(), seed_ids)
    live.sort(key=lambda p: (p.created_at, p.id))
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for p in live:
            f.write(p.model_dump_json() + "\n")
    print(f"exported {len(live)} live prediction(s) to {out_path}")


def cmd_verify_export(
    cfg,
    out_path: str = "data/predictions_live.jsonl",
    seed_path: str | None = None,
):
    """Fail if committed JSONL does not mirror live predictions in the DB (HR-11)."""
    from services.dashboard_seed import _load_live_rows
    from services.track_record import partition_by_origin, seed_prediction_ids, verify_live_export_sync

    reg = Registry(cfg["database_path"])
    seed_ids = seed_prediction_ids(seed_path)
    _, db_live = partition_by_origin(reg.load(), seed_ids)
    jsonl_live = _load_live_rows(Path(out_path))

    errors = verify_live_export_sync(db_live, jsonl_live)
    if errors:
        print("verify-export FAILED:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        sys.exit(1)
    print(f"verify-export OK ({len(db_live)} live prediction(s) in sync)")


def cmd_query_agent(
    cfg,
    *,
    subcmd: str = "audit",
    dry_run: bool = False,
    extra_args: list[str] | None = None,
):
    from services.job_query_agent.audit import run_audit

    extra_args = extra_args or []
    agent_cfg = cfg.setdefault("job_query_agent", {})
    if subcmd == "audit":
        summary = run_audit(cfg, write_traces=True, queue_proposals=False)
        print(json.dumps(summary, indent=2))
    elif subcmd == "once":
        fail_weak = agent_cfg.get("evaluate", {}).get("fail_on_weak_core", True)
        agent_cfg.setdefault("evaluate", {})["fail_on_weak_core"] = fail_weak
        try:
            summary = run_audit(cfg, write_traces=True, queue_proposals=True)
        except AssertionError as exc:
            print(str(exc), file=sys.stderr)
            sys.exit(1)
        print(json.dumps(summary, indent=2))
    elif subcmd == "run":
        from services.job_query_agent.loop import run_calibration_cycle

        summary = run_calibration_cycle(cfg, write_traces=True, dry_run=dry_run)
        print(json.dumps(summary, indent=2))
        if summary["final"]["p0_regressions"] > 0:
            sys.exit(1)
    elif subcmd == "apply":
        from services.job_query_agent.apply import run_apply_pending

        ids = [a for a in extra_args if not a.startswith("-")]
        summary = run_apply_pending(cfg, dry_run=dry_run, proposal_ids=ids or None)
        print(json.dumps(summary, indent=2))
    elif subcmd == "coverage":
        from services.bls_coverage import coverage_gaps, run_coverage_enrichment
        import job_radar as _jr
        _jr_cfg = cfg.get("job_radar", {})
        _search_cfg = _jr.resolve_search_config(_jr_cfg)
        _jobs = _jr.load_knowledge_base(_jr_cfg.get("kb_path", "data/jobs_kb.json"))
        if extra_args and extra_args[0] == "gaps":
            gaps = coverage_gaps(_jobs, _search_cfg)
            print(json.dumps([
                {"rank": i+1, "title": g["title"], "emp_k": g["emp_k"],
                 "sim": g["_current_sim"], "industry": g["industry"]}
                for i, g in enumerate(gaps)
            ], indent=2))
        else:
            budget = int(extra_args[0]) if extra_args else 5
            summary = run_coverage_enrichment(cfg, daily_budget=budget, dry_run=dry_run)
            print(json.dumps(summary, indent=2))
    elif subcmd == "transition-eval":
        import job_radar as _jr
        from services.transition_evaluator.evaluate import run_evaluation_pass

        _kb_path = cfg.get("job_radar", {}).get("kb_path", "data/jobs_kb.json")
        jobs = _jr.load_knowledge_base(_kb_path)
        max_pairs = int(extra_args[0]) if extra_args else 40
        summary = run_evaluation_pass(jobs, max_pairs=max_pairs, kb_path=_kb_path)
        print(json.dumps(summary, indent=2))
    elif subcmd == "ingest-logs":
        from services.job_query_agent.search_log import merge_search_logs

        if not extra_args:
            print("usage: query-agent ingest-logs <path.jsonl>", file=sys.stderr)
            sys.exit(2)
        log_path = agent_cfg.get("discover", {}).get(
            "search_log_path", "data/radar_search_log.jsonl",
        )
        merged = merge_search_logs(extra_args[0], log_path)
        print(json.dumps({"merged": merged, "dest": log_path}, indent=2))
    else:
        print(f"unknown query-agent subcommand: {subcmd}", file=sys.stderr)
        sys.exit(2)


def cmd_approve(cfg):
    pending = Path("pending")
    mds = sorted(pending.glob("*.md")) if pending.exists() else []
    if not mds:
        print("nothing queued")
        return
    reg = Registry(cfg["database_path"])
    publishers = orchestrator.build_publishers(cfg)
    for md_file in mds:
        md = md_file.read_text()
        html = pub.render_html(md)
        # reconstruct the prediction list from the sidecar json
        sidecar = md_file.with_suffix(".json")
        preds = []
        if sidecar.exists():
            from schemas import Prediction
            preds = [Prediction(**d) for d in json.loads(sidecar.read_text())]
        pub.publish_or_queue(publishers, md, html, preds, require_review=False)
        md_file.unlink()
        sidecar.unlink(missing_ok=True)
    print("approved and published")


def _extract_opt(args: list[str], name: str) -> str | None:
    if name in args:
        idx = args.index(name)
        if idx + 1 >= len(args):
            print(f"error: {name} requires a value", file=sys.stderr)
            sys.exit(2)
        val = args[idx + 1]
        del args[idx : idx + 2]
        return val
    return None


def _parse_args(argv: list[str]) -> tuple[list[str], str | None]:
    args = list(argv)
    config_path = os.environ.get("FORECASTER_CONFIG")
    val = _extract_opt(args, "--config")
    if val is not None:
        config_path = val
    return args, config_path


def main():
    args, config_path = _parse_args(sys.argv[1:])
    out_path = _extract_opt(args, "--out")
    mock_flag = "--mock" in args
    dry_run_flag = "--dry-run" in args
    if mock_flag:
        args.remove("--mock")
    if dry_run_flag:
        args.remove("--dry-run")
    cmd = args[0] if args else "once"
    cfg = load_config(config_path)
    if mock_flag:
        cfg["mock_llm"] = True
    _apply_mock_llm(cfg)
    if cmd == "once":
        print(json.dumps(orchestrator.run_cycle(cfg)["scoreboard"], indent=2))
    elif cmd == "loop":
        orchestrator.run_loop(cfg)
    elif cmd == "resolve":
        cmd_resolve(cfg)
    elif cmd == "score":
        cmd_score(cfg)
    elif cmd == "approve":
        cmd_approve(cfg)
    elif cmd == "calibrate-jobs":
        cmd_calibrate_jobs(cfg, dry_run=dry_run_flag)
    elif cmd == "export":
        cmd_export(cfg, out_path or "data/predictions_live.jsonl")
    elif cmd == "verify-export":
        cmd_verify_export(cfg, out_path or "data/predictions_live.jsonl")
    elif cmd == "warmup":
        src = _extract_opt(args, "--src") or out_path or "data/predictions_live.jsonl"
        cmd_warmup(cfg, src)
    elif cmd == "query-agent":
        sub = args[1] if len(args) > 1 else "audit"
        extra = args[2:] if len(args) > 2 else []
        cmd_query_agent(cfg, subcmd=sub, dry_run=dry_run_flag, extra_args=extra)
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
