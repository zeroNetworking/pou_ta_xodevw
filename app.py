"""
Που τα ξοδεύω — Flask Application Entry Point

Architecture (routes → services → database):
  app.py            — routes only, HTTP in/out
  services/
    db.py           — DB connection (Flask g pattern)
    transactions.py — add / edit / delete transaction logic
    months.py       — create / close / delete month logic
    fixed.py        — fixed expenses + payment toggle logic
    analytics.py    — stats, charts, calendar, search logic
    rate_limit.py   — sliding-window rate limiter with memory-leak fix
    validation.py   — shared input validation helpers
    constants.py    — GREEK_MONTHS, EXPENSE_TREE, CAT_COLORS, etc.

Fixes applied:
  1.  DB uses Flask g + teardown (no manual conn.close() anywhere)
  2.  Session expiration: PERMANENT_SESSION_LIFETIME = 2 hours
  3.  Input validation on every JSON endpoint (missing fields → 400)
  4.  Business logic extracted to services/ (routes are thin wrappers)
  5.  DB CHECK constraints + 7 indexes (in services/db.py)
  6.  Rate limiting extended to register + add_transaction
  7.  CSRF protection on JSON endpoints via X-CSRF-Token header
  8.  Rate limiter memory leak fixed via before_request cleanup
  9.  debug=True replaced with DEBUG env variable
  10. Month closing throttled to once per 10 min per user
  11. Detailed logging on every write operation
  12. Profile page: change username, change password, delete account
  13. CSV export per month
"""

from flask import Flask, render_template, request, jsonify, redirect, url_for, session, g, Response
import sqlite3
import csv
import io
from datetime import datetime, date, timedelta
import os
import calendar
import hashlib
import secrets
import hmac
import logging
from urllib.parse import quote as url_quote

from services.db        import get_db, init_db
from services.constants import (
    GREEK_MONTHS, INCOME_CATEGORIES, EXPENSE_TREE, CAT_COLORS,
    MONTH_CLOSE_THROTTLE_SECONDS,
)
from services.validation  import is_valid_password, is_valid_username, safe_float, ALLOWED_TYPES
from services.rate_limit  import is_rate_limited, record_attempt, cleanup_rate_limits
from services.transactions import add_transaction as svc_add_transaction
from services.transactions import edit_transaction as svc_edit_transaction
from services.transactions import delete_transaction as svc_delete_transaction
from services.months      import (
    create_month, close_month as svc_close_month, delete_month as svc_delete_month,
    close_expired_months, get_month_stats, should_suggest_new_month,
)
from services.fixed       import add_fixed_expense, delete_fixed_expense, toggle_fixed_payment, edit_fixed_expense
from services.analytics   import (
    get_analytics_data, build_budget_alerts,
    group_transactions_by_day, calculate_adjacent_months,
    get_dashboard_summary,
)
from functools import wraps

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s  %(levelname)-8s  %(message)s',
    handlers=[
        logging.FileHandler('finance_app.log', encoding='utf-8'),
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger(__name__)


# ==============================================================================
# App Setup
# ==============================================================================

app = Flask(__name__)

_default_dev_key = 'dev-only-change-in-production-xK9#mP'
app.secret_key = os.environ.get('SECRET_KEY', _default_dev_key)

if app.secret_key == _default_dev_key:
    import warnings
    warnings.warn(
        "Using default SECRET_KEY — set SECRET_KEY env var before deployment.",
        stacklevel=2
    )
    # FIX: Block production starts with default key (Gunicorn sets this)
    if os.environ.get('GUNICORN_CMD_ARGS') or os.environ.get('PRODUCTION') == '1':
        raise RuntimeError(
            "FATAL: Set SECRET_KEY env var before running in production."
        )

app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=2)
DEBUG_MODE = os.environ.get('DEBUG', '0') == '1'


# ==============================================================================
# Request Hooks
# ==============================================================================

@app.teardown_appcontext
def close_db(exception):
    """Automatically closes the DB at the end of every request."""
    db = g.pop('db', None)
    if db is not None:
        db.close()


@app.before_request
def before_each_request():
    session.permanent = True
    cleanup_rate_limits()


# ==============================================================================
# Auth Helpers
# ==============================================================================

def hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 200_000).hex()


def verify_password(password: str, salt: str, stored_hash: str) -> bool:
    """FIX: constant-time comparison to prevent timing attacks."""
    computed = hash_password(password, salt)
    return hmac.compare_digest(computed, stored_hash)


def get_current_user_id():
    return session.get('user_id')


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not get_current_user_id():
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return wrapper


def get_common_template_vars() -> dict:
    return {'username': session.get('username'), 'now': datetime.now()}


# ==============================================================================
# CSRF Protection
# ==============================================================================

