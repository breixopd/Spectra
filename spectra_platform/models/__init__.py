"""SQLAlchemy database models."""

from __future__ import annotations

from importlib import import_module

_MODEL_EXPORTS = {
    "SystemConfig": ("spectra_platform.models.config", "SystemConfig"),
    "ServerNode": ("spectra_platform.models.server_node", "ServerNode"),
    "AuditEventType": ("spectra_platform.models.audit_log", "AuditEventType"),
    "AuditLog": ("spectra_platform.models.audit_log", "AuditLog"),
    "Base": ("spectra_common.orm.base", "Base"),
    "Exploit": ("spectra_platform.models.exploit", "Exploit"),
    "Finding": ("spectra_platform.models.finding", "Finding"),
    "FindingStatus": ("spectra_platform.models.finding", "FindingStatus"),
    "Severity": ("spectra_platform.models.finding", "Severity"),
    "Mission": ("spectra_platform.models.mission", "Mission"),
    "MissionStatus": ("spectra_platform.models.mission", "MissionStatus"),
    "PentestSession": ("spectra_platform.models.pentest_session", "PentestSession"),
    "ApiKey": ("spectra_platform.models.plan", "ApiKey"),
    "Plan": ("spectra_platform.models.plan", "Plan"),
    "Subscription": ("spectra_platform.models.plan", "Subscription"),
    "UsageRecord": ("spectra_platform.models.plan", "UsageRecord"),
    "Target": ("spectra_platform.models.target", "Target"),
    "TargetStatus": ("spectra_platform.models.target", "TargetStatus"),
    "User": ("spectra_platform.models.user", "User"),
    "UserPreferences": ("spectra_platform.models.user_preferences", "UserPreferences"),
    "TrainingSample": ("spectra_platform.models.training", "TrainingSample"),
    "FineTuningJob": ("spectra_platform.models.training", "FineTuningJob"),
}

__all__ = list(_MODEL_EXPORTS)


def __getattr__(name: str):
    if name not in _MODEL_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = _MODEL_EXPORTS[name]
    return getattr(import_module(module_name), attr_name)
