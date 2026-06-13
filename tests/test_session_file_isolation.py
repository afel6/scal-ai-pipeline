import os
import sys
import pytest
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import (
    db,
    get_user_file_history_context,
)

class TestSessionFileIsolation:

    @pytest.fixture(autouse=True)
    def clean_db(self):
        # Clear mock data
        try:
            db("DELETE FROM user_files WHERE user_email LIKE ?", ("test_isolation%",))
            db("DELETE FROM m WHERE user_email LIKE ?", ("test_isolation%",))
            db("DELETE FROM sessions WHERE user_email LIKE ?", ("test_isolation%",))
        except Exception:
            pass
        yield
        try:
            db("DELETE FROM user_files WHERE user_email LIKE ?", ("test_isolation%",))
            db("DELETE FROM m WHERE user_email LIKE ?", ("test_isolation%",))
            db("DELETE FROM sessions WHERE user_email LIKE ?", ("test_isolation%",))
        except Exception:
            pass


    def test_global_vs_scoped_isolation(self):
        email = "test_isolation_user@prc.ly"
        sid_1 = "session-1"
        sid_2 = "session-2"
        
        # 1. Insert two files under user_files
        db(
            "INSERT INTO user_files (user_email, filename, file_hash, data_type, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (email, "file1.xlsx", "hash1", "SCAL", time.time() - 10)
        )
        db(
            "INSERT INTO user_files (user_email, filename, file_hash, data_type, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (email, "file2.xlsx", "hash2", "SCAL", time.time())
        )
        
        # 2. Link file1.xlsx to session 1 via message record
        db(
            "INSERT INTO m (sid, role, text, ts, user_email, fname) VALUES (?, ?, ?, ?, ?, ?)",
            (sid_1, "user", "upload file1", time.time(), email, "file1.xlsx")
        )
        
        # 3. Call get_user_file_history_context without sid (New Chat context) -> should be empty
        context_new_chat = get_user_file_history_context(email, sid=None)
        assert context_new_chat == ""
        
        # 4. Call get_user_file_history_context with sid_2 -> should be empty (since file2.xlsx isn't linked to sid_2 yet)
        context_sid_2_empty = get_user_file_history_context(email, sid=sid_2)
        assert context_sid_2_empty == ""
        
        # 5. Call get_user_file_history_context with sid_1 -> should contain file1.xlsx but NOT file2.xlsx
        context_sid_1 = get_user_file_history_context(email, sid=sid_1)
        assert "file1.xlsx" in context_sid_1
        assert "file2.xlsx" not in context_sid_1
        
        # 6. Now link file2.xlsx to session 2
        db(
            "INSERT INTO m (sid, role, text, ts, user_email, fname) VALUES (?, ?, ?, ?, ?, ?)",
            (sid_2, "user", "upload file2", time.time(), email, "file2.xlsx")
        )
        context_sid_2 = get_user_file_history_context(email, sid=sid_2)
        assert "file2.xlsx" in context_sid_2
        assert "file1.xlsx" not in context_sid_2
