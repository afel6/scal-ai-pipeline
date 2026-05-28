import os
import time
import shutil
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("AssetCleanupJob")

def run_storage_purge(target_directory: str = "outputs", age_threshold_seconds: int = 86400):
    """
    Automated data lifecycle script scheduled via cron or background tasks. 
    Purges isolated session directories older than 24 hours to prevent local disk exhaustion.
    """
    if not os.path.exists(target_directory):
        return
        
    current_time = time.time()
    deleted_folders = 0
    
    for item in os.listdir(target_directory):
        item_path = os.path.join(target_directory, item)
        if os.path.isdir(item_path):
            age = current_time - os.path.getmtime(item_path)
            if age > age_threshold_seconds:
                try:
                    logger.info(f"Purging expired session folder [Age: {age/3600:.2f} hrs]: {item}")
                    shutil.rmtree(item_path)
                    deleted_folders += 1
                except Exception as e:
                    logger.error(f"Failed to delete directory {item_path}: {str(e)}")
                    
    logger.info(f"Purge process concluded. Successfully removed {deleted_folders} expired session folders.")

if __name__ == "__main__":
    run_storage_purge()