def generate_csrf_token() -> str:
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_hex(32)
    return session['csrf_token']


def validate_csrf_form() -> bool:
    form_token    = request.form.get('csrf_token', '')
    session_token = session.get('csrf_token', '')
    return form_token == session_token and len(session_token) > 0


def validate_csrf_json() -> bool:
    header_token  = request.headers.get('X-CSRF-Token', '')
    session_token = session.get('csrf_token', '')
    return header_token == session_token and len(session_token) > 0


app.jinja_env.globals['csrf_token'] = generate_csrf_token


# ==============================================================================
# Input Validation Helper
# ==============================================================================

def require_json_fields(data: dict, *fields):
    for field in fields:
        if data.get(field) is None:
            logger.warning("Missing JSON field '%s' from user %s", field, get_current_user_id())
            return False, (jsonify({'success': False, 'error': f'Missing field: {field}'}), 400)
    return True, None


def service_response(result: dict):
    status = result.pop('status', 200 if result.get('success') else 400)
    return jsonify(result), status


def safe_content_disposition(filename: str) -> str:
    """
    FIX: RFC 5987 Content-Disposition header for non-ASCII filenames.
    Uses both filename (ASCII fallback) and filename* (UTF-8 encoded).
    Solves: UnicodeEncodeError with Greek characters in HTTP headers.
    """
    ascii_name = filename.encode('ascii', 'ignore').decode('ascii') or 'export'
    utf8_name  = url_quote(filename, safe='')
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{utf8_name}"


# ==============================================================================
# Month Closing Throttle
# ==============================================================================

def maybe_close_expired_months(user_id: int) -> None:
    """Runs close_expired_months at most once every 10 min per user."""
    now      = datetime.now().timestamp()
    last_run = session.get('last_close_check', 0)
    if now - last_run >= MONTH_CLOSE_THROTTLE_SECONDS:
        close_expired_months(user_id)
        session['last_close_check'] = now


# ==============================================================================
# Routes — Authentication
# ==============================================================================

@app.route('/login', methods=['GET', 'POST'])
def login():
    if get_current_user_id():
        return redirect(url_for('index'))

    error = None

    if request.method == 'POST':
        # FIX: CSRF validation on login form
        if not validate_csrf_form():
            error = 'Σφάλμα ασφαλείας. Ανανέωσε τη σελίδα.'
            return render_template('login.html', error=error)

        username  = request.form.get('username', '').strip()
        password  = request.form.get('password', '')
        client_ip = request.remote_addr or '0.0.0.0'

        if is_rate_limited('login', client_ip):
            logger.warning("Login rate limit exceeded for IP %s", client_ip)
            error = 'Πάρα πολλές αποτυχημένες προσπάθειες. Δοκίμασε σε 5 λεπτά.'
            return render_template('login.html', error=error)

        cursor = get_db().cursor()
        cursor.execute("SELECT * FROM users WHERE username=?", (username,))
        user = cursor.fetchone()

        password_correct = (
            user is not None
            and verify_password(password, user['salt'], user['password_hash'])
        )

        if password_correct:
            # FIX: session regeneration to prevent session fixation attacks
            session.clear()
            session['user_id']  = user['id']
            session['username'] = user['username']
            logger.info("Successful login: user=%s ip=%s", username, client_ip)
            return redirect(url_for('index'))

        record_attempt('login', client_ip)
        logger.warning("Failed login: username='%s' ip=%s", username, client_ip)
        error = 'Λάθος όνομα χρήστη ή κωδικός.'

    return render_template('login.html', error=error)


@app.route('/register', methods=['GET', 'POST'])
def register():
    if get_current_user_id():
        return redirect(url_for('index'))

    errors = []

    if request.method == 'POST':
        # FIX: CSRF validation on register form
        if not validate_csrf_form():
            errors.append('Σφάλμα ασφαλείας. Ανανέωσε τη σελίδα.')
            return render_template('register.html', errors=errors)

        username  = request.form.get('username', '').strip()
        password  = request.form.get('password', '')
        confirm   = request.form.get('confirm', '')
        client_ip = request.remote_addr or '0.0.0.0'

        if is_rate_limited('register', client_ip):
            errors.append('Πάρα πολλές εγγραφές. Δοκίμασε αργότερα.')
            return render_template('register.html', errors=errors)

        if not is_valid_username(username):
            errors.append('Username: 8–12 χαρακτήρες (γράμματα, αριθμοί, _).')
        if not is_valid_password(password):
            errors.append('Κωδικός: 8+, κεφαλαίο, αριθμό, σύμβολο.')
        if password != confirm:
            errors.append('Οι κωδικοί δεν ταιριάζουν.')

        if not errors:
            salt    = secrets.token_hex(16)
            pw_hash = hash_password(password, salt)
            db      = get_db()
            cursor  = db.cursor()
            try:
                cursor.execute(
                    "INSERT INTO users (username, password_hash, salt) VALUES (?,?,?)",
                    (username, pw_hash, salt)
                )
                db.commit()
                new_user_id = cursor.lastrowid
                record_attempt('register', client_ip)
                session['user_id']  = new_user_id
                session['username'] = username
                logger.info("New user registered: %s from %s", username, client_ip)
                return redirect(url_for('index'))
            except sqlite3.IntegrityError:
                errors.append('Το username χρησιμοποιείται ήδη.')

    return render_template('register.html', errors=errors)


