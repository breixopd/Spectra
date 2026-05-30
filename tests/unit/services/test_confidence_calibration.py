"""Tests for app.services.ai.calibration.ConfidenceCalibrator."""

from spectra_ai_core.calibration import ConfidenceCalibrator


class TestRecordPrediction:
    def test_records_single(self):
        cal = ConfidenceCalibrator()
        cal.record_prediction("agent-a", 0.8, 0.7)
        assert len(cal._records) == 1

    def test_rolling_window_truncation(self):
        cal = ConfidenceCalibrator(window_size=10)
        for _i in range(15):
            cal.record_prediction("agent-a", 0.5, 0.5)
        assert len(cal._records) == 10


class TestCalibrationFactor:
    def _fill(
        self,
        cal: ConfidenceCalibrator,
        agent: str,
        predicted: float,
        actual: float,
        n: int = 15,
        task_type: str = "general",
    ):
        for _ in range(n):
            cal.record_prediction(agent, predicted, actual, task_type)

    def test_insufficient_data_returns_one(self):
        cal = ConfidenceCalibrator()
        for _ in range(5):
            cal.record_prediction("agent-a", 0.9, 0.5)
        assert cal.get_calibration_factor("agent-a") == 1.0

    def test_over_confident_agent(self):
        cal = ConfidenceCalibrator()
        self._fill(cal, "agent-a", predicted=0.9, actual=0.45)
        factor = cal.get_calibration_factor("agent-a")
        assert factor < 1.0  # Should scale down
        assert abs(factor - 0.5) < 0.05

    def test_under_confident_agent(self):
        cal = ConfidenceCalibrator()
        self._fill(cal, "agent-a", predicted=0.4, actual=0.8)
        factor = cal.get_calibration_factor("agent-a")
        assert factor > 1.0  # Should scale up
        assert abs(factor - 2.0) < 0.05

    def test_well_calibrated_agent(self):
        cal = ConfidenceCalibrator()
        self._fill(cal, "agent-a", predicted=0.7, actual=0.7)
        factor = cal.get_calibration_factor("agent-a")
        assert abs(factor - 1.0) < 0.05

    def test_per_agent_filtering(self):
        cal = ConfidenceCalibrator()
        self._fill(cal, "agent-a", predicted=0.9, actual=0.45)
        self._fill(cal, "agent-b", predicted=0.5, actual=0.5)
        assert cal.get_calibration_factor("agent-a") < 1.0
        assert abs(cal.get_calibration_factor("agent-b") - 1.0) < 0.05

    def test_per_task_type_filtering(self):
        cal = ConfidenceCalibrator()
        self._fill(cal, "agent-a", 0.9, 0.45, task_type="recon")
        self._fill(cal, "agent-a", 0.5, 0.5, task_type="exploit")
        assert cal.get_calibration_factor("agent-a", "recon") < 1.0
        assert abs(cal.get_calibration_factor("agent-a", "exploit") - 1.0) < 0.05

    def test_factor_clamped_upper(self):
        cal = ConfidenceCalibrator()
        # Extreme underestimate: predicted ~0.05, actual ~1.0 → raw factor=20
        self._fill(cal, "agent-a", predicted=0.05, actual=1.0)
        factor = cal.get_calibration_factor("agent-a")
        assert factor <= 2.0

    def test_factor_clamped_lower(self):
        cal = ConfidenceCalibrator()
        self._fill(cal, "agent-a", predicted=0.9, actual=0.1)
        factor = cal.get_calibration_factor("agent-a")
        assert factor >= 0.3


class TestCalibrateConfidence:
    def test_adjusts_confidence(self):
        cal = ConfidenceCalibrator()
        for _ in range(15):
            cal.record_prediction("agent-a", 0.9, 0.45)
        calibrated = cal.calibrate_confidence("agent-a", 0.8)
        assert calibrated < 0.8

    def test_clamp_to_range(self):
        cal = ConfidenceCalibrator()
        for _ in range(15):
            cal.record_prediction("agent-a", 0.4, 0.8)
        calibrated = cal.calibrate_confidence("agent-a", 0.9)
        assert 0.0 <= calibrated <= 1.0


class TestGetAgentStats:
    def test_empty_stats(self):
        cal = ConfidenceCalibrator()
        stats = cal.get_agent_stats("unknown")
        assert stats["total_predictions"] == 0
        assert stats["calibration_factor"] == 1.0

    def test_populated_stats(self):
        cal = ConfidenceCalibrator()
        for _ in range(15):
            cal.record_prediction("agent-a", 0.8, 0.6)
        stats = cal.get_agent_stats("agent-a")
        assert stats["total_predictions"] == 15
        assert stats["avg_predicted"] == 0.8
        assert stats["avg_actual"] == 0.6
