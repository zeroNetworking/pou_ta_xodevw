"""
Analytics Service
Business logic for all reporting, stats aggregation, and calendar data.
"""

import calendar
import logging
from datetime import datetime
from .db import get_db

logger = logging.getLogger(__name__)


def get_analytics_data(user_id: int) -> dict:
    """
    Loads all analytics data for a user in one pass.
    Returns a dict ready to pass directly to the analytics template.
    Uses a single GROUP BY query to avoid N+1 queries.
    """
    db     = get_db()
    cursor = db.cursor()

    # All months in chronological order (for chart x-axis)
    cursor.execute(
        "SELECT * FROM months WHERE user_id=? ORDER BY year, month", (user_id,)
    )
    all_months = cursor.fetchall()

    # Single aggregate query for ALL months at once — avoids N+1
    cursor.execute(
        """SELECT month_id,
               SUM(CASE WHEN type='income'  THEN amount ELSE 0 END) AS total_income,
               SUM(CASE WHEN type='expense' THEN amount ELSE 0 END) AS total_expense
           FROM transactions
           WHERE month_id IN (SELECT id FROM months WHERE user_id=?)
           GROUP BY month_id""",
        (user_id,)
    )
    stats_by_month_id = {
        row['month_id']: {
            'total_income':  round(row['total_income'],  2),
            'total_expense': round(row['total_expense'], 2),
            'balance':       round(row['total_income'] - row['total_expense'], 2),
        }
        for row in cursor.fetchall()
    }

    # Merge month records with their computed stats
    months_with_stats = []
    for month in all_months:
        ms = stats_by_month_id.get(month['id'], {
            'total_income': 0.0, 'total_expense': 0.0, 'balance': 0.0
        })
        months_with_stats.append({**dict(month), **ms})

    # All-time totals
    cursor.execute(
        """SELECT COALESCE(SUM(t.amount), 0) FROM transactions t JOIN months m ON t.month_id=m.id
           WHERE m.user_id=? AND t.type='income'""", (user_id,)
    )
    total_income = cursor.fetchone()[0]

    cursor.execute(
        """SELECT COALESCE(SUM(t.amount), 0) FROM transactions t JOIN months m ON t.month_id=m.id
           WHERE m.user_id=? AND t.type='expense'""", (user_id,)
    )
    total_expense = cursor.fetchone()[0]

    # Top 5 expense categories (for the horizontal bar chart)
    cursor.execute(
        """SELECT t.category, SUM(t.amount) AS total
           FROM transactions t JOIN months m ON t.month_id=m.id
           WHERE m.user_id=? AND t.type='expense'
           GROUP BY t.category ORDER BY total DESC LIMIT 5""",
        (user_id,)
    )
    top_categories = cursor.fetchall()

    # Simple spending insights
    suggestions = _build_suggestions(months_with_stats, top_categories)

    avg_expense = total_expense / len(months_with_stats) if months_with_stats else 0

    return {
        'months_with_stats': months_with_stats,
        'total_income':      round(total_income, 2),
        'total_expense':     round(total_expense, 2),
        'total_balance':     round(total_income - total_expense, 2),
        'top_categories':    top_categories,
        'suggestions':       suggestions,
        'avg_expense':       round(avg_expense, 2),
    }


def _build_suggestions(months_with_stats: list, top_categories) -> list:
    """Generates simple spending insights from the data."""
    suggestions = []

    if top_categories:
        top = top_categories[0]
        suggestions.append(
            f"Ξοδεύεις πιο πολύ σε '{top['category']}' ({top['total']:.2f}€ συνολικά)"
        )

    if len(months_with_stats) >= 2:
        last = months_with_stats[-1]
        prev = months_with_stats[-2]
        if last['total_expense'] > prev['total_expense'] * 1.1:
            diff = last['total_expense'] - prev['total_expense']
            suggestions.append(f"Τα έξοδα αυξήθηκαν κατά {diff:.2f}€ τον τελευταίο μήνα")

    return suggestions


