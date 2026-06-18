import pytest
from unittest.mock import patch, MagicMock, mock_open
import db_purge

@patch('os.path.exists')
@patch('builtins.print')
@patch('psycopg2.connect')
def test_main_no_db_url(mock_connect, mock_print, mock_exists):
    """Test scenario where .env exists but has no DATABASE_URL."""
    mock_exists.return_value = True
    m_open = mock_open(read_data="OTHER_VAR=value\n")

    with patch('builtins.open', m_open):
        db_purge.main()

    mock_print.assert_any_call("[-] Could not find DATABASE_URL in .env")
    mock_connect.assert_not_called()

@patch('os.path.exists')
@patch('builtins.print')
@patch('psycopg2.connect')
def test_main_no_env_file(mock_connect, mock_print, mock_exists):
    """Test scenario where .env does not exist."""
    mock_exists.return_value = False

    db_purge.main()

    mock_print.assert_any_call("[-] Could not find DATABASE_URL in .env")
    mock_connect.assert_not_called()

@patch('os.path.exists')
@patch('builtins.print')
@patch('psycopg2.connect')
def test_main_success(mock_connect, mock_print, mock_exists):
    """Test successful database connection and execution of purge operations."""
    mock_exists.return_value = True
    m_open = mock_open(read_data="DATABASE_URL=postgres://user:pass@localhost:5432/testdb\n")

    # Setup mock DB connection and cursor
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_cur.rowcount = 42
    mock_conn.cursor.return_value = mock_cur
    mock_connect.return_value = mock_conn

    with patch('builtins.open', m_open):
        db_purge.main()

    # Verify execute was called for the 6 delete statements
    assert mock_cur.execute.call_count == 6
    mock_conn.commit.assert_called_once()
    mock_conn.rollback.assert_not_called()
    mock_cur.close.assert_called_once()
    mock_conn.close.assert_called_once()

    # Check that success message was printed
    mock_print.assert_any_call("[+] DATABASE SUCCESSFULLY PURGED AND RESTORED TO PURE SOURCE-OF-TRUTH STATE!")

@patch('os.path.exists')
@patch('builtins.print')
@patch('psycopg2.connect')
def test_main_db_exception(mock_connect, mock_print, mock_exists):
    """Test exception handling during database operations."""
    mock_exists.return_value = True
    m_open = mock_open(read_data="DATABASE_URL=postgres://user:pass@localhost:5432/testdb\n")

    # Setup mock DB connection and cursor to raise exception
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_cur.execute.side_effect = Exception("Mock DB Error")
    mock_conn.cursor.return_value = mock_cur
    mock_connect.return_value = mock_conn

    with patch('builtins.open', m_open):
        db_purge.main()

    # Check exception handling
    mock_conn.commit.assert_not_called()
    mock_conn.rollback.assert_called_once()
    mock_cur.close.assert_called_once()
    mock_conn.close.assert_called_once()

    # Check error log
    mock_print.assert_any_call("[-] Database operation failed: Mock DB Error")