@app.route('/logout')
def logout():
    logger.info("User %s logged out", session.get('username'))
    session.clear()
    return redirect(url_for('login'))


# ==============================================================================
# Routes — Profile
# ==============================================================================

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    """
    Profile settings page.
    Handles three POST actions via a hidden 'action' field:
      - change_username  → validates + updates username
      - change_password  → validates current pw + sets new one
      - delete_account   → confirms password + wipes all user data
    All POST actions validate the CSRF token from the form body.
    """
    user_id = get_current_user_id()
    db      = get_db()
    cursor  = db.cursor()
    success = None
    error   = None

    if request.method == 'POST':

        if not validate_csrf_form():
            error = 'Σφάλμα ασφαλείας. Ανανέωσε τη σελίδα και δοκίμασε ξανά.'
            return _render_profile(user_id, success, error)

        action = request.form.get('action', '')

        # ── Change Username ──────────────────────────────────
        if action == 'change_username':
            new_username     = request.form.get('new_username', '').strip()
            confirm_password = request.form.get('confirm_password', '')

            cursor.execute("SELECT * FROM users WHERE id=?", (user_id,))
            user = cursor.fetchone()
            if not user or not verify_password(confirm_password, user['salt'], user['password_hash']):
                error = 'Λάθος κωδικός.'
            elif not is_valid_username(new_username):
                error = 'Username: 8–12 χαρακτήρες (γράμματα, αριθμοί, _).'
            elif new_username == user['username']:
                error = 'Το νέο username είναι ίδιο με το τρέχον.'
            else:
                try:
                    cursor.execute(
                        "UPDATE users SET username=? WHERE id=?",
                        (new_username, user_id)
                    )
                    db.commit()
                    session['username'] = new_username
                    success = f"Username αλλάχτηκε σε '{new_username}'."
                    logger.info("User %s changed username to %s", user_id, new_username)
                except sqlite3.IntegrityError:
                    error = 'Αυτό το username χρησιμοποιείται ήδη.'

        # ── Change Password ──────────────────────────────────
        elif action == 'change_password':
            current_password     = request.form.get('current_password', '')
            new_password         = request.form.get('new_password', '')
            confirm_new_password = request.form.get('confirm_new_password', '')

            cursor.execute("SELECT * FROM users WHERE id=?", (user_id,))
            user = cursor.fetchone()

            if not user or not verify_password(current_password, user['salt'], user['password_hash']):
                error = 'Ο τρέχων κωδικός είναι λάθος.'
            elif not is_valid_password(new_password):
                error = 'Νέος κωδικός: 8+, κεφαλαίο, αριθμό, σύμβολο.'
            elif new_password != confirm_new_password:
                error = 'Οι νέοι κωδικοί δεν ταιριάζουν.'
            elif new_password == current_password:
                error = 'Ο νέος κωδικός είναι ίδιος με τον παλιό.'
            else:
                new_salt    = secrets.token_hex(16)
                new_pw_hash = hash_password(new_password, new_salt)
                cursor.execute(
                    "UPDATE users SET password_hash=?, salt=? WHERE id=?",
                    (new_pw_hash, new_salt, user_id)
                )
                db.commit()
                success = 'Ο κωδικός άλλαξε επιτυχώς.'
                logger.info("User %s changed their password", user_id)

        # ── Delete Account ───────────────────────────────────
        elif action == 'delete_account':
            delete_password = request.form.get('delete_password', '')

            cursor.execute("SELECT * FROM users WHERE id=?", (user_id,))
            user = cursor.fetchone()

            if not user or not verify_password(delete_password, user['salt'], user['password_hash']):
                error = 'Λάθος κωδικός. Ο λογαριασμός δεν διαγράφηκε.'
            else:
                cursor.execute("SELECT id FROM months WHERE user_id=?", (user_id,))
                month_ids = [row['id'] for row in cursor.fetchall()]
                for mid in month_ids:
                    cursor.execute("DELETE FROM fixed_payments WHERE month_id=?", (mid,))
                    cursor.execute("DELETE FROM transactions WHERE month_id=?", (mid,))
                cursor.execute("DELETE FROM months WHERE user_id=?", (user_id,))
                cursor.execute("DELETE FROM budgets WHERE user_id=?", (user_id,))
                cursor.execute("SELECT id FROM fixed_expenses WHERE user_id=?", (user_id,))
                fe_ids = [row['id'] for row in cursor.fetchall()]
                for fid in fe_ids:
                    cursor.execute("DELETE FROM fixed_payments WHERE fixed_expense_id=?", (fid,))
                cursor.execute("DELETE FROM fixed_expenses WHERE user_id=?", (user_id,))
                cursor.execute("DELETE FROM users WHERE id=?", (user_id,))
                db.commit()
                logger.info("User %s deleted their account", user_id)
                session.clear()
                return redirect(url_for('login'))

    return _render_profile(user_id, success, error)


