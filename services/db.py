"""
Database Module
Flask g-based connection management with automatic teardown.
All services import get_db() from here.
"""

import sqlite3
import os
from flask import g

DB_PATH = os.environ.get(
    'DATABASE_PATH',
    os.path.join(os.path.dirname(os.path.dirname(__file__)), 'database.db')
)


def get_db():
    """
    Returns the DB connection for the current request context.
    Creates it once per request and stores it in Flask's g object.
    Foreign key enforcement is enabled by default.
    """
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def init_db():
    """
    Creates all tables and performance indexes.
    Also includes CHECK constraints (item 5) so the DB enforces data integrity
    even if application-level validation has a bug.
    Called once at app startup from __main__.
    Uses a direct connection (not g) since this runs before any request context.
    """
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    cursor = db.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            username             TEXT NOT NULL UNIQUE,
            password_hash        TEXT NOT NULL,
            salt                 TEXT NOT NULL,
            recovery_question    TEXT,
            recovery_answer_hash TEXT,
            recovery_answer_salt TEXT,
            created_at           TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS months (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL,
            year       INTEGER NOT NULL CHECK(year >= 2000 AND year <= 2100),
            month      INTEGER NOT NULL CHECK(month >= 1 AND month <= 12),
            name       TEXT NOT NULL,
            is_closed  INTEGER DEFAULT 0 CHECK(is_closed IN (0, 1)),
            closed_at  TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, year, month),
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    ''')

    # FIX #5 — DB CHECK constraints: enforce business rules at the database level
    # Even if application code has a bug, the DB will reject invalid data
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            month_id         INTEGER NOT NULL,
            category         TEXT NOT NULL,
            subcategory      TEXT,
            type             TEXT NOT NULL CHECK(type IN ('income', 'expense')),
            amount           REAL NOT NULL CHECK(amount >= 0),
            description      TEXT,
            transaction_date TEXT NOT NULL,
            late_entry       INTEGER DEFAULT 0 CHECK(late_entry IN (0, 1)),
            late_entry_note  TEXT,
            created_at       TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(month_id) REFERENCES months(id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS budgets (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id  INTEGER NOT NULL,
            category TEXT NOT NULL,
            amount   REAL DEFAULT 0 CHECK(amount >= 0),
            UNIQUE(user_id, category),
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS fixed_expenses (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL,
            label      TEXT NOT NULL,
            amount     REAL DEFAULT 0 CHECK(amount >= 0),
            category   TEXT,
            sort_order INTEGER DEFAULT 0,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS fixed_payments (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            fixed_expense_id INTEGER NOT NULL,
            month_id         INTEGER NOT NULL,
            paid             INTEGER DEFAULT 0 CHECK(paid IN (0, 1)),
            paid_at          TEXT,
            UNIQUE(fixed_expense_id, month_id)
        )
    ''')

    # FIX #5 — Performance indexes (original 5 + 2 new composite indexes)
    indexes = [
        # Original indexes
        "CREATE INDEX IF NOT EXISTS idx_months_user        ON months(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_transactions_month ON transactions(month_id)",
        "CREATE INDEX IF NOT EXISTS idx_transactions_date  ON transactions(transaction_date)",
        "CREATE INDEX IF NOT EXISTS idx_transactions_cat   ON transactions(category)",
        "CREATE INDEX IF NOT EXISTS idx_fixed_user         ON fixed_expenses(user_id)",
        # FIX #3 (extra) — 2 new composite indexes from the review
        # Speeds up: SELECT ... WHERE month_id=? AND type='expense/income'
        "CREATE INDEX IF NOT EXISTS idx_transactions_month_type ON transactions(month_id, type)",
        # Speeds up: SELECT ... WHERE user_id=? AND year=? AND month=?
        "CREATE INDEX IF NOT EXISTS idx_months_user_year_month  ON months(user_id, year, month)",
    ]
    for idx in indexes:
        cursor.execute(idx)

    # Safe migration for older installations that may be missing columns
    for table, column, definition in [
        ('transactions', 'subcategory',     'TEXT'),
        ('transactions', 'late_entry',      'INTEGER DEFAULT 0'),
        ('transactions', 'late_entry_note', 'TEXT'),
        # Password recovery columns — added later, must be nullable so existing
        # users keep working until they set up their recovery question.
        ('users', 'recovery_question',    'TEXT'),
        ('users', 'recovery_answer_hash', 'TEXT'),
        ('users', 'recovery_answer_salt', 'TEXT'),
    ]:
        try:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        except Exception:
            pass

    # Migration: fix old databases where UNIQUE constraint was (year, month)
    # instead of (user_id, year, month). Check by trying to inspect the schema.
    try:
        cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='months'")
        schema = cursor.fetchone()
        if schema and 'UNIQUE(user_id, year, month)' not in schema[0]:
            # Old schema detected — recreate the table with correct constraint
            # Use a transaction so we can rollback if anything goes wrong
            cursor.execute("ALTER TABLE months RENAME TO _months_old")
            try:
                cursor.execute('''
                    CREATE TABLE months (
                        id         INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id    INTEGER NOT NULL,
                        year       INTEGER NOT NULL CHECK(year >= 2000 AND year <= 2100),
                        month      INTEGER NOT NULL CHECK(month >= 1 AND month <= 12),
                        name       TEXT NOT NULL,
                        is_closed  INTEGER DEFAULT 0 CHECK(is_closed IN (0, 1)),
                        closed_at  TEXT,
                        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(user_id, year, month),
                        FOREIGN KEY(user_id) REFERENCES users(id)
                    )
                ''')
                cursor.execute('''
                    INSERT INTO months (id, user_id, year, month, name, is_closed, closed_at, created_at)
                    SELECT id, user_id, year, month, name, is_closed, closed_at, created_at
                    FROM _months_old
                ''')
                cursor.execute("DROP TABLE _months_old")
                # Recreate indexes
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_months_user ON months(user_id)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_months_user_year_month ON months(user_id, year, month)")
            except Exception as migration_err:
                # Rollback: restore original table if migration failed
                import logging as _log
                _log.getLogger(__name__).error("Months migration failed, rolling back: %s", migration_err)
                try:
                    cursor.execute("DROP TABLE IF EXISTS months")
                    cursor.execute("ALTER TABLE _months_old RENAME TO months")
                except Exception:
                    pass
    except Exception:
        pass

    db.commit()
    db.close()


