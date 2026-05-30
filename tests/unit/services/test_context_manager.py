"""Tests for ContextManager."""

from spectra_ai_core.context import ContextManager, ContextSection, Priority


class TestContextManager:
    def test_build_returns_all_sections_within_budget(self):
        ctx = ContextManager(max_context_tokens=5000)
        sections = [
            ContextSection("a", "Hello world", Priority.CRITICAL),
            ContextSection("b", "Some tools info", Priority.HIGH),
        ]
        result = ctx.build(sections)
        assert "Hello world" in result
        assert "Some tools info" in result

    def test_build_sorts_by_priority(self):
        ctx = ContextManager(max_context_tokens=5000)
        sections = [
            ContextSection("low", "LOW_CONTENT", Priority.LOW),
            ContextSection("critical", "CRITICAL_CONTENT", Priority.CRITICAL),
        ]
        result = ctx.build(sections)
        assert result.index("CRITICAL_CONTENT") < result.index("LOW_CONTENT")

    def test_build_drops_low_priority_when_over_budget(self):
        ctx = ContextManager(max_context_tokens=10)  # ~40 chars budget
        sections = [
            ContextSection("critical", "A" * 36, Priority.CRITICAL),
            ContextSection("low", "B" * 40, Priority.LOW),
        ]
        result = ctx.build(sections)
        assert "A" * 36 in result
        assert "B" * 40 not in result

    def test_build_truncates_high_priority_when_over_budget(self):
        ctx = ContextManager(max_context_tokens=100)  # ~400 chars budget
        sections = [
            ContextSection("first", "X" * 200, Priority.CRITICAL),
            ContextSection("second", "Y" * 300, Priority.HIGH),
        ]
        result = ctx.build(sections)
        assert "X" * 200 in result
        assert "[... truncated]" in result  # second section truncated
        assert "Y" * 300 not in result  # not fully included

    def test_build_skips_empty_sections(self):
        ctx = ContextManager(max_context_tokens=5000)
        sections = [
            ContextSection("a", "content", Priority.CRITICAL),
            ContextSection("b", "", Priority.HIGH),
            ContextSection("c", "   ", Priority.LOW),
        ]
        result = ctx.build(sections)
        assert result == "content"

    def test_per_section_cap(self):
        ctx = ContextManager(max_context_tokens=5000)
        sections = [
            ContextSection("big", "A" * 2000, Priority.HIGH, max_tokens=50),
        ]
        result = ctx.build(sections)
        # max_tokens=50 => 200 chars max
        assert len(result) < 250  # 200 chars + truncation marker

    def test_critical_never_dropped(self):
        # Budget is smaller than section but enough for truncation (>100 chars)
        ctx = ContextManager(max_context_tokens=50)  # ~200 chars
        sections = [
            ContextSection("sys", "A" * 800, Priority.CRITICAL),
        ]
        result = ctx.build(sections)
        assert len(result) > 0
        assert "[... truncated]" in result

    def test_estimate_tokens(self):
        assert ContextManager.estimate_tokens("A" * 400) == 114

    def test_section_token_estimate(self):
        s = ContextSection("x", "A" * 100, Priority.CRITICAL)
        assert s.token_estimate == 28