def _render_profile(user_id: int, success, error):
    """Helper: loads profile stats and renders the profile template."""
    db     = get_db()
    cursor = db.cursor()

    cursor.execute("SELECT username, created_at FROM users WHERE id=?", (user_id,))
    user = cursor.fetchone()

    cursor.execute("SELECT COUNT(*) FROM months WHERE user_id=?", (user_id,))
    total_months = cursor.fetchone()[0]

    cursor.execute(
        """SELECT COUNT(*) FROM transactions t JOIN months m ON t.month_id = m.id
           WHERE m.user_id=?""", (user_id,)
    )
    total_transactions = cursor.fetchone()[0]

    cursor.execute(
        "SELECT * FROM months WHERE user_id=? ORDER BY year DESC, month DESC", (user_id,)
    )
    all_months = cursor.fetchall()

    return render_template('profile.html',
        created_at=user['created_at'],
        total_months=total_months,
        total_transactions=total_transactions,
        all_months=all_months,
        greek_months=GREEK_MONTHS,
        success=success,
        error=error,
        **get_common_template_vars()
    )


# ==============================================================================
# Routes — Dashboard & Months
# ==============================================================================

@app.route('/')
@login_required
def index():
    user_id = get_current_user_id()
    maybe_close_expired_months(user_id)

    today  = date.today()
    cursor = get_db().cursor()
    cursor.execute(
        "SELECT * FROM months WHERE user_id=? ORDER BY year DESC, month DESC", (user_id,)
    )
    all_months = cursor.fetchall()

    current_month = next(
        (m for m in all_months if m['year'] == today.year and m['month'] == today.month),
        None
    )

    # Dashboard summary: trend chart data + all-time totals
    dash = get_dashboard_summary(user_id) if all_months else None

    return render_template('index.html',
        months=all_months, current_month=current_month,
        all_months=all_months, greek_months=GREEK_MONTHS,
        cat_colors=CAT_COLORS, dash=dash,
        today=today, suggest_new_month=should_suggest_new_month(user_id),
        next_month=today.month, next_year=today.year,
        **get_common_template_vars()
    )


@app.route('/new_month', methods=['POST'])
@login_required
def new_month():
    if not validate_csrf_json():
        return jsonify({'success': False, 'error': 'CSRF validation failed'}), 403
    user_id = get_current_user_id()
    data    = request.json or {}
    try:
        year  = int(data.get('year',  date.today().year))
        month = int(data.get('month', date.today().month))
    except (ValueError, TypeError):
        return jsonify({'success': False, 'error': 'Invalid year or month'}), 400
    result = create_month(user_id, year, month)
    return service_response(result)


@app.route('/delete_month/<int:month_id>', methods=['DELETE'])
@login_required
def delete_month(month_id):
    if not validate_csrf_json():
        return jsonify({'success': False, 'error': 'CSRF validation failed'}), 403
    user_id = get_current_user_id()
    result  = svc_delete_month(user_id, month_id)
    return service_response(result)


