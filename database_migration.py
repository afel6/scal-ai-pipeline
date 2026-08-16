import os
import sys
import logging
import sqlite3
from pathlib import Path

try:
    import psycopg2
except ImportError:
    psycopg2 = None

logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

# -- Configuration --
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
DB_DIR_STR = os.getenv("DB_DIR", ".")
# Strict AGENTS.md rule: Use pathlib.Path only for paths
DB_PATH = Path(DB_DIR_STR) / "chat_history.db"

_PG_AVAILABLE = False
_PG_CONN = None

def check_postgres():
    global _PG_AVAILABLE, _PG_CONN
    if not DATABASE_URL:
        logger.warning("DATABASE_URL not set.")
        return False

    if not psycopg2:
        logger.warning("psycopg2 is not installed.")
        return False

    try:
        _PG_CONN = psycopg2.connect(DATABASE_URL)
        _PG_AVAILABLE = True
        logger.info("PostgreSQL connection successful.")
        return True
    except Exception as e:
        logger.error(f"Failed to connect to PostgreSQL: {e}")
        return False

def init_postgres_db(conn):
    base_stmts = [
        "CREATE TABLE IF NOT EXISTS m (id INTEGER PRIMARY KEY AUTOINCREMENT, sid TEXT, role TEXT, text TEXT, url TEXT, ts REAL, user_email TEXT, fname TEXT)",
        "CREATE TABLE IF NOT EXISTS sessions (sid TEXT PRIMARY KEY, title TEXT NOT NULL DEFAULT 'New Study', user_email TEXT, created_at REAL, updated_at REAL)",
        "CREATE TABLE IF NOT EXISTS kb (id INTEGER PRIMARY KEY AUTOINCREMENT, sid TEXT, user_email TEXT, source TEXT, chunk TEXT)",
        "CREATE TABLE IF NOT EXISTS kb_vectors (id INTEGER PRIMARY KEY AUTOINCREMENT, chunk_id INTEGER UNIQUE, embedding BLOB)",
        "CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT UNIQUE, name TEXT, created_at REAL)",
        "CREATE TABLE IF NOT EXISTS feedback (id INTEGER PRIMARY KEY AUTOINCREMENT, user_email TEXT, bug_report TEXT, ts REAL)",
        "CREATE TABLE IF NOT EXISTS analytics_events (id INTEGER PRIMARY KEY AUTOINCREMENT, user_email TEXT, event_type TEXT, event_data TEXT, ts REAL)",
        "CREATE TABLE IF NOT EXISTS physics_audits (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, user_email TEXT, timestamp REAL, data_type TEXT, health_score INTEGER, violations TEXT, file_name TEXT)",
        "CREATE TABLE IF NOT EXISTS response_cache (id INTEGER PRIMARY KEY AUTOINCREMENT, query_hash TEXT UNIQUE, response TEXT, created_at REAL)",
        "CREATE TABLE IF NOT EXISTS session_summaries (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT UNIQUE, user_email TEXT, well_name TEXT, data_type TEXT, key_params TEXT, created_at REAL)",
        "CREATE TABLE IF NOT EXISTS library_docs (id INTEGER PRIMARY KEY AUTOINCREMENT, filename TEXT NOT NULL, file_hash TEXT NOT NULL UNIQUE, data_type TEXT, uploaded_by TEXT, created_at REAL)",
        "CREATE TABLE IF NOT EXISTS library_chunks (id INTEGER PRIMARY KEY AUTOINCREMENT, doc_id INTEGER REFERENCES library_docs(id) ON DELETE CASCADE, chunk_text TEXT NOT NULL, embedding BLOB, source TEXT)",
        "CREATE TABLE IF NOT EXISTS user_files (id INTEGER PRIMARY KEY AUTOINCREMENT, user_email TEXT NOT NULL, filename TEXT NOT NULL, file_hash TEXT NOT NULL, extracted_text TEXT, data_type TEXT, key_params TEXT, created_at REAL, UNIQUE(user_email, file_hash))",
        "CREATE TABLE IF NOT EXISTS api_metrics (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, timestamp REAL, model TEXT, prompt_tokens INTEGER, completion_tokens INTEGER, cost_usd REAL)",
        "CREATE TABLE IF NOT EXISTS user_corrections (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, user_email TEXT, original_issue TEXT, corrected_value TEXT, timestamp REAL)",
        "CREATE TABLE IF NOT EXISTS session_cache (sid TEXT PRIMARY KEY, ground_truth TEXT, labeled_values TEXT, flat_vectors TEXT, raw_excel_data TEXT, updated_at REAL)",
    ]

    # Do replacements safely. We must not replace "REAL" with "TIMESTAMP" blindly,
    # because cost_usd is a REAL (float).
    pg_stmts = []
    for s in base_stmts:
        s = s.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY").replace("BLOB", "BYTEA")
        # specific replacement for known timestamp columns
        s = s.replace("ts REAL", "ts TIMESTAMP").replace("created_at REAL", "created_at TIMESTAMP").replace("updated_at REAL", "updated_at TIMESTAMP").replace("timestamp REAL", "timestamp TIMESTAMP")
        pg_stmts.append(s)

    indices = [
        "CREATE INDEX IF NOT EXISTS idx_query_hash ON response_cache(query_hash)",
        "CREATE INDEX IF NOT EXISTS idx_library_chunks_doc ON library_chunks(doc_id)",
        "CREATE INDEX IF NOT EXISTS idx_user_files_email ON user_files(user_email)",
        "CREATE INDEX IF NOT EXISTS idx_m_sid ON m(sid)",
        "CREATE INDEX IF NOT EXISTS idx_m_user_email ON m(user_email)",
        "CREATE INDEX IF NOT EXISTS idx_sessions_user_email ON sessions(user_email)",
        "CREATE INDEX IF NOT EXISTS idx_kb_source ON kb(source)",
        "CREATE INDEX IF NOT EXISTS idx_kb_sid ON kb(sid)",
        "CREATE INDEX IF NOT EXISTS idx_library_chunks_source ON library_chunks(source)",
    ]

    with conn.cursor() as cur:
        for stmt in pg_stmts:
            try:
                cur.execute(stmt)
            except Exception as e:
                logger.error(f"Error executing statement: {stmt}\n{e}")
                conn.rollback()
                continue

        for idx in indices:
            try:
                cur.execute(idx)
            except Exception as e:
                logger.error(f"Error executing index creation: {idx}\n{e}")
                conn.rollback()
                continue

        conn.commit()
    logger.info("PostgreSQL database initialized with native types.")

