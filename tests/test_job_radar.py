"""Tests for job_radar transition helpers."""
from __future__ import annotations

import job_radar


def test_get_transition_details_accepts_string_targets():
    jobs = [
        {
            "id": "role_a",
            "title": "Role A",
            "transition_targets": ["role_b", "missing"],
        },
        {
            "id": "role_b",
            "title": "Role B",
            "description": "Target role",
            "industry": "Tech",
            "category": "emerging",
            "required_skills": ["Python"],
        },
    ]
    details = job_radar.get_transition_details("role_a", jobs)
    assert len(details) == 1
    assert details[0]["id"] == "role_b"
    assert details[0]["title"] == "Role B"
    assert details[0]["skill_bridge"] is None


def test_normalize_transition_targets_skips_invalid_entries():
    out = job_radar._normalize_transition_targets([
        "fin_risk_manager",
        {"target_id": "tech_ai_infra_eng", "skill_bridge": "bridge"},
        42,
        None,
    ])
    assert len(out) == 2
    assert out[0]["target_id"] == "fin_risk_manager"
    assert out[1]["target_id"] == "tech_ai_infra_eng"
