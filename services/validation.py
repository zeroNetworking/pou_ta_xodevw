"""
Validation Helpers
Input validation used across multiple services and routes.
"""

import re

# Allowed transaction types — used for whitelist validation
ALLOWED_TYPES = {'income', 'expense'}


def safe_float(value, default: float = 0.0) -> float:
    """Converts a value to a non-negative float. Returns default on failure."""
    try:
        result = float(value)
        return result if result >= 0 else default
    except (ValueError, TypeError):
        return default


def is_valid_password(password: str) -> bool:
    """Min 8 chars, 1 uppercase, 1 digit, 1 symbol."""
    return (
        len(password) >= 8
        and bool(re.search(r'[A-Z]', password))
        and bool(re.search(r'[0-9]', password))
        and bool(re.search(r'[^A-Za-z0-9]', password))
    )


def is_valid_username(username: str) -> bool:
    """8–12 chars, letters/digits/underscore only."""
    return (
        8 <= len(username) <= 12
        and bool(re.match(r'^[A-Za-z0-9_]+$', username))
    )
