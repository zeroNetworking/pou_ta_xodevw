"""
Fixed Expenses Service
Business logic for recurring monthly bills and their payment tracking.
"""

import logging
from datetime import date, datetime
from .db import get_db
from .validation import safe_float

logger = logging.getLogger(__name__)


def add_fixed_expense(user_id: int, data: dict) -> dict:
    """
    Creates a new recurring fixed expense definition.
    Returns {'success': True, 'id': new_id} or error dict.
    """
    label = data.get('label', '').strip()
    if not label:
        return {'success': False, 'error': 'Label cannot be empty', 'status': 400}

    db     = get_db()
    cursor = db.cursor()
    cursor.execute(
        "INSERT INTO fixed_expenses (user_id, label, amount, category) VALUES (?,?,?,?)",
        (user_id, label, safe_float(data.get('amount', 0)), data.get('category', ''))
    )
    db.commit()
    new_id = cursor.lastrowid
    logger.info("User %s added fixed expense #%s: %s", user_id, new_id, label)
    return {'success': True, 'id': new_id}


def delete_fixed_expense(user_id: int, fixed_expense_id: int) -> dict:
    """
    Deletes a fixed expense and all its payment records.
    FIX: ownership check runs BEFORE deleting payments to prevent
    an attacker from wiping another user's payment records.
    """
    db     = get_db()
    cursor = db.cursor()
    # Verify ownership first — abort if this expense doesn't belong to the user
    cursor.execute(
        "SELECT id FROM fixed_expenses WHERE id=? AND user_id=?", (fixed_expense_id, user_id)
    )
    if not cursor.fetchone():
        return {'success': False, 'error': 'Not found', 'status': 404}
    # Safe to delete now — ownership confirmed
    cursor.execute("DELETE FROM fixed_payments WHERE fixed_expense_id=?", (fixed_expense_id,))
    cursor.execute("DELETE FROM fixed_expenses WHERE id=?", (fixed_expense_id,))
    db.commit()
    logger.info("User %s deleted fixed expense #%s", user_id, fixed_expense_id)
    return {'success': True}


def edit_fixed_expense(user_id: int, fixed_expense_id: int, data: dict) -> dict:
    """
    Updates an existing fixed expense (label, amount, category).
    Returns {'success': True} or error dict.
    """
    label = data.get('label', '').strip()
    if not label:
        return {'success': False, 'error': 'Η περιγραφή δεν μπορεί να είναι κενή', 'status': 400}

    db     = get_db()
    cursor = db.cursor()

    cursor.execute(
        "SELECT id FROM fixed_expenses WHERE id=? AND user_id=?", (fixed_expense_id, user_id)
    )
    if not cursor.fetchone():
        return {'success': False, 'error': 'Not found', 'status': 404}

    cursor.execute(
        "UPDATE fixed_expenses SET label=?, amount=?, category=? WHERE id=?",
        (label, safe_float(data.get('amount', 0)), data.get('category', ''), fixed_expense_id)
    )
    db.commit()
    logger.info("User %s edited fixed expense #%s: %s", user_id, fixed_expense_id, label)
    return {'success': True}


def toggle_fixed_payment(user_id: int, data: dict) -> dict:
    """
    Marks a fixed expense as paid or unpaid for a specific month.
    When paid and the expense has an amount, automatically inserts/removes the transaction.
    Only works on open months.
    Returns {'success': True} or error dict.
    """
    fixed_expense_id = data.get('fixed_expense_id')
    month_id         = data.get('month_id')
    mark_as_paid     = int(data.get('paid', 1))

    db     = get_db()
    cursor = db.cursor()

    # Verify ownership of the fixed expense
    cursor.execute(
        "SELECT * FROM fixed_expenses WHERE id=? AND user_id=?", (fixed_expense_id, user_id)
    )
    fixed_expense = cursor.fetchone()
    if not fixed_expense:
        return {'success': False, 'error': 'Fixed expense not found', 'status': 404}

    # Verify the target month is open and belongs to this user
    cursor.execute("SELECT * FROM months WHERE id=? AND user_id=?", (month_id, user_id))
    target_month = cursor.fetchone()
    if not target_month or target_month['is_closed']:
        return {'success': False, 'error': 'Δεν μπορείς να αλλάξεις σταθερά έξοδα σε κλειστό μήνα', 'status': 403}

    cursor.execute(
        "SELECT * FROM fixed_payments WHERE fixed_expense_id=? AND month_id=?",
        (fixed_expense_id, month_id)
    )
    existing_payment = cursor.fetchone()

    has_amount       = fixed_expense['amount'] and fixed_expense['amount'] > 0
    auto_description = f"[Σταθερό] {fixed_expense['label']}"
    category         = fixed_expense['category'] or 'Διάφορα / Έκτακτα'

    if mark_as_paid and has_amount:
        # Insert auto-transaction when marking as paid
        cursor.execute(
            """INSERT INTO transactions
               (month_id, category, subcategory, type, amount, description, transaction_date)
               VALUES (?,?,?,?,?,?,?)""",
            (month_id, category, '', 'expense', fixed_expense['amount'],
             auto_description, date.today().isoformat())
        )
    elif not mark_as_paid and existing_payment and has_amount:
        # Remove the auto-transaction when marking as unpaid
        cursor.execute(
            """DELETE FROM transactions
               WHERE month_id=? AND description=? AND amount=? AND type='expense'""",
            (month_id, auto_description, fixed_expense['amount'])
        )

    # Upsert the payment record
    cursor.execute(
        """INSERT INTO fixed_payments (fixed_expense_id, month_id, paid, paid_at)
           VALUES (?,?,?,?)
           ON CONFLICT(fixed_expense_id, month_id)
           DO UPDATE SET paid=excluded.paid, paid_at=excluded.paid_at""",
        (fixed_expense_id, month_id, mark_as_paid,
         datetime.now().isoformat() if mark_as_paid else None)
    )
    db.commit()
    logger.info("User %s toggled fixed payment fe=%s month=%s paid=%s",
                user_id, fixed_expense_id, month_id, mark_as_paid)
    return {'success': True}
