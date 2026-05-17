# app.py

# PRC-HUB-VER-14-PROD-READY | 2026-05-10

# Changes: DB connection pooling Â· safe PG placeholder translation Â· thread-safe

#          key rotation Â· thread-local file URIs Â· asyncio.Queue SSE bridge Â·

#          run_in_executor RAG Â· transactional KB ingest Â· admin backend auth Â·

#          env-var secrets Â· slowapi rate limiting Â· dead code purged



import os, io, uuid, time, re, hmac, hashlib, secrets as _secrets
import json as _json, logging, threading, asyncio
import anyio

from contextlib import asynccontextmanager, contextmanager
from typing import Optional
from concurrent.futures import ThreadPoolExecutor

import numpy as np



from fastapi import FastAPI, UploadFile, File, Form, Request, HTTPException, Header, Depends, BackgroundTasks

from fastapi.responses import FileResponse, StreamingResponse, JSONResponse

from fastapi.staticfiles import StaticFiles

from fastapi.middleware.cors import CORSMiddleware



from google import genai as genai_new

from google.genai import types as genai_types



from hviel_doc_engine import HvielDocEngine

from skills_engine import SkillsEngine

from petrophysical_curves import Endpoints, KrCurveFitter

from physics_validator import PhysicsGuard

from scal_file_handler import SCALFileHandler, extract_file_data

from report_generator import PRCReportEngine



logging.basicConfig(

    level=logging.INFO,

    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",

)

_logger = logging.getLogger("PRC-Hub")



# -- ENV ----------------------------------------------------------------------

try:

    from dotenv import load_dotenv

    load_dotenv()

except Exception:

    pass



# -- RATE LIMITER (optional dep) -----------------------------------------------

try:

    from slowapi import Limiter, _rate_limit_exceeded_handler

    from slowapi.util import get_remote_address

    from slowapi.errors import RateLimitExceeded

    _limiter = Limiter(key_func=get_remote_address)

    _RATE_LIMIT = True

except ImportError:

    _limiter = None

    _RATE_LIMIT = False



# -- SECRETS -------------------------------------------------------------------

_GEMINI_POOL_RAW: list[str] = []

for _k, _v in os.environ.items():

    if _k.startswith("GEMINI_API_KEY"):

        _GEMINI_POOL_RAW.extend(x.strip() for x in _v.split(",") if x.strip())



GEMINI_KEY_POOL: list[str] = list(dict.fromkeys(_GEMINI_POOL_RAW)) or [

    os.getenv("GEMINI_API_KEY", "DUMMY_KEY").strip(' \n\r\t"\'')

]



KB_INGEST_SECRET = os.getenv("KB_INGEST_SECRET", "").strip()

ADMIN_PIN        = os.getenv("ADMIN_PIN", "").strip()



_ADMIN_TOKENS:    dict[str, float] = {}   # token  ->  expiry (epoch)

_ADMIN_TOKEN_TTL: int              = 900  # 15 min



# -- DATABASE LAYER ------------------------------------------------------------

DATABASE_URL  = os.getenv("DATABASE_URL", "").strip()

DB_PATH       = "chat_history.db"



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


_PG_POOL      = None

_PG_AVAILABLE = False

_SQLITE_LOCK  = threading.Lock()



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

            try:

                yield conn, "?"

            finally:

                conn.close()





def db(query: str, params: tuple = ()) -> list:

    """Execute a query with ? placeholders, falling back to SQLite if PostgreSQL fails."""

    last_err = None

    for attempt in range(2):

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

            _logger.warning(f"[DB RETRY] Attempt {attempt+1} failed for query '{query[:50]}...': {e}")

            time.sleep(0.1 * (attempt + 1))

    

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

                        "model":  {"type": "STRING", "description": "For petrophysics.py: regress_archie_m_a, regress_archie_n, rqi_fzi. For centrifuge: pc_only, full, hassler_brunner"},

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

        ]

    }

]



_PETRO_KEYS = frozenset({

    "swr","snr","krw_max","kro_max","nw","no","Lw","Ew","Tw","Lo","Eo","To",

    "nx","ny","dx","dy","dz","dt","steps","porosity","perm","swi","pi","q_inj","mu_w","mu_o",

})



_tls = threading.local()





