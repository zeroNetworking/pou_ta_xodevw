"""
Transaction Service
Business logic for adding, editing, and deleting transactions.
Routes call these functions — no SQL lives in routes.
"""

from datetime import date
import logging
from .db import get_db
from .validation import safe_float, ALLOWED_TYPES

logger = logging.getLogger(__name__)


def add_transaction(user_id: int, data: dict) -> dict:
    """
    Validates and inserts a new transaction into a month.
    Returns {'success': True, 'id': new_id} or {'success': False, 'error': '...', 'status': int}.
    """
    month_id      = data.get('month_id')
    category      = data.get('category', '').strip()
    trans_type    = data.get('type', 'expense')
    is_late_entry = int(data.get('late_entry', 0))

    # Validate type
    if trans_type not in ALLOWED_TYPES:
        return {'success': False, 'error': f'Invalid type: {trans_type}', 'status': 400}

    # Validate amount
    amount = safe_float(data.get('amount', 0))
    if amount <= 0:
        return {'success': False, 'error': 'Amount must be greater than 0', 'status': 400}

    if not category:
        return {'success': False, 'error': 'Category is required', 'status': 400}

    db     = get_db()
    cursor = db.cursor()

    # Verify the target month belongs to this user
    cursor.execute("SELECT * FROM months WHERE id=? AND user_id=?", (month_id, user_id))
    month = cursor.fetchone()
    if not month:
        return {'success': False, 'error': 'Month not found', 'status': 404}

    # Closed months reject direct transactions unless it's a late entry
    if month['is_closed'] and not is_late_entry:
        return {'success': False, 'error': 'Μη επεξεργάσιμος μήνας', 'status': 403}

    cursor.execute(
        """INSERT INTO transactions
           (month_id, category, subcategory, type, amount, description,
            transaction_date, late_entry, late_entry_note)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (
            month_id,
            category,
            data.get('subcategory', ''),
            trans_type,
            amount,
            data.get('description', ''),
            data.get('date', date.today().isoformat()),
            is_late_entry,
            data.get('late_entry_note', ''),
        )
    )
    db.commit()
    new_id = cursor.lastrowid
    logger.info("User %s added transaction #%s: %.2f€ %s / %s", user_id, new_id, amount, trans_type, category)
    return {'success': True, 'id': new_id}


def edit_transaction(user_id: int, transaction_id: int, data: dict) -> dict:
    """
    Updates an existing transaction. Verifies ownership via JOIN.
    Returns {'success': True} or {'success': False, 'error': '...', 'status': int}.
    """
    trans_type = data.get('type', 'expense')
    if trans_type not in ALLOWED_TYPES:
        return {'success': False, 'error': f'Invalid type: {trans_type}', 'status': 400}

    try:
        amount = float(data.get('amount', 0))
        if amount <= 0:
            raise ValueError
    except (ValueError, TypeError):
        return {'success': False, 'error': 'Μη έγκυρο ποσό', 'status': 400}

    db     = get_db()
    cursor = db.cursor()

    # Ownership check via JOIN: transaction → month → user
    cursor.execute(
        """SELECT t.id FROM transactions t JOIN months m ON t.month_id = m.id
           WHERE t.id=? AND m.user_id=?""",
        (transaction_id, user_id)
    )
    if not cursor.fetchone():
        logger.warning("User %s tried to edit transaction %s they don't own", user_id, transaction_id)
        return {'success': False, 'error': 'Not found', 'status': 403}

    cursor.execute(
        """UPDATE transactions
           SET category=?, subcategory=?, type=?, amount=?, description=?, transaction_date=?
           WHERE id=?""",
        (
            data.get('category', ''),
            data.get('subcategory', ''),
            trans_type,
            amount,
            data.get('description', ''),
            data.get('date', date.today().isoformat()),
            transaction_id,
        )
    )
    db.commit()
    logger.info("User %s edited transaction #%s", user_id, transaction_id)
    return {'success': True}


def delete_transaction(user_id: int, transaction_id: int) -> dict:
    """
    Deletes a transaction after verifying ownership.
    Returns {'success': True} or {'success': False, 'error': '...', 'status': int}.
    """
    db     = get_db()
    cursor = db.cursor()

    cursor.execute(
        """SELECT t.id FROM transactions t JOIN months m ON t.month_id = m.id
           WHERE t.id=? AND m.user_id=?""",
        (transaction_id, user_id)
    )
    if not cursor.fetchone():
        logger.warning("User %s tried to delete transaction %s they don't own", user_id, transaction_id)
        return {'success': False, 'error': 'Not found', 'status': 403}

    cursor.execute("DELETE FROM transactions WHERE id=?", (transaction_id,))
    db.commit()
    logger.info("User %s deleted transaction #%s", user_id, transaction_id)
    return {'success': True}
