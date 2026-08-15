
import os
import sqlite3
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2 import pool

DATABASE_URL = os.getenv("DATABASE_URL")
USE_POSTGRES = DATABASE_URL is not None and DATABASE_URL != ""

pg_pool = None
if USE_POSTGRES:
    try:
        pg_pool = pool.SimpleConnectionPool(1, 20, dsn=DATABASE_URL)
        print("✅ Postgres pool created")
    except Exception as e:
        print(f"❌ Postgres pool error: {e}")
        USE_POSTGRES = False

SQLITE_PATH = os.getenv("SQLITE_PATH", "/data/bot.db" if os.path.exists("/data") else "bot.db")

def get_conn():
    if USE_POSTGRES and pg_pool:
        return pg_pool.getconn()
    else:
        conn = sqlite3.connect(SQLITE_PATH, check_same_thread=False, isolation_level=None, timeout=30)
        conn.row_factory = sqlite3.Row
        # WAL mode for concurrency
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
        except: pass
        return conn

def put_conn(conn):
    if USE_POSTGRES and pg_pool:
        pg_pool.putconn(conn)
    else:
        try: conn.close()
        except: pass

def get_cursor(conn):
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
                    invoice_id TEXT UNIQUE,
                    expected_amount DOUBLE PRECISION,
                    admin_note TEXT
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
            cur.execute("""
                CREATE TABLE IF NOT EXISTS group_members (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    username TEXT,
                    group_name TEXT,
                    group_id TEXT,
                    method TEXT,
                    status TEXT DEFAULT 'added',
                    invite_link TEXT,
                    created_at TEXT DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id SERIAL PRIMARY KEY,
                    title TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    group_link TEXT NOT NULL,
                    group_id TEXT NOT NULL,
                    group_username TEXT DEFAULT '',
                    reward DOUBLE PRECISION DEFAULT 1,
                    reward_type TEXT DEFAULT 'withdrawable',
                    is_active INTEGER DEFAULT 1,
                    is_mandatory INTEGER DEFAULT 1,
                    icon TEXT DEFAULT '🚀',
                    sort_order INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_tasks (
                    user_id BIGINT,
                    task_id INTEGER,
                    status TEXT DEFAULT 'pending',
                    verified_at TEXT,
                    reward_claimed INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT NOW(),
                    PRIMARY KEY (user_id, task_id)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS admin_logs (
                    id SERIAL PRIMARY KEY,
                    admin_action TEXT,
                    target_user_id BIGINT,
                    details TEXT,
                    created_at TEXT DEFAULT NOW()
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_deposits_status ON deposits(status)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_deposits_invoice ON deposits(invoice_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_users_referred ON users(referred_by)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_withdrawals_user ON withdrawals(user_id)")
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
             invoice_id TEXT UNIQUE, expected_amount REAL, admin_note TEXT
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
            conn.execute("""CREATE TABLE IF NOT EXISTS group_members (
             id INTEGER PRIMARY KEY AUTOINCREMENT,
             user_id INTEGER, username TEXT, group_name TEXT, group_id TEXT,
             method TEXT, status TEXT DEFAULT 'added', invite_link TEXT, created_at TEXT
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS tasks (
             id INTEGER PRIMARY KEY AUTOINCREMENT,
             title TEXT NOT NULL, description TEXT DEFAULT '', group_link TEXT NOT NULL,
             group_id TEXT NOT NULL, group_username TEXT DEFAULT '', reward REAL DEFAULT 1,
             reward_type TEXT DEFAULT 'withdrawable', is_active INTEGER DEFAULT 1,
             is_mandatory INTEGER DEFAULT 1, icon TEXT DEFAULT '🚀', sort_order INTEGER DEFAULT 0,
             created_at TEXT
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS user_tasks (
             user_id INTEGER, task_id INTEGER, status TEXT DEFAULT 'pending',
             verified_at TEXT, reward_claimed INTEGER DEFAULT 0, created_at TEXT,
             PRIMARY KEY (user_id, task_id)
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS admin_logs (
             id INTEGER PRIMARY KEY AUTOINCREMENT, admin_action TEXT,
             target_user_id INTEGER, details TEXT, created_at TEXT
            )""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_deposits_status ON deposits(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_deposits_invoice ON deposits(invoice_id)")
            conn.commit()
        print(f"✅ Database ready: {'POSTGRES' if USE_POSTGRES else 'SQLITE at '+SQLITE_PATH}")
    finally:
        put_conn(conn)
