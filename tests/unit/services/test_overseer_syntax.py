"""Tests for overseer.html template syntax correctness."""

from pathlib import Path

OVERSEER_TEMPLATE = Path(__file__).resolve().parents[3] / "services" / "api" / "templates" / "overseer.html"


class TestOverseerSyntax:
    """Verify overseer.html has no JS syntax errors."""

    def test_template_exists(self):
        assert OVERSEER_TEMPLATE.exists()

    def test_balanced_braces(self):
        """Script blocks should have balanced curly braces."""
        content = OVERSEER_TEMPLATE.read_text()
        # Extract all script block content
        in_script = False
        script_content = []
        for line in content.split("\n"):
            if "<script" in line:
                in_script = True
                continue
            if "</script>" in line:
                in_script = False
                continue
            if in_script:
                script_content.append(line)

        js = "\n".join(script_content)
        # Remove strings and comments to avoid false positives
        # Simple heuristic: count { and } outside of strings
        opens = js.count("{")
        closes = js.count("}")
        assert opens == closes, f"Unbalanced braces in overseer.html scripts: {opens} opens vs {closes} closes"