def build_budget_alerts(expense_by_category: list, budgets: dict, stats: dict) -> list:
    """Builds budget alert messages at 75%, 90%, 100% thresholds."""
    alerts = []

    for row in expense_by_category:
        category     = row['category']
        budget_limit = budgets.get(category, 0)
        if budget_limit <= 0:
            continue
        spent      = row['total']
        percentage = (spent / budget_limit) * 100

        if percentage >= 100:
            alerts.append({'level': 'danger',
                'msg': f"🚨 Υπέρβαση budget '{category}': {spent:.2f}€ / {budget_limit:.2f}€ ({percentage:.0f}%)"})
        elif percentage >= 90:
            alerts.append({'level': 'warning',
                'msg': f"⚠️ Σχεδόν στο όριο '{category}': {spent:.2f}€ / {budget_limit:.2f}€ ({percentage:.0f}%)"})
        elif percentage >= 75:
            alerts.append({'level': 'info',
                'msg': f"📊 75%+ budget '{category}': {spent:.2f}€ / {budget_limit:.2f}€ ({percentage:.0f}%)"})

    if stats['total_income'] > 0:
        balance_pct = (stats['total_expense'] / stats['total_income']) * 100
        remaining   = stats['total_income'] - stats['total_expense']
        if balance_pct >= 100:
            alerts.append({'level': 'danger',
                'msg': f"🚨 Τα έξοδα ξεπέρασαν τα έσοδα! ({stats['total_expense']:.2f}€ > {stats['total_income']:.2f}€)"})
        elif balance_pct >= 90:
            alerts.append({'level': 'warning',
                'msg': f"⚠️ {balance_pct:.0f}% των εσόδων χρησιμοποιήθηκε — απομένουν {remaining:.2f}€"})

    return alerts


def group_transactions_by_day(transactions) -> dict:
    """Groups transactions by day number. Returns {day: {income, expense, transactions}}."""
    days_data = {}
    for t in transactions:
        try:
            day = datetime.fromisoformat(t['transaction_date']).day
        except (ValueError, TypeError):
            continue
        if day not in days_data:
            days_data[day] = {'income': 0.0, 'expense': 0.0, 'transactions': []}
        days_data[day]['transactions'].append(dict(t))
        if t['type'] == 'income':
            days_data[day]['income'] += t['amount']
        else:
            days_data[day]['expense'] += t['amount']
    return days_data


def calculate_adjacent_months(year: int, month: int) -> tuple:
    """Returns (prev_year, prev_month, next_year, next_month)."""
    prev_year  = year - 1 if month == 1  else year
    prev_month = 12       if month == 1  else month - 1
    next_year  = year + 1 if month == 12 else year
    next_month = 1        if month == 12 else month + 1
    return prev_year, prev_month, next_year, next_month


def get_dashboard_summary(user_id: int) -> dict:
    """
    Lightweight dashboard stats: per-month income/expense for the trend chart,
    all-time totals, and top 5 categories. Cheaper than full get_analytics_data().
    """
    db     = get_db()
    cursor = db.cursor()

    # Per-month stats in chronological order (for the trend chart x-axis)
    cursor.execute(
        """SELECT m.id, m.name, m.year, m.month, m.is_closed,
               COALESCE(SUM(CASE WHEN t.type='income'  THEN t.amount ELSE 0 END), 0) AS income,
               COALESCE(SUM(CASE WHEN t.type='expense' THEN t.amount ELSE 0 END), 0) AS expense
           FROM months m
           LEFT JOIN transactions t ON t.month_id = m.id
           WHERE m.user_id=?
           GROUP BY m.id
           ORDER BY m.year ASC, m.month ASC""",
        (user_id,)
    )
    monthly = []
    total_income = total_expense = 0.0
    for row in cursor.fetchall():
        inc = round(row['income'], 2)
        exp = round(row['expense'], 2)
        total_income  += inc
        total_expense += exp
        monthly.append({
            'name':    row['name'],
            'income':  inc,
            'expense': exp,
            'balance': round(inc - exp, 2),
        })

    # Top 5 expense categories all-time
    cursor.execute(
        """SELECT t.category, SUM(t.amount) AS total
           FROM transactions t JOIN months m ON t.month_id=m.id
           WHERE m.user_id=? AND t.type='expense'
           GROUP BY t.category ORDER BY total DESC LIMIT 5""",
        (user_id,)
    )
    top_cats = [{'category': r['category'], 'total': round(r['total'], 2)} for r in cursor.fetchall()]

    return {
        'monthly':       monthly,
        'total_income':  round(total_income, 2),
        'total_expense': round(total_expense, 2),
        'total_balance': round(total_income - total_expense, 2),
        'top_categories': top_cats,
        'avg_expense':   round(total_expense / len(monthly), 2) if monthly else 0,
    }
