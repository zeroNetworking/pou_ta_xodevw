# ══════════════════════════════════════════════════════════════
# ΠΡΟΣΘΕΣΕ ΑΥΤΟ στο app.py
# Βάλτο μετά το route /logout και πριν τα Dashboard routes
# ══════════════════════════════════════════════════════════════

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    """
    Profile settings page.
    Handles three form actions via a hidden 'action' field:
      - change_username  → validates + updates username
      - change_password  → validates current pw + sets new one
      - delete_account   → confirms password + wipes all user data
    All POST actions validate the CSRF token from the form body.
    """
    user_id  = get_current_user_id()
    db       = get_db()
    cursor   = db.cursor()
    success  = None
    error    = None

    if request.method == 'POST':

        # CSRF validation for all profile form actions
        if not validate_csrf_form():
            error = 'Σφάλμα ασφαλείας. Ανανέωσε τη σελίδα και δοκίμασε ξανά.'
            return _render_profile(user_id, success, error)

        action = request.form.get('action', '')

        # ── Change Username ──────────────────────────────────
        if action == 'change_username':
            new_username     = request.form.get('new_username', '').strip()
            confirm_password = request.form.get('confirm_password', '')

            # Verify the current password before allowing username change
            cursor.execute("SELECT * FROM users WHERE id=?", (user_id,))
            user = cursor.fetchone()
            if not user or hash_password(confirm_password, user['salt']) != user['password_hash']:
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
                    # Update session so the sidebar shows the new name immediately
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

            if not user or hash_password(current_password, user['salt']) != user['password_hash']:
                error = 'Ο τρέχων κωδικός είναι λάθος.'
            elif not is_valid_password(new_password):
                error = 'Νέος κωδικός: 8+, κεφαλαίο, αριθμό, σύμβολο.'
            elif new_password != confirm_new_password:
                error = 'Οι νέοι κωδικοί δεν ταιριάζουν.'
            elif new_password == current_password:
                error = 'Ο νέος κωδικός είναι ίδιος με τον παλιό.'
            else:
                # Generate a fresh salt on every password change
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

            if not user or hash_password(delete_password, user['salt']) != user['password_hash']:
                error = 'Λάθος κωδικός. Ο λογαριασμός δεν διαγράφηκε.'
            else:
                # Cascade delete: remove everything that belongs to this user
                # Order matters: transactions → fixed_payments → months → budgets → fixed_expenses → users

                # Get all month IDs for this user
                cursor.execute("SELECT id FROM months WHERE user_id=?", (user_id,))
                month_ids = [row['id'] for row in cursor.fetchall()]

                for mid in month_ids:
                    cursor.execute("DELETE FROM fixed_payments WHERE month_id=?", (mid,))
                    cursor.execute("DELETE FROM transactions WHERE month_id=?", (mid,))

                cursor.execute("DELETE FROM months WHERE user_id=?", (user_id,))
                cursor.execute("DELETE FROM budgets WHERE user_id=?", (user_id,))

                # Get all fixed expense IDs for this user and delete their payments
                cursor.execute("SELECT id FROM fixed_expenses WHERE user_id=?", (user_id,))
                fe_ids = [row['id'] for row in cursor.fetchall()]
                for fid in fe_ids:
                    cursor.execute("DELETE FROM fixed_payments WHERE fixed_expense_id=?", (fid,))

                cursor.execute("DELETE FROM fixed_expenses WHERE user_id=?", (user_id,))
                cursor.execute("DELETE FROM users WHERE id=?", (user_id,))
                db.commit()

                logger.info("User %s deleted their account", user_id)

                # Clear session and redirect to login
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
        """SELECT COUNT(*) FROM transactions t
           JOIN months m ON t.month_id = m.id
           WHERE m.user_id=?""",
        (user_id,)
    )
    total_transactions = cursor.fetchone()[0]

    cursor.execute(
        "SELECT * FROM months WHERE user_id=? ORDER BY year DESC, month DESC",
        (user_id,)
    )
    all_months = cursor.fetchall()

    return render_template('profile.html',
        username=user['username'],
        created_at=user['created_at'],
        total_months=total_months,
        total_transactions=total_transactions,
        all_months=all_months,
        greek_months=GREEK_MONTHS,
        success=success,
        error=error,
        **get_common_template_vars()
    )


# ══════════════════════════════════════════════════════════════
# ΠΡΟΣΘΕΣΕ ΑΥΤΟ στο base.html sidebar nav
# Βάλτο μετά το logout button στο sidebar-user div:
#
#   <a href="{{ url_for('profile') }}" class="profile-nav-btn" title="Προφίλ">⚙</a>
#
# ══════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════
# ΠΡΟΣΘΕΣΕ ΑΥΤΟ στο style.css (στο τέλος του αρχείου)
# ══════════════════════════════════════════════════════════════

PROFILE_CSS = """
/* ── Profile Page ─────────────────────────────────────────── */
.profile-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px;
    align-items: start;
}
.profile-card { }
.profile-form { display: flex; flex-direction: column; }
.profile-info-body { padding: 8px 0 4px; }
.profile-info-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 10px 16px;
    border-bottom: 1px solid var(--border-subtle);
    font-size: 13px;
}
.profile-info-row:last-child { border-bottom: none; }
.profile-info-label { color: var(--text-muted); font-size: 12px; }
.profile-info-val   { font-weight: 500; }

/* Danger zone card */
.profile-danger-card { border-left: 3px solid var(--expense); }
.profile-danger-body {
    padding: 14px 16px 16px;
    display: flex;
    flex-direction: column;
    gap: 10px;
    font-size: 13px;
    color: var(--text-secondary);
}

/* Danger button */
.btn-danger {
    background: var(--expense);
    color: white;
    border-color: var(--expense);
}
.btn-danger:hover { background: #a01010; border-color: #a01010; }

/* Profile gear icon in sidebar */
.profile-nav-btn {
    font-size: 13px;
    color: var(--text-muted);
    text-decoration: none;
    padding: 2px 4px;
    border-radius: 4px;
    transition: all 0.12s;
}
.profile-nav-btn:hover { color: var(--text-primary); background: var(--bg); }

@media (max-width: 768px) {
    .profile-grid { grid-template-columns: 1fr; }
}
"""
