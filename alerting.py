import logging
import json
import time
import urllib.request
import smtplib
from email.mime.text import MIMEText
import threading
from typing import Optional
from config import settings
import retry_budget

logger = logging.getLogger("Alerting")

_consecutive_llm_failures = 0
_llm_lock = threading.Lock()

# Consecutive provider failures that mark the chat LLM degraded for /health.
# Matches the alert threshold: a single chat turn against an unreachable
# provider retries ~5×, so this trips on the first fully-failed turn.
# One exhausted retry budget (D3.3: LLM_MAX_ATTEMPTS consecutive failures) is
# the signal that the provider is down for this box, not a magic number.
_LLM_UNHEALTHY_AFTER = retry_budget.RetryBudget.from_env().max_attempts
_last_llm_success_ts: Optional[float] = None
_last_llm_error: str = ""

def send_alert(subject: str, message: str):
    # Log the alert at warning level so it shows in structured logs
    logger.warning(f"[ALERT TRIGGERED] Subject: {subject} | Message: {message}")
    
    # Webhook
    if settings.ALERT_WEBHOOK_URL:
        payload = {"text": f"ALERT: {subject}\n{message}"}
        try:
            req = urllib.request.Request(
                settings.ALERT_WEBHOOK_URL,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=5):
                pass
            logger.info("Webhook alert sent successfully.")
        except Exception as e:
            logger.error(f"Failed to send webhook alert: {e}")
            
    # SMTP
    if settings.ALERT_SMTP_HOST and settings.ALERT_EMAIL_TO:
        msg = MIMEText(message)
        msg["Subject"] = f"ALERT: {subject}"
        msg["From"] = settings.ALERT_SMTP_USER or "alert@prc-ai.ly"
        msg["To"] = settings.ALERT_EMAIL_TO
        
        try:
            if settings.ALERT_SMTP_PORT == 465:
                server = smtplib.SMTP_SSL(settings.ALERT_SMTP_HOST, settings.ALERT_SMTP_PORT, timeout=5)
            else:
                server = smtplib.SMTP(settings.ALERT_SMTP_HOST, settings.ALERT_SMTP_PORT, timeout=5)
                server.ehlo()
                # A STARTTLS failure aborts the send (outer handler logs it): the
                # credentials are never sent in the clear (D3.1).
                server.starttls()
                server.ehlo()
            if settings.ALERT_SMTP_USER and settings.ALERT_SMTP_PASSWORD:
                server.login(settings.ALERT_SMTP_USER, settings.ALERT_SMTP_PASSWORD)
            server.send_message(msg)
            server.quit()
            logger.info("SMTP alert sent successfully.")
        except Exception as e:
            logger.error(f"Failed to send SMTP alert: {e}")

def track_llm_call(success: bool, error_msg: str = ""):
    global _consecutive_llm_failures, _last_llm_success_ts, _last_llm_error
    trigger_alert = False
    count = 0
    with _llm_lock:
        if success:
            _consecutive_llm_failures = 0
            _last_llm_success_ts = time.time()
        else:
            _consecutive_llm_failures += 1
            count = _consecutive_llm_failures
            _last_llm_error = error_msg or _last_llm_error
            if _consecutive_llm_failures >= _LLM_UNHEALTHY_AFTER:
                trigger_alert = True

    if trigger_alert:
        send_alert(
            subject="PRC AI HUB [CONSECUTIVE LLM FAILURES]",
            message=f"LLM calls have failed {count} times consecutively."
        )

def record_llm_success():
    track_llm_call(True)

def record_llm_failure(error_msg: str):
    track_llm_call(False, error_msg)

def llm_health() -> dict:
    """Chat-LLM liveness for /health, from the success/failure signal every
    provider call already reports. Provider-agnostic on purpose: when C2 swaps
    the NVIDIA/Gemini path for the single adapter, it keeps calling
    record_llm_success/failure and this stays correct with no change here.
    """
    with _llm_lock:
        fails = _consecutive_llm_failures
        return {
            "healthy": fails < _LLM_UNHEALTHY_AFTER,
            "consecutive_failures": fails,
            "last_success_ts": _last_llm_success_ts,
            "last_error": _last_llm_error if fails else "",
        }

def trigger_500_alert(path: str, exc: Exception):
    send_alert(
        subject="Unhandled 500 Internal Server Error",
        message=f"Endpoint {path} failed with exception: {str(exc)}"
    )

def trigger_latency_alert(path: str, duration: float):
    send_alert(
        subject="PRC AI HUB [LATENCY ALERT]",
        message=f"Endpoint {path} took {duration:.2f} seconds to respond."
    )
