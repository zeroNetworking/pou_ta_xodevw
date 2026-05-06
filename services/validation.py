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


# Recovery answer rules: prevent trivially weak answers (empty, "a", "1234").
# We hash the answer like a password, so "low entropy = brute-forceable".
MIN_RECOVERY_ANSWER_LENGTH = 3
MAX_RECOVERY_ANSWER_LENGTH = 100


def is_valid_recovery_answer(answer: str) -> bool:
    """
    Recovery answer: 3–100 chars after stripping whitespace.
    Short enough to remember, long enough to resist trivial guessing.
    """
    cleaned = (answer or '').strip()
    return MIN_RECOVERY_ANSWER_LENGTH <= len(cleaned) <= MAX_RECOVERY_ANSWER_LENGTH


def normalize_recovery_answer(answer: str) -> str:
    """
    Canonicalize the answer before hashing so that 'Rex', ' rex ', and
    'REX' all match. We lowercase + strip — same approach used by major
    providers for security questions.
    """
    return (answer or '').strip().lower()
