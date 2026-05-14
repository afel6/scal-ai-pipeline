import pytest
import os
import time

@pytest.fixture(scope="session", autouse=True)
def setup_database():
    """Ensure the database is initialized before any tests run."""
    from app import init_db, db
    
    # Try to initialize database
    init_db()
    
    # Verify it worked
    try:
        db("SELECT 1 FROM m LIMIT 1")
    except Exception as e:
        print(f"FAILED TO INIT DB! {e}")
        # Try one more time explicitly
        base_stmts = [
            "CREATE TABLE IF NOT EXISTS m (id INTEGER PRIMARY KEY AUTOINCREMENT, sid TEXT, role TEXT, text TEXT, url TEXT, ts REAL, user_email TEXT, fname TEXT)",
            "CREATE TABLE IF NOT EXISTS sessions (sid TEXT PRIMARY KEY, title TEXT NOT NULL DEFAULT 'New Study', user_email TEXT, created_at REAL, updated_at REAL)",
            "CREATE TABLE IF NOT EXISTS kb (id INTEGER PRIMARY KEY AUTOINCREMENT, sid TEXT, user_email TEXT, source TEXT, chunk TEXT)",
            "CREATE TABLE IF NOT EXISTS kb_vectors (id INTEGER PRIMARY KEY AUTOINCREMENT, chunk_id INTEGER UNIQUE, embedding BLOB)",
            "CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT UNIQUE, name TEXT, created_at REAL)",
            "CREATE TABLE IF NOT EXISTS feedback (id INTEGER PRIMARY KEY AUTOINCREMENT, user_email TEXT, bug_report TEXT, ts REAL)",
            "CREATE TABLE IF NOT EXISTS analytics_events (id INTEGER PRIMARY KEY AUTOINCREMENT, user_email TEXT, event_type TEXT, event_data TEXT, ts REAL)",
            "CREATE TABLE IF NOT EXISTS physics_audits (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, user_email TEXT, timestamp REAL, data_type TEXT, health_score INTEGER, violations TEXT, file_name TEXT)",
            "CREATE TABLE IF NOT EXISTS response_cache (id INTEGER PRIMARY KEY AUTOINCREMENT, query_hash TEXT UNIQUE, response TEXT, created_at REAL)"
        ]
        for s in base_stmts:
            db(s)
