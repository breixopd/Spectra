"""Utility functions for Mission Executor."""

import logging
import re

logger = logging.getLogger(__name__)

def detect_target_type(target: str) -> str:
    """Detect target type from format."""
    # URL pattern
    if target.startswith(("http://", "https://")):
        return "url"

    # CIDR pattern
    if "/" in target and re.match(
        r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}/\d{1,2}$", target
    ):
        return "cidr"

    # IP address pattern
    if re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", target):
        return "ip"

    # Domain pattern
    if re.match(r"^[a-zA-Z0-9][a-zA-Z0-9-]*\.[a-zA-Z]{2,}$", target):
        return "domain"

    return "host"
