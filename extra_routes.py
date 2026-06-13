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

