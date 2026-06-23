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
    import yaml
    from run import load_config

    fc.set_mock_mode(True)
    cfg_dict = yaml.safe_load(ci.read_text(encoding="utf-8"))
    cfg_dict.setdefault("model", "llama-3.3-70b-versatile")
    cfg_dict.setdefault("evolution", {"n_bootstrap": 10})
    cfg_dict.setdefault("require_review", False)
    orchestrator.run_cycle(cfg_dict)

    assert (site / "index.html").is_file()
    html = (site / "index.html").read_text(encoding="utf-8")
    assert "Forecast" in html or "forecast" in html.lower()