def migrate_data(pg_conn):
    if not DB_PATH.exists():
        logger.info(f"SQLite database not found at {DB_PATH}. Nothing to migrate.")
        return

    logger.info(f"Starting data migration from {DB_PATH}")

    tables = [
        "m", "sessions", "kb", "kb_vectors", "users", "feedback",
        "analytics_events", "physics_audits", "response_cache",
        "session_summaries", "library_docs", "library_chunks",
        "user_files", "api_metrics", "user_corrections", "session_cache"
    ]

    sqlite_conn = sqlite3.connect(DB_PATH)
    sqlite_conn.row_factory = sqlite3.Row
    sqlite_cur = sqlite_conn.cursor()

    pg_cur = pg_conn.cursor()

    for table in tables:
        logger.info(f"Migrating table: {table}")
        try:
            sqlite_cur.execute(f"SELECT * FROM {table}")
            rows = sqlite_cur.fetchall()
        except sqlite3.OperationalError as e:
            logger.warning(f"Skipping table {table} due to error: {e}")
            continue

        if not rows:
            logger.info(f"Table {table} is empty. Skipping.")
            continue

        columns = rows[0].keys()
        col_names = ", ".join(columns)
        placeholders = ", ".join(["%s"] * len(columns))

        # Determine the primary key or unique constraint to handle conflicts safely
        # To make it simple and safe for all tables, we handle unique constraints individually
        # or use ON CONFLICT DO NOTHING if there is a primary key
        # For simplicity in this script, we'll try to insert and catch UniqueViolation

        insert_query = f"INSERT INTO {table} ({col_names}) VALUES ({placeholders})"

        if table in ["sessions", "session_cache"]:
            # sid is primary key
            insert_query += " ON CONFLICT (sid) DO NOTHING"
        elif table == "users":
            insert_query += " ON CONFLICT (id) DO NOTHING"
        elif table == "response_cache":
            insert_query += " ON CONFLICT (id) DO NOTHING"
        elif table == "session_summaries":
            insert_query += " ON CONFLICT (id) DO NOTHING"
        elif table == "library_docs":
            insert_query += " ON CONFLICT (id) DO NOTHING"
        elif table == "user_files":
            insert_query += " ON CONFLICT (id) DO NOTHING"
        elif table == "kb_vectors":
            insert_query += " ON CONFLICT (id) DO NOTHING"
        elif table in ["m", "kb", "feedback", "analytics_events", "physics_audits",
                       "library_chunks", "api_metrics", "user_corrections"]:
            # These have ID as primary key.
            insert_query += " ON CONFLICT (id) DO NOTHING"
        else:
             logger.warning(f"Unhandled conflict resolution for table {table}, using basic insert.")


        from datetime import datetime

        migrated_count = 0
        for row in rows:
            row_values = list(row)

            # Convert values based on their columns
            for i, val in enumerate(row_values):
                if isinstance(val, memoryview):
                     row_values[i] = val.tobytes()
                # For TIMESTAMP columns, we need to convert float (REAL) to datetime
                elif isinstance(val, float) and ("ts" in columns or "timestamp" in columns or "created_at" in columns or "updated_at" in columns):
                     # Attempt to find if this column is actually a timestamp column
                     col_name = list(columns)[i]
                     if col_name in ["ts", "timestamp", "created_at", "updated_at"] and val is not None:
                          row_values[i] = datetime.fromtimestamp(val)

            try:
                pg_cur.execute(insert_query, tuple(row_values))
                migrated_count += 1
            except psycopg2.Error as e:
                pg_conn.rollback()
                logger.debug(f"Failed to insert row into {table}: {e}")
            else:
                pg_conn.commit()

        logger.info(f"Migrated {migrated_count}/{len(rows)} rows for table {table}.")

        # After inserting rows with explicit IDs for SERIAL columns,
        # we need to update the sequences so future inserts don't fail.
        if table not in ["sessions", "session_cache"]:
             try:
                 # Find the max ID
                 pg_cur.execute(f"SELECT MAX(id) FROM {table}")
                 max_id = pg_cur.fetchone()[0]
                 if max_id is not None:
                      seq_name = f"{table}_id_seq"
                      pg_cur.execute(f"SELECT setval('{seq_name}', {max_id})")
                      pg_conn.commit()
             except psycopg2.Error as e:
                 pg_conn.rollback()
                 logger.debug(f"Could not update sequence for {table}: {e}")

    sqlite_conn.close()
    pg_cur.close()

def main():
    if not check_postgres():
        logger.error("PostgreSQL not available. Exiting.")
        sys.exit(1)

    try:
        init_postgres_db(_PG_CONN)
        migrate_data(_PG_CONN)
    finally:
        if _PG_CONN:
            _PG_CONN.close()
            logger.info("PostgreSQL connection closed.")

if __name__ == "__main__":
    main()
