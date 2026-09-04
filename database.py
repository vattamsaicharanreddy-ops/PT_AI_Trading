import os
import logging
import sqlite3
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2 import pool

logger = logging.getLogger("db")

DATABASE_URL = os.getenv("DATABASE_URL")
USE_POSTGRES = DATABASE_URL is not None

pg_pool = None
if USE_POSTGRES:
    try:
        pg_pool = pool.SimpleConnectionPool(1, 20, dsn=DATABASE_URL)
        logger.info("Postgres pool created")
    except Exception as e:
        logger.error(f"Postgres pool error: {e}")
        USE_POSTGRES = False

SQLITE_PATH = os.getenv(
    "APP_DB_PATH",
    "/data/bot.db" if os.path.exists("/data") else "bot.db",
)


def ph():
    return "%s" if USE_POSTGRES else "?"


def get_conn():
    if USE_POSTGRES and pg_pool:
        return pg_pool.getconn()
    else:
        conn = sqlite3.connect(SQLITE_PATH, check_same_thread=False, isolation_level=None)
        conn.row_factory = sqlite3.Row
        return conn


def put_conn(conn):
    if conn is None:
        return
    try:
        if USE_POSTGRES and pg_pool:
            pg_pool.putconn(conn)
        else:
            conn.close()
    except Exception as e:
        logger.warning(f"put_conn error: {e}")


def get_cursor(conn):
    return conn.cursor(cursor_factory=RealDictCursor) if USE_POSTGRES else conn.cursor()