@app.route('/month/<int:month_id>')
@login_required
def month_detail(month_id):
    user_id = get_current_user_id()
    maybe_close_expired_months(user_id)

    db     = get_db()
    cursor = db.cursor()

    cursor.execute("SELECT * FROM months WHERE id=? AND user_id=?", (month_id, user_id))
    month = cursor.fetchone()
    if not month:
        return redirect(url_for('index'))

    cursor.execute(
        "SELECT * FROM transactions WHERE month_id=? ORDER BY transaction_date DESC, id DESC",
        (month_id,)
    )
    transactions = cursor.fetchall()

    cursor.execute("SELECT * FROM budgets WHERE user_id=?", (user_id,))
    budgets = {row['category']: row['amount'] for row in cursor.fetchall()}

    cursor.execute(
        """SELECT category, SUM(amount) AS total FROM transactions
           WHERE month_id=? AND type='expense' GROUP BY category ORDER BY total DESC""",
        (month_id,)
    )
    expense_by_category = cursor.fetchall()

    cursor.execute(
        "SELECT * FROM months WHERE user_id=? ORDER BY year DESC, month DESC", (user_id,)
    )
    all_months = cursor.fetchall()

    cursor.execute(
        "SELECT * FROM months WHERE user_id=? AND is_closed=1 ORDER BY year DESC, month DESC LIMIT 6",
        (user_id,)
    )
    closed_months = cursor.fetchall()

    cursor.execute(
        "SELECT * FROM fixed_expenses WHERE user_id=? ORDER BY sort_order, id", (user_id,)
    )
    fixed_expenses = cursor.fetchall()

    fixed_payment_status = {}
    for fe in fixed_expenses:
        cursor.execute(
            "SELECT * FROM fixed_payments WHERE fixed_expense_id=? AND month_id=?",
            (fe['id'], month_id)
        )
        payment = cursor.fetchone()
        fixed_payment_status[fe['id']] = {
            'paid':    bool(payment and payment['paid']),
            'paid_at': payment['paid_at'] if payment else None,
        }

    stats  = get_month_stats(month_id)
    alerts = build_budget_alerts(expense_by_category, budgets, stats)

    editable = not month['is_closed']
    days_since_close = None
    if month['is_closed'] and month['closed_at']:
        closed_date      = datetime.fromisoformat(month['closed_at']).date()
        days_since_close = (date.today() - closed_date).days

    return render_template('month.html',
        month=month, transactions=transactions, stats=stats,
        income_categories=INCOME_CATEGORIES, expense_tree=EXPENSE_TREE,
        cat_colors=CAT_COLORS, expense_by_cat=expense_by_category,
        budgets=budgets, alerts=alerts, all_months=all_months,
        closed_months=closed_months, fixed_expenses=fixed_expenses,
        fixed_status=fixed_payment_status, greek_months=GREEK_MONTHS,
        editable=editable, days_since_close=days_since_close,
        **get_common_template_vars()
    )


@app.route('/close_month/<int:month_id>', methods=['POST'])
@login_required
def close_month(month_id):
    if not validate_csrf_json():
        return jsonify({'success': False, 'error': 'CSRF validation failed'}), 403
    user_id = get_current_user_id()
    result  = svc_close_month(user_id, month_id)
    return service_response(result)


# ==============================================================================
# Routes — Transactions (CRUD)
# ==============================================================================

@app.route('/add_transaction', methods=['POST'])
@login_required
def add_transaction():
    if not validate_csrf_json():
        return jsonify({'success': False, 'error': 'CSRF validation failed'}), 403
    user_id   = get_current_user_id()
    client_ip = request.remote_addr or '0.0.0.0'
    data      = request.json or {}
    if is_rate_limited('add_transaction', client_ip):
        return jsonify({'success': False, 'error': 'Too many requests'}), 429
    ok, err = require_json_fields(data, 'month_id', 'category', 'amount')
    if not ok:
        return err
    result = svc_add_transaction(user_id, data)
    return service_response(result)


@app.route('/edit_transaction/<int:transaction_id>', methods=['PUT'])
@login_required
def edit_transaction(transaction_id):
    if not validate_csrf_json():
        return jsonify({'success': False, 'error': 'CSRF validation failed'}), 403
    user_id = get_current_user_id()
    data    = request.json or {}
    ok, err = require_json_fields(data, 'category', 'amount')
    if not ok:
        return err
    result = svc_edit_transaction(user_id, transaction_id, data)
    return service_response(result)


@app.route('/delete_transaction/<int:transaction_id>', methods=['DELETE'])
@login_required
def delete_transaction(transaction_id):
    if not validate_csrf_json():
        return jsonify({'success': False, 'error': 'CSRF validation failed'}), 403
    user_id = get_current_user_id()
    result  = svc_delete_transaction(user_id, transaction_id)
    return service_response(result)


# ==============================================================================
# Routes — Budget
# ==============================================================================

@app.route('/set_budget', methods=['POST'])
@login_required
def set_budget():
    if not validate_csrf_json():
        return jsonify({'success': False, 'error': 'CSRF validation failed'}), 403
    user_id = get_current_user_id()
    data    = request.json or {}
    ok, err = require_json_fields(data, 'category')
    if not ok:
        return err
    db     = get_db()
    cursor = db.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO budgets (user_id, category, amount) VALUES (?,?,?)",
        (user_id, data.get('category', ''), safe_float(data.get('amount', 0)))
    )
    db.commit()
    logger.info("User %s updated budget for '%s': %.2f€", user_id, data.get('category'), safe_float(data.get('amount', 0)))
    return jsonify({'success': True})


# ==============================================================================
# Routes — Fixed Expenses
# ==============================================================================

