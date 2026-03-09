from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_setup_template_exposes_quick_setup_and_advanced_routing():
    content = (REPO_ROOT / "app/templates/setup.html").read_text(encoding="utf-8")

    assert "Quick Setup" in content
    assert "Advanced Routing" in content
    assert "Fallback Chain" in content
    assert "default_provider" in content
    assert "Cloud / API Gateway" in content
    assert "OpenAI-Compatible API" not in content
    assert "LiteLLM Route" not in content


def test_settings_template_exposes_quick_setup_and_fallback_editor():
    content = (REPO_ROOT / "app/templates/settings.html").read_text(encoding="utf-8")

    assert "Quick Setup" in content
    assert "Advanced Routing" in content
    assert "Default Fallback Chain" in content
    assert "resolved-ai-summary" in content
    assert "Cloud / API Gateway" in content
    assert "OpenAI-Compatible API" not in content
    assert "LiteLLM Route" not in content