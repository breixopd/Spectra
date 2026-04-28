"""Shared plugin registry exceptions."""


class PluginValidationError(Exception):
    """Raised when plugin validation fails."""


class PluginInstallationError(Exception):
    """Raised when plugin installation fails."""
