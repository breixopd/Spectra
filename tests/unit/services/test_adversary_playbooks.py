"""Tests for adversary playbooks."""

from spectra_ai_core.adversary_playbooks import (
    ADVERSARY_PLAYBOOKS,
    get_adversary_playbook,
    list_adversary_playbooks,
)


def test_list_playbooks_returns_all():
    result = list_adversary_playbooks()
    assert len(result) == len(ADVERSARY_PLAYBOOKS)
    assert all("id" in pb for pb in result)
    assert all("name" in pb for pb in result)
    assert all("step_count" in pb for pb in result)


def test_get_playbook_by_id_found():
    pb = get_adversary_playbook("apt28-web")
    assert pb is not None
    assert pb.id == "apt28-web"
    assert pb.threat_actor == "APT28 (Fancy Bear)"
    assert len(pb.steps) > 0
    assert pb.steps[0].name == "web_recon"


def test_get_playbook_by_id_not_found():
    pb = get_adversary_playbook("nonexistent")
    assert pb is None


def test_playbook_steps_parsed():
    pb = get_adversary_playbook("generic-network")
    assert pb is not None
    step_names = [s.name for s in pb.steps]
    assert "discovery" in step_names
    assert "vuln_scan" in step_names
