"""SQLAlchemy database models."""

from __future__ import annotations

from importlib import import_module

_MODEL_EXPORTS = {
    "SystemConfig": ("app.models.config", "SystemConfig"),
    "ServerNode": ("app.models.server_node", "ServerNode"),
    "AuditEventType": ("app.models.audit_log", "AuditEventType"),
    "AuditLog": ("app.models.audit_log", "AuditLog"),
    "Base": ("app.models.base", "Base"),
    "Exploit": ("app.models.exploit", "Exploit"),
    "Finding": ("app.models.finding", "Finding"),
    "FindingStatus": ("app.models.finding", "FindingStatus"),
    "Severity": ("app.models.finding", "Severity"),
    "Mission": ("app.models.mission", "Mission"),
    "MissionStatus": ("app.models.mission", "MissionStatus"),
    "PentestSession": ("app.models.pentest_session", "PentestSession"),
    "ApiKey": ("app.models.plan", "ApiKey"),
    "Plan": ("app.models.plan", "Plan"),
    "Subscription": ("app.models.plan", "Subscription"),
    "UsageRecord": ("app.models.plan", "UsageRecord"),
    "Target": ("app.models.target", "Target"),
    "TargetStatus": ("app.models.target", "TargetStatus"),
    "User": ("app.models.user", "User"),
    "UserPreferences": ("app.models.user_preferences", "UserPreferences"),
    "TrainingSample": ("app.models.training", "TrainingSample"),
    "FineTuningJob": ("app.models.training", "FineTuningJob"),
}

__all__ = list(_MODEL_EXPORTS)


def __getattr__(name: str):
    if name not in _MODEL_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = _MODEL_EXPORTS[name]
    return getattr(import_module(module_name), attr_name)
