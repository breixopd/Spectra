"""Tests for deterministic advisory lock IDs."""

from app.core.advisory_locks import stable_lock_id


def test_stable_lock_id_is_deterministic_and_bigint_safe():
    value = stable_lock_id("spectra_backup")

    assert value == 5364792680498971710
    assert value == stable_lock_id("spectra_backup")
    assert value != stable_lock_id("spectra_quota_reset")
    assert 0 <= value <= (1 << 63) - 1


def test_scheduler_lock_constants_use_stable_helper():
    from app import scheduler_service

    assert scheduler_service._BACKUP_LOCK_ID == stable_lock_id("spectra_backup")
    assert scheduler_service._SCHEDULER_LEADER_LOCK_ID == stable_lock_id("spectra_scheduler_leader")