def safe_close(conn):
    try:
        put_conn(conn)
    except Exception:
        pass


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
                    title TEXT,
                    description TEXT DEFAULT '',
                    group_link TEXT,
                    group_id TEXT,
                    group_username TEXT DEFAULT '',
                    reward DOUBLE PRECISION DEFAULT 1.0,
                    reward_type TEXT DEFAULT 'withdrawable',
                    is_active INTEGER DEFAULT 1,
                    is_mandatory INTEGER DEFAULT 1,
                    icon TEXT DEFAULT '',
                    sort_order INTEGER DEFAULT 0,
                    created_at TEXT
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_tasks (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    task_id INTEGER,
                    status TEXT DEFAULT 'pending',
                    verified_at TEXT,
                    reward_claimed INTEGER DEFAULT 0,
                    UNIQUE(user_id, task_id)
                )
            """)

            cur.execute("CREATE INDEX IF NOT EXISTS idx_deposits_status ON deposits(status)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_deposits_user ON deposits(user_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_deposits_invoice ON deposits(invoice_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_withdrawals_status ON withdrawals(status)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_withdrawals_user ON withdrawals(user_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_referral_logs_to ON referral_logs(to_user)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_user_tasks_user ON user_tasks(user_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_user_tasks_task ON user_tasks(task_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_user_tasks_lookup ON user_tasks(user_id, task_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_tasks_active ON tasks(is_active)")

            migrations = [
                "ALTER TABLE deposits ADD COLUMN IF NOT EXISTS admin_note TEXT",
                "ALTER TABLE withdrawals ADD COLUMN IF NOT EXISTS admin_note TEXT",
                "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS task_type TEXT DEFAULT 'join'",
                "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS task_config TEXT DEFAULT ''",
                "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS sort_order INTEGER DEFAULT 0",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_date TEXT DEFAULT ''",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS login_streak INTEGER DEFAULT 0",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_spin_date TEXT DEFAULT ''",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS total_games_played INTEGER DEFAULT 0",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS total_games_won INTEGER DEFAULT 0",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_webapp_open TEXT DEFAULT ''",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_nudge_at TEXT DEFAULT ''",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS admin_added_balance DOUBLE PRECISION DEFAULT 0",
            ]
            for m in migrations:
                try:
                    cur.execute(m)
                except Exception:
                    pass

            cur.execute("""CREATE TABLE IF NOT EXISTS game_history (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                game_type TEXT,
                bet DOUBLE PRECISION DEFAULT 0,
                result TEXT DEFAULT 'lost',
                payout DOUBLE PRECISION DEFAULT 0,
                choice TEXT DEFAULT '',
                details TEXT DEFAULT '',
                created_at TEXT DEFAULT NOW()
            )""")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_game_history_user ON game_history(user_id)")

            try:
                cur.execute("""CREATE TABLE IF NOT EXISTS saved_messages (
                    id SERIAL PRIMARY KEY,
                    title TEXT NOT NULL,
                    message TEXT NOT NULL,
                    photo_url TEXT DEFAULT '',
                    created_at TEXT
                )""")
            except Exception:
                pass

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
            conn.execute("""CREATE TABLE IF NOT EXISTS group_members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER, username TEXT, group_name TEXT, group_id TEXT,
                method TEXT, status TEXT DEFAULT 'added', invite_link TEXT, created_at TEXT
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT, description TEXT DEFAULT '', group_link TEXT,
                group_id TEXT, group_username TEXT DEFAULT '', reward REAL DEFAULT 1.0,
                reward_type TEXT DEFAULT 'withdrawable', is_active INTEGER DEFAULT 1,
                is_mandatory INTEGER DEFAULT 1, icon TEXT DEFAULT '', sort_order INTEGER DEFAULT 0,
                created_at TEXT
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS user_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER, task_id INTEGER, status TEXT DEFAULT 'pending',
                verified_at TEXT, reward_claimed INTEGER DEFAULT 0,
                UNIQUE(user_id, task_id)
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS saved_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                photo_url TEXT DEFAULT '',
                created_at TEXT
            )""")

            for stmt in [
                "CREATE INDEX IF NOT EXISTS idx_deposits_status ON deposits(status)",
                "CREATE INDEX IF NOT EXISTS idx_deposits_user ON deposits(user_id)",
                "CREATE INDEX IF NOT EXISTS idx_deposits_invoice ON deposits(invoice_id)",
                "CREATE INDEX IF NOT EXISTS idx_withdrawals_status ON withdrawals(status)",
                "CREATE INDEX IF NOT EXISTS idx_withdrawals_user ON withdrawals(user_id)",
                "CREATE INDEX IF NOT EXISTS idx_referral_logs_to ON referral_logs(to_user)",
                "CREATE INDEX IF NOT EXISTS idx_user_tasks_user ON user_tasks(user_id)",
                "CREATE INDEX IF NOT EXISTS idx_user_tasks_task ON user_tasks(task_id)",
                "CREATE INDEX IF NOT EXISTS idx_user_tasks_lookup ON user_tasks(user_id, task_id)",
                "CREATE INDEX IF NOT EXISTS idx_tasks_active ON tasks(is_active)",
            ]:
                conn.execute(stmt)

            for stmt in [
                "ALTER TABLE deposits ADD COLUMN admin_note TEXT",
                "ALTER TABLE withdrawals ADD COLUMN admin_note TEXT",
            ]:
                try:
                    conn.execute(stmt)
                except Exception:
                    pass

            try:
                conn.execute("ALTER TABLE tasks ADD COLUMN task_type TEXT DEFAULT 'join'")
            except Exception:
                pass
            try:
                conn.execute("ALTER TABLE tasks ADD COLUMN task_config TEXT DEFAULT ''")
            except Exception:
                pass
            for stmt in [
                "ALTER TABLE users ADD COLUMN last_login_date TEXT DEFAULT ''",
                "ALTER TABLE users ADD COLUMN login_streak INTEGER DEFAULT 0",
                "ALTER TABLE users ADD COLUMN last_spin_date TEXT DEFAULT ''",
            ]:
                try:
                    conn.execute(stmt)
                except Exception:
                    pass

            conn.execute("""CREATE TABLE IF NOT EXISTS game_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                game_type TEXT,
                bet REAL DEFAULT 0,
                result TEXT DEFAULT 'lost',
                payout REAL DEFAULT 0,
                choice TEXT DEFAULT '',
                details TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now'))
            )""")

            for stmt in [
                "ALTER TABLE users ADD COLUMN total_games_played INTEGER DEFAULT 0",
                "ALTER TABLE users ADD COLUMN total_games_won INTEGER DEFAULT 0",
                "ALTER TABLE users ADD COLUMN last_webapp_open TEXT DEFAULT ''",
                "ALTER TABLE users ADD COLUMN last_nudge_at TEXT DEFAULT ''",
                "ALTER TABLE users ADD COLUMN admin_added_balance REAL DEFAULT 0",
            ]:
                try:
                    conn.execute(stmt)
                except Exception:
                    pass

            conn.commit()
        logger.info(f"Database ready: {'POSTGRES' if USE_POSTGRES else 'SQLITE at ' + SQLITE_PATH}")
    finally:
        safe_close(conn)
