# ══════════════════════════════════════════════════════════════
# ΠΡΟΣΘΕΣΕ ΑΥΤΟ στο app.py — μαζί με τον export_month_csv route
# (στην ενότητα Routes — Export)
# ══════════════════════════════════════════════════════════════

@app.route('/export/month/<int:month_id>/pdf')
@login_required
def export_month_pdf(month_id):
    """
    Generates and downloads a full monthly PDF report.
    Includes: summary stats, category bar chart, fixed expenses
    payment status, and the complete transaction list.
    """
    from services.pdf_report import generate_month_pdf

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
    filename  = f"finance_{safe_name}.pdf"
    logger.info("User %s exported month %s as PDF", user_id, month_id)

    return Response(
        pdf_bytes,
        mimetype='application/pdf',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'}
    )