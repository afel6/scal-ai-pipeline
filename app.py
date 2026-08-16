# app.py

# PRC-HUB-VER-14-PROD-READY | 2026-05-10

# Changes: DB connection pooling Â· safe PG placeholder translation Â· thread-safe

#          key rotation Â· thread-local file URIs Â· asyncio.Queue SSE bridge Â·

#          run_in_executor RAG Â· transactional KB ingest Â· admin backend auth Â·

#          env-var secrets Â· slowapi rate limiting Â· dead code purged

# --- PYDANTIC MONKEYPATCH FOR GENKIT HTTP_OPTIONS SCHEMA RESOLUTION ---
try:
    from pydantic.json_schema import GenerateJsonSchema
    _orig_handle = GenerateJsonSchema.handle_invalid_for_json_schema
    def _patched_handle(self, schema, error_info):
        try:
            return _orig_handle(self, schema, error_info)
        except Exception:
            return {"type": "object"}
    GenerateJsonSchema.handle_invalid_for_json_schema = _patched_handle
except Exception:
    pass

# --- PYDANTIC MONKEYPATCH FOR GENKIT TypeAdapter.json_schema PROPERTIES RESOLUTION ---
try:
    from pydantic import TypeAdapter
    _orig_json_schema = TypeAdapter.json_schema
    def ensure_properties(d):
        if isinstance(d, dict):
            if d.get("type") == "object" and "properties" not in d:
                d["properties"] = {}
            for v in list(d.values()):
                ensure_properties(v)
        elif isinstance(d, list):
            for item in d:
                ensure_properties(item)

    def _patched_json_schema(self, *args, **kwargs):
        schema = _orig_json_schema(self, *args, **kwargs)
        ensure_properties(schema)
        return schema
    TypeAdapter.json_schema = _patched_json_schema
except Exception:
    pass

from pathlib import Path
import os, io, uuid, time, re, hmac, hashlib, secrets as _secrets
import json as _json, logging, threading, asyncio
import anyio
from config import settings

GLOBAL_EVENT_LOOP = None

from contextlib import asynccontextmanager, contextmanager
from typing import Optional
from concurrent.futures import ThreadPoolExecutor

import numpy as np



from fastapi import FastAPI, UploadFile, File, Form, Request, HTTPException, Header, Depends, BackgroundTasks, Query

from fastapi.responses import FileResponse, StreamingResponse, JSONResponse

from fastapi.staticfiles import StaticFiles

from fastapi.middleware.cors import CORSMiddleware



from google import genai as genai_new

from google.genai import types as genai_types



from hviel_doc_engine import HvielDocEngine

from skills_engine import SkillsEngine

from petrophysical_curves import Endpoints, KrCurveFitter

from physics_validator import PhysicsGuard

from scal_file_handler import SCALFileHandler, extract_file_data, _extract_pdf as _sfh_extract_pdf, _extract_docx as _sfh_extract_docx, strip_thinking_blocks, strip_placeholder_artifacts, clean_citation_clutter, validate_extraction_against_inventory, extract_absolute_file_truth, validate_permeability_column_binding, compress_traceability_ledger
from file_reader import read_file, to_prompt_string, build_gemini_message

from report_generator import PRCReportEngine
from grader import grade_ai_response
import data_validator
import visualizer
from llm_insight_generator import MasterEngineerNode, DashboardArchitectNode
from dashboard_architect import generate_universal_dashboard, detect_test_type
from llm_json_utils import (
    LLMJsonParseError,
    CORRECTIVE_JSON_PROMPT,
    parse_llm_json,
    llm_json_with_retry,
)

import defusedxml
defusedxml.defuse_stdlib()





from logger_setup import request_id_var, setup_logging
setup_logging(settings.DEBUG)
_logger = logging.getLogger("PRC-Hub")



# -- ENV ----------------------------------------------------------------------

try:

    from dotenv import load_dotenv

    load_dotenv()

except Exception:

    pass



# -- RATE LIMITER --------------------------------------------------------------

try:

    import sys

    from slowapi import Limiter, _rate_limit_exceeded_handler

    from slowapi.util import get_remote_address

    from slowapi.errors import RateLimitExceeded

    _limiter = Limiter(
        key_func=get_remote_address,
        default_limits=["60/minute"],
        storage_uri=settings.REDIS_URL or "memory://",
        enabled=not (settings.TESTING or "pytest" in sys.modules or "PYTEST_CURRENT_TEST" in os.environ)
    )

    _RATE_LIMIT = True

except ImportError:

    _limiter = None

    _RATE_LIMIT = False



# -- SECRETS -------------------------------------------------------------------

GEMINI_KEY_POOL: list[str] = settings.gemini_keys

# --- NVIDIA NIM (OpenAI-compatible) chat backend --------------------------- #
# The Hviel chat assistant + petrophysical tool-calling now run on NVIDIA NIM
# (model nvidia/nemotron-3-super-120b-a12b) instead of Gemini. Keys are read
# from the environment (NVIDIA_API_KEY, plus optional NVIDIA_API_KEY1..N for
# failover). Deterministic file extraction (scal_file_handler) is unchanged.
def _load_nvidia_keys() -> list[str]:
    keys: list[str] = []
    base = os.getenv("NVIDIA_API_KEY")
    if base:
        keys.extend([k.strip(" \n\r\t\"'") for k in base.split(",") if k.strip(" \n\r\t\"'")])
    for k, v in os.environ.items():
        if k.startswith("NVIDIA_API_KEY") and k != "NVIDIA_API_KEY" and v:
            keys.extend([x.strip(" \n\r\t\"'") for x in v.split(",") if x.strip(" \n\r\t\"'")])
    return list(dict.fromkeys(keys))

NVIDIA_KEY_POOL: list[str] = _load_nvidia_keys()
NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
NVIDIA_MODEL = "openai/gpt-oss-120b"
# HTTP timeout (seconds) for a single NVIDIA NIM completion call. Large multi-sheet
# prompts on a reasoning model can exceed the old hardcoded 120s; env-configurable.
try:
    NVIDIA_HTTP_TIMEOUT = float(os.getenv("SCAL_LLM_HTTP_TIMEOUT", "300") or 300)
    if NVIDIA_HTTP_TIMEOUT <= 0:
        NVIDIA_HTTP_TIMEOUT = 300.0
except (TypeError, ValueError):
    NVIDIA_HTTP_TIMEOUT = 300.0
_nvidia_key_idx = 0
_nvidia_key_lock = threading.Lock()

KB_INGEST_SECRET = settings.KB_INGEST_SECRET

ADMIN_PIN        = settings.ADMIN_PIN



_ADMIN_TOKENS:    dict[str, float] = {}   # token  ->  expiry (epoch)

_ADMIN_TOKEN_TTL: int              = 900  # 15 min



# -- DATABASE LAYER ------------------------------------------------------------

DATABASE_URL  = settings.DATABASE_URL

DB_PATH       = str(Path(settings.DB_DIR) / "chat_history.db")



# ── JSON SAFETY HELPER ────────────────────────────────────────────────────────
# NumPy / math can produce NaN or Infinity which are valid Python but INVALID
# JSON — JSON.parse() in the browser will throw, causing the PARSE FAILURE error.
# This helper recursively replaces them with None (serialized as JSON null).
def _sanitize_for_json(obj):
    """Recursively replace NaN/Inf with None so json.dumps stays valid JSON."""
    import math
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_for_json(v) for v in obj]
    # numpy scalar types
    try:
        import numpy as _np
        if isinstance(obj, _np.floating):
            v = float(obj)
            return None if (math.isnan(v) or math.isinf(v)) else v
        if isinstance(obj, _np.integer):
            return int(obj)
        if isinstance(obj, _np.ndarray):
            return [_sanitize_for_json(x) for x in obj.tolist()]
    except ImportError:
        pass
    return obj

def _safe_json_dumps(obj, **kwargs):
    """Sanitize then dump — guaranteed valid JSON, no NaN/Infinity leakage."""
    return _json.dumps(_sanitize_for_json(obj), ensure_ascii=False, **kwargs)


import sys
from concurrent.futures import ThreadPoolExecutor

# User session tokens
_USER_TOKENS: dict[str, float] = {}
_USER_TOKEN_TTL: int = 86400  # 24 hours

# Sequential single-threaded SQLite executor queue to serialize all database operations and prevent locks/deadlocks.
_sqlite_executor = ThreadPoolExecutor(max_workers=1)

def is_testing() -> bool:
    """Returns True if running in a test suite (pytest)."""
    return "pytest" in sys.modules or "PYTEST_CURRENT_TEST" in os.environ or settings.TESTING

def normalize_email(email: Optional[str]) -> Optional[str]:
    if not email:
        return None
    return email.lower().strip()

def verify_user_or_admin(
    authorization: Optional[str] = Header(None),
    token: Optional[str] = Query(None),
    token_form: Optional[str] = Form(None),
    user_email: Optional[str] = Form(None),
    email_query: Optional[str] = Query(None)
):
    """Enforces token-based authentication on all user-facing endpoints (Security Issue 1)."""

    if is_testing():
        return True

    # Safely extract string values from FastAPI defaults
    auth_str = authorization if isinstance(authorization, str) else None
    token_str = token if isinstance(token, str) else None
    token_form_str = token_form if isinstance(token_form, str) else None

    # Normalize token input
    t = None
    if auth_str and auth_str.startswith("Bearer "):
        t = auth_str.split(" ")[1]
    elif token_str:
        t = token_str
    elif token_form_str:
        t = token_form_str

    # 2. Check token against Admin & User token pools
    if t:
        if t in _ADMIN_TOKENS and time.time() <= _ADMIN_TOKENS[t]:
            return True
        if t in _USER_TOKENS and time.time() <= _USER_TOKENS[t]:
            return True
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    raise HTTPException(status_code=401, detail="Authentication token required")

def sanitize_prompt(prompt: str) -> str:
    """Sanitizes user prompt inputs against prompt injection attacks (Security Issue 3)."""
    if not prompt:
        return ""
    adversarial_patterns = [
        r"(?i)\bignore\s+(?:all\s+)?previous\s+instructions\b",
        r"(?i)\bignore\s+(?:the\s+)?above\s+instructions\b",
        r"(?i)\bignore\s+(?:the\s+)?system\s+prompt\b",
        r"(?i)\byou\s+are\s+now\s+a\s+different\s+ai\b",
        r"(?i)\bforget\s+(?:all\s+)?previous\s+instructions\b",
        r"(?i)\bforget\s+(?:your\s+)?system\s+prompt\b",
        r"(?i)\bswitch\s+(?:your\s+)?persona\b",
        r"(?i)\bact\s+as\s+a\b",
        r"(?i)\bnew\s+rule\b",
        r"(?i)\bdo\s+not\s+follow\s+any\s+restrictions\b",
        r"(?i)\breveal\s+(?:your\s+)?system\s+prompt\b",
        r"(?i)\bshow\s+(?:your\s+)?system\s+prompt\b",
        r"(?i)\bprint\s+(?:your\s+)?system\s+prompt\b",
        r"(?i)\bwhat\s+is\s+your\s+system\s+prompt\b",
        r"(?i)\boutput\s+(?:your\s+)?system\s+prompt\b",
        r"(?i)\bexport\s+(?:your\s+)?system\s+prompt\b"
    ]
    sanitized = prompt
    for pattern in adversarial_patterns:
        sanitized = re.sub(pattern, "[PROMPT INJECTION BLOCK]", sanitized)
    return sanitized

def validate_gemini_api_keys():
    """Validates the configured Gemini API keys on startup by making a small check.
    Raises ValueError with a clear, readable error message if keys are invalid (Crash Issue 6)."""
    _logger.info("[STARTUP-VAL] Validating Gemini API key(s)...")
    if not GEMINI_KEY_POOL or GEMINI_KEY_POOL[0] == "DUMMY_KEY":
        raise ValueError(
            "CRITICAL: Gemini API key is missing or set to default 'DUMMY_KEY'. "
            "Please configure the GEMINI_API_KEY environment variable in your .env file."
        )
    try:
        test_client = genai_new.Client(api_key=GEMINI_KEY_POOL[0])
        test_client.models.list()
        _logger.info("[STARTUP-VAL] Gemini API key validated successfully.")
    except Exception as e:
        err_msg = str(e)
        _logger.error(f"[STARTUP-VAL] Gemini API key validation failed: {err_msg}")
        raise ValueError(
            f"CRITICAL: The configured Gemini API key is invalid or unauthorized! "
            f"Error details: {err_msg}. Please verify your GEMINI_API_KEY environment variable."
        ) from e

_PG_POOL      = None

_PG_AVAILABLE = False

_SQLITE_LOCK  = threading.Lock()

_PG_POOL_LOCK = threading.Lock()  # guards pool reinit across threads



if DATABASE_URL:

    try:

        from psycopg2 import pool as _pg_pool_mod

        _PG_POOL      = _pg_pool_mod.ThreadedConnectionPool(5, 50, DATABASE_URL)
        _PG_AVAILABLE = True
        _logger.info("[DB] PostgreSQL pool ready (5-50 conns)")

    except Exception as _e:

        _logger.warning(f"[DB] PostgreSQL unavailable, using SQLite: {_e}")



if not _PG_AVAILABLE:

    import sqlite3

    _logger.info("[DB] SQLite + WAL mode")


# ── DB RETRY / RESILIENCE ──────────────────────────────────────────────────────

# Delays applied BETWEEN attempts (not before the first): 500 ms → 1 s → 2 s.
_DB_RETRY_DELAYS = (0.5, 1.0, 2.0)

# Both psycopg2 and sqlite3 name their transient socket/lock errors the same way.
# Checking __name__ avoids importing driver-specific exception classes here.
_DB_TRANSIENT_ERROR_NAMES = frozenset({"OperationalError", "InterfaceError"})


def _reinit_pg_pool() -> bool:
    """Close the current PG pool and open a fresh one against DATABASE_URL.

    Called automatically when a transient connection error is detected so that
    the next retry gets a live socket instead of a dead one.  Thread-safe: only
    one reinit runs at a time; concurrent callers block on _PG_POOL_LOCK and
    then proceed with the already-refreshed pool.

    Returns True if the new pool was created successfully, False otherwise.
    """
    global _PG_POOL, _PG_AVAILABLE
    if not DATABASE_URL:
        return False
    with _PG_POOL_LOCK:
        try:
            if _PG_POOL is not None:
                try:
                    _PG_POOL.closeall()
                except Exception:
                    pass
            from psycopg2 import pool as _pg_pool_mod
            _PG_POOL = _pg_pool_mod.ThreadedConnectionPool(5, 50, DATABASE_URL)
            _PG_AVAILABLE = True
            _logger.warning("[DB] PG pool re-initialized after transient connection failure.")
            return True
        except Exception as _reinit_err:
            _logger.error(f"[DB] Pool re-init failed: {_reinit_err}")
            return False


def with_db_retry(fn):
    """Decorator: retry a DB-calling function up to 3 times with exponential backoff.

    Retry schedule: 500 ms → 1 s → 2 s between attempts.
    On psycopg2 OperationalError / InterfaceError the PG pool is torn down and
    rebuilt before the next attempt so dead sockets are never reused.

    Usage:
        @with_db_retry
        def my_query():
            with _get_conn() as (conn, ph):
                ...
    """
    import functools

    @functools.wraps(fn)
    def _wrapper(*args, **kwargs):
        last_err = None
        for attempt, delay in enumerate(_DB_RETRY_DELAYS):
            try:
                return fn(*args, **kwargs)
            except Exception as exc:
                last_err = exc
                _logger.warning(
                    f"[DB RETRY] {fn.__name__} attempt {attempt + 1}/3 "
                    f"({type(exc).__name__}): {exc}"
                )
                if type(exc).__name__ in _DB_TRANSIENT_ERROR_NAMES and _PG_AVAILABLE:
                    _reinit_pg_pool()
                if attempt < len(_DB_RETRY_DELAYS) - 1:
                    time.sleep(delay)
        _logger.error(f"[DB FINAL ERROR] {fn.__name__} gave up after 3 attempts: {last_err}")
        raise last_err

    return _wrapper



def _translate_placeholders(query: str) -> str:

    """Convert SQLite ? placeholders to PostgreSQL %s for psycopg2 driver."""

    out, in_str, quote = [], False, None

    for ch in query:

        if in_str:

            out.append(ch)

            if ch == quote:

                in_str = False

        elif ch in ("'", '"'):

            in_str, quote = True, ch

            out.append(ch)

        elif ch == "?":

            out.append("%s")

        else:

            out.append(ch)

    return "".join(out)





@contextmanager

def _get_conn():

    """Yield (connection, placeholder). Pools PG; locks SQLite."""

    if _PG_AVAILABLE:

        conn = None

        for _ in range(3):

            conn = _PG_POOL.getconn()

            try:

                with conn.cursor() as cur:

                    cur.execute("SELECT 1")

                break

            except Exception:

                _PG_POOL.putconn(conn, close=True)

                conn = None

        if not conn:

            raise Exception("DB Pool exhausted or all connections dead.")

        

        try:

            yield conn, "%s"

        finally:

            try:

                # If an error occurred during yield, the connection might be broken.

                # psycopg2 connections have a 'closed' attribute or we can check status.

                if hasattr(conn, "closed") and conn.closed:

                    _PG_POOL.putconn(conn, close=True)

                else:

                    _PG_POOL.putconn(conn)

            except Exception:

                pass

    else:

        with _SQLITE_LOCK:

            conn = sqlite3.connect(DB_PATH, timeout=10)

            conn.execute("PRAGMA journal_mode=WAL")

            conn.execute("PRAGMA busy_timeout=10000")

            conn.execute("PRAGMA foreign_keys = ON;")

            try:

                yield conn, "?"

            finally:

                conn.close()





def db(query: str, params: tuple = ()) -> list:

    """Execute a query with ? placeholders, falling back to SQLite if PostgreSQL fails."""

    last_err = None

    for attempt, delay in enumerate(_DB_RETRY_DELAYS):

        try:

            with _get_conn() as (conn, ph):

                q = query if ph == "?" else _translate_placeholders(query)

                cur = conn.cursor()

                cur.execute(q, params)

                try:

                    result = cur.fetchall()

                except Exception:

                    result = []

                conn.commit()

                return result

        except Exception as e:

            last_err = e

            _logger.warning(
                f"[DB RETRY] Attempt {attempt + 1}/3 for '{query[:60]}' "
                f"({type(e).__name__}): {e}"
            )

            if type(e).__name__ in _DB_TRANSIENT_ERROR_NAMES and _PG_AVAILABLE:

                _reinit_pg_pool()

            if attempt < len(_DB_RETRY_DELAYS) - 1:

                time.sleep(delay)



    _logger.error(f"[DB FINAL ERROR] Query: {query} | Error: {last_err}")

    raise last_err





async def async_db(query: str, params: tuple = ()) -> list:

    """Non-blocking DB call for async routes."""

    return await asyncio.to_thread(db, query, params)





def _log_physics_audit(sid: str, data_type: str, audit_res: dict, file_name: str = None):

    """Immutable logging to the Physics Audit Ledger."""

    try:

        score = audit_res.get("score", 0)

        violations = _json.dumps(audit_res.get("violations", []))

        db("INSERT INTO physics_audits (session_id, timestamp, data_type, health_score, violations, file_name) "

           "VALUES (?, ?, ?, ?, ?, ?)",

           (sid, time.time(), data_type, score, violations, file_name))

        _logger.info(f"[AUDIT] Logged {data_type} audit for {sid} (Score: {score}%)")

    except Exception as e:

        _logger.error(f"[AUDIT] Failed to log audit: {e}")


# ── SESSION MEMORY SUMMARY ────────────────────────────────────────────────────

def _extract_petrophysical_summary(response_text: str, file_name: str) -> dict:
    """Quick non-streaming NVIDIA NIM call to extract key params from analysis reply."""
    prompt = (
        "You are a petrophysical parameter extractor. Given the assistant response below, "
        "extract key values into JSON. Return ONLY valid JSON with these exact keys "
        "(use null for any not found): "
        "{\"well_name\": string_or_null, \"data_type\": string_or_null, "
        "\"Pd_psia\": number_or_null, \"Sw_i\": number_or_null, \"Sor\": number_or_null, "
        "\"krw_max\": number_or_null, \"kro_max\": number_or_null, "
        "\"m_cementation\": number_or_null, \"n_saturation\": number_or_null, "
        "\"sample_count\": integer_or_null}\n\n"
        f"Source file: {file_name}\n\nAssistant response:\n{response_text[:4000]}"
    )
    try:
        # NVIDIA NIM (gpt-oss-120b) may fence the JSON or wrap it in prose;
        # llm_json_with_retry re-prompts once with a corrective instruction.
        def _gen(corrective):
            p = prompt if not corrective else f"{prompt}\n\n{corrective}"
            return _nvidia_text_generate(p, temperature=0.1, max_tokens=1024)
        parsed = llm_json_with_retry(_gen, logger=_logger)
        return parsed if isinstance(parsed, dict) else {}
    except Exception as e:
        import alerting
        alerting.record_llm_failure(str(e))
        _logger.warning(f"[Summary] Extraction failed for {file_name}: {e}")
        return {}


def _save_summary_background(sid: str, email: str, response_text: str, file_name: str):
    """Background task: extract params from analysis reply and persist to session_summaries."""
    params = _extract_petrophysical_summary(response_text, file_name)
    if not params:
        return
    try:
        well = params.get("well_name")
        dtype = params.get("data_type")
        key_params_json = _json.dumps({
            k: v for k, v in params.items()
            if v is not None and k not in ("well_name", "data_type")
        })
        if _PG_AVAILABLE:
            db(
                "INSERT INTO session_summaries (session_id, user_email, well_name, data_type, key_params, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (session_id) DO UPDATE SET "
                "well_name=EXCLUDED.well_name, data_type=EXCLUDED.data_type, key_params=EXCLUDED.key_params",
                (sid, email, well, dtype, key_params_json, time.time()),
            )
        else:
            db(
                "INSERT OR REPLACE INTO session_summaries (session_id, user_email, well_name, data_type, key_params, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (sid, email, well, dtype, key_params_json, time.time()),
            )
        _logger.info(f"[Summary] Saved {dtype} summary for session {sid} (well: {well})")

        # Back-fill key_params into user_files for the file that triggered this analysis
        try:
            if _PG_AVAILABLE:
                db(
                    "UPDATE user_files SET key_params=? WHERE user_email=? AND filename=?",
                    (key_params_json, email, file_name),
                )
            else:
                db(
                    "UPDATE user_files SET key_params=? WHERE user_email=? AND filename=?",
                    (key_params_json, email, file_name),
                )
        except Exception:
            pass

    except Exception as e:
        _logger.error(f"[Summary] DB save failed for {sid}: {e}")


def get_session_summary_context(sid: str) -> str:
    """Return a formatted session memory block to prepend to kb_ctx, or empty string."""
    try:
        rows = db("SELECT well_name, data_type, key_params FROM session_summaries WHERE session_id=?", (sid,))
        if not rows:
            return ""
        well, dtype, params_json = rows[0]
        params: dict = {}
        try:
            params = _json.loads(params_json or "{}")
        except Exception:
            pass
        lines = ["[SESSION MEMORY — previously analysed data for this session]"]
        if well:
            lines.append(f"Well: {well}")
        if dtype:
            lines.append(f"Data type: {dtype}")
        for k, v in params.items():
            if v is not None:
                lines.append(f"{k}: {v}")
        lines.append("[END SESSION MEMORY]")
        return "\n".join(lines)
    except Exception as e:
        _logger.warning(f"[Summary] Context read failed for {sid}: {e}")
        return ""


# ── USER FILE HISTORY ─────────────────────────────────────────────────────────

def get_user_file_history_context(email: str, sid: str = None) -> str:
    """Return formatted ENGINEER FILE HISTORY block for the user uploads scoped to the session."""
    if not email:
        return ""
    try:
        if sid:
            # Only select files that were actually uploaded in this session (by looking at message fname records)
            fname_rows = db(
                "SELECT DISTINCT fname FROM (SELECT fname FROM m WHERE sid=? AND user_email=? AND fname IS NOT NULL ORDER BY id DESC) sub",
                (sid, email),
            )
            session_fnames = []
            seen = set()
            for r in (fname_rows or []):
                if r[0]:
                    for fn in r[0].split(";"):
                        fn = fn.strip()
                        if fn and fn not in seen:
                            session_fnames.append(fn)
                            seen.add(fn)
            if not session_fnames:
                return ""
            
            # Query user_files for only these filenames
            placeholders = ",".join("?" for _ in session_fnames)
            rows = db(
                f"SELECT filename, data_type, key_params, created_at FROM user_files "
                f"WHERE user_email=? AND filename IN ({placeholders}) ORDER BY created_at DESC",
                (email, *session_fnames),
            )
        else:
            # If no session ID is provided, there are no files in this session yet
            return ""

        if not rows:
            return ""
        lines = ["ENGINEER FILE HISTORY (your previously uploaded files):"]
        for i, (fname, dtype, params_json, ts) in enumerate(rows, 1):
            date_str = time.strftime("%Y-%m-%d", time.localtime(ts)) if ts else "unknown"
            params: dict = {}
            try:
                params = _json.loads(params_json or "{}")
            except Exception:
                pass
            param_str = ", ".join(f"{k}={v}" for k, v in params.items() if v is not None)
            entry = f"{i}. {fname} ({dtype or 'unknown'}) — uploaded {date_str}"
            if param_str:
                entry += f" — {param_str}"
            lines.append(entry)
        return "\n".join(lines)
    except Exception as e:
        _logger.warning(f"[UserFiles] History read failed for {email}: {e}")
        return ""



def _env_int(name: str, default: int) -> int:
    """Read a positive integer from the environment; fall back to default on
    missing, empty, non-numeric, or non-positive values."""
    try:
        v = int(os.getenv(name, "") or default)
        return v if v > 0 else default
    except (TypeError, ValueError):
        return default


def _cap_prompt_block(text: str, max_chars: int, label: str = "BLOCK") -> str:
    """Hard character cap for any text block injected into an LLM prompt.

    Keeps head + tail and drops the middle with an explicit marker so the model
    knows data was elided and can ask for a specific sheet/column/row range
    instead of guessing. Second line of defense behind the structured per-sheet
    row capping in `_truncate_ground_truth`.
    """
    if not text or len(text) <= max_chars:
        return text
    marker = (
        f"\n... [TRUNCATED {label}: {len(text) - max_chars} CHARS ELIDED TO FIT THE MODEL "
        f"CONTEXT WINDOW — ask for a specific sheet/column/row range for full detail] ...\n"
    )
    budget = max(1000, max_chars - len(marker))
    head_len = int(budget * 0.7)
    tail_len = budget - head_len
    return text[:head_len] + marker + text[-tail_len:]


def format_sheet_as_markdown(sheet_name, columns, rows, full_shape_str):
    import ast
    parsed_rows = []
    for r_str in rows:
        start_idx = r_str.find('[')
        if start_idx != -1:
            try:
                vals = ast.literal_eval(r_str[start_idx:])
                parsed_rows.append(vals)
            except:
                pass
                
    # If columns list is empty, infer length from the first parsed row
    if not columns and parsed_rows:
        columns = [f"Col {i}" for i in range(len(parsed_rows[0]))]
        
    num_cols = len(columns)
    col_types = []
    
    for col_idx in range(num_cols):
        is_numeric = True
        has_val = False
        for r in parsed_rows:
            if col_idx < len(r):
                val = r[col_idx]
                if val is not None:
                    has_val = True
                    # Check if numeric
                    if not isinstance(val, (int, float)):
                        is_numeric = False
                        break
        if has_val and is_numeric:
            col_types.append("numeric")
        else:
            col_types.append("string")
            
    md_lines = []
    md_lines.append(f"  SHEET: \"{sheet_name}\"")
    md_lines.append(f"    FULL SHAPE: {full_shape_str}")
    md_lines.append(f"    COLUMNS AND DATA TYPES:")
    for col, c_type in zip(columns, col_types):
        md_lines.append(f"      - {col} ({c_type})")
        
    md_lines.append("    DATA PREVIEW (MARKDOWN):")
    
    if num_cols > 0:
        header_line = "    | " + " | ".join(columns) + " |"
        sep_line = "    | " + " | ".join(["---"] * num_cols) + " |"
        md_lines.append(header_line)
        md_lines.append(sep_line)
        
        total_rows = len(parsed_rows)
        if total_rows <= 10:
            for r in parsed_rows:
                # Ensure length matches num_cols
                r_extended = r + [None] * (num_cols - len(r))
                row_str = "    | " + " | ".join(str(val) if val is not None else "" for val in r_extended[:num_cols]) + " |"
                md_lines.append(row_str)
        else:
            for idx in range(5):
                r = parsed_rows[idx]
                r_extended = r + [None] * (num_cols - len(r))
                row_str = "    | " + " | ".join(str(val) if val is not None else "" for val in r_extended[:num_cols]) + " |"
                md_lines.append(row_str)
                
            # Truncation marker row
            trunc_marker = f"    | ... | [TRUNCATED {total_rows - 10} ROWS FOR BREVITY — ask for a specific row range to see them] | " + " | ".join(["..."] * max(0, num_cols - 2)) + " |"
            md_lines.append(trunc_marker)
            
            for idx in range(total_rows - 5, total_rows):
                r = parsed_rows[idx]
                r_extended = r + [None] * (num_cols - len(r))
                row_str = "    | " + " | ".join(str(val) if val is not None else "" for val in r_extended[:num_cols]) + " |"
                md_lines.append(row_str)
    else:
        md_lines.append("    [No columns available to preview]")
        
    return "\n".join(md_lines)


def _truncate_ground_truth(gt_text: str, max_rows: int = None, max_chars: int = None) -> str:
    """Truncate large tabular ground-truth inventory data before LLM prompt injection using a hierarchical capping mechanism.

    Each sheet is represented as:
      - Sheet metadata (Sheet name, row/column count, column headers, data types).
      - A sampled preview of the data (first 5 and last 5 rows formatted as Markdown tables, with an indicator like `... [N rows truncated] ...` in between).
    Ensures that dense numeric tables do not exceed 100,000 characters of total injected prompt text.
    """
    if not gt_text:
        return ""
        
    if max_chars is None:
        max_chars = 100000
        
    import ast
    import re
    
    lines = gt_text.splitlines()
    output_lines = []
    
    current_sheet = None
    sheet_columns = []
    sheet_shape = ""
    sheet_rows = []
    
    def flush_sheet():
        if current_sheet is not None:
            formatted = format_sheet_as_markdown(current_sheet, sheet_columns, sheet_rows, sheet_shape)
            output_lines.append(formatted)
            output_lines.append("")
            
    for line in lines:
        if line.startswith("╔") or line.startswith("║") or line.startswith("╚") or not line.strip():
            output_lines.append(line)
        elif line.startswith("═══ FILE:") or line.startswith("TOTAL SHEETS:") or line.startswith("SHEET NAMES:"):
            flush_sheet()
            current_sheet = None
            sheet_rows = []
            output_lines.append(line)
        elif line.strip().startswith("SHEET:"):
            flush_sheet()
            sheet_rows = []
            sheet_columns = []
            sheet_shape = ""
            m = re.match(r'^\s*SHEET:\s*["\']?(.*?)["\']?$', line)
            if m:
                current_sheet = m.group(1)
            else:
                current_sheet = "Unknown"
        elif line.strip().startswith("COLUMNS (") or line.strip().startswith("COLUMNS("):
            idx = line.find(':')
            if idx != -1:
                try:
                    sheet_columns = ast.literal_eval(line[idx+1:].strip())
                except:
                    sheet_columns = []
        elif line.strip().startswith("FULL SHAPE:"):
            idx = line.find(':')
            if idx != -1:
                sheet_shape = line[idx+1:].strip()
        elif line.strip().startswith("ROW "):
            sheet_rows.append(line)
        else:
            output_lines.append(line)
            
    flush_sheet()
    
    out = "\n".join(output_lines)
    
    if len(out) > max_chars:
        structural_prefixes = ("═══ FILE:", "TOTAL SHEETS:", "SHEET NAMES:",
                               "  SHEET: ", "    COLUMNS AND DATA TYPES:", "    FULL SHAPE:")
        skeleton = [ln for ln in out.splitlines()
                    if ln.startswith(structural_prefixes) or "═══ FILE: " in ln]
        skeleton_text = ""
        if skeleton:
            skeleton_text = ("\n[STRUCTURAL SHEET INDEX — all sheets/columns/shapes preserved "
                             "despite truncation above]:\n" + "\n".join(skeleton) + "\n")
            skeleton_text = _cap_prompt_block(skeleton_text, max(2000, max_chars // 4), "SHEET INDEX")
        body_budget = max(1000, max_chars - len(skeleton_text))
        out = _cap_prompt_block(out, body_budget, "GROUND TRUTH INVENTORY") + skeleton_text
        
    return out


def populate_cache_from_ground_truth(sid: str, gt_text: str):
    if not sid or not gt_text:
        return
    with SESSION_DATA_CACHE_LOCK:
        if sid not in SESSION_DATA_CACHE:
            SESSION_DATA_CACHE[sid] = {}
        if "labeled_values" not in SESSION_DATA_CACHE[sid]:
            SESSION_DATA_CACHE[sid]["labeled_values"] = {}
            
        import ast
        
        # Split by SHEET:
        sheets = gt_text.split("  SHEET: ")
        for sheet_part in sheets[1:]:
            lines = sheet_part.split("\n")
            if not lines:
                continue
            sheet_name_match = re.match(r'^["\']?(.*?)["\']?$', lines[0].strip())
            if not sheet_name_match:
                continue
            sheet_name = sheet_name_match.group(1)
            
            # Find columns line
            cols = []
            grid = []
            for line in lines[1:]:
                if "COLUMNS (" in line:
                    col_str = line.partition("):")[2].strip()
                    try:
                        cols = ast.literal_eval(col_str)
                    except Exception:
                        cols = [c.strip().strip("'\"[]") for c in col_str.split(",")]
                elif "    ROW " in line:
                    row_vals_str = line.partition(":")[2].strip()
                    try:
                        row_vals = ast.literal_eval(row_vals_str)
                        grid.append(row_vals)
                    except Exception:
                        continue
            
            # Zip columns and values (legacy fallback mapping)
            for row_vals in grid:
                for col, val in zip(cols, row_vals):
                    if val is not None and isinstance(val, (int, float)) and not isinstance(val, bool):
                        col_clean = col.strip().lower()
                        SESSION_DATA_CACHE[sid]["labeled_values"][col_clean] = val
                        sheet_key = f"{sheet_name}.{col}".lower().replace(" ", "_")
                        SESSION_DATA_CACHE[sid]["labeled_values"][sheet_key] = val

            # Advanced cell-based spatial extraction (horizontal and vertical scan)
            full_grid = [cols] + grid
            n_rows_g = len(full_grid)
            for r in range(n_rows_g):
                n_cols_g = len(full_grid[r])
                for c in range(n_cols_g):
                    cell = full_grid[r][c]
                    if isinstance(cell, str) and cell.strip():
                        # Extract value to the right
                        val_r = None
                        if c + 1 < n_cols_g:
                            val_r = full_grid[r][c + 1]
                        # Extract value below
                        val_d = None
                        if r + 1 < n_rows_g and c < len(full_grid[r + 1]):
                            val_d = full_grid[r + 1][c]
                            
                        # Standard label clean
                        def clean_lbl(s):
                            s = re.sub(r'[^a-zA-Z0-9_]', '_', s.lower())
                            s = re.sub(r'_{2,}', '_', s)
                            return s.strip('_')
                            
                        for val in [val_r, val_d]:
                            if val is not None and isinstance(val, (int, float)) and not isinstance(val, bool):
                                cl = clean_lbl(cell)
                                if cl:
                                    SESSION_DATA_CACHE[sid]["labeled_values"][cl] = val
                                    sheet_key = f"{sheet_name.lower()}.{cl}".replace(" ", "_")
                                    SESSION_DATA_CACHE[sid]["labeled_values"][sheet_key] = val
                                    
                                    # Keyword standardized mappings (excluding mathematical derivatives)
                                    if any(x in cl for x in ["swi", "swc", "connate", "irreducible_water", "sw_irr", "swir"]):
                                        if not any(x in cl for x in ["1_", "1-", "1 -"]):
                                            SESSION_DATA_CACHE[sid]["labeled_values"]["swi"] = val
                                    if any(x in cl for x in ["sor", "s_or", "residual_oil", "sorw", "sorg"]):
                                        if not any(x in cl for x in ["1_", "1-", "1 -"]):
                                            SESSION_DATA_CACHE[sid]["labeled_values"]["sor"] = val
                                    if any(x in cl for x in ["cementation", "exponent_m", "exponentm", "tortuosity"]):
                                        SESSION_DATA_CACHE[sid]["labeled_values"]["m"] = val
                                    if any(x in cl for x in ["saturation_exponent", "exponent_n", "exponentn"]):
                                        SESSION_DATA_CACHE[sid]["labeled_values"]["n"] = val
                                    if any(x in cl for x in ["porosity", "phi"]):
                                        SESSION_DATA_CACHE[sid]["labeled_values"]["porosity"] = val
                                    if any(x in cl for x in ["permeability", "perm", "klinkenberg"]):
                                        SESSION_DATA_CACHE[sid]["labeled_values"]["permeability"] = val
                                    if any(x in cl for x in ["compressibility", "pore_volume_compressibility", "pore_vol_comp"]):
                                        SESSION_DATA_CACHE[sid]["labeled_values"]["pore_volume_compressibility"] = val
                                        
                                    # Generic slope mapping based on sheet context (slope and well_b represent Archie m and n)
                                    if "slope" in cl or "well_b" in cl:
                                        sh_lower = sheet_name.lower()
                                        if "ri" in sh_lower or "resistivity_index" in sh_lower:
                                            SESSION_DATA_CACHE[sid]["labeled_values"]["n"] = abs(val)
                                        elif "ff" in sh_lower or "formation_factor" in sh_lower:
                                            SESSION_DATA_CACHE[sid]["labeled_values"]["m"] = abs(val)
    save_session_cache_to_db(sid)


def _detect_main_table(df):
    """
    Scans a pandas DataFrame to find the contiguous row range and headers of the primary data table.
    Returns (data_start_row, headers) or (None, None).
    """
    import pandas as pd
    import numpy as np
    n_rows, n_cols = df.shape
    if n_rows < 2 or n_cols < 1:
        return None, None
        
    def is_numeric(val):
        if pd.isna(val):
            return False
        if isinstance(val, bool):
            return False
        if isinstance(val, (int, float, np.integer, np.floating)):
            return True
        if isinstance(val, str):
            try:
                float(val)
                return True
            except ValueError:
                return False
        return False

    # 1. Identify candidate data rows
    candidates = []
    for r in range(n_rows):
        row_vals = df.iloc[r].tolist()
        num_count = sum(1 for val in row_vals if is_numeric(val))
        non_empty = sum(1 for val in row_vals if pd.notna(val) and str(val).strip() != "")
        if num_count >= 1 and num_count >= 0.5 * non_empty:
            candidates.append(r)
            
    if not candidates:
        return None, None
        
    # 2. Group into contiguous rows
    groups = []
    current_group = [candidates[0]]
    for r in candidates[1:]:
        if r == current_group[-1] + 1:
            current_group.append(r)
        else:
            groups.append(current_group)
            current_group = [r]
    groups.append(current_group)
    
    # 3. Score groups to find the main data table
    best_group = None
    best_score = -1
    best_numeric_cols = []
    
    for group in groups:
        numeric_cols = []
        for c in range(n_cols):
            col_vals = [df.iloc[r, c] for r in group]
            num_in_col = sum(1 for val in col_vals if is_numeric(val))
            if num_in_col >= 0.7 * len(group):
                numeric_cols.append(c)
        
        score = len(group) * len(numeric_cols)
        if score > best_score:
            best_score = score
            best_group = group
            best_numeric_cols = numeric_cols
            
    if best_score < 4 or not best_group:
        # Fallback to simple backward-compatible heuristic
        data_start_row = None
        for i in range(n_rows):
            row_vals = df.iloc[i].tolist()
            num_count = sum(1 for v in row_vals if pd.notna(v) and isinstance(v, (int, float)) and not isinstance(v, bool))
            if num_count >= 1:
                data_start_row = i
                break
        if data_start_row is None:
            data_start_row = 1
            
        headers = []
        for col_idx in range(n_cols):
            parts = []
            for r in range(max(0, data_start_row)):
                cell_val = df.iloc[r, col_idx]
                cell_str = str(cell_val).strip() if pd.notna(cell_val) else ""
                if cell_str and cell_str.lower() != "nan":
                    parts.append(cell_str)
            headers.append(" ".join(parts) if parts else f"col_{col_idx}")
            
        seen = {}
        unique_headers = []
        for h in headers:
            h_clean = h.strip()
            if not h_clean:
                h_clean = "unnamed"
            if h_clean in seen:
                seen[h_clean] += 1
                unique_headers.append(f"{h_clean}_{seen[h_clean]}")
            else:
                seen[h_clean] = 1
                unique_headers.append(h_clean)
        headers = unique_headers
        return data_start_row, headers
        
    data_start_row = best_group[0]
    
    # 4. Find the header row by scanning upwards from data_start_row - 1
    header_row_idx = None
    for r in range(data_start_row - 1, -1, -1):
        row_vals = df.iloc[r].tolist()
        non_empty_strings = [str(val).strip() for val in row_vals if pd.notna(val) and str(val).strip() != "" and not is_numeric(val)]
        if len(non_empty_strings) >= 1:
            header_row_idx = r
            break
            
    if header_row_idx is None:
        header_row_idx = max(0, data_start_row - 1)
        
    # 5. Extract headers
    headers = []
    for col_idx in range(n_cols):
        parts = []
        for r in range(header_row_idx, data_start_row):
            cell_val = df.iloc[r, col_idx]
            cell_str = str(cell_val).strip() if pd.notna(cell_val) else ""
            if cell_str and cell_str.lower() != "nan":
                parts.append(cell_str)
        headers.append(" ".join(parts) if parts else f"col_{col_idx}")
        
    seen = {}
    unique_headers = []
    for h in headers:
        h_clean = h.strip()
        if not h_clean:
            h_clean = "unnamed"
        if h_clean in seen:
            seen[h_clean] += 1
            unique_headers.append(f"{h_clean}_{seen[h_clean]}")
        else:
            seen[h_clean] = 1
            unique_headers.append(h_clean)
            
    return data_start_row, unique_headers


def cache_excel_data_vectors(sid: str, filepath: str):
    """Parses Excel/CSV sheets using pandas and caches raw numeric vectors (lists of floats)
    in SESSION_DATA_CACHE[sid]["flat_vectors"] and SESSION_DATA_CACHE[sid]["raw_excel_data"].
    """
    if not sid or not filepath:
        return
    import pandas as pd
    from pathlib import Path
    import numpy as np
    ext = Path(filepath).suffix.lower()
    
    with SESSION_DATA_CACHE_LOCK:
        if sid not in SESSION_DATA_CACHE:
            SESSION_DATA_CACHE[sid] = {}
        if "flat_vectors" not in SESSION_DATA_CACHE[sid]:
            SESSION_DATA_CACHE[sid]["flat_vectors"] = {}
        if "raw_excel_data" not in SESSION_DATA_CACHE[sid]:
            SESSION_DATA_CACHE[sid]["raw_excel_data"] = {}
            
    sheets_dict = {}
    try:
        if ext in ('.xlsx', '.xlsm', '.xls', '.ods'):
            xl = pd.ExcelFile(filepath)
            for sheet in xl.sheet_names:
                try:
                    df = pd.read_excel(xl, sheet_name=sheet, header=None)
                    sheets_dict[sheet] = df
                except Exception:
                    pass
            xl.close()
        elif ext == '.csv':
            try:
                from file_reader import smart_read_csv
                df = smart_read_csv(filepath, header=None)
                sheets_dict["Sheet1"] = df
            except Exception:
                pass
    except Exception as e:
        _logger.warning(f"[CacheVectors] Failed to read {filepath}: {e}")
        return

    # Process each sheet to find numeric columns
    for sheet_name, df in sheets_dict.items():
        if df.empty:
            continue
        data_start_row, headers = _detect_main_table(df)
        if data_start_row is None or headers is None:
            continue
        n_rows, n_cols = df.shape

        col_vectors = {h: [] for h in headers}
        for r in range(data_start_row, n_rows):
            for col_idx in range(n_cols):
                if col_idx >= len(headers):
                    continue
                h = headers[col_idx]
                val_raw = df.iloc[r, col_idx]
                if pd.isna(val_raw):
                    col_vectors[h].append(None)
                else:
                    try:
                        v = float(val_raw)
                        if np.isnan(v):
                            col_vectors[h].append(None)
                        else:
                            col_vectors[h].append(v)
                    except (ValueError, TypeError):
                        col_vectors[h].append(None)
                        
        valid_cols = {}
        with SESSION_DATA_CACHE_LOCK:
            if sheet_name not in SESSION_DATA_CACHE[sid]["raw_excel_data"]:
                SESSION_DATA_CACHE[sid]["raw_excel_data"][sheet_name] = {}
                
            # Store the original col_vectors preserving None for row-by-row alignment
            SESSION_DATA_CACHE[sid]["raw_excel_data"][sheet_name]["__aligned_vectors__"] = col_vectors
            
            for h, vals in col_vectors.items():
                clean_vals = [v for v in vals if v is not None]
                if len(clean_vals) >= 2:
                    valid_cols[h] = clean_vals
                    SESSION_DATA_CACHE[sid]["raw_excel_data"][sheet_name][h] = clean_vals
                    flat_key = f"{sheet_name}.{h}".lower().replace(" ", "_")
                    SESSION_DATA_CACHE[sid]["flat_vectors"][flat_key] = clean_vals
                    SESSION_DATA_CACHE[sid]["flat_vectors"][h.lower()] = clean_vals
                    
        _logger.info(f"[CacheVectors] Cached {len(valid_cols)} columns from sheet {sheet_name}")
    save_session_cache_to_db(sid)


def find_cached_vector(sid: str, aliases: list) -> list:
    """Fuzzy matches keys in flat_vectors to aliases and returns the first matched list of floats."""
    if not sid:
        return []
    fhash = resolve_cache_key(sid)
    load_session_cache_from_db(fhash)
    with SESSION_DATA_CACHE_LOCK:
        flat = SESSION_DATA_CACHE.get(fhash, {}).get("flat_vectors", {})
        for alias in aliases:
            a_clean = alias.lower().replace(" ", "").replace("_", "")
            for k, vals in flat.items():
                k_clean = k.lower().replace(" ", "").replace("_", "")
                if a_clean == k_clean or a_clean in k_clean or k_clean in a_clean:
                    return vals
    return []


def find_aligned_bca_columns(sid: str):
    """
    Looks through the session cache raw_excel_data to find aligned Depth, Porosity,
    and Permeability columns across any sheet using flexible aliases.
    
    Returns (phi_list, perm_list, depth_list, sheet_name, porosity_is_percent) 
    or (None, None, None, None, False)
    """
    if not sid:
        return None, None, None, None, False
        
    fhash = resolve_cache_key(sid)
    load_session_cache_from_db(fhash)
    
    porosity_aliases = ["porosity", "por", "phit", "phi", "porosity (%)", "por (%)"]
    permeability_aliases = ["k air", "kair", "k_air", "perm", "k (md)", "kh", "ka", "permeability", "k horizontal"]
    depth_aliases = ["depth", "depth (ft)", "depth (m)", "md", "tvd"]
    
    with SESSION_DATA_CACHE_LOCK:
        raw_excel = SESSION_DATA_CACHE.get(fhash, {}).get("raw_excel_data", {})
        if not raw_excel:
            return None, None, None, None, False
            
        # Try sheets in order
        for sheet_name, sheet_dict in raw_excel.items():
            aligned = sheet_dict.get("__aligned_vectors__")
            if not aligned:
                # Fallback to checking other keys in sheet_dict directly if __aligned_vectors__ is not present
                aligned = {k: v for k, v in sheet_dict.items() if isinstance(v, list) and not k.startswith("__")}
            
            if not aligned:
                continue
                
            phi_col = None
            perm_col = None
            depth_col = None
            
            for h in aligned.keys():
                h_clean = re.sub(r'[\s\-_\.\(\)/\\%]+', '', str(h).lower())
                if not phi_col:
                    for alias in porosity_aliases:
                        a_clean = re.sub(r'[\s\-_\.\(\)/\\%]+', '', str(alias).lower())
                        if h_clean == a_clean or a_clean in h_clean or h_clean in a_clean:
                            phi_col = h
                            break
                if not perm_col:
                    for alias in permeability_aliases:
                        a_clean = re.sub(r'[\s\-_\.\(\)/\\%]+', '', str(alias).lower())
                        if h_clean == a_clean or a_clean in h_clean or h_clean in a_clean:
                            perm_col = h
                            break
                if not depth_col:
                    for alias in depth_aliases:
                        a_clean = re.sub(r'[\s\-_\.\(\)/\\%]+', '', str(alias).lower())
                        if h_clean == a_clean or a_clean in h_clean or h_clean in a_clean:
                            depth_col = h
                            break
                            
            if phi_col and perm_col:
                phi_vals = aligned[phi_col]
                perm_vals = aligned[perm_col]
                depth_vals = aligned[depth_col] if depth_col else [float(i+1) for i in range(len(phi_vals))]
                
                # Match lengths to prevent shifts
                max_len = max(len(phi_vals), len(perm_vals), len(depth_vals))
                phi_vals = phi_vals + [None] * (max_len - len(phi_vals))
                perm_vals = perm_vals + [None] * (max_len - len(perm_vals))
                depth_vals = depth_vals + [None] * (max_len - len(depth_vals))
                
                clean_phi = []
                clean_perm = []
                clean_depth = []
                
                for p, k, d in zip(phi_vals, perm_vals, depth_vals):
                    if p is not None and k is not None:
                        try:
                            p_f = float(p)
                            k_f = float(k)
                            d_f = float(d) if d is not None else float(len(clean_phi) + 1)
                            if p_f > 0 and k_f > 0:
                                clean_phi.append(p_f)
                                clean_perm.append(k_f)
                                clean_depth.append(d_f)
                        except (ValueError, TypeError):
                            continue
                            
                if len(clean_phi) >= 2:
                    # Determine if porosity is in percent or fraction
                    max_p = max(clean_phi)
                    is_percent = max_p > 1.0
                    return clean_phi, clean_perm, clean_depth, sheet_name, is_percent
                    
    return None, None, None, None, False


def find_aligned_columns(sid: str, expected_aliases: dict):
    """
    General fuzzy column matcher. expected_aliases is a dict: {param_name: [list_of_aliases]}
    Returns (aligned_data_dict, sheet_name) or None
    """
    if not sid:
        return None
        
    fhash = resolve_cache_key(sid)
    load_session_cache_from_db(fhash)
    
    with SESSION_DATA_CACHE_LOCK:
        raw_excel = SESSION_DATA_CACHE.get(fhash, {}).get("raw_excel_data", {})
        if not raw_excel:
            return None
            
        for sheet_name, sheet_dict in raw_excel.items():
            aligned = sheet_dict.get("__aligned_vectors__")
            if not aligned:
                aligned = {k: v for k, v in sheet_dict.items() if isinstance(v, list) and not k.startswith("__")}
            
            if not aligned:
                continue
                
            matched_cols = {}
            for param, aliases in expected_aliases.items():
                matched_col = None
                for h in aligned.keys():
                    h_clean = re.sub(r'[\s\-_\.\(\)/\\%]+', '', str(h).lower())
                    for alias in aliases:
                        a_clean = re.sub(r'[\s\-_\.\(\)/\\%]+', '', str(alias).lower())
                        if h_clean == a_clean or a_clean in h_clean or h_clean in a_clean:
                            matched_col = h
                            break
                    if matched_col:
                        break
                if matched_col:
                    matched_cols[param] = matched_col
            
            # If we matched enough required columns
            required_count = len(expected_aliases) if len(expected_aliases) <= 2 else len(expected_aliases) - 1
            if len(matched_cols) >= required_count:
                lengths = [len(aligned[col]) for col in matched_cols.values()]
                max_len = max(lengths) if lengths else 0
                
                aligned_data = {}
                for param, col in matched_cols.items():
                    vals = aligned[col]
                    aligned_data[param] = vals + [None] * (max_len - len(vals))
                    
                depth_aliases = ["depth", "depth (ft)", "depth (m)", "md", "tvd"]
                depth_col = None
                for h in aligned.keys():
                    h_clean = re.sub(r'[\s\-_\.\(\)/\\%]+', '', str(h).lower())
                    for alias in depth_aliases:
                        a_clean = re.sub(r'[\s\-_\.\(\)/\\%]+', '', str(alias).lower())
                        if h_clean == a_clean or a_clean in h_clean or h_clean in a_clean:
                            depth_col = h
                            break
                    if depth_col:
                        break
                if depth_col:
                    aligned_data["depth"] = aligned[depth_col] + [None] * (max_len - len(aligned[depth_col]))
                else:
                    aligned_data["depth"] = [float(i+1) for i in range(max_len)]
                    
                return aligned_data, sheet_name
                
    return None


class _MissingParam(Exception):
    """Raised when a required parameter is absent from BOTH the inputs and the
    active session cache. No generic constant is ever substituted."""


def calculate_derived_value(formula_id: str, inputs_str: str, session_id: str):
    # Parse inputs, e.g. "phi=0.15,m=1.85" (NO generic-constant fallbacks)
    inputs = {}
    for part in inputs_str.split(","):
        if "=" in part:
            k, v = part.split("=")
            try:
                inputs[k.strip().lower()] = float(v.strip())
            except Exception:
                pass
            
    # STRICT: no `default` parameter at all. A missing parameter ALWAYS raises
    # _MissingParam — never substitutes a constant, never fabricates provenance.
    def get_param(name: str) -> float:
        name_lower = name.lower()
        if name_lower in inputs:
            return inputs[name_lower]
        # Fallback strictly to validated cache lookup only.
        # Resolve to the content-hash key and hydrate from DB first so any
        # worker (multi-process) sees the upload, not just the one that ingested.
        load_session_cache_from_db(session_id)          # acquires lock itself
        _fhash = resolve_cache_key(session_id)
        with SESSION_DATA_CACHE_LOCK:
            cache = (SESSION_DATA_CACHE.get(_fhash)
                     or SESSION_DATA_CACHE.get(session_id, {}))
            labeled = cache.get("labeled_values", {})
            if name_lower in labeled:
                return float(labeled[name_lower])
            # whole-token (word-boundary) match only — never substring,
            # so 'm' cannot bind to 'rm' or 'cementation_m'.
            for ck, cv in labeled.items():
                if name_lower in re.split(r'[^a-z0-9]+', str(ck).lower()):
                    return float(cv)
        raise _MissingParam(name)

    def opt(name: str):
        """Optional input: returns the value if present in inputs/cache, else None
        (never a fabricated constant). Used only for the archie_sw alternative-input
        chain (Ri vs Ro/Rt vs Rw)."""
        try:
            return get_param(name)
        except _MissingParam:
            return None

    formula_id = formula_id.lower()
    if formula_id == "archie_f":
        a = get_param("a")
        phi = get_param("phi")
        m = get_param("m")
        if phi > 1.0:
            phi /= 100.0
        return a * (phi ** -m)
        
    elif formula_id == "archie_sw":
        n = get_param("n")
        ri = opt("ri")
        if ri is not None:
            return (1.0 / ri) ** (1.0 / n)
        ro = opt("ro")
        rt = opt("rt")
        if ro is not None and rt is not None:
            return (ro / rt) ** (1.0 / n)
        # Fallback Sw = (a * Rw / (Rt * phi**m))**(1/n)
        a = get_param("a")
        rw = get_param("rw")
        rt = get_param("rt")
        phi = get_param("phi")
        m = get_param("m")
        if phi > 1.0: phi /= 100.0
        return (a * rw / (rt * (phi ** m))) ** (1.0 / n)
        
    elif formula_id == "displacement_efficiency":
        sor = get_param("sor")
        swi = get_param("swi")
        if sor > 1.0: sor /= 100.0
        if swi > 1.0: swi /= 100.0
        return (1.0 - swi - sor) / (1.0 - swi)
        
    elif formula_id in ("rqi", "rqi_fzi"):
        perm = get_param("perm")
        phi = get_param("phi")
        if phi > 1.0: phi /= 100.0
        if phi <= 0.0: return 0.0
        import numpy as np
        return 0.0314 * np.sqrt(perm / phi)
        
    elif formula_id == "fzi":
        perm = get_param("perm")
        phi = get_param("phi")
        if phi > 1.0: phi /= 100.0
        if phi <= 0.0 or phi >= 1.0: return 0.0
        import numpy as np
        rqi = 0.0314 * np.sqrt(perm / phi)
        return rqi / (phi / (1.0 - phi))
        
    else:
        raise ValueError(f"Unknown formula: {formula_id}")


def process_provenance_tokens(llm_response_text: str, session_id: str) -> str:
    if not llm_response_text:
        return llm_response_text

    # 1. Parse Cache Lookups: {{val:cache_key}}
    def replace_cache(match):
        cache_key = match.group(1).strip()
        
        def normalize_key(s):
            s = re.sub(r'[^a-zA-Z0-9_]', '_', s.lower())
            s = re.sub(r'_{2,}', '_', s)
            return s.strip('_')
            
        cache_key_norm = normalize_key(cache_key)
        val = None
        load_session_cache_from_db(session_id)          # acquires lock itself
        _fhash = resolve_cache_key(session_id)
        with SESSION_DATA_CACHE_LOCK:
            cache = (SESSION_DATA_CACHE.get(_fhash)
                     or SESSION_DATA_CACHE.get(session_id, {}))
            labeled = cache.get("labeled_values", {})
            
            # Direct match
            if cache_key_norm in labeled:
                val = labeled[cache_key_norm]
            else:
                # Direct match on normalized keys
                for k, v in labeled.items():
                    if normalize_key(k) == cache_key_norm:
                        val = v
                        break
                        
            # Token match fallback
            if val is None:
                for k, v in labeled.items():
                    k_norm = normalize_key(k)
                    if cache_key_norm in k_norm.split('_') or k_norm in cache_key_norm.split('_'):
                        val = v
                        break
                        
        if val is None:
            with SESSION_DATA_CACHE_LOCK:
                gt = cache.get("ground_truth", "")
            if gt:
                match_gt = re.search(rf'(?i)\b{re.escape(cache_key)}\b.*?[:=]\s*(\d+(?:\.\d+)?)', gt)
                if match_gt:
                    val = match_gt.group(1)
                    
        if val is not None:
            try:
                val_float = float(val)
                if val_float.is_integer():
                    val_str = str(int(val_float))
                else:
                    val_str = f"{val_float:.3f}"
            except Exception:
                val_str = str(val)
            # '·' separator, NOT '|': a pipe inside a markdown table cell splits
            # the row into extra columns and corrupts every provenance table.
            return f"{val_str} · CACHED · HIGH"
        return "[unverified — absent from cache]"

    processed = re.sub(r'\{\{val:([^|}]+)\}\}', replace_cache, llm_response_text)

    # 2. Parse Derived Values: {{val:formula_id|inputs}}
    def replace_derived(match):
        formula_id = match.group(1).strip()
        inputs_str = match.group(2).strip()
        try:
            val = calculate_derived_value(formula_id, inputs_str, session_id)
            if val is not None:
                return f"{val:.3f} · DERIVED · HIGH {inputs_str}"
        except _MissingParam:
            return "[unverified — absent from cache]"
        except Exception as e:
            _logger.warning(f"[Provenance] Formula {formula_id} failed: {e}")
        return f"[unverified — math error on {formula_id}]"

    processed = re.sub(r'\{\{val:([^|]+)\|([^}]+)\}\}', replace_derived, processed)

    # Support {{cite:cache_key}}
    def replace_cite(match):
        cache_key = match.group(1).strip()
        return f"*{cache_key}*"
    processed = re.sub(r'\{\{cite:([^}]+)\}\}', replace_cite, processed)

    # 3. Clean up the final markdown tables to be pristine and extremely clean (removing raw tokens and citation tags from cells)
    lines = processed.split("\n")
    in_table = False
    for idx, line in enumerate(lines):
        if re.match(r'^\s*\|(?:\s*:-*:\s*|:-*\s*|[-:\s]*\|)+$', line):
            in_table = True
            continue
        
        if in_table:
            if not line.strip().startswith("|"):
                in_table = False
                continue
                
            cells = line.split("|")
            modified_cells = []
            for cell_idx, cell in enumerate(cells):
                if cell_idx == 0 or cell_idx == len(cells) - 1:
                    modified_cells.append(cell)
                    continue
                    
                cell_strip = cell.strip()
                # Clean CACHED / DERIVED markers from table cells
                if " · CACHED · " in cell_strip:
                    cell_strip = cell_strip.split(" · CACHED · ")[0].strip()
                if " · DERIVED · " in cell_strip:
                    cell_strip = cell_strip.split(" · DERIVED · ")[0].strip()
                if "[unverified" in cell_strip:
                    # Keep raw numbers if present, otherwise output standard empty marker
                    match_num = re.search(r'(-?\d+(?:\.\d+)?)', cell_strip)
                    if match_num:
                        cell_strip = match_num.group(1)
                    else:
                        cell_strip = "-"
                
                modified_cells.append(f" {cell_strip} ")
            lines[idx] = "|".join(modified_cells)
            
    result_text = "\n".join(lines)
    return result_text


# ── SCAL DOC-GEN HELPER ──────────────────────────────────────────────────────

def _scal_doc_summary(extracted: dict) -> str:
    """Compact per-sample scalar summary from SCALFileHandler output.

    Emits only pre-computed scalar values (not raw arrays) so Gemini can
    populate document table rows directly without re-deriving values from
    curves.  Used by both the chat upload path (stored to user_files) and
    generate_document_json (injected into the prompt for the current request).
    """
    samples = extracted.get("samples", {})
    if not isinstance(samples, dict) or not samples:
        return ""
    lines = ["[SCAL PER-SAMPLE SUMMARY — pre-computed values for document tables]"]
    for sample_name, sd in samples.items():
        if not isinstance(sd, dict):
            continue
        lines.append(f"\nSample: {sample_name}")
        # FDAM / Kw-vs-throughput
        if "initial_KL_mD" in sd:
            lines.append(f"  initial_KL_mD = {sd['initial_KL_mD']}")
            lines.append(f"  final_KL_mD = {sd['final_KL_mD']}")
            if sd.get("KL_change_pct") is not None:
                lines.append(f"  KL_change_pct = {sd['KL_change_pct']}")
        # PC / Imbibition (Sor values and signed Pc range)
        if sd.get("Sor_Lab_pct") is not None:
            lines.append(f"  Sor_Lab_pct = {sd['Sor_Lab_pct']}")
        if sd.get("Sor_TC_pct") is not None:
            lines.append(f"  Sor_TC_pct = {sd['Sor_TC_pct']}")
        if sd.get("Pc_psi"):
            lines.append(f"  Pc_min_psi = {min(sd['Pc_psi'])}")
        # MICP
        if sd.get("threshold_pressure_psi") is not None:
            lines.append(f"  threshold_pressure_psi = {sd['threshold_pressure_psi']}")
        d = sd.get("drainage") if isinstance(sd.get("drainage"), dict) else {}
        d_pv = d.get("sat_pv", [])
        if d_pv:
            max_d = max(d_pv)
            if not sd.get("sat_is_percent", True):
                max_d = round(max_d * 100, 2)
            lines.append(f"  max_hg_sat_pct = {max_d}")
        i = sd.get("imbibition") if isinstance(sd.get("imbibition"), dict) else {}
        i_pv = i.get("sat_pv", [])
        if i_pv:
            max_i = max(i_pv)
            if not sd.get("sat_is_percent", True):
                max_i = round(max_i * 100, 2)
            lines.append(f"  max_imb_hg_sat_pct = {max_i}")
    return "\n".join(lines)


# ── LIBRARY HELPERS ───────────────────────────────────────────────────────────

def _chunk_with_overlap(text: str, chunk_words: int = 500, overlap_words: int = 50) -> list[str]:
    """Split text into overlapping word-count chunks."""
    words = text.split()
    if not words:
        return []
    step = max(chunk_words - overlap_words, 1)
    chunks = []
    for i in range(0, len(words), step):
        chunk = " ".join(words[i : i + chunk_words])
        if chunk.strip():
            chunks.append(chunk)
        if i + chunk_words >= len(words):
            break
    return chunks


def _extract_text_for_library(file_bytes: bytes, filename: str) -> str:
    """Extract plain text from PDF, DOCX, or plain text file bytes."""
    ext = Path(filename.lower()).suffix
    if ext == ".pdf":
        return _sfh_extract_pdf(file_bytes)
    if ext in (".docx", ".doc"):
        return _sfh_extract_docx(file_bytes)
    try:
        return file_bytes.decode("utf-8", errors="replace")
    except Exception:
        return ""


def _ingest_library_file(file_bytes: bytes, filename: str, uploader_email: str) -> dict:
    """Blocking: hash-check, extract, chunk, embed, insert. Returns result dict."""
    file_hash = hashlib.sha256(file_bytes).hexdigest()

    # Deduplication check
    existing = db("SELECT filename FROM library_docs WHERE file_hash=?", (file_hash,))
    if existing:
        return {"duplicate": True, "existing_file": existing[0][0]}

    ext = Path(filename.lower()).suffix.lstrip(".")
    data_type = ext.upper() or "UNKNOWN"

    text = _extract_text_for_library(file_bytes, filename)
    if not text.strip():
        return {"error": "Could not extract text from file"}

    chunks = _chunk_with_overlap(text)
    if not chunks:
        return {"error": "No usable text chunks extracted"}

    # Embed all chunks concurrently (massively speeds up ingestion for large docs)
    embedded: list[tuple[str, bytes | None]] = []
    with ThreadPoolExecutor(max_workers=16) as executor:
        futures = [executor.submit(KnowledgeBase._embed, chunk) for chunk in chunks]
        for chunk, fut in zip(chunks, futures):
            try:
                vec = fut.result()
            except Exception as e:
                _logger.warning(f"[Library] Parallel embed error: {e}")
                vec = None
            embedded.append((chunk, vec.tobytes() if vec is not None else None))

    with _get_conn() as (conn, ph):
        cur = conn.cursor()
        try:
            if ph == "?":
                cur.execute(
                    "INSERT INTO library_docs (filename, file_hash, data_type, uploaded_by, created_at) VALUES (?,?,?,?,?)",
                    (filename, file_hash, data_type, uploader_email, time.time()),
                )
                doc_id = cur.lastrowid
            else:
                cur.execute(
                    "INSERT INTO library_docs (filename, file_hash, data_type, uploaded_by, created_at) VALUES (%s,%s,%s,%s,%s) RETURNING id",
                    (filename, file_hash, data_type, uploader_email, time.time()),
                )
                doc_id = cur.fetchone()[0]

            if embedded:
                chunk_data = [(doc_id, chunk_text, emb_bytes, filename) for chunk_text, emb_bytes in embedded]
                cur.executemany(
                    f"INSERT INTO library_chunks (doc_id, chunk_text, embedding, source) VALUES ({ph},{ph},{ph},{ph})",
                    chunk_data,
                )

            conn.commit()
            _LibraryEmbCache.invalidate()
            _logger.info(f"[Library] Ingested '{filename}' — {len(embedded)} chunks (doc_id={doc_id})")
            return {"status": "ingested", "chunks": len(embedded), "doc_id": doc_id}

        except Exception as e:
            conn.rollback()
            _logger.error(f"[Library] Ingest DB error: {e}")
            return {"error": str(e)}



# -- THREAD-SAFE KEY TRACKING --------------------------------------------------

_FAILED_KEYS:      dict[str, dict] = {}

_FAILED_KEYS_LOCK: threading.Lock  = threading.Lock()





def _mark_key_failed(key: str, is_hard: bool = False) -> None:

    with _FAILED_KEYS_LOCK:

        _FAILED_KEYS[key] = {"ts": time.time(), "wait": 3600 if is_hard else 60}





def _key_healthy(key: str) -> bool:

    with _FAILED_KEYS_LOCK:

        f = _FAILED_KEYS.get(key, {})

    return (time.time() - f.get("ts", 0)) >= f.get("wait", 0)





# -- SYSTEM PROMPT -------------------------------------------------------------

from pathlib import Path
SYSTEM_PROMPT = (Path(__file__).parent / "prompts" / "hviel_system_prompt.md").read_text(encoding="utf-8")








# -- GEMINI TOOL DECLARATIONS --------------------------------------------------

_HVIEL_TOOLS = [

    {

        "function_declarations": [

            {

                "name": "calculate_petrophysics_properties",

                "description": "**MANDATORY for centrifuge Hassler-Brunner / Forbes corrections and for FZI/RQI calculations. Do not produce Pc(Sw) or RQI values without calling this tool first.** Calculation Engine for SCAL Tracks A, B, D, E. Does NOT generate charts, only returns calculated JSON data.",

                "parameters": {

                    "type": "OBJECT",

                    "properties": {

                        "script": {"type": "STRING", "description": "One of: petrophysics.py, micp_skill.py, centrifuge_skill.py"},

                        "model":  {"type": "STRING", "description": "For petrophysics.py: regress_archie_m_a, regress_archie_n, rqi_fzi. For centrifuge: pc_only, full, hassler_brunner. rqi_fzi params: {phi: [fractions 0-1], perm: [mD], depth: [optional array]}. Returns full per-sample table with HU classification."},

                        "params": {"type": "OBJECT", "description": "Parameters required for the selected script and model."}

                    },

                    "required": ["script", "params"]

                }

            },

            {

                "name": "execute_python_simulation",

                "description": "Universal petrophysical simulation (Brooks-Corey, 1D Kr curves, 2D IMPES reservoir waterflood). Returns JSON for PRC plotting.",

                "parameters": {

                    "type": "OBJECT",

                    "properties": {

                        "model":  {"type": "STRING"},

                        "mode":   {"type": "STRING"},

                        "params": {

                            "type": "OBJECT",

                            "properties": {

                                "swr":     {"type": "NUMBER"}, "snr": {"type": "NUMBER"},

                                "krw_max": {"type": "NUMBER"}, "kro_max": {"type": "NUMBER"},

                                "nw":      {"type": "NUMBER"}, "no": {"type": "NUMBER"},

                                "nx":      {"type": "NUMBER"}, "ny": {"type": "NUMBER"},

                                "steps":   {"type": "NUMBER"},

                            },

                        },

                    },

                    "required": ["model", "mode", "params"],

                },

            },

            {

                "name": "generate_mermaid_diagram",

                "description": "Generates Mermaid.js diagram code for complex workflows.",

                "parameters": {

                    "type": "OBJECT",

                    "properties": {

                        "type":    {"type": "STRING"},

                        "content": {"type": "STRING"},

                    },

                    "required": ["type", "content"],

                },

            },

            {

                "name": "fit_petrophysical_curve",

                "description": (

                    "**MANDATORY before reporting any fitted parameter (Archie n, m, a, MICP Pe/Pd/modal radius, Corey exponents, J-function values). Never report these values without calling this tool first. If the tool fails, report the failure  -  do not estimate.** "

                    "Fits raw SCAL lab data to standard petrophysical models. Select model by curve type:\n"

                    "  model='brooks_corey' or 'let'  ->  Relative Permeability (pass sw, krw, kro arrays).\n"

                    "  model='micp'  ->  Mercury Injection (pass pc=[psia], s_hg=[fraction 0-1]). "

                    "For imbibition (recovery) cycle: also pass pc_imb=[psia], s_hg_imb=[fraction]. "

                    "Auto-generates log-scale Pc curve (drainage solid, imbibition dashed) + PSD.\n"

                    "  model='ri'  ->  Resistivity Index Archie fit (pass sw=[...], ri=[...]). Log-log plot, fits n exponent.\n"

                    "  model='ff'  ->  Formation Factor Archie fit (pass porosity=[...], ff=[...]). Log-log plot, fits m and a.\n"

                    "  model='jfunction'  ->  Leverett J-Function (pass sw=[...], pc=[psia], k_md=X, phi_val=Y, ift_cos_theta=26.5).\n"

                    "  model='pc_centrifuge'  ->  Capillary Pressure direct (pass sw=[...], pc=[psia values]).\n"

                    "  model='overburden'  ->  Compaction curves (pass pressure=[psia], porosity=[...], perm=[mD]). Dual-axis.\n"

                    "  model='poroperm'  ->  Porosity vs Permeability cross-plot with log-linear fit (pass porosity=[...], perm=[mD]).\n"

                    "  model='poroperm_depth'  ->  Porosity & Permeability vs Depth (pass depth=[...], porosity=[...], perm=[mD]). Dual-axis.\n"

                    "Pass sample_name='Core-1' to label multi-sample charts."

                ),

                "parameters": {

                    "type": "OBJECT",

                    "properties": {

                        "model":         {"type": "STRING"},

                        "sw":            {"type": "ARRAY", "items": {"type": "NUMBER"}},

                        "krw":           {"type": "ARRAY", "items": {"type": "NUMBER"}},

                        "kro":           {"type": "ARRAY", "items": {"type": "NUMBER"}},

                        "pc":            {"type": "ARRAY", "items": {"type": "NUMBER"}},

                        "s_hg":         {"type": "ARRAY", "items": {"type": "NUMBER"}},

                        "pc_imb":       {"type": "ARRAY", "items": {"type": "NUMBER"}},

                        "s_hg_imb":     {"type": "ARRAY", "items": {"type": "NUMBER"}},

                        "ri":            {"type": "ARRAY", "items": {"type": "NUMBER"}},

                        "ff":            {"type": "ARRAY", "items": {"type": "NUMBER"}},

                        "porosity":      {"type": "ARRAY", "items": {"type": "NUMBER"}},

                        "perm":          {"type": "ARRAY", "items": {"type": "NUMBER"}},

                        "pressure":      {"type": "ARRAY", "items": {"type": "NUMBER"}},

                        "depth":         {"type": "ARRAY", "items": {"type": "NUMBER"}},

                        "k_md":          {"type": "NUMBER"},

                        "phi_val":       {"type": "NUMBER"},

                        "ift_cos_theta": {"type": "NUMBER"},

                        "sample_name":   {"type": "STRING"},

                    },

                    "required": ["model"],

                },

            },

            {

                "name": "agentic_history_matching",

                "description": "Simulated Annealing history matching on SCAL lab data.",

                "parameters": {

                    "type": "OBJECT",

                    "properties": {

                        "sw":  {"type": "ARRAY", "items": {"type": "NUMBER"}},

                        "krw": {"type": "ARRAY", "items": {"type": "NUMBER"}},

                        "kro": {"type": "ARRAY", "items": {"type": "NUMBER"}},

                    },

                    "required": ["sw", "krw", "kro"],

                },

            },

            {

                "name": "generate_executive_report",

                "description": (

                    "**REFUSE this call if no SCAL analysis tools have been invoked in the current session. A report cannot be generated when no analysis has been performed. Return an error message asking the user to upload data and run analysis first.** "

                    "Generates a professional PRC Executive SCAL Report (.docx) for the current "

                    "engineering session. Call this when the user asks for a report, summary "

                    "document, or engineering deliverable. Pass the well name extracted from the "

                    "conversation context."

                ),

                "parameters": {

                    "type": "OBJECT",

                    "properties": {

                        "well_name":    {"type": "STRING"},

                        "report_title": {"type": "STRING"},

                    },

                    "required": ["well_name"],

                },

            },

            {

                "name": "get_audit_history",

                "description": "Retrieves the historical record of physics audits (the Auditor's Ledger) for the current session.",

                "parameters": {"type": "OBJECT", "properties": {}},

            },

            {
                "name": "sandbox_fit_brooks_corey",
                "description": "Fits Brooks-Corey relative permeability curves (exponent nw and no) to Sw, Krw, Kro data in a secure physics sandbox. Automatically enforces physical constraints and corrects anomalies.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "sw": {"type": "ARRAY", "items": {"type": "NUMBER"}},
                        "krw": {"type": "ARRAY", "items": {"type": "NUMBER"}},
                        "kro": {"type": "ARRAY", "items": {"type": "NUMBER"}},
                        "swi": {"type": "NUMBER"},
                        "sor": {"type": "NUMBER"},
                        "krw_max": {"type": "NUMBER"},
                        "kro_max": {"type": "NUMBER"},
                        "sample_name": {"type": "STRING"}
                    },
                    "required": ["sw", "krw", "kro", "swi", "sor"]
                }
            },

            {
                "name": "sandbox_fit_archie",
                "description": "Fits Archie parameters (a, m or b, n) securely in a sandbox. model_type='FF' fits a/m from porosity vs formation factor. model_type='RI' fits b/n from Sw vs resistivity index.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "x": {"type": "ARRAY", "items": {"type": "NUMBER"}},
                        "y": {"type": "ARRAY", "items": {"type": "NUMBER"}},
                        "model_type": {"type": "STRING"},
                        "sample_name": {"type": "STRING"}
                    },
                    "required": ["x", "y", "model_type"]
                }
            },

            {
                "name": "hybrid_geological_search",
                "description": "Hybrid geological knowledge search: fuses the SQLite Geological Knowledge Graph (Libyan basins, formations, lithologies, fluids, wells) with vector analog-well retrieval. Mention basin/formation/well names in query_text to anchor the graph traversal; pass porosity (porous_low/porous_high, fraction) and permeability (perm_low/perm_high, mD) windows to fetch analog wells from the vector store.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "query_text": {"type": "STRING"},
                        "porous_low": {"type": "NUMBER"},
                        "porous_high": {"type": "NUMBER"},
                        "perm_low": {"type": "NUMBER"},
                        "perm_high": {"type": "NUMBER"},
                        "depth_limit": {"type": "INTEGER"},
                        "n_results": {"type": "INTEGER"}
                    },
                    "required": ["query_text"]
                }
            },

        ]

    }

]



_PETRO_KEYS = frozenset({

    "swr","snr","krw_max","kro_max","nw","no","Lw","Ew","Tw","Lo","Eo","To",

    "nx","ny","dx","dy","dz","dt","steps","porosity","perm","swi","pi","q_inj","mu_w","mu_o",

})



import contextvars
from pydantic import BaseModel, Field
from genkit.ai import Genkit
from genkit.plugins.google_genai import GoogleAI
from genkit.ai._server import ServerSpec

class TLSContext:
    def __init__(self):
        self._var = contextvars.ContextVar("tls_context", default=None)
    def _get_dict(self):
        d = self._var.get()
        if d is None:
            d = {}
            self._var.set(d)
        return d
    def __getattr__(self, name):
        d = self._get_dict()
        if name in d:
            return d[name]
        raise AttributeError(f"'TLSContext' object has no attribute '{name}'")
    def __setattr__(self, name, value):
        if name == "_var":
            super().__setattr__(name, value)
        else:
            d = self._get_dict()
            d[name] = value
    def __delattr__(self, name):
        d = self._get_dict()
        if name in d:
            del d[name]
        else:
            raise AttributeError(f"'TLSContext' object has no attribute '{name}'")

_tls = TLSContext()

# Initialize Google Genkit Plugin and Client
google_ai_plugin = GoogleAI(api_key=GEMINI_KEY_POOL[0])
ai = Genkit(plugins=[google_ai_plugin], reflection_server_spec=ServerSpec(port=3105))

# Define tool schemas for Genkit

class CalculatePetrophysicsInput(BaseModel):
    script: str = Field(description="One of: petrophysics.py, micp_skill.py, centrifuge_skill.py")
    model: Optional[str] = Field(None, description="For petrophysics.py: regress_archie_m_a, regress_archie_n, rqi_fzi. For centrifuge: pc_only, full, hassler_brunner. rqi_fzi params: {phi: [fractions 0-1], perm: [mD], depth: [optional array]}. Returns full per-sample table with HU classification.")
    params: dict = Field(description="Parameters required for the selected script and model.")

class ExecutePythonSimulationParamsInput(BaseModel):
    swr: Optional[float] = None
    snr: Optional[float] = None
    krw_max: Optional[float] = None
    kro_max: Optional[float] = None
    nw: Optional[float] = None
    no: Optional[float] = None
    nx: Optional[float] = None
    ny: Optional[float] = None
    steps: Optional[float] = None

class ExecutePythonSimulationInput(BaseModel):
    model: str
    mode: str
    params: ExecutePythonSimulationParamsInput

class GenerateMermaidDiagramInput(BaseModel):
    type: str
    content: str

class FitPetrophysicalCurveInput(BaseModel):
    model: str
    sw: Optional[list[float]] = None
    krw: Optional[list[float]] = None
    kro: Optional[list[float]] = None
    pc: Optional[list[float]] = None
    s_hg: Optional[list[float]] = None
    pc_imb: Optional[list[float]] = None
    s_hg_imb: Optional[list[float]] = None
    ri: Optional[list[float]] = None
    ff: Optional[list[float]] = None
    porosity: Optional[list[float]] = None
    perm: Optional[list[float]] = None
    pressure: Optional[list[float]] = None
    depth: Optional[list[float]] = None
    k_md: Optional[float] = None
    phi_val: Optional[float] = None
    ift_cos_theta: Optional[float] = None
    sample_name: Optional[str] = None

class AgenticHistoryMatchingInput(BaseModel):
    sw: list[float]
    krw: list[float]
    kro: list[float]

class GenerateExecutiveReportInput(BaseModel):
    well_name: str
    report_title: Optional[str] = None

class GetAuditHistoryInput(BaseModel):
    session_id: Optional[str] = Field(None, description="Optional session ID to retrieve audit history for")

@ai.tool(name="calculate_petrophysics_properties", description="**MANDATORY for centrifuge Hassler-Brunner / Forbes corrections and for FZI/RQI calculations. Do not produce Pc(Sw) or RQI values without calling this tool first.** Calculation Engine for SCAL Tracks A, B, D, E. Does NOT generate charts, only returns calculated JSON data.")
def calculate_petrophysics_properties_tool(input: CalculatePetrophysicsInput) -> str:
    return "Calculated"

@ai.tool(name="execute_python_simulation", description="Universal petrophysical simulation (Brooks-Corey, 1D Kr curves, 2D IMPES reservoir waterflood). Returns JSON for PRC plotting.")
def execute_python_simulation_tool(input: ExecutePythonSimulationInput) -> str:
    return "Simulated"

@ai.tool(name="generate_mermaid_diagram", description="Generates Mermaid.js diagram code for complex workflows.")
def generate_mermaid_diagram_tool(input: GenerateMermaidDiagramInput) -> str:
    return "Generated"

@ai.tool(name="fit_petrophysical_curve", description="**MANDATORY before reporting any fitted parameter (Archie n, m, a, MICP Pe/Pd/modal radius, Corey exponents, J-function values). Never report these values without calling this tool first. If the tool fails, report the failure  -  do not estimate.** Fits raw SCAL lab data to standard petrophysical models. Select model by curve type:\n  model='brooks_corey' or 'let'  ->  Relative Permeability (pass sw, krw, kro arrays).\n  model='micp'  ->  Mercury Injection (pass pc=[psia], s_hg=[fraction 0-1]). For imbibition (recovery) cycle: also pass pc_imb=[psia], s_hg_imb=[fraction]. Auto-generates log-scale Pc curve (drainage solid, imbibition dashed) + PSD.\n  model='ri'  ->  Resistivity Index Archie fit (pass sw=[...], ri=[...]). Log-log plot, fits n exponent.\n  model='ff'  ->  Formation Factor Archie fit (pass porosity=[...], ff=[...]). Log-log plot, fits m and a.\n  model='jfunction'  ->  Leverett J-Function (pass sw=[...], pc=[psia], k_md=X, phi_val=Y, ift_cos_theta=26.5).\n  model='pc_centrifuge'  ->  Capillary Pressure direct (pass sw=[...], pc=[psia values]).\n  model='overburden'  ->  Compaction curves (pass pressure=[psia], porosity=[...], perm=[mD]). Dual-axis.\n  model='poroperm'  ->  Porosity vs Permeability cross-plot with log-linear fit (pass porosity=[...], perm=[mD]).\n  model='poroperm_depth'  ->  Porosity & Permeability vs Depth (pass depth=[...], porosity=[...], perm=[mD]). Dual-axis.\nPass sample_name='Core-1' to label multi-sample charts.")
def fit_petrophysical_curve_tool(input: FitPetrophysicalCurveInput) -> str:
    return "Fitted"

@ai.tool(name="agentic_history_matching", description="Simulated Annealing history matching on SCAL lab data.")
def agentic_history_matching_tool(input: AgenticHistoryMatchingInput) -> str:
    return "Matched"

@ai.tool(name="generate_executive_report", description="**REFUSE this call if no SCAL analysis tools have been invoked in the current session. A report cannot be generated when no analysis has been performed. Return an error message asking the user to upload data and run analysis first.** Generates a professional PRC Executive SCAL Report (.docx) for the current engineering session. Call this when the user asks for a report, summary document, or engineering deliverable. Pass the well name extracted from the conversation context.")
def generate_executive_report_tool(input: GenerateExecutiveReportInput) -> str:
    return "Report generated"

@ai.tool(name="get_audit_history", description="Retrieves the historical record of physics audits (the Auditor's Ledger) for the current session.")
def get_audit_history_tool(input: GetAuditHistoryInput) -> str:
    return "Audits retrieved"

class SandboxFitBrooksCoreyInput(BaseModel):
    sw: list[float]
    krw: list[float]
    kro: list[float]
    swi: float
    sor: float
    krw_max: Optional[float] = 1.0
    kro_max: Optional[float] = 1.0
    sample_name: Optional[str] = None

class SandboxFitArchieInput(BaseModel):
    x: list[float]
    y: list[float]
    model_type: str
    sample_name: Optional[str] = None

@ai.tool(name="sandbox_fit_brooks_corey", description="Fits Brooks-Corey relative permeability curves (exponent nw and no) to Sw, Krw, Kro data in a secure physics sandbox. Automatically enforces physical constraints and corrects anomalies.")
def sandbox_fit_brooks_corey_tool(input: SandboxFitBrooksCoreyInput) -> str:
    import json
    from physics_sandbox import PhysicsSandbox
    sandbox = PhysicsSandbox()
    fit_res = sandbox.fit_brooks_corey(
        sw=input.sw,
        krw=input.krw,
        kro=input.kro,
        swi=input.swi,
        sor=input.sor,
        krw_max=input.krw_max,
        kro_max=input.kro_max,
    )
    if input.sample_name:
        fit_res["sample_name"] = input.sample_name
    return json.dumps(fit_res)

@ai.tool(name="sandbox_fit_archie", description="Fits Archie parameters (a, m or b, n) securely in a sandbox. model_type='FF' fits a/m from porosity vs formation factor. model_type='RI' fits b/n from Sw vs resistivity index.")
def sandbox_fit_archie_tool(input: SandboxFitArchieInput) -> str:
    import json
    from physics_sandbox import PhysicsSandbox
    sandbox = PhysicsSandbox()
    fit_res = sandbox.fit_archie(x=input.x, y=input.y, model_type=input.model_type)
    if input.sample_name:
        fit_res["sample_name"] = input.sample_name
    return json.dumps(fit_res)

class HybridGeologicalSearchInput(BaseModel):
    query_text: str
    porous_low: Optional[float] = None
    porous_high: Optional[float] = None
    perm_low: Optional[float] = None
    perm_high: Optional[float] = None
    depth_limit: Optional[int] = 1
    n_results: Optional[int] = 3

@ai.tool(name="hybrid_geological_search", description="Hybrid geological knowledge search: fuses the SQLite Geological Knowledge Graph (Libyan basins, formations, lithologies, fluids, wells) with vector analog-well retrieval. Mention basin/formation/well names in query_text to anchor the graph traversal; pass porosity (porous_low/porous_high, fraction) and permeability (perm_low/perm_high, mD) windows to fetch analog wells from the vector store.")
def hybrid_geological_search_tool(input: HybridGeologicalSearchInput) -> str:
    import json
    from geological_graph import GeologicalGraph
    from rag_database import RAGDatabase
    graph = GeologicalGraph(db_path=settings.graph_db_path, seed=True)
    retriever = RAGDatabase()
    porous_range = (
        (float(input.porous_low), float(input.porous_high))
        if input.porous_low is not None and input.porous_high is not None else None
    )
    perm_range = (
        (float(input.perm_low), float(input.perm_high))
        if input.perm_low is not None and input.perm_high is not None else None
    )
    res = graph.hybrid_search(
        query_text=input.query_text,
        porous_range=porous_range,
        perm_range=perm_range,
        retriever=retriever,
        depth_limit=input.depth_limit or 1,
        n_results=input.n_results or 3,
    )
    return json.dumps(res)

# Compatibility Wrapper Classes for Genkit response to Gemini SDK response mapping

class GeminiPartCompat:
    def __init__(self, part):
        self._part = part

    @property
    def text(self) -> Optional[str]:
        p = self._part
        if hasattr(p, "text") and p.text is not None:
            return p.text
        if hasattr(p, "root"):
            r = p.root
            if hasattr(r, "text") and r.text is not None:
                return r.text
        return None

    @property
    def function_call(self):
        p = self._part
        tr = None
        if hasattr(p, "tool_request") and p.tool_request is not None:
            tr = p.tool_request
        elif hasattr(p, "root"):
            r = p.root
            if hasattr(r, "tool_request") and r.tool_request is not None:
                tr = r.tool_request
        
        if tr:
            class FuncCallCompat:
                def __init__(self, name, args):
                    self.name = name
                    self.args = args
            return FuncCallCompat(getattr(tr, "name", ""), getattr(tr, "input", {}))
        return None

class GeminiContentCompat:
    def __init__(self, message_or_content):
        self._msg = message_or_content
        parts_list = []
        if message_or_content:
            if hasattr(message_or_content, "content") and message_or_content.content:
                parts_list = message_or_content.content
            elif hasattr(message_or_content, "parts") and message_or_content.parts:
                parts_list = message_or_content.parts
        self.parts = [GeminiPartCompat(p) for p in parts_list]

class GeminiCandidateCompat:
    def __init__(self, candidate_or_message):
        self.content = GeminiContentCompat(candidate_or_message)

class GeminiUsageMetadataCompat:
    def __init__(self, usage):
        self._usage = usage

    @property
    def prompt_token_count(self) -> int:
        if self._usage and getattr(self._usage, "input_tokens", None) is not None:
            return int(self._usage.input_tokens)
        return 0

    @property
    def candidates_token_count(self) -> int:
        if self._usage and getattr(self._usage, "output_tokens", None) is not None:
            return int(self._usage.output_tokens)
        return 0

class GeminiResponseCompat:
    def __init__(self, genkit_resp):
        self._resp = genkit_resp
        self.candidates = [GeminiCandidateCompat(getattr(genkit_resp, "message", None))]
        self.usage_metadata = GeminiUsageMetadataCompat(getattr(genkit_resp, "usage", None))

    @property
    def text(self) -> str:
        if hasattr(self._resp, "text"):
            return self._resp.text
        parts = []
        msg = getattr(self._resp, "message", None)
        if msg and hasattr(msg, "content") and msg.content:
            for p in msg.content:
                if hasattr(p, "text") and p.text:
                    parts.append(p.text)
                elif hasattr(p, "root") and hasattr(p.root, "text") and p.root.text:
                    parts.append(p.root.text)
        return "".join(parts)

class GeminiChunkCompat:
    def __init__(self, genkit_chunk):
        self._chunk = genkit_chunk
        class MockContent:
            def __init__(self, parts):
                self.parts = parts
        class MockCandidate:
            def __init__(self, parts):
                self.content = MockContent(parts)
        
        parts_list = getattr(genkit_chunk, "content", []) or []
        self.candidates = [MockCandidate([GeminiPartCompat(p) for p in parts_list])]
        self.usage_metadata = GeminiUsageMetadataCompat(getattr(genkit_chunk, "usage", None))

def _add_breadcrumb(msg: str):
    if not hasattr(_tls, "breadcrumbs"):
        _tls.breadcrumbs = []
    _tls.breadcrumbs.append({
        "timestamp": time.time(),
        "step": msg
    })

def _log_api_usage(session_id: str, model: str, prompt_tokens: int, completion_tokens: int):
    # Calculate cost (Standard rates per 1M tokens)
    in_rate = 1.25 if "pro" in model else 0.075
    out_rate = 5.00 if "pro" in model else 0.30
    cost = ((prompt_tokens * in_rate) + (completion_tokens * out_rate)) / 1_000_000
    
    try:
        db("INSERT INTO api_metrics (session_id, timestamp, model, prompt_tokens, completion_tokens, cost_usd) VALUES (?, ?, ?, ?, ?, ?)",
           (session_id, time.time(), model, prompt_tokens, completion_tokens, cost))
    except Exception as e:
        _logger.warning(f"[CostTracker] Failed to insert metrics: {e}")

def _extract_and_log_corrections(session_id: str, email: str, text: str) -> str:
    # Pattern to find [CORRECTION: issue | value]
    pattern = r"\[CORRECTION:\s*(.*?)\s*\|\s*(.*?)\s*\]"
    matches = re.findall(pattern, text)
    for issue, val in matches:
        try:
            db("INSERT INTO user_corrections (session_id, user_email, original_issue, corrected_value, timestamp) VALUES (?, ?, ?, ?, ?)",
               (session_id, email, issue.strip(), val.strip(), time.time()))
        except Exception as e:
            _logger.warning(f"[LearningLoop] Failed to store correction: {e}")
    # Strip the tags from the final user-facing text
    return re.sub(pattern, "", text).strip()





# ===================== NVIDIA NIM tool-calling backend ====================== #
# Genkit/Gemini chat path replaced by direct NVIDIA NIM calls. The big chat
# tool-loop downstream is untouched: these helpers return genai-shaped shims
# (resp.candidates[0].content.parts with .text / .function_call(.name,.args)).
import urllib.request as _nv_urllib
import urllib.error as _nv_urlerr


class _NvFuncCall:
    def __init__(self, name, args):
        self.name = name
        self.args = args or {}


class _NvPart:
    def __init__(self, text=None, func=None):
        self._text = text
        self._func = func

    @property
    def text(self):
        return self._text

    @property
    def function_call(self):
        return self._func


class _NvContent:
    def __init__(self, parts):
        self.parts = parts


class _NvCandidate:
    def __init__(self, parts):
        self.content = _NvContent(parts)


class _NvUsage:
    def __init__(self, pt, ct):
        self.prompt_token_count = pt
        self.candidates_token_count = ct


class _NvResponse:
    def __init__(self, parts, usage):
        self.candidates = [_NvCandidate(parts)]
        self.usage_metadata = usage

    @property
    def text(self):
        return "".join(p.text for p in self.candidates[0].content.parts if p.text)


def _nv_lower_schema(s):
    """Recursively lowercase Gemini uppercase JSON-schema type strings for OpenAI."""
    if isinstance(s, dict):
        out = {}
        for k, v in s.items():
            if k == "type" and isinstance(v, str):
                out[k] = v.lower()
            elif k == "properties" and isinstance(v, dict):
                out[k] = {pk: _nv_lower_schema(pv) for pk, pv in v.items()}
            elif k == "items":
                out[k] = _nv_lower_schema(v)
            else:
                out[k] = _nv_lower_schema(v) if isinstance(v, (dict, list)) else v
        return out
    if isinstance(s, list):
        return [_nv_lower_schema(x) for x in s]
    return s


_NVIDIA_TOOLS_CACHE = None


def _nvidia_tools():
    global _NVIDIA_TOOLS_CACHE
    if _NVIDIA_TOOLS_CACHE is None:
        tools = []
        for group in _HVIEL_TOOLS:
            for fd in group.get("function_declarations", []):
                tools.append({
                    "type": "function",
                    "function": {
                        "name": fd["name"],
                        "description": fd.get("description", ""),
                        "parameters": _nv_lower_schema(fd.get("parameters") or {"type": "object", "properties": {}}),
                    },
                })
        _NVIDIA_TOOLS_CACHE = tools
    return _NVIDIA_TOOLS_CACHE


def _nv_config_unpack(config):
    system_instruction = None
    temperature = 0.2
    want_tools = False
    if config:
        si = getattr(config, "system_instruction", None)
        if si:
            if isinstance(si, str):
                system_instruction = si
            elif hasattr(si, "parts") and si.parts:
                system_instruction = "".join(p.text for p in si.parts if getattr(p, "text", None))
            else:
                system_instruction = str(si)
        if getattr(config, "temperature", None) is not None:
            temperature = config.temperature
        if getattr(config, "tools", None):
            want_tools = True
    return system_instruction, temperature, want_tools


def _nv_contents_to_neutral(contents):
    """genai Content list -> neutral [{role, parts:[{text}|{tool_request}|{tool_response}]}].
    file_data parts are intentionally dropped (NVIDIA has no Files API; the
    deterministic ground-truth extraction is already injected as prompt text)."""
    messages_data = []
    for c in contents:
        role_str = getattr(c, "role", "user")
        role = "model" if role_str == "model" else "user"
        parts_data = []
        for p in getattr(c, "parts", []) or []:
            if hasattr(p, "text") and p.text:
                parts_data.append({"text": p.text})
            elif hasattr(p, "function_call") and p.function_call:
                parts_data.append({"tool_request": {"name": p.function_call.name, "input": dict(p.function_call.args or {})}})
            elif hasattr(p, "function_response") and p.function_response:
                parts_data.append({"tool_response": {"name": p.function_response.name, "output": p.function_response.response}})
        if parts_data:
            messages_data.append({"role": role, "parts": parts_data})
    return messages_data


def _nv_messages_from_neutral(messages_data, system_instruction):
    """Neutral messages -> OpenAI chat messages, synthesizing tool_call ids."""
    oa = []
    if system_instruction:
        oa.append({"role": "system", "content": system_instruction})
    pending_ids = []
    counter = 0
    for m in messages_data:
        role = m.get("role", "user")
        parts = m.get("parts", []) or []
        texts = [p["text"] for p in parts if "text" in p]
        treqs = [p["tool_request"] for p in parts if "tool_request" in p]
        tresps = [p["tool_response"] for p in parts if "tool_response" in p]
        if role == "model":
            content = "".join(texts)
            tool_calls = []
            for tr in treqs:
                cid = "call_%d" % counter
                counter += 1
                pending_ids.append(cid)
                tool_calls.append({
                    "id": cid,
                    "type": "function",
                    "function": {"name": tr.get("name", ""), "arguments": _json.dumps(tr.get("input") or {})},
                })
            msg = {"role": "assistant"}
            if tool_calls:
                msg["content"] = content or None
                msg["tool_calls"] = tool_calls
            else:
                msg["content"] = content
            oa.append(msg)
        else:
            if tresps:
                for tr in tresps:
                    if pending_ids:
                        cid = pending_ids.pop(0)
                    else:
                        cid = "call_%d" % counter
                        counter += 1
                    out = tr.get("output")
                    oa.append({
                        "role": "tool",
                        "tool_call_id": cid,
                        "content": out if isinstance(out, str) else _json.dumps(out),
                    })
                if texts:
                    oa.append({"role": "user", "content": "".join(texts)})
            else:
                oa.append({"role": "user", "content": "".join(texts)})
    return oa


def _nvidia_generate(messages_data, system_instruction, temperature, want_tools, max_tokens=4096):
    global _nvidia_key_idx
    if not NVIDIA_KEY_POOL:
        raise RuntimeError("No NVIDIA API keys configured (set NVIDIA_API_KEY).")
    oa_messages = _nv_messages_from_neutral(messages_data, system_instruction)
    # Context-overflow guard: a large multi-sheet workbook's un-truncated ground-truth
    # can exceed the model context window (gpt-oss-120b ~131K tokens), making NVIDIA
    # compute a negative output budget -> 400 "max_tokens must be at least 1". Cap the
    # combined input by truncating the single largest message so the prompt fits.
    _MAX_INPUT_CHARS = 170000  # dense numeric tables tokenize heavily; keep well under gpt-oss 131K ctx
    _total = sum(len(m.get("content") or "") for m in oa_messages)
    if _total > _MAX_INPUT_CHARS:
        # The ground-truth is injected into BOTH the system and user messages, so the
        # bloat is split across multiple large blocks. Shrink EVERY oversized message
        # proportionally so the combined input lands under the cap (truncating only the
        # single largest would leave the other(s) and still overflow).
        # Keep head + tail, drop the middle. Truncating from the tail alone silently
        # deletes whatever was appended last -- for the system message that's the
        # refusal/formatting rules and SYSTEM_PROMPT (appended after the ground-truth
        # dump), and for the user message that's the actual "[USER REQUEST]: ..." line
        # and the "MANDATORY SYSTEM OVERRIDE" note (appended after extracted_context).
        # A tail-only cut left the model with a bare data dump and no instructions or
        # question, so it fell back to generic textbook answers instead of grounding.
        _ratio = _MAX_INPUT_CHARS / float(_total)
        for _m in oa_messages:
            _c = _m.get("content")
            if isinstance(_c, str) and len(_c) > 2000:
                _keep = max(2000, int(len(_c) * _ratio))
                if _keep < len(_c):
                    _marker = (
                        "\n\n[... middle content truncated to fit the model context window; "
                        "ask about a specific sheet/sample for its full detail ...]\n\n"
                    )
                    _budget = max(0, _keep - len(_marker))
                    _head_len = int(_budget * 0.65)
                    _tail_len = _budget - _head_len
                    if _tail_len > 0:
                        _m["content"] = _c[:_head_len] + _marker + _c[-_tail_len:]
                    else:
                        _m["content"] = _c[:_keep] + _marker
        try:
            _new = sum(len(m.get("content") or "") for m in oa_messages)
            _logger.warning("[NVIDIA] input %d chars > %d; truncated to ~%d." % (_total, _MAX_INPUT_CHARS, _new))
        except Exception:
            pass
    payload = {
        "model": NVIDIA_MODEL,
        "temperature": 0.2 if temperature is None else float(temperature),
        "top_p": 0.95,
        "max_tokens": max_tokens,
        "stream": False,
        # gpt-oss is a reasoning model; "low" effort keeps latency down so large
        # multi-sheet uploads finish inside the chat timeout.
        "reasoning_effort": "low",
        "messages": oa_messages,
    }
    if want_tools:
        payload["tools"] = _nvidia_tools()
        payload["tool_choice"] = "auto"
    try:
        _logger.info("[NVIDIA] generate -> model=%s tools=%s msgs=%d" % (NVIDIA_MODEL, want_tools, len(payload["messages"])))
    except Exception:
        pass
    body = _json.dumps(payload).encode("utf-8")
    errors = []
    last_exc = None
    for _ in range(len(NVIDIA_KEY_POOL)):
        with _nvidia_key_lock:
            key = NVIDIA_KEY_POOL[_nvidia_key_idx % len(NVIDIA_KEY_POOL)]
        try:
            req = _nv_urllib.Request(NVIDIA_BASE_URL, data=body, method="POST", headers={
                "accept": "application/json",
                "content-type": "application/json",
                "authorization": "Bearer %s" % key,
            })
            with _nv_urllib.urlopen(req, timeout=NVIDIA_HTTP_TIMEOUT) as r:
                data = _json.loads(r.read().decode("utf-8"))
            msg = data["choices"][0]["message"]
            parts = []
            content = msg.get("content")
            if content:
                parts.append(_NvPart(text=content))
            for tc in msg.get("tool_calls") or []:
                fn = tc.get("function", {})
                try:
                    args = _json.loads(fn.get("arguments") or "{}")
                except Exception:
                    args = {}
                parts.append(_NvPart(func=_NvFuncCall(fn.get("name", ""), args)))
            if not parts:
                parts.append(_NvPart(text=msg.get("reasoning_content") or ""))
            usage = data.get("usage") or {}
            return _NvResponse(parts, _NvUsage(usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)))
        except Exception as exc:
            last_exc = exc
            detail = exc
            if isinstance(exc, _nv_urlerr.HTTPError):
                try:
                    detail = exc.read().decode("utf-8")[:300]
                except Exception:
                    pass
            errors.append(str(detail))
            try:
                _logger.warning("[NVIDIA] call failed (key %s...): %s" % (key[:8], detail))
            except Exception:
                pass
            with _nvidia_key_lock:
                _nvidia_key_idx = (_nvidia_key_idx + 1) % len(NVIDIA_KEY_POOL)
    raise RuntimeError("All NVIDIA NIM keys failed: %s" % errors)


def _call_gemini_with_retry(client, model, contents, config, max_retries=5, base_delay=2, max_tokens=4096):
    """NVIDIA NIM-backed non-streaming generate; returns a genai-shaped shim."""
    system_instruction, temperature, want_tools = _nv_config_unpack(config)
    messages_data = _nv_contents_to_neutral(contents)
    last_exc = None
    for attempt in range(max_retries):
        try:
            resp = _nvidia_generate(messages_data, system_instruction, temperature, want_tools, max_tokens=max_tokens)
            try:
                if resp.usage_metadata:
                    _log_api_usage(getattr(_tls, "current_session_id", "SYSTEM"), NVIDIA_MODEL,
                                   resp.usage_metadata.prompt_token_count, resp.usage_metadata.candidates_token_count)
            except Exception as ue:
                _logger.warning("[CostTracker] usage log failed: %s" % ue)
            import alerting
            alerting.record_llm_success()
            return resp
        except Exception as e:
            last_exc = e
            import alerting
            alerting.record_llm_failure(str(e))
            if attempt < max_retries - 1:
                time.sleep(base_delay * (2 ** attempt))
                continue
            raise
    raise ValueError("NVIDIA call failed after %d retries: %s" % (max_retries, last_exc))


def _nvidia_text_generate(prompt, system_instruction=None, temperature=0.2,
                          max_retries=3, base_delay=2, max_tokens=4096):
    """Small shared helper for the report/extraction pipeline: plain prompt ->
    response text via NVIDIA NIM (no tools), reusing _nvidia_generate with the
    same retry/backoff, usage logging and alerting as the chat wrappers.
    Injected into llm_insight_generator nodes as `llm_call` so that module
    never imports app.py."""
    if not NVIDIA_KEY_POOL:
        # Fail fast with a clear, actionable message instead of retry-sleeping.
        raise RuntimeError(
            "No NVIDIA API keys configured (set NVIDIA_API_KEY / NVIDIA_API_KEY1..N); "
            "the report/extraction pipeline requires NVIDIA NIM access."
        )
    messages_data = [{"role": "user", "parts": [{"text": str(prompt)}]}]
    last_exc = None
    for attempt in range(max_retries):
        try:
            resp = _nvidia_generate(messages_data, system_instruction, temperature, False, max_tokens=max_tokens)
            try:
                if resp.usage_metadata:
                    _log_api_usage(getattr(_tls, "current_session_id", "SYSTEM"), NVIDIA_MODEL,
                                   resp.usage_metadata.prompt_token_count, resp.usage_metadata.candidates_token_count)
            except Exception as ue:
                _logger.warning("[CostTracker] usage log failed: %s" % ue)
            import alerting
            alerting.record_llm_success()
            return resp.text or ""
        except Exception as e:
            last_exc = e
            import alerting
            alerting.record_llm_failure(str(e))
            if attempt < max_retries - 1:
                time.sleep(base_delay * (2 ** attempt))
                continue
            raise
    raise ValueError("NVIDIA text call failed after %d retries: %s" % (max_retries, last_exc))

GLOBAL_STREAM_QUEUES = {}

def _call_gemini_stream_with_retry(client, model, contents, config, max_retries=3, base_delay=2):
    """NVIDIA NIM-backed 'streaming' generate. NVIDIA is called non-streaming so
    tool-calls parse reliably; the full result is yielded as one genai-shaped
    chunk and the caller token-streams part.text downstream."""
    system_instruction, temperature, want_tools = _nv_config_unpack(config)
    messages_data = _nv_contents_to_neutral(contents)
    last_exc = None
    for attempt in range(max_retries):
        try:
            resp = _nvidia_generate(messages_data, system_instruction, temperature, want_tools)
            try:
                if resp.usage_metadata:
                    _log_api_usage(getattr(_tls, "current_session_id", "SYSTEM"), NVIDIA_MODEL,
                                   resp.usage_metadata.prompt_token_count, resp.usage_metadata.candidates_token_count)
            except Exception as ue:
                _logger.warning("[CostTracker] stream usage log failed: %s" % ue)
            import alerting
            alerting.record_llm_success()
            yield resp
            return
        except Exception as e:
            last_exc = e
            import alerting
            alerting.record_llm_failure(str(e))
            if attempt < max_retries - 1:
                time.sleep(base_delay * (2 ** attempt))
                continue
            raise
    raise ValueError("NVIDIA stream failed after %d retries: %s" % (max_retries, last_exc))


# -- GEMINI HA CLIENT -------------------------------------------------------- #

class PRCChatAssistant:

    def __init__(self, keys: list[str]):

        self.model_name   = "gemini-2.5-pro"

        self._keys        = keys

        self._current_idx = 0

        self._idx_lock    = threading.Lock()

        self._client_lock = threading.Lock()

        self._client      = None

        # _pending_kb lives on _tls (thread-local) — see chat() — NOT on self.

        self._init_client()



    def _init_client(self) -> None:

        for i in range(len(self._keys)):

            with self._idx_lock:

                idx = (self._current_idx + i) % len(self._keys)

            key = self._keys[idx]

            if not _key_healthy(key):

                continue

            try:

                # Explicitly use 'v1' to avoid 'not found for v1beta' errors

                client = genai_new.Client(api_key=key)

                with self._client_lock:

                    self._client      = client

                    self._current_idx = idx

                    try:
                        google_ai_plugin._client._api_client.api_key = key
                        google_ai_plugin._client.aio._api_client.api_key = key
                    except Exception as p_err:
                        _logger.warning(f"[HA] Failed to propagate key to Genkit: {p_err}")

                _logger.info(f"[HA] Node {idx+1} active ({key[:8]}...)")

                return

            except Exception as e:

                _logger.warning(f"[HA] Node {idx+1} init failed: {e}")

        try:

            with self._client_lock:

                self._client = genai_new.Client(api_key=self._keys[0])
                try:
                    google_ai_plugin._client._api_client.api_key = self._keys[0]
                    google_ai_plugin._client.aio._api_client.api_key = self._keys[0]
                except Exception as p_err:
                    _logger.warning(f"[HA] Failed to propagate fallback key to Genkit: {p_err}")

        except Exception as e:

            _logger.error(f"[HA] Emergency fallback failed: {e}")



    def rotate_key(self, is_hard_fail: bool = False) -> None:

        with self._idx_lock:

            _mark_key_failed(self._keys[self._current_idx], is_hard_fail)

            self._current_idx = (self._current_idx + 1) % len(self._keys)

        self._init_client()



    def _execute_tool(self, call):

        """Generator that yields progress strings, then finally the tool result."""

        name, args = call.name, call.args

        if name == "execute_python_simulation":

            p = dict(args.get("params") or {})

            for k in _PETRO_KEYS:

                if k in args and k not in p:

                    p[k] = args[k]

            p["model"] = args.get("model")

            p["mode"]  = args.get("mode", "1d")

            

            full_out = []

            for chunk in SkillsEngine.run_skill_stream("petroleum", "simulator", "simulation_core.py", [_json.dumps(p)]):

                if "stdout" in chunk:

                    line = chunk["stdout"]

                    full_out.append(line)

                    if "PROGRESS:" in line:

                        yield (False, line.strip())

                elif "stderr" in chunk:

                    full_out.append(chunk["stderr"])

            

            out = "".join(full_out)

            if args.get("mode") == "2d" and "success" in (out or ""):

                yield (True, f"__SIMULATION_START__\n{out}\n__SIMULATION_END__")

            else:

                yield (True, out or "")

            return

        elif name == "calculate_petrophysics_properties":
            script = args.get("script")
            model = args.get("model")
            p = dict(args.get("params") or {})

            if model == "rqi_fzi" or script == "petrophysics.py" and model == "rqi_fzi":
                phi = p.get("phi")
                perm = p.get("perm")
                depth = p.get("depth")
                k_groups = p.get("k_groups", p.get("k", 3))
                
                if not phi or not perm:
                    sid = getattr(_tls, 'current_session_id', None)
                    clean_phi, clean_perm, clean_depth, sheet_name, is_percent = find_aligned_bca_columns(sid)
                    if clean_phi and clean_perm:
                        phi = clean_phi
                        perm = clean_perm
                        depth = clean_depth
                        if is_percent:
                            phi = [v / 100.0 for v in phi]
                        p["phi"] = phi
                        p["perm"] = perm
                        p["depth"] = depth
                        p["k_groups"] = k_groups
                        _logger.info(f"[FZI/RQI AutoExtract] Auto-extracted {len(phi)} aligned samples from sheet '{sheet_name}'. Porosity percent normalized: {is_percent}")
                    else:
                        _logger.warning(f"[FZI/RQI AutoExtract] Could not auto-extract aligned columns for session {sid}.")
                else:
                    if phi and max(phi) > 1.0:
                        phi = [v / 100.0 for v in phi]
                        p["phi"] = phi
                        _logger.info(f"[FZI/RQI AutoExtract] Manually passed porosity was in percent (>1.0), normalized to fraction.")
                
                p["k_groups"] = k_groups

            if script == "petrophysics.py":
                sid = getattr(_tls, 'current_session_id', None)
                if sid:
                    if model == "klinkenberg":
                        ka = p.get("ka")
                        if not ka:
                            res_aligned = find_aligned_columns(sid, {
                                "ka": ["ka", "k air", "kair", "k_air", "perm", "permeability"],
                                "pm": ["pm", "mean pressure", "mean press", "p mean", "p_mean", "pressure"]
                            })
                            if res_aligned:
                                aligned_data, sheet_name = res_aligned
                                p["ka"] = [v for v in aligned_data["ka"] if v is not None]
                                p["pm"] = [v if v is not None else 14.7 for v in aligned_data["pm"]]
                                p["depth"] = [v for v in aligned_data["depth"] if v is not None]
                                _logger.info(f"[Klinkenberg AutoExtract] Extracted from '{sheet_name}'")
                                
                    elif model == "retort_saturation":
                        vw = p.get("v_w_raw")
                        vo = p.get("v_o")
                        vp = p.get("v_p")
                        if not vw or not vo or not vp:
                            res_aligned = find_aligned_columns(sid, {
                                "v_w_raw": ["v_w_raw", "vw_raw", "vw raw", "retort water", "water raw", "water volume", "water vol"],
                                "v_o": ["v_o", "vo", "retort oil", "oil volume", "oil vol"],
                                "v_p": ["v_p", "vp", "pore volume", "pore vol", "pv"]
                            })
                            if res_aligned:
                                aligned_data, sheet_name = res_aligned
                                p["v_w_raw"] = []
                                p["v_o"] = []
                                p["v_p"] = []
                                p["depth"] = []
                                for idx in range(len(aligned_data["v_w_raw"])):
                                    w_val = aligned_data["v_w_raw"][idx]
                                    o_val = aligned_data["v_o"][idx]
                                    p_val = aligned_data["v_p"][idx]
                                    if w_val is not None and o_val is not None and p_val is not None:
                                        p["v_w_raw"].append(w_val)
                                        p["v_o"].append(o_val)
                                        p["v_p"].append(p_val)
                                        p["depth"].append(aligned_data["depth"][idx])
                                _logger.info(f"[Retort AutoExtract] Extracted from '{sheet_name}'")
                                
                    elif model == "dean_stark":
                        vw = p.get("v_w")
                        wpre = p.get("w_pre")
                        wpost = p.get("w_post")
                        vp = p.get("v_p")
                        if not vw or not wpre or not wpost or not vp:
                            res_aligned = find_aligned_columns(sid, {
                                "v_w": ["v_w", "vw", "dean stark water", "ds water", "extracted water", "water volume", "water vol"],
                                "w_pre": ["w_pre", "wpre", "pre-weight", "initial weight", "weight pre", "dry weight pre"],
                                "w_post": ["w_post", "wpost", "post-weight", "dry weight post", "weight post", "weight dry"],
                                "v_p": ["v_p", "vp", "pore volume", "pore vol", "pv"]
                            })
                            if res_aligned:
                                aligned_data, sheet_name = res_aligned
                                p["v_w"] = []
                                p["w_pre"] = []
                                p["w_post"] = []
                                p["v_p"] = []
                                p["depth"] = []
                                for idx in range(len(aligned_data["v_w"])):
                                    w_val = aligned_data["v_w"][idx]
                                    pre_val = aligned_data["w_pre"][idx]
                                    post_val = aligned_data["w_post"][idx]
                                    p_val = aligned_data["v_p"][idx]
                                    if w_val is not None and pre_val is not None and post_val is not None and p_val is not None:
                                        p["v_w"].append(w_val)
                                        p["w_pre"].append(pre_val)
                                        p["w_post"].append(post_val)
                                        p["v_p"].append(p_val)
                                        p["depth"].append(aligned_data["depth"][idx])
                                _logger.info(f"[Dean-Stark AutoExtract] Extracted from '{sheet_name}'")

                    elif model == "boyles_law_porosity":
                        p1 = p.get("p1")
                        p2 = p.get("p2")
                        vb = p.get("v_b")
                        v1 = p.get("v1", 100.0)
                        v_added = p.get("v_added", 80.0)
                        if not p1 or not p2 or not vb:
                            res_aligned = find_aligned_columns(sid, {
                                "p1": ["p1", "pressure 1", "press 1", "initial pressure", "p_1"],
                                "p2": ["p2", "pressure 2", "press 2", "final pressure", "expansion pressure", "p_2"],
                                "v_b": ["v_b", "vb", "bulk volume", "bulk vol"]
                            })
                            if res_aligned:
                                aligned_data, sheet_name = res_aligned
                                p["p1"] = []
                                p["p2"] = []
                                p["v_b"] = []
                                p["depth"] = []
                                for idx in range(len(aligned_data["p1"])):
                                    p1_val = aligned_data["p1"][idx]
                                    p2_val = aligned_data["p2"][idx]
                                    vb_val = aligned_data["v_b"][idx]
                                    if p1_val is not None and p2_val is not None and vb_val is not None:
                                        p["p1"].append(p1_val)
                                        p["p2"].append(p2_val)
                                        p["v_b"].append(vb_val)
                                        p["depth"].append(aligned_data["depth"][idx])
                                p["v1"] = v1
                                p["v_added"] = v_added
                                _logger.info(f"[Boyle's Law AutoExtract] Extracted from '{sheet_name}'")

                    elif model == "amott_wettability":
                        dsw_s = p.get("dsw_s")
                        dsw_d = p.get("dsw_d")
                        dso_s = p.get("dso_s")
                        dso_d = p.get("dso_d")
                        if not dsw_s or not dsw_d or not dso_s or not dso_d:
                            res_aligned = find_aligned_columns(sid, {
                                "dsw_s": ["dsw_s", "dsws", "spontaneous water", "imbibition water spontaneous", "dsw_spont"],
                                "dsw_d": ["dsw_d", "dswd", "forced water", "displacement water forced", "dsw_forced"],
                                "dso_s": ["dso_s", "dsos", "spontaneous oil", "imbibition oil spontaneous", "dso_spont"],
                                "dso_d": ["dso_d", "dsod", "forced oil", "displacement oil forced", "dso_forced"]
                            })
                            if res_aligned:
                                aligned_data, sheet_name = res_aligned
                                p["dsw_s"] = []
                                p["dsw_d"] = []
                                p["dso_s"] = []
                                p["dso_d"] = []
                                p["depth"] = []
                                for idx in range(len(aligned_data["dsw_s"])):
                                    w_s = aligned_data["dsw_s"][idx]
                                    w_d = aligned_data["dsw_d"][idx]
                                    o_s = aligned_data["dso_s"][idx]
                                    o_d = aligned_data["dso_d"][idx]
                                    if w_s is not None and w_d is not None and o_s is not None and o_d is not None:
                                        p["dsw_s"].append(w_s)
                                        p["dsw_d"].append(w_d)
                                        p["dso_s"].append(o_s)
                                        p["dso_d"].append(o_d)
                                        p["depth"].append(aligned_data["depth"][idx])
                                _logger.info(f"[Amott AutoExtract] Extracted from '{sheet_name}'")

                    elif model == "xrd_mineralogy":
                        minerals = p.get("minerals")
                        if not minerals:
                            fhash_xrd = resolve_cache_key(sid)
                            load_session_cache_from_db(fhash_xrd)
                            with SESSION_DATA_CACHE_LOCK:
                                raw_excel = SESSION_DATA_CACHE.get(fhash_xrd, {}).get("raw_excel_data", {})
                            if raw_excel:
                                for sheet_name, sheet_dict in raw_excel.items():
                                    aligned = sheet_dict.get("__aligned_vectors__")
                                    if not aligned:
                                        aligned = {k: v for k, v in sheet_dict.items() if isinstance(v, list) and not k.startswith("__")}
                                    if not aligned:
                                        continue
                                        
                                    matched_minerals = {}
                                    mineral_keywords = ["quartz", "feldspar", "calcite", "dolomite", "smectite", "illite", "kaolinite", "chlorite", "anhydrite", "pyrite", "clay"]
                                    for h, vals in aligned.items():
                                        h_clean = str(h).lower()
                                        for keyword in mineral_keywords:
                                            if keyword in h_clean:
                                                matched_minerals[keyword] = [v if v is not None else 0.0 for v in vals]
                                                break
                                    if matched_minerals:
                                        p["minerals"] = matched_minerals
                                        depth_col = None
                                        for h in aligned.keys():
                                            if "depth" in str(h).lower() or "md" in str(h).lower():
                                                depth_col = h
                                                break
                                        if depth_col:
                                            p["depth"] = [v for v in aligned[depth_col] if v is not None]
                                        else:
                                            p["depth"] = [float(i+1) for i in range(len(list(matched_minerals.values())[0]))]
                                        _logger.info(f"[XRD AutoExtract] Extracted {len(matched_minerals)} minerals from '{sheet_name}'")
                                        break

                    elif model == "nmr_t2_distribution":
                        t2_times = p.get("t2_times")
                        amplitudes = p.get("amplitudes")
                        if not t2_times or not amplitudes:
                            res_aligned = find_aligned_columns(sid, {
                                "t2_times": ["t2_times", "t2", "bins", "t2 time", "relaxation time", "t2 ms"],
                                "amplitudes": ["amplitudes", "amplitude", "amp", "distribution", "porosity distribution"]
                            })
                            if res_aligned:
                                aligned_data, sheet_name = res_aligned
                                p["t2_times"] = [v for v in aligned_data["t2_times"] if v is not None]
                                p["amplitudes"] = [v for v in aligned_data["amplitudes"] if v is not None]
                                p["depth"] = [v for v in aligned_data["depth"] if v is not None]
                                p["cutoff_ms"] = p.get("cutoff_ms", 33.0)
                                _logger.info(f"[NMR AutoExtract] Extracted from '{sheet_name}'")

                    elif model == "ct_scan":
                        hu_values = p.get("hu_values")
                        if not hu_values:
                            res_aligned = find_aligned_columns(sid, {
                                "hu_values": ["hu_values", "hu", "ct", "ct number", "hounsfield", "density_hu"]
                            })
                            if res_aligned:
                                aligned_data, sheet_name = res_aligned
                                p["hu_values"] = [v for v in aligned_data["hu_values"] if v is not None]
                                p["depth"] = [v for v in aligned_data["depth"] if v is not None]
                                _logger.info(f"[CT Scan AutoExtract] Extracted from '{sheet_name}'")

                    elif model == "supplementary":
                        sg = p.get("sg")
                        w_init = p.get("w_init")
                        if not sg and not w_init:
                            res_aligned = find_aligned_columns(sid, {
                                "sg": ["sg", "specific gravity", "oil gravity sg", "oil sg", "density sg"],
                                "w_init": ["w_init", "initial weight", "dry weight", "w_dry"],
                                "w_acid": ["w_acid", "acid weight", "insoluble weight", "w_insoluble"]
                            })
                            if res_aligned:
                                aligned_data, sheet_name = res_aligned
                                p["depth"] = [v for v in aligned_data["depth"] if v is not None]
                                if "sg" in aligned_data and any(v is not None for v in aligned_data["sg"]):
                                    p["sg"] = [v for v in aligned_data["sg"] if v is not None]
                                if "w_init" in aligned_data and "w_acid" in aligned_data:
                                    p["w_init"] = [v for v in aligned_data["w_init"] if v is not None]
                                    p["w_acid"] = [v for v in aligned_data["w_acid"] if v is not None]
                                _logger.info(f"[Supplementary AutoExtract] Extracted from '{sheet_name}'")

                subdir = "scalskills/scripts"
                args_list = [model, _json.dumps(p)]
            else:
                subdir = ""
                p["mode"] = model
                args_list = [_json.dumps(p)]

                

            res = SkillsEngine.run_skill("petroleum", subdir, script, args_list)

            if ("error" in res and res["error"]) or res.get("exit_code", 0) != 0 or res.get("stderr"):
                err_msg = res.get("error") or res.get("stderr") or f"Subprocess exited with code {res.get('exit_code')}"
                result = _json.dumps({"status": "error", "error": str(err_msg).strip()})
            else:
                result = res.get("stdout", "")

            # If the calculation was successful, bind thresholds/avg values to session cache
            try:
                calc_res = _json.loads(result)
                sid = getattr(_tls, 'current_session_id', None)
                if calc_res.get("status") == "success" and sid:
                    with SESSION_DATA_CACHE_LOCK:
                        if sid not in SESSION_DATA_CACHE:
                            SESSION_DATA_CACHE[sid] = {}
                        if "labeled_values" not in SESSION_DATA_CACHE[sid]:
                            SESSION_DATA_CACHE[sid]["labeled_values"] = {}
                        if "thresholds" in calc_res:
                            for tk, tv in calc_res["thresholds"].items():
                                SESSION_DATA_CACHE[sid]["labeled_values"][tk] = tv
                    _logger.info(f"[Skills Audit] Petrophysics properties successfully bound to cache for session {sid}.")
            except Exception as cache_err:
                _logger.warning(f"Failed to auto-bind petrophysics properties to cache: {cache_err}")

            yield (True, result)

            return

        elif name == "generate_mermaid_diagram":

            _logger.info("[Skills Audit] Tool generate_mermaid_diagram is INSUFFICIENT for data row validation, bypassing cache binding.")
            result = f"__MERMAID_START__\n{args.get('content','')}\n__MERMAID_END__"

        elif name == "fit_petrophysical_curve":

            model = args.get("model", "")

            if model in ("micp", "ri", "ff", "jfunction", "pc_centrifuge", "overburden", "poroperm", "poroperm_depth"):

                # All analytic models: computation fully handled by _format_tool_response using args

                result = _json.dumps({"status": "ready", "model": model})

            else:

                data = {"model": model, "sw": args.get("sw",[]), "krw": args.get("krw",[])}

                res  = SkillsEngine.run_skill("petroleum", "", "curve_fitting_skill.py", [_json.dumps(data)])

                if ("error" in res and res["error"]) or res.get("exit_code", 0) != 0 or res.get("stderr"):
                    err_msg = res.get("error") or res.get("stderr") or f"Subprocess exited with code {res.get('exit_code')}"
                    result = _json.dumps({"status": "error", "error": str(err_msg).strip()})
                else:
                    result = res.get("stdout", "")

                # Bind parameters directly to local session cache (Skills Assessment Integration)
                try:
                    fit_res = _json.loads(result)
                    sid = getattr(_tls, 'current_session_id', None)
                    if fit_res.get("success") and sid:
                        with SESSION_DATA_CACHE_LOCK:
                            if sid not in SESSION_DATA_CACHE:
                                SESSION_DATA_CACHE[sid] = {}
                            if "labeled_values" not in SESSION_DATA_CACHE[sid]:
                                SESSION_DATA_CACHE[sid]["labeled_values"] = {}
                            for param_k in ["swr", "sor", "krw_max", "kro_max", "nw", "no", "Lw", "Ew", "Tw", "Lo", "Eo", "To"]:
                                if param_k in fit_res:
                                    SESSION_DATA_CACHE[sid]["labeled_values"][param_k] = fit_res[param_k]
                        _logger.info(f"[Skills Audit] Curve fitting parameters successfully bound to cache for session {sid}.")
                except Exception as cache_err:
                    _logger.warning(f"Failed to auto-bind fitted curves to cache: {cache_err}")

        elif name == "agentic_history_matching":

            data = {"sw": args.get("sw",[]), "krw": args.get("krw",[]), "kro": args.get("kro",[])}

            res  = SkillsEngine.run_skill("petroleum", "simulator", "history_matching_skill.py", [_json.dumps(data)])

            result = res.get("stdout") or res.get("stderr") or res.get("error", "")

        elif name == "generate_executive_report":

            sid  = getattr(_tls, 'current_session_id', None)

            well = args.get("well_name", "")
            if not well or well.upper() == "UNKNOWN WELL":
                # Fall back to the well name extracted from the uploaded file this turn
                well = getattr(_tls, 'last_well_name', None) or "UNKNOWN WELL"

            if not sid:

                result = "ERROR: session context unavailable  -  use the Download Report button instead."

            else:

                try:

                    # Use generate() method as defined in report_generator.py

                    filename = PRCReportEngine().generate(session_id=sid, well_name=well, output_dir=str(PRC_VAULT))

                    result = f"REPORT_READY:{filename}"

                except Exception as e:

                    _logger.error(f"[Report] Tool generation failed: {e}")

                    result = f"ERROR: {e}"

        elif name == "get_audit_history":

            sid = getattr(_tls, 'current_session_id', None)

            if not sid:

                result = "ERROR: Session ID unavailable."

            else:

                rows = db("SELECT timestamp, data_type, health_score, violations, file_name "

                          "FROM physics_audits WHERE session_id=? ORDER BY timestamp DESC", (sid,))

                if not rows:

                    result = "No audit records found for this session. The Auditor's Ledger is currently empty."

                else:

                    summary = ["### PRC AUDIT LEDGER  -  SESSION HISTORY"]

                    for r in rows:

                        ts = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(r[0]))

                        v_list = _json.loads(r[3])

                        v_str  = ", ".join([v['rule'] for v in v_list]) if v_list else "None"

                        summary.append(f"**[{ts}] {r[1].upper()}**\n- Score: {r[2]}%\n- File: {r[4] or 'N/A'}\n- Violations: {v_str}")

                    result = "\n\n".join(summary)

        elif name == "sandbox_fit_brooks_corey":
            from physics_sandbox import PhysicsSandbox, run_sandboxed
            sw = args.get("sw", [])
            krw = args.get("krw", [])
            kro = args.get("kro", [])
            swi = args.get("swi", 0.0)
            sor = args.get("sor", 0.0)
            krw_max = args.get("krw_max", 1.0)
            kro_max = args.get("kro_max", 1.0)

            sandbox = PhysicsSandbox()
            inputs = {
                "sandbox": sandbox,
                "sw": sw,
                "krw": krw,
                "kro": kro,
                "swi": swi,
                "sor": sor,
                "krw_max": krw_max,
                "kro_max": kro_max
            }
            source = "result = sandbox.fit_brooks_corey(sw, krw, kro, swi, sor, krw_max, kro_max)"
            try:
                fit_res = run_sandboxed(source, inputs=inputs)
                sid = getattr(_tls, 'current_session_id', None)
                if sid and isinstance(fit_res, dict) and "parameters" in fit_res:
                    with SESSION_DATA_CACHE_LOCK:
                        if sid not in SESSION_DATA_CACHE:
                            SESSION_DATA_CACHE[sid] = {}
                        if "labeled_values" not in SESSION_DATA_CACHE[sid]:
                            SESSION_DATA_CACHE[sid]["labeled_values"] = {}
                        params = fit_res.get("parameters", {})
                        SESSION_DATA_CACHE[sid]["labeled_values"]["nw"] = params.get("nw")
                        SESSION_DATA_CACHE[sid]["labeled_values"]["no"] = params.get("no")
                        SESSION_DATA_CACHE[sid]["labeled_values"]["swr"] = params.get("Swi")
                        SESSION_DATA_CACHE[sid]["labeled_values"]["sor"] = params.get("Sor")
                        SESSION_DATA_CACHE[sid]["labeled_values"]["krw_max"] = params.get("Krw_max")
                        SESSION_DATA_CACHE[sid]["labeled_values"]["kro_max"] = params.get("Kro_max")
                    _logger.info(f"[Skills Audit] Sandbox Brooks-Corey parameters successfully bound to cache for session {sid}.")
                result = _json.dumps(fit_res)
            except Exception as e:
                result = _json.dumps({"status": "error", "error": str(e)})

        elif name == "sandbox_fit_archie":
            from physics_sandbox import PhysicsSandbox, run_sandboxed
            x = args.get("x", [])
            y = args.get("y", [])
            model_type = args.get("model_type", "RI")

            sandbox = PhysicsSandbox()
            inputs = {
                "sandbox": sandbox,
                "x": x,
                "y": y,
                "model_type": model_type
            }
            source = "result = sandbox.fit_archie(x, y, model_type)"
            try:
                fit_res = run_sandboxed(source, inputs=inputs)
                sid = getattr(_tls, 'current_session_id', None)
                if sid and isinstance(fit_res, dict) and "parameters" in fit_res:
                    with SESSION_DATA_CACHE_LOCK:
                        if sid not in SESSION_DATA_CACHE:
                            SESSION_DATA_CACHE[sid] = {}
                        if "labeled_values" not in SESSION_DATA_CACHE[sid]:
                            SESSION_DATA_CACHE[sid]["labeled_values"] = {}
                        params = fit_res.get("parameters", {})
                        if model_type.upper() == "RI":
                            SESSION_DATA_CACHE[sid]["labeled_values"]["b"] = params.get("b")
                            SESSION_DATA_CACHE[sid]["labeled_values"]["n"] = params.get("n")
                        else:
                            SESSION_DATA_CACHE[sid]["labeled_values"]["a"] = params.get("a")
                            SESSION_DATA_CACHE[sid]["labeled_values"]["m"] = params.get("m")
                    _logger.info(f"[Skills Audit] Sandbox Archie {model_type} parameters successfully bound to cache for session {sid}.")
                result = _json.dumps(fit_res)
            except Exception as e:
                result = _json.dumps({"status": "error", "error": str(e)})

        elif name == "hybrid_geological_search":
            try:
                from geological_graph import GeologicalGraph

                query_text = args.get("query_text", "")
                porous_low = args.get("porous_low")
                porous_high = args.get("porous_high")
                perm_low = args.get("perm_low")
                perm_high = args.get("perm_high")
                depth_limit = int(args.get("depth_limit") or 1)
                n_results = int(args.get("n_results") or 3)

                porous_range = (
                    (float(porous_low), float(porous_high))
                    if porous_low is not None and porous_high is not None else None
                )
                perm_range = (
                    (float(perm_low), float(perm_high))
                    if perm_low is not None and perm_high is not None else None
                )

                graph = GeologicalGraph(db_path=settings.graph_db_path, seed=True)

                retriever = None
                try:
                    from rag_database import RAGDatabase
                    retriever = RAGDatabase()
                except (KeyboardInterrupt, SystemExit):
                    raise
                except BaseException as rag_exc:
                    # BaseException on purpose: chromadb's Rust bindings raise
                    # pyo3 PanicException (a BaseException) on corrupt/legacy
                    # stores; degrade to a graph-only answer instead of dying.
                    _logger.warning("Hybrid search: vector retriever unavailable (%s) — graph-only result.", rag_exc)

                res = graph.hybrid_search(
                    query_text=query_text,
                    porous_range=porous_range,
                    perm_range=perm_range,
                    retriever=retriever,
                    depth_limit=depth_limit,
                    n_results=n_results,
                )
                result = _json.dumps(res)
            except Exception as e:
                result = _json.dumps({"status": "error", "error": str(e)})

        else:

            result = f"Unknown tool: {name}"

        

        yield (True, result)



    def _filter_duplicate_plots(self, tool_calls_in_turn: list) -> list[str]:
        """
        Filters out intermediate plots of the same model type, preserving only the last plot payload
        for each curve-fitting type to prevent visual clutter in the chat UI.
        """
        formatted_outputs = []
        last_call_index = {}
        
        # Track the last index of the tool call for each model/type
        for idx, (fc, raw, fmt) in enumerate(tool_calls_in_turn):
            if fc.name == "fit_petrophysical_curve":
                model = fc.args.get("model")
                if model:
                    last_call_index[model] = idx
                    
        for idx, (fc, raw, fmt) in enumerate(tool_calls_in_turn):
            if fc.name == "fit_petrophysical_curve":
                model = fc.args.get("model")
                # If this is not the last call for this model, strip the __PRC_PLOT__ block
                if model and last_call_index.get(model) != idx:
                    cleaned_fmt = re.sub(r'__PRC_PLOT__\n.*?\n\n', '', fmt, flags=re.DOTALL)
                    formatted_outputs.append(cleaned_fmt)
                else:
                    formatted_outputs.append(fmt)
            else:
                formatted_outputs.append(fmt)
                
        return formatted_outputs



    def _format_tool_response(self, name: str, args: dict, result: str) -> str:

        try:

            if name == "sandbox_fit_brooks_corey":
                try:
                    fit_res = _json.loads(result)
                    if "error" in fit_res:
                        return f"⚠️ Sandbox Brooks-Corey fitting failed: {fit_res['error']}"
                    
                    sw = args.get("sw", [])
                    krw = args.get("krw", [])
                    kro = args.get("kro", [])
                    sample = args.get("sample_name", "Core")
                    
                    params = fit_res.get("parameters", {})
                    nw = params.get("nw")
                    no = params.get("no")
                    Swi = params.get("Swi")
                    Sor = params.get("Sor")
                    Krw_max = params.get("Krw_max")
                    Kro_max = params.get("Kro_max")
                    
                    coords = fit_res.get("coordinates", {})
                    sw_fit = coords.get("Sw", [])
                    krw_fit = coords.get("Krw", [])
                    kro_fit = coords.get("Kro", [])
                    
                    health = fit_res.get("health", {})
                    
                    def _pts(S, K): 
                        return [{"x": round(float(s), 4), "y": round(float(k), 4)} for s, k in zip(S, K)]
                    
                    curves = [
                        {"name": "Krw (Lab)", "data": _pts(sw, krw), "color": "#38bdf8", "showLine": False, "showPoints": True, "yId": "left"},
                        {"name": "Kro (Lab)", "data": _pts(sw, kro), "color": "#fb923c", "showLine": False, "showPoints": True, "yId": "right"},
                        {"name": f"Krw (Brooks Corey)", "data": _pts(sw_fit, krw_fit), "color": "#0ea5e9", "showLine": True, "showPoints": False, "yId": "left"},
                        {"name": f"Kro (Brooks Corey)", "data": _pts(sw_fit, kro_fit), "color": "#f97316", "showLine": True, "showPoints": False, "yId": "right"}
                    ]
                    
                    plot_data = {
                        "title": f"Relative Permeability — Kr vs Sw ({sample})",
                        "xAxis": {"label": "Water Saturation Sw"},
                        "yAxis": {"label": "Krw"}, "yAxis2": {"label": "Kro"},
                        "dualAxis": True, 
                        "curves": curves,
                        "metadata": {
                            "endpoints": {"Swi": Swi, "Sor": Sor, "Krw_max": Krw_max, "Kro_max": Kro_max},
                            "validation": {
                                "is_valid": health.get("grade") in ("A", "B"),
                                "warnings": health.get("warnings", []),
                                "errors": health.get("errors", [])
                            },
                            "fit_params": {"model": "Brooks Corey", "nw": nw, "no": no}
                        }
                    }
                    
                    # Log the physics audit
                    audit = {
                        "score": health.get("score", 0.0),
                        "grade": health.get("grade", "F"),
                        "warnings": health.get("warnings", []),
                        "errors": health.get("errors", [])
                    }
                    _log_physics_audit(
                        getattr(_tls, 'current_session_id', 'ANONYMOUS'), 
                        "history_matching", 
                        audit, 
                        getattr(_tls, 'last_file_name', None)
                    )
                    
                    return f"__PRC_PLOT__\n{_safe_json_dumps(plot_data)}\n\n"
                except Exception as e:
                    return f"⚠️ Error formatting sandbox Brooks-Corey response: {e}"

            if name == "sandbox_fit_archie":
                try:
                    fit_res = _json.loads(result)
                    if "error" in fit_res:
                        return f"⚠️ Sandbox Archie fitting failed: {fit_res['error']}"
                    
                    x = args.get("x", [])
                    y = args.get("y", [])
                    model_type = args.get("model_type", "RI").upper()
                    sample = args.get("sample_name", "Core")
                    
                    params = fit_res.get("parameters", {})
                    health = fit_res.get("health", {})
                    coords = fit_res.get("coordinates", {})
                    x_coords = coords.get("x", [])
                    y_lab = coords.get("y", [[], []])[0]
                    y_fit = coords.get("y", [[], []])[1]
                    
                    if model_type == "RI":
                        n_val = params.get("n")
                        plot_ri = {
                            "title": f"Resistivity Index  -  RI vs Sw ({sample})",
                            "xAxis": {"label": "Water Saturation Sw (fraction)"},
                            "yAxis": {"label": "Resistivity Index RI (dimensionless)"},
                            "xAxisLog": True, "yAxisLog": True,
                            "curves": [
                                {"name": f"RI Lab ({sample})", "showLine": False, "showPoints": True, "color": "#f59e0b", "data": [{"x": float(s), "y": float(r)} for s, r in zip(x_coords, y_lab)]},
                                {"name": f"RI Archie  n={n_val:.3f}", "showLine": True, "showPoints": False, "color": "#fbbf24", "data": [{"x": float(s), "y": float(r)} for s, r in zip(x_coords, y_fit)]},
                            ],
                            "metadata": {"archie": {"n": round(n_val, 4)}, "physics_audit": health},
                        }
                        
                        _log_physics_audit(
                            getattr(_tls, 'current_session_id', 'ANONYMOUS'), 
                            "ri", 
                            health, 
                            getattr(_tls, 'last_file_name', None)
                        )
                        
                        return f"__PRC_PLOT__\n{_safe_json_dumps(plot_ri)}\n\n"
                    else:
                        m_val = params.get("m")
                        a_val = params.get("a")
                        plot_ff = {
                            "title": f"Formation Factor  -  FF vs Porosity ({sample})",
                            "xAxis": {"label": "Porosity φ (fraction)"},
                            "yAxis": {"label": "Formation Factor FF (dimensionless)"},
                            "xAxisLog": True, "yAxisLog": True,
                            "curves": [
                                {"name": f"FF Lab ({sample})", "showLine": False, "showPoints": True, "color": "#10b981", "data": [{"x": float(p), "y": float(f)} for p, f in zip(x_coords, y_lab)]},
                                {"name": f"FF Archie  m={m_val:.3f} a={a_val:.3f}", "showLine": True, "showPoints": False, "color": "#34d399", "data": [{"x": float(p), "y": float(f)} for p, f in zip(x_coords, y_fit)]},
                            ],
                            "metadata": {"archie": {"m": round(m_val, 4), "a": round(a_val, 4)}, "physics_audit": health},
                        }
                        
                        _log_physics_audit(
                            getattr(_tls, 'current_session_id', 'ANONYMOUS'), 
                            "ff", 
                            health, 
                            getattr(_tls, 'last_file_name', None)
                        )
                        
                        return f"__PRC_PLOT__\n{_safe_json_dumps(plot_ff)}\n\n"
                except Exception as e:
                    return f"⚠️ Error formatting sandbox Archie response: {e}"

            if name == "hybrid_geological_search":
                try:
                    res = _json.loads(result)
                    if isinstance(res, dict) and res.get("status") == "error":
                        return f"⚠️ Hybrid geological search failed: {res.get('error')}"

                    query = res.get("query") or args.get("query_text", "")
                    graph_part = res.get("graph", {}) or {}
                    matched = graph_part.get("matched_nodes", []) or []
                    subgraphs = graph_part.get("subgraphs", []) or []
                    vector = res.get("vector", []) or []

                    lines = [f"\n\n**🗺️ Hybrid Geological Search** — `{query}`\n"]

                    if matched:
                        lines.append("**Matched Graph Entities:** " + ", ".join(f"`{m}`" for m in matched) + "\n")
                    else:
                        lines.append("**Matched Graph Entities:** none found in the knowledge graph.\n")

                    for sg in subgraphs:
                        edges = sg.get("edges", []) or []
                        if not edges:
                            continue
                        lines.append(f"**Relations around `{sg.get('root')}`** (depth {sg.get('depth_limit')}):")
                        for e in edges:
                            meta = e.get("metadata") or {}
                            meta_str = ""
                            if meta:
                                meta_str = " — *" + ", ".join(f"{k}={v}" for k, v in sorted(meta.items())) + "*"
                            lines.append(f"- `{e.get('source')}` —[{e.get('relation')}]→ `{e.get('target')}`{meta_str}")
                        lines.append("")

                    if vector:
                        lines.append(f"**Analog Wells (vector search — {len(vector)} match(es)):**")
                        for w in vector:
                            ctx = str(w.get("context", ""))[:140]
                            lines.append(f"- `{w.get('id')}` — {ctx}")
                    else:
                        lines.append("**Analog Wells:** no vector matches for the requested petrophysical window.")

                    return "\n".join(lines) + "\n\n"
                except Exception as e:
                    return f"⚠️ Error formatting hybrid geological search response: {e}"

            # â"€â"€ Executive Report â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€

            if name == "generate_executive_report":

                if result.startswith("REPORT_READY:"):

                    base  = result[len("REPORT_READY:"):]

                    dl    = f"/api/download/{base}"

                    well  = args.get("well_name", "UNKNOWN WELL").upper()

                    return (

                        f"\n\n**Executive SCAL Report  -  {well}**\n\n"

                        f"The report has been compiled and is ready for download.\n\n"

                        f"ðŸ“„ `{base}`\n\n"

                        f"__REPORT_DL__{dl}__END_REPORT_DL__\n\n"

                        f"*Sign off after engineering review before distribution.*\n\n"

                    )

                return f"\n\n{result}\n\n"



            # â"€â"€ MICP: Drainage + Imbibition, log-Pc, % x-axis, hysteresis â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€

            if name == "fit_petrophysical_curve" and args.get("model") == "micp":

                pc_raw      = args.get("pc",      [])

                shg_raw     = args.get("s_hg",    [])

                pc_imb_raw  = args.get("pc_imb",  [])

                shg_imb_raw = args.get("s_hg_imb",[])

                if len(pc_raw) > 1 and len(shg_raw) > 1:

                    pc_arr  = np.array(pc_raw,  dtype=float)

                    shg_arr = np.array(shg_raw, dtype=float)

                    idx     = np.argsort(shg_arr)

                    pc_s    = pc_arr[idx]

                    shg_s   = shg_arr[idx]

                    # X-axis: fraction  ->  % Pore Volume

                    shg_pct = shg_s * 100.0

                    pc_pos  = np.maximum(pc_s, 0.1)

                    # Washburn: r(Âµm) = 107.5 / Pc_psia  (Hg-air: Î³=480 mN/m, Î¸=140Â°)

                    r_um    = 107.5 / pc_pos

                    # Entry pressure  -  first point where Hg_sat > 1 %

                    entry_mask = shg_s > 0.01

                    pe = float(pc_s[entry_mask][0]) if entry_mask.any() else float(pc_s[0])

                    # Threshold pressure  -  inflection of Pc(Sw) curve

                    if len(pc_s) > 2:

                        grad   = np.gradient(shg_s, pc_s)

                        thr_pc = float(pc_s[np.argmax(grad)])

                    else:

                        thr_pc = pe

                    thr_r = 107.5 / max(thr_pc, 0.1)

                    # PSD: dSw/d(log10 r)

                    log_r   = np.log10(r_um)

                    psd_pts = []

                    for j in range(1, len(shg_s)):

                        dlr = log_r[j] - log_r[j - 1]

                        if abs(dlr) > 1e-10:

                            psd_pts.append({

                                "x": float((r_um[j] + r_um[j-1]) / 2),

                                "y": float(abs((shg_s[j] - shg_s[j-1]) / dlr)),

                            })

                    psd_pts.sort(key=lambda p: p["x"])

                    # â"€â"€ Imbibition (recovery) cycle â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€

                    has_imb       = len(pc_imb_raw) > 1 and len(shg_imb_raw) > 1

                    trapped_pct   = None

                    curves_pc     = [

                        {"name": "Drainage Pc", "showLine": True, "showPoints": True,

                         "color": "#a855f7", "dashed": False,

                         "data": [{"x": float(s), "y": float(p)}

                                  for s, p in zip(shg_pct, pc_s)]},

                    ]

                    if has_imb:

                        pc_imb_a   = np.array(pc_imb_raw,  dtype=float)

                        shg_imb_a  = np.array(shg_imb_raw, dtype=float)

                        idx_imb    = np.argsort(shg_imb_a)

                        pc_imb_s   = pc_imb_a[idx_imb]

                        shg_imb_s  = shg_imb_a[idx_imb]

                        shg_imb_pct= shg_imb_s * 100.0

                        # Trapped Hg = drainage peak sat âˆ’ imbibition final sat

                        trapped_pct = round(float(shg_pct[-1]) - float(shg_imb_pct[-1]), 1)

                        curves_pc.append({

                            "name": "Imbibition Pc", "showLine": True, "showPoints": True,

                            "color": "#c084fc", "dashed": True,

                            "data": [{"x": float(s), "y": float(p)}

                                     for s, p in zip(shg_imb_pct, pc_imb_s)],

                        })

                    # Pore Throat Sorting Coefficient (Simple proxy: ratio of 25th to 75th percentile radii)

                    # or better: use the PSD peak width. For now, let's provide a 'Sorting Index'

                    sorting_idx = 1.0

                    if len(psd_pts) > 5:

                        psd_y = np.array([p["y"] for p in psd_pts])

                        # Normalize sorting: sharp peak = low index (well sorted)

                        sorting_idx = round(float(np.sum(psd_y) / (np.max(psd_y) * len(psd_y) + 1e-9)), 2)



                    # Plot 1  -  Capillary Pressure (log-scale Y)

                    plot_pc = {

                        "title":    "MICP  -  Capillary Pressure vs Mercury Saturation",

                        "xAxis":    {"label": "Mercury Saturation (% Pore Volume)"},

                        "yAxis":    {"label": "Capillary Pressure Pc (psia)"},

                        "yAxisLog": True,

                        "curves":   curves_pc,

                        "metadata": {"micp": {

                            "entry_pressure_psia":     round(pe, 2),

                            "threshold_pressure_psia": round(thr_pc, 2),

                            "modal_pore_radius_um":    round(thr_r, 3),

                            "max_hg_saturation_pct":   round(float(shg_pct[-1]), 1),

                            "trapped_hg_pct":          trapped_pct,

                            "sorting_index":           sorting_idx,

                        }},

                    }

                    # Plot 2  -  Pore Size Distribution

                    plot_psd = {

                        "title":  "Pore Throat Size Distribution (MICP)",

                        "xAxis":  {"label": "Pore Throat Radius r (Âµm)"},

                        "yAxis":  {"label": "Incremental Hg Saturation  dSw/d(log r)"},

                        "curves": [{"name": "Pore Throat Distribution", "showLine": True,

                                    "showPoints": False, "color": "#f59e0b",

                                    "data": psd_pts}],

                    }

                    # â"€â"€ Physics Guard â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€

                    audit = PhysicsGuard().validate_micp(pc_s, shg_s).generate_health_score()

                    plot_pc["metadata"]["physics_audit"] = audit

                    _log_physics_audit(

                        getattr(_tls, 'current_session_id', 'ANONYMOUS'), 

                        "micp", 

                        audit, 

                        getattr(_tls, 'last_file_name', None)

                    )



                    parts = [

                        f"Entry Pressure Pe = {pe:.1f} psia",

                        f"Threshold Pressure = {thr_pc:.1f} psia",

                        f"Modal Pore Throat r = {thr_r:.3f} Âµm",

                        f"Max Hg Saturation = {float(shg_pct[-1]):.1f}%",

                        f"Pore Sorting Index = {sorting_idx}",

                    ]

                    if trapped_pct is not None:

                        parts.append(f"Trapped Hg (Hysteresis) = {trapped_pct:.1f}%")

                    summary = "  |  ".join(parts)

                    return (

                        f"__PRC_PLOT__\n{_safe_json_dumps(plot_pc)}\n\n"

                        f"__PRC_PLOT__\n{_safe_json_dumps(plot_psd)}\n\n"

                    )



            # â"€â"€ RESISTIVITY INDEX (Archie n fit, log-log) â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€

            if name == "fit_petrophysical_curve" and args.get("model") == "ri":

                sid = getattr(_tls, 'current_session_id', None)

                # STRICT CACHE-ONLY: fit exclusively on the verified cached column vectors
                # the report engine uses. NO LLM/inline-arg fallback. No cache -> terminate.
                sw_raw, ri_raw = [], []
                if sid:
                    sw_raw = find_cached_vector(sid, ["sw", "water saturation", "saturation"])
                    ri_raw = find_cached_vector(sid, ["ri", "resistivity index", "index"])
                if not sw_raw or not ri_raw:
                    return (
                        "⚠️ Resistivity Index fit aborted: no verified Sw / RI vectors are present "
                        "in the session cache. Upload the SCAL file so the fit runs strictly on "
                        "cached laboratory data — inline or model-supplied values are not accepted."
                    )

                sample = args.get("sample_name", "Core")

                if len(sw_raw) > 1 and len(ri_raw) > 1 and len(sw_raw) == len(ri_raw):

                    sw_a = np.array(sw_raw, dtype=float)
                    ri_a = np.array(ri_raw, dtype=float)
                    # Sort by Sw WITHOUT severing the measured Sw<->RI pairing
                    # (the prior independent re-sort of RI fabricated the lab scatter).
                    idx_sort = np.argsort(sw_a)
                    sw_a = sw_a[idx_sort]
                    ri_a = ri_a[idx_sort]

                    mask     = (sw_a > 0) & (ri_a > 0)
                    n_arch   = float(-np.polyfit(np.log(sw_a[mask]), np.log(ri_a[mask]), 1)[0])

                    # Physics boundary: Archie n in [1.5, 3.0]. Do NOT clamp-and-synthesize.
                    # Intercept gracefully so the text answer and the chart can never disagree.
                    if not (1.5 <= n_arch <= 3.0):
                        _audit_fail = PhysicsGuard().validate_archie(sw_a, ri_a, "RI").generate_health_score()
                        _log_physics_audit(getattr(_tls, 'current_session_id', 'ANONYMOUS'), "ri",
                                           _audit_fail, getattr(_tls, 'last_file_name', None))
                        return (
                            f"⚠️ Physics boundary check failed for the Resistivity Index fit: "
                            f"the fitted Archie saturation exponent n={n_arch:.3f} falls outside the valid "
                            f"reservoir-rock range [1.5, 3.0]. No RI chart was generated, to avoid emitting "
                            f"fabricated data points. Please verify the raw Sw / RI columns for sample '{sample}'."
                        )

                    sw_fit   = np.linspace(float(sw_a.min()), 1.0, 80)
                    ri_fit   = sw_fit ** (-n_arch)

                    plot_ri  = {

                        "title":    f"Resistivity Index  -  RI vs Sw ({sample})",

                        "xAxis":    {"label": "Water Saturation Sw (fraction)"},

                        "yAxis":    {"label": "Resistivity Index RI (dimensionless)"},

                        "xAxisLog": True, "yAxisLog": True,

                        "curves": [

                            {"name": f"RI Lab ({sample})", "showLine": False, "showPoints": True,

                             "color": "#f59e0b",

                             "data": [{"x": float(s), "y": float(r)} for s, r in zip(sw_a, ri_a)]},

                            {"name": f"RI Archie  n={n_arch:.3f}", "showLine": True, "showPoints": False,

                             "color": "#fbbf24",

                             "data": [{"x": float(s), "y": float(r)} for s, r in zip(sw_fit, ri_fit)]},

                        ],

                        "metadata": {"archie": {"n": round(n_arch, 4)}},

                    }

                    # â"€â"€ Physics Guard â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€

                    audit = PhysicsGuard().validate_archie(sw_a, ri_a, "RI").generate_health_score()

                    plot_ri["metadata"]["physics_audit"] = audit

                    _log_physics_audit(

                        getattr(_tls, 'current_session_id', 'ANONYMOUS'), 

                        "ri", 

                        audit, 

                        getattr(_tls, 'last_file_name', None)

                    )

                    if sid:

                        with SESSION_DATA_CACHE_LOCK:

                            if sid not in SESSION_DATA_CACHE:

                                SESSION_DATA_CACHE[sid] = {}

                            if "labeled_values" not in SESSION_DATA_CACHE[sid]:

                                SESSION_DATA_CACHE[sid]["labeled_values"] = {}

                            SESSION_DATA_CACHE[sid]["labeled_values"]["n"] = n_arch

                            SESSION_DATA_CACHE[sid]["labeled_values"]["n_arch"] = n_arch

                            SESSION_DATA_CACHE[sid]["labeled_values"]["saturation_exponent"] = n_arch



                    return (

                        f"__PRC_PLOT__\n{_safe_json_dumps(plot_ri)}\n\n"

                    )



            # â"€â"€ FORMATION FACTOR (Archie m, a fit, log-log) â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€

            if name == "fit_petrophysical_curve" and args.get("model") == "ff":

                sid = getattr(_tls, 'current_session_id', None)

                # STRICT CACHE-ONLY: fit exclusively on the verified cached column vectors
                # the report engine uses. NO LLM/inline-arg fallback. No cache -> terminate.
                phi_raw, ff_raw = [], []
                if sid:
                    phi_raw = find_cached_vector(sid, ["porosity", "phi"])
                    ff_raw  = find_cached_vector(sid, ["ff", "formation factor"])
                if not phi_raw or not ff_raw:
                    return (
                        "⚠️ Formation Factor fit aborted: no verified porosity / FF vectors are "
                        "present in the session cache. Upload the SCAL file so the fit runs strictly "
                        "on cached laboratory data — inline or model-supplied values are not accepted."
                    )

                sample  = args.get("sample_name", "Core")

                if len(phi_raw) > 1 and len(ff_raw) > 1 and len(phi_raw) == len(ff_raw):

                    phi_a   = np.array(phi_raw, dtype=float)
                    ff_a    = np.array(ff_raw,  dtype=float)
                    # Sort by porosity WITHOUT severing the measured phi<->FF pairing.
                    idx_sort = np.argsort(phi_a)
                    phi_a = phi_a[idx_sort]
                    ff_a = ff_a[idx_sort]

                    mask    = (phi_a > 0) & (ff_a > 0)
                    coeffs  = np.polyfit(np.log(phi_a[mask]), np.log(ff_a[mask]), 1)
                    m_arch  = float(-coeffs[0])
                    a_arch  = float(np.exp(coeffs[1]))

                    # Physics boundary: cementation m in [1.3, 3.5], tortuosity a in [0.3, 2.5].
                    # Intercept gracefully rather than clamping into range and synthesizing a curve.
                    if not (1.3 <= m_arch <= 3.5 and 0.3 <= a_arch <= 2.5):
                        _audit_fail = PhysicsGuard().validate_archie(phi_a, ff_a, "FF").generate_health_score()
                        _log_physics_audit(getattr(_tls, 'current_session_id', 'ANONYMOUS'), "ff",
                                           _audit_fail, getattr(_tls, 'last_file_name', None))
                        return (
                            f"⚠️ Physics boundary check failed for the Formation Factor fit: "
                            f"fitted m={m_arch:.3f}, a={a_arch:.3f} fall outside valid reservoir-rock ranges "
                            f"(m∈[1.3,3.5], a∈[0.3,2.5]). No FF chart was generated, to avoid emitting "
                            f"fabricated data points. Please verify the raw porosity / FF columns for sample '{sample}'."
                        )

                    phi_fit = np.linspace(float(phi_a.min()), float(phi_a.max()), 80)
                    ff_fit  = a_arch / (phi_fit ** m_arch)

                    plot_ff = {

                        "title":    f"Formation Factor  -  FF vs Porosity ({sample})",

                        "xAxis":    {"label": "Porosity Ï† (fraction)"},

                        "yAxis":    {"label": "Formation Factor FF (dimensionless)"},

                        "xAxisLog": True, "yAxisLog": True,

                        "curves": [

                            {"name": f"FF Lab ({sample})", "showLine": False, "showPoints": True,

                             "color": "#a78bfa",

                             "data": [{"x": float(p), "y": float(f)} for p, f in zip(phi_a, ff_a)]},

                            {"name": f"FF Archie  m={m_arch:.3f}  a={a_arch:.3f}", "showLine": True, "showPoints": False,

                             "color": "#8b5cf6",

                             "data": [{"x": float(p), "y": float(f)} for p, f in zip(phi_fit, ff_fit)]},

                        ],

                        "metadata": {"archie": {"m": round(m_arch, 4), "a": round(a_arch, 4)}},

                    }

                    # â"€â"€ Physics Guard â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€

                    audit = PhysicsGuard().validate_archie(phi_a, ff_a, "FF").generate_health_score()

                    plot_ff["metadata"]["physics_audit"] = audit

                    _log_physics_audit(

                        getattr(_tls, 'current_session_id', 'ANONYMOUS'), 

                        "ff", 

                        audit, 

                        getattr(_tls, 'last_file_name', None)

                    )



                    if sid:
                        with SESSION_DATA_CACHE_LOCK:
                            if sid not in SESSION_DATA_CACHE:
                                SESSION_DATA_CACHE[sid] = {}
                            if "labeled_values" not in SESSION_DATA_CACHE[sid]:
                                SESSION_DATA_CACHE[sid]["labeled_values"] = {}
                            SESSION_DATA_CACHE[sid]["labeled_values"]["m"] = m_arch
                            SESSION_DATA_CACHE[sid]["labeled_values"]["a"] = a_arch
                            SESSION_DATA_CACHE[sid]["labeled_values"]["cementation_exponent"] = m_arch
                            SESSION_DATA_CACHE[sid]["labeled_values"]["tortuosity_factor"] = a_arch

                    return (

                        f"__PRC_PLOT__\n{_safe_json_dumps(plot_ff)}\n\n"

                    )



            # â"€â"€ LEVERETT J-FUNCTION â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€

            if name == "fit_petrophysical_curve" and args.get("model") == "jfunction":

                sw_raw  = args.get("sw",  [])

                pc_raw  = args.get("pc",  [])

                k_md    = float(args.get("k_md",          10.0))

                phi_val = float(args.get("phi_val",        0.20))

                ift_ct  = float(args.get("ift_cos_theta", 26.5))

                sample  = args.get("sample_name", "Core")

                if len(sw_raw) > 1 and len(pc_raw) > 1:

                    sw_a  = np.array(sw_raw, dtype=float)

                    pc_a  = np.array(pc_raw, dtype=float)

                    # J = 0.21645  x  Pc[psia]  x  sqrt(k[mD]/Ï†) / ÏƒcosÎ¸[dyn/cm]

                    j_arr = 0.21645 * pc_a * np.sqrt(k_md / phi_val) / ift_ct

                    idx   = np.argsort(sw_a)

                    plot_j = {

                        "title": f"Leverett J-Function ({sample}  k={k_md} mD  Ï†={phi_val:.3f})",

                        "xAxis": {"label": "Water Saturation Sw (fraction)"},

                        "yAxis": {"label": "Leverett J-Function (dimensionless)"},

                        "curves": [

                            {"name": f"J-Function ({sample})", "showLine": True, "showPoints": True,

                             "color": "#34d399",

                             "data": [{"x": float(sw_a[i]), "y": float(j_arr[i])} for i in idx]},

                        ],

                        "metadata": {"jfunction": {"k_md": k_md, "phi": phi_val, "ift_cos_theta": ift_ct}},

                    }

                    # ── Physics Guard: J-Function domain boundaries ──────
                    audit = PhysicsGuard().validate_j_function(
                        j_arr, sw_arr=sw_a, ift_cos_theta=ift_ct,
                        fluid_system=f"σ·cos(θ)={ift_ct}"
                    ).generate_health_score()
                    plot_j["metadata"]["physics_audit"] = audit

                    _log_physics_audit(
                        getattr(_tls, 'current_session_id', 'ANONYMOUS'),
                        "jfunction",
                        audit,
                        f"J-Function: k={k_md} mD, φ={phi_val:.3f}, IFT={ift_ct}"
                    )

                    return (

                        f"__PRC_PLOT__\n{_safe_json_dumps(plot_j)}\n\n"

                    )



            # â"€â"€ CAPILLARY PRESSURE  -  CENTRIFUGE / POROUS PLATE â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€

            if name == "fit_petrophysical_curve" and args.get("model") == "pc_centrifuge":

                sw_raw = args.get("sw", [])

                pc_raw = args.get("pc", [])

                sample = args.get("sample_name", "Core")

                if len(sw_raw) > 1 and len(pc_raw) > 1:

                    sw_a = np.array(sw_raw, dtype=float)

                    pc_a = np.array(pc_raw, dtype=float)

                    idx  = np.argsort(sw_a)

                    plot_pc = {

                        "title": f"Capillary Pressure  -  Pc vs Sw ({sample})",

                        "xAxis": {"label": "Water Saturation Sw (fraction)"},

                        "yAxis": {"label": "Capillary Pressure Pc (psia)"},

                        "curves": [

                            {"name": f"Pc ({sample})", "showLine": True, "showPoints": True,

                             "color": "#38bdf8",

                             "data": [{"x": float(sw_a[i]), "y": float(pc_a[i])} for i in idx]},

                        ],

                    }

                    # â"€â"€ Physics Guard â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€

                    audit = PhysicsGuard().validate_pc(sw_a, pc_a).generate_health_score()

                    plot_pc["metadata"]["physics_audit"] = audit

                    _log_physics_audit(

                        getattr(_tls, 'current_session_id', 'ANONYMOUS'), 

                        "pc", 

                        audit, 

                        getattr(_tls, 'last_file_name', None)

                    )



                    summary = (f"Pc range: {float(pc_a.min()):.2f} â€“ {float(pc_a.max()):.2f} psia | "

                               f"Sw range: {float(sw_a.min()):.3f} â€“ {float(sw_a.max()):.3f}")

                    return (f"__PRC_PLOT__\n{_safe_json_dumps(plot_pc)}\n\n")



            # ── OVERBURDEN COMPACTION (dual-axis: φ left, k right log-scale) ──────────

            if name == "fit_petrophysical_curve" and args.get("model") == "overburden":

                pres_raw = args.get("pressure", [])

                phi_raw  = args.get("porosity", [])

                perm_raw = args.get("perm",     [])

                sample   = args.get("sample_name", "Core")

                if len(pres_raw) > 1:

                    pres_a  = np.array(pres_raw, dtype=float)

                    idx     = np.argsort(pres_a)

                    curves  = []

                    if len(phi_raw) > 1:

                        phi_a = np.array(phi_raw, dtype=float)

                        curves.append({

                            "name": f"Porosity φ ({sample})", "showLine": True, "showPoints": True,

                            "color": "#38bdf8", "yId": "left",

                            "data": [{"x": float(pres_a[i]), "y": float(phi_a[i])} for i in idx],

                        })

                    if len(perm_raw) > 1:

                        perm_a = np.array(perm_raw, dtype=float)

                        curves.append({

                            "name": f"Permeability k ({sample})", "showLine": True, "showPoints": True,

                            "color": "#fb923c", "yId": "right",

                            "data": [{"x": float(pres_a[i]), "y": float(perm_a[i])} for i in idx],

                        })

                    plot_ob = {

                        "title":         f"Overburden Compaction  -  φ & k vs Net Stress ({sample})",

                        "xAxis":         {"label": "Net Confining Pressure (psia)", "domain": ["auto", "auto"]},

                        "yAxis":         {"label": "Porosity φ (fraction)", "domain": ["auto", "auto"]},

                        "yAxis2":        {"label": "Permeability k (mD)", "domain": ["auto", "auto"]},

                        "dualAxis":      True,

                        "yAxisRightLog": True,

                        "curves":        curves,

                    }

                    summary = (f"Pressure range: {float(pres_a.min()):.0f} – {float(pres_a.max()):.0f} psia")

                    return (f"__PRC_PLOT__\n{_safe_json_dumps(plot_ob)}\n\n")

                else:
                    if len(phi_raw) > 1 and len(perm_raw) > 1:
                        is_depth_like = any(p > 100 for p in pres_raw) if pres_raw else False
                        if is_depth_like:
                            args["model"] = "poroperm_depth"
                            if len(pres_raw) == 1:
                                try:
                                    start_depth = float(pres_raw[0])
                                except ValueError:
                                    start_depth = 1000.0
                                args["depth"] = [start_depth + i for i in range(len(phi_raw))]
                            else:
                                args["depth"] = pres_raw
                        else:
                            args["model"] = "poroperm"


            # ── POROSITY-PERMEABILITY CROSS-PLOT ──────────────────────────────────────

            if name == "fit_petrophysical_curve" and args.get("model") == "poroperm":

                phi_raw  = args.get("porosity", [])

                perm_raw = args.get("perm",     [])

                sample   = args.get("sample_name", "Core")

                if len(phi_raw) > 1 and len(perm_raw) > 1:

                    phi_a  = np.array(phi_raw, dtype=float)

                    perm_a = np.array(perm_raw, dtype=float)

                    mask   = (phi_a > 0) & (perm_a > 0)

                    if np.sum(mask) > 1:

                        phi_filtered  = phi_a[mask]

                        perm_filtered = perm_a[mask]

                        coeffs = np.polyfit(phi_filtered, np.log10(perm_filtered), 1)

                        A, B   = float(coeffs[0]), float(coeffs[1])

                        phi_fit  = np.linspace(float(phi_filtered.min()), float(phi_filtered.max()), 100)

                        perm_fit = 10 ** (A * phi_fit + B)

                        phi_max    = float(np.max(phi_filtered))

                        is_percent = phi_max > 1.0

                        x_label    = "Porosity φ (%)" if is_percent else "Porosity φ (fraction)"

                        curves = [

                            {

                                "name":       f"Samples ({sample})",

                                "showLine":   False,

                                "showPoints": True,

                                "color":      "#38bdf8",

                                "data":       [{"x": float(p), "y": float(k)} for p, k in zip(phi_filtered, perm_filtered)],

                            },

                            {

                                "name":       f"Fit: log10(k) = {A:.4f}*φ + {B:.4f}",

                                "showLine":   True,

                                "showPoints": False,

                                "dashed":     True,

                                "color":      "#fb923c",

                                "data":       [{"x": float(p), "y": float(k)} for p, k in zip(phi_fit, perm_fit)],

                            }

                        ]

                        plot_poroperm = {

                            "title":    f"Porosity vs Permeability Cross-Plot ({sample})",

                            "xAxis":    {"label": x_label, "domain": ["auto", "auto"]},

                            "yAxis":    {"label": "Permeability k (mD)", "domain": ["auto", "auto"]},

                            "yAxisLog": True,

                            "curves":   curves,

                        }

                        return (f"__PRC_PLOT__\n{_safe_json_dumps(plot_poroperm)}\n\n")


            # ── POROSITY & PERMEABILITY VS DEPTH ──────────────────────────────────────

            if name == "fit_petrophysical_curve" and args.get("model") == "poroperm_depth":

                depth_raw = args.get("depth",    [])

                phi_raw   = args.get("porosity", [])

                perm_raw  = args.get("perm",     [])

                sample    = args.get("sample_name", "Core")

                if len(depth_raw) > 1 and len(phi_raw) > 1 and len(perm_raw) > 1:

                    depth_a = np.array(depth_raw, dtype=float)

                    phi_a   = np.array(phi_raw,  dtype=float)

                    perm_a  = np.array(perm_raw,  dtype=float)

                    idx          = np.argsort(depth_a)

                    depth_sorted = depth_a[idx]

                    phi_sorted   = phi_a[idx]

                    perm_sorted  = perm_a[idx]

                    phi_max    = float(np.max(phi_sorted))

                    is_percent = phi_max > 1.0

                    y1_label   = "Porosity φ (%)" if is_percent else "Porosity φ (fraction)"

                    curves = [

                        {

                            "name":       f"Porosity φ ({sample})",

                            "showLine":   True,

                            "showPoints": True,

                            "color":      "#38bdf8",

                            "yId":        "left",

                            "data":       [{"x": float(d), "y": float(p)} for d, p in zip(depth_sorted, phi_sorted)],

                        },

                        {

                            "name":       f"Permeability k ({sample})",

                            "showLine":   True,

                            "showPoints": True,

                            "color":      "#fb923c",

                            "yId":        "right",

                            "data":       [{"x": float(d), "y": float(k)} for d, k in zip(depth_sorted, perm_sorted)],

                        }

                    ]

                    plot_depth = {

                        "title":         f"Porosity & Permeability vs Depth ({sample})",

                        "xAxis":         {"label": "Depth (m)" if np.max(depth_sorted) > 1000 else "Depth (ft)", "domain": ["auto", "auto"]},

                        "yAxis":         {"label": y1_label, "domain": ["auto", "auto"]},

                        "yAxis2":        {"label": "Permeability k (mD)", "domain": ["auto", "auto"]},

                        "dualAxis":      True,

                        "yAxisRightLog": True,

                        "curves":        curves,

                    }

                    return (f"__PRC_PLOT__\n{_safe_json_dumps(plot_depth)}\n\n")



            try:

                tr = _json.loads(result) if isinstance(result, str) else result

            except Exception:

                tr = {}

            # ── RQI/FZI Black Box Fix ─────────────────────────────────────────
            # The petrophysics.py rqi_fzi model returns a full structured payload
            # with per-sample rows and HU summary. Format it as a visible markdown
            # table so the LLM can present results conversationally.
            if name == "calculate_petrophysics_properties" and tr.get("status") == "success" and tr.get("samples"):
                model = args.get("model")
                lines = []
                
                sid = getattr(_tls, 'current_session_id', None)
                sheet_name = None
                filename = None
                if sid:
                    try:
                        fnames = get_filenames_from_cache(sid)
                        if fnames:
                            filename = fnames[0]
                    except Exception:
                        pass
                
                if model == "rqi_fzi":
                    if sid:
                        with SESSION_DATA_CACHE_LOCK:
                            if sid not in SESSION_DATA_CACHE:
                                SESSION_DATA_CACHE[sid] = {}
                            if "labeled_values" not in SESSION_DATA_CACHE[sid]:
                                SESSION_DATA_CACHE[sid]["labeled_values"] = {}
                            for s in tr["samples"]:
                                s_name = str(s.get('sample', '')).lower().strip()
                                if s_name:
                                    SESSION_DATA_CACHE[sid]["labeled_values"][f"rqi_{s_name}"] = s.get('rqi', 0.0)
                                    SESSION_DATA_CACHE[sid]["labeled_values"][f"fzi_{s_name}"] = s.get('fzi', 0.0)
                                    SESSION_DATA_CACHE[sid]["labeled_values"][f"hu_{s_name}"] = s.get('hu', 1)
                                    SESSION_DATA_CACHE[sid]["labeled_values"][f"bca_hydraulicunits_rqi_{s_name}"] = s.get('rqi', 0.0)
                                    SESSION_DATA_CACHE[sid]["labeled_values"][f"bca_hydraulicunits_fzi_{s_name}"] = s.get('fzi', 0.0)
                                    SESSION_DATA_CACHE[sid]["labeled_values"][f"bca_hydraulicunits_hu_{s_name}"] = s.get('hu', 1)
                    hu_summary = tr.get("summary", [])
                    num_units = len(hu_summary)
                    lines.append(f"\n\n**RQI / FZI Calculation — {tr.get('total_samples', '?')} Samples, {num_units} Hydraulic Units**\n")
                    lines.append("| # | Depth | Porosity (%) | Perm (mD) | phi_z | RQI (um) | FZI (um) | HU | Quality |")
                    lines.append("|---|-------|-------------|-----------|-------|----------|----------|----|---------|")
                    for s in tr["samples"]:
                        lines.append(
                            f"| {s['sample']} | {s['depth']:.2f} | {s['phi_pct']:.4f} | {s['perm_md']:.4f} "
                            f"| {s['phi_z']:.6f} | {s['rqi']:.4f} | {s['fzi']:.4f} | {s['hu']} | {s['hu_quality']} |"
                        )
                    lines.append("")
                    lines.append("**Hydraulic Unit Summary**\n")
                    lines.append("| HU | Quality | Count | Avg Phi (%) | Avg K (mD) | Avg FZI (um) | FZI Range |")
                    lines.append("|----|---------|-------|-------------|------------|--------------|-----------|")
                    for h in hu_summary:
                        lines.append(
                            f"| {h['hu']} | {h['quality']} | {h['count']} | {h['avg_phi_pct']:.2f} | {h['avg_k_md']:.2f} "
                            f"| {h['avg_fzi']:.4f} | {h['fzi_min']:.4f} - {h['fzi_max']:.4f} |"
                        )
                    thresh = tr.get("thresholds", {})
                    if thresh:
                        lines.append("")
                        t_parts = []
                        for idx in range(num_units - 1):
                            tk = f"hu{idx+1}_hu{idx+2}"
                            if tk in thresh:
                                t_parts.append(f"HU{idx+1}/HU{idx+2} = {thresh[tk]} FZI")
                        if t_parts:
                            lines.append(f"**Partition Thresholds:** " + " | ".join(t_parts))
                            
                elif model == "klinkenberg":
                    lines.append(f"\n\n**Klinkenberg Permeability Correction — {tr.get('total_samples', '?')} Samples**\n")
                    lines.append("| # | Depth | Gas Perm Ka (mD) | Mean Pressure (psi) | Corrected Perm KL (mD) | Slippage b (psi) |")
                    lines.append("|---|-------|------------------|---------------------|------------------------|------------------|")
                    for s in tr["samples"]:
                        lines.append(
                            f"| {s['sample']} | {s['depth']:.2f} | {s['ka_md']:.4f} | {s['pm_psi']:.2f} | {s['kl_md']:.4f} | {s['b_slippage']:.4f} |"
                        )
                        
                elif model == "retort_saturation":
                    lines.append(f"\n\n**Fluid Saturation (Retort Method, 0.85 H2O Correction) — {tr.get('total_samples', '?')} Samples**\n")
                    lines.append("| # | Depth | Pore Volume (cc) | Raw Water (cc) | Corrected Water (cc) | Raw Oil (cc) | Corrected Oil (cc) | Sw (%) | So (%) | Sg (%) |")
                    lines.append("|---|-------|------------------|----------------|----------------------|--------------|--------------------|--------|--------|--------|")
                    for s in tr["samples"]:
                        lines.append(
                            f"| {s['sample']} | {s['depth']:.2f} | {s['vp_cc']:.4f} | {s['vw_raw_cc']:.4f} | {s['vw_corr_cc']:.4f} | "
                            f"{s['vo_raw_cc']:.4f} | {s['vo_corr_cc']:.4f} | {s['sw_pct']:.1f}% | {s['so_pct']:.1f}% | {s['sg_pct']:.1f}% |"
                        )
                        
                elif model == "dean_stark":
                    lines.append(f"\n\n**Fluid Saturation (Dean-Stark Toluene Extraction) — {tr.get('total_samples', '?')} Samples**\n")
                    lines.append("| # | Depth | Pore Volume (cc) | Extracted Water (cc) | Total Weight Loss (g) | Calculated Oil (cc) | Sw (%) | So (%) | Sg (%) |")
                    lines.append("|---|-------|------------------|----------------------|-----------------------|---------------------|--------|--------|--------|")
                    for s in tr["samples"]:
                        lines.append(
                            f"| {s['sample']} | {s['depth']:.2f} | {s['vp_cc']:.4f} | {s['vw_extracted_cc']:.4f} | {s['w_loss_g']:.4f} | "
                            f"{s['vo_calc_cc']:.4f} | {s['sw_pct']:.1f}% | {s['so_pct']:.1f}% | {s['sg_pct']:.1f}% |"
                        )
                        
                elif model == "boyles_law_porosity":
                    lines.append(f"\n\n**Boyle's Law Helium Porosity — {tr.get('total_samples', '?')} Samples**\n")
                    lines.append("| # | Depth | P1 (psi) | P2 (psi) | Bulk Volume Vb (cc) | Grain Volume Vg (cc) | Pore Volume Vp (cc) | Porosity (%) |")
                    lines.append("|---|-------|----------|----------|---------------------|----------------------|---------------------|--------------|")
                    for s in tr["samples"]:
                        lines.append(
                            f"| {s['sample']} | {s['depth']:.2f} | {s['p1_psi']:.2f} | {s['p2_psi']:.2f} | "
                            f"{s['vb_cc']:.4f} | {s['vg_cc']:.4f} | {s['vp_cc']:.4f} | {s['phi_pct']:.2f}% |"
                        )
                        
                elif model == "amott_wettability":
                    lines.append(f"\n\n**Amott & Amott-Harvey Wettability Index — {tr.get('total_samples', '?')} Samples**\n")
                    lines.append("| # | Depth | Water Index Iw | Oil Index Io | Amott-Harvey Index IAH | Wettability State |")
                    lines.append("|---|-------|----------------|--------------|------------------------|-------------------|")
                    for s in tr["samples"]:
                        lines.append(
                            f"| {s['sample']} | {s['depth']:.2f} | {s['iw']:.4f} | {s['io']:.4f} | {s['iah']:.4f} | **{s['wettability_state']}** |"
                        )
                        
                elif model == "xrd_mineralogy":
                    lines.append(f"\n\n**XRD Mineralogy Analysis — {tr.get('total_samples', '?')} Samples**\n")
                    lines.append("| # | Depth | Total Sum | Sum Check | Smectite (%) | Clay Warning | Mineral Composition Breakdown |")
                    lines.append("|---|-------|-----------|-----------|--------------|--------------|--------------------------------|")
                    for s in tr["samples"]:
                        sum_status = "✅ 100%" if not s["sum_violation"] else f"❌ {s['total_sum']}%"
                        smec_status = "⚠️ Clay Risk" if s["smectite_warning"] else "✅ Safe"
                        comp_str = ", ".join(f"{k}: {v}%" for k, v in s["composition"].items() if v > 0)
                        lines.append(
                            f"| {s['sample']} | {s['depth']:.2f} | {s['total_sum']:.2f}% | {sum_status} | {s['smectite_pct']:.2f}% | {smec_status} | {comp_str} |"
                        )
                        
                elif model == "nmr_t2_distribution":
                    lines.append(f"\n\n**NMR T2 Pore-Volume Partitioning — {tr.get('total_samples', '?')} Samples**\n")
                    lines.append("| # | Depth | T2 Cutoff (ms) | BVI Bound PV | FFI Free PV | Total NMR Porosity | Free Fluid Ratio |")
                    lines.append("|---|-------|----------------|--------------|-------------|--------------------|------------------|")
                    for s in tr["samples"]:
                        lines.append(
                            f"| {s['sample']} | {s['depth']:.2f} | {s['cutoff_ms']:.1f} | {s['bvi_bound']:.4f} | {s['ffi_free']:.4f} | "
                            f"{s['total_nmr_porosity']:.4f} | {s['free_fluid_ratio']:.2%} |"
                        )
                        
                elif model == "ct_scan":
                    lines.append(f"\n\n**CT Scan Density & Lithology Identification — {tr.get('total_samples', '?')} Samples**\n")
                    lines.append("| # | Depth | CT Value (HU) | Fractures Identified | Bulk Lithology |")
                    lines.append("|---|-------|---------------|----------------------|----------------|")
                    for s in tr["samples"]:
                        frac_status = "🚨 Open Fracture" if s["fractured_identified"] else "✅ Competent"
                        lines.append(
                            f"| {s['sample']} | {s['depth']:.2f} | {s['ct_hu']:.1f} | {frac_status} | **{s['lithology']}** |"
                        )
                        
                elif model == "supplementary":
                    lines.append(f"\n\n**Supplementary Core Properties — {tr.get('total_samples', '?')} Samples**\n")
                    has_api = "api_gravity" in tr["samples"][0]
                    has_sol = "solubility_pct" in tr["samples"][0]
                    
                    header = "| # | Depth |"
                    sep = "|---|-------|"
                    if has_api:
                        header += " Specific Gravity | API Gravity |"
                        sep += "------------------|-------------|"
                    if has_sol:
                        header += " Initial Weight (g) | Insoluble (g) | Solubility | Carbonate Class |"
                        sep += "--------------------|---------------|------------|-----------------|"
                    lines.append(header)
                    lines.append(sep)
                    
                    for s in tr["samples"]:
                        row = f"| {s['sample']} | {s['depth']:.2f} |"
                        if has_api:
                            row += f" {s['specific_gravity']:.4f} | {s['api_gravity']:.2f}° API |"
                        if has_sol:
                            carb_status = "💎 Carbonate" if s["carbonate_rock"] else "🪨 Siliciclastic"
                            row += f" {s['initial_weight_g']:.4f} | {s['insoluble_weight_g']:.4f} | {s['solubility_pct']:.2f}% | {carb_status} |"
                        lines.append(row)
                    
                    if has_sol:
                        high_sol = False
                        for s in tr["samples"]:
                            if s.get("solubility_pct", 0) > 50.0:
                                high_sol = True
                                break
                        if high_sol:
                            lines.append("")
                            lines.append("> ⚠️ **Engineering Note (Acid Solubility > 50%):** High carbonate content detected. Avoid acid-based core cleaning solvents to prevent structural damage, and flag the core for carbonate-specific SCAL protocols.")
                
                # Fetch sheet name
                sheet_name = None
                try:
                    expected_dict = {}
                    if model == "klinkenberg":
                        expected_dict = {"ka": ["ka"]}
                    elif model == "retort_saturation":
                        expected_dict = {"v_w_raw": ["v_w_raw"]}
                    elif model == "dean_stark":
                        expected_dict = {"v_w": ["v_w"]}
                    elif model == "boyles_law_porosity":
                        expected_dict = {"p1": ["p1"]}
                    elif model == "amott_wettability":
                        expected_dict = {"dsw_s": ["dsw_s"]}
                    elif model == "nmr_t2_distribution":
                        expected_dict = {"t2_times": ["t2_times"]}
                    elif model == "ct_scan":
                        expected_dict = {"hu_values": ["hu_values"]}
                    elif model == "supplementary":
                        expected_dict = {"sg": ["sg"], "w_init": ["w_init"]}
                        
                    if expected_dict:
                        _, s_name = find_aligned_columns(sid, expected_dict)
                        sheet_name = s_name
                    elif model == "xrd_mineralogy":
                        fhash_xrd2 = resolve_cache_key(sid)
                        load_session_cache_from_db(fhash_xrd2)
                        with SESSION_DATA_CACHE_LOCK:
                            raw_excel = SESSION_DATA_CACHE.get(fhash_xrd2, {}).get("raw_excel_data", {})
                        if raw_excel:
                            for s_name, sheet_dict in raw_excel.items():
                                aligned = sheet_dict.get("__aligned_vectors__")
                                if not aligned:
                                    aligned = {k: v for k, v in sheet_dict.items() if isinstance(v, list) and not k.startswith("__")}
                                if aligned and any("quartz" in str(h).lower() or "clay" in str(h).lower() for h in aligned.keys()):
                                    sheet_name = s_name
                                    break
                    else:
                        _, _, _, s_name, _ = find_aligned_bca_columns(sid)
                        sheet_name = s_name
                except Exception:
                    pass
                
                parts = []
                if filename:
                    parts.append(f"file '{filename}'")
                if sheet_name:
                    parts.append(f"sheet '{sheet_name}'")
                
                source_str = " | ".join(parts) if parts else "uploaded spreadsheet"
                lines.append("")
                lines.append(f"*Provenance: Aligned vectors from {source_str} | calculations performed programmatically.*")
                lines.append("")
                return "\n".join(lines)

            if name == "agentic_history_matching" and tr.get("success"):

                sw, krw, kro = args.get("sw",[]), args.get("krw",[]), args.get("kro",[])

                p, mse = tr.get("optimal_parameters",{}), tr.get("final_mse", 0)



                sw_arr, krw_arr, kro_arr = np.array(sw), np.array(krw), np.array(kro)

                ep = Endpoints(

                    Swi=float(sw_arr.min()),

                    Sor=1.0 - float(sw_arr.max()),

                    Krw_max=p.get("krw_max", 0.5),

                    Kro_max=p.get("kro_max", 0.8)

                )

                fitter   = KrCurveFitter(ep)

                bc_res   = fitter.fit_brooks_corey(sw_arr, krw_arr, kro_arr)

                plot_data = fitter.to_plot_json(sw_arr, krw_arr, kro_arr, model="brooks_corey", fit_result=bc_res)



                # â"€â"€ Physics Guard â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€

                audit = PhysicsGuard().validate_kr(sw_arr, krw_arr, kro_arr).generate_health_score()

                plot_data["metadata"] = plot_data.get("metadata", {})

                plot_data["metadata"]["physics_audit"] = audit

                _log_physics_audit(

                    getattr(_tls, 'current_session_id', 'ANONYMOUS'), 

                    "history_matching", 

                    audit, 

                    getattr(_tls, 'last_file_name', None)

                )



                return (

                    f"__PRC_PLOT__\n{_safe_json_dumps(plot_data)}\n\n"

                )

            elif name == "execute_python_simulation":

                if isinstance(result, str) and "__SIMULATION_START__" in result:

                    return f"{result}\n\n"

                if tr and tr.get("mode") == "1d" and tr.get("status") == "success":

                    sw, krw, kro = tr.get("sw",[]), tr.get("krw",[]), tr.get("kro",[])

                    pm = tr.get("params", {})



                    sw_arr, krw_arr, kro_arr = np.array(sw), np.array(krw), np.array(kro)

                    ep = Endpoints(

                        Swi=pm.get("swr", 0.15),

                        Sor=pm.get("snr", 0.2),

                        Krw_max=pm.get("krw_max", 0.5),

                        Kro_max=pm.get("kro_max", 0.8)

                    )

                    fitter    = KrCurveFitter(ep)

                    bc_res    = fitter.fit_brooks_corey(sw_arr, krw_arr, kro_arr)

                    plot_data = fitter.to_plot_json(sw_arr, krw_arr, kro_arr, model="brooks_corey", fit_result=bc_res)



                    # â"€â"€ Physics Guard â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€

                    audit = PhysicsGuard().validate_kr(sw_arr, krw_arr, kro_arr).generate_health_score()

                    plot_data["metadata"] = plot_data.get("metadata", {})

                    plot_data["metadata"]["physics_audit"] = audit

                    _log_physics_audit(

                        getattr(_tls, 'current_session_id', 'ANONYMOUS'), 

                        "simulation_1d", 

                        audit, 

                        getattr(_tls, 'last_file_name', None)

                    )



                    return (

                        f"__PRC_PLOT__\n{_safe_json_dumps(plot_data)}\n\n"

                    )

        except Exception:

            pass

        return ""



    def _tool_result_summary(self, name: str, raw_result: str) -> dict:

        """Returns a compact dict for the next-turn FunctionResponse so Gemini can interpret results."""

        try:

            if name == "generate_mermaid_diagram":

                return {"status": "diagram_rendered", "note": "Mermaid diagram generated. Summarize briefly without mentioning tool execution."}

            

            data = {}

            if name == "execute_python_simulation" and isinstance(raw_result, str) and "__SIMULATION_START__" in raw_result:

                json_str = raw_result.split("__SIMULATION_START__")[1].split("__SIMULATION_END__")[0].strip()

                try:

                    data = _json.loads(json_str)

                except Exception:

                    data = {}

            else:

                try:

                    data = _json.loads(raw_result) if isinstance(raw_result, str) else raw_result

                except Exception:

                    data = {}

                    

            if name == "execute_python_simulation":

                if isinstance(data, dict) and data.get("status") == "success":

                    if data.get("mode") == "1d":

                        pm = data.get("params", {})

                        return {

                            "status": "success",

                            "model": "Brooks-Corey 1D",

                            "parameters": {k: pm.get(k) for k in ("swr","snr","krw_max","kro_max","nw","no") if pm.get(k) is not None},

                            "note": "Kr curves computed. Proceed with physics interpretation without mentioning tool execution.",

                        }

                    elif data.get("mode") == "2d":

                        return {

                            "status": "success",

                            "model": "2D IMPES",

                            "note": "2D IMPES simulation complete. Analyze the results directly without mentioning that a tool was executed.",

                        }

            elif name == "agentic_history_matching":

                if isinstance(data, dict) and data.get("success"):

                    return {

                        "status": "success",

                        "optimal_parameters": data.get("optimal_parameters", {}),

                        "final_mse": data.get("final_mse"),

                        "note": "History matching complete. Proceed with Phase 3 certification without mentioning tool execution.",

                    }

            elif name == "fit_petrophysical_curve":

                _MODEL_NOTES = {

                    "micp":          "Pc curve and Pore Size Distribution computed. Proceed with Entry Pressure, Threshold Pressure, and Pore Throat Sorting analysis without mentioning tool execution.",

                    "ri":            "Resistivity Index log-log plot computed. State Archie n, compare to PRC library range nâˆˆ[1.5,3.0], interpret wettability effect without mentioning tool execution.",

                    "ff":            "Formation Factor log-log plot computed. State Archie m and a, interpret cementation and pore geometry without mentioning tool execution.",

                    "jfunction":     "Leverett J-Function computed. Assess J-curve shape for capillary continuity and capillary entry threshold without mentioning tool execution.",

                    "pc_centrifuge": "Capillary Pressure curve computed. Interpret drainage vs imbibition, entry pressure, and residual saturation without mentioning tool execution.",

                    "overburden":    "Overburden compaction dual-axis plot computed. Quantify porosity loss and permeability reduction per 1000 psia confining stress without mentioning tool execution.",

                }

                model_key = data.get("model", "") if isinstance(data, dict) else ""

                if model_key in _MODEL_NOTES:

                    return {

                        "status": "success",

                        "model": model_key.upper(),

                        "note": _MODEL_NOTES[model_key],

                    }

                if isinstance(data, dict) and data.get("success"):

                    return {

                        "status": "success",

                        "fit_params": data.get("params", {}),

                        "note": "Curve fit complete. Proceed with wettability and endpoint interpretation without mentioning tool execution.",

                    }

            elif name == "get_audit_history":

                return {

                    "status": "success",

                    "note": "PRC Audit Ledger retrieved. Analyze the quality trend and alert the engineer of recurring violations without mentioning tool execution."

                }

            elif name == "generate_executive_report":

                return {

                    "status": "success",

                    "well_name": args.get("well_name", "Unknown Well"),

                    "note": "Executive report generated. Do not mention tool execution."

                }

        except Exception as e:

            _logger.error(f"[Tool] _format_tool_response error ({name}): {e}")

            pass

        return {"status": "executed", "tool": name, "note": "Action complete. Provide the final engineering interpretation directly without stating that a tool was executed."}



    def _build_contents(self, history: list, enriched_msg: str, f_parts: list) -> tuple[list, list[str]]:

        SUPPORTED = {

            "application/pdf", "image/jpeg", "image/png", "image/gif", "image/webp",

            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",

            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",

            "text/plain", "text/csv", "application/json"

        }

        contents  = []

        for h in history:

            role  = "user" if h["role"] == "user" else "model"

            text  = h.get("text", "")

            parts = [genai_types.Part(text=text)]

            url   = h.get("url")

            if url and "|" in url:

                uri, mime = url.split("|", 1)

                parts.append(genai_types.Part(file_data=genai_types.FileData(file_uri=uri, mime_type=mime)))

            contents.append(genai_types.Content(role=role, parts=parts))



        if contents and contents[-1].role == "user":

            contents.pop()



        with self._client_lock:

            client = self._client



        user_parts    = [genai_types.Part(text=enriched_msg)]

        uploaded_uris: list[str] = []



        import tempfile

        for data_bytes, mime, fname in f_parts:

            safe_mime = mime or "application/octet-stream"

            if safe_mime not in SUPPORTED:

                continue



            # Skip Gemini Files API for spreadsheets, PDFs, DOCX, and plain text — all
            # extracted locally in chat() and injected into the prompt. Avoids 30-120s upload latency.
            if any(x in safe_mime for x in ["spreadsheet", "excel", "csv", "sheet", "pdf", "wordprocessingml", "text/plain"]):

                continue



            with tempfile.NamedTemporaryFile(delete=False) as tf:

                tf.write(data_bytes)

                tmp = tf.name

            try:

                uf = client.files.upload(file=tmp, config={"mime_type": mime})

                for _ in range(7):

                    if str(getattr(uf, "state", "")).upper().endswith("ACTIVE"):

                        break

                    time.sleep(0.5)

                    uf = client.files.get(name=uf.name)

                user_parts.append(genai_types.Part(file_data=genai_types.FileData(file_uri=uf.uri, mime_type=mime)))

                uploaded_uris.append(f"{uf.uri}|{mime}")

            finally:

                try:
                    Path(tmp).unlink(missing_ok=True)
                except Exception:
                    pass



        contents.append(genai_types.Content(role="user", parts=user_parts))



        # Ensure session exists in the sessions table

        # We don't have the sid here, so we do it in the caller

        return contents, uploaded_uris



    def chat(self, history: list, msg: str, kb_context: str = "", f_parts: list = [], stream: bool = False, sid: str = None, email: str = None):

        _tls.pending_kb = []       # thread-local: safe under 50+ concurrent workers
        _tls.last_well_name = None  # updated when a SCAL file is processed this turn

        extracted_context = ""

        # ── SESSION FILE REGISTRY (Persistence Guard) ──
        session_files_ctx = ""
        if sid:
            try:
                # Use a lightweight query to see what files were mentioned in this session
                # We also want to know which one was the VERY LAST one mentioned before this turn
                rows = db("SELECT fname, MAX(ts) as max_ts FROM m WHERE sid=? AND fname IS NOT NULL GROUP BY fname ORDER BY max_ts DESC", (sid,))
                if rows:
                    fnames = [r[0] for r in rows]
                    session_files_ctx = f"[SESSION FILE REGISTRY]: This session contains data for: {', '.join(fnames)}.\n"
                    session_files_ctx += f"[LATEST SESSION FILE]: {fnames[0]}\n"
                    session_files_ctx += "Reference the [LATEST SESSION FILE] if the user asks generic questions.\n\n"
            except: pass

        extracted_context = ""
        # Accumulates raw text from NON-TABULAR files (DOCX/PDF/TXT) uploaded THIS turn so
        # the model can read/summarize them immediately. Spreadsheets continue to flow
        # through the structural ground-truth + labeled-values path below.
        fresh_file_context = ""

        def _cap_doc_text(t: str, limit: int = 60000) -> str:
            # Guardrail: a very large extracted document can push the model's mandated
            # <thinking> block past the output-token limit, leaving an empty visible answer.
            # Cap the raw text dump (summaries and section lookups still work fine) and mark
            # the truncation so the model knows more content exists.
            if t and len(t) > limit:
                return t[:limit] + (
                    f"\n\n[... {len(t) - limit} more characters truncated for length. "
                    f"Ask about a specific section or table for its full detail ...]"
                )
            return t

        import tempfile

        def _sample_data(data, max_rows: int = 40):
            if isinstance(data, list):
                if len(data) > max_rows:
                    step = max(1, len(data) // max_rows)
                    return data[::step][:max_rows]
                return data
            elif isinstance(data, dict):
                sampled = {}
                for k, v in data.items():
                    if isinstance(v, list) and len(v) > max_rows:
                        step = max(1, len(v) // max_rows)
                        sampled[k] = v[::step][:max_rows]
                    elif isinstance(v, dict):
                        sampled[k] = _sample_data(v, max_rows)
                    else:
                        sampled[k] = v
                return sampled
            return data


        if f_parts and sid:
            evict_session(sid)

        for data_bytes, mime, fname in f_parts:
            safe_mime = (mime or "application/octet-stream").lower()
            ext = Path(fname).suffix.lower() if fname else ".xlsx"
            is_spreadsheet = any(x in safe_mime for x in ["spreadsheet", "excel", "csv", "sheet"]) or ext in [".xlsx", ".xls", ".csv"]
            is_docx = "wordprocessingml" in safe_mime or ext in [".docx", ".doc"]
            
            if is_spreadsheet or is_docx:
                if not ext:
                    ext = ".xlsx" if is_spreadsheet else ".docx"

                with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tf:
                    tf.write(data_bytes)
                    tmp_path = tf.name

                try:
                    # Force chat handler to call the EXACT same extraction function used by the report:
                    mandatory_ground_truth = extract_absolute_file_truth([(tmp_path, fname)])
                    if sid:
                        with SESSION_DATA_CACHE_LOCK:
                            SESSION_DATA_CACHE[sid] = {
                                "ground_truth": mandatory_ground_truth,
                                "timestamp": time.time()
                            }
                        populate_cache_from_ground_truth(sid, mandatory_ground_truth)
                        if is_spreadsheet:
                            cache_excel_data_vectors(sid, tmp_path)
                    
                    # ALWAYS persist raw text to user_files so follow-up messages can recover it
                    fr_data = read_file(tmp_path, target_identifier=None)
                    fr_text, _ = to_prompt_string(fr_data)
                    # Surface freshly-uploaded WORD DOCUMENT text in THIS turn's prompt so
                    # Hviel can read/summarize narrative reports (and their tables) right away.
                    # Spreadsheets keep using the structural ground-truth path, not this dump.
                    if is_docx and fr_text:
                        _doc_label = "WORD DOCUMENT" if ext == ".docx" else "DOCUMENT"
                        fresh_file_context += f"\n\n[{_doc_label}: {fname}]\n{_cap_doc_text(fr_text)}\n"
                    if email and fr_text:
                        _fhash_store = hashlib.sha256(data_bytes).hexdigest()
                        db(
                            "INSERT INTO user_files"
                            " (user_email, filename, file_hash, extracted_text, data_type, created_at)"
                            " VALUES (?,?,?,?,?,?)"
                            " ON CONFLICT(user_email, file_hash)"
                            " DO UPDATE SET extracted_text=EXCLUDED.extracted_text,"
                            " filename=EXCLUDED.filename",
                            (email, fname, _fhash_store, fr_text, "SCAL", time.time()),
                        )
                finally:
                    try: Path(tmp_path).unlink(missing_ok=True)
                    except: pass

            elif "pdf" in safe_mime:
                try:
                    text = _sfh_extract_pdf(data_bytes)
                    if text.strip():
                        fresh_file_context += f"\n\n[PDF DOCUMENT: {fname}]\n{_cap_doc_text(text)}\n"
                    if text.strip() and email:
                        _fhash_store = hashlib.sha256(data_bytes).hexdigest()
                        db(
                            "INSERT INTO user_files"
                            " (user_email, filename, file_hash, extracted_text, data_type, created_at)"
                            " VALUES (?,?,?,?,?,?)"
                            " ON CONFLICT(user_email, file_hash)"
                            " DO UPDATE SET extracted_text=EXCLUDED.extracted_text,"
                            " filename=EXCLUDED.filename",
                            (email, fname, _fhash_store, text, "PDF", time.time()),
                        )
                except Exception as e:
                    _logger.warning(f"[PDF Extract] {fname}: {e}")

            elif "text/plain" in safe_mime or ext in (".txt", ".text"):
                try:
                    content = data_bytes.decode("utf-8", errors="ignore")
                    if content.strip():
                        fresh_file_context += f"\n\n[DOCUMENT: {fname}]\n{_cap_doc_text(content)}\n"
                    if content.strip() and email:
                        _fhash_store = hashlib.sha256(data_bytes).hexdigest()
                        db(
                            "INSERT INTO user_files"
                            " (user_email, filename, file_hash, extracted_text, data_type, created_at)"
                            " VALUES (?,?,?,?,?,?)"
                            " ON CONFLICT(user_email, file_hash)"
                            " DO UPDATE SET extracted_text=EXCLUDED.extracted_text,"
                            " filename=EXCLUDED.filename",
                            (email, fname, _fhash_store, content, "TXT", time.time()),
                        )
                except Exception as e:
                    _logger.warning(f"[TXT Extract] {fname}: {e}")


        # Surface freshly-uploaded document text (DOCX/PDF/TXT) in THIS turn's prompt.
        if fresh_file_context:
            extracted_context += fresh_file_context

        # ── DIRECTLY HYDRATE THE CHAT PROMPT WITH TRUE CACHE ──
        has_cached_data = False
        cached_gt = ""
        labeled_values = {}
        if sid:
            load_session_cache_from_db(sid)
            with SESSION_DATA_CACHE_LOCK:
                if sid in SESSION_DATA_CACHE and SESSION_DATA_CACHE[sid]:
                    has_cached_data = True
                    cached_gt = SESSION_DATA_CACHE[sid].get("ground_truth", "")
                    labeled_values = SESSION_DATA_CACHE[sid].get("labeled_values", {})

        # Inject the full un-truncated database structures directly into the context payload.
        # Only inject the structural ground-truth inventory when it actually describes tabular
        # data. For non-tabular files (DOCX/PDF/TXT) the inventory is content-free
        # ("[Non-tabular file, no sheet/column inventory applicable]") — injecting it would both
        # mislead the model into refusing AND (by making extracted_context non-empty) suppress
        # the document-recovery block below on follow-up turns.
        if has_cached_data:
            gt_has_tables = bool(cached_gt) and ("COLUMNS (" in cached_gt or bool(labeled_values))
            if gt_has_tables:
                truncated_gt = _truncate_ground_truth(cached_gt)
                extracted_context += f"\n\n[MANDATORY GROUND TRUTH INVENTORY]:\n{truncated_gt}\n\n"
            if labeled_values:
                _lv_cap = _env_int("SCAL_GT_JSON_MAX_CHARS", 30000)
                extracted_context += f"[FULLY-VERIFIED EXTRACTION PARAMETERS]:\n{_cap_prompt_block(str(labeled_values), _lv_cap, 'LABELED VALUES')}\n\n"


        # ── DOCUMENT RECOVERY FOR FOLLOW-UP MESSAGES ──────────────────────────
        # When no file is uploaded in this message but the session has previous uploads,
        # recover the full raw document text from user_files so Hviel can read ALL tables.
        # This is what makes Hviel work like Claude/Gemini — the full document is always available.
        if not extracted_context and sid and email:
            try:
                file_rows = db(
                    "SELECT DISTINCT fname, file_hash FROM (SELECT fname, file_hash FROM m WHERE sid=? AND user_email=? AND fname IS NOT NULL ORDER BY id DESC) sub",
                    (sid, email),
                )
                _seen_fn: set = set()
                session_files: list = []
                for row in (file_rows or []):
                    _raw_fn = row[0]
                    _fhash = row[1]
                    if _raw_fn:
                        for _fn in _raw_fn.split(";"):
                            _fn = _fn.strip()
                            if _fn and _fn not in _seen_fn:
                                session_files.append((_fn, _fhash))
                                _seen_fn.add(_fn)
                for _sfname, _sfhash in session_files[:5]:  # Up to 5 files per session
                    if _sfhash:
                        stored = db(
                            "SELECT extracted_text FROM user_files WHERE user_email=? AND file_hash=?",
                            (email, _sfhash),
                        )
                    else:
                        stored = db(
                            "SELECT extracted_text FROM user_files WHERE user_email=? AND filename=?",
                            (email, _sfname),
                        )
                    if stored and stored[0][0]:
                        _ext = Path(_sfname).suffix.lower()
                        _label = "SPREADSHEET" if _ext in (".xlsx", ".xls", ".csv") else "WORD DOCUMENT" if _ext == ".docx" else "DOCUMENT"
                        extracted_context += f"\n\n[{_label}: {_sfname}]\n{_cap_doc_text(stored[0][0])}\n"
                        _logger.info(f"[Chat] Recovered stored document text for {_sfname} ({len(stored[0][0])} chars)")
            except Exception as _dbe:
                _logger.warning(f"[Chat] Could not retrieve stored document context: {_dbe}")

        # ── HARD REFUSAL GATE (zero-hallucination data isolation) ─────────────
        # If the user asks for file/sheet/column/sample data but this session has NO
        # grounded data (empty cache, no recovered document, no active upload this turn),
        # refuse outright. We never let the model answer SCAL specifics from general
        # knowledge. General petrophysics questions (no data reference) pass through.
        import re as _re_gate
        _scal_data_ref = _re_gate.compile(
            r"(?i)\b(?:sheets?|worksheets?|columns?|rows?|cells?|samples?|core\s*plugs?|"
            r"spreadsheet|excel|uploaded|extract|tabulate|the\s+file|the\s+data|"
            r"the\s+report|the\s+table|values?)\b"
        )
        if (not extracted_context) and (not has_cached_data) and (not f_parts) and msg and _scal_data_ref.search(msg):
            _refusal = (
                "⚠️ I can't answer that from this session. No SCAL file data is currently "
                "loaded in this conversation (the session cache is empty), so I have no "
                "verified worksheet, column, or parameter values to read from. I will not "
                "estimate or infer petrophysical values from general knowledge.\n\n"
                "Please upload the relevant Excel/CSV file (or use the Generate Report flow) "
                "so every reported number is grounded in your actual data."
            )
            def _gen_refusal():
                yield _refusal
            return _gen_refusal() if stream else _refusal

        # ── INCOMPLETE-LOAD GATE (fluid-saturation-bound completeness) ────────
        # [DELEGATED TO LLM SYSTEM PROMPT INSTEAD OF BLANKET INTERCEPT FOR BATCH QUERIES]
        # if has_cached_data and msg:
        #     def _cache_has(param: str) -> bool:
        #         if param in labeled_values:
        #             return True
        #         for _k in labeled_values.keys():
        #             if param in _re_gate.split(r'[^a-z0-9]+', str(_k).lower()):
        #                 return True
        #         return False
        #     _sat_query = _re_gate.search(
        #         r"(?i)\b(?:swi|sor|displacement\s+effic|recover|mobile\s+(?:oil|fluid)|"
        #         r"residual\s+oil|irreducible\s+water|saturation\s+endpoint)\b",
        #         msg,
        #     )
        #     if _sat_query:
        #         _has_swi, _has_sor = _cache_has("swi"), _cache_has("sor")
        #         if not (_has_swi and _has_sor):
        #             _missing = ("Swi and Sor" if not (_has_swi or _has_sor)
        #                         else ("Swi" if not _has_swi else "Sor"))
        #             _refusal2 = (
        #                 f"⚠️ I can't compute that: the session cache is loaded but its verified "
        #                 f"parameters are missing the required fluid-saturation bound(s) ({_missing}). "
        #                 f"Saturation-dependent results (displacement efficiency, recovery, residual "
        #                 f"saturations) cannot be derived without them, and I will not substitute "
        #                 f"assumed values. Please re-upload a file whose extraction yields explicit "
        #                 f"Swi and Sor."
        #             )
        #             def _gen_refusal2():
        #                 yield _refusal2
        #             return _gen_refusal2() if stream else _refusal2

        # Strict Context Shielding

        is_new_upload = len(f_parts) > 0

        wants_comparison = any(word in msg.lower() for word in ["compare", "previous", "last", "difference", "both", "past"])

        

        if is_new_upload and not wants_comparison:

            kb_context = "" # WIPE old memory to prevent mixing!

            session_files_ctx = "" # Wipe registry to prevent mentioning old files



        enriched = ""

        if session_files_ctx:

            enriched += session_files_ctx

            

        if kb_context or extracted_context:

            if extracted_context:

                enriched += f"### [PRIMARY CONTEXT: NEW UPLOADED DATA] ###\n{extracted_context}\n"

                enriched += "NOTE: The data above is the ONLY relevant data for the current request. Ignore past files.\n\n"

            

            if kb_context:

                enriched += f"### [SECONDARY CONTEXT: PAST SESSION MEMORY (RAG)] ###\n{kb_context}\n"

                enriched += "NOTE: Use this ONLY if the user explicitly requested a comparison.\n\n"

            

            enriched += f"[USER REQUEST]: {msg}\n"

            enriched += "\n[MANDATORY SYSTEM OVERRIDE: YOU MUST USE THE DATA PROVIDED ABOVE. EVERY NUMBER MUST HAVE A CITATION [Filename, Sheet: ..., Cell: ...]. IF THE NEW UPLOAD CONFLICTS WITH PAST CONTEXT, THE NEW UPLOAD IS THE TRUTH.]"

        else:

            enriched = msg



        # Semantic Cache Lookup

        # We must hash the ENRICHED text (which includes file data) plus a bit of history 

        # so "summarize this" doesn't hit a generic cache from a different file.

        cache_base = enriched.strip() + str(history[-1:] if history else "")

        query_hash = hashlib.sha256(cache_base.encode()).hexdigest()

        cached = db("SELECT response FROM response_cache WHERE query_hash=?", (query_hash,))

        

        bypass_cache = email and "test@prc.local" in email.lower()
        if cached and not bypass_cache:
            _logger.info(f"[CACHE] Hit for query hash: {query_hash[:8]}")
            def _gen_cached():
                yield cached[0][0]
            return _gen_cached() if stream else cached[0][0]



        contents, uploaded_uris = self._build_contents(history, enriched, f_parts)

        _tls.last_file_uris = ",".join(uploaded_uris) if uploaded_uris else None



        def _generate():

            # Dynamic Model Routing

            msg_low_routing = msg.lower() if msg else ""

            # Always use the validated model. gemini-2.5-pro leaked <execute_python>
            # thinking tokens into text output during function-calling turns.
            # gemini-2.5-flash is the only CLAUDE.md-validated model (section 5).
            active_model = "gemini-2.5-flash"



            _MAX_OVERLOAD_RETRIES = 3  # retries per key on 503

            _MAX_503_RETRIES = 3

            for attempt in range(len(self._keys)):

                try:

                    with self._client_lock:

                        client = self._client

                    # Dynamic prompt construction with continuous learning corrections
                    dynamic_system_prompt = SYSTEM_PROMPT
                    
                    # 1. Inject server-side Ground Truth from Cache if available
                    if sid:
                        with SESSION_DATA_CACHE_LOCK:
                            cached_entry = SESSION_DATA_CACHE.get(sid)
                        if cached_entry:
                            gt_text = cached_entry.get("ground_truth", "")
                            labeled_vals = cached_entry.get("labeled_values", {})
                            flat_vecs = cached_entry.get("flat_vectors", {})
                            
                            extra_prompt = "## MANDATORY_GROUND_TRUTH_INVENTORY (SESSION DATA CACHE)\n\n"
                            extra_prompt += "You are provided with a MANDATORY_GROUND_TRUTH_INVENTORY and cached data structures extracted programmatically by the Python server from the actual binary file uploaded in this session.\n"
                            extra_prompt += "This data is ABSOLUTE TRUTH. You MUST read and cite only values/sheets/columns listed below.\n\n"
                            
                            _json_cap = _env_int("SCAL_GT_JSON_MAX_CHARS", 30000)
                            if gt_text:
                                extra_prompt += f"{_truncate_ground_truth(gt_text)}\n\n"
                            if labeled_vals:
                                extra_prompt += f"### CACHED LABELED VALUES:\n{_cap_prompt_block(_json.dumps(labeled_vals, indent=2), _json_cap, 'LABELED VALUES')}\n\n"
                            if flat_vecs:
                                # flat_vectors holds full numeric column vectors for every sheet
                                # (each stored under two keys) — for a 10-sheet x 2000-row workbook
                                # this JSON dump alone can exceed the model context. Cap it hard.
                                extra_prompt += f"### CACHED FLAT VECTORS:\n{_cap_prompt_block(_json.dumps(flat_vecs, indent=2), _json_cap, 'FLAT VECTORS')}\n\n"
                                
                            extra_prompt += "=========================================\n\n"
                            
                            # Question-Specific Granular Refusal and Enforcements Instruction Block
                            refusal_rules = "\n\n=== MANDATORY GRANULAR CALCULATIONS & REFUSAL INSTRUCTIONS ===\n"
                            refusal_rules += "1. INDEPENDENT QUESTION EVALUATION: You must evaluate every question in a batch completely independently. Never refuse to answer a whole message or batch because one question lacks parameters.\n"
                            refusal_rules += "2. GRANULAR CALCULATIONS & MISSING PARAMETER REFUSALS:\n"
                            refusal_rules += "   If the user asks for a specific petrophysical parameter, fit, or calculation, and its required inputs are missing from the CACHED LABELED VALUES above:\n"
                            refusal_rules += "     - You MUST output a clean, structured refusal ONLY for that specific question.\n"
                            refusal_rules += "     - For example, if Swi or Sor is missing from the cache, and a question asks for displacement efficiency (Ed), recovery, mobile oil, or residual saturation, you MUST output a warning: "
                            refusal_rules += "'⚠️ I can't compute that: the session cache is loaded but its verified parameters are missing the required fluid-saturation bound(s) (Swi/Sor). Saturation-dependent results cannot be derived without them, and I will not substitute assumed values. Please re-upload a file whose extraction yields explicit Swi and Sor.'\n"
                            refusal_rules += "     - Do NOT substitute assumed, estimated, or default constants (like Swi=0.1 or Sor=0.1) under any circumstances. If it's missing, refuse that specific question.\n"
                            refusal_rules += "     - Answer all other questions in the batch normally using the verified cache.\n"
                            refusal_rules += "3. DISPLACEMENT EFFICIENCY FORMULA ENFORCEMENT:\n"
                            refusal_rules += "   - For any calculation of Displacement Efficiency (Ed) on any sample/well, you MUST strictly use: Ed = (1 - Swi - Sor) / (1 - Swi).\n"
                            refusal_rules += "   - You are strictly FORBIDDEN from using the wrong formula (Swi - Sor) / Swi. Any output of (Swi - Sor)/Swi is an immediate failure.\n"
                            refusal_rules += "   - Show the mathematical expansion dynamically based on the verified Swi and Sor from the cache.\n"
                            refusal_rules += "========================================================================\n\n"
                            
                            dynamic_system_prompt = extra_prompt + refusal_rules + dynamic_system_prompt
                            
                    if sid or email:
                        try:
                            corrs = db("SELECT original_issue, corrected_value FROM user_corrections WHERE session_id=? OR user_email=? ORDER BY timestamp ASC", (sid or "", email or ""))
                            if corrs:
                                dynamic_system_prompt += "\n\n=== LEARNED SYSTEM PREFERENCES & PAST CORRECTIONS ===\n"
                                dynamic_system_prompt += "The user has made the following corrections/overrides in this session. You MUST obey these instructions strictly for all subsequent data loading, column mapping, and parameter fitting:\n"
                                for orig, corr in corrs:
                                    dynamic_system_prompt += f"- [Issue]: {orig}  -->  [Correction]: {corr}\n"
                                dynamic_system_prompt += "======================================================\n\n"
                        except Exception as e_corr:
                            _logger.warning(f"[LearningLoop] Failed to fetch corrections: {e_corr}")

                    cfg = genai_types.GenerateContentConfig(

                        temperature=0.2,

                        tools=_HVIEL_TOOLS,

                        system_instruction=dynamic_system_prompt,

                    )



                    # â"€â"€ STREAMING PATH (multi-turn tool use) â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€

                    if stream:

                        current_contents = list(contents)

                        full_response = ""

                        

                        # Cognitive Mode Detection

                        initial_mode = "Critical Analysis"

                        msg_low = enriched.lower()

                        if any(x in msg_low for x in ["summarize", "overview", "what's in"]): initial_mode = "Engineering Overview"

                        elif any(x in msg_low for x in ["plot", "curve", "chart", "graph"]): initial_mode = "Visual Synthesizer"

                        elif any(x in msg_low for x in ["simulate", "impes", "brooks"]): initial_mode = "Simulation Engine"

                        elif any(x in msg_low for x in ["audit", "verify", "is this"]): initial_mode = "Petrophysical Audit"

                        yield {"type": "mode", "text": initial_mode}



                        for _turn in range(4):

                            tool_calls_in_turn: list = []  # (fc_obj, raw_result, formatted_str)

                            model_parts_in_turn: list = []



                            for chunk in _call_gemini_stream_with_retry(

                                client, active_model, current_contents, cfg

                            ):

                                if not (chunk.candidates and chunk.candidates[0].content):

                                    continue

                                for part in chunk.candidates[0].content.parts or []:

                                    model_parts_in_turn.append(part)

                                    if part.function_call:

                                        raw = ""

                                        # Update mode to reflect tool usage

                                        yield {"type": "mode", "text": f"Running {part.function_call.name.replace('_', ' ')}"}

                                        for is_final, data in self._execute_tool(part.function_call):

                                            if not is_final:

                                                yield {"type": "progress", "text": data}

                                            else:

                                                raw = data

                                        

                                        fmt = self._format_tool_response(

                                            part.function_call.name,

                                            dict(part.function_call.args or {}),

                                            raw,

                                        )

                                        tool_calls_in_turn.append((part.function_call, raw, fmt))



                                    elif part.text:

                                        full_response += part.text

                                        yield {"type": "token", "text": part.text}



                            # Emit formatted tool results (plots/mermaid) after text for this turn

                            for _, _, fmt in tool_calls_in_turn:

                                full_response += fmt

                                yield {"type": "token", "text": fmt}



                            if not tool_calls_in_turn:

                                # Save to cache

                                try:

                                    db("INSERT INTO response_cache (query_hash, response, created_at) VALUES (?, ?, ?)",

                                       (query_hash, full_response, time.time()))

                                except Exception: pass

                                break  # Pure text turn — conversation complete



                            # Append model turn + function responses, then loop for Gemini's interpretation

                            if model_parts_in_turn:

                                current_contents.append(

                                    genai_types.Content(role="model", parts=model_parts_in_turn)

                                )

                            fn_parts = [

                                genai_types.Part(

                                    function_response=genai_types.FunctionResponse(

                                        name=fc.name,

                                        response=self._tool_result_summary(fc.name, raw),

                                    )

                                )

                                for fc, raw, _ in tool_calls_in_turn

                            ]

                            current_contents.append(

                                genai_types.Content(role="user", parts=fn_parts)

                            )

                        return



                    # â"€â"€ NON-STREAMING PATH (multi-turn tool use) â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€

                    current_contents = list(contents)

                    final = ""

                    for _turn in range(4):

                        resp = _call_gemini_with_retry(

                            client, active_model, current_contents, cfg

                        )

                        if not (resp and resp.candidates and resp.candidates[0].content):

                            break

                        tool_calls_in_turn = []

                        model_parts_in_turn = []

                        for part in resp.candidates[0].content.parts or []:

                            model_parts_in_turn.append(part)

                            if part.function_call:

                                raw = ""

                                for is_final, data in self._execute_tool(part.function_call):

                                    if not is_final:

                                        # In non-streaming mode, we can't really yield, but let's at least capture it

                                        pass

                                    else:

                                        raw = data

                                

                                fmt = self._format_tool_response(

                                    part.function_call.name,

                                    dict(part.function_call.args or {}),

                                    raw,

                                )

                                tool_calls_in_turn.append((part.function_call, raw, fmt))

                            elif part.text:

                                final += part.text

                        for _, _, fmt in tool_calls_in_turn:

                            final += fmt

                        if not tool_calls_in_turn:

                            # Save to cache

                            try:

                                db("INSERT INTO response_cache (query_hash, response, created_at) VALUES (?, ?, ?)",

                                   (query_hash, final, time.time()))

                            except Exception: pass

                            break

                        if model_parts_in_turn:

                            current_contents.append(

                                genai_types.Content(role="model", parts=model_parts_in_turn)

                            )

                        fn_parts = [

                            genai_types.Part(

                                function_response=genai_types.FunctionResponse(

                                    name=fc.name,

                                    response=self._tool_result_summary(fc.name, raw),

                                )

                            )

                            for fc, raw, _ in tool_calls_in_turn

                        ]

                        current_contents.append(

                            genai_types.Content(role="user", parts=fn_parts)

                        )

                    yield {"type": "token", "text": final or "Unable to generate a response. Please rephrase your query."}

                    return



                except Exception as e:

                    err     = str(e).lower()

                    is_auth = any(x in err for x in ["401","403","unauthorized","permission"])

                    is_rate = any(x in err for x in ["429","resource_exhausted"])

                    is_overload = any(x in err for x in ["503","unavailable","overloaded","capacity"])

                    if (is_auth or is_rate or is_overload) and attempt < len(self._keys) - 1:

                        self.rotate_key(is_hard_fail=is_auth)

                        if stream:
                            yield {"type": "progress", "text": "PRC Node Rotating - retrying..."}
                        continue

                    if is_overload:

                        # All keys exhausted on 503 - yield a user-facing message instead of crashing

                        _logger.warning(f"[Hviel] All keys returned 503 (overload): {e}")

                        yield {"type": "token", "text": "[!]� Gemini is currently under high demand (503). Please retry in a few seconds."}

                        return

                    _logger.error(f"[Hviel] Generation failed (attempt {attempt+1}): {e}")

                    raise



        if stream:

            return _generate()

        else:

            final_resp = ""

            for c in _generate():

                if isinstance(c, dict):

                    if c.get("type") == "token":

                        final_resp += c.get("text", "")

                else:

                    final_resp += str(c)

            return final_resp or "Error generating response."



    def generate_document_json(

        self, file_type: str, message: str, history: list, kb_context: str, engineer: str,
        f_parts: list = None, sid: str = None, email: str = None,

    ) -> str:

        """Call Gemini (no tools) to produce structured JSON for HvielDocEngine.build_from_json().

        Returns raw JSON string  -  may have ```json fences which build_from_json strips."""

        _SCHEMAS = {

            "docx": (

                '{"title":"...","subtitle":"...","author":"...","date":"DD Month YYYY",'

                '"sections":[{"heading":"...","level":1,"paragraphs":["..."],"bullets":["..."]}],'

                '"tables":[{"caption":"...","headers":["Col1","Col2"],"rows":[["val1","val2"]]}]}'

            ),

            "xlsx": (

                '{"title":"...","sheets":[{"name":"Sheet Name",'

                '"headers":["Parameter (unit)","Value"],"rows":[["Swi","0.22"]],'

                '"column_widths":[24,16]}]}'

            ),

            "pptx": (

                '{"title":"...","subtitle":"...","slides":['

                '{"title":"...","content":"...","bullets":["..."]}]}'

            ),

            "pdf": (

                '{"title":"...","author":"...","sections":['

                '{"heading":"...","paragraphs":["..."],"bullets":["..."]}],'

                '"tables":[{"caption":"...","headers":["Col1"],"rows":[["val1"]]}]}'

            ),

        }

        schema = _SCHEMAS.get(file_type, _SCHEMAS["docx"])



        # Extract file data using the same read_file/to_prompt_string pipeline as the
        # chat response path — this is the single source of truth for tabular values.
        _logger.info(f"[DocGen] f_parts count: {len(f_parts or [])}")

        file_context = ""
        _debug_kw_data   = {}
        _debug_micp_data = {}
        _debug_imbi_data = {}

        for data_bytes, mime, fname in (f_parts or []):
            ext = Path(fname).suffix.lower() if fname else ".xlsx"
            if not ext:
                ext = ".xlsx"
            try:
                with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tf:
                    tf.write(data_bytes)
                    tmp_path = tf.name
                try:
                    fr_data = read_file(tmp_path)
                    _logger.info(f"[DocGen] read_file keys for {fname}: {list(fr_data.keys())}")
                    fr_text, _ = to_prompt_string(fr_data)
                    _logger.info(f"[DocGen] to_prompt_string first 500 chars for {fname}: {fr_text[:500] if fr_text else '(empty)'}")
                    if fr_text:
                        file_context += f"\n\n[UPLOADED FILE: {fname}]\n{fr_text}\n"
                    # Collect per-type extraction for debug logging
                    _scal_dbg = fr_data.get("scal", {})
                    _ttype_dbg = (_scal_dbg.get("test_type") or "UNKNOWN") if _scal_dbg else "UNKNOWN"
                    if _ttype_dbg == "KW_THROUGHPUT":
                        _debug_kw_data   = _scal_dbg.get("results", {})
                    elif _ttype_dbg == "MICP":
                        _debug_micp_data = _scal_dbg.get("results", {})
                    elif _ttype_dbg == "IMBIBITION":
                        _debug_imbi_data = _scal_dbg.get("results", {})
                    # Run SCALFileHandler to get per-sample scalars (initial_KL, final_KL,
                    # Sor_Lab, threshold_pressure, max_hg_sat, etc.) that file_reader.py
                    # does not pre-compute. These are required for table row population.
                    try:
                        scal_res = extract_file_data(tmp_path)
                        if scal_res.get("data_type") not in (None, "UNKNOWN") and scal_res.get("extracted"):
                            _summary = _scal_doc_summary(scal_res["extracted"])
                            if _summary:
                                file_context += f"\n{_summary}\n"
                                _logger.info(f"[DocGen] SCAL summary added for {fname} ({scal_res['data_type']})")
                    except Exception as _se:
                        _logger.warning(f"[DocGen] SCAL extraction failed for {fname}: {_se}")
                finally:
                    try:
                        Path(tmp_path).unlink(missing_ok=True)
                    except Exception:
                        pass
            except Exception as _fe:
                _logger.warning(f"[DocGen] File read failed for {fname}: {_fe}")

        _logger.info(f"[DocGen] file_context length: {len(file_context)} chars; kb_context length: {len(kb_context or '')} chars")

        # Session-file fallback: if no files were re-uploaded with this request,
        # recover the extracted text stored in user_files during the original upload turn.
        # This is the fix for all three table failures — the document generator was
        # producing "data not available" solely because f_parts was empty on the
        # document generation request.
        if not file_context and sid and email:
            try:
                file_rows = db(
                    "SELECT DISTINCT fname, file_hash FROM (SELECT fname, file_hash FROM m WHERE sid=? AND user_email=? AND fname IS NOT NULL ORDER BY id DESC) sub",
                    (sid, email),
                )
                _seen_fn: set = set()
                session_files: list = []
                for row in (file_rows or []):
                    _raw_fn = row[0]
                    _fhash = row[1]
                    if _raw_fn:
                        for _fn in _raw_fn.split(";"):
                            _fn = _fn.strip()
                            if _fn and _fn not in _seen_fn:
                                session_files.append((_fn, _fhash))
                                _seen_fn.add(_fn)
                for _sfname, _sfhash in session_files[:10]:
                    if _sfhash:
                        stored = db(
                            "SELECT extracted_text FROM user_files WHERE user_email=? AND file_hash=?",
                            (email, _sfhash),
                        )
                    else:
                        stored = db(
                            "SELECT extracted_text FROM user_files WHERE user_email=? AND filename=?",
                            (email, _sfname),
                        )
                    if stored and stored[0][0]:
                        file_context += f"\n\n[UPLOADED FILE: {_sfname}]\n{stored[0][0]}\n"
                        _logger.info(f"[DocGen] Recovered stored extracted_text for {_sfname} ({len(stored[0][0])} chars)")
            except Exception as _dbe:
                _logger.warning(f"[DocGen] Could not retrieve stored file context: {_dbe}")

        _logger.info(f"[DocGen] file_context after fallback: {len(file_context)} chars")

        _logger.debug(f"[DocGen] f_parts={len(f_parts or [])} sid={sid} file_context={len(file_context)} chars")

        hist_text = "".join(

            f"{h['role'].upper()}: {h.get('text','')[:600]}\n\n" for h in history[-8:]

        )

        kb_section = (
            f"\nPRIMARY DATA SOURCE — extracted values from uploaded lab files."
            f" Use these values for all tables. Do NOT write 'data not available'"
            f" if this section contains the value:\n{kb_context[:4000]}\n"
            if kb_context else ""
        )



        system_doc = (

            f"You are Hviel  -  PRC Senior AI Petrophysical Specialist, Petroleum Research Center, Libya.\n"

            f"Generate a professional {file_type.upper()} export for the PRC.\n"

            f"CRITICAL: Respond with ONLY valid JSON. No markdown fences. No explanation. Raw JSON only.\n\n"

            f"JSON SCHEMA (use this structure exactly):\n{schema}\n\n"

            f"CONTENT RULES:\n"

            f"- The PRIMARY DATA SOURCE section contains extracted values from uploaded lab files."
            f" Always populate table cells with values from that section.\n"

            f"- Only write 'data not available' if the specific value is genuinely absent from PRIMARY DATA SOURCE.\n"

            f"- NEVER invent, estimate, or hallucinate numerical values.\n"

            f"- Use engineering units throughout: mD, fraction, psi, m TVDSS, dimensionless\n"

            f"- Include Executive Summary, Methodology, Results & Interpretation, and Conclusions sections\n"

            f"- Minimum 4 sections (docx/pdf) or 2 data sheets (xlsx) with substantive content\n"

            f"- author field: \"{engineer}\"\n"

            f"- Never use '...' or '[insert value]'  -  use 'data not available' for missing values\n"

            f"\nOUTPUT STYLE RULES:\n"
            f"- Write in third person, past tense: 'Five samples were analyzed' not 'I analyzed five samples'\n"
            f"- No filler, no enthusiasm ('Great!', 'Successfully!'), no hedging\n"
            f"- Never expose internal reasoning ('I will...', 'Let me...', 'I have successfully...')\n"
            f"- Never expose tool names, source-column references, or raw data arrays in prose\n"
            f"- Round numbers to sensible significant figures matching measurement precision\n"
            f"- Summarize ranges in prose ('Pressure ranged from 0.45 to 18.4 psi'); put detailed values in tables\n"
            f"- Always state units on first mention of any value\n"

        )



        file_section = (
            f"\nUPLOADED FILE DATA (primary data source — use these values in all tables):\n{file_context}\n"
            if file_context else
            "\n[NO FILE DATA UPLOADED — write 'data not available' for any value not found in the conversation history.]\n"
        )

        user_content = (

            f"{kb_section}"

            f"{file_section}\n"

            f"CONVERSATION HISTORY:\n{hist_text}"

            f"DOCUMENT REQUEST: {message}"

        )

        _logger.debug(f"[DocGen] Prompt built: system_doc={len(system_doc)} chars, user_content={len(user_content)} chars")

        active_model = "gemini-2.5-flash"

        # Dynamic document prompt construction with corrections
        dynamic_system_doc = system_doc
        if sid or email:
            try:
                corrs = db("SELECT original_issue, corrected_value FROM user_corrections WHERE session_id=? OR user_email=? ORDER BY timestamp ASC", (sid or "", email or ""))
                if corrs:
                    dynamic_system_doc += "\n\n=== LEARNED SYSTEM PREFERENCES & PAST CORRECTIONS ===\n"
                    dynamic_system_doc += "The user has made the following corrections/overrides in this session. You MUST obey these instructions strictly for all subsequent data loading, column mapping, and parameter fitting:\n"
                    for orig, corr in corrs:
                        dynamic_system_doc += f"- [Issue]: {orig}  -->  [Correction]: {corr}\n"
                    dynamic_system_doc += "======================================================\n\n"
            except Exception as e_corr:
                _logger.warning(f"[LearningLoop] Failed to fetch corrections for docgen: {e_corr}")

        cfg = genai_types.GenerateContentConfig(temperature=0.1, system_instruction=dynamic_system_doc)

        contents = [genai_types.Content(role="user", parts=[genai_types.Part(text=user_content)])]

        _logger.debug(f"[DocGen] Pre-call context: kw={bool(_debug_kw_data)} micp={bool(_debug_micp_data)} imbi={bool(_debug_imbi_data)}")

        with self._client_lock:

            client = self._client



        for attempt in range(len(self._keys)):

            try:

                resp = _call_gemini_with_retry(

                    client, active_model, contents, cfg, max_tokens=8192

                )

                if resp and resp.candidates and resp.candidates[0].content:

                    raw = "".join(

                        p.text for p in (resp.candidates[0].content.parts or []) if p.text

                    )

                    if raw.strip():

                        raw = raw.strip()

                        # JSON-robustness gate: gpt-oss-120b occasionally fences the
                        # JSON or wraps it in prose. Verify parseability here and do
                        # ONE corrective re-prompt on failure so build_from_json never
                        # silently degrades to an empty document.
                        try:
                            parse_llm_json(raw)
                            return raw
                        except LLMJsonParseError as _pe:
                            _logger.warning(f"[DocGen] LLM JSON unparseable ({_pe}); one corrective retry...")
                            retry_contents = list(contents) + [
                                genai_types.Content(role="model", parts=[genai_types.Part(text=raw[:4000])]),
                                genai_types.Content(role="user", parts=[genai_types.Part(text=CORRECTIVE_JSON_PROMPT)]),
                            ]
                            resp2 = _call_gemini_with_retry(client, active_model, retry_contents, cfg,
                                                            max_retries=2, max_tokens=8192)
                            raw2 = ""
                            if resp2 and resp2.candidates and resp2.candidates[0].content:
                                raw2 = "".join(p.text for p in (resp2.candidates[0].content.parts or []) if p.text).strip()
                            if raw2:
                                try:
                                    parse_llm_json(raw2)
                                    return raw2
                                except LLMJsonParseError:
                                    pass
                            # Last resort: return the original reply and let
                            # build_from_json's regex salvage attempt it.
                            return raw

                raise ValueError("Empty response from model")

            except Exception as e:

                err     = str(e).lower()

                is_auth = any(x in err for x in ["401","403","unauthorized","permission"])

                is_rate = any(x in err for x in ["429","resource_exhausted"])

                if (is_auth or is_rate) and attempt < len(self._keys) - 1:

                    self.rotate_key(is_hard_fail=is_auth)

                    with self._client_lock:

                        client = self._client

                    continue

                raise

        raise ValueError("Document generation LLM call (NVIDIA NIM) failed after all retries")





# â"€â"€ RAG / KNOWLEDGE BASE â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€

EMBED_MODEL        = "gemini-embedding-2"

_EMBED_CLIENT_LOCK = threading.Lock()

_EMBED_CLIENT      = None



def _get_embed_client() -> genai_new.Client:

    global _EMBED_CLIENT

    with _EMBED_CLIENT_LOCK:

        if _EMBED_CLIENT is None:

            _EMBED_CLIENT = genai_new.Client(api_key=GEMINI_KEY_POOL[0])

        return _EMBED_CLIENT



class _LibraryEmbCache:
    """Thread-safe in-memory cache for library_chunks embeddings.

    Populated on first search; invalidated whenever library_chunks is written.
    Eliminates the per-search DB round-trip and NumPy deserialization cost.
    """
    _lock    = threading.Lock()
    _sources: list | None      = None
    _texts:   list | None      = None
    _norms:   "np.ndarray | None" = None

    @classmethod
    def get(cls):
        with cls._lock:
            if cls._sources is None:
                return None
            return cls._sources, cls._texts, cls._norms

    @classmethod
    def set(cls, sources: list, texts: list, norms: "np.ndarray"):
        with cls._lock:
            cls._sources = sources
            cls._texts   = texts
            cls._norms   = norms

    @classmethod
    def invalidate(cls):
        with cls._lock:
            cls._sources = None
            cls._texts   = None
            cls._norms   = None


class KnowledgeBase:

    CHUNK_SIZE = 600

    @staticmethod

    def _embed(text: str) -> "np.ndarray | None":

        try:

            result = _get_embed_client().models.embed_content(model=EMBED_MODEL, contents=text)

            return np.array(result.embeddings[0].values, dtype=np.float32)

        except Exception as e:

            _logger.warning(f"[RAG] Embed error: {e}")

            return None



    @staticmethod

    def chunk_text(text: str, source: str) -> list[tuple[str, str]]:

        words = text.split()

        return [(source, " ".join(words[i : i + KnowledgeBase.CHUNK_SIZE])) for i in range(0, len(words), KnowledgeBase.CHUNK_SIZE)]



    @staticmethod

    def ingest_transactional(name: str, chunks: list[tuple[str, str]], sid: str = None, email: str = None) -> None:

        """Embed and store chunks. Expects already chunked data."""

        if not chunks: return

        chunk_data = []
        valid_chunks = []
        for source, chunk in chunks:
            if not chunk or len(chunk.strip()) < 10: continue
            valid_chunks.append((source, chunk))

        if valid_chunks:
            with ThreadPoolExecutor(max_workers=16) as executor:
                futures = [executor.submit(KnowledgeBase._embed, chunk) for _, chunk in valid_chunks]
                for (source, chunk), fut in zip(valid_chunks, futures):
                    try:
                        vec = fut.result()
                    except Exception as e:
                        _logger.warning(f"[RAG] Parallel embed error: {e}")
                        vec = None
                    chunk_data.append((source, chunk, vec))

        if not chunk_data: return



        with _get_conn() as (conn, ph):

            cur = conn.cursor()

            try:

                # Cleanup existing chunks for this specific file in THIS session

                cur.execute(f"SELECT id FROM kb WHERE source = {ph} AND (sid = {ph} OR sid IS NULL)", (name, sid))

                old_ids = [r[0] for r in cur.fetchall()]

                if old_ids:

                    in_ph = ",".join([ph] * len(old_ids))

                    cur.execute(f"DELETE FROM kb_vectors WHERE chunk_id IN ({in_ph})", tuple(old_ids))

                cur.execute(f"DELETE FROM kb WHERE source = {ph} AND (sid = {ph} OR sid IS NULL)", (name, sid))

                

                for source, chunk, vec in chunk_data:

                    if ph == "?":

                        cur.execute("INSERT INTO kb (sid, user_email, source, chunk) VALUES (?,?,?,?)", (sid, email, source, chunk))

                        chunk_id = cur.lastrowid

                    else:

                        cur.execute("INSERT INTO kb (sid, user_email, source, chunk) VALUES (%s,%s,%s,%s) RETURNING id", (sid, email, source, chunk))

                        chunk_id = cur.fetchone()[0]

                    if vec is not None:

                        cur.execute(f"INSERT INTO kb_vectors (chunk_id, embedding) VALUES ({ph},{ph})", (chunk_id, vec.tobytes()))

                conn.commit()

            except Exception as e:

                _logger.error(f"[RAG] Ingest failed: {e}")

                conn.rollback()



    @staticmethod

    def search(query: str, top_k: int = 15, sid: str = None, email: str = None) -> str:

        try:

            if not query or len(query.strip()) < 8: return ""

            clean_q   = query[:1000].strip()

            

            # Skip embedding for generic chat/politeness

            generic = {"hello", "hi", "thanks", "thank", "ok", "yes", "no", "bye", "who are you"}

            if clean_q.lower() in generic: return ""



            # Filter KB chunks by session ID, or user-email for cross-session user files

            with _get_conn() as (conn, ph):

                cur = conn.cursor()

                cur.execute(
                    f"SELECT COUNT(*) FROM kb_vectors JOIN kb ON kb.id = kb_vectors.chunk_id "
                    f"WHERE (kb.sid = {ph} OR (kb.sid IS NULL AND kb.user_email = {ph}))",
                    (sid, email),
                )

                vec_count = cur.fetchone()[0]



            # ── Session / user-file vector search ──────────────────────────────
            scored_parts: list[tuple[float, str]] = []
            q_vec = None

            if 0 < vec_count < 5000:

                q_vec = KnowledgeBase._embed(clean_q)

                if q_vec is not None:

                    rows = db(
                        f"SELECT kb.source, kb.chunk, kb_vectors.embedding FROM kb_vectors "
                        f"JOIN kb ON kb.id = kb_vectors.chunk_id "
                        f"WHERE (kb.sid = {ph} OR (kb.sid IS NULL AND kb.user_email = {ph}))",
                        (sid, email),
                    )

                    if rows:

                        sources = [r[0] for r in rows]; texts = [r[1] for r in rows]; raw_vecs = [r[2] for r in rows]

                        vecs = np.stack([np.frombuffer(bytes(v) if isinstance(v, memoryview) else v, dtype=np.float32) for v in raw_vecs])

                        q_norm = q_vec / (np.linalg.norm(q_vec) + 1e-9)

                        v_norms = vecs / (np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-9)

                        scores = v_norms @ q_norm

                        for i in np.argsort(scores)[::-1][:top_k]:
                            if scores[i] > 0.40:
                                scored_parts.append((float(scores[i]), f"[From: {sources[i]}]\n{texts[i]}"))

            # ── Library vector search (global, in-memory cached) ─────────────────
            try:
                cached = _LibraryEmbCache.get()
                if cached is None:
                    # Cache miss: load once from DB, normalize, and store
                    lib_rows = db("SELECT source, chunk_text, embedding FROM library_chunks WHERE embedding IS NOT NULL")
                    if lib_rows:
                        _src  = [r[0] for r in lib_rows]
                        _txt  = [r[1] for r in lib_rows]
                        _vecs = np.stack([
                            np.frombuffer(bytes(v) if isinstance(v, memoryview) else v, dtype=np.float32)
                            for v in (r[2] for r in lib_rows)
                        ])
                        _nrm  = _vecs / (np.linalg.norm(_vecs, axis=1, keepdims=True) + 1e-9)
                        _LibraryEmbCache.set(_src, _txt, _nrm)
                        cached = (_src, _txt, _nrm)
                if cached is not None:
                    lib_sources, lib_texts, lv_norms = cached
                    if q_vec is None:
                        q_vec = KnowledgeBase._embed(clean_q)
                    if q_vec is not None:
                        q_norm_lib = q_vec / (np.linalg.norm(q_vec) + 1e-9)
                        lib_scores = lv_norms @ q_norm_lib
                        for i in np.argsort(lib_scores)[::-1][:5]:
                            if lib_scores[i] > 0.35:
                                scored_parts.append((float(lib_scores[i]), f"[Library: {lib_sources[i]}]\n{lib_texts[i]}"))
            except Exception as _le:
                _logger.debug(f"[RAG] Library search error: {_le}")

            if scored_parts:
                scored_parts.sort(key=lambda x: x[0], reverse=True)
                return "\n\n".join(t for _, t in scored_parts[:top_k])

            # Fallback to keyword search with session filtering

            words = [w.lower() for w in re.split(r"\W+", clean_q) if len(w) > 3][:5]

            if not words: return ""



            # ph is still in scope from the vec_count query above — no second _get_conn() needed
            clause = " OR ".join([f"LOWER(chunk) LIKE {ph}" for _ in words])

            params = tuple([sid, email] + [f"%{w}%" for w in words])

            rows = db(
                f"SELECT source, chunk FROM kb "
                f"WHERE (sid = {ph} OR (sid IS NULL AND user_email = {ph})) AND ({clause}) LIMIT {top_k}",
                params,
            )

            return "\n\n".join([f"[From: {r[0]}]\n{r[1]}" for r in rows])

        except Exception as e:

            _logger.error(f"[RAG] Search error: {e}")

            return ""



    @staticmethod

    async def search_async(query: str, top_k: int = 15, sid: str = None, email: str = None) -> str:

        loop = asyncio.get_running_loop()

        return await loop.run_in_executor(None, KnowledgeBase.search, query, top_k, sid, email)



    @staticmethod

    def delete_session_data(sid: str) -> None:

        """Clear all KB chunks associated with a session."""

        with _get_conn() as (conn, ph):

            cur = conn.cursor()

            try:

                cur.execute(f"SELECT id FROM kb WHERE sid = {ph}", (sid,))

                chunk_ids = [r[0] for r in cur.fetchall()]

                if chunk_ids:

                    in_ph = ",".join([ph] * len(chunk_ids))

                    cur.execute(f"DELETE FROM kb_vectors WHERE chunk_id IN ({in_ph})", tuple(chunk_ids))

                cur.execute(f"DELETE FROM kb WHERE sid = {ph}", (sid,))

                conn.commit()

            except Exception as e:

                _logger.error(f"[RAG] Session cleanup failed: {e}")

                conn.rollback()





# â"€â"€ APP SETUP â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€

def init_db() -> None:

    base_stmts = [

        "CREATE TABLE IF NOT EXISTS m (id INTEGER PRIMARY KEY AUTOINCREMENT, sid TEXT, role TEXT, text TEXT, url TEXT, ts REAL, user_email TEXT, fname TEXT, file_hash TEXT)",

        "CREATE TABLE IF NOT EXISTS sessions (sid TEXT PRIMARY KEY, title TEXT NOT NULL DEFAULT 'New Study', user_email TEXT, created_at REAL, updated_at REAL)",

        "CREATE TABLE IF NOT EXISTS kb (id INTEGER PRIMARY KEY AUTOINCREMENT, sid TEXT, user_email TEXT, source TEXT, chunk TEXT)",

        "CREATE TABLE IF NOT EXISTS kb_vectors (id INTEGER PRIMARY KEY AUTOINCREMENT, chunk_id INTEGER UNIQUE, embedding BLOB)",

        "CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT UNIQUE, name TEXT, created_at REAL)",

        "CREATE TABLE IF NOT EXISTS feedback (id INTEGER PRIMARY KEY AUTOINCREMENT, user_email TEXT, bug_report TEXT, ts REAL)",

        "CREATE TABLE IF NOT EXISTS analytics_events (id INTEGER PRIMARY KEY AUTOINCREMENT, user_email TEXT, event_type TEXT, event_data TEXT, ts REAL)",

        # THE AUDITOR'S LEDGER  -  append-only physics integrity log

        "CREATE TABLE IF NOT EXISTS physics_audits (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, user_email TEXT, timestamp REAL, data_type TEXT, health_score INTEGER, violations TEXT, file_name TEXT)",

        "CREATE TABLE IF NOT EXISTS response_cache (id INTEGER PRIMARY KEY AUTOINCREMENT, query_hash TEXT UNIQUE, response TEXT, created_at REAL)",

        "CREATE TABLE IF NOT EXISTS session_summaries (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT UNIQUE, user_email TEXT, well_name TEXT, data_type TEXT, key_params TEXT, created_at REAL)",

        # ── LIBRARY (shared, global, admin-ingested documents) ─────────────────
        "CREATE TABLE IF NOT EXISTS library_docs (id INTEGER PRIMARY KEY AUTOINCREMENT, filename TEXT NOT NULL, file_hash TEXT NOT NULL UNIQUE, data_type TEXT, uploaded_by TEXT, created_at REAL)",
        "CREATE TABLE IF NOT EXISTS library_chunks (id INTEGER PRIMARY KEY AUTOINCREMENT, doc_id INTEGER REFERENCES library_docs(id) ON DELETE CASCADE, chunk_text TEXT NOT NULL, embedding BLOB, source TEXT)",

        # ── USER FILE STORE (per-user persistent file history) ─────────────────
        "CREATE TABLE IF NOT EXISTS user_files (id INTEGER PRIMARY KEY AUTOINCREMENT, user_email TEXT NOT NULL, filename TEXT NOT NULL, file_hash TEXT NOT NULL, extracted_text TEXT, data_type TEXT, key_params TEXT, created_at REAL, UNIQUE(user_email, file_hash))",

        "CREATE TABLE IF NOT EXISTS api_metrics (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, timestamp REAL, model TEXT, prompt_tokens INTEGER, completion_tokens INTEGER, cost_usd REAL)",
        "CREATE TABLE IF NOT EXISTS user_corrections (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, user_email TEXT, original_issue TEXT, corrected_value TEXT, timestamp REAL)",
        "CREATE TABLE IF NOT EXISTS session_cache (sid TEXT PRIMARY KEY, ground_truth TEXT, labeled_values TEXT, flat_vectors TEXT, raw_excel_data TEXT, updated_at REAL)",
        "CREATE TABLE IF NOT EXISTS basin_physics_rules (basin_name TEXT, rule_key TEXT, min_limit REAL, max_limit REAL, PRIMARY KEY (basin_name, rule_key))",
    ]

    if _PG_AVAILABLE:
        base_stmts = [s.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY").replace("BLOB", "BYTEA") for s in base_stmts]

    for s in base_stmts:
        try: db(s)
        except Exception: pass
    # Seed default basin rules
    try:
        db("INSERT INTO basin_physics_rules (basin_name, rule_key, min_limit, max_limit) VALUES "
           "('Default', 'm', 1.3, 2.5), "
           "('Default', 'a', 0.5, 1.5) "
           "ON CONFLICT (basin_name, rule_key) DO NOTHING")
    except Exception:
        pass

    try: db("CREATE INDEX IF NOT EXISTS idx_query_hash ON response_cache(query_hash)")
    except Exception: pass

    try: db("CREATE INDEX IF NOT EXISTS idx_library_chunks_doc ON library_chunks(doc_id)")
    except Exception: pass

    try: db("CREATE INDEX IF NOT EXISTS idx_user_files_email ON user_files(user_email)")
    except Exception: pass

    try: db("CREATE INDEX IF NOT EXISTS idx_m_sid ON m(sid)")
    except Exception: pass

    try: db("CREATE INDEX IF NOT EXISTS idx_m_user_email ON m(user_email)")
    except Exception: pass

    try: db("CREATE INDEX IF NOT EXISTS idx_sessions_user_email ON sessions(user_email)")
    except Exception: pass

    try: db("CREATE INDEX IF NOT EXISTS idx_kb_source ON kb(source)")
    except Exception: pass

    try: db("CREATE INDEX IF NOT EXISTS idx_kb_sid ON kb(sid)")
    except Exception: pass

    try: db("CREATE INDEX IF NOT EXISTS idx_library_chunks_source ON library_chunks(source)")
    except Exception: pass

    # Migrations for KB isolation

    # Migrations for KB isolation

    for col in ["sid", "user_email"]:

        try: 
            # Use raw execute to avoid triggering the DB retry/error logs in db() function
            with _get_conn() as (conn, ph):
                cur = conn.cursor()
                cur.execute(f"ALTER TABLE kb ADD COLUMN {col} TEXT")
                conn.commit()
        except Exception: 
            pass

    try:
        with _get_conn() as (conn, ph):
            cur = conn.cursor()
            cur.execute("ALTER TABLE m ADD COLUMN file_hash TEXT")
            conn.commit()
    except Exception:
        pass

    # Backfill existing m rows  ->  sessions table (migration for pre-existing installs)

    try:

        if _PG_AVAILABLE:

            db("INSERT INTO sessions (sid,title,user_email,created_at,updated_at) "

               "SELECT sid,'New Study',MAX(user_email),MIN(ts),MAX(ts) FROM m GROUP BY sid "

               "ON CONFLICT (sid) DO NOTHING")

        else:

            db("INSERT OR IGNORE INTO sessions (sid,title,user_email,created_at,updated_at) "

               "SELECT sid,'New Study',MAX(user_email),MIN(ts),MAX(ts) FROM m GROUP BY sid")

    except Exception:

        pass



@asynccontextmanager
async def lifespan(app: FastAPI):
    global GLOBAL_EVENT_LOOP
    GLOBAL_EVENT_LOOP = asyncio.get_running_loop()
    # API key validation on startup with clear error (Crash Issue 6)
    if not is_testing():
        try:
            validate_gemini_api_keys()
        except ValueError as ve:
            _logger.critical(f"[STARTUP-CRITICAL] {ve}")
            os._exit(1)
    init_db()
    try:
        purge_all_historical_assets()
    except Exception as pe:
        _logger.error(f"Startup purge failed: {pe}")
    try:
        start_session_ttl_monitor()
    except Exception as me:
        _logger.error(f"Failed to start TTL monitor: {me}")
    # Increase default thread pool size to support 50+ concurrent engineers (blocking I/O)
    loop = asyncio.get_running_loop()
    executor = ThreadPoolExecutor(max_workers=100)
    loop.set_default_executor(executor)
    # Increase AnyIO's thread pool capacity (used by Starlette for sync generators)
    try:
        limiter = anyio.to_thread.current_default_thread_limiter()
        limiter.total_tokens = 100
    except Exception as e:
        _logger.warning(f"Failed to set AnyIO thread limit: {e}")
        
    # Write openapi.json on startup
    try:
        from fastapi.openapi.utils import get_openapi
        openapi_schema = get_openapi(
            title=app.title,
            version=app.version,
            openapi_version=app.openapi_version,
            description=app.description,
            routes=app.routes,
        )
        written = False
        try:
            vault_dir = Path(settings.PRC_AI_VAULT)
            vault_dir.mkdir(parents=True, exist_ok=True)
            openapi_path = vault_dir / "openapi.json"
            with open(openapi_path, "w", encoding="utf-8") as f:
                _json.dump(openapi_schema, f, indent=2)
            _logger.info(f"OpenAPI schema successfully written to vault: {openapi_path}")
            written = True
        except Exception as vault_err:
            _logger.warning(f"Could not write OpenAPI schema to vault ({vault_err}). Trying fallback to current directory.")
            
        if not written:
            openapi_path = Path("openapi.json")
            with open(openapi_path, "w", encoding="utf-8") as f:
                _json.dump(openapi_schema, f, indent=2)
            _logger.info(f"OpenAPI schema successfully written to fallback: {openapi_path.resolve()}")
    except Exception as oe:
        _logger.error(f"Failed to export OpenAPI schema: {oe}")

    try:
        yield
    finally:
        executor.shutdown(wait=False)  # release threads on shutdown; don't block SIGTERM



is_prod = not (settings.DEBUG or settings.TESTING)
docs_url = None if is_prod else "/docs"
redoc_url = None if is_prod else "/redoc"
openapi_url = None if is_prod else "/openapi.json"

app = FastAPI(
    lifespan=lifespan,
    docs_url=docs_url,
    redoc_url=redoc_url,
    openapi_url=openapi_url
)

if _RATE_LIMIT:
    app.state.limiter = _limiter

# Global Exception Handlers
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
import traceback
import alerting

@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    req_id = request_id_var.get("-")
    headers = {"Retry-After": "60"}
    content = {
        "error": f"Rate limit exceeded: {exc.detail or str(exc)}",
        "code": 429,
        "request_id": req_id
    }
    _logger.warning(f"Rate limit exceeded for client {request.client.host if request.client else 'unknown'}: {exc.detail}")
    return JSONResponse(status_code=429, content=content, headers=headers)

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    req_id = request_id_var.get("-")
    content = {
        "error": exc.detail,
        "code": exc.status_code,
        "request_id": req_id
    }
    _logger.error(f"HTTPException status={exc.status_code} detail={exc.detail} request_id={req_id}")
    return JSONResponse(status_code=exc.status_code, content=content)

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    req_id = request_id_var.get("-")
    errors_detail = str(exc.errors())
    content = {
        "error": f"Validation failed: {errors_detail}",
        "code": 422,
        "request_id": req_id
    }
    _logger.error(f"Validation error: {errors_detail} request_id={req_id}")
    return JSONResponse(status_code=422, content=content)

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    req_id = request_id_var.get("-")
    _logger.error(f"Unhandled exception: {str(exc)}\n{traceback.format_exc()} request_id={req_id}")
    
    try:
        alerting.trigger_500_alert(request.url.path, exc)
    except Exception as alert_err:
        _logger.error(f"Failed to send alert for unhandled exception: {alert_err}")

    is_prod_env = not (settings.DEBUG or settings.TESTING)
    if is_prod_env:
        error_msg = "Internal server error. Please try again."
    else:
        error_msg = f"Internal server error: {str(exc)}"
        
    content = {
        "error": error_msg,
        "code": 500,
        "request_id": req_id
    }
    return JSONResponse(status_code=500, content=content)

# Request ID & Duration Alerting Middleware
@app.middleware("http")
async def add_request_id_and_timer(request: Request, call_next):
    req_id = request.headers.get("X-Request-ID") or request.headers.get("x-request-id") or str(uuid.uuid4())
    token = request_id_var.set(req_id)
    start_time = time.time()
    try:
        response = await call_next(request)
        duration = time.time() - start_time
        
        # Check if response took > 30s and is not SSE
        if duration > 30.0:
            content_type = response.headers.get("content-type", "")
            if "text/event-stream" not in content_type:
                try:
                    alerting.trigger_latency_alert(request.url.path, duration)
                except Exception as alert_err:
                    _logger.error(f"Failed to send alert for slow response: {alert_err}")
                    
        response.headers["X-Request-ID"] = req_id
        return response
    finally:
        request_id_var.reset(token)



_CORS_ORIGINS: list[str] = [
    o.strip()
    for o in os.getenv("ALLOWED_ORIGINS", "").split(",")
    if o.strip() and o.strip() != "*"
]

app.add_middleware(

    CORSMiddleware,

    allow_origins=_CORS_ORIGINS,

    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",

    allow_credentials=True,

    allow_methods=["*"],

    allow_headers=["*"],

)



assistant = PRCChatAssistant(GEMINI_KEY_POOL)

# Central shared PRC vault — all exported decks/spreadsheets/Word/PDF reports
# from BOTH Hviel (SCAL) and Aviel (PVT) are written here. Overridable via env.
PRC_VAULT = Path(os.getenv("PRC_AI_VAULT", r"C:/Users/Asus/Downloads/PRC_AI_Vault"))
PRC_VAULT.mkdir(parents=True, exist_ok=True)

try:

    hviel_engine = HvielDocEngine(output_dir=str(PRC_VAULT))

except Exception as _he:

    _logger.error(f"[SYSTEM] HvielDocEngine failed: {_he}")

    hviel_engine = None



# â"€â"€ ROUTES â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€

# â"€â"€ AUTH & SESSION VERIFICATION â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€

def _verify_session_owner(sid: str, email: str):

    """Row-Level Security: every session endpoint must verify the caller owns the session."""

    if not email:

        raise HTTPException(status_code=401, detail="Authentication required")

    row = db("SELECT user_email FROM sessions WHERE sid=?", (sid,))

    if row and row[0][0] and row[0][0].lower().strip() != email.lower().strip():

        _logger.warning(f"[SECURITY] Unauthorized access attempt: {email}  ->  session {sid}")

        raise HTTPException(status_code=403, detail="Unauthorized: You do not own this session.")



@app.get("/health")
def health():
    db_ok = False
    db_err = ""
    try:
        db("SELECT 1")
        db_ok = True
    except Exception as e:
        db_ok = False
        db_err = str(e)

    # Check key pool
    with _FAILED_KEYS_LOCK:
        snap = dict(_FAILED_KEYS)
    now = time.time()
    cooldown = sum(1 for v in snap.values() if (now - v.get("ts", 0)) < v.get("wait", 0))
    keys_degraded = len(GEMINI_KEY_POOL) == 0 or (cooldown >= len(GEMINI_KEY_POOL))

    if not db_ok or keys_degraded:
        details = []
        if not db_ok:
            details.append(f"Database connectivity failed: {db_err}")
        if keys_degraded:
            details.append(f"AI API Keys pool is degraded (All {len(GEMINI_KEY_POOL)} keys are in cooldown or pool is empty).")
        
        try:
            alerting.send_alert(
                subject="Degraded Health Check Alert (SCAL Pipeline)",
                message="\n".join(details)
            )
        except Exception as alert_err:
            _logger.error(f"Failed to send alert for degraded health: {alert_err}")
            
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "db": "ok" if db_ok else "fail", "api_keys": "degraded" if keys_degraded else "ok"}
        )

    return {"status": "ok", "db": "postgres" if _PG_AVAILABLE else "sqlite"}



@app.get("/api/diag")
def diag(
    authorization: Optional[str] = Header(None),
    token: Optional[str] = Query(None),
):
    verify_user_or_admin(authorization=authorization, token=token)
    with _FAILED_KEYS_LOCK: snap = dict(_FAILED_KEYS)

    now = time.time(); cooldown = sum(1 for v in snap.values() if (now - v.get("ts",0)) < v.get("wait",0))

    with assistant._idx_lock: idx = assistant._current_idx

    return {"version": "PRC-HUB-VER-14-PROD-READY", "node_pool_size": len(GEMINI_KEY_POOL), "active_node_idx": idx, "nodes_in_cooldown": cooldown}



@app.get("/api/v1/telemetry/metrics")
async def get_telemetry_metrics(
    authorization: Optional[str] = Header(None),
    x_admin_pin: Optional[str] = Header(None),
    pin: Optional[str] = None
):
    # Authenticate either via Bearer Token, X-Admin-Pin header, or pin query parameter
    authenticated = False
    if authorization and authorization.startswith("Bearer "):
        try:
            verify_admin(authorization)
            authenticated = True
        except HTTPException:
            pass
    
    if not authenticated:
        input_pin = (x_admin_pin or pin or "").strip()
        if ADMIN_PIN and hmac.compare_digest(input_pin, ADMIN_PIN):
            authenticated = True
            
    if not authenticated:
        raise HTTPException(status_code=401, detail="Unauthorized metrics access. Valid Bearer token or ADMIN_PIN required.")
        
    # Compile Latency Metrics
    with _REPORT_LATENCY_LOCK:
        latencies = list(_REPORT_LATENCY_LIST)
    avg_latency = sum(latencies) / len(latencies) if latencies else 0.0
    
    # Fetch cumulative API costs
    try:
        cost_res = db("SELECT SUM(cost_usd) FROM api_metrics")
        cumulative_cost_usd = float(cost_res[0][0]) if cost_res and cost_res[0][0] is not None else 0.0
    except Exception:
        cumulative_cost_usd = 0.0
        
    # Fetch total volume of processed petrophysical datasets
    try:
        dataset_res = db("SELECT COUNT(*) FROM physics_audits")
        total_processed_datasets = int(dataset_res[0][0]) if dataset_res and dataset_res[0][0] is not None else 0
    except Exception:
        total_processed_datasets = 0
        
    db_metrics = {}
    if _PG_AVAILABLE and _PG_POOL is not None:
        try:
            # ThreadedConnectionPool internal variables
            active = 0
            if hasattr(_PG_POOL, "_used"):
                active = len(_PG_POOL._used)
                db_metrics["pg_pool_active_connections"] = active
            if hasattr(_PG_POOL, "_pool"):
                db_metrics["pg_pool_idle_connections"] = len(_PG_POOL._pool)
            
            max_conn = 50
            if hasattr(_PG_POOL, "maxconn"):
                max_conn = _PG_POOL.maxconn
                db_metrics["pg_pool_max_connections"] = max_conn
            
            # Pool health status: check if we are hitting the ceiling
            if active >= max_conn:
                db_metrics["db_pool_health"] = "exhausted"
            else:
                db_metrics["db_pool_health"] = "healthy"

            # Database WAL file size (PostgreSQL)
            try:
                # pg_ls_waldir() requires superuser or pg_monitor role
                wal_res = db("SELECT SUM(size) FROM pg_ls_waldir()")
                db_metrics["pg_wal_size_kb"] = float(wal_res[0][0]) / 1024.0 if wal_res and wal_res[0][0] is not None else 0.0
            except Exception:
                db_metrics["pg_wal_size_kb"] = None  # Restricted access or managed service
                
        except Exception as e:
            _logger.error(f"Error fetching pg pool metrics: {e}")
            db_metrics["db_pool_health"] = "error"
    else:
        try:
            db_path_obj = Path(DB_PATH)
            db_metrics["sqlite_db_size_kb"] = db_path_obj.stat().st_size / 1024.0 if db_path_obj.exists() else 0.0
            
            # Use pathlib exclusively for WAL path discovery as per AGENTS.md
            wal_path_obj = db_path_obj.with_name(db_path_obj.name + "-wal")
            db_metrics["sqlite_wal_size_kb"] = wal_path_obj.stat().st_size / 1024.0 if wal_path_obj.exists() else 0.0
            
            # SQLite health check
            db_metrics["db_pool_health"] = "healthy" if db_path_obj.exists() else "uninitialized"
        except Exception as e:
            _logger.error(f"Error fetching sqlite metrics: {e}")
            db_metrics["db_pool_health"] = "error"

    metrics_payload = {
        "average_document_compilation_latency_seconds": round(avg_latency, 2),
        "cumulative_api_token_cost_usd": round(cumulative_cost_usd, 6),
        "total_processed_datasets_volume": total_processed_datasets,
        "cached_report_runs_count": len(latencies)
    }
    metrics_payload.update(db_metrics)

    return {
        "status": "success",
        "metrics": metrics_payload
    }




# â"€â"€ ADMIN AUTH â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€

def verify_admin(authorization: str = Header(None)):

    if not authorization or not authorization.startswith("Bearer "):

        raise HTTPException(status_code=401, detail="Missing or invalid token")

    token = authorization.split(" ")[1]

    if token not in _ADMIN_TOKENS or time.time() > _ADMIN_TOKENS[token]:

        if token in _ADMIN_TOKENS: del _ADMIN_TOKENS[token]

        raise HTTPException(status_code=401, detail="Token expired or invalid")

    return True



@app.post("/api/auth")

async def user_login(pin: str = Form(...), name: str = Form(""), email: str = Form("")):

    # Auth against configured ADMIN_PIN (must be set in environment)

    if not hmac.compare_digest(str(pin), str(ADMIN_PIN)):

        _logger.warning("[AUTH] Failed user login attempt")

        await asyncio.sleep(0.5)

        raise HTTPException(status_code=401, detail="Invalid Access Code")

    # Register/refresh the engineer profile (replaces the old /api/register)

    if email:

        try:

            db("INSERT INTO users (email, name, created_at) VALUES (?, ?, ?)",
               (normalize_email(email), name.strip(), time.time()))

        except Exception:

            pass  # already registered

    # Issue a session token so user-facing endpoints can authenticate

    token = _secrets.token_hex(16)

    _USER_TOKENS[token] = time.time() + _USER_TOKEN_TTL

    return {"status": "success", "token": token}



@app.post("/api/admin/auth")

async def admin_login(pin: str = Form(...)):

    # Auth against configured ADMIN_PIN (must be set in environment)

    if not hmac.compare_digest(str(pin), str(ADMIN_PIN)):

        _logger.warning("[ADMIN] Failed login attempt")

        await asyncio.sleep(1) # Throttling

        raise HTTPException(status_code=401, detail="Invalid Admin PIN")

    

    _logger.info("[ADMIN] Successful login")

    token = _secrets.token_hex(16)

    _ADMIN_TOKENS[token] = time.time() + _ADMIN_TOKEN_TTL

    return {"token": token}



@app.get("/api/admin/summary")

def get_summary(admin: bool = Depends(verify_admin)):

    try:

        t_users    = db("SELECT COUNT(*) FROM users")[0][0]

        t_feedback = db("SELECT COUNT(*) FROM feedback")[0][0]

        t_events   = db("SELECT COUNT(*) FROM analytics_events")[0][0]

        t_msgs     = db("SELECT COUNT(*) FROM m")[0][0]

        t_sessions = len(db("SELECT DISTINCT sid FROM m"))

        t_kb       = db("SELECT COUNT(*) FROM kb")[0][0]

        # ── Visual Admin Telemetry updates ──
        
        t_tokens_res = db("SELECT SUM(prompt_tokens + completion_tokens) FROM api_metrics")
        t_tokens = t_tokens_res[0][0] if t_tokens_res and t_tokens_res[0][0] is not None else 0

        t_cost_res = db("SELECT SUM(cost_usd) FROM api_metrics")
        t_cost = t_cost_res[0][0] if t_cost_res and t_cost_res[0][0] is not None else 0.0

        t_engineers_res = db("SELECT COUNT(DISTINCT user_email) FROM m WHERE user_email IS NOT NULL AND role = 'user'")
        t_engineers = t_engineers_res[0][0] if t_engineers_res and t_engineers_res[0][0] is not None else 0

        # Usage breakdown by engineer
        eng_breakdown = []
        try:
            eng_rows = db("""
                SELECT COALESCE(s.user_email, 'anonymous') as email, 
                       SUM(a.prompt_tokens + a.completion_tokens) as tokens, 
                       SUM(a.cost_usd) as cost, 
                       COUNT(DISTINCT a.session_id) as sessions 
                FROM api_metrics a 
                LEFT JOIN sessions s ON a.session_id = s.sid 
                GROUP BY s.user_email 
                ORDER BY tokens DESC
            """)
            eng_breakdown = [{"email": r[0], "tokens": r[1], "cost": r[2], "sessions": r[3]} for r in eng_rows]
        except Exception as e_eng:
            _logger.warning(f"[AdminSummary] Failed to query engineer breakdown: {e_eng}")

        # Usage breakdown by model
        mod_breakdown = []
        try:
            mod_rows = db("SELECT model, SUM(prompt_tokens + completion_tokens) as tokens, SUM(cost_usd) as cost FROM api_metrics GROUP BY model")
            mod_breakdown = [{"model": r[0], "tokens": r[1], "cost": r[2]} for r in mod_rows]
        except Exception as e_mod:
            _logger.warning(f"[AdminSummary] Failed to query model breakdown: {e_mod}")

        return {

            "total_users": t_users, "total_feedback": t_feedback,

            "total_events": t_events, "total_messages": t_msgs,

            "total_sessions": t_sessions, "total_kb_chunks": t_kb,

            "total_tokens": t_tokens, "total_cost_usd": t_cost,
            
            "total_engineers": t_engineers,
            
            "engineer_breakdown": eng_breakdown,
            
            "model_breakdown": mod_breakdown,

            "storage_type": "PostgreSQL" if _PG_AVAILABLE else "SQLite"

        }

    except Exception as e:

        raise HTTPException(status_code=500, detail=str(e))



@app.get("/api/admin/analytics")

def get_analytics(admin: bool = Depends(verify_admin)):

    rows = db("SELECT user_email, event_type, event_data, ts FROM analytics_events ORDER BY ts DESC LIMIT 200")

    return {"events": [{"email": r[0], "type": r[1], "data": r[2], "ts": r[3]} for r in rows]}



@app.get("/api/admin/feedback")

def get_feedback(admin: bool = Depends(verify_admin)):

    rows = db("SELECT user_email, bug_report, ts FROM feedback ORDER BY ts DESC LIMIT 100")

    return {"feedback": [{"email": r[0], "report": r[1], "ts": r[2]} for r in rows]}



@app.get("/api/admin/users")

def get_users(admin: bool = Depends(verify_admin)):

    rows = db("SELECT email, name, created_at FROM users ORDER BY created_at DESC")

    return {"users": [{"email": r[0], "name": r[1], "created_at": r[2]} for r in rows]}



@app.post("/api/feedback")
async def submit_feedback(
    user_email: str = Form(""),
    bug_report: str = Form(...),
    authorization: Optional[str] = Header(None),
    token: Optional[str] = Query(None),
):
    verify_user_or_admin(authorization=authorization, token=token, user_email=user_email)
    await async_db("INSERT INTO feedback (user_email, bug_report, ts) VALUES (?, ?, ?)", (user_email.lower(), bug_report, time.time()))
    return {"status": "ok"}



@app.post("/api/analytics/event")
async def track_event(
    user_email: str = Form(""),
    event_type: str = Form(...),
    event_data: str = Form(""),
    authorization: Optional[str] = Header(None),
    token: Optional[str] = Query(None),
):
    verify_user_or_admin(authorization=authorization, token=token, user_email=user_email)
    await async_db("INSERT INTO analytics_events (user_email, event_type, event_data, ts) VALUES (?, ?, ?, ?)",
       (user_email.lower(), event_type, event_data, time.time()))
    return {"status": "ok"}



@app.get("/api/sessions")
async def get_sessions(
    email: str = None,
    authorization: Optional[str] = Header(None),
    token: Optional[str] = Query(None),
):
    verify_user_or_admin(authorization=authorization, token=token, email_query=email)
    if not email:
        return []
    const_email = email.lower().strip()
    rows = await async_db(
        "SELECT sid, title, updated_at FROM sessions "
        "WHERE user_email=? ORDER BY updated_at DESC",
        (const_email,),
    )
    return [{"id": r[0], "title": r[1], "ts": r[2]} for r in rows]



@app.get("/api/session/{sid}")
def get_session(
    sid: str,
    email: str = None,
    authorization: Optional[str] = Header(None),
    token: Optional[str] = Query(None),
):
    verify_user_or_admin(authorization=authorization, token=token, email_query=email)
    _verify_session_owner(sid, email)
    rows = db("SELECT role, text, url, ts, fname FROM m WHERE sid=? AND user_email=? ORDER BY id", (sid, email))
    title_row = db("SELECT title FROM sessions WHERE sid=? AND user_email=?", (sid, email))
    title = title_row[0][0] if title_row else "New Study"
    if not title_row:
        # Pre-create the empty session so it exists in the database and sidebar immediately
        if _PG_AVAILABLE:
            db("INSERT INTO sessions (sid, title, user_email, updated_at) VALUES (?, 'New Study', ?, ?) ON CONFLICT (sid) DO NOTHING", (sid, email or "", time.time()))
        else:
            db("INSERT OR IGNORE INTO sessions (sid, title, user_email, created_at, updated_at) VALUES (?, 'New Study', ?, ?, ?)", (sid, email or "", time.time(), time.time()))
    return {
        "status":"ok",
        "title": title,
        "messages":[{"role":r,"text":t,"download_url":u,"ts":ts,"fileName":fn} for r,t,u,ts,fn in rows]
    }



@app.post("/api/session/{sid}/title")
async def update_session_title(
    sid: str,
    email: str = Form(...),
    title: str = Form(...),
    authorization: Optional[str] = Header(None),
    token: Optional[str] = Query(None),
):
    verify_user_or_admin(authorization=authorization, token=token, user_email=email)
    _verify_session_owner(sid, email)
    if _PG_AVAILABLE:
        await async_db("INSERT INTO sessions (sid, title, user_email, updated_at) VALUES (?, ?, ?, ?) "
           "ON CONFLICT (sid) DO UPDATE SET title = EXCLUDED.title, updated_at = EXCLUDED.updated_at",
           (sid, title, email, time.time()))
    else:
        await async_db("INSERT OR REPLACE INTO sessions (sid, title, user_email, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
           (sid, title, email, time.time(), time.time()))
    return {"status": "ok"}



@app.delete("/api/session/{sid}")
def delete_session(
    sid: str,
    email: str = None,
    authorization: Optional[str] = Header(None),
    token: Optional[str] = Query(None),
):
    verify_user_or_admin(authorization=authorization, token=token, email_query=email)
    _verify_session_owner(sid, email)
    
    # Retrieve and delete files associated with this session
    try:
        rows = db("SELECT DISTINCT fname FROM m WHERE sid=? AND user_email=?", (sid, email))
        fnames = []
        for r in (rows or []):
            if r[0]:
                for fn in r[0].split(";"):
                    fn = fn.strip()
                    if fn:
                        fnames.append(fn)
        for fn in fnames:
            db("DELETE FROM user_files WHERE user_email=? AND filename=?", (email, fn))
            _logger.info(f"[DeleteSession] Cleared file record {fn} from user_files")
    except Exception as _fe:
        _logger.warning(f"[DeleteSession] Failed to clear user_files: {_fe}")

    db("DELETE FROM m WHERE sid=?", (sid,))
    db("DELETE FROM sessions WHERE sid=?", (sid,))
    db("DELETE FROM physics_audits WHERE session_id=?", (sid,))
    KnowledgeBase.delete_session_data(sid)
    return {"status": "ok"}



def parse_q0_questions(text: str) -> list[tuple[str, str]]:
    import csv
    questions = []
    lines = text.split('\n')
    in_q0_sheet = False
    for line in lines:
        lstrip = line.strip()
        if 'Sheet:' in line:
            if 'Q0' in line:
                in_q0_sheet = True
            else:
                in_q0_sheet = False
        
        if in_q0_sheet or not any('Sheet:' in l for l in lines):
            try:
                row = list(csv.reader([lstrip]))[0]
                if len(row) >= 2 and row[0].strip().startswith('Q') and row[0].strip()[1:].isdigit():
                    q_num = row[0].strip()
                    q_text = row[-1].strip()
                    if q_text and q_text.lower() not in ("question", "topic"):
                        questions.append((q_num, q_text))
            except Exception:
                pass
    seen = set()
    unique_qs = []
    for q_num, q_text in questions:
        if q_num not in seen:
            seen.add(q_num)
            unique_qs.append((q_num, q_text))
    return unique_qs


def detect_multi_question(message: str, sid: str, email: str) -> list[tuple[str, str]]:
    # 1. Parse pasted questions from message if they look like multiple Q1, Q2, etc.
    all_matches = list(re.finditer(r'\b(Q\d+)\b', message))
    q_matches = []
    for m in all_matches:
        start_idx = m.start()
        preceding = message[:start_idx]
        is_at_start = (start_idx == 0) or preceding.strip() == ""
        is_after_newline = False
        if not is_at_start:
            if re.search(r'[\r\n]\s*$', preceding):
                is_after_newline = True
        if is_at_start or is_after_newline:
            q_matches.append(m)

    if len(q_matches) >= 3:
        questions = []
        for idx, match in enumerate(q_matches):
            q_num = match.group(1)
            start = match.end()
            end = q_matches[idx+1].start() if idx + 1 < len(q_matches) else len(message)
            q_text = message[start:end].strip()
            q_text = re.sub(r'^[:.\-\s\u2013\u2014]+', '', q_text)
            if len(q_text) > 10:
                questions.append((q_num, q_text))
        
        seen_q = set()
        deduped_qs = []
        for qn, qt in questions:
            qn_norm = qn.strip().upper()
            if qn_norm not in seen_q:
                seen_q.add(qn_norm)
                deduped_qs.append((qn, qt))
        
        if len(deduped_qs) >= 3:
            return deduped_qs

    # 2. Check if the message is a trigger to answer Q0 questions
    is_trigger = any(x in message.lower() for x in ["solve all", "answer all", "q0", "comprehensive report", "advanced report"])
    if is_trigger and sid and email:
        rows = db("SELECT fname, file_hash FROM m WHERE sid=? AND role='user' AND fname IS NOT NULL ORDER BY id DESC LIMIT 1", (sid,))
        fname = rows[0][0] if rows else None
        fhash = rows[0][1] if rows else None
        if not fname:
            rows = db("SELECT filename, file_hash FROM user_files WHERE user_email=? ORDER BY created_at DESC LIMIT 1", (email,))
            fname = rows[0][0] if rows else None
            fhash = rows[0][1] if rows else None
        if fname:
            for f in fname.split(';'):
                if fhash:
                    row = db("SELECT extracted_text FROM user_files WHERE user_email=? AND file_hash=?", (email, fhash))
                else:
                    row = db("SELECT extracted_text FROM user_files WHERE user_email=? AND filename=?", (email, f))
                if row and row[0][0]:
                    qs = parse_q0_questions(row[0][0])
                    if qs:
                        return qs
    return []


@app.get(
    "/api/chat/stream",
    description="Stream chat responses from the SCAL AI Assistant.",
    responses={
        429: {"description": "Rate limit exceeded"},
        500: {"description": "Internal server error"}
    }
)
@_limiter.limit("10/minute")
async def chat_stream(
    request: Request,
    message:       str,
    background_tasks: BackgroundTasks,
    session_id:    Optional[str]   = None,
    user_email:    Optional[str]   = None,
    auth:          bool            = Depends(verify_user_or_admin),
):
    message = sanitize_prompt(message)

    if session_id in ("null", "undefined", "", None):
        sid = str(uuid.uuid4())
    else:
        sid = session_id

    email = user_email.lower().strip() if user_email else None

    # Synchronously insert session row before starting producer/threads
    if _PG_AVAILABLE:
        await async_db(
            "INSERT INTO sessions (sid, title, user_email, updated_at) VALUES (?, 'New Study', ?, ?) "
            "ON CONFLICT (sid) DO UPDATE SET updated_at = EXCLUDED.updated_at",
            (sid, email, time.time())
        )
    else:
        await async_db(
            "INSERT OR IGNORE INTO sessions (sid, title, user_email, created_at, updated_at) VALUES (?, 'New Study', ?, ?, ?)",
            (sid, email, time.time(), time.time())
        )
        await async_db("UPDATE sessions SET updated_at=? WHERE sid=?", (time.time(), sid))

    

    # â"€â"€ SSE PRODUCER WITH HEARTBEAT â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€

    async def _producer():

        q = asyncio.Queue(maxsize=2000)  # bounded: prevents unbounded growth on client disconnect

        loop = asyncio.get_running_loop()

        in_thinking = False
        text_buffer = ""

        def get_matching_suffix_len(text: str, tag: str) -> int:
            for i in range(min(len(text), len(tag)), 0, -1):
                if tag.startswith(text[-i:].lower()):
                    return i
            return 0

        def _enqueue(item):
            """Put an item on the queue only if the consumer is still alive."""
            if q.qsize() < 1900:
                loop.call_soon_threadsafe(q.put_nowait, item)
            # else: consumer (_producer) has gone away; silently drop to stop memory growth



        # Run the synchronous generator in a separate thread to keep the event loop free.

        def _sync_worker():

            try:

                # 1. Search Knowledge Base

                kb_ctx = KnowledgeBase.search(message, sid=sid, email=email)

                file_history_ctx = get_user_file_history_context(email, sid=sid)
                summary_ctx = get_session_summary_context(sid)
                prefix = "\n\n".join(filter(None, [file_history_ctx, summary_ctx]))
                if prefix:
                    kb_ctx = prefix + "\n\n" + kb_ctx if kb_ctx else prefix

                # 2. Log User Message

                db("INSERT INTO m (sid,role,text,ts,user_email) VALUES (?,?,?,?,?)", 

                   (sid, "user", message, time.time(), email))

                

                # 3. Session Management

                if _PG_AVAILABLE:

                    db("INSERT INTO sessions (sid, title, user_email, updated_at) VALUES (?, 'New Study', ?, ?) "

                       "ON CONFLICT (sid) DO UPDATE SET updated_at = EXCLUDED.updated_at",

                       (sid, email, time.time()))

                else:

                    db("INSERT OR IGNORE INTO sessions (sid, title, user_email, created_at, updated_at) VALUES (?, 'New Study', ?, ?, ?)",

                       (sid, email, time.time(), time.time()))

                    db("UPDATE sessions SET updated_at=? WHERE sid=?", (time.time(), sid))

                auto_rename_session_if_new(sid, email, filename=None, message=message)



                # 4. Context Preparation
                hist_rows = db("SELECT role, text FROM m WHERE sid=? ORDER BY id DESC LIMIT 2", (sid,))
                history   = list(reversed([{"role": r, "text": t} for r, t in hist_rows]))

                # 5. Gemini Chat Logic
                _tls.current_session_id = sid
                qs = detect_multi_question(message, sid, email)
                if qs:
                    _logger.info(f"[SSE Worker] Detected multi-question streaming ({len(qs)} sub-questions).")
                    
                    rows_answered = db("SELECT text FROM m WHERE sid=? AND role='model'", (sid,))
                    answered_qnums = set()
                    for r in rows_answered:
                        txt = r[0] or ""
                        m_check = re.findall(r'<!-- CHECKPOINT (Q\d+) -->', txt)
                        for q_val in m_check:
                            answered_qnums.add(q_val)
                    
                    combined_answers = []
                    for q_num, q_text in qs:
                        if q_num in answered_qnums:
                            chk_row = db("SELECT text FROM m WHERE sid=? AND role='model' AND text LIKE ?", (sid, f"%<!-- CHECKPOINT {q_num} -->%"))
                            if chk_row and chk_row[0][0]:
                                ans_text = chk_row[0][0]
                                combined_answers.append(ans_text)
                                _enqueue({"type": "token", "text": f"\n\n### {q_num} (Cached Analysis):\n\n"})
                                for chunk_part in [ans_text[i:i+100] for i in range(0, len(ans_text), 100)]:
                                    _enqueue({"type": "token", "text": chunk_part})
                                    import time as _time
                                    _time.sleep(0.01)
                                _logger.info(f"[SSE Worker] Streamed cached {q_num}")
                                continue
                        
                        try:
                            _logger.info(f"[SSE Worker] Generating {q_num}...")
                            sub_msg = f"Solve and provide a detailed analysis for this specific question:\n\n**{q_num}: {q_text}**"
                            
                            hist_rows = db("SELECT role, text FROM m WHERE sid=? AND user_email=? ORDER BY id DESC LIMIT 4", (sid, email))
                            sub_history = list(reversed([{"role": r, "text": t} for r, t in hist_rows]))
                            
                            _enqueue({"type": "token", "text": f"\n\n### {q_num}: {q_text}\n\n"})
                            
                            max_attempts = 5
                            attempt_delay = 1.0
                            success_gen = False
                            sub_reply = ""
                            for attempt in range(max_attempts):
                                try:
                                    sub_reply = ""
                                    for chunk in assistant.chat(sub_history, sub_msg, kb_context=kb_ctx, stream=True, sid=sid, email=email):
                                        if q.qsize() >= 1900:
                                            break
                                        if isinstance(chunk, dict):
                                            if chunk.get("type") == "token":
                                                sub_reply += chunk.get("text", "")
                                            _enqueue(chunk)
                                        else:
                                            sub_reply += str(chunk)
                                            _enqueue({"type": "token", "text": str(chunk)})
                                    success_gen = True
                                    break
                                except Exception as ex:
                                    err_l = str(ex).lower()
                                    is_trans = any(x in err_l for x in ["503", "429", "resource_exhausted", "unavailable", "timeout", "overload", "rate_limit"])
                                    if is_trans and attempt < max_attempts - 1:
                                        _logger.warning(f"[SSE Worker] API error on {q_num} attempt {attempt+1}: {ex}. Retrying in {attempt_delay}s...")
                                        import time as _time
                                        _time.sleep(attempt_delay)
                                        attempt_delay *= 2.0
                                    else:
                                        raise ex
                            
                            if not success_gen or not sub_reply:
                                raise ValueError("Empty response generated or max attempts reached.")
                                
                            sub_reply = strip_thinking_blocks(sub_reply)
                            sub_reply = strip_placeholder_artifacts(sub_reply)
                            sub_reply = process_provenance_tokens(sub_reply, sid)
                            filenames = get_filenames_from_cache(sid)
                            sub_reply = compress_traceability_ledger(sub_reply, filenames)
                            sub_reply = _extract_and_log_corrections(sid, email, sub_reply)
                            
                            sub_reply += f"\n<!-- CHECKPOINT {q_num} -->"
                            
                            db("INSERT INTO m (sid,role,text,ts,user_email) VALUES (?,?,?,?,?)",
                               (sid, "model", sub_reply, time.time(), email))
                            
                            combined_answers.append(sub_reply)
                            _logger.info(f"[SSE Worker] Successfully completed and checkpointed {q_num}.")
                        except Exception as q_ex:
                            _logger.error(f"[SSE Worker] Permanent failure generating {q_num}: {q_ex}")
                            err_msg = f"\n\n[ERROR] {q_num} failed: Unable to generate a response. This may be due to an API timeout, context window limit, or temporary model overload. Please retry with a shorter query, or try asking the model to process a specific sheet.\n<!-- CHECKPOINT {q_num} -->"
                            _enqueue({"type": "token", "text": err_msg})
                            db("INSERT INTO m (sid,role,text,ts,user_email) VALUES (?,?,?,?,?)",
                               (sid, "model", err_msg, time.time(), email))
                            combined_answers.append(err_msg)
                
                else:
                    full_reply = ""
                    max_attempts = 5
                    attempt_delay = 1.0
                    for attempt in range(max_attempts):
                        try:
                            full_reply = ""
                            for chunk in assistant.chat(history, message, kb_context=kb_ctx, stream=True, sid=sid, email=email):
                                if q.qsize() >= 1900:
                                    _logger.warning("[SSE Worker] Queue near-full — client likely disconnected, aborting.")
                                    break
                                if isinstance(chunk, dict):
                                    if chunk.get("type") == "token":
                                        full_reply += chunk.get("text", "")
                                    _enqueue(chunk)
                                else:
                                    full_reply += str(chunk)
                                    _enqueue({"type": "token", "text": str(chunk)})
                            break
                        except Exception as ex:
                            err_l = str(ex).lower()
                            is_trans = any(x in err_l for x in ["503", "429", "resource_exhausted", "unavailable", "timeout", "overload", "rate_limit"])
                            if is_trans and attempt < max_attempts - 1:
                                _logger.warning(f"[SSE Worker] API error on attempt {attempt+1}: {ex}. Retrying in {attempt_delay}s...")
                                import time as _time
                                _time.sleep(attempt_delay)
                                attempt_delay *= 2.0
                            else:
                                raise ex

                    # 6. Finalization — strip LLM artifacts before persistence
                    if full_reply:
                        full_reply = strip_thinking_blocks(full_reply)
                        full_reply = strip_placeholder_artifacts(full_reply)
                        full_reply = process_provenance_tokens(full_reply, sid)
                        filenames = get_filenames_from_cache(sid)
                        full_reply = compress_traceability_ledger(full_reply, filenames)
                        full_reply = _extract_and_log_corrections(sid, email, full_reply)
                        db("INSERT INTO m (sid,role,text,ts,user_email) VALUES (?,?,?,?,?)",
                           (sid, "model", full_reply, time.time(), email))

                if getattr(_tls, 'pending_kb', None):
                    _enqueue({"type": "__PENDING_KB__", "data": list(_tls.pending_kb)})

                _enqueue({"type": "done"})

            except Exception as e:

                _logger.error(f"[SSE Worker] Error: {e}")

                _enqueue({"type": "error", "msg": str(e)})

                _enqueue({"type": "done"})



        # Start background processing — outer try/except catches task-creation
        # failures, the handshake yield, and any exception that escapes the
        # per-iteration try/except inside the while loop.
        try:
            task = asyncio.create_task(asyncio.to_thread(_sync_worker))
            task.add_done_callback(
                lambda t: _logger.error(f"[SSE Worker] Unhandled task exception: {t.exception()}")
                if not t.cancelled() and t.exception() else None
            )

            # Initial handshake
            yield f"data: {_json.dumps({'type': 'session', 'session_id': sid})}\n\n"

            while True:

                try:

                    # Wait for data with 15s timeout to send heartbeat

                    chunk = await asyncio.wait_for(q.get(), timeout=15.0)



                    if chunk["type"] == "done":

                        yield f"data: {_json.dumps(chunk)}\n\n"

                        break

                    elif chunk["type"] == "__PENDING_KB__":

                        background_tasks.add_task(KnowledgeBase.ingest_transactional, "SCAL Upload", chunk["data"], sid=sid, email=email)

                        continue

                    if chunk["type"] == "token":
                        token_text = chunk.get("text", "")
                        text_buffer += token_text
                        
                        output_text = ""
                        while True:
                            if in_thinking:
                                idx = text_buffer.lower().find("</thinking>")
                                if idx != -1:
                                    in_thinking = False
                                    text_buffer = text_buffer[idx + len("</thinking>"):]
                                else:
                                    keep_len = get_matching_suffix_len(text_buffer, "</thinking>")
                                    if keep_len > 0:
                                        text_buffer = text_buffer[-keep_len:]
                                    else:
                                        text_buffer = ""
                                    break
                            else:
                                idx = text_buffer.lower().find("<thinking>")
                                if idx != -1:
                                    output_text += text_buffer[:idx]
                                    in_thinking = True
                                    text_buffer = text_buffer[idx + len("<thinking>"):]
                                else:
                                    keep_len = get_matching_suffix_len(text_buffer, "<thinking>")
                                    if keep_len > 0:
                                        output_text += text_buffer[:-keep_len]
                                        text_buffer = text_buffer[-keep_len:]
                                    else:
                                        output_text += text_buffer
                                        text_buffer = ""
                                    break
                        
                        if output_text:
                            # 1. Suppress Placeholder Leaks
                            output_text = strip_placeholder_artifacts(output_text)
                            
                            # 2. Clean Up Citation Clutter
                            filenames = get_filenames_from_cache(sid)
                            output_text = clean_citation_clutter(output_text, filenames)
                            
                            yield f"data: {_json.dumps({'type': 'token', 'text': output_text})}\n\n"
                        continue

                    yield f"data: {_json.dumps(chunk)}\n\n"

                except asyncio.TimeoutError:

                    # Keep-alive heartbeat (SSE comment)

                    yield ": ping\n\n"

                except Exception as e:

                    _logger.error(f"[SSE Producer] Error: {e}")

                    yield f"data: {_json.dumps({'type': 'error', 'msg': 'Internal Stream Error'})}\n\n"

                    break

        except Exception as e:
            _logger.error(f"[SSE Producer] Fatal outer error: {e}")
            try:
                yield f"data: {_json.dumps({'type': 'error', 'msg': f'Stream error: {str(e)[:200]}'})}\n\n"
                yield f"data: {_json.dumps({'type': 'done'})}\n\n"
            except Exception:
                pass
    return StreamingResponse(
        _producer(),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"}
    )



def sanitize_filename(filename: str) -> str:
    """Sanitizes filename to protect against path traversal (CWE-22) and invalid characters."""
    if not filename:
        return "unnamed_file"
    # Take only the base name (no directory components)
    basename = Path(filename).name
    basename = basename.replace('\\', '/').split('/')[-1] # enforce base name regardless of OS separator
    # Remove directory traversal sequences (e.g. "../" or "..\\")
    basename = re.sub(r'\.\.+', '.', basename)
    # Filter characters: allow letters, numbers, spaces, dots, dashes, underscores
    path_obj = Path(basename)
    name, ext = path_obj.stem, path_obj.suffix
    name = re.sub(r'[^\w\s\.-]', '', name)
    ext = re.sub(r'[^\w\.-]', '', ext)
    sanitized = f"{name}{ext}".strip()
    return sanitized if sanitized else "unnamed_file"


def verify_file_signature(file_bytes: bytes, filename: str) -> bool:
    """
    Verifies that the magic bytes of file_bytes match the declared filename extension.
    This prevents extension-spoofing attacks (e.g., renaming a .exe to .xlsx).
    """
    if not file_bytes:
        return True
    
    ext = filename.split(".")[-1].lower() if "." in filename else ""
    if not ext:
        return False
        
    # Enforce magic bytes for PDF
    if ext == "pdf":
        return file_bytes.startswith(b"%PDF")
        
    # Enforce magic bytes for ZIP/DOCX/PPTX/XLSX/XLSM
    if ext in ["docx", "pptx", "xlsx", "xlsm", "zip"]:
        return file_bytes.startswith(b"PK\x03\x04")
        
    # Enforce magic bytes for legacy OLE formats XLS/DOC
    if ext in ["xls", "doc"]:
        return file_bytes.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")
        
    # For text, csv, md, markdown, json, xml, check that they do not contain binary header markers or null bytes
    if ext in ["txt", "csv", "md", "markdown", "json", "xml"]:
        # Ensure no executable headers
        if file_bytes.startswith(b"MZ") or file_bytes.startswith(b"\x7fELF"):
            return False
        # Ensure no null bytes in the first 1024 bytes (indicates binary data)
        sample = file_bytes[:1024]
        if b"\x00" in sample:
            return False
        return True
        
    return False



@app.post(
    "/api/chat",
    description="Handle POST request chat messages with optional file attachments.",
    responses={
        429: {"description": "Rate limit exceeded"},
        500: {"description": "Internal server error"}
    }
)
@_limiter.limit("10/minute")
async def handle(
    request: Request,
    background_tasks: BackgroundTasks,

    message:       Optional[str]    = Form(None),

    session_id:    Optional[str]    = Form(None),

    user_email:    Optional[str]    = Form(None),

    engineer_name: Optional[str]    = Form(None),

    files:         list[UploadFile] = File(default=[]),

    auth:          bool             = Depends(verify_user_or_admin),

):
    try:
        _tls.breadcrumbs = []
        _add_breadcrumb("Chat request received")
        message = sanitize_prompt(message) if message else message

        sid      = session_id or str(uuid.uuid4())

        # Destructive memory eviction protocol on new study / file upload
        is_new_session = session_id in ("null", "undefined", "", None) or not session_id
        valid_files = [f for f in files if getattr(f, "filename", "")]
        if is_new_session or valid_files:
            evict_session(sid)

        email    = user_email.lower().strip() if user_email else None

        # Synchronously insert session row at the start of request
        if _PG_AVAILABLE:
            await async_db(
                "INSERT INTO sessions (sid, title, user_email, updated_at) VALUES (?, 'New Study', ?, ?) "
                "ON CONFLICT (sid) DO UPDATE SET updated_at = EXCLUDED.updated_at",
                (sid, email, time.time())
            )
        else:
            await async_db(
                "INSERT OR IGNORE INTO sessions (sid, title, user_email, created_at, updated_at) VALUES (?, 'New Study', ?, ?, ?)",
                (sid, email, time.time(), time.time())
            )
            await async_db("UPDATE sessions SET updated_at=? WHERE sid=?", (time.time(), sid))

        engineer = (engineer_name or "PRC Engineering Staff").strip()



        valid_files = [f for f in files if getattr(f, "filename", "")]

        for f in valid_files:
            f.filename = sanitize_filename(f.filename)
            sig_bytes = await f.read(1024)
            await f.seek(0)
            if not verify_file_signature(sig_bytes, f.filename):
                raise HTTPException(status_code=400, detail=f"File signature mismatch or invalid format for extension: {f.filename}")

        f_parts = []

        _tls.last_file_name = valid_files[0].filename if valid_files else None

        _tls.current_session_id = sid

        for file in valid_files:
            max_bytes = settings.SCAL_MAX_UPLOAD_MB * 1024 * 1024
            chunk_size = 64 * 1024
            content = bytearray()
            while True:
                chunk = await file.read(chunk_size)
                if not chunk:
                    break
                content.extend(chunk)
                if len(content) > max_bytes:
                    raise HTTPException(status_code=413, detail=f"File '{file.filename}' exceeds the {settings.SCAL_MAX_UPLOAD_MB} MB limit.")
            b = bytes(content)

            if b:

                f_parts.append((b, file.content_type, file.filename))

                # Persist a file record for cross-session history (key_params filled later by background task)
                try:
                    fhash = hashlib.sha256(b).hexdigest()
                    fext  = Path(file.filename.lower()).suffix.lstrip(".")
                    ftype = fext.upper() or "UNKNOWN"
                    if _PG_AVAILABLE:
                        db(
                            "INSERT INTO user_files (user_email, filename, file_hash, data_type, created_at) "
                            "VALUES (?,?,?,?,?) ON CONFLICT (user_email, file_hash) DO NOTHING",
                            (email, file.filename, fhash, ftype, time.time()),
                        )
                    else:
                        db(
                            "INSERT OR IGNORE INTO user_files (user_email, filename, file_hash, data_type, created_at) "
                            "VALUES (?,?,?,?,?)",
                            (email, file.filename, fhash, ftype, time.time()),
                        )
                except Exception as _ufe:
                    _logger.warning(f"[UserFiles] Could not record file for {email}: {_ufe}")

        if f_parts:
            # Synchronously extract file text and populate database/cache
            # so that detect_multi_question can see the extracted text and questions.
            import tempfile
            for data_bytes, mime, fname in f_parts:
                safe_mime = (mime or "application/octet-stream").lower()
                ext = Path(fname).suffix.lower() if fname else ".xlsx"
                is_spreadsheet = any(x in safe_mime for x in ["spreadsheet", "excel", "csv", "sheet"]) or ext in [".xlsx", ".xls", ".csv"]
                is_docx = "wordprocessingml" in safe_mime or ext in [".docx", ".doc"]
                
                if is_spreadsheet or is_docx:
                    if not ext:
                        ext = ".xlsx" if is_spreadsheet else ".docx"
                    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tf:
                        tf.write(data_bytes)
                        tmp_path = tf.name
                    try:
                        mandatory_ground_truth = extract_absolute_file_truth([(tmp_path, fname)])
                        _fhash_store = hashlib.sha256(data_bytes).hexdigest()
                        if sid:
                            with SESSION_DATA_CACHE_LOCK:
                                SESSION_DATA_CACHE[_fhash_store] = {
                                    "ground_truth": mandatory_ground_truth,
                                    "timestamp": time.time()
                                }
                            populate_cache_from_ground_truth(_fhash_store, mandatory_ground_truth)
                            if is_spreadsheet:
                                cache_excel_data_vectors(_fhash_store, tmp_path)
                        
                        fr_data = read_file(tmp_path, target_identifier=None)
                        fr_text, _ = to_prompt_string(fr_data)
                        if email and fr_text:
                            _fhash_store = hashlib.sha256(data_bytes).hexdigest()
                            db(
                                "INSERT INTO user_files"
                                " (user_email, filename, file_hash, extracted_text, data_type, created_at)"
                                " VALUES (?,?,?,?,?,?)"
                                " ON CONFLICT(user_email, file_hash)"
                                " DO UPDATE SET extracted_text=EXCLUDED.extracted_text,"
                                " filename=EXCLUDED.filename",
                                (email, fname, _fhash_store, fr_text, "SCAL", time.time()),
                            )
                    except Exception as ex:
                        _logger.error(f"[Bootstrap Extract] Failed to extract text for {fname}: {ex}")
                    finally:
                        try: Path(tmp_path).unlink(missing_ok=True)
                        except: pass
                elif "pdf" in safe_mime:
                    try:
                        text = _sfh_extract_pdf(data_bytes)
                        if text.strip() and email:
                            _fhash_store = hashlib.sha256(data_bytes).hexdigest()
                            db(
                                "INSERT INTO user_files"
                                " (user_email, filename, file_hash, extracted_text, data_type, created_at)"
                                " VALUES (?,?,?,?,?,?)"
                                " ON CONFLICT(user_email, file_hash)"
                                " DO UPDATE SET extracted_text=EXCLUDED.extracted_text,"
                                " filename=EXCLUDED.filename",
                                (email, fname, _fhash_store, text, "PDF", time.time()),
                            )
                    except Exception as e:
                        _logger.warning(f"[PDF Bootstrap Extract] {fname}: {e}")
                elif "text/plain" in safe_mime or ext in (".txt", ".text"):
                    try:
                        content = data_bytes.decode("utf-8", errors="ignore")
                        if content.strip() and email:
                            _fhash_store = hashlib.sha256(data_bytes).hexdigest()
                            db(
                                "INSERT INTO user_files"
                                " (user_email, filename, file_hash, extracted_text, data_type, created_at)"
                                " VALUES (?,?,?,?,?,?)"
                                " ON CONFLICT(user_email, file_hash)"
                                " DO UPDATE SET extracted_text=EXCLUDED.extracted_text,"
                                " filename=EXCLUDED.filename",
                                (email, fname, _fhash_store, content, "TXT", time.time()),
                            )
                    except Exception as e:
                        _logger.warning(f"[TXT Bootstrap Extract] {fname}: {e}")



        kb_ctx = await KnowledgeBase.search_async(message, sid=sid, email=email)

        file_history_ctx = get_user_file_history_context(email, sid=sid)
        summary_ctx = get_session_summary_context(sid)
        prefix = "\n\n".join(filter(None, [file_history_ctx, summary_ctx]))
        if prefix:
            kb_ctx = prefix + "\n\n" + kb_ctx if kb_ctx else prefix

        # Save user message WITH filename if applicable

        # Store all uploaded filenames (semicolon-delimited) so the session-file
        # fallback in generate_document_json() can recover extracted_text for every
        # file, not just the first one in a multi-file upload.
        fname = ";".join(f.filename for f in valid_files) if valid_files else None

        primary_fhash = None
        if valid_files and f_parts:
            primary_fhash = hashlib.sha256(f_parts[0][0]).hexdigest()

        await async_db("INSERT INTO m (sid,role,text,ts,user_email,fname,file_hash) VALUES (?,?,?,?,?,?,?)",
           (sid, "user", message, time.time(), email, fname, primary_fhash))



        # Upsert into sessions table

        if _PG_AVAILABLE:

            await async_db("INSERT INTO sessions (sid, title, user_email, updated_at) VALUES (?, 'New Study', ?, ?) "

               "ON CONFLICT (sid) DO UPDATE SET updated_at = EXCLUDED.updated_at",

               (sid, email, time.time()))

        else:

            await async_db("INSERT OR IGNORE INTO sessions (sid, title, user_email, created_at, updated_at) VALUES (?, 'New Study', ?, ?, ?)",

               (sid, email, time.time(), time.time()))

            await async_db("UPDATE sessions SET updated_at=? WHERE sid=?", (time.time(), sid))

        f_name_rename = valid_files[0].filename if valid_files else None
        auto_rename_session_if_new(sid, email, filename=f_name_rename, message=message)



        # â"€â"€ Security Guard: Verify session ownership before any data access â"€â"€â"€â"€â"€â"€â"€

        _verify_session_owner(sid, email)



        # â"€â"€ Document generation path (Gemini JSON  ->  HvielDocEngine file) â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€

        file_type = hviel_engine._detect_type(message) if hviel_engine else None

        if file_type:

            try:

                hist_rows = db("SELECT role, text FROM m WHERE sid=? AND user_email=? ORDER BY id DESC LIMIT 10", (sid, email))

                history   = list(reversed([{"role": r, "text": t} for r, t in hist_rows]))



                # Run blocking Gemini call + file I/O in a thread so we don't block the event loop

                def _build_file():

                    raw_json = assistant.generate_document_json(

                        file_type, message, history, kb_ctx, engineer, f_parts,
                        sid=sid, email=email,

                    )

                    return hviel_engine.build_from_json(raw_json, file_type, engineer=engineer)



                filepath = await asyncio.get_running_loop().run_in_executor(None, _build_file)

                basename = Path(filepath).name

                dl_url   = f"/api/download/{basename}"



                type_labels = {"docx": "Word Document", "xlsx": "Excel Spreadsheet",

                               "pptx": "PowerPoint Presentation", "pdf": "PDF Report"}

                reply = (

                    f"### PRC {type_labels.get(file_type, file_type.upper())} Ready\n\n"

                    f"Your professional export has been compiled from the current session analysis. "

                    f"Click **Download** to retrieve the file."

                )

                await async_db("INSERT INTO m (sid,role,text,url,ts,user_email,fname) VALUES (?,?,?,?,?,?,?)",

                   (sid, "model", reply, dl_url, time.time(), email, basename))



                return {

                    "status":          "success",

                    "session_id":      sid,

                    "reply":           reply,

                    "is_report_ready": True,

                    "download_url":    dl_url,

                    "doc_type":        "excel" if file_type == "xlsx" else file_type,

                }

            except Exception as e:

                _logger.error(f"[DocGen] {file_type} generation failed: {e}")

                err_lower = str(e).lower()
                is_overload = any(x in err_lower for x in [
                    "503", "unavailable", "resource_exhausted", "overload", "retries"
                ])
                reply = (
                    " Gemini is currently unavailable after 5 attempts. "
                    "Please try again in a few minutes or contact PRC support."
                    if is_overload else
                    f" Document generation failed: {str(e)[:200]}. "
                    "Please retry or contact PRC support."
                )

                await async_db("INSERT INTO m (sid,role,text,ts,user_email) VALUES (?,?,?,?,?)",

                   (sid, "model", reply, time.time(), email))

                return {"status": "error", "session_id": sid, "reply": reply,
                        "is_doc_error": True}



        # â"€â"€ Standard chat path (Gemini with file analysis) â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€

        hist_rows = db("SELECT role, text FROM m WHERE sid=? AND user_email=? ORDER BY id DESC LIMIT 10", (sid, email))

        history   = list(reversed([{"role": r, "text": t} for r, t in hist_rows]))



        # Run blocking Gemini call in a thread so we don't block the FastAPI event loop.
        # _post_kb captures _tls.pending_kb from INSIDE the executor thread where chat() runs,
        # because _tls is thread-local and invisible across thread boundaries.
        _post_kb: list = []

        def _chat_capture():
            import time as _time
            qs = detect_multi_question(message, sid, email)
            if qs:
                _logger.info(f"[CheckpointLoop] Detected multi-question query ({len(qs)} sub-questions).")
                
                rows_answered = db("SELECT text FROM m WHERE sid=? AND role='model'", (sid,))
                answered_qnums = set()
                for r in rows_answered:
                    txt = r[0] or ""
                    m_check = re.findall(r'<!-- CHECKPOINT (Q\d+) -->', txt)
                    for q_val in m_check:
                        answered_qnums.add(q_val)
                
                _logger.info(f"[CheckpointLoop] Found already completed: {answered_qnums}")
                
                combined_answers = []
                for q_num, q_text in qs:
                    if q_num in answered_qnums:
                        chk_row = db("SELECT text FROM m WHERE sid=? AND role='model' AND text LIKE ?", (sid, f"%<!-- CHECKPOINT {q_num} -->%"))
                        if chk_row and chk_row[0][0]:
                            ans_text = chk_row[0][0]
                            combined_answers.append(ans_text)
                            _logger.info(f"[CheckpointLoop] Loaded {q_num} from DB.")
                            continue
                    
                    try:
                        _logger.info(f"[CheckpointLoop] Generating {q_num}...")
                        sub_msg = f"Solve and provide a detailed analysis for this specific question:\n\n**{q_num}: {q_text}**"
                        
                        hist_rows = db("SELECT role, text FROM m WHERE sid=? AND user_email=? ORDER BY id DESC LIMIT 4", (sid, email))
                        sub_history = list(reversed([{"role": r, "text": t} for r, t in hist_rows]))
                        
                        max_attempts = 5
                        attempt_delay = 1.0
                        resp_obj = None
                        for attempt in range(max_attempts):
                            try:
                                resp_obj = assistant.chat(sub_history, sub_msg, kb_ctx, f_parts, sid=sid, email=email)
                                break
                            except Exception as ex:
                                err_l = str(ex).lower()
                                is_trans = any(x in err_l for x in ["503", "429", "resource_exhausted", "unavailable", "timeout", "overload", "rate_limit"])
                                if is_trans and attempt < max_attempts - 1:
                                    _logger.warning(f"[CheckpointLoop] API error on {q_num} attempt {attempt+1}: {ex}. Retrying in {attempt_delay}s...")
                                    _time.sleep(attempt_delay)
                                    attempt_delay *= 2.0
                                else:
                                    raise ex
                        
                        ans_text = resp_obj if isinstance(resp_obj, str) else str(resp_obj) if resp_obj is not None else ""
                        if not ans_text:
                            raise ValueError("Empty response generated or max attempts reached.")
                            
                        ans_text = strip_thinking_blocks(ans_text)
                        ans_text = strip_placeholder_artifacts(ans_text)
                        ans_text = process_provenance_tokens(ans_text, sid)
                        filenames = get_filenames_from_cache(sid)
                        ans_text = clean_citation_clutter(ans_text, filenames)
                        ans_text = compress_traceability_ledger(ans_text, filenames)
                        ans_text = _extract_and_log_corrections(sid, email, ans_text)
                        
                        ans_text += f"\n<!-- CHECKPOINT {q_num} -->"
                        
                        db("INSERT INTO m (sid,role,text,ts,user_email) VALUES (?,?,?,?,?)",
                           (sid, "model", ans_text, _time.time(), email))
                        
                        combined_answers.append(ans_text)
                        _logger.info(f"[CheckpointLoop] Successfully completed and checkpointed {q_num}.")
                    except Exception as q_ex:
                        _logger.error(f"[CheckpointLoop] Permanent failure generating {q_num}: {q_ex}")
                        err_msg = f"\n\n[ERROR] {q_num} failed: Unable to generate a response. This may be due to an API timeout, context window limit, or temporary model overload. Please retry with a shorter query, or try asking the model to process a specific sheet.\n<!-- CHECKPOINT {q_num} -->"
                        db("INSERT INTO m (sid,role,text,ts,user_email) VALUES (?,?,?,?,?)",
                           (sid, "model", err_msg, _time.time(), email))
                        combined_answers.append(err_msg)
                
                full_report = "\n\n---\n\n".join(combined_answers)
                _post_kb.extend(getattr(_tls, 'pending_kb', []))
                return {"is_multi": True, "reply": full_report}
            
            else:
                max_attempts = 5
                attempt_delay = 1.0
                resp_obj = None
                for attempt in range(max_attempts):
                    try:
                        resp_obj = assistant.chat(history, message, kb_ctx, f_parts, sid=sid, email=email)
                        break
                    except Exception as ex:
                        err_l = str(ex).lower()
                        is_trans = any(x in err_l for x in ["503", "429", "resource_exhausted", "unavailable", "timeout", "overload", "rate_limit"])
                        if is_trans and attempt < max_attempts - 1:
                            _logger.warning(f"[Chat] API error on attempt {attempt+1}: {ex}. Retrying in {attempt_delay}s...")
                            _time.sleep(attempt_delay)
                            attempt_delay *= 2.0
                        else:
                            raise ex
                
                _post_kb.extend(getattr(_tls, 'pending_kb', []))
                return resp_obj

        try:
            resp = await anyio.to_thread.run_sync(_chat_capture)
        except Exception as e:
            _logger.error(f"[Chat] Gemini/file processing error: {e}")
            reply = f"Processing error: {str(e)[:300]}. Please retry or contact PRC support."
            await async_db("INSERT INTO m (sid,role,text,ts,user_email) VALUES (?,?,?,?,?)",
               (sid, "model", reply, time.time(), email))
            return {"status": "error", "session_id": sid, "reply": reply}

        is_multi = isinstance(resp, dict) and resp.get("is_multi")
        if is_multi:
            resp_text = resp["reply"]
        else:
            resp_text = resp if isinstance(resp, str) else str(resp) if resp is not None else ""
            resp_text = strip_thinking_blocks(resp_text)
            resp_text = strip_placeholder_artifacts(resp_text)
            resp_text = process_provenance_tokens(resp_text, sid)
            filenames = get_filenames_from_cache(sid)
            resp_text = clean_citation_clutter(resp_text, filenames)
            resp_text = compress_traceability_ledger(resp_text, filenames)
            resp_text = _extract_and_log_corrections(sid, email, resp_text)
            if not resp_text.strip():
                # Empty after post-processing almost always means the model's mandated
                # <thinking> block consumed the output-token budget on a very large file,
                # leaving no visible answer. Surface a clear, actionable message instead of
                # returning a silent blank reply.
                resp_text = (
                    "⚠️ I read the file, but the answer came back empty — this usually happens "
                    "when an uploaded document is very large and the response gets cut off. "
                    "Please ask about a specific part (e.g. \"summarize the conclusions\" or "
                    "\"show me the porosity table\") and I'll pull it directly."
                )
            await async_db("INSERT INTO m (sid,role,text,ts,user_email) VALUES (?,?,?,?,?)",
               (sid, "model", resp_text, time.time(), email))



        if _post_kb:

            background_tasks.add_task(KnowledgeBase.ingest_transactional, "SCAL Upload", _post_kb, sid=sid, email=email)

        if valid_files and resp_text:
            background_tasks.add_task(_save_summary_background, sid, email, resp_text, valid_files[0].filename)
            try:
                import tempfile
                ext = Path(valid_files[0].filename or "").suffix.lower() or ".xlsx"
                with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tf:
                    tf.write(f_parts[0][0])
                    tmp_filepath = tf.name
                try:
                    result = grade_ai_response(tmp_filepath, resp_text)
                    _logger.info("[AutoGrader] Console Report")
                    _logger.info(result["report"])
                finally:
                    try: Path(tmp_filepath).unlink(missing_ok=True)
                    except Exception: pass
            except Exception as ge:
                _logger.warning(f"[AutoGrader] Failed to execute console grade: {ge}")

        return {"status": "success", "session_id": sid, "reply": resp_text}
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        diag = {
            "timestamp": time.time(),
            "error": str(e),
            "traceback": tb,
            "breadcrumbs": getattr(_tls, "breadcrumbs", [])
        }
        try:
            Path("outputs").mkdir(parents=True, exist_ok=True)
            with open("outputs/crash_diagnostics.json", "w", encoding="utf-8") as diag_f:
                import json as _json_diag
                _json_diag.dump(diag, diag_f, indent=2)
        except Exception as save_err:
            _logger.warning(f"[AppCrash] Failed to save crash diagnostics: {save_err}")
        _logger.error(f"[AppCrash] Diagnostic report saved: {e}")
        raise HTTPException(status_code=500, detail=f"Request crashed. Diagnostics stored. Error: {str(e)}")





# ── LIBRARY INGEST ROUTE ──────────────────────────────────────────────────────

@app.post("/api/library/ingest")
async def library_ingest(
    file: UploadFile = File(...),
    uploader_email: str = Form(""),
    x_ingest_secret: str = Header("", alias="X-Ingest-Secret"),
):
    if not KB_INGEST_SECRET or not hmac.compare_digest(x_ingest_secret.strip(), KB_INGEST_SECRET):
        raise HTTPException(status_code=403, detail="Invalid ingest secret")
    file.filename = sanitize_filename(file.filename)
    max_bytes = settings.SCAL_MAX_UPLOAD_MB * 1024 * 1024
    chunk_size = 64 * 1024
    content = bytearray()
    while True:
        chunk = await file.read(chunk_size)
        if not chunk:
            break
        content.extend(chunk)
        if len(content) > max_bytes:
            raise HTTPException(status_code=413, detail=f"File '{file.filename}' exceeds the {settings.SCAL_MAX_UPLOAD_MB} MB limit.")
    file_bytes = bytes(content)
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Empty file")
    if not verify_file_signature(file_bytes, file.filename):
        raise HTTPException(status_code=400, detail=f"File signature mismatch or invalid format for extension: {file.filename}")

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None, _ingest_library_file, file_bytes, file.filename, uploader_email.lower().strip()
    )

    if result.get("duplicate"):
        raise HTTPException(
            status_code=409,
            detail={"error": "This document is already in the library", "existing_file": result["existing_file"]},
        )
    if result.get("error"):
        raise HTTPException(status_code=500, detail=result["error"])

    return result


@app.get("/api/library/docs")
async def library_list(x_ingest_secret: str = Header("", alias="X-Ingest-Secret")):
    if not KB_INGEST_SECRET or not hmac.compare_digest(x_ingest_secret.strip(), KB_INGEST_SECRET):
        raise HTTPException(status_code=403, detail="Invalid ingest secret")
    rows = db("SELECT id, filename, data_type, uploaded_by, created_at FROM library_docs ORDER BY created_at DESC")
    return {"docs": [{"id": r[0], "filename": r[1], "data_type": r[2], "uploaded_by": r[3], "created_at": r[4]} for r in rows]}


# ── KNOWLEDGE BASE & SKILLS REGISTRY ENDPOINTS ───────────────────────────────

def _parse_skill_md(file_path: str) -> dict:
    """Parse YAML frontmatter from SKILL.md and return dict of metadata."""
    metadata = {"name": "", "description": ""}
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read().strip()
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                yaml_block = parts[1]
                lines = yaml_block.splitlines()
                idx = 0
                while idx < len(lines):
                    line = lines[idx]
                    stripped = line.strip()
                    if not stripped or stripped.startswith("#"):
                        idx += 1
                        continue
                    if ":" in line:
                        k, v = line.split(":", 1)
                        k = k.strip().lower()
                        v = v.strip()
                        if k == "name":
                            metadata["name"] = v.strip('"\'')
                        elif k in ("description", "desc"):
                            if v in (">", "|"):
                                desc_lines = []
                                idx += 1
                                while idx < len(lines):
                                    next_line = lines[idx]
                                    if next_line.strip() and not next_line.startswith(" ") and not next_line.startswith("\t"):
                                        idx -= 1
                                        break
                                    desc_lines.append(next_line.strip())
                                    idx += 1
                                metadata["description"] = " ".join(desc_lines)
                            else:
                                metadata["description"] = v.strip('"\'')
                    idx += 1
    except Exception as e:
        _logger.warning(f"[Skills] Failed to parse skill metadata from {file_path}: {e}")
    return metadata


@app.get("/api/kb/status")
async def kb_status():
    try:
        # Aggregate global chunks from library_docs and library_chunks
        global_rows = await async_db(
            "SELECT filename, (SELECT COUNT(*) FROM library_chunks WHERE doc_id = library_docs.id) FROM library_docs"
        )
        
        # Aggregate transactional chunks from kb
        trans_rows = await async_db(
            "SELECT source, COUNT(*) FROM kb GROUP BY source"
        )
        
        books_map = {}
        for filename, count in global_rows:
            if filename:
                clean_name = filename.replace("File: ", "").strip()
                books_map[clean_name] = books_map.get(clean_name, 0) + (count or 0)

        for source, count in trans_rows:
            if source:
                clean_name = source.replace("File: ", "").strip()
                books_map[clean_name] = books_map.get(clean_name, 0) + (count or 0)
                
        books = [{"name": k, "chunks": v} for k, v in books_map.items()]
        total_chunks = sum(books_map.values())
        
        return {"books": books, "total_chunks": total_chunks}
    except Exception as e:
        _logger.error(f"[KB Status] Failed to get status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/kb/ingest")
async def kb_ingest(
    file: UploadFile = File(...),
    password: str = Form(...),
):
    is_valid = (KB_INGEST_SECRET and hmac.compare_digest(password.strip(), KB_INGEST_SECRET)) or \
               (ADMIN_PIN and hmac.compare_digest(password.strip(), ADMIN_PIN))
    if not is_valid:
        raise HTTPException(status_code=403, detail="Invalid admin pin")
    file.filename = sanitize_filename(file.filename)
    max_bytes = settings.SCAL_MAX_UPLOAD_MB * 1024 * 1024
    chunk_size = 64 * 1024
    content = bytearray()
    while True:
        chunk = await file.read(chunk_size)
        if not chunk:
            break
        content.extend(chunk)
        if len(content) > max_bytes:
            raise HTTPException(status_code=413, detail=f"File '{file.filename}' exceeds the {settings.SCAL_MAX_UPLOAD_MB} MB limit.")
    file_bytes = bytes(content)
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Empty file")
    if not verify_file_signature(file_bytes, file.filename):
        raise HTTPException(status_code=400, detail=f"File signature mismatch or invalid format for extension: {file.filename}")

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None, _ingest_library_file, file_bytes, file.filename, "admin"
    )

    if result.get("duplicate"):
        raise HTTPException(
            status_code=409,
            detail=f"This document is already in the library as '{result['existing_file']}'",
        )
    if result.get("error"):
        raise HTTPException(status_code=500, detail=result["error"])

    # Calculate words count
    words_count = 0
    try:
        text = _extract_text_for_library(file_bytes, file.filename)
        words_count = len(text.split())
    except Exception:
        words_count = result.get("chunks", 0) * 150

    return {
        "status": "success",
        "book": file.filename,
        "chunks_stored": result.get("chunks", 0),
        "words": words_count
    }


@app.post("/api/kb/delete")
async def kb_delete(
    filename: str = Form(...),
    password: str = Form(...),
):
    is_valid = False
    if KB_INGEST_SECRET and hmac.compare_digest(password.strip(), KB_INGEST_SECRET):
        is_valid = True
    elif ADMIN_PIN and hmac.compare_digest(password.strip(), ADMIN_PIN):
        is_valid = True
    if not is_valid:
        raise HTTPException(status_code=403, detail="Invalid admin pin")

    clean_name = filename.replace("File: ", "").strip()

    try:
        await async_db(
            "DELETE FROM library_chunks WHERE doc_id IN (SELECT id FROM library_docs WHERE filename = ? OR filename = ?)",
            (clean_name, f"File: {clean_name}"),
        )
        await async_db(
            "DELETE FROM library_docs WHERE filename = ? OR filename = ?",
            (clean_name, f"File: {clean_name}"),
        )
        await async_db(
            "DELETE FROM kb WHERE source = ? OR source = ?",
            (clean_name, f"File: {clean_name}"),
        )
        _LibraryEmbCache.invalidate()
        return {"status": "success", "message": f"Successfully deleted {clean_name}"}
    except Exception as e:
        _logger.error(f"[KB Delete] Failed to delete {clean_name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/skills/list")
async def list_skills_endpoint():
    skills_dir = Path(__file__).parent / "hermes_skills_library"
    skills_list = []
    
    if not skills_dir.exists():
        return {"skills": []}
        
    try:
        for cat_dir in skills_dir.iterdir():
            if cat_dir.is_dir():
                for skill_dir in cat_dir.iterdir():
                    if skill_dir.is_dir():
                        skill_md_path = skill_dir / "SKILL.md"
                        if skill_md_path.exists():
                            meta = _parse_skill_md(str(skill_md_path))
                            name = meta.get("name") or skill_dir.name.replace("-", " ").title()
                            desc = meta.get("description") or ""
                            desc = re.sub(r'\s+', ' ', desc).strip()
                            skills_list.append({
                                "category": cat_dir.name.replace("-", " ").title(),
                                "name": name,
                                "desc": desc
                            })
    except Exception as e:
        _logger.error(f"[Skills List] Failed to list skills: {e}")
        raise HTTPException(status_code=500, detail=str(e))
        
    return {"skills": skills_list}


# Resolved once at startup; chat-generated docs are written to the shared PRC vault
# by HvielDocEngine(output_dir=str(PRC_VAULT)) and served from here.

import pathlib as _pathlib

_DOWNLOAD_ROOT = PRC_VAULT.resolve()



@app.get("/api/download/{filename:path}")
async def dl(
    filename: str,
    user_email: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
    token: Optional[str] = Query(None),
):
    verify_user_or_admin(authorization=authorization, token=token, email_query=user_email)
    target = (_DOWNLOAD_ROOT / _pathlib.Path(filename).name).resolve()

    if not str(target).startswith(str(_DOWNLOAD_ROOT)):

        raise HTTPException(status_code=403, detail="Access denied")

    if not target.is_file():

        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(str(target))





# ── PRODUCTION ASYNC PIPELINE REMEDIATION ────────────────────────────────────
TASKS_DB: dict[str, dict] = {}
SESSION_DATA_CACHE_LOCK: threading.Lock = threading.Lock()
SESSION_DATA_CACHE: dict[str, dict] = {}


def get_session_active_hash(session_id: str) -> Optional[str]:
    if not session_id:
        return None
    try:
        rows = db("SELECT file_hash FROM m WHERE sid=? AND file_hash IS NOT NULL ORDER BY id DESC LIMIT 1", (session_id,))
        if rows and rows[0][0]:
            return rows[0][0]
    except Exception as e:
        _logger.warning(f"Failed to query active file hash for session {session_id}: {e}")
    return None


def resolve_cache_key(key: str) -> str:
    if not key:
        return ""
    if len(key) == 64 and all(c in "0123456789abcdefABCDEF" for c in key):
        return key
    active_hash = get_session_active_hash(key)
    return active_hash or key


def evict_session(session_id: str) -> None:
    """Single source of truth for destructive session eviction.

    Clears the session's cache dict in place (dropping ground truth, labeled
    values, and flat vectors), resets it to a clean empty shell, and forces an
    explicit garbage-collection pass so no ghost memory survives across sessions.
    Wired into chat init, file upload, and the explicit /api/clear-session route
    so eviction logic can never drift between call sites again.
    """
    if not session_id:
        return
    import gc
    with SESSION_DATA_CACHE_LOCK:
        if session_id not in SESSION_DATA_CACHE:
            SESSION_DATA_CACHE[session_id] = {}
        SESSION_DATA_CACHE[session_id].clear()
        SESSION_DATA_CACHE[session_id]["labeled_values"] = {}
    try:
        db("DELETE FROM session_cache WHERE sid=?", (session_id,))
    except Exception as _ev_err:
        _logger.warning(f"[SessionCacheDB] Delete failed during eviction: {_ev_err}")
    gc.collect()


def save_session_cache_to_db(sid: str) -> None:
    """Serializes and persists the in-memory session cache dictionary to the database
    to support multi-process, multi-worker, or stateless container deployments (like Render).
    """
    if not sid:
        return
    sid = resolve_cache_key(sid)
    try:
        with SESSION_DATA_CACHE_LOCK:
            cache_data = SESSION_DATA_CACHE.get(sid)
            if not cache_data:
                return
            gt = cache_data.get("ground_truth", "")
            lv = _json.dumps(cache_data.get("labeled_values", {}))
            fv = _json.dumps(cache_data.get("flat_vectors", {}))
            re_data = _json.dumps(cache_data.get("raw_excel_data", {}))
            
        db(
            "INSERT INTO session_cache (sid, ground_truth, labeled_values, flat_vectors, raw_excel_data, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (sid) DO UPDATE SET "
            "  ground_truth = EXCLUDED.ground_truth, "
            "  labeled_values = EXCLUDED.labeled_values, "
            "  flat_vectors = EXCLUDED.flat_vectors, "
            "  raw_excel_data = EXCLUDED.raw_excel_data, "
            "  updated_at = EXCLUDED.updated_at",
            (sid, gt, lv, fv, re_data, time.time())
        )
    except Exception as e:
        _logger.warning(f"[SessionCacheDB] Save failed for {sid}: {e}")


def load_session_cache_from_db(sid: str) -> None:
    """Restores the session cache from the SQLite database if it's missing from the in-memory dict.
    Ensures that any Gunicorn/Uvicorn worker process has access to the uploaded file's extracted data.
    """
    if not sid:
        return
    sid = resolve_cache_key(sid)
    try:
        with SESSION_DATA_CACHE_LOCK:
            if sid in SESSION_DATA_CACHE and SESSION_DATA_CACHE[sid] and SESSION_DATA_CACHE[sid].get("ground_truth"):
                return
                
        rows = db("SELECT ground_truth, labeled_values, flat_vectors, raw_excel_data FROM session_cache WHERE sid=?", (sid,))
        if not rows:
            return
            
        gt, lv_json, fv_json, re_json = rows[0]
        try:
            lv = _json.loads(lv_json) if lv_json else {}
        except Exception:
            lv = {}
        try:
            fv = _json.loads(fv_json) if fv_json else {}
        except Exception:
            fv = {}
        try:
            re_data = _json.loads(re_json) if re_json else {}
        except Exception:
            re_data = {}
            
        with SESSION_DATA_CACHE_LOCK:
            if sid not in SESSION_DATA_CACHE:
                SESSION_DATA_CACHE[sid] = {}
            SESSION_DATA_CACHE[sid]["ground_truth"] = gt
            SESSION_DATA_CACHE[sid]["labeled_values"] = lv
            SESSION_DATA_CACHE[sid]["flat_vectors"] = fv
            SESSION_DATA_CACHE[sid]["raw_excel_data"] = re_data
            SESSION_DATA_CACHE[sid]["timestamp"] = time.time()
            
        _logger.info(f"[SessionCacheDB] Restored cache for {sid} from DB: {len(gt)} chars ground truth, {len(lv)} labeled values.")
    except Exception as e:
        _logger.warning(f"[SessionCacheDB] Load failed for {sid}: {e}")


def auto_rename_session_if_new(sid: str, email: str, filename: str = None, message: str = None):
    """Automatically assigns a descriptive title to a session if its current title is 'New Study'."""
    try:
        if not sid:
            return
        const_email = email.lower().strip() if email else ""
        
        _logger.info(f"[AutoRename] Invoked for session {sid} (filename={filename}, message_len={len(message) if message else 0})")
        
        # Check current title
        rows = db("SELECT title FROM sessions WHERE sid=?", (sid,))
        current_title = "New Study"
        exists = False
        if rows:
            current_title = rows[0][0]
            exists = True
            
        _logger.info(f"[AutoRename] Session exists={exists}, current title: '{current_title}'")
            
        if current_title != "New Study" and current_title.strip() != "":
            _logger.info(f"[AutoRename] Title already customized, bypassing auto-rename.")
            return
            
        # Determine new title
        new_title = None
        if filename:
            # Strip extension and clean
            base = filename.rsplit(".", 1)[0]
            new_title = base.replace("_", " ").replace("-", " ").strip()
            # Truncate if extremely long
            if len(new_title) > 40:
                new_title = new_title[:37] + "..."
        elif message:
            # Clean message
            clean_msg = message.strip()
            # Get first 5 words
            words = clean_msg.split()
            if words:
                new_title = " ".join(words[:5])
                if len(clean_msg) > len(new_title):
                    new_title += "..."
                    
        if new_title:
            if exists:
                db("UPDATE sessions SET title = ?, updated_at = ? WHERE sid = ?", (new_title, time.time(), sid))
                _logger.info(f"[AutoRename] Successfully updated title in DB to: '{new_title}'")
            else:
                _logger.info(f"[AutoRename] Session row does not exist yet, pre-creating with title: '{new_title}'")
                if _PG_AVAILABLE:
                    db("INSERT INTO sessions (sid, title, user_email, updated_at) VALUES (?, ?, ?, ?) "
                       "ON CONFLICT (sid) DO UPDATE SET title = EXCLUDED.title, updated_at = EXCLUDED.updated_at",
                       (sid, new_title, const_email, time.time()))
                else:
                    db("INSERT OR REPLACE INTO sessions (sid, title, user_email, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                       (sid, new_title, const_email, time.time(), time.time()))
                _logger.info(f"[AutoRename] Inserted session row with title '{new_title}' successfully.")
        else:
            _logger.info(f"[AutoRename] No descriptive title could be determined.")
    except Exception as e:
        _logger.warning(f"[AutoRename] Failed to auto-rename session {sid}: {e}")


@app.post("/api/clear-session")
async def clear_session(session_id: str = Form(...)):
    """Explicit destructive eviction of a session's cached SCAL data.
    Enforces absolute isolation: clears the dict and forces gc.collect()."""
    import re as _re
    if not _re.match(r"^(report-)?[a-zA-Z0-9\-]+$", session_id):
        raise HTTPException(status_code=400, detail="Invalid session_id format")
    evict_session(session_id)
    return {"status": "cleared", "session_id": session_id}


@app.post("/api/clear-user-files")
async def clear_user_files(email: str = Form(...)):
    """Wipes all user uploaded files from user_files to prevent cross-session AI confusion."""
    try:
        email_clean = email.lower().strip()
        db("DELETE FROM user_files WHERE user_email=?", (email_clean,))
        _logger.info(f"[ClearUserFiles] Successfully cleared all user files for {email_clean}")
        return {"status": "ok", "message": "Successfully cleared all user files."}
    except Exception as e:
        _logger.error(f"[ClearUserFiles] Failed to clear user files for {email}: {e}")
        raise HTTPException(status_code=500, detail=str(e))



def purge_all_historical_assets():
    """Wipes historical assets (T1-31, xlsx, csv) and clears memory using Path to guarantee absolute state isolation."""
    from pathlib import Path
    import gc
    import tempfile
    import shutil
    _logger.info("[STARTUP-PURGE] Executing synchronous background sterilization...")

    # 1. Hard wipe uploads directory
    upload_dir = Path("./uploads")
    try:
        if upload_dir.exists():
            shutil.rmtree(str(upload_dir), ignore_errors=True)
        upload_dir.mkdir(parents=True, exist_ok=True)
        _logger.info(f"[STARTUP-PURGE] Cleaned and recreated upload directory: {upload_dir}")
    except Exception as e:
        _logger.warning(f"[STARTUP-PURGE] Failed to wipe upload directory {upload_dir}: {e}")

    # 2. Hard wipe tmp / temp directory of any files containing 'T1-31' or ending with '.xlsx', '.csv'
    try:
        temp_dir = Path(tempfile.gettempdir())
        purged_count = 0
        if temp_dir.exists():
            for item in temp_dir.iterdir():
                try:
                    if item.is_file():
                        file_low = item.name.lower()
                        is_t131 = 't1-31' in file_low
                        is_excel_or_csv = file_low.endswith('.xlsx') or file_low.endswith('.xls') or file_low.endswith('.csv')
                        if is_t131 or is_excel_or_csv:
                            item.unlink(missing_ok=True)
                            purged_count += 1
                except Exception:
                    pass
        _logger.info(f"[STARTUP-PURGE] Purged {purged_count} orphaned spreadsheet/T1-31 files from {temp_dir}")
    except Exception as e:
        _logger.warning(f"[STARTUP-PURGE] Failed to purge temp files: {e}")

    # 3. Clear global cache dictionaries completely
    with SESSION_DATA_CACHE_LOCK:
        SESSION_DATA_CACHE.clear()
    gc.collect()
    _logger.info("[STARTUP-PURGE] Global SESSION_DATA_CACHE wiped and garbage collector invoked.")


def start_session_ttl_monitor():
    """Starts a background thread to evict idle session caches after 15 minutes of inactivity."""
    import threading
    import time
    import gc
    from pathlib import Path
    import tempfile

    def monitor_loop():
        while True:
            try:
                time.sleep(60)  # Check every minute
                now = time.time()
                evicted_sessions = []
                
                with SESSION_DATA_CACHE_LOCK:
                    for sid, cache_item in list(SESSION_DATA_CACHE.items()):
                        last_act = cache_item.get("last_activity") or cache_item.get("timestamp") or now
                        if now - last_act > 15 * 60:  # 15 minutes idle
                            evicted_sessions.append(sid)
                            SESSION_DATA_CACHE.pop(sid, None)
                
                if evicted_sessions:
                    _logger.info(f"[TTL-MONITOR] Evicting {len(evicted_sessions)} idle sessions: {evicted_sessions}")
                    temp_dir = Path(tempfile.gettempdir())
                    upload_dir = Path("./uploads")
                    purged_files = 0
                    
                    for sid in evicted_sessions:
                        for base_dir in [temp_dir, upload_dir]:
                            if not base_dir.exists():
                                continue
                            try:
                                for item in base_dir.iterdir():
                                    if item.is_file() and sid in item.name:
                                        try:
                                            item.unlink(missing_ok=True)
                                            purged_files += 1
                                        except Exception:
                                            pass
                            except Exception:
                                pass
                    
                    gc.collect()
                    if purged_files:
                        _logger.info(f"[TTL-MONITOR] Cleaned up {purged_files} files from disk associated with evicted sessions.")
            except Exception as monitor_err:
                _logger.warning(f"[TTL-MONITOR] Error in background thread: {monitor_err}")
                
    t = threading.Thread(target=monitor_loop, daemon=True)
    t.start()


def get_filenames_from_cache(sid: Optional[str]) -> list[str]:
    """Helper to extract original filenames from the ground truth in the session cache."""
    if not sid:
        return []
    fhash = resolve_cache_key(sid)
    with SESSION_DATA_CACHE_LOCK:
        cached = SESSION_DATA_CACHE.get(fhash)
        if not cached:
            return []
        gt = cached.get("ground_truth", "")
    if not gt:
        return []
    # Find all occurrences of ═══ FILE: <filename> ═══
    filenames = [f.strip() for f in re.findall(r'═══ FILE:\s*([^═]+)\s*═══', gt)]
    return filenames

_REPORT_LATENCY_LIST: list[float] = []
_REPORT_LATENCY_LOCK: threading.Lock = threading.Lock()
# Upload cap for large lab reports. Default 75 MB on the sovereign on-prem box;
# override via SCAL_MAX_UPLOAD_MB. Streaming guard still enforces the limit.
_MAX_UPLOAD_BYTES = int(os.getenv("SCAL_MAX_UPLOAD_MB", "75")) * 1024 * 1024

import tempfile

async def process_large_file_stream(file: UploadFile, temp_file_path: str, max_bytes: int):
    """
    Streams incoming files in 512KB chunks directly to disk.
    If the file size exceeds the max_bytes limit, raises HTTP 413.
    """
    total_bytes = 0
    with open(temp_file_path, "wb") as buffer:
        while True:
            chunk = await file.read(512 * 1024)  # 512KB chunks
            if not chunk:
                break
            total_bytes += len(chunk)
            if total_bytes > max_bytes:
                raise HTTPException(
                    status_code=413,
                    detail=f"File size exceeds maximum allowed {max_bytes // (1024 * 1024)}MB limit."
                )
            buffer.write(chunk)


def sync_document_generation_task(
    session_id: str,
    temp_file_path: str,
    filename: str,
    email: str = None,
    message: str = None
):
    try:
        # Progress 0-10%
        TASKS_DB[session_id].update({"status": "processing", "progress": 5})
        ext = Path(filename.lower()).suffix
        is_docx = ext == ".docx"
        is_spreadsheet = ext in [".xlsx", ".xls", ".csv"]
        
        # Read the file
        fr_data = read_file(temp_file_path, target_identifier=None)
        fr_text, _ = to_prompt_string(fr_data)
        if not fr_text:
            raise ValueError("Empty or unreadable file content.")
            
        TASKS_DB[session_id].update({"progress": 15})
        
        # Phase 0b: Generate GROUND TRUTH structural inventory from the actual file
        phase0b_inventory = None
        phase0b_inventory_text = ""
        mandatory_ground_truth = ""
        # Calculate file content hash
        with open(temp_file_path, "rb") as f:
            fhash = hashlib.sha256(f.read()).hexdigest()

        if is_spreadsheet or is_docx:
            try:
                # Deterministic pre-parser: raw pd.ExcelFile, zero SCALFileHandler dependency
                mandatory_ground_truth = extract_absolute_file_truth(
                    [(temp_file_path, filename)]
                )
                if session_id:
                    with SESSION_DATA_CACHE_LOCK:
                        SESSION_DATA_CACHE[fhash] = {
                            "ground_truth": mandatory_ground_truth,
                            "timestamp": time.time()
                        }
                    populate_cache_from_ground_truth(fhash, mandatory_ground_truth)
                    if is_spreadsheet:
                        cache_excel_data_vectors(fhash, temp_file_path)
                _logger.info(f"[Phase 0b BG] Deterministic MANDATORY_GROUND_TRUTH_INVENTORY generated for {filename} with hash {fhash}")
            except Exception as mgt_err:
                _logger.warning(f"[Phase 0b BG] extract_absolute_file_truth failed for {filename}: {mgt_err}")
        
        if is_spreadsheet:
            try:
                _handler = SCALFileHandler(temp_file_path)
                _handler.read()
                phase0b_inventory = _handler.generate_structural_inventory()
                phase0b_inventory_text = _handler.generate_structural_inventory_text()
                _logger.info(f"[Phase 0b BG] Generated structural inventory for {filename}: "
                             f"{len(phase0b_inventory.get('sheets_found', []))} sheets")
                if phase0b_inventory.get("multi_well_alert"):
                    _logger.warning(f"[Phase 0b BG] MULTI-WELL ALERT in {filename}: "
                                    f"{phase0b_inventory['multi_well_alert']}")
            except Exception as inv_err:
                _logger.warning(f"[Phase 0b BG] Inventory generation failed for {filename}: {inv_err}")
        
        # Progress 10-30%: Extract structure from Gemini with HA client
        extraction_prompt_path = str(Path(__file__).parent / "prompts" / "extraction_system_prompt.md")
        with open(extraction_prompt_path, "r", encoding="utf-8") as f:
            system_instruction = f.read()
        
        # Inject MANDATORY_GROUND_TRUTH_INVENTORY into the SYSTEM INSTRUCTION
        if mandatory_ground_truth:
            system_instruction = (
                f"{system_instruction}\n\n"
                f"## MANDATORY_GROUND_TRUTH_INVENTORY\n\n"
                f"You are provided with a MANDATORY_GROUND_TRUTH_INVENTORY extracted "
                f"programmatically by the Python server from the actual binary file. "
                f"This inventory is ABSOLUTE TRUTH and supersedes ANY text analysis you perform.\n\n"
                f"RULES:\n"
                f"1. If your analysis references a sheet name that does NOT exist in this inventory, "
                f"you MUST immediately output STRUCTURAL_HALT and fail.\n"
                f"2. If your analysis references a column label that does NOT exist in this inventory, "
                f"you MUST immediately output STRUCTURAL_HALT and fail.\n"
                f"3. You are FORBIDDEN from recycling numbers, columns, or sheet names from previous "
                f"chat turns or cached context. Only use what is in the current file.\n"
                f"4. For permeability fields (KL, Ka, Air_Permeability_md, Klinkenberg_Permeability_md), "
                f"the source column header MUST contain 'mD', 'Permeability', 'KL', or 'Ka'. "
                f"You MUST REJECT columns with '(cc)', 'Volume', 'Cum.vol', or 'Cumulative' for permeability extraction.\n"
                f"5. If a cell explicitly states 'Swi = <value>' or 'Sor = <value>', bind that value "
                f"directly to explicit_Swi or explicit_Sor. These override ALL derived calculations.\n\n"
                f"{mandatory_ground_truth}\n"
            )
            
        msg = message or "Analyze petrophysical data from uploaded file."
        full_markdown_variable = (
            f"--- START OF FULL DOCUMENT MARKDOWN ---\n{fr_text}\n--- END OF FULL DOCUMENT MARKDOWN ---\n\n"
        )
        
        # Also inject Phase 0b inventory text into user prompt for cross-validation
        if phase0b_inventory_text:
            full_markdown_variable += (
                f"--- GROUND TRUTH: PHASE 0b STRUCTURAL INVENTORY (generated by Python parser) ---\n"
                f"{phase0b_inventory_text}\n"
                f"--- END GROUND TRUTH ---\n"
                f"IMPORTANT: The inventory above was generated by the Python file parser from the actual binary file. "
                f"Your Phase 0b output MUST match this exactly. If your output diverges, you are hallucinating.\n\n"
            )
        
        full_markdown_variable += (
            f"USER REQUEST: {msg}\n\n"
            f"CRITICAL: Only extract the specific table(s) or data requested by the user above. "
            f"If the user specifies a specific table (e.g., 'Table 2.1.1'), only extract the rows for that table. "
            f"Do not extract rows from other tables or other core plug sweeps.\n\n"
            f"MANDATORY PHASE 0b — PROOF OF READ:\n"
            f"Before ANY extraction, you MUST output a structural file inventory proving you have inspected the actual file.\n"
            f"You are FORBIDDEN from relying on remembered file structures or historical context.\n\n"
            f"MANDATORY PROTOCOLS FOR EXTRACTION:\n"
            f"0b. You must execute and return Phase 0b (PROOF OF READ: filename, sheets_found, per-sheet header/shape/first 2 rows inventory, multi_well_alert).\n"
            f"1. You must execute and return Protocol 1 (FILE-OPEN PROOF: sheet names and raw column headers target sheet inventory).\n"
            f"2. You must execute and return Protocol 2 (HEADER & UNIT DOUBLE-CHECK: print literal column headers/units for every extracted data value).\n"
            f"3. You must execute and return Protocol 3 (LABELED-VALUE ABSOLUTE PRIORITY: extract explicitly stated Swi/Sor laboratory values and list them under overridden_endpoints).\n"
            f"Your JSON output MUST match the structured schema format: a single object containing 'phase_0b_proof_of_read', 'protocol_1_file_open_proof', 'protocol_2_header_unit_double_check', 'protocol_3_labeled_value_absolute_priority', and the final rows array as 'extracted_data'.\n\n"
            f"STRUCTURAL HALT: If you cite a sheet name or column header NOT in your own Phase 0b inventory, HALT and output a STRUCTURAL_HALT error."
        )
        
        contents = [
            genai_types.Content(
                role="user",
                parts=[genai_types.Part.from_text(text=full_markdown_variable)]
            )
        ]
        config = genai_types.GenerateContentConfig(
            system_instruction=system_instruction,
            response_mime_type="application/json"
        )
        
        TASKS_DB[session_id].update({"progress": 20})

        # _call_gemini_with_retry is NVIDIA NIM-backed and ignores client/model —
        # no Gemini client (or key) is needed on this path anymore.
        client = None
        if not NVIDIA_KEY_POOL:
            raise RuntimeError(
                "No NVIDIA API keys configured (set NVIDIA_API_KEY / NVIDIA_API_KEY1..N); "
                "document generation requires NVIDIA NIM access."
            )
        response = _call_gemini_with_retry(
            client=client,
            model="gemini-2.5-flash",  # ignored: NVIDIA shim always uses NVIDIA_MODEL
            contents=contents,
            config=config,
            max_retries=3,
            base_delay=2,
            max_tokens=8192,
        )

        response_text = response.text or ""
        clean_text = response_text.strip()
        if clean_text.startswith("```"):
            lines = clean_text.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines[-1].startswith("```"):
                lines = lines[:-1]
            clean_text = "\n".join(lines).strip()
        
        # Strip <thinking> blocks from response
        clean_text = strip_thinking_blocks(clean_text)
            
        def salvage_and_clean_json(text_to_parse: str) -> list:
            parsed = None
            try:
                parsed = _json.loads(text_to_parse)
            except Exception:
                clean_t = text_to_parse.strip()
                last_brace = clean_t.rfind('}')
                if last_brace != -1:
                    if clean_t.startswith("{"):
                        for suffix in ["}", "]}", "]} }", "] }"]:
                            try:
                                parsed = _json.loads(clean_t[:last_brace + 1] + suffix)
                                break
                            except Exception:
                                continue
                    else:
                        try:
                            parsed = _json.loads(clean_t[:last_brace + 1] + ']')
                        except Exception:
                            pass

            if parsed is None:
                # Lenient fallback: tolerate ```json fences / prose around the JSON
                # (gpt-oss-120b habit) before declaring a parse failure.
                try:
                    parsed = parse_llm_json(text_to_parse)
                except LLMJsonParseError:
                    parsed = None

            if parsed is None:
                raise LLMJsonParseError("Could not parse or salvage valid JSON from LLM extraction response.")
            
            # Phase 0b: Check for STRUCTURAL_HALT from LLM
            if isinstance(parsed, dict) and "STRUCTURAL_HALT" in parsed:
                halt_msg = parsed["STRUCTURAL_HALT"]
                _logger.error(f"[Phase 0b] STRUCTURAL HALT in background task: {halt_msg}")
                raise ValueError(f"STRUCTURAL_HALT: LLM detected hallucinated reference — {halt_msg}")
            
            # Phase 0b: Python-side structural validation against ground truth
            if isinstance(parsed, dict) and phase0b_inventory:
                violations = validate_extraction_against_inventory(parsed, phase0b_inventory)
                if violations:
                    for v in violations:
                        _logger.error(f"[Phase 0b BG] {v}")
                    raise ValueError(
                        f"STRUCTURAL_HALT: Python-side validation caught {len(violations)} "
                        f"hallucinated reference(s): {'; '.join(violations[:3])}"
                    )
            
            # Permeability column binding validation
            if isinstance(parsed, dict):
                perm_violations = validate_permeability_column_binding(parsed)
                if perm_violations:
                    for pv in perm_violations:
                        _logger.error(f"[Phase 0b BG] {pv}")
                    raise ValueError(
                        f"PERM_COLUMN_HALT: {len(perm_violations)} permeability "
                        f"data-shuffling error(s): {'; '.join(perm_violations[:3])}"
                    )
                
            if isinstance(parsed, dict) and "extracted_data" in parsed:
                _logger.info("[Pipeline] Successfully parsed Phase 0b + mandatory protocols and structured data in background task.")
                overrides = parsed.get("protocol_3_labeled_value_absolute_priority", {}).get("overridden_endpoints", {})
                data_list = parsed.get("extracted_data", [])
                if isinstance(data_list, list) and isinstance(overrides, dict):
                    for row in data_list:
                        if isinstance(row, dict):
                            for ok, ov in overrides.items():
                                if ov is not None:
                                    if ok.lower() == "swi":
                                        row["explicit_Swi"] = float(ov)
                                    elif ok.lower() == "sor":
                                        row["explicit_Sor"] = float(ov)
                return data_list
            return parsed if isinstance(parsed, list) else []

        try:
            extracted_json = salvage_and_clean_json(clean_text)
        except LLMJsonParseError as je:
            # Pure parse failure (NOT a structural/permeability halt): re-prompt
            # ONCE with a corrective instruction, then parse again.
            _logger.warning(f"[BgTask] Extraction JSON unparseable ({je}); one corrective retry...")
            retry_contents = list(contents) + [
                genai_types.Content(role="model", parts=[genai_types.Part.from_text(text=response_text[:4000])]),
                genai_types.Content(role="user", parts=[genai_types.Part.from_text(text=CORRECTIVE_JSON_PROMPT)]),
            ]
            try:
                response = _call_gemini_with_retry(
                    client=None,
                    model="gemini-2.5-flash",  # ignored: NVIDIA shim always uses NVIDIA_MODEL
                    contents=retry_contents,
                    config=config,
                    max_retries=2,
                    base_delay=2,
                    max_tokens=8192,
                )
                response_text = response.text or ""
                clean_text = response_text.strip()
                if clean_text.startswith("```"):
                    _lines = clean_text.splitlines()
                    if _lines and _lines[0].startswith("```"):
                        _lines = _lines[1:]
                    if _lines and _lines[-1].startswith("```"):
                        _lines = _lines[:-1]
                    clean_text = "\n".join(_lines).strip()
                clean_text = strip_thinking_blocks(clean_text)
                extracted_json = salvage_and_clean_json(clean_text)
            except Exception as je2:
                raise ValueError(f"Failed to parse LLM extraction output as JSON (after one corrective retry): {je2}")
        except Exception as je:
            raise ValueError(f"Failed to parse LLM extraction output as JSON: {je}")
                
        def merge_and_deduplicate_sweeps(samples):
            if not samples or not isinstance(samples, list): return []
            samples = [s for s in samples if isinstance(s, dict)]
            if not samples: return []
            sweeps = []
            current_sweep = []
            last_p = None
            for s in samples:
                p = s.get("Pressure_psi")
                if p is not None:
                    if last_p is not None and p <= last_p:
                        if current_sweep: sweeps.append(current_sweep)
                        current_sweep = []
                current_sweep.append(s)
                last_p = p
            if current_sweep: sweeps.append(current_sweep)
            
            merged_sweeps = []
            for sweep in sweeps:
                matched = False
                for ms in merged_sweeps:
                    if len(sweep) == len(ms):
                        match = True
                        for i in range(len(sweep)):
                            if sweep[i].get("Pressure_psi") != ms[i].get("Pressure_psi") or sweep[i].get("Porosity_percent") != ms[i].get("Porosity_percent"):
                                match = False
                                break
                        if match:
                            for i in range(len(sweep)):
                                for k, v in sweep[i].items():
                                    if v is not None and ms[i].get(k) is None:
                                        ms[i][k] = v
                            matched = True
                            break
                if not matched:
                    merged_sweeps.append(sweep)
                    
            result = []
            for ms in merged_sweeps:
                result.extend(ms)
            return result

        extracted_json = merge_and_deduplicate_sweeps(extracted_json)
        TASKS_DB[session_id].update({"progress": 30})
        
        # Progress 30-70%: Physics Audit, DB Inserts, isolated geomech md, dashboard and plots
        validation_result = data_validator.validate_scal_data(extracted_json)
        physics_score = 100
        physics_status = "PASS"
        violations = []
        
        if validation_result.get("status") == "error":
            physics_status = "FAIL"
            physics_score = max(0, 100 - 15 * len(validation_result.get("errors", [])))
            violations = validation_result.get("errors", [])
            
        detected_type = detect_test_type(extracted_json)
        _log_physics_audit(
            sid=session_id,
            data_type=detected_type,
            audit_res={"score": physics_score, "violations": violations},
            file_name=filename
        )
        
        TASKS_DB[session_id].update({"progress": 40})
        
        from prc_physics import calculate_compressibility_sweep, enrich_json_with_brooks_corey
        try:
            extracted_json = calculate_compressibility_sweep(extracted_json)
            extracted_json = enrich_json_with_brooks_corey(extracted_json)
        except Exception as pe:
            _logger.warning(f"Error during deterministic physics calculation in bg: {pe}")
            
        TASKS_DB[session_id].update({"progress": 45})
        
        # Insert consecutively in DB
        db("INSERT INTO m (sid,role,text,ts,user_email,fname,file_hash) VALUES (?,?,?,?,?,?,?)",
           (session_id, "user", msg, time.time() - 2.0, email, filename, fhash))
           
        violations_str = "\n".join(f"- {v}" for v in violations) if violations else "No physical violations found."
        audit_text = f"PHYSICS HEALTH AUDIT: {physics_score}% | STATUS: {physics_status}\n{violations_str}"
        db("INSERT INTO m (sid,role,text,ts,user_email) VALUES (?,?,?,?,?)",
           (session_id, "model", audit_text, time.time() - 1.0, email))
           
        pressures = []
        porosities = []
        perms = []
        for r in extracted_json:
            p = r.get("Pressure_psi")
            phi = r.get("Porosity_percent")
            k = r.get("Air_Permeability_md")
            if p is not None and phi is not None:
                pressures.append(p)
                porosities.append(phi)
                perms.append(k if k is not None else 0.0)
                
        plot_json = {
            "title": "Porosity & Permeability vs Overburden Pressure",
            "curves": [
                {"name": "Porosity (%)", "x": pressures, "y": porosities, "yId": "left"},
                {"name": "Permeability (mD)", "x": pressures, "y": perms, "yId": "right"}
            ],
            "dualAxis": True,
            "y_label": "Porosity (%)",
            "y_label2": "Air Permeability (mD)",
            "x_label": "Overburden Pressure (psi)"
        }
        plot_text = f"__PRC_PLOT__\n{_json.dumps(plot_json)}\n\n"
        db("INSERT INTO m (sid,role,text,ts,user_email) VALUES (?,?,?,?,?)",
           (session_id, "model", plot_text, time.time(), email))
           
        TASKS_DB[session_id].update({"progress": 55})

        import os as _os
        base_dir = _os.path.dirname(_os.path.abspath(__file__))
        outputs_dir = _os.path.join(base_dir, "outputs", session_id)
        _os.makedirs(outputs_dir, exist_ok=True)
        
        # Master Engineer analysis runs on NVIDIA NIM via the injected llm_call
        # (sovereign path). The Gemini key is only kept as a legacy fallback
        # client inside the node; with DUMMY_KEY the node degrades to its
        # offline analysis text instead of crashing.
        active_key = GEMINI_KEY_POOL[0] if GEMINI_KEY_POOL else "DUMMY_KEY"
        master_eng = MasterEngineerNode(api_key=active_key, llm_call=_nvidia_text_generate)
        engineer_report = master_eng.analyze_scal_data(extracted_json)
        
        report_path = _os.path.join(outputs_dir, "reservoir_report.md")
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(engineer_report)
            
        well_name = "PROVISIONAL WELL"
        if isinstance(fr_data, dict):
            well_name = fr_data.get("well_name") or fr_data.get("well") or "PROVISIONAL WELL"
            
        _dash_audit = {"score": physics_score, "status": physics_status, "violations": violations}
        dash_output_path = _os.path.join(outputs_dir, "app_dashboard.py")
        
        streamlit_code = generate_universal_dashboard(
            validated_json=extracted_json,
            well_name=well_name,
            test_type=detected_type,
            physics_audit=_dash_audit,
            output_path=dash_output_path,
        )
        
        visualizer.generate_plots(extracted_json, output_dir=outputs_dir, streamlit_code=streamlit_code)
        
        try:
            with open(temp_file_path, "rb") as f:
                data_bytes = f.read()
            _fhash_store = hashlib.sha256(data_bytes).hexdigest()
            db(
                "INSERT INTO user_files"
                " (user_email, filename, file_hash, extracted_text, data_type, created_at)"
                " VALUES (?,?,?,?,?,?)"
                " ON CONFLICT(user_email, file_hash)"
                " DO UPDATE SET extracted_text=EXCLUDED.extracted_text,"
                " filename=EXCLUDED.filename",
                (email, filename, _fhash_store, fr_text, "SCAL", time.time()),
            )
        except Exception as _ufe:
            _logger.warning(f"Could not log file to user_files in bg task: {_ufe}")
            
        TASKS_DB[session_id].update({"progress": 70})
        
        start_time = time.time()
        filename_report = PRCReportEngine().generate(session_id, well_name, output_dir=str(PRC_VAULT))
        duration = time.time() - start_time
        with _REPORT_LATENCY_LOCK:
            _REPORT_LATENCY_LIST.append(duration)
            
        TASKS_DB[session_id].update({
            "status": "success",
            "progress": 100,
            "result": f"/api/report/download/{filename_report}"
        })
        
    except Exception as e:
        _logger.error(f"[BgTask] Failed document generation task for {session_id}: {e}", exc_info=True)
        if session_id in TASKS_DB:
            TASKS_DB[session_id].update({
                "status": "error",
                "progress": 100,
                "error": str(e)
            })
    finally:
        try:
            Path(temp_file_path).unlink(missing_ok=True)
        except Exception:
            pass


def async_report_compile_task(session_id: str, well_name: str):
    try:
        TASKS_DB[session_id]["progress"] = 30
        start_time = time.time()
        filename = PRCReportEngine().generate(session_id, well_name, output_dir=str(PRC_VAULT))
        duration = time.time() - start_time
        with _REPORT_LATENCY_LOCK:
            _REPORT_LATENCY_LIST.append(duration)
            
        TASKS_DB[session_id].update({
            "status": "success",
            "progress": 100,
            "result": f"/api/report/download/{filename}"
        })
    except Exception as e:
        _logger.error(f"[Background Task Error] Report generation failed: {e}")
        TASKS_DB[session_id].update({
            "status": "error",
            "progress": 100,
            "error": f"Report generation failed: {str(e)}"
        })


@app.post(
    "/api/report/generate",
    description="Generate petrophysical conclusion and interpret SCAL report insights.",
    responses={
        429: {"description": "Rate limit exceeded"},
        500: {"description": "Internal server error"}
    }
)
@_limiter.limit("10/minute")
async def generate_report(
    request: Request,
    background_tasks: BackgroundTasks,
    session_id: str = Form(...),
    well_name:  str = Form("UNKNOWN WELL"),
    auth:       bool = Depends(verify_user_or_admin),
):
    # Path traversal prevention using regex
    if not re.match(r"^(report-)?[a-zA-Z0-9\-]+$", session_id):
        raise HTTPException(status_code=400, detail="Invalid session_id format.")

    # Initialize task record in TASKS_DB
    TASKS_DB[session_id] = {
        "status": "processing",
        "progress": 10,
        "result": None,
        "error": None
    }

    background_tasks.add_task(async_report_compile_task, session_id, well_name)

    return JSONResponse(
        status_code=202,
        content={
            "status": "processing",
            "progress": 10,
            "session_id": session_id,
            "task_url": f"/api/v1/tasks/{session_id}"
        }
    )


@app.post(
    "/api/v1/analyze-scal",
    description="Analyze uploaded SCAL spreadsheet or file, returning parameters and starting session.",
    responses={
        429: {"description": "Rate limit exceeded"},
        500: {"description": "Internal server error"}
    }
)
@_limiter.limit("10/minute")
async def analyze_scal(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    session_id: Optional[str] = Form(None),
    user_email: Optional[str] = Form(None),
    message: Optional[str] = Form(None),
    authorization: Optional[str] = Header(None),
    token: Optional[str] = Query(None),
):
    temp_file_path = None
    try:
        verify_user_or_admin(authorization=authorization, token=token, user_email=user_email)
        sid = session_id or str(uuid.uuid4())

        # Destructive memory eviction protocol on new file ingestion
        evict_session(sid)

        filename = sanitize_filename(file.filename)
        email = normalize_email(user_email)
        if not email and sid:
            row = db("SELECT user_email FROM sessions WHERE sid=?", (sid,))
            if row and row[0][0]:
                email = row[0][0].lower().strip()
        msg = (message or "Analyze petrophysical data from uploaded file.").strip()

        # Synchronously insert session row before report generation
        if _PG_AVAILABLE:
            await async_db(
                "INSERT INTO sessions (sid, title, user_email, updated_at) VALUES (?, 'New Study', ?, ?) "
                "ON CONFLICT (sid) DO UPDATE SET updated_at = EXCLUDED.updated_at",
                (sid, email, time.time())
            )
        else:
            await async_db(
                "INSERT OR IGNORE INTO sessions (sid, title, user_email, created_at, updated_at) VALUES (?, 'New Study', ?, ?, ?)",
                (sid, email, time.time(), time.time())
            )
            await async_db("UPDATE sessions SET updated_at=? WHERE sid=?", (time.time(), sid))

        auto_rename_session_if_new(sid, email, filename=filename, message=msg)
        
        # Path traversal prevention using regex
        if not re.match(r"^(report-)?[a-zA-Z0-9\-]+$", sid):
            raise HTTPException(status_code=400, detail="Invalid session_id format.")

        # Setup isolated temp file paths
        import tempfile
        from pathlib import Path
        ext = Path(filename.lower()).suffix
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
        temp_file_path = temp_file.name
        temp_file.close()

        # Safe streaming of file chunked to temp path
        await process_large_file_stream(file, temp_file_path, _MAX_UPLOAD_BYTES)

        # Signature verification (prevent invalid files) from temp file
        with open(temp_file_path, "rb") as f:
            sig_bytes = f.read(1024)
        if not verify_file_signature(sig_bytes, filename):
            raise HTTPException(status_code=400, detail=f"File signature mismatch or invalid format for extension: {filename}")

        # Run the absolute truth extractor to convert spreadsheet rows into string context
        from scal_file_handler import extract_absolute_file_truth
        loop = asyncio.get_running_loop()
        ground_truth_string = await loop.run_in_executor(None, extract_absolute_file_truth, [(temp_file_path, file.filename)])
        
        # Calculate file content hash
        with open(temp_file_path, "rb") as f:
            fhash = hashlib.sha256(f.read()).hexdigest()

        # HYDRATE THE ACTIVE CHAT CACHE NATIVELY BEFORE ANY UTILITY RUNS
        with SESSION_DATA_CACHE_LOCK:
            if fhash not in SESSION_DATA_CACHE:
                SESSION_DATA_CACHE[fhash] = {}
            SESSION_DATA_CACHE[fhash]["ground_truth"] = ground_truth_string
            # Initialize labeled values if missing to ensure completeness gate passes
            if "labeled_values" not in SESSION_DATA_CACHE[fhash]:
                SESSION_DATA_CACHE[fhash]["labeled_values"] = {}
                
        # Also populate labeled values and flat vectors synchronously to prevent fitters from aborting
        populate_cache_from_ground_truth(fhash, ground_truth_string)
        ext_lower = Path(file.filename).suffix.lower()
        if ext_lower in ('.xlsx', '.xlsm', '.xls', '.ods', '.csv'):
            await loop.run_in_executor(None, cache_excel_data_vectors, fhash, temp_file_path)

        # Initialize task record in TASKS_DB
        TASKS_DB[sid] = {
            "status": "queued",
            "progress": 0,
            "result": None,
            "error": None
        }
        
        # Trigger the background task worker
        background_tasks.add_task(
            sync_document_generation_task,
            session_id=sid,
            temp_file_path=temp_file_path,
            filename=filename,
            email=email,
            message=msg
        )
        
        return JSONResponse(
            status_code=202,
            content={
                "status": "queued",
                "progress": 0,
                "session_id": sid,
                "task_url": f"/api/v1/tasks/{sid}"
            }
        )
    except HTTPException as he:
        if temp_file_path:
            try: Path(temp_file_path).unlink(missing_ok=True)
            except Exception: pass
        raise he
    except Exception as e:
        if temp_file_path:
            try: Path(temp_file_path).unlink(missing_ok=True)
            except Exception: pass
        _logger.error(f"[AnalyzeSCAL] Failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/tasks/{session_id}")
async def get_task_status(
    session_id: str,
    user_email: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
    token: Optional[str] = Query(None),
):
    try:
        verify_user_or_admin(authorization=authorization, token=token, email_query=user_email)
        if "\x00" in session_id:
            raise HTTPException(status_code=400, detail="Null bytes are strictly prohibited.")
        # Path traversal prevention using regex check
        if not re.match(r"^(report-)?[a-zA-Z0-9\-]+$", session_id):
            raise HTTPException(status_code=400, detail="Invalid session_id format.")
            
        if session_id not in TASKS_DB:
            raise HTTPException(status_code=404, detail="Task not found or expired.")
            
        return TASKS_DB[session_id]
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid session identifier: {str(e)}")


@app.get("/api/report/download/{filename}")
async def download_report(
    filename: str,
    user_email: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
    token: Optional[str] = Query(None),
):
    try:
        verify_user_or_admin(authorization=authorization, token=token, email_query=user_email)
        # Clean null bytes immediately (CWE-22)
        if "\x00" in filename:
            raise HTTPException(status_code=400, detail="Null bytes are strictly prohibited.")
            
        # Serve from the shared PRC vault with path-containment guard (CWE-22)
        reports_root = PRC_VAULT
        target = (reports_root / Path(filename).name).resolve()

        if not str(target).startswith(str(reports_root.resolve())):
            raise HTTPException(status_code=403, detail="Access denied")

        if not target.is_file():
            raise HTTPException(status_code=404, detail="Report not found")

        return FileResponse(str(target), filename=Path(filename).name)
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid path parameters: {str(e)}")

# -- GRADER ------------------------------------------------------------------

@app.post(
    "/api/grade",
    description="Grade AI responses against authoritative documents uploaded.",
    responses={
        429: {"description": "Rate limit exceeded"},
        500: {"description": "Internal server error"}
    }
)
@_limiter.limit("10/minute")
async def api_grade_response(
    request: Request,
    file:        UploadFile = File(...),
    ai_response: str        = Form(...),
    user_email:  Optional[str] = Form(None),
    authorization: Optional[str] = Header(None),
    token:       Optional[str] = Query(None),
):
    verify_user_or_admin(authorization=authorization, token=token, user_email=user_email)
    import tempfile
    file.filename = sanitize_filename(file.filename)
    max_bytes = _MAX_UPLOAD_BYTES
    chunk_size = 64 * 1024
    content = bytearray()
    while True:
        chunk = await file.read(chunk_size)
        if not chunk:
            break
        content.extend(chunk)
        if len(content) > max_bytes:
            raise HTTPException(status_code=413, detail="File size exceeds maximum allowed limit.")
    file_bytes = bytes(content)
    if not verify_file_signature(file_bytes, file.filename):
        raise HTTPException(status_code=400, detail=f"File signature mismatch or invalid format for extension: {file.filename}")
    ext = Path(file.filename).suffix.lower() or ".xlsx"
    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tf:
        tf.write(file_bytes)
        tmp_path = tf.name
    try:
        result = grade_ai_response(tmp_path, ai_response)
        return {
            "status":  "success",
            "score":   result["score"],
            "grade":   result["grade"],
            "report":  result["report"],
            "checks":  result["checks"],
        }
    except Exception as e:
        _logger.error(f"[Grader] {e}")
        raise HTTPException(status_code=500, detail=str(e))
class ScalCalibrateRequest(BaseModel):
    # Brooks-Corey points
    sw: Optional[list[float]] = None
    krw: Optional[list[float]] = None
    kro: Optional[list[float]] = None
    swi: float = 0.15
    sor: float = 0.2
    krw_max: float = 0.5
    kro_max: float = 0.8
    
    # Archie points
    porosity: Optional[list[float]] = None
    formation_factor: Optional[list[float]] = None
    
    basin_name: Optional[str] = "Default"


@app.post("/api/scal/calibrate")
def scal_calibrate(req: ScalCalibrateRequest):
    import numpy as np
    from petrophysical_curves import Endpoints, KrCurveFitter
    from physics_validator import PhysicsGuard
    
    # Check if we are calibrating Archie
    if req.porosity is not None and req.formation_factor is not None:
        phi_arr = np.array(req.porosity)
        ff_arr = np.array(req.formation_factor)
        # Avoid zeros/negatives
        valid = (phi_arr > 0) & (ff_arr > 0)
        if np.sum(valid) >= 2:
            x = np.log(phi_arr[valid])
            y = np.log(ff_arr[valid])
            slope, intercept = np.polyfit(x, y, 1)
            m_fit = -slope
            a_fit = np.exp(intercept)
        else:
            m_fit = 2.0
            a_fit = 1.0
            
        guard = PhysicsGuard()
        guard.validate_archie_parameters(a=a_fit, m=m_fit, b=1.0, n=2.0, basin_name=req.basin_name)
        audit = guard.generate_health_score()
        
        # Build coordinates for the fitted line
        phi_line = np.linspace(0.01, 0.4, 50)
        ff_line = a_fit * (phi_line ** -m_fit)
        
        return {
            "type": "archie",
            "a": float(a_fit),
            "m": float(m_fit),
            "phi_line": phi_line.tolist(),
            "ff_line": ff_line.tolist(),
            "physics_audit": audit
        }
        
    # Relative permeability calibration
    if req.sw is not None and req.krw is not None and req.kro is not None:
        sw_arr = np.array(req.sw)
        krw_arr = np.array(req.krw)
        kro_arr = np.array(req.kro)
        
        ep = Endpoints(
            Swi=req.swi,
            Sor=req.sor,
            Krw_max=req.krw_max,
            Kro_max=req.kro_max
        )
        
        fitter = KrCurveFitter(ep)
        bc_res = fitter.fit_brooks_corey(sw_arr, krw_arr, kro_arr)
        plot_data = fitter.to_plot_json(sw_arr, krw_arr, kro_arr, model="brooks_corey", fit_result=bc_res)
        
        guard = PhysicsGuard()
        guard.validate_kr(sw_arr, krw_arr, kro_arr)
        audit = guard.generate_health_score()
        
        plot_data["metadata"] = plot_data.get("metadata", {})
        plot_data["metadata"]["physics_audit"] = audit
        plot_data["type"] = "kr"
        
        return plot_data

    raise HTTPException(status_code=400, detail="Missing coordinate inputs for calibration.")


class BasinRuleModel(BaseModel):
    basin_name: str
    rule_key: str
    min_limit: float
    max_limit: float


@app.get("/api/admin/rules")
def get_admin_rules():
    rows = db("SELECT basin_name, rule_key, min_limit, max_limit FROM basin_physics_rules")
    return [{"basin_name": r[0], "rule_key": r[1], "min_limit": r[2], "max_limit": r[3]} for r in rows]


@app.post("/api/admin/rules")
def post_admin_rule(req: BasinRuleModel):
    db(
        "INSERT INTO basin_physics_rules (basin_name, rule_key, min_limit, max_limit) "
        "VALUES (?, ?, ?, ?) "
        "ON CONFLICT(basin_name, rule_key) DO UPDATE SET min_limit=excluded.min_limit, max_limit=excluded.max_limit",
        (req.basin_name, req.rule_key, req.min_limit, req.max_limit)
    )
    return {"status": "success"}


# ── FRONTEND SERVING (SPA) ──â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€

_DIST_DIR = str(Path(__file__).parent / "frontend" / "dist")

# Resolved once at startup; used by serve_spa to enforce path containment (CWE-22)

_DIST_DIR_PATH = Path(_DIST_DIR).resolve()



if Path(_DIST_DIR).exists():

    app.mount("/assets", StaticFiles(directory=str(Path(_DIST_DIR) / "assets")), name="assets")



@app.get("/{full_path:path}")

async def serve_spa(full_path: str):

    if full_path.startswith("api/"):

        raise HTTPException(status_code=404, detail="API endpoint not found")



    # Resolve the candidate path and verify it stays inside _DIST_DIR (CWE-22 guard).

    # Unlike /api/download we allow nested paths (assets/js/â€¦) so we use the full

    # sub-path, but we still reject any traversal that escapes the dist tree.

    candidate = (_DIST_DIR_PATH / full_path).resolve()

    if not str(candidate).startswith(str(_DIST_DIR_PATH)):

        raise HTTPException(status_code=403, detail="Access denied")



    if candidate.is_file():

        return FileResponse(str(candidate))



    # If the path has an extension, it's a file request that wasn't found - return 404!

    # This prevents returning index.html (200 OK) for ../app.py or other system files.

    if "." in Path(full_path).name:

        raise HTTPException(status_code=404, detail="File not found")



    index_html = _DIST_DIR_PATH / "index.html"

    if index_html.exists():

        return FileResponse(str(index_html))



    return {"error": "Frontend build not found. Run 'npm run build' in frontend directory."}



if __name__ == "__main__":

    import uvicorn

    init_db()

    uvicorn.run(app, host="0.0.0.0", port=8000)


