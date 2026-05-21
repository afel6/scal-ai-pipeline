import sqlite3
import sys

sys.stdout.reconfigure(encoding='utf-8')

conn = sqlite3.connect("chat_history.db")
cursor = conn.cursor()

# Get the last 15 messages from table 'm'
cursor.execute("SELECT id, role, text FROM m ORDER BY id DESC LIMIT 15")
rows = cursor.fetchall()

# Reversing order so it's chronological
for row in reversed(rows):
    msg_id, role, text = row
    print(f"Message ID: {msg_id} | Role: {role}")
    # Print first 200 characters and last 200 characters if long
    if text and len(text) > 400:
        print(text[:300] + "\n... [TRUNCATED] ...\n" + text[-300:])
    else:
        print(text)
    print("=" * 80)

conn.close()
