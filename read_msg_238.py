import sqlite3
import sys

sys.stdout.reconfigure(encoding='utf-8')

conn = sqlite3.connect("chat_history.db")
cursor = conn.cursor()

cursor.execute("SELECT text FROM m WHERE id = 238")
text = cursor.fetchone()[0]

print("Length of message 238:", len(text))
print(text)

conn.close()
