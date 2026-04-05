import sqlite3
import pprint

conn = sqlite3.connect('chat_history.db')
c = conn.cursor()
c.execute("SELECT sid, role, text, ts FROM m ORDER BY ts ASC")
rows = c.fetchall()

sessions = {}
for r in rows:
    sid, role, text, ts = r
    if sid not in sessions:
        sessions[sid] = []
    sessions[sid].append({"role": role, "text_len": len(text) if text else 0, "text_preview": text[:100] if text else ""})

pprint.pprint(sessions)
