import os
import time
import shutil
from unittest.mock import patch
import pytest

from cleanup_assets import run_storage_purge

def test_run_storage_purge_no_directory(tmp_path):
    target_dir = tmp_path / "nonexistent"
    # Should not raise any error
    run_storage_purge(target_directory=str(target_dir))

def test_run_storage_purge_empty_directory(tmp_path):
    target_dir = tmp_path / "empty"
    target_dir.mkdir()
    run_storage_purge(target_directory=str(target_dir))
    assert target_dir.exists()

def test_run_storage_purge_with_mixed_contents(tmp_path):
    target_dir = tmp_path / "outputs"
    target_dir.mkdir()

    # Create old directory
    old_dir = target_dir / "old_session"
    old_dir.mkdir()

    # Create recent directory
    recent_dir = target_dir / "recent_session"
    recent_dir.mkdir()

    # Create old file
    old_file = target_dir / "old_file.txt"
    old_file.write_text("hello")

    current_time = time.time()

    # Set time for old items (older than 86400 seconds)
    past_time = current_time - 100000
    os.utime(old_dir, (past_time, past_time))
    os.utime(old_file, (past_time, past_time))

    # Set time for recent item (newer than 86400 seconds)
    recent_time = current_time - 100
    os.utime(recent_dir, (recent_time, recent_time))

    # Run purge
    run_storage_purge(target_directory=str(target_dir), age_threshold_seconds=86400)

    # Old directory should be deleted
    assert not old_dir.exists()

    # Recent directory should remain
    assert recent_dir.exists()

    # Old file should remain because the script only deletes directories
    assert old_file.exists()

def test_run_storage_purge_exception_handling(tmp_path, caplog):
    target_dir = tmp_path / "outputs"
    target_dir.mkdir()

    error_dir = target_dir / "error_session"
    error_dir.mkdir()

    # Set to past time
    past_time = time.time() - 100000
    os.utime(error_dir, (past_time, past_time))

    # Mock shutil.rmtree to raise an exception
    with patch('cleanup_assets.shutil.rmtree') as mock_rmtree:
        mock_rmtree.side_effect = PermissionError("Permission denied")
        run_storage_purge(target_directory=str(target_dir), age_threshold_seconds=86400)

    # Assert directory still exists because it failed to delete
    assert error_dir.exists()

    # Verify the error was logged
    assert "Failed to delete directory" in caplog.text
    assert "Permission denied" in caplog.text
