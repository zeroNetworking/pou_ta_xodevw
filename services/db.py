"""
Database Module
Flask g-based connection management with automatic teardown.
All services import get_db() from here.
"""

import sqlite3
import os
from flask import g


def _resolve_db_path():
    """Finds the database file. Priority: env var > data/ > project root."""
    if os.environ.get('DATABASE_PATH'):
        return os.environ['DATABASE_PATH']
    project_root = os.path.dirname(os.path.dirname(__file__))
    data_path = os.path.join(project_root, 'data', 'database.db')
    if os.path.isfile(data_path):
        return data_path
    root_path = os.path.join(project_root, 'database.db')
    if os.path.isfile(root_path):
        return root_path
    data_dir = os.path.join(project_root, 'data')
    if os.path.isdir(data_dir):
        return data_path
    return root_path


DB_PATH = _resolve_db_path()


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


def _repair_stale_references(db, cursor):
    """
    Repairs tables that have stale foreign key references to _months_old.
    This happens when a previous migration crashed mid-way.
    Rebuilds affected tables with corrected schema while preserving data.
    """
    # Find all tables with _months_old references
    cursor.execute("SELECT name, sql FROM sqlite_master WHERE type='table'")
    all_tables = cursor.fetchall()

    broken_tables = []
    has_months_old = False
    for row in all_tables:
        if row['name'] == '_months_old':
            has_months_old = True
        if row['sql'] and '_months_old' in row['sql']:
            broken_tables.append((row['name'], row['sql']))

    if not broken_tables and not has_months_old:
        return  # Nothing to fix

    print(f"DB REPAIR: Found {len(broken_tables)} broken table(s), _months_old exists: {has_months_old}")

    cursor.execute("PRAGMA foreign_keys = OFF")

    # Fix broken tables by rebuilding with corrected schema
    for table_name, old_sql in broken_tables:
        new_sql = old_sql.replace('_months_old', 'months')
        try:
            cursor.execute(f"SELECT * FROM {table_name}")
            rows = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description]

            cursor.execute(f"DROP TABLE {table_name}")
            cursor.execute(new_sql)

            if rows:
                placeholders = ','.join('?' * len(columns))
                col_names = ','.join(columns)
                for row in rows:
                    try:
                        cursor.execute(
                            f"INSERT INTO {table_name} ({col_names}) VALUES ({placeholders})",
                            tuple(row)
                        )
                    except Exception:
                        pass  # Skip duplicates

            print(f"DB REPAIR: Rebuilt {table_name} ({len(rows)} rows)")
        except Exception as e:
            print(f"DB REPAIR WARNING: Failed to rebuild {table_name}: {e}")

    # Handle leftover _months_old table
    if has_months_old:
        try:
            # Check if months table exists and has data
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='months'")
            months_exists = cursor.fetchone() is not None

            if months_exists:
                cursor.execute("SELECT COUNT(*) FROM months")
                months_count = cursor.fetchone()[0]
            else:
                months_count = 0

            cursor.execute("SELECT COUNT(*) FROM _months_old")
            old_count = cursor.fetchone()[0]

            if old_count > 0 and months_count == 0:
                if months_exists:
                    cursor.execute("DROP TABLE months")
                cursor.execute("ALTER TABLE _months_old RENAME TO months")
                print(f"DB REPAIR: Recovered {old_count} months from _months_old")
            else:
                cursor.execute("DROP TABLE _months_old")
                print("DB REPAIR: Cleaned up empty _months_old")
        except Exception as e:
            print(f"DB REPAIR WARNING: _months_old cleanup failed: {e}")

    cursor.execute("PRAGMA foreign_keys = ON")
    db.commit()


def init_db():
    """
    Creates all tables and performance indexes.
    Also repairs stale migration leftovers and runs safe schema upgrades.
    Called once at app startup from __main__.
    """
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    cursor = db.cursor()

    # Step 1: Repair any stale _months_old references FIRST
    _repair_stale_references(db, cursor)

    # Step 2: Create tables (IF NOT EXISTS — safe for existing DBs)
    cursor.execute("PRAGMA foreign_keys = ON")

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            salt          TEXT NOT NULL,
            created_at    TEXT DEFAULT CURRENT_TIMESTAMP
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

    # Step 3: Performance indexes
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_months_user        ON months(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_transactions_month ON transactions(month_id)",
        "CREATE INDEX IF NOT EXISTS idx_transactions_date  ON transactions(transaction_date)",
        "CREATE INDEX IF NOT EXISTS idx_transactions_cat   ON transactions(category)",
        "CREATE INDEX IF NOT EXISTS idx_fixed_user         ON fixed_expenses(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_transactions_month_type ON transactions(month_id, type)",
        "CREATE INDEX IF NOT EXISTS idx_months_user_year_month  ON months(user_id, year, month)",
    ]
    for idx in indexes:
        try:
            cursor.execute(idx)
        except Exception:
            pass

    # Step 4: Safe column migrations for older installations
    for table, column, definition in [
        ('transactions', 'subcategory',     'TEXT'),
        ('transactions', 'late_entry',      'INTEGER DEFAULT 0'),
        ('transactions', 'late_entry_note', 'TEXT'),
    ]:
        try:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        except Exception:
            pass

    # Step 5: Fix UNIQUE constraint on months if schema is outdated
    # Only attempt if _months_old does NOT exist (we already handled that above)
    try:
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='_months_old'")
        if not cursor.fetchone():
            cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='months'")
            schema_row = cursor.fetchone()
            if schema_row and schema_row['sql'] and 'UNIQUE(user_id, year, month)' not in schema_row['sql']:
                cursor.execute("PRAGMA foreign_keys = OFF")
                cursor.execute("ALTER TABLE months RENAME TO _months_old")
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
                    INSERT OR IGNORE INTO months (id, user_id, year, month, name, is_closed, closed_at, created_at)
                    SELECT id, user_id, year, month, name, is_closed, closed_at, created_at
                    FROM _months_old
                ''')
                cursor.execute("DROP TABLE _months_old")
                cursor.execute("PRAGMA foreign_keys = ON")
                db.commit()
    except Exception as e:
        print(f"WARNING: months schema upgrade failed: {e}")
        # Recovery: rename back if possible
        try:
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='_months_old'")
            if cursor.fetchone():
                cursor.execute("DROP TABLE IF EXISTS months")
                cursor.execute("ALTER TABLE _months_old RENAME TO months")
                db.commit()
        except Exception:
            pass

    db.commit()
    db.close()