# â”€â”€ GEMINI HA CLIENT â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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

                _logger.info(f"[HA] Node {idx+1} active ({key[:8]}...)")

                return

            except Exception as e:

                _logger.warning(f"[HA] Node {idx+1} init failed: {e}")

        try:

            with self._client_lock:

                self._client = genai_new.Client(api_key=self._keys[0])

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

            if script == "petrophysics.py":

                subdir = "scalskills/scripts"

                args_list = [model, _json.dumps(p)]

            else:

                subdir = ""

                p["mode"] = model

                args_list = [_json.dumps(p)]

                

            res = SkillsEngine.run_skill("petroleum", subdir, script, args_list)

            result = res.get("stdout") or res.get("stderr") or res.get("error", "")

            yield (True, result)

            return

        elif name == "generate_mermaid_diagram":

            result = f"__MERMAID_START__\n{args.get('content','')}\n__MERMAID_END__"

        elif name == "fit_petrophysical_curve":

            model = args.get("model", "")

            if model in ("micp", "ri", "ff", "jfunction", "pc_centrifuge", "overburden"):

                # All analytic models: computation fully handled by _format_tool_response using args

                result = _json.dumps({"status": "ready", "model": model})

            else:

                data = {"model": model, "sw": args.get("sw",[]), "krw": args.get("krw",[])}

                res  = SkillsEngine.run_skill("petroleum", "", "curve_fitting_skill.py", [_json.dumps(data)])

                result = res.get("stdout") or res.get("stderr") or res.get("error", "")

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

                    filename = PRCReportEngine().generate(session_id=sid, well_name=well)

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

        else:

            result = f"Unknown tool: {name}"

        

        yield (True, result)



    def _format_tool_response(self, name: str, args: dict, result: str) -> str:

        try:

            # â”€â”€ Executive Report â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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



            # â”€â”€ MICP: Drainage + Imbibition, log-Pc, % x-axis, hysteresis â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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

                    # â”€â”€ Imbibition (recovery) cycle â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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

                    # â”€â”€ Physics Guard â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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



            # â”€â”€ RESISTIVITY INDEX (Archie n fit, log-log) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

            if name == "fit_petrophysical_curve" and args.get("model") == "ri":

                sw_raw = args.get("sw", [])

                ri_raw = args.get("ri", [])

                sample = args.get("sample_name", "Core")

                if len(sw_raw) > 1 and len(ri_raw) > 1:

                    sw_a = np.array(sw_raw, dtype=float)

                    ri_a = np.array(ri_raw, dtype=float)

                    mask     = (sw_a > 0) & (ri_a > 0)

                    log_sw   = np.log(sw_a[mask])

                    log_ri   = np.log(ri_a[mask])

                    n_arch   = float(-np.polyfit(log_sw, log_ri, 1)[0])

                    n_arch   = max(1.5, min(n_arch, 3.0))

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

                    # â”€â”€ Physics Guard â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

                    audit = PhysicsGuard().validate_archie(sw_a, ri_a, "RI").generate_health_score()

                    plot_ri["metadata"]["physics_audit"] = audit

                    _log_physics_audit(

                        getattr(_tls, 'current_session_id', 'ANONYMOUS'), 

                        "ri", 

                        audit, 

                        getattr(_tls, 'last_file_name', None)

                    )



                    return (

                        f"__PRC_PLOT__\n{_safe_json_dumps(plot_ri)}\n\n"

                    )



            # â”€â”€ FORMATION FACTOR (Archie m, a fit, log-log) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

            if name == "fit_petrophysical_curve" and args.get("model") == "ff":

                phi_raw = args.get("porosity", [])

                ff_raw  = args.get("ff", [])

                sample  = args.get("sample_name", "Core")

                if len(phi_raw) > 1 and len(ff_raw) > 1:

                    phi_a   = np.array(phi_raw, dtype=float)

                    ff_a    = np.array(ff_raw,  dtype=float)

                    mask    = (phi_a > 0) & (ff_a > 0)

                    coeffs  = np.polyfit(np.log(phi_a[mask]), np.log(ff_a[mask]), 1)

                    m_arch  = float(max(1.3, min(-coeffs[0], 3.5)))

                    a_arch  = float(max(0.3, min(np.exp(coeffs[1]), 2.5)))

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

                    # â”€â”€ Physics Guard â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

                    audit = PhysicsGuard().validate_archie(phi_a, ff_a, "FF").generate_health_score()

                    plot_ff["metadata"]["physics_audit"] = audit

                    _log_physics_audit(

                        getattr(_tls, 'current_session_id', 'ANONYMOUS'), 

                        "ff", 

                        audit, 

                        getattr(_tls, 'last_file_name', None)

                    )



                    return (

                        f"__PRC_PLOT__\n{_safe_json_dumps(plot_ff)}\n\n"

                    )



            # â”€â”€ LEVERETT J-FUNCTION â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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

                    return (

                        f"__PRC_PLOT__\n{_safe_json_dumps(plot_j)}\n\n"

                    )



            # â”€â”€ CAPILLARY PRESSURE  -  CENTRIFUGE / POROUS PLATE â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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

                    # â”€â”€ Physics Guard â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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



            # â”€â”€ OVERBURDEN COMPACTION (dual-axis: Ï† left, k right log-scale) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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

                            "name": f"Porosity Ï† ({sample})", "showLine": True, "showPoints": True,

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

                        "title":         f"Overburden Compaction  -  Ï† & k vs Net Stress ({sample})",

                        "xAxis":         {"label": "Net Confining Pressure (psia)"},

                        "yAxis":         {"label": "Porosity Ï† (fraction)"},

                        "yAxis2":        {"label": "Permeability k (mD)"},

                        "dualAxis":      True,

                        "yAxisRightLog": True,

                        "curves":        curves,

                    }

                    summary = (f"Pressure range: {float(pres_a.min()):.0f} â€“ {float(pres_a.max()):.0f} psia")

                    return (f"__PRC_PLOT__\n{_safe_json_dumps(plot_ob)}\n\n")



            try:

                tr = _json.loads(result) if isinstance(result, str) else result

            except Exception:

                tr = {}

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



                # â”€â”€ Physics Guard â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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



                    # â”€â”€ Physics Guard â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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



            # Skip native Gemini upload for spreadsheets to eliminate 30s+ TTFT latency.

            # SCALFileHandler already extracts this data and provides it in the prompt.

            if "spreadsheet" in safe_mime or "excel" in safe_mime or "csv" in safe_mime or "sheet" in safe_mime:

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

                    os.unlink(tmp)

                except OSError:

                    pass



        contents.append(genai_types.Content(role="user", parts=user_parts))



        # Ensure session exists in the sessions table

        # We don't have the sid here, so we do it in the caller

        return contents, uploaded_uris



    def chat(self, history: list, msg: str, kb_context: str = "", f_parts: list = [], stream: bool = False, sid: str = None, email: str = None):

        _tls.pending_kb = []       # thread-local: safe under 50+ concurrent workers
        _tls.last_well_name = None  # updated when a SCAL file is processed this turn

        

        # â”€â”€ SESSION FILE REGISTRY (Persistence Guard) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

        session_files_ctx = ""

        if sid:

            try:

                # Use a lightweight query to see what files were mentioned in this session

                # We also want to know which one was the VERY LAST one mentioned before this turn

                rows = db("SELECT DISTINCT fname FROM m WHERE sid=? AND fname IS NOT NULL ORDER BY ts DESC", (sid,))

                if rows:

                    fnames = [r[0] for r in rows]

                    session_files_ctx = f"[SESSION FILE REGISTRY]: This session contains data for: {', '.join(fnames)}.\n"

                    session_files_ctx += f"[LATEST SESSION FILE]: {fnames[0]}\n"

                    session_files_ctx += "Reference the [LATEST SESSION FILE] if the user asks generic questions.\n\n"

            except: pass



        extracted_context = ""

        import tempfile

        def _sample_data(data: dict, max_rows: int = 40) -> dict:

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



        for data_bytes, mime, fname in f_parts:

            safe_mime = mime or "application/octet-stream"

            if any(x in safe_mime for x in ["spreadsheet", "excel", "csv", "sheet"]):

                ext = os.path.splitext(fname)[1].lower() if fname else ".xlsx"

                if not ext: ext = ".xlsx"

                with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tf:

                    tf.write(data_bytes)

                    tmp_path = tf.name

                try:

                    result = extract_file_data(tmp_path)

                    well_name = result.get('well_name', 'PROVISIONAL WELL')
                    _tls.last_well_name = well_name  # make available to report tool

                    inventory = f"FILE: {fname}\nWELL: {well_name}\nSHEETS: {', '.join(result['sheet_names'])}\nIDENTIFIED TYPE: {result['data_type']}\nTOTAL ROWS: {result['row_count']}\n"

                    extracted_context += f"\n\n[NEW UPLOAD INVENTORY]:\n{inventory}"

                    

                    if result.get('data_type') != 'UNKNOWN':

                        data_json = _json.dumps(result['extracted'])

                        sampled = _sample_data(result['extracted'])

                        extracted_context += f"[EXTRACTED DATA - WELL: {well_name}]:\n{_json.dumps(sampled, indent=2)}\n"

                        # Use the class method to chunk the JSON string

                        chunks = KnowledgeBase.chunk_text(data_json, f"File: {fname}")

                        _tls.pending_kb.extend(chunks)

                    else:

                        first_sheet = result['sheet_names'][0] if result['sheet_names'] else None

                        if first_sheet and first_sheet in handler.raw_data:

                            raw_df = handler.raw_data[first_sheet].iloc[:15, :10]

                            raw_str = raw_df.to_string(index=False, header=False)

                            extracted_context += f"[RAW DATA PREVIEW - SHEET: {first_sheet}]:\n{raw_str}\n"

                            _tls.pending_kb.append((f"Raw: {fname}", raw_str))

                except Exception as e:

                    _logger.error(f"SCAL Handler Error: {e}")

                finally:

                    try: os.unlink(tmp_path)

                    except: pass



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

            needs_pro = (

                len(f_parts) > 0 or 

                bool(extracted_context) or 

                any(x in msg_low_routing for x in ["simulate", "audit", "calculate", "fit", "report", "plot", "parameter"])

            )

            active_model = "gemini-2.5-pro" if needs_pro else "gemini-2.5-flash"



            _MAX_OVERLOAD_RETRIES = 3  # retries per key on 503

            _MAX_503_RETRIES = 3

            for attempt in range(len(self._keys)):

                try:

                    with self._client_lock:

                        client = self._client

                    cfg = genai_types.GenerateContentConfig(

                        temperature=0.2,

                        tools=_HVIEL_TOOLS,

                        system_instruction=SYSTEM_PROMPT,

                    )



                    # â”€â”€ STREAMING PATH (multi-turn tool use) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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



                            for chunk in client.models.generate_content_stream(

                                model=active_model, contents=current_contents, config=cfg

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



                    # â”€â”€ NON-STREAMING PATH (multi-turn tool use) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

                    current_contents = list(contents)

                    final = ""

                    for _turn in range(4):

                        resp = client.models.generate_content(

                            model=active_model, contents=current_contents, config=cfg

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

        self, file_type: str, message: str, history: list, kb_context: str, engineer: str

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



        hist_text = "".join(

            f"{h['role'].upper()}: {h.get('text','')[:600]}\n\n" for h in history[-8:]

        )

        kb_section = f"\nKNOWLEDGE BASE:\n{kb_context[:2500]}\n" if kb_context else ""



        system_doc = (

            f"You are Hviel  -  PRC Senior AI Petrophysical Specialist, Petroleum Research Center, Libya.\n"

            f"Generate a professional {file_type.upper()} export for the PRC.\n"

            f"CRITICAL: Respond with ONLY valid JSON. No markdown fences. No explanation. Raw JSON only.\n\n"

            f"JSON SCHEMA (use this structure exactly):\n{schema}\n\n"

            f"CONTENT RULES:\n"

            f"- Populate with real petrophysical data drawn from the conversation (Sw, Kr, Pc, Archie, etc.)\n"

            f"- Use engineering units throughout: mD, fraction, psi, m TVDSS, dimensionless\n"

            f"- Include Executive Summary, Methodology, Results & Interpretation, and Conclusions sections\n"

            f"- Tables must contain realistic numerical SCAL data  -  no placeholder values\n"

            f"- Minimum 4 sections (docx/pdf) or 2 data sheets (xlsx) with substantive content\n"

            f"- author field: \"{engineer}\"\n"

            f"- Never use '...' or '[insert value]'  -  derive everything from the conversation\n"

        )



        user_content = (

            f"CONVERSATION HISTORY:\n{hist_text}"

            f"{kb_section}\n"

            f"DOCUMENT REQUEST: {message}"

        )



        cfg = genai_types.GenerateContentConfig(temperature=0.1, system_instruction=system_doc)

        contents = [genai_types.Content(role="user", parts=[genai_types.Part(text=user_content)])]



        with self._client_lock:

            client = self._client



        for attempt in range(len(self._keys)):

            try:

                resp = client.models.generate_content(

                    model=active_model, contents=contents, config=cfg

                )

                if resp and resp.candidates and resp.candidates[0].content:

                    raw = "".join(

                        p.text for p in (resp.candidates[0].content.parts or []) if p.text

                    )

                    if raw.strip():

                        return raw.strip()

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

        raise ValueError("Gemini document generation failed after all retries")





# â”€â”€ RAG / KNOWLEDGE BASE â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

EMBED_MODEL        = "gemini-embedding-2"

_EMBED_CLIENT_LOCK = threading.Lock()

_EMBED_CLIENT      = None



def _get_embed_client() -> genai_new.Client:

    global _EMBED_CLIENT

    with _EMBED_CLIENT_LOCK:

        if _EMBED_CLIENT is None:

            _EMBED_CLIENT = genai_new.Client(api_key=GEMINI_KEY_POOL[0])

        return _EMBED_CLIENT



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

        for source, chunk in chunks:

            if not chunk or len(chunk.strip()) < 10: continue

            vec = KnowledgeBase._embed(chunk)

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



            # Filter KB chunks by session ID (Strict Isolation)

            with _get_conn() as (conn, ph):

                cur = conn.cursor()

                cur.execute(f"SELECT COUNT(*) FROM kb_vectors JOIN kb ON kb.id = kb_vectors.chunk_id WHERE kb.sid = {ph}", (sid,))

                vec_count = cur.fetchone()[0]

                

            if 0 < vec_count < 5000:

                q_vec = KnowledgeBase._embed(clean_q)

                if q_vec is not None:

                    # Optimized: Only pull vectors for THIS session

                    rows = db(f"SELECT kb.source, kb.chunk, kb_vectors.embedding FROM kb_vectors JOIN kb ON kb.id = kb_vectors.chunk_id WHERE kb.sid = {ph}", (sid,))

                    if rows:

                        sources = [r[0] for r in rows]; texts = [r[1] for r in rows]; raw_vecs = [r[2] for r in rows]

                        vecs = np.stack([np.frombuffer(bytes(v) if isinstance(v, memoryview) else v, dtype=np.float32) for v in raw_vecs])

                        q_norm = q_vec / (np.linalg.norm(q_vec) + 1e-9)

                        v_norms = vecs / (np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-9)

                        scores = v_norms @ q_norm

                        top_idx = np.argsort(scores)[::-1][:top_k]

                        parts = [f"[From: {sources[i]}]\n{texts[i]}" for i in top_idx if scores[i] > 0.40]

                        if parts: return "\n\n".join(parts)



            # Fallback to keyword search with session filtering

            words = [w.lower() for w in re.split(r"\W+", clean_q) if len(w) > 3][:5]

            if not words: return ""

            

            with _get_conn() as (conn, ph):

                clause = " OR ".join([f"LOWER(chunk) LIKE {ph}" for _ in words])

                params = tuple([f"%{w}%" for w in words] + [sid])

                rows = db(f"SELECT source, chunk FROM kb WHERE sid = {ph} AND ({clause}) LIMIT {top_k}", params)

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





# â”€â”€ APP SETUP â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def init_db() -> None:

    base_stmts = [

        "CREATE TABLE IF NOT EXISTS m (id INTEGER PRIMARY KEY AUTOINCREMENT, sid TEXT, role TEXT, text TEXT, url TEXT, ts REAL, user_email TEXT, fname TEXT)",

        "CREATE TABLE IF NOT EXISTS sessions (sid TEXT PRIMARY KEY, title TEXT NOT NULL DEFAULT 'New Study', user_email TEXT, created_at REAL, updated_at REAL)",

        "CREATE TABLE IF NOT EXISTS kb (id INTEGER PRIMARY KEY AUTOINCREMENT, sid TEXT, user_email TEXT, source TEXT, chunk TEXT)",

        "CREATE TABLE IF NOT EXISTS kb_vectors (id INTEGER PRIMARY KEY AUTOINCREMENT, chunk_id INTEGER UNIQUE, embedding BLOB)",

        "CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT UNIQUE, name TEXT, created_at REAL)",

        "CREATE TABLE IF NOT EXISTS feedback (id INTEGER PRIMARY KEY AUTOINCREMENT, user_email TEXT, bug_report TEXT, ts REAL)",

        "CREATE TABLE IF NOT EXISTS analytics_events (id INTEGER PRIMARY KEY AUTOINCREMENT, user_email TEXT, event_type TEXT, event_data TEXT, ts REAL)",

        # THE AUDITOR'S LEDGER  -  append-only physics integrity log

        "CREATE TABLE IF NOT EXISTS physics_audits (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, user_email TEXT, timestamp REAL, data_type TEXT, health_score INTEGER, violations TEXT, file_name TEXT)",

        "CREATE TABLE IF NOT EXISTS response_cache (id INTEGER PRIMARY KEY AUTOINCREMENT, query_hash TEXT UNIQUE, response TEXT, created_at REAL)",

    ]

    if _PG_AVAILABLE:

        base_stmts = [s.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY").replace("BLOB", "BYTEA") for s in base_stmts]

    for s in base_stmts:

        try: db(s)

        except Exception: pass

    try: db("CREATE INDEX IF NOT EXISTS idx_query_hash ON response_cache(query_hash)")

    except Exception: pass

    

    # Migrations for KB isolation

    for col in ["sid", "user_email"]:

        try: db(f"ALTER TABLE kb ADD COLUMN {col} TEXT")

        except Exception: pass

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
    init_db()
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
    try:
        yield
    finally:
        executor.shutdown(wait=False)  # release threads on shutdown; don't block SIGTERM



app = FastAPI(lifespan=lifespan)

if _RATE_LIMIT:

    app.state.limiter = _limiter

    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)



@app.exception_handler(Exception)
async def _global_exception_handler(request: Request, exc: Exception):
    import traceback
    _logger.error(f"UNHANDLED ERROR {request.method} {request.url.path}: {traceback.format_exc()}")
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error. Please try again.", "detail": str(exc)},
    )



_CORS_ORIGINS: list[str] = [
    o.strip()
    for o in os.getenv("ALLOWED_ORIGINS", "*").split(",")
    if o.strip()
] or ["*"]

app.add_middleware(

    CORSMiddleware,

    allow_origins=_CORS_ORIGINS,

    allow_credentials=True,

    allow_methods=["*"],

    allow_headers=["*"],

)



assistant = PRCChatAssistant(GEMINI_KEY_POOL)

try:

    hviel_engine = HvielDocEngine(output_dir=".")

except Exception as _he:

    _logger.error(f"[SYSTEM] HvielDocEngine failed: {_he}")

    hviel_engine = None



# â”€â”€ ROUTES â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

# â”€â”€ AUTH & SESSION VERIFICATION â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _verify_session_owner(sid: str, email: str):

    """Row-Level Security: every session endpoint must verify the caller owns the session."""

    if not email:

        raise HTTPException(status_code=401, detail="Authentication required")

    row = db("SELECT user_email FROM sessions WHERE sid=?", (sid,))

    if row and row[0][0] and row[0][0].lower().strip() != email.lower().strip():

        _logger.warning(f"[SECURITY] Unauthorized access attempt: {email}  ->  session {sid}")

        raise HTTPException(status_code=403, detail="Unauthorized: You do not own this session.")



@app.get("/health")

def health(): return {"status": "ok", "db": "postgres" if _PG_AVAILABLE else "sqlite"}



@app.get("/api/diag")

def diag():

    with _FAILED_KEYS_LOCK: snap = dict(_FAILED_KEYS)

    now = time.time(); cooldown = sum(1 for v in snap.values() if (now - v.get("ts",0)) < v.get("wait",0))

    with assistant._idx_lock: idx = assistant._current_idx

    return {"version": "PRC-HUB-VER-14-PROD-READY", "node_pool_size": len(GEMINI_KEY_POOL), "active_node_idx": idx, "nodes_in_cooldown": cooldown}



# â”€â”€ ADMIN AUTH â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def verify_admin(authorization: str = Header(None)):

    if not authorization or not authorization.startswith("Bearer "):

        raise HTTPException(status_code=401, detail="Missing or invalid token")

    token = authorization.split(" ")[1]

    if token not in _ADMIN_TOKENS or time.time() > _ADMIN_TOKENS[token]:

        if token in _ADMIN_TOKENS: del _ADMIN_TOKENS[token]

        raise HTTPException(status_code=401, detail="Token expired or invalid")

    return True



@app.post("/api/auth")

async def user_login(pin: str = Form(...)):

    # Auth against configured ADMIN_PIN (must be set in environment)

    target_pin = ADMIN_PIN

    if pin != target_pin:

        _logger.warning(f"[AUTH] Failed user login attempt with code: {pin}")

        time.sleep(0.5)

        raise HTTPException(status_code=401, detail="Invalid Access Code")

    return {"status": "success"}



@app.post("/api/admin/auth")

async def admin_login(pin: str = Form(...)):

    # Auth against configured ADMIN_PIN (must be set in environment)

    target_pin = ADMIN_PIN

    if pin != target_pin:

        _logger.warning(f"[ADMIN] Failed login attempt with PIN: {pin}")

        time.sleep(1) # Throttling

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

        return {

            "total_users": t_users, "total_feedback": t_feedback,

            "total_events": t_events, "total_messages": t_msgs,

            "total_sessions": t_sessions, "total_kb_chunks": t_kb,

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

async def submit_feedback(user_email: str = Form(""), bug_report: str = Form(...)):

    await async_db("INSERT INTO feedback (user_email, bug_report, ts) VALUES (?, ?, ?)", (user_email.lower(), bug_report, time.time()))

    return {"status": "ok"}



@app.post("/api/analytics/event")

async def track_event(user_email: str = Form(""), event_type: str = Form(...), event_data: str = Form("")):

    await async_db("INSERT INTO analytics_events (user_email, event_type, event_data, ts) VALUES (?, ?, ?, ?)",

       (user_email.lower(), event_type, event_data, time.time()))

    return {"status": "ok"}



@app.get("/api/sessions")

async def get_sessions(email: str = None):

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

def get_session(sid: str, email: str = None):

    _verify_session_owner(sid, email)

    rows = db("SELECT role, text, url, ts, fname FROM m WHERE sid=? AND user_email=? ORDER BY id", (sid, email))

    title_row = db("SELECT title FROM sessions WHERE sid=? AND user_email=?", (sid, email))

    title = title_row[0][0] if title_row else "New Study"

    return {

        "status":"ok",

        "title": title,

        "messages":[{"role":r,"text":t,"download_url":u,"ts":ts,"fileName":fn} for r,t,u,ts,fn in rows]

    }



@app.post("/api/session/{sid}/title")

async def update_session_title(sid: str, email: str = Form(...), title: str = Form(...)):

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

def delete_session(sid: str, email: str = None):

    _verify_session_owner(sid, email)

    db("DELETE FROM m WHERE sid=?", (sid,))

    db("DELETE FROM sessions WHERE sid=?", (sid,))

    db("DELETE FROM physics_audits WHERE session_id=?", (sid,))

    KnowledgeBase.delete_session_data(sid)

    return {"status": "ok"}



@app.get("/api/chat/stream")

async def chat_stream(

    message:       str,

    background_tasks: BackgroundTasks,

    session_id:    Optional[str]   = None,

    user_email:    Optional[str]   = None,

):

    if session_id in ("null", "undefined", "", None):

        sid = str(uuid.uuid4())

    else:

        sid = session_id

    email = user_email.lower().strip() if user_email else None

    

    # â”€â”€ SSE PRODUCER WITH HEARTBEAT â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    async def _producer():

        q = asyncio.Queue(maxsize=2000)  # bounded: prevents unbounded growth on client disconnect

        loop = asyncio.get_running_loop()

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



                # 4. Context Preparation

                hist_rows = db("SELECT role, text FROM m WHERE sid=? ORDER BY id DESC LIMIT 10", (sid,))

                history   = list(reversed([{"role": r, "text": t} for r, t in hist_rows]))



                # 5. Gemini Chat Logic

                _tls.current_session_id = sid

                full_reply = ""

                for chunk in assistant.chat(history, message, kb_context=kb_ctx, stream=True, sid=sid, email=email):

                    if q.qsize() >= 1900:  # consumer gone; abort stream to stop memory growth
                        _logger.warning("[SSE Worker] Queue near-full — client likely disconnected, aborting.")
                        break

                    if isinstance(chunk, dict):

                        if chunk.get("type") == "token":

                            full_reply += chunk.get("text", "")

                        _enqueue(chunk)

                    else:

                        full_reply += str(chunk)

                        _enqueue({"type": "token", "text": str(chunk)})



                # 6. Finalization

                if full_reply:

                    db("INSERT INTO m (sid,role,text,ts,user_email) VALUES (?,?,?,?,?)",

                       (sid, "model", full_reply, time.time(), email))



                if getattr(_tls, 'pending_kb', None):

                    # Capture pending KB — _tls is this worker thread's own storage

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



@app.post("/api/chat")

async def handle(

    background_tasks: BackgroundTasks,

    message:       Optional[str]    = Form(None),

    session_id:    Optional[str]    = Form(None),

    user_email:    Optional[str]    = Form(None),

    engineer_name: Optional[str]    = Form(None),

    files:         list[UploadFile] = File(default=[]),

):

    sid      = session_id or str(uuid.uuid4())

    email    = user_email.lower().strip() if user_email else None

    engineer = (engineer_name or "PRC Engineering Staff").strip()



    valid_files = [f for f in files if getattr(f, "filename", "")]

    

    f_parts = []

    _tls.last_file_name = valid_files[0].filename if valid_files else None

    _tls.current_session_id = sid

    for file in valid_files:

        b = await file.read()

        if b:

            f_parts.append((b, file.content_type, file.filename))



    kb_ctx = await KnowledgeBase.search_async(message, sid=sid, email=email)

    

    # Save user message WITH filename if applicable

    fname = valid_files[0].filename if valid_files else None

    await async_db("INSERT INTO m (sid,role,text,ts,user_email,fname) VALUES (?,?,?,?,?,?)",

       (sid, "user", message, time.time(), email, fname))



    # Upsert into sessions table

    if _PG_AVAILABLE:

        await async_db("INSERT INTO sessions (sid, title, user_email, updated_at) VALUES (?, 'New Study', ?, ?) "

           "ON CONFLICT (sid) DO UPDATE SET updated_at = EXCLUDED.updated_at",

           (sid, email, time.time()))

    else:

        await async_db("INSERT OR IGNORE INTO sessions (sid, title, user_email, created_at, updated_at) VALUES (?, 'New Study', ?, ?, ?)",

           (sid, email, time.time(), time.time()))

        await async_db("UPDATE sessions SET updated_at=? WHERE sid=?", (time.time(), sid))



    # â”€â”€ Security Guard: Verify session ownership before any data access â”€â”€â”€â”€â”€â”€â”€

    _verify_session_owner(sid, email)



    # â”€â”€ Document generation path (Gemini JSON  ->  HvielDocEngine file) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    file_type = hviel_engine._detect_type(message) if hviel_engine else None

    if file_type:

        try:

            hist_rows = db("SELECT role, text FROM m WHERE sid=? AND user_email=? ORDER BY id DESC LIMIT 10", (sid, email))

            history   = list(reversed([{"role": r, "text": t} for r, t in hist_rows]))



            # Run blocking Gemini call + file I/O in a thread so we don't block the event loop

            def _build_file():

                raw_json = assistant.generate_document_json(

                    file_type, message, history, kb_ctx, engineer

                )

                return hviel_engine.build_from_json(raw_json, file_type, engineer=engineer)



            filepath = await asyncio.get_running_loop().run_in_executor(None, _build_file)

            basename = os.path.basename(filepath)

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

            reply = (

                f" Document generation failed: {str(e)[:300]}. "

                f"Please retry or contact PRC support."

            )

            await async_db("INSERT INTO m (sid,role,text,ts,user_email) VALUES (?,?,?,?,?)",

               (sid, "model", reply, time.time(), email))

            return {"status": "error", "session_id": sid, "reply": reply}



    # â”€â”€ Standard chat path (Gemini with file analysis) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    hist_rows = db("SELECT role, text FROM m WHERE sid=? AND user_email=? ORDER BY id DESC LIMIT 10", (sid, email))

    history   = list(reversed([{"role": r, "text": t} for r, t in hist_rows]))



    # Run blocking Gemini call in a thread so we don't block the FastAPI event loop.
    # _post_kb captures _tls.pending_kb from INSIDE the executor thread where chat() runs,
    # because _tls is thread-local and invisible across thread boundaries.
    _post_kb: list = []

    def _chat_capture():
        result = assistant.chat(history, message, kb_ctx, f_parts, sid=sid, email=email)
        _post_kb.extend(getattr(_tls, 'pending_kb', []))
        return result

    try:
        resp = await asyncio.get_running_loop().run_in_executor(None, _chat_capture)
    except Exception as e:
        _logger.error(f"[Chat] Gemini/file processing error: {e}")
        reply = f"Processing error: {str(e)[:300]}. Please retry or contact PRC support."
        await async_db("INSERT INTO m (sid,role,text,ts,user_email) VALUES (?,?,?,?,?)",
           (sid, "model", reply, time.time(), email))
        return {"status": "error", "session_id": sid, "reply": reply}

    resp_text = resp if isinstance(resp, str) else str(resp) if resp is not None else ""
    await async_db("INSERT INTO m (sid,role,text,ts,user_email) VALUES (?,?,?,?,?)",

       (sid, "model", resp_text, time.time(), email))



    if _post_kb:

        background_tasks.add_task(KnowledgeBase.ingest_transactional, "SCAL Upload", _post_kb, sid=sid, email=email)



    return {"status": "success", "session_id": sid, "reply": resp_text}





# Resolved once at startup; files are written to CWD by HvielDocEngine(output_dir=".")

import pathlib as _pathlib

_DOWNLOAD_ROOT = _pathlib.Path(".").resolve()



@app.get("/api/download/{filename:path}")

async def dl(filename: str):

    target = (_DOWNLOAD_ROOT / _pathlib.Path(filename).name).resolve()

    if not str(target).startswith(str(_DOWNLOAD_ROOT)):

        raise HTTPException(status_code=403, detail="Access denied")

    if not target.is_file():

        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(str(target))





@app.post("/api/report/generate")

async def generate_report(

    session_id: str = Form(...),

    well_name:  str = Form("UNKNOWN WELL"),

):

    try:

        filename = PRCReportEngine().generate(session_id, well_name)

        return {"status": "success", "download_url": f"/api/report/download/{filename}"}

    except Exception as e:

        _logger.error(f"[Report] {e}")

        raise HTTPException(status_code=500, detail=str(e))





@app.get("/api/report/download/{filename}")

async def download_report(filename: str):

    # Serve from the reports/ subdirectory with path-containment guard (CWE-22)

    reports_root = _pathlib.Path(os.getcwd()) / "reports"

    target = (reports_root / _pathlib.Path(filename).name).resolve()

    if not str(target).startswith(str(reports_root.resolve())):

        raise HTTPException(status_code=403, detail="Access denied")

    if not target.is_file():

        raise HTTPException(status_code=404, detail="Report not found")

    return FileResponse(str(target), filename=_pathlib.Path(filename).name)





# â”€â”€ FRONTEND SERVING (SPA) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

_DIST_DIR = os.path.join(os.path.dirname(__file__), "frontend", "dist")

# Resolved once at startup; used by serve_spa to enforce path containment (CWE-22)

_DIST_DIR_PATH = _pathlib.Path(_DIST_DIR).resolve()



if os.path.exists(_DIST_DIR):

    app.mount("/assets", StaticFiles(directory=os.path.join(_DIST_DIR, "assets")), name="assets")



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



    index_html = _DIST_DIR_PATH / "index.html"

    if index_html.exists():

        return FileResponse(str(index_html))



    return {"error": "Frontend build not found. Run 'npm run build' in frontend directory."}



if __name__ == "__main__":

    import uvicorn

    init_db()

    uvicorn.run(app, host="0.0.0.0", port=8000)


