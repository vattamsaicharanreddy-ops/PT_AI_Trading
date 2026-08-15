
import os
import sqlite3
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2 import pool

DATABASE_URL = os.getenv("DATABASE_URL")
USE_POSTGRES = DATABASE_URL is not None

pg_pool = None
if USE_POSTGRES:
    try:
        pg_pool = pool.SimpleConnectionPool(1, 20, dsn=DATABASE_URL)
        print("✅ Postgres pool created")
    except Exception as e:
        print(f"❌ Postgres pool error: {e}")
        USE_POSTGRES = False

SQLITE_PATH = "/data/bot.db" if os.path.exists("/data") else "bot.db"

def get_conn():
    if USE_POSTGRES and pg_pool:
        return pg_pool.getconn()
    else:
        conn = sqlite3.connect(SQLITE_PATH, check_same_thread=False, isolation_level=None)
        conn.row_factory = sqlite3.Row
        return conn

def put_conn(conn):
    if USE_POSTGRES and pg_pool:
        pg_pool.putconn(conn)
    else:
        conn.close()

def get_cursor(conn):
    """Return mapping rows on both supported database engines."""
    return conn.cursor(cursor_factory=RealDictCursor) if USE_POSTGRES else conn.cursor()

def init_db():
    conn = get_conn()
    try:
        if USE_POSTGRES:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    username TEXT,
                    balance DOUBLE PRECISION DEFAULT 0,
                    withdrawable DOUBLE PRECISION DEFAULT 0,
                    profit DOUBLE PRECISION DEFAULT 0,
                    profit_per_hour DOUBLE PRECISION DEFAULT 0,
                    daily_percent DOUBLE PRECISION DEFAULT 0,
                    ai_start TEXT,
                    ai_end TEXT,
                    last_claim TEXT,
                    last_auto_claim TEXT,
                    total_deposit DOUBLE PRECISION DEFAULT 0,
                    total_withdraw DOUBLE PRECISION DEFAULT 0,
                    current_tier INTEGER DEFAULT 7,
                    referred_by BIGINT,
                    referral_earnings DOUBLE PRECISION DEFAULT 0,
                    created_at TEXT,
                    last_withdraw_date TEXT,
                    is_banned INTEGER DEFAULT 0
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS deposits (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    amount DOUBLE PRECISION,
                    network TEXT,
                    tx_hash TEXT,
                    status TEXT DEFAULT 'awaiting_payment',
                    actual_amount DOUBLE PRECISION DEFAULT 0,
                    verified_at TEXT,
                    created_at TEXT,
                    expires_at TEXT,
                    invoice_id TEXT,
                    expected_amount DOUBLE PRECISION
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS withdrawals (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    amount DOUBLE PRECISION,
                    address TEXT,
                    network TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TEXT,
                    auto_approved INTEGER DEFAULT 0,
                    tx_hash TEXT,
                    admin_note TEXT
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS referral_logs (
                    id SERIAL PRIMARY KEY,
                    from_user BIGINT,
                    to_user BIGINT,
                    level INTEGER,
                    deposit_amount DOUBLE PRECISION,
                    bonus_amount DOUBLE PRECISION,
                    bonus_percent DOUBLE PRECISION,
                    created_at TEXT
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS used_tx_hashes (
                    tx_hash TEXT PRIMARY KEY,
                    used_at TEXT
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS withdrawal_announcements (
                    id SERIAL PRIMARY KEY,
                    withdrawal_id INTEGER,
                    tx_hash TEXT,
                    posted_at TEXT
                )
            """)
            conn.commit()
            cur.close()
        else:
            conn.execute("""CREATE TABLE IF NOT EXISTS users (
             user_id INTEGER PRIMARY KEY, username TEXT,
             balance REAL DEFAULT 0, withdrawable REAL DEFAULT 0, profit REAL DEFAULT 0,
             profit_per_hour REAL DEFAULT 0, daily_percent REAL DEFAULT 0,
             ai_start TEXT, ai_end TEXT, last_claim TEXT, last_auto_claim TEXT,
             total_deposit REAL DEFAULT 0, total_withdraw REAL DEFAULT 0,
             current_tier INTEGER DEFAULT 7, referred_by INTEGER, referral_earnings REAL DEFAULT 0,
             created_at TEXT, last_withdraw_date TEXT, is_banned INTEGER DEFAULT 0
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS deposits (
             id INTEGER PRIMARY KEY AUTOINCREMENT,
             user_id INTEGER, amount REAL, network TEXT, tx_hash TEXT,
             status TEXT DEFAULT 'awaiting_payment', actual_amount REAL DEFAULT 0,
             verified_at TEXT, created_at TEXT, expires_at TEXT,
             invoice_id TEXT, expected_amount REAL
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS withdrawals (
             id INTEGER PRIMARY KEY AUTOINCREMENT,
             user_id INTEGER, amount REAL, address TEXT, network TEXT,
             status TEXT DEFAULT 'pending', created_at TEXT, auto_approved INTEGER DEFAULT 0,
             tx_hash TEXT, admin_note TEXT
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS referral_logs (
             id INTEGER PRIMARY KEY AUTOINCREMENT,
             from_user INTEGER, to_user INTEGER, level INTEGER,
             deposit_amount REAL, bonus_amount REAL, bonus_percent REAL, created_at TEXT
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS used_tx_hashes (
             tx_hash TEXT PRIMARY KEY, used_at TEXT
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS withdrawal_announcements (
             id INTEGER PRIMARY KEY AUTOINCREMENT,
             withdrawal_id INTEGER, tx_hash TEXT, posted_at TEXT
            )""")
            conn.commit()
        # Keep existing installations compatible when a previous release created
        # an older version of one of these tables.
        migrations = {
            "users": [
                ("username", "TEXT"), ("referral_earnings", "DOUBLE PRECISION DEFAULT 0"),
                ("created_at", "TEXT"), ("last_withdraw_date", "TEXT"), ("is_banned", "INTEGER DEFAULT 0"),
            ],
            "deposits": [
                ("actual_amount", "DOUBLE PRECISION DEFAULT 0"), ("verified_at", "TEXT"),
                ("expires_at", "TEXT"), ("invoice_id", "TEXT"), ("expected_amount", "DOUBLE PRECISION"),
            ],
            "withdrawals": [("auto_approved", "INTEGER DEFAULT 0"), ("tx_hash", "TEXT"), ("admin_note", "TEXT")],
            "referral_logs": [("bonus_percent", "DOUBLE PRECISION")],
        }
        if USE_POSTGRES:
            cur = conn.cursor()
            for table, columns in migrations.items():
                for name, definition in columns:
                    cur.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {name} {definition}")
            conn.commit()
            cur.close()
        else:
            for table, columns in migrations.items():
                existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
                for name, definition in columns:
                    if name not in existing:
                        conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition.replace('DOUBLE PRECISION', 'REAL')}")
            conn.commit()
        print(f"✅ Database ready: {'POSTGRES' if USE_POSTGRES else 'SQLITE at '+SQLITE_PATH}")
    finally:
        put_conn(conn)
