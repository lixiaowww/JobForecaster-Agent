"""i18n helper tests (no Streamlit UI)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ui import i18n


def test_translate_both_languages(monkeypatch):
    monkeypatch.setattr(i18n, "lang", lambda: "en")
    assert i18n.t("tab_radar") == "Job Impact Radar"
    assert i18n._translate("zh", "tab_radar") == "岗位影响雷达"


def test_job_fields_chinese():
    job = {"title": "Engineer", "title_zh": "工程师", "description": "EN", "description_zh": "中文描述"}
    assert i18n._job_title_for("zh", job) == "工程师"
    assert i18n._job_description_for("zh", job) == "中文描述"
    assert i18n._job_title_for("en", job) == "Engineer"


def test_industry_and_status_chinese():
    assert i18n._translate("zh", "industry_finance") == "金融"
    assert i18n._translate("zh", "emp_status_employed") == "在职"
    assert i18n._translate("zh", "exp_level_junior") == "初级（在岗 0–3 年）"
    assert i18n._translate("zh", "pred_labor") == "劳动力"
    assert i18n._job_category_label_for("zh", "at_risk") == "高风险"


def test_industry_label_english():
    assert i18n._industry_label_for("en", "Tech") == "Tech"
    assert i18n._industry_label_for("zh", "Tech") == "科技"


def test_all_keys_have_both_languages():
    for key, entry in i18n._STRINGS.items():
        assert entry.get("en"), key
        assert entry.get("zh"), key
