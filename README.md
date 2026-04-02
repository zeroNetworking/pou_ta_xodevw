# Finance Manager

Personal finance tracking application built with Flask and SQLite. Tracks monthly income and expenses with accounting-period logic, budget alerts, recurring fixed expenses, and a calendar ledger view.

---

## What This App Does

Finance Manager is not a simple expense tracker. It implements proper **accounting period logic**:

- Each month is an isolated **accounting period** that can be open or closed
- Closed months are **immutable** — no direct edits allowed
- Forgotten transactions from a closed month are added via **Late Entry** from an open month (with a timestamp and note)
- **Recurring fixed expenses** (rent, subscriptions) are defined once and tracked per month as paid/unpaid
- **Budget limits** per category with alerts at 75%, 90%, and 100%
- Full **analytics** across all months with charts
- **Calendar ledger** view showing transactions per day
- **Search** across all transactions (category, subcategory, description)

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3, Flask |
| Database | SQLite (via raw SQL) |
| Frontend | Jinja2 templates, vanilla JS, Chart.js |
| Auth | Session-based, PBKDF2-SHA256 password hashing |
| Security | CSRF tokens, rate limiting, ownership checks |
| Styling | Custom CSS (DM Sans + DM Mono fonts) |

---

## Project Structure

```
finance_manager/
├── app.py                  # Main Flask application (all routes, logic, helpers)
├── database.db             # SQLite database (auto-created on first run)
├── finance_app.log         # Application log file (auto-created)
├── requirements.txt        # Python dependencies
├── README.md
│
├── templates/
│   ├── base.html           # Base layout: sidebar, modals, bottom nav
│   ├── index.html          # Dashboard — month cards grid
│   ├── month.html          # Month detail — transactions, form, chart
│   ├── analytics.html      # Analytics — charts, per-month table
│   ├── calendar.html       # Calendar ledger view
│   ├── search.html         # Search results
│   ├── login.html          # Login page
│   └── register.html       # Registration page
│
└── static/
    ├── css/
    │   └── style.css       # All application styles
    └── js/
        └── main.js         # Shared JS: clock, modals, privacy toggle, drawer
```

---

## Database Schema

```
users
  id, username (UNIQUE), password_hash, salt, created_at

months
  id, user_id → users, year, month, name
  is_closed (0/1), closed_at
  UNIQUE(user_id, year, month)

transactions
  id, month_id → months, category, subcategory
  type (income/expense), amount, description
  transaction_date, late_entry (0/1), late_entry_note
  created_at

budgets
  id, user_id → users, category, amount
  UNIQUE(user_id, category)

fixed_expenses
  id, user_id → users, label, amount, category, sort_order

fixed_payments
  id, fixed_expense_id → fixed_expenses, month_id → months
  paid (0/1), paid_at
  UNIQUE(fixed_expense_id, month_id)
```

---

## How to Run (Development)

### 1. Clone and install dependencies

```bash
git clone <repo-url>
cd finance_manager
pip install flask
```

### 2. Set the secret key (important)

```bash
# Linux / macOS
export SECRET_KEY="your-random-secret-key-here"

# Windows
set SECRET_KEY=your-random-secret-key-here
```

Never use the default key in production. The app will print a warning if you do.

### 3. Run

```bash
python app.py
```

The app starts on `http://localhost:5000`. The database is created automatically on first run.

---

## Security Features

### Password Hashing
PBKDF2-SHA256 with 200,000 iterations and a unique random salt per user. This is production-level hashing strength.

### CSRF Protection
A session-bound CSRF token is generated for every session and validated on HTML form POST requests. It is exposed to Jinja2 templates globally via `csrf_token()`.

### Rate Limiting (Login)
Login attempts are rate-limited per IP address: 10 failed attempts within 5 minutes triggers a lockout. This is in-memory (resets on server restart). For production, use Redis-backed rate limiting.

### Ownership Validation (IDOR Prevention)
Every write operation (edit, delete, close) validates that the resource belongs to the logged-in user via a JOIN check:

```sql
SELECT t.id FROM transactions t
JOIN months m ON t.month_id = m.id
WHERE t.id = ? AND m.user_id = ?
```

This prevents Insecure Direct Object Reference (IDOR) attacks where a user could manipulate another user's data.

### Session Secret Key
Read from `SECRET_KEY` environment variable. Never hardcoded. The app warns at startup if using the default dev key.

---

## Key Concepts

### Accounting Periods
Each month is an independent accounting period. When a month's last day passes (23:59:59), it is automatically closed on the next page load. Closed months are read-only.

### Late Entry
If a transaction from a past closed month was missed, it can be added from an open month using the Late Entry form. The transaction is stored in the closed month's `month_id` with `late_entry=1` and a note explaining why it was late.

### Fixed Expenses
Recurring bills (rent, electricity, gym) are defined once in `fixed_expenses`. Each month, the user marks them as paid. Toggling paid status automatically adds or removes the corresponding transaction from the month.

### Budget Alerts
Budget limits are set per expense category. Alerts are generated at 75% (info), 90% (warning), and 100% (danger). A global alert also fires if total expenses reach 90% or 100% of total income.

### Privacy Mode
A privacy toggle in the sidebar blurs all monetary values on screen using CSS `filter: blur()`. The preference is saved in `localStorage` and persists across page navigation.

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/api/month_stats/<month_id>` | Income/expense/balance for one month (JSON) |
| GET | `/api/now` | Current server time and month name (JSON) |

---

## Known Limitations & Future Work

| Area | Current State | Future Improvement |
|---|---|---|
| Architecture | Single `app.py` file | Split into modules: `auth/`, `months/`, `transactions/`, `services/` |
| Database | SQLite, raw SQL | PostgreSQL + SQLAlchemy |
| Auth | Session cookies | JWT tokens |
| Rate limiting | In-memory (resets on restart) | Redis-backed (persistent) |
| CSRF | HTML forms only | Headers for JSON API calls |
| Session expiry | No expiration set | `PERMANENT_SESSION_LIFETIME` |
| DB indexes | None | Add indexes on `user_id`, `month_id`, `transaction_date` |
| Background jobs | `close_expired_months` runs on page load | Celery background task |
| Tests | None | Unit tests for services and routes |
| Deployment | `debug=True` | Gunicorn + Nginx + Docker |
| Password reset | Not implemented | Email-based reset flow |

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `SECRET_KEY` | Yes (production) | Flask session signing key. Use a long random string. |

---

## Logging

All events are written to `finance_app.log` and printed to the console. Logged events include:

- Successful and failed login attempts (with IP address)
- Month close events
- Unauthorized access attempts (ownership violations)
- App startup

---

## License

Personal project. All rights reserved.
