"""Tests for app.services.ai.adaptive.AdaptiveScanner."""


from app.services.ai.adaptive import AdaptiveScanner, ScanOutcome


class TestRecordOutcome:
    def test_records_single_outcome(self):
        scanner = AdaptiveScanner()
        outcome = ScanOutcome(tool_name="nmap", target_type="web",
                              template_or_args="-sV", findings_count=3)
        scanner.record_outcome(outcome)
        assert len(scanner._outcomes) == 1

    def test_records_multiple_outcomes(self):
        scanner = AdaptiveScanner()
        for i in range(5):
            scanner.record_outcome(ScanOutcome(
                tool_name="nuclei", target_type="web",
                template_or_args="cves", findings_count=i,
            ))
        assert len(scanner._outcomes) == 5


class TestShouldSkip:
    def _populate(self, scanner: AdaptiveScanner, tool: str, target: str,
                  template: str, count: int, findings: int = 0):
        for _ in range(count):
            scanner.record_outcome(ScanOutcome(
                tool_name=tool, target_type=target,
                template_or_args=template, findings_count=findings,
            ))

    def test_skip_low_yield_tool(self):
        scanner = AdaptiveScanner(min_samples=3, skip_threshold=0.1)
        self._populate(scanner, "nikto", "ssh", "default", 5, findings=0)
        skip, reason = scanner.should_skip("nikto", "ssh")
        assert skip is True
        assert "0%" in reason

    def test_no_skip_high_yield_tool(self):
        scanner = AdaptiveScanner(min_samples=3, skip_threshold=0.1)
        self._populate(scanner, "nmap", "web", "-sV", 5, findings=2)
        skip, _ = scanner.should_skip("nmap", "web")
        assert skip is False

    def test_no_skip_insufficient_samples(self):
        scanner = AdaptiveScanner(min_samples=5)
        self._populate(scanner, "nmap", "web", "-sV", 2, findings=0)
        skip, _ = scanner.should_skip("nmap", "web")
        assert skip is False

    def test_skip_low_yield_template(self):
        scanner = AdaptiveScanner(min_samples=3, skip_threshold=0.1)
        self._populate(scanner, "nuclei", "web", "cve-2020-1234", 4, findings=0)
        skip, reason = scanner.should_skip("nuclei", "web", "cve-2020-1234")
        assert skip is True
        assert "cve-2020-1234" in reason

    def test_no_skip_different_target_type(self):
        scanner = AdaptiveScanner(min_samples=3, skip_threshold=0.1)
        self._populate(scanner, "nmap", "ssh", "-sV", 5, findings=0)
        skip, _ = scanner.should_skip("nmap", "web")
        assert skip is False


class TestGetRecommendedTools:
    def test_recommendations_sorted_by_score(self):
        scanner = AdaptiveScanner(min_samples=2)
        for _ in range(3):
            scanner.record_outcome(ScanOutcome(
                tool_name="nmap", target_type="web",
                template_or_args="-sV", findings_count=5,
                scan_duration_seconds=10,
            ))
            scanner.record_outcome(ScanOutcome(
                tool_name="nikto", target_type="web",
                template_or_args="default", findings_count=1,
                scan_duration_seconds=60,
            ))
        recs = scanner.get_recommended_tools("web")
        assert len(recs) == 2
        assert recs[0]["tool"] == "nmap"
        assert recs[0]["score"] > recs[1]["score"]

    def test_respects_limit(self):
        scanner = AdaptiveScanner(min_samples=2)
        for name in ("a", "b", "c", "d"):
            for _ in range(3):
                scanner.record_outcome(ScanOutcome(
                    tool_name=name, target_type="web",
                    template_or_args="x", findings_count=1,
                    scan_duration_seconds=1,
                ))
        recs = scanner.get_recommended_tools("web", limit=2)
        assert len(recs) == 2

    def test_empty_for_unknown_target(self):
        scanner = AdaptiveScanner()
        assert scanner.get_recommended_tools("unknown") == []

    def test_excludes_below_min_samples(self):
        scanner = AdaptiveScanner(min_samples=5)
        for _ in range(3):
            scanner.record_outcome(ScanOutcome(
                tool_name="nmap", target_type="web",
                template_or_args="-sV", findings_count=5,
            ))
        recs = scanner.get_recommended_tools("web")
        assert len(recs) == 0


class TestEffectivenessScoring:
    def test_score_reflects_yield_and_findings(self):
        scanner = AdaptiveScanner(min_samples=2)
        # High yield, many findings, fast
        for _ in range(3):
            scanner.record_outcome(ScanOutcome(
                tool_name="fast_tool", target_type="web",
                template_or_args="x", findings_count=10,
                scan_duration_seconds=5,
            ))
        # Low yield, few findings, slow
        for _ in range(3):
            scanner.record_outcome(ScanOutcome(
                tool_name="slow_tool", target_type="web",
                template_or_args="x", findings_count=1,
                scan_duration_seconds=100,
            ))
        recs = scanner.get_recommended_tools("web")
        fast = next(r for r in recs if r["tool"] == "fast_tool")
        slow = next(r for r in recs if r["tool"] == "slow_tool")
        assert fast["score"] > slow["score"]
        assert fast["yield_rate"] == 1.0
