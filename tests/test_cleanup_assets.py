import os
import time
from unittest.mock import patch
import pytest

from cleanup_assets import run_storage_purge, logger

def test_run_storage_purge_non_existent_dir(tmp_path):
    # Verify early exit when target directory is missing
    target_dir = tmp_path / "non_existent"
    # Should not raise any error
    run_storage_purge(str(target_dir))

def test_run_storage_purge_deletes_old_folders(tmp_path):
    target_dir = tmp_path / "outputs"
    target_dir.mkdir()

    # Create an old folder
    old_folder = target_dir / "old_folder"
    old_folder.mkdir()

    # Create a new folder
    new_folder = target_dir / "new_folder"
    new_folder.mkdir()

    # Create a file (should be ignored regardless of age)
    test_file = target_dir / "test_file.txt"
    test_file.touch()

    # Mock time and getmtime
    current_time = 1000000
    age_threshold = 86400

    def mock_getmtime(path):
        if "old_folder" in str(path):
            return current_time - age_threshold - 100 # Older than threshold
        else:
            return current_time - 100 # Newer than threshold

    with patch('time.time', return_value=current_time), \
         patch('os.path.getmtime', side_effect=mock_getmtime):

        run_storage_purge(str(target_dir), age_threshold)

    assert not old_folder.exists()
    assert new_folder.exists()
    assert test_file.exists()

def test_run_storage_purge_exception_handling(tmp_path, caplog):
    target_dir = tmp_path / "outputs"
    target_dir.mkdir()

    # Create an old folder
    old_folder = target_dir / "old_folder"
    old_folder.mkdir()

    current_time = 1000000
    age_threshold = 86400

    def mock_getmtime(path):
        return current_time - age_threshold - 100 # Older than threshold

    # Mock shutil.rmtree to raise an exception
    with patch('time.time', return_value=current_time), \
         patch('os.path.getmtime', side_effect=mock_getmtime), \
         patch('shutil.rmtree', side_effect=PermissionError("Permission denied")):

         run_storage_purge(str(target_dir), age_threshold)

    # Check that error was logged
    assert any("Failed to delete directory" in record.message for record in caplog.records)
    assert any("Permission denied" in record.message for record in caplog.records)
    # The folder shouldn't be deleted since rmtree raised exception
    assert old_folder.exists()
