"""
Rate Limiter
In-memory sliding-window rate limiting per action per IP.

FIX #2 — Memory leak prevention:
The old dict grew forever. Now cleanup_rate_limits() is called on every
before_request to evict expired timestamps and delete empty keys.

For production, replace with flask-limiter backed by Redis.
"""

import time
import logging

logger = logging.getLogger(__name__)

# Storage: { "action:ip": [timestamp1, timestamp2, ...] }
_rate_attempts: dict = {}

# Limits per action: (max_attempts, window_seconds)
RATE_LIMITS = {
    'login':           (10,  300),    # 10 failed logins per 5 minutes
    'register':        (5,   3600),   # 5 registrations per hour per IP
    'add_transaction': (60,  60),     # 60 transactions per minute (anti-spam)
}

# The maximum age of any timestamp we ever keep (= longest window)
_MAX_WINDOW = max(w for _, w in RATE_LIMITS.values())


def cleanup_rate_limits() -> None:
    """
    FIX #2 — Removes expired timestamps and deletes empty keys.
    Called by before_request so the dict stays small regardless of traffic.
    Only purges entries older than the longest rate-limit window (1 hour).
    """
    now = time.time()
    for key in list(_rate_attempts.keys()):
        _rate_attempts[key] = [t for t in _rate_attempts[key] if now - t < _MAX_WINDOW]
        if not _rate_attempts[key]:
            del _rate_attempts[key]


def is_rate_limited(action: str, ip_address: str) -> bool:
    """
    Returns True if the IP has exceeded the rate limit for the given action.
    Uses a sliding window — old attempts outside the window don't count.
    """
    limit, window = RATE_LIMITS.get(action, (100, 60))
    key    = f"{action}:{ip_address}"
    now    = time.time()
    recent = [t for t in _rate_attempts.get(key, []) if now - t < window]
    _rate_attempts[key] = recent
    return len(recent) >= limit


def record_attempt(action: str, ip_address: str) -> None:
    """Records a rate-limited action attempt timestamp for the given IP."""
    key = f"{action}:{ip_address}"
    _rate_attempts.setdefault(key, []).append(time.time())
