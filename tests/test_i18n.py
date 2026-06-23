"""i18n helper tests (no Streamlit UI)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ui import i18n


def test_translate_both_languages(monkeypatch):
    monkeypatch.setattr(
        i18n,
        "lang",
        lambda: "en",
    )
    assert i18n.t("tab_radar") == "Job Forecast Radar"
    assert i18n._translate("zh", "tab_radar") == "岗位预测雷达"


def test_job_fields_chinese():
    job = {"title": "Engineer", "title_zh": "工程师", "description": "EN", "description_zh": "中文描述"}
    assert i18n._job_title_for("zh", job) == "工程师"
    assert i18n._job_description_for("zh", job) == "中文描述"
    assert i18n._job_title_for("en", job) == "Engineer"


def test_all_keys_have_both_languages():
    for key, entry in i18n._STRINGS.items():
        assert entry.get("en"), key
        assert entry.get("zh"), key