@app.route('/fixed_expenses', methods=['POST'])
@login_required
def add_fixed_expense_route():
    if not validate_csrf_json():
        return jsonify({'success': False, 'error': 'CSRF validation failed'}), 403
    user_id = get_current_user_id()
    data    = request.json or {}
    result  = add_fixed_expense(user_id, data)
    return service_response(result)


@app.route('/fixed_expenses/<int:fixed_expense_id>', methods=['DELETE'])
@login_required
def delete_fixed_expense_route(fixed_expense_id):
    if not validate_csrf_json():
        return jsonify({'success': False, 'error': 'CSRF validation failed'}), 403
    user_id = get_current_user_id()
    result  = delete_fixed_expense(user_id, fixed_expense_id)
    return service_response(result)


@app.route('/fixed_expenses/<int:fixed_expense_id>', methods=['PUT'])
@login_required
def edit_fixed_expense_route(fixed_expense_id):
    if not validate_csrf_json():
        return jsonify({'success': False, 'error': 'CSRF validation failed'}), 403
    user_id = get_current_user_id()
    data    = request.json or {}
    result  = edit_fixed_expense(user_id, fixed_expense_id, data)
    return service_response(result)


@app.route('/fixed_payment', methods=['POST'])
@login_required
def toggle_fixed_payment_route():
    if not validate_csrf_json():
        return jsonify({'success': False, 'error': 'CSRF validation failed'}), 403
    user_id = get_current_user_id()
    data    = request.json or {}
    ok, err = require_json_fields(data, 'fixed_expense_id', 'month_id')
    if not ok:
        return err
    result = toggle_fixed_payment(user_id, data)
    return service_response(result)


# ==============================================================================
# Routes — Analytics, Calendar, Search
# ==============================================================================

@app.route('/analytics')
@login_required
def analytics():
    user_id = get_current_user_id()
    db      = get_db()
    cursor  = db.cursor()
    data    = get_analytics_data(user_id)
    cursor.execute(
        "SELECT * FROM months WHERE user_id=? ORDER BY year DESC, month DESC", (user_id,)
    )
    sidebar_months = cursor.fetchall()
    return render_template('analytics.html',
        analytics_data=data['months_with_stats'],
        total_income=data['total_income'],
        total_expense=data['total_expense'],
        total_balance=data['total_balance'],
        top_categories=data['top_categories'],
        suggestions=data['suggestions'],
        avg_expense=data['avg_expense'],
        cat_colors=CAT_COLORS,
        all_months=sidebar_months,
        greek_months=GREEK_MONTHS,
        **get_common_template_vars()
    )


@app.route('/calendar')
@app.route('/calendar/<int:year>/<int:month_num>')
@login_required
def calendar_view(year=None, month_num=None):
    user_id = get_current_user_id()
    today   = date.today()
    if year is None:
        year = today.year
    if month_num is None:
        month_num = today.month
    if not (1 <= month_num <= 12) or not (2000 <= year <= 2100):
        return redirect(url_for('calendar_view'))
    prev_year, prev_month, next_year, next_month = calculate_adjacent_months(year, month_num)
    first_weekday, days_in_month = calendar.monthrange(year, month_num)
    db     = get_db()
    cursor = db.cursor()
    cursor.execute(
        """SELECT t.* FROM transactions t JOIN months m ON t.month_id = m.id
           WHERE m.user_id=? AND m.year=? AND m.month=?
           ORDER BY t.transaction_date, t.id""",
        (user_id, year, month_num)
    )
    transactions = cursor.fetchall()
    cursor.execute(
        "SELECT id FROM months WHERE user_id=? AND year=? AND month=?",
        (user_id, year, month_num)
    )
    month_row = cursor.fetchone()
    month_id  = month_row['id'] if month_row else None
    cursor.execute(
        "SELECT * FROM months WHERE user_id=? ORDER BY year DESC, month DESC", (user_id,)
    )
    all_months = cursor.fetchall()
    return render_template('calendar.html',
        year=year, month_num=month_num, month_name=GREEK_MONTHS[month_num],
        first_weekday=first_weekday, days_in_month=days_in_month,
        days_data=group_transactions_by_day(transactions),
        today=today, prev_year=prev_year, prev_month=prev_month,
        next_year=next_year, next_month=next_month,
        month_id=month_id, all_months=all_months, greek_months=GREEK_MONTHS,
        **get_common_template_vars()
    )


