"""SQLite ডাটাবেস স্তর।

নীতি: পুরোনো টেবিল কখনো মুছে নতুন করে তৈরি করা হয় না।
- টেবিল না থাকলে CREATE TABLE IF NOT EXISTS
- কলাম না থাকলে শুধু ALTER TABLE ... ADD COLUMN
"""
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

import config

_conn: sqlite3.Connection | None = None

SCHEMA_VERSION = 1

CREATE_STATEMENTS = [
    """CREATE TABLE IF NOT EXISTS schema_migrations (
        version INTEGER PRIMARY KEY, applied_at TEXT)""",
    """CREATE TABLE IF NOT EXISTS admin_users (
        telegram_user_id INTEGER PRIMARY KEY,
        role TEXT NOT NULL DEFAULT 'viewer',
        enabled INTEGER NOT NULL DEFAULT 1,
        created_at TEXT)""",
    """CREATE TABLE IF NOT EXISTS profiles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        owner_user_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'stopped',
        rules_text TEXT,
        required_columns TEXT,
        created_at TEXT,
        updated_at TEXT)""",
    """CREATE TABLE IF NOT EXISTS jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        external_job_key TEXT,
        bot_chat_id TEXT,
        group_chat_id TEXT,
        status TEXT NOT NULL DEFAULT 'active',
        rules_text TEXT,
        confirm_keyword TEXT,
        created_at TEXT)""",
    """CREATE TABLE IF NOT EXISTS profile_jobs (
        profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
        job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
        enabled INTEGER NOT NULL DEFAULT 1,
        check_interval_seconds INTEGER NOT NULL DEFAULT 120,
        monitor_state TEXT NOT NULL DEFAULT 'unknown',
        last_check_at TEXT,
        last_result TEXT,
        last_group_msg_id INTEGER,
        open_episode_handled INTEGER NOT NULL DEFAULT 0,
        created_at TEXT,
        PRIMARY KEY (profile_id, job_id))""",
    """CREATE TABLE IF NOT EXISTS excel_files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
        file_path TEXT NOT NULL,
        original_name TEXT,
        row_count INTEGER,
        status TEXT NOT NULL DEFAULT 'active',
        created_at TEXT,
        deleted_at TEXT)""",
    """CREATE TABLE IF NOT EXISTS job_queue (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
        job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
        excel_file_id INTEGER REFERENCES excel_files(id),
        status TEXT NOT NULL DEFAULT 'pending',
        attempt_count INTEGER NOT NULL DEFAULT 0,
        last_error TEXT,
        next_attempt_at TEXT,
        created_at TEXT,
        started_at TEXT,
        completed_at TEXT)""",
    """CREATE TABLE IF NOT EXISTS job_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        profile_id INTEGER REFERENCES profiles(id) ON DELETE SET NULL,
        job_id INTEGER REFERENCES jobs(id) ON DELETE SET NULL,
        event_type TEXT NOT NULL,
        message TEXT,
        created_at TEXT)""",
    """CREATE TABLE IF NOT EXISTS telegram_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        owner_user_id INTEGER NOT NULL,
        phone_hint TEXT,
        api_id_enc TEXT,
        api_hash_enc TEXT,
        session_enc TEXT,
        status TEXT NOT NULL DEFAULT 'connected',
        last_error TEXT,
        created_at TEXT,
        updated_at TEXT)""",
]

INDEX_STATEMENTS = [
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_profiles_owner_name ON profiles(owner_user_id, lower(name))",
    # একই Bot-এ একই External Key দুবার হবে না
    """CREATE UNIQUE INDEX IF NOT EXISTS ux_jobs_bot_key ON jobs(lower(bot_chat_id), lower(external_job_key))
       WHERE external_job_key IS NOT NULL AND external_job_key <> ''""",
    # একই Profile+Job-এর জন্য একসাথে একটির বেশি সক্রিয় Queue Item নয়
    """CREATE UNIQUE INDEX IF NOT EXISTS ux_queue_active ON job_queue(profile_id, job_id)
       WHERE status IN ('pending','processing','uncertain')""",
    "CREATE INDEX IF NOT EXISTS ix_queue_status ON job_queue(status)",
    "CREATE INDEX IF NOT EXISTS ix_history_profile ON job_history(profile_id, id)",
    "CREATE INDEX IF NOT EXISTS ix_excel_profile ON excel_files(profile_id, status)",
]

