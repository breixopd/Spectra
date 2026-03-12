"""Agent confidence calibration.

Tracks predicted confidence scores against actual finding accuracy
to provide calibration feedback for agents.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

logger = logging.getLogger("spectra.ai.calibration")


@dataclass
class CalibrationRecord:
    agent_name: str
    predicted_confidence: float
    actual_accuracy: float  # 1.0 = confirmed, 0.0 = false positive
    task_type: str
    timestamp: datetime


class ConfidenceCalibrator:
    """Tracks and calibrates agent confidence scores.

    Maintains a rolling window of predictions vs outcomes and provides
    a calibration factor that agents can use to adjust their confidence.
    """

    def __init__(self, window_size: int = 200):
        self._records: list[CalibrationRecord] = []
        self._window_size = window_size

    def record_prediction(self, agent_name: str, predicted_confidence: float,
                          actual_accuracy: float, task_type: str = "general"):
        """Record a prediction/outcome pair for calibration."""
        self._records.append(CalibrationRecord(
            agent_name=agent_name,
            predicted_confidence=predicted_confidence,
            actual_accuracy=actual_accuracy,
            task_type=task_type,
            timestamp=datetime.now(UTC),
        ))
        if len(self._records) > self._window_size:
            self._records = self._records[-self._window_size:]

    def get_calibration_factor(self, agent_name: str, task_type: str | None = None) -> float:
        """Get calibration factor for an agent.

        Returns a multiplier: >1 means agent underestimates, <1 means overestimates.
        1.0 means well-calibrated or insufficient data.
        """
        records = [r for r in self._records if r.agent_name == agent_name]
        if task_type:
            records = [r for r in records if r.task_type == task_type]

        if len(records) < 10:
            return 1.0  # Not enough data

        avg_predicted = sum(r.predicted_confidence for r in records) / len(records)
        avg_actual = sum(r.actual_accuracy for r in records) / len(records)

        if avg_predicted == 0:
            return 1.0

        factor = avg_actual / avg_predicted
        # Clamp to reasonable range
        return max(0.3, min(2.0, factor))

    def calibrate_confidence(self, agent_name: str, raw_confidence: float,
                              task_type: str | None = None) -> float:
        """Apply calibration to a raw confidence score."""
        factor = self.get_calibration_factor(agent_name, task_type)
        calibrated = raw_confidence * factor
        return max(0.0, min(1.0, calibrated))

    def get_agent_stats(self, agent_name: str) -> dict:
        """Get calibration stats for an agent."""
        records = [r for r in self._records if r.agent_name == agent_name]
        if not records:
            return {"total_predictions": 0, "calibration_factor": 1.0}

        return {
            "total_predictions": len(records),
            "avg_predicted": round(sum(r.predicted_confidence for r in records) / len(records), 3),
            "avg_actual": round(sum(r.actual_accuracy for r in records) / len(records), 3),
            "calibration_factor": round(self.get_calibration_factor(agent_name), 3),
        }

    async def persist(self):
        """Persist calibration data to DB for cross-restart retention."""
        import json

        from sqlalchemy import text

        from app.core.database import async_session_maker

        data = [
            {
                "agent": r.agent_name,
                "predicted": r.predicted_confidence,
                "actual": r.actual_accuracy,
                "task": r.task_type,
                "ts": r.timestamp.isoformat(),
            }
            for r in self._records
        ]
        async with async_session_maker() as session:
            await session.execute(
                text("""
                    INSERT INTO system_cache (key, value, expires_at)
                    VALUES ('calibration_data', :value, now() + interval '90 days')
                    ON CONFLICT (key) DO UPDATE SET value = :value, expires_at = now() + interval '90 days'
                """),
                {"value": json.dumps(data)}
            )
            await session.commit()

    async def restore(self):
        """Restore calibration data from DB."""
        import json

        from sqlalchemy import text

        from app.core.database import async_session_maker

        try:
            async with async_session_maker() as session:
                result = await session.execute(
                    text("SELECT value FROM system_cache WHERE key = 'calibration_data'")
                )
                row = result.fetchone()
                if row:
                    data = json.loads(row[0]) if isinstance(row[0], str) else row[0]
                    for d in data:
                        self._records.append(CalibrationRecord(
                            agent_name=d["agent"],
                            predicted_confidence=d["predicted"],
                            actual_accuracy=d["actual"],
                            task_type=d["task"],
                            timestamp=datetime.fromisoformat(d["ts"]),
                        ))
        except Exception:
            pass


# Singleton
_calibrator: ConfidenceCalibrator | None = None

def get_calibrator() -> ConfidenceCalibrator:
    global _calibrator
    if _calibrator is None:
        _calibrator = ConfidenceCalibrator()
    return _calibrator
