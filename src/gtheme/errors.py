"""Exception types for clean, user-facing failures."""

from __future__ import annotations


class GthemeError(Exception):
    """Base for clean, user-facing failures."""


class ThemeSecurityError(GthemeError):
    """Path escape / unsafe manifest / refused action."""


class ThemeValidationError(GthemeError):
    """Theme manifest or contents failed validation."""


class ThemeNotFoundError(GthemeError):
    """Requested theme could not be located."""
