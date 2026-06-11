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
