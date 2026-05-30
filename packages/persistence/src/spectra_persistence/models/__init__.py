"""SQLAlchemy database models."""

from __future__ import annotations

from importlib import import_module

_MODEL_EXPORTS = {
    "SystemConfig": ("spectra_persistence.models.config", "SystemConfig"),
    "ServerNode": ("spectra_persistence.models.server_node", "ServerNode"),
    "AuditEventType": ("spectra_persistence.models.audit_log", "AuditEventType"),
    "AuditLog": ("spectra_persistence.models.audit_log", "AuditLog"),
    "Base": ("spectra_persistence.orm.base", "Base"),
    "Exploit": ("spectra_persistence.models.exploit", "Exploit"),
    "Finding": ("spectra_persistence.models.finding", "Finding"),
    "FindingStatus": ("spectra_persistence.models.finding", "FindingStatus"),
    "ProofStatus": ("spectra_persistence.models.finding", "ProofStatus"),
    "Severity": ("spectra_persistence.models.finding", "Severity"),
    "Mission": ("spectra_persistence.models.mission", "Mission"),
    "MissionStatus": ("spectra_persistence.models.mission", "MissionStatus"),
    "PentestSession": ("spectra_persistence.models.pentest_session", "PentestSession"),
    "ApiKey": ("spectra_persistence.models.plan", "ApiKey"),
    "Plan": ("spectra_persistence.models.plan", "Plan"),
    "Subscription": ("spectra_persistence.models.plan", "Subscription"),
    "UsageRecord": ("spectra_persistence.models.plan", "UsageRecord"),
    "Target": ("spectra_persistence.models.target", "Target"),
    "TargetStatus": ("spectra_persistence.models.target", "TargetStatus"),
    "User": ("spectra_persistence.models.user", "User"),
    "UserPreferences": ("spectra_persistence.models.user_preferences", "UserPreferences"),
    "TrainingSample": ("spectra_persistence.models.training", "TrainingSample"),
    "FineTuningJob": ("spectra_persistence.models.training", "FineTuningJob"),
    "RulesOfEngagement": ("spectra_persistence.models.roe", "RulesOfEngagement"),
}

__all__ = list(_MODEL_EXPORTS)


def __getattr__(name: str):
    if name not in _MODEL_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = _MODEL_EXPORTS[name]
    return getattr(import_module(module_name), attr_name)
