from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
API_SERVICE_ROOT = REPO_ROOT / "services" / "api"


def test_setup_template_exposes_current_gateway_setup():
    content = (API_SERVICE_ROOT / "templates/setup.html").read_text(encoding="utf-8")

    assert "System Setup" in content
    assert "AI Gateway" in content
    assert "TensorZero Gateway URL" in content
    assert "Customize AI model configuration" in content
    assert "Quick Setup" not in content
    assert "HAS_USERS" in content
    assert "/api/settings" in content
    assert "Advanced Routing" not in content
    assert "Fallback Chain" not in content


def test_settings_template_exposes_current_gateway_summary():
    content = (API_SERVICE_ROOT / "templates/settings.html").read_text(encoding="utf-8")

    assert "System Settings" in content
    assert "AI Gateway" in content
    assert "TensorZero Gateway URL" in content
    assert "resolved-ai-summary" in content
    assert "Quick Setup" not in content
    assert "Advanced Routing" not in content
    assert "Default Fallback Chain" not in content


def test_settings_template_exposes_sandbox_pool_controls():
    content = (API_SERVICE_ROOT / "templates/settings.html").read_text(encoding="utf-8")

    assert "Sandbox Pool" in content
    assert "sandbox_max_containers" in content
    assert "sandbox_memory_limit" in content
    assert "sandbox_cpu_shares" in content
    assert "sandbox_max_lifetime" in content
    assert "sandbox-status" in content
    assert 'name="sandbox_network_isolation"' in content
    assert 'name="sandbox_oom_escalation_enabled"' in content
    assert 'name="sandbox_resource_tiers"' in content
    assert "sandbox_worker" in content
    assert 'name="sandbox_idle_timeout"' in content
    assert 'name="sandbox_heartbeat_interval"' in content
    assert 'name="sandbox_image_scan_block_critical"' in content
    assert 'name="sandbox_per_user_limit"' in content
    assert 'name="sandbox_default_priority"' in content


def test_settings_js_handles_sandbox_fields():
    content = (API_SERVICE_ROOT / "static/js/settings.js").read_text(encoding="utf-8")

    assert "sandbox_max_containers" in content
    assert "sandbox_memory_limit" in content
    assert "sandbox_cpu_shares" in content
    assert "sandbox_max_lifetime" in content
    assert "sandbox-status-dot" in content
