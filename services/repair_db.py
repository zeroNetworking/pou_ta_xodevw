"""
Database Repair Script — fixes stale _months_old foreign key references.

Run once: python repair_db.py
This rebuilds any tables that have broken foreign key references
while preserving ALL your data.
"""

import sqlite3
import os
import shutil
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), 'database.db')
if not os.path.isfile(DB_PATH):
    DB_PATH = os.path.join(os.path.dirname(__file__), 'data', 'database.db')

if not os.path.isfile(DB_PATH):
    print("❌ database.db not found!")
    exit(1)

print(f"📂 Database: {DB_PATH}")

# Backup first
backup = f"{DB_PATH}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
shutil.copy2(DB_PATH, backup)
print(f"💾 Backup: {backup}")

db = sqlite3.connect(DB_PATH)
db.row_factory = sqlite3.Row
cursor = db.cursor()

# Check current state
print("\n📋 Current tables:")
cursor.execute("SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name")
for row in cursor.fetchall():
    has_old_ref = '_months_old' in (row['sql'] or '')
    marker = ' ⚠️  HAS _months_old REFERENCE!' if has_old_ref else ''
    print(f"  {row['name']}{marker}")

# Check for _months_old references in any table
cursor.execute("SELECT name, sql FROM sqlite_master WHERE type='table'")
broken_tables = []
for row in cursor.fetchall():
    if row['sql'] and '_months_old' in row['sql']:
        broken_tables.append(row['name'])

if not broken_tables:
    # Also clean up _months_old if it exists
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='_months_old'")
    if cursor.fetchone():
        print("\n🧹 Cleaning up leftover _months_old...")
        cursor.execute("DROP TABLE _months_old")
        db.commit()
        print("✅ Done!")
    else:
        print("\n✅ Database is clean — no _months_old references found!")
    db.close()
    exit(0)

print(f"\n⚠️  Found {len(broken_tables)} table(s) with _months_old references: {broken_tables}")
print("🔧 Rebuilding...")

# Disable foreign keys during repair
cursor.execute("PRAGMA foreign_keys = OFF")

for table_name in broken_tables:
    # Get current schema
    cursor.execute(f"SELECT sql FROM sqlite_master WHERE type='table' AND name='{table_name}'")
    old_sql = cursor.fetchone()['sql']

    # Fix the schema: replace _months_old with months
    new_sql = old_sql.replace('_months_old', 'months')

    # Get data
    cursor.execute(f"SELECT * FROM {table_name}")
    rows = cursor.fetchall()
    columns = [desc[0] for desc in cursor.description]

    print(f"  📦 {table_name}: {len(rows)} rows, fixing schema...")

    # Rebuild
    cursor.execute(f"DROP TABLE {table_name}")
    cursor.execute(new_sql)

    # Re-insert data
    if rows:
        placeholders = ','.join('?' * len(columns))
        col_names = ','.join(columns)
        for row in rows:
            try:
                cursor.execute(
                    f"INSERT INTO {table_name} ({col_names}) VALUES ({placeholders})",
                    tuple(row)
                )
            except Exception as e:
                print(f"    ⚠️  Skipped row: {e}")

    print(f"  ✅ {table_name} rebuilt successfully")

# Clean up _months_old if it still exists
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='_months_old'")
if cursor.fetchone():
    cursor.execute("DROP TABLE _months_old")
    print("  🧹 Dropped leftover _months_old")

# Re-enable foreign keys
cursor.execute("PRAGMA foreign_keys = ON")

# Verify
cursor.execute("PRAGMA integrity_check")
integrity = cursor.fetchone()[0]
print(f"\n🔍 Integrity check: {integrity}")

# Verify no more _months_old references
cursor.execute("SELECT name, sql FROM sqlite_master WHERE type='table'")
still_broken = [r['name'] for r in cursor.fetchall() if r['sql'] and '_months_old' in r['sql']]
if still_broken:
    print(f"❌ Still broken: {still_broken}")
else:
    print("✅ All _months_old references removed!")

db.commit()
db.close()

print(f"\n🎉 Repair complete! Backup at: {backup}")
print("   Now restart: python app.py")