@app.route('/search')
@login_required
def search():
    user_id = get_current_user_id()
    query   = request.args.get('q', '').strip()
    pattern = f'%{query}%'
    db      = get_db()
    cursor  = db.cursor()
    cursor.execute(
        """SELECT t.*, m.name AS month_name
           FROM transactions t JOIN months m ON t.month_id=m.id
           WHERE m.user_id=? AND (t.category LIKE ? OR t.subcategory LIKE ? OR t.description LIKE ?)
           ORDER BY t.transaction_date DESC""",
        (user_id, pattern, pattern, pattern)
    )
    results = cursor.fetchall()
    cursor.execute(
        "SELECT * FROM months WHERE user_id=? ORDER BY year DESC, month DESC", (user_id,)
    )
    all_months = cursor.fetchall()
    return render_template('search.html',
        results=results, query=query, all_months=all_months,
        greek_months=GREEK_MONTHS, **get_common_template_vars()
    )


# ==============================================================================
# Routes — Export
# ==============================================================================

@app.route('/export/month/<int:month_id>/csv')
@login_required
def export_month_csv(month_id):
    """Exports all transactions of a month as a UTF-8 CSV file (with BOM for Excel)."""
    user_id = get_current_user_id()
    db      = get_db()
    cursor  = db.cursor()

    cursor.execute("SELECT * FROM months WHERE id=? AND user_id=?", (month_id, user_id))
    month = cursor.fetchone()
    if not month:
        return redirect(url_for('index'))

    cursor.execute(
        """SELECT transaction_date, type, category, subcategory,
                  amount, description, late_entry, late_entry_note
           FROM transactions WHERE month_id=?
           ORDER BY transaction_date ASC, id ASC""",
        (month_id,)
    )
    transactions = cursor.fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Ημερομηνία', 'Τύπος', 'Κατηγορία', 'Υποκατηγορία',
                     'Ποσό (€)', 'Περιγραφή', 'Καθυστερημένη', 'Σημείωση'])

    total_income = total_expense = 0.0
    for t in transactions:
        writer.writerow([
            t['transaction_date'],
            'Έσοδο' if t['type'] == 'income' else 'Έξοδο',
            t['category'], t['subcategory'] or '',
            f"{t['amount']:.2f}", t['description'] or '',
            'Ναι' if t['late_entry'] else 'Όχι', t['late_entry_note'] or '',
        ])
        if t['type'] == 'income':
            total_income += t['amount']
        else:
            total_expense += t['amount']

    writer.writerow([])
    writer.writerow(['ΣΥΝΟΛΑ', '', '', '', '', '', '', ''])
    writer.writerow(['Σύνολο Εσόδων',  '', '', '', f"{total_income:.2f}",  '', '', ''])
    writer.writerow(['Σύνολο Εξόδων',  '', '', '', f"{total_expense:.2f}", '', '', ''])
    writer.writerow(['Υπόλοιπο',       '', '', '', f"{total_income - total_expense:.2f}", '', '', ''])

    output.seek(0)
    safe_name = month['name'].replace(' ', '_').replace('/', '-')
    filename  = f"pou_ta_xodevw_{safe_name}.csv"
    logger.info("User %s exported month %s as CSV", user_id, month_id)

    return Response(
        '\ufeff' + output.getvalue(),
        mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': safe_content_disposition(filename)}
    )


@app.route('/export/month/<int:month_id>/pdf')
@login_required
def export_month_pdf(month_id):
    """
    Generates and downloads a full monthly PDF report.
    Includes: summary stats, category bar chart, fixed expenses
    payment status, and the complete transaction list.
    """
    try:
        from services.pdf_report import generate_month_pdf
    except ImportError:
        logger.error("reportlab not installed — PDF export unavailable")
        return jsonify({
            'success': False,
            'error': 'Η εξαγωγή PDF δεν είναι διαθέσιμη. Εγκατέστησε: pip install reportlab'
        }), 500

    user_id = get_current_user_id()
    db      = get_db()
    cursor  = db.cursor()

    # Ownership check
    cursor.execute("SELECT * FROM months WHERE id=? AND user_id=?", (month_id, user_id))
    month = cursor.fetchone()
    if not month:
        return redirect(url_for('index'))

    # Fetch all required data
    cursor.execute(
        "SELECT * FROM transactions WHERE month_id=? ORDER BY transaction_date ASC, id ASC",
        (month_id,)
    )
    transactions = cursor.fetchall()

    cursor.execute(
        """SELECT category, SUM(amount) AS total FROM transactions
           WHERE month_id=? AND type='expense'
           GROUP BY category ORDER BY total DESC""",
        (month_id,)
    )
    expense_by_cat = cursor.fetchall()

    cursor.execute(
        "SELECT * FROM fixed_expenses WHERE user_id=? ORDER BY sort_order, id",
        (user_id,)
    )
    fixed_expenses = cursor.fetchall()

    # Build fixed payment status dict
    fixed_payment_status = {}
    for fe in fixed_expenses:
        cursor.execute(
            "SELECT * FROM fixed_payments WHERE fixed_expense_id=? AND month_id=?",
            (fe['id'], month_id)
        )
        payment = cursor.fetchone()
        fixed_payment_status[fe['id']] = {
            'paid':    bool(payment and payment['paid']),
            'paid_at': payment['paid_at'] if payment else None,
        }

    stats = get_month_stats(month_id)

    # Generate PDF bytes
    pdf_bytes = generate_month_pdf(
        dict(month), list(map(dict, transactions)), stats,
        list(map(dict, expense_by_cat)),
        list(map(dict, fixed_expenses)),
        fixed_payment_status
    )

    safe_name = month['name'].replace(' ', '_').replace('/', '-')
    filename  = f"pou_ta_xodevw_{safe_name}.pdf"
    logger.info("User %s exported month %s as PDF", user_id, month_id)

    return Response(
        pdf_bytes,
        mimetype='application/pdf',
        headers={'Content-Disposition': safe_content_disposition(filename)}
    )


