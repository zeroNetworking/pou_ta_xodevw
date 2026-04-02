"""
Month Service
Business logic for creating, closing, and managing accounting months.
"""

import calendar
import logging
from datetime import datetime, date
import sqlite3
from .db import get_db
from .constants import GREEK_MONTHS

logger = logging.getLogger(__name__)


def create_month(user_id: int, year: int, month: int) -> dict:
    """
    Creates a new accounting month for the user.
    Rules:
      - Year must be 2000–2100, month must be 1–12
      - Cannot create a month in the past (before the current calendar month)
    """
    if not (2000 <= year <= 2100):
        return {'success': False, 'error': 'Year out of range (2000–2100)', 'status': 400}
    if not (1 <= month <= 12):
        return {'success': False, 'error': 'Month must be between 1 and 12', 'status': 400}

    # Block past months — only current month or future months allowed
    today = date.today()
    if (year, month) < (today.year, today.month):
        return {
            'success': False,
            'error': f'Δεν μπορείς να δημιουργήσεις μήνα στο παρελθόν. '
                     f'Ο νωρίτερος επιτρεπτός είναι {GREEK_MONTHS[today.month]} {today.year}.',
            'status': 400
        }

    name   = f"{GREEK_MONTHS[month]} {year}"
    db     = get_db()
    cursor = db.cursor()

    # Pre-check: does THIS USER already have this month?
    cursor.execute(
        "SELECT id FROM months WHERE user_id=? AND year=? AND month=?",
        (user_id, year, month)
    )
    existing = cursor.fetchone()
    if existing:
        return {'success': False, 'error': 'Ο μήνας υπάρχει ήδη', 'month_id': existing['id'], 'status': 409}

    try:
        cursor.execute(
            "INSERT INTO months (user_id, year, month, name) VALUES (?,?,?,?)",
            (user_id, year, month, name)
        )
        db.commit()
        new_id = cursor.lastrowid
        logger.info("User %s created month %s-%s (id=%s)", user_id, year, month, new_id)
        return {'success': True, 'month_id': new_id, 'name': name}

    except sqlite3.IntegrityError as e:
        logger.error("IntegrityError creating month for user %s: %s", user_id, e)
        return {'success': False, 'error': 'Σφάλμα δημιουργίας μήνα. Δοκίμασε να διαγράψεις τη βάση και να ξαναρχίσεις.', 'status': 500}


def close_month(user_id: int, month_id: int) -> dict:
    """
    Manually closes a month, making it read-only.
    Returns {'success': True} or {'success': False, 'error': '...', 'status': int}.
    """
    db     = get_db()
    cursor = db.cursor()

    cursor.execute("SELECT id FROM months WHERE id=? AND user_id=?", (month_id, user_id))
    if not cursor.fetchone():
        logger.warning("User %s tried to close month %s they don't own", user_id, month_id)
        return {'success': False, 'error': 'Not found', 'status': 403}

    cursor.execute(
        "UPDATE months SET is_closed=1, closed_at=? WHERE id=?",
        (datetime.now().isoformat(), month_id)
    )
    db.commit()
    logger.info("User %s closed month %s", user_id, month_id)
    return {'success': True}


def delete_month(user_id: int, month_id: int) -> dict:
    """
    Permanently deletes a month and all its transactions and fixed payments.
    Returns {'success': True} or {'success': False, 'error': '...', 'status': int}.
    """
    db     = get_db()
    cursor = db.cursor()

    cursor.execute("SELECT id FROM months WHERE id=? AND user_id=?", (month_id, user_id))
    if not cursor.fetchone():
        return {'success': False, 'error': 'Not found', 'status': 404}

    cursor.execute("DELETE FROM fixed_payments WHERE month_id=?", (month_id,))
    cursor.execute("DELETE FROM transactions WHERE month_id=?", (month_id,))
    cursor.execute("DELETE FROM months WHERE id=?", (month_id,))
    db.commit()
    logger.info("User %s deleted month %s", user_id, month_id)
    return {'success': True}


def close_expired_months(user_id: int) -> None:
    """
    Auto-closes all months whose last day has passed.
    Called via the throttled maybe_close_expired_months() in app.py,
    so it runs at most once every 10 minutes per user.
    """
    now    = datetime.now()
    db     = get_db()
    cursor = db.cursor()

    cursor.execute("SELECT * FROM months WHERE is_closed=0 AND user_id=?", (user_id,))
    for month in cursor.fetchall():
        last_day  = calendar.monthrange(month['year'], month['month'])[1]
        month_end = datetime(month['year'], month['month'], last_day, 23, 59, 59)
        if now > month_end:
            cursor.execute(
                "UPDATE months SET is_closed=1, closed_at=? WHERE id=?",
                (month_end.isoformat(), month['id'])
            )
    db.commit()


def get_month_stats(month_id: int) -> dict:
    """Calculates income, expense, balance, and top category for a month."""
    db     = get_db()
    cursor = db.cursor()

    cursor.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE month_id=? AND type='income'",
        (month_id,)
    )
    total_income = cursor.fetchone()[0]

    cursor.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE month_id=? AND type='expense'",
        (month_id,)
    )
    total_expense = cursor.fetchone()[0]

    cursor.execute(
        """SELECT category, SUM(amount) AS total FROM transactions
           WHERE month_id=? AND type='expense'
           GROUP BY category ORDER BY total DESC LIMIT 1""",
        (month_id,)
    )
    top = cursor.fetchone()

    return {
        'total_income':         round(total_income, 2),
        'total_expense':        round(total_expense, 2),
        'balance':              round(total_income - total_expense, 2),
        'top_expense_category': top['category'] if top else None,
        'top_expense_amount':   round(top['total'], 2) if top else 0,
    }


def should_suggest_new_month(user_id: int) -> bool:
    """Returns True if the app should prompt to create a new month."""
    today  = date.today()
    db     = get_db()
    cursor = db.cursor()

    cursor.execute(
        "SELECT id FROM months WHERE user_id=? AND year=? AND month=?",
        (user_id, today.year, today.month)
    )
    has_current = cursor.fetchone() is not None

    cursor.execute(
        "SELECT COUNT(*) FROM months WHERE user_id=? AND is_closed=1", (user_id,)
    )
    has_closed = cursor.fetchone()[0] > 0

    return not has_current and has_closed
