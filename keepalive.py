"""
PRC Keep-Alive Engine
Pings the server every 10 minutes to prevent Render free-tier cold starts.
Runs as a daemon thread — zero impact on request handling.
"""
import threading
import time
import os
import urllib.request

SELF_URL = os.getenv("RENDER_EXTERNAL_URL", "").strip().rstrip("/")
PING_INTERVAL = 600  # 10 minutes

def _ping_loop():
    if not SELF_URL:
        print("[KEEPALIVE] No RENDER_EXTERNAL_URL set — skip self-ping (local mode).")
        return
    print(f"[KEEPALIVE] Self-ping active → {SELF_URL}/health every {PING_INTERVAL//60} min")
    while True:
        time.sleep(PING_INTERVAL)
        try:
            with urllib.request.urlopen(f"{SELF_URL}/health", timeout=10) as r:
                print(f"[KEEPALIVE] Ping OK — status {r.status}")
        except Exception as e:
            print(f"[KEEPALIVE] Ping failed (non-critical): {e}")

def start():
    """Start the keep-alive thread. Call once at app startup."""
    t = threading.Thread(target=_ping_loop, daemon=True)
    t.start()