# পুরোনো ডাটাবেসে যে কলাম না থাকতে পারে (nullable/ধ্রুব ডিফল্টসহ)
ADDITIVE_COLUMNS = [
    ("profiles", "rules_text", "TEXT"), ("profiles", "required_columns", "TEXT"),
    ("profiles", "updated_at", "TEXT"), ("profiles", "created_at", "TEXT"),
    ("jobs", "external_job_key", "TEXT"), ("jobs", "bot_chat_id", "TEXT"),
    ("jobs", "group_chat_id", "TEXT"), ("jobs", "rules_text", "TEXT"),
    ("jobs", "confirm_keyword", "TEXT"), ("jobs", "created_at", "TEXT"),
    ("jobs", "status", "TEXT DEFAULT 'active'"),
    ("profile_jobs", "enabled", "INTEGER DEFAULT 1"),
    ("profile_jobs", "check_interval_seconds", "INTEGER DEFAULT 120"),
    ("profile_jobs", "monitor_state", "TEXT DEFAULT 'unknown'"),
    ("profile_jobs", "last_check_at", "TEXT"), ("profile_jobs", "last_result", "TEXT"),
    ("profile_jobs", "last_group_msg_id", "INTEGER"),
    ("profile_jobs", "open_episode_handled", "INTEGER DEFAULT 0"),
    ("profile_jobs", "created_at", "TEXT"),
    ("excel_files", "original_name", "TEXT"), ("excel_files", "row_count", "INTEGER"),
    ("excel_files", "deleted_at", "TEXT"), ("excel_files", "created_at", "TEXT"),
    ("job_queue", "attempt_count", "INTEGER DEFAULT 0"), ("job_queue", "last_error", "TEXT"),
    ("job_queue", "next_attempt_at", "TEXT"), ("job_queue", "created_at", "TEXT"),
    ("job_queue", "started_at", "TEXT"), ("job_queue", "completed_at", "TEXT"),
    ("job_history", "created_at", "TEXT"),
    ("telegram_sessions", "phone_hint", "TEXT"), ("telegram_sessions", "last_error", "TEXT"),
    ("telegram_sessions", "updated_at", "TEXT"), ("telegram_sessions", "created_at", "TEXT"),
]


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def connect(path=None) -> sqlite3.Connection:
    global _conn
    if _conn is not None:
        return _conn
    _conn = sqlite3.connect(str(path or config.DB_PATH), isolation_level=None,
                            check_same_thread=False)
    _conn.row_factory = sqlite3.Row
    _conn.execute("PRAGMA journal_mode=WAL")
    _conn.execute("PRAGMA foreign_keys=ON")
    _conn.execute("PRAGMA busy_timeout=5000")
    return _conn


def close():
    global _conn
    if _conn is not None:
        _conn.close()
        _conn = None


def migrate():
    """নিরাপদ, শুধু-যোগ-করা মাইগ্রেশন। যতবার চালানো হোক ক্ষতি নেই।"""
    c = connect()
    for stmt in CREATE_STATEMENTS:
        c.execute(stmt)
    for table, col, ddl in ADDITIVE_COLUMNS:
        existing = {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}
        if existing and col not in existing:
            c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
    for stmt in INDEX_STATEMENTS:
        try:
            c.execute(stmt)
        except sqlite3.IntegrityError as e:
            # পুরোনো ডাটায় ডুপ্লিকেট থাকলে ইনডেক্স বসবে না; ডাটা মোছা হয় না
            print(f"⚠️ ইনডেক্স তৈরি করা যায়নি (ডুপ্লিকেট ডাটা আছে): {e}")
    c.execute("INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(?,?)",
              (SCHEMA_VERSION, now_utc()))


# ---- ছোট সহায়ক ফাংশন ----
def one(sql, params=()):
    return connect().execute(sql, params).fetchone()


def all(sql, params=()):
    return connect().execute(sql, params).fetchall()


def run(sql, params=()):
    return connect().execute(sql, params)


@contextmanager
def tx():
    """একটি ট্রানজ্যাকশন: ভুল হলে সব Rollback।"""
    c = connect()
    c.execute("BEGIN IMMEDIATE")
    try:
        yield c
        c.execute("COMMIT")
    except BaseException:
        c.execute("ROLLBACK")
        raise
