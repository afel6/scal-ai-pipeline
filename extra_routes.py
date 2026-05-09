"""
Extra API Routes: Feedback, Analytics, User Registration
"""
import os
import time
from fastapi import Form


def register_extra_routes(app, db):

    @app.post("/api/feedback")
    async def submit_feedback(
        user_email: str = Form(""),
        bug_report: str = Form(...)
    ):
        const_email = user_email.lower().strip() if user_email else ""
        db("INSERT INTO feedback (user_email, bug_report, ts) VALUES (?, ?, ?)",
           (const_email, bug_report, time.time()))
        return {"status": "ok"}

    @app.post("/api/analytics/event")
    async def track_event(
        user_email: str = Form(""),
        event_type: str = Form(...),
        event_data: str = Form("")
    ):
        const_email = user_email.lower().strip() if user_email else ""
        db("INSERT INTO analytics_events (user_email, event_type, event_data, ts) VALUES (?, ?, ?, ?)",
           (const_email, event_type, event_data, time.time()))
        return {"status": "ok"}

    @app.post("/api/register")
    async def register_user(
        email: str = Form(...),
        name: str = Form(...)
    ):
        try:
            db("INSERT INTO users (email, name, created_at) VALUES (?, ?, ?)",
               (email.lower().strip(), name.strip(), time.time()))
        except Exception:
            pass
        return {"status": "ok"}

    @app.get("/api/admin/analytics")
    def get_analytics():
        try:
            events = db("SELECT user_email, event_type, event_data, ts FROM analytics_events ORDER BY ts DESC LIMIT 200")
            return {"events": [{"email": e[0], "type": e[1], "data": e[2], "ts": e[3]} for e in events]}
        except Exception:
            return {"events": []}

    @app.get("/api/admin/feedback")
    def get_feedback():
        try:
            rows = db("SELECT user_email, bug_report, ts FROM feedback ORDER BY ts DESC LIMIT 100")
            return {"feedback": [{"email": r[0], "report": r[1], "ts": r[2]} for r in rows]}
        except Exception:
            return {"feedback": []}

    @app.get("/api/admin/users")
    def get_users():
        try:
            rows = db("SELECT email, name, created_at FROM users ORDER BY created_at DESC")
            return {"users": [{"email": r[0], "name": r[1], "created_at": r[2]} for r in rows]}
        except Exception:
            return {"users": []}

    @app.get("/api/admin/summary")
    def get_summary():
        """Aggregated stats for the Admin Dashboard."""
        try:
            total_users = db("SELECT COUNT(*) FROM users")[0][0]
        except Exception:
            total_users = 0
        try:
            total_feedback = db("SELECT COUNT(*) FROM feedback")[0][0]
        except Exception:
            total_feedback = 0
        try:
            total_events = db("SELECT COUNT(*) FROM analytics_events")[0][0]
        except Exception:
            total_events = 0
        try:
            total_messages = db("SELECT COUNT(*) FROM m")[0][0]
        except Exception:
            total_messages = 0
        try:
            total_sessions = len(db("SELECT DISTINCT sid FROM m"))
        except Exception:
            total_sessions = 0
        try:
            total_kb = db("SELECT COUNT(*) FROM kb")[0][0]
        except Exception:
            total_kb = 0
        return {
            "total_users": total_users,
            "total_feedback": total_feedback,
            "total_events": total_events,
            "total_messages": total_messages,
            "total_sessions": total_sessions,
            "total_kb_chunks": total_kb,
            "storage_type": "PostgreSQL (Permanent)" if os.getenv("DATABASE_URL") else "SQLite (Temporary)"
        }
