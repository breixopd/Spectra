"""Shared Spectra tool contracts.

Worker-only execution code should stay in the worker service. Cross-service
plugin schemas, validation, and sandbox data contracts should move here.
"""

from spectra_tools_core.registry_exceptions import (
    PluginInstallationError,
    PluginValidationError,
)

__all__ = [
    "PluginInstallationError",
    "PluginValidationError",
]
