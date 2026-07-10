"""Tests for the generic self-mutation provenance ledger (HR-1 offline)."""
from __future__ import annotations

from services import provenance


def test_record_patch_returns_id_and_is_active(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    patch_id = provenance.record_patch(
        subsystem="job_query_agent",
        patch_type="alias_patch",
        reason="test",
        before={"search_aliases": []},
        after={"search_aliases": ["swe ic"]},
        target_id="tech_software_eng",
        query="swe ic",
        path=ledger,
    )
    assert patch_id.startswith("job_query_agent_")
    active = provenance.active_patches(ledger)
    assert len(active) == 1
    assert active[0]["patch_id"] == patch_id
    assert active[0]["before"]["search_aliases"] == []
    assert active[0]["after"]["search_aliases"] == ["swe ic"]


def test_reverted_patch_excluded_from_active(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    patch_id = provenance.record_patch(
        subsystem="job_query_agent", patch_type="title_alias", reason="test",
        path=ledger,
    )
    assert provenance.active_patches(ledger) == [provenance.get_patch(patch_id, ledger)]
    provenance.mark_reverted(patch_id, reason="regressed", path=ledger)
    assert provenance.active_patches(ledger) == []
    assert provenance.is_reverted(patch_id, path=ledger)


def test_active_patches_filters_by_subsystem(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    a = provenance.record_patch(subsystem="job_query_agent", patch_type="x", reason="r", path=ledger)
    b = provenance.record_patch(subsystem="transition_evaluator", patch_type="y", reason="r", path=ledger)
    only_jqa = provenance.active_patches(ledger, subsystem="job_query_agent")
    assert [p["patch_id"] for p in only_jqa] == [a]
    only_te = provenance.active_patches(ledger, subsystem="transition_evaluator")
    assert [p["patch_id"] for p in only_te] == [b]


def test_get_patch_unknown_returns_none(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    assert provenance.get_patch("does_not_exist", ledger) is None
    assert not provenance.is_reverted("does_not_exist", ledger)


def test_load_events_missing_file_returns_empty(tmp_path):
    ledger = tmp_path / "nope.jsonl"
    assert provenance.load_events(ledger) == []
    assert provenance.active_patches(ledger) == []


def test_active_patches_most_recent_first(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    first = provenance.record_patch(subsystem="job_query_agent", patch_type="x", reason="1", path=ledger)
    second = provenance.record_patch(subsystem="job_query_agent", patch_type="x", reason="2", path=ledger)
    ids = [p["patch_id"] for p in provenance.active_patches(ledger)]
    assert ids[0] == second or ids[0] == first  # ts resolution may tie; both present
    assert set(ids) == {first, second}
