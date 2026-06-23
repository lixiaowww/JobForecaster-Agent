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


def _parse_args(argv: list[str]) -> tuple[list[str], str | None]:
    args = list(argv)
    config_path = os.environ.get("FORECASTER_CONFIG")
    if "--config" in args:
        idx = args.index("--config")
        if idx + 1 >= len(args):
            print("error: --config requires a path", file=sys.stderr)
            sys.exit(2)
        config_path = args[idx + 1]
        del args[idx : idx + 2]
    return args, config_path


def main():
    args, config_path = _parse_args(sys.argv[1:])
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
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