def wipe_user_data(db, user_id: int) -> None:
    """
    Deletes a user and ALL their data, in the correct order to satisfy
    foreign key constraints.

    Caller must commit. Caller must own the connection (typically via get_db()).
    Replaces ~15 lines of inline DELETE statements that used to live in the
    profile route — keeps deletion logic in one place so it stays consistent.
    """
    cursor = db.cursor()

    # Get the user's months + fixed expenses up-front so we can clean up
    # their child rows (transactions, fixed_payments) before removing parents.
    cursor.execute("SELECT id FROM months WHERE user_id=?", (user_id,))
    month_ids = [row['id'] for row in cursor.fetchall()]

    cursor.execute("SELECT id FROM fixed_expenses WHERE user_id=?", (user_id,))
    fixed_expense_ids = [row['id'] for row in cursor.fetchall()]

    # Children of months
    for month_id in month_ids:
        cursor.execute("DELETE FROM fixed_payments WHERE month_id=?", (month_id,))
        cursor.execute("DELETE FROM transactions   WHERE month_id=?", (month_id,))

    # Children of fixed_expenses (in case some payments aren't linked to a month)
    for fixed_id in fixed_expense_ids:
        cursor.execute("DELETE FROM fixed_payments WHERE fixed_expense_id=?", (fixed_id,))

    # Parents — order matters: months & fixed_expenses reference users
    cursor.execute("DELETE FROM months         WHERE user_id=?", (user_id,))
    cursor.execute("DELETE FROM budgets        WHERE user_id=?", (user_id,))
    cursor.execute("DELETE FROM fixed_expenses WHERE user_id=?", (user_id,))
    cursor.execute("DELETE FROM users          WHERE id=?",      (user_id,))