@app.route('/export/year/csv')
@login_required
def export_year_csv():
    """
    Exports multiple months as a single CSV.
    Query params: month_ids=1,2,3 (comma-separated month IDs)
    """
    user_id   = get_current_user_id()
    month_ids = request.args.get('month_ids', '')
    if not month_ids:
        return jsonify({'error': 'Δεν επιλέχθηκαν μήνες'}), 400

    try:
        ids = [int(x) for x in month_ids.split(',') if x.strip()]
    except ValueError:
        return jsonify({'error': 'Invalid month IDs'}), 400

    db     = get_db()
    cursor = db.cursor()

    # Verify all months belong to this user
    placeholders = ','.join('?' * len(ids))
    cursor.execute(
        f"SELECT * FROM months WHERE id IN ({placeholders}) AND user_id=? ORDER BY year, month",
        ids + [user_id]
    )
    months = cursor.fetchall()
    if not months:
        return redirect(url_for('index'))

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Μήνας', 'Ημερομηνία', 'Τύπος', 'Κατηγορία', 'Υποκατηγορία',
                     'Ποσό (€)', 'Περιγραφή'])

    grand_income = grand_expense = 0.0
    for m in months:
        cursor.execute(
            """SELECT * FROM transactions WHERE month_id=?
               ORDER BY transaction_date ASC, id ASC""",
            (m['id'],)
        )
        for t in cursor.fetchall():
            writer.writerow([
                m['name'],
                t['transaction_date'],
                'Έσοδο' if t['type'] == 'income' else 'Έξοδο',
                t['category'], t['subcategory'] or '',
                f"{t['amount']:.2f}", t['description'] or '',
            ])
            if t['type'] == 'income':
                grand_income += t['amount']
            else:
                grand_expense += t['amount']

    writer.writerow([])
    writer.writerow(['ΣΥΝΟΛΑ', '', '', '', '', '', ''])
    writer.writerow(['Σύνολο Εσόδων',  '', '', '', '', f"{grand_income:.2f}", ''])
    writer.writerow(['Σύνολο Εξόδων',  '', '', '', '', f"{grand_expense:.2f}", ''])
    writer.writerow(['Υπόλοιπο',       '', '', '', '', f"{grand_income - grand_expense:.2f}", ''])

    output.seek(0)
    first = months[0]
    last  = months[-1]
    filename = f"pou_ta_xodevw_{first['year']}_{first['month']:02d}-{last['year']}_{last['month']:02d}.csv"
    logger.info("User %s exported %d months as CSV", user_id, len(months))

    return Response(
        '\ufeff' + output.getvalue(),
        mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': safe_content_disposition(filename)}
    )


# ==============================================================================
# API Endpoints (JSON)
# ==============================================================================

@app.route('/api/month_stats/<int:month_id>')
@login_required
def api_month_stats(month_id):
    # FIX: ownership check — prevent users from reading other users' month stats
    user_id = get_current_user_id()
    cursor  = get_db().cursor()
    cursor.execute("SELECT id FROM months WHERE id=? AND user_id=?", (month_id, user_id))
    if not cursor.fetchone():
        return jsonify({'error': 'Not found'}), 404
    return jsonify(get_month_stats(month_id))


@app.route('/api/now')
def api_now():
    now = datetime.now()
    return jsonify({'time': now.strftime('%H:%M:%S'), 'month': GREEK_MONTHS[now.month]})


@app.route('/api/csrf_token')
@login_required
def api_csrf_token():
    return jsonify({'csrf_token': generate_csrf_token()})


# ==============================================================================
# Entry Point
# ==============================================================================

if __name__ == '__main__':
    init_db()
    logger.info("Που τα ξοδεύω starting on port 5000 (debug=%s)", DEBUG_MODE)
    app.run(debug=DEBUG_MODE, port=5000)
