"""CI profile smoke test — mock cycle writes site/index.html."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from paths import PROJECT_ROOT


def test_ci_config_mock_cycle_writes_site(tmp_path, monkeypatch):
    monkeypatch.chdir(PROJECT_ROOT)
    db = tmp_path / "forecaster.db"
    site = tmp_path / "site"
    site.mkdir()
    cfg = PROJECT_ROOT / "config.ci.yaml"
    text = cfg.read_text(encoding="utf-8").replace(
        "database_path: data/forecaster.db",
        f"database_path: {db}",
    ).replace(
        "out_dir: site",
        f"out_dir: {site}",
    )
    ci = tmp_path / "ci.yaml"
    ci.write_text(text, encoding="utf-8")

    import loop as orchestrator
    import forecast as fc
    import ingest as ing
    import yaml
    from schemas import Signal

    # Keep the "offline" harness genuinely offline: replace the network signal
    # sources (arXiv/RSS/Tavily/FRED) with deterministic canned signals.
    canned = [
        Signal(source="arxiv", title="AI agents automate analytical workflows",
               summary="Study on LLM task automation across knowledge work.",
               published="2026-06-22", kind="paper"),
        Signal(source="FRED", title="Unemployment rate steady",
               summary="latest 4.1 on 2026-06-01 (prev 4.1)",
               published="2026-06-01", kind="indicator"),
    ]
    monkeypatch.setattr(ing, "gather_signals", lambda *a, **k: list(canned))

    fc.set_mock_mode(True)
    cfg_dict = yaml.safe_load(ci.read_text(encoding="utf-8"))
    cfg_dict.setdefault("model", "llama-3.3-70b-versatile")
    cfg_dict.setdefault("evolution", {"n_bootstrap": 10})
    cfg_dict.setdefault("require_review", False)
    orchestrator.run_cycle(cfg_dict)

    assert (site / "index.html").is_file()
    html = (site / "index.html").read_text(encoding="utf-8")
    assert "Forecast" in html or "forecast" in html.lower()
