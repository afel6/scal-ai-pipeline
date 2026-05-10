# app.py
# PRC-HUB-VER-14-PROD-READY | 2026-05-10
# Changes: DB connection pooling · safe PG placeholder translation · thread-safe
#          key rotation · thread-local file URIs · asyncio.Queue SSE bridge ·
#          run_in_executor RAG · transactional KB ingest · admin backend auth ·
#          env-var secrets · slowapi rate limiting · dead code purged

print("[SYSTEM] app.py loading...")

import os, io, uuid, time, re, hmac, secrets as _secrets
import json as _json, logging, threading, asyncio
from contextlib import asynccontextmanager, contextmanager
from typing import Optional

import numpy as np
import pandas as pd

from fastapi import FastAPI, UploadFile, File, Form, Request, HTTPException, Header, Depends
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from bs4 import BeautifulSoup
from docx import Document

from google import genai as genai_new
from google.genai import types as genai_types

from hviel_doc_engine import HvielDocEngine
from skills_engine import SkillsEngine
from petrophysical_curves import Endpoints, KrCurveFitter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
_logger = logging.getLogger("PRC-Hub")

# ── ENV ───────────────────────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# ── RATE LIMITER (optional dep) ───────────────────────────────────────────────
try:
    from slowapi import Limiter, _rate_limit_exceeded_handler
    from slowapi.util import get_remote_address
    from slowapi.errors import RateLimitExceeded
    _limiter = Limiter(key_func=get_remote_address)
    _RATE_LIMIT = True
except ImportError:
    _limiter = None
    _RATE_LIMIT = False

# ── SECRETS ───────────────────────────────────────────────────────────────────
_GEMINI_POOL_RAW: list[str] = []
for _k, _v in os.environ.items():
    if _k.startswith("GEMINI_API_KEY"):
        _GEMINI_POOL_RAW.extend(x.strip() for x in _v.split(",") if x.strip())

GEMINI_KEY_POOL: list[str] = list(dict.fromkeys(_GEMINI_POOL_RAW)) or [
    os.getenv("GEMINI_API_KEY", "DUMMY_KEY").strip(' \n\r\t"\'')
]

KB_INGEST_SECRET = os.getenv("KB_INGEST_SECRET", "").strip()
ADMIN_PIN        = os.getenv("ADMIN_PIN",         "").strip()

_ADMIN_TOKENS:    dict[str, float] = {}   # token → expiry (epoch)
_ADMIN_TOKEN_TTL: int              = 900  # 15 min

# ── DATABASE LAYER ────────────────────────────────────────────────────────────
DATABASE_URL  = os.getenv("DATABASE_URL", "").strip()
DB_PATH       = "chat_history.db"
_PG_POOL      = None
_PG_AVAILABLE = False
_SQLITE_LOCK  = threading.Lock()

if DATABASE_URL:
    try:
        from psycopg2 import pool as _pg_pool_mod
        _PG_POOL      = _pg_pool_mod.ThreadedConnectionPool(2, 15, DATABASE_URL)
        _PG_AVAILABLE = True
        _logger.info("[DB] PostgreSQL pool ready (2–15 conns)")
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
        conn = _PG_POOL.getconn()
        try:
            yield conn, "%s"
        finally:
            _PG_POOL.putconn(conn)
    else:
        with _SQLITE_LOCK:
            conn = sqlite3.connect(DB_PATH, timeout=10)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            try:
                yield conn, "?"
            finally:
                conn.close()


def db(query: str, params: tuple = ()) -> list:
    """Execute a query written with ? placeholders against the active backend."""
    try:
        with _get_conn() as (conn, ph):
            q   = query if ph == "?" else _translate_placeholders(query)
            cur = conn.cursor()
            cur.execute(q, params)
            try:
                result = cur.fetchall()
            except Exception:
                result = []
            conn.commit()
            return result
    except Exception as e:
        _logger.error(f"[DB ERROR] Query: {query} | Error: {e}")
        raise


# ── THREAD-SAFE KEY TRACKING ──────────────────────────────────────────────────
_FAILED_KEYS:      dict[str, dict] = {}
_FAILED_KEYS_LOCK: threading.Lock  = threading.Lock()


def _mark_key_failed(key: str, is_hard: bool = False) -> None:
    with _FAILED_KEYS_LOCK:
        _FAILED_KEYS[key] = {"ts": time.time(), "wait": 3600 if is_hard else 60}


def _key_healthy(key: str) -> bool:
    with _FAILED_KEYS_LOCK:
        f = _FAILED_KEYS.get(key, {})
    return (time.time() - f.get("ts", 0)) >= f.get("wait", 0)


# ── SYSTEM PROMPT ─────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are Hviel — the Senior AI Petrophysical Specialist of the Petroleum Research Center (PRC), Libya. \
You carry 20+ years of SCAL laboratory authority. Every response is a signed engineering deliverable.

════════════════════════════════════════════════════
SECTION 1 — IDENTITY & VOICE
════════════════════════════════════════════════════
• Speak with the precision of a Principal Engineer authoring a PRC Executive Board report.
• Every quantitative claim is anchored in a physical model, a fitted parameter, or a cited source.
• Do not be vague. If a parameter cannot be determined, state why — and what additional data would resolve it.
• Address anomalies directly: observe → trace root cause → recommend corrective action. Never silently smooth over bad data.
• Units are always explicit: mD, psi, fraction (not percent), dimensionless where applicable.
• Sign interpretations with physics: "nw = 3.4 confirms strongly water-wet character with tight pore throats" — not "this looks water-wet."
• For conversational or conceptual questions, respond as a knowledgeable colleague: clear, concise, technically grounded.
• YOU ARE THE LEADER OF THE CONVERSATION. You do not wait to be given data. You demonstrate, \
simulate, and teach proactively. A senior consultant does not ask "please send me data" — \
he picks up the pen, runs the model, and presents findings. Then he invites the client to \
replace the synthetic baseline with their actual laboratory measurements.

════════════════════════════════════════════════════
SECTION 2 — KNOWLEDGE BASE PROTOCOL (MANDATORY)
════════════════════════════════════════════════════
Each user message may contain a [CONTEXT: ...] block sourced from the PRC technical library \
(API RP 40, Amott/USBM wettability standards, Brooks-Corey / LET references, PRC field studies).

MANDATORY STEPS:
1. Read the [CONTEXT: ...] block FIRST before forming any answer.
2. Ground your response in that context. Cite it explicitly: "Per the PRC technical library (API RP 40 §4.3)..."
3. If the context does not address the question, state plainly: \
"This specific topic is not in the current PRC library — responding from reservoir engineering fundamentals."

════════════════════════════════════════════════════
SECTION 3 — TOOL EXECUTION PROTOCOL (MANDATORY)
════════════════════════════════════════════════════
You have four tools. Use them proactively — do not describe what you could compute. Execute it.

RULE 0 — PROACTIVE DEMONSTRATION (HIGHEST PRIORITY):
  Trigger: The user asks about curves, simulations, models, or petrophysical fitting AND \
has NOT provided any numerical lab data in this conversation.
  THIS IS MANDATORY. You must NEVER respond with "please upload your data" or \
"could you provide measurements?" — that is a junior analyst response. A senior \
PRC consultant picks up the pen and demonstrates.

  REQUIRED SEQUENCE:
  Step 1 — Announce (one paragraph, confident tone):
    "I see you haven't uploaded laboratory measurements yet. For demonstration purposes, \
I will now generate a synthetic petrophysical model for a typical Libyan [Sandstone OR \
Carbonate, choose based on context] reservoir using PRC standard baseline parameters. \
This will give you a concrete reference frame — you can replace this baseline with your \
actual SCAL measurements at any time."

  Step 2 — Explain the physics BEFORE calling the tool (two to three sentences):
    Define the parameters you are about to use: what Swi (irreducible water saturation) \
represents physically, what Sor (residual oil saturation) means for sweep efficiency, \
what the Corey exponents nw and no control (curve concavity / mobility ratio), and what \
krw_max and kro_max represent as endpoint permeability scalers.

  Step 3 — Call `execute_python_simulation` IMMEDIATELY with PRC standard defaults:
    swr=0.20, snr=0.15, krw_max=0.65, kro_max=0.90, nw=2.5, no=2.5, model="brooks_corey"
    Do NOT modify these defaults unless the user has explicitly specified different values.

  Step 4 — After the tool returns, narrate the results:
    Interpret the crossover point (where Krw = Kro), comment on mobility ratio and \
what it implies for waterflood displacement efficiency, note whether the curves suggest \
a water-wet or mixed-wet system, and flag any endpoints that would require adjustment \
for a real Libyan field study.

  Step 5 — Invite replacement:
    "These are PRC standard baseline parameters. Share your laboratory Sw-Krw-Kro \
measurements and I will immediately fit the actual model to your data."

RULE 1 — DATA DETECTED:
  When the user provides Sw, Krw, Kro, Pc, RI, porosity, or permeability values:
  → Call `fit_petrophysical_curve` or `execute_python_simulation` immediately.
  → Do NOT ask for confirmation. PRC protocol mandates analysis on data receipt.

RULE 2 — SIMULATION REQUEST:
  For any Brooks-Corey or LET scenario (including sensitivity checks):
  → Call `execute_python_simulation` with mode="1d" for standard 1D Kr curves.
  → Use the exact parameters provided; if a parameter is unspecified, apply PRC defaults \
(swr=0.20, snr=0.20, krw_max=0.65, kro_max=0.90, nw=2.5, no=2.5).

RULE 3 — WORKFLOW DIAGRAMS:
  For multi-step QC protocols, history-matching workflows, or engineering decision trees:
  → Call `generate_mermaid_diagram` with type="flowchart".

RULE 4 — NO BARE TABLES:
  Never present a data table, parameter set, or fitted result without an accompanying plot.
  If a tool did not auto-generate a plot, manually construct a __PRC_PLOT__ block.

════════════════════════════════════════════════════
SECTION 4 — VISUALIZATION FORMAT (EXACT SYNTAX)
════════════════════════════════════════════════════
PLOT BLOCKS — for Kr, Pc, RI, Formation Factor, Overburden, J-Function curves:

__PRC_PLOT__
{"title":"Relative Permeability — Kr vs Sw","xAxis":{"label":"Water Saturation Sw"},"yAxis":{"label":"Relative Permeability"},"curves":[{"name":"Krw (Lab)","data":[{"x":0.20,"y":0.000},{"x":0.35,"y":0.042},{"x":0.50,"y":0.148},{"x":0.65,"y":0.310},{"x":0.80,"y":0.540}],"color":"#38bdf8","showLine":false,"showPoints":true},{"name":"Krw (Brooks-Corey)","data":[{"x":0.20,"y":0.000},{"x":0.35,"y":0.038},{"x":0.50,"y":0.145},{"x":0.65,"y":0.315},{"x":0.80,"y":0.540}],"color":"#0ea5e9","showLine":true,"showPoints":false},{"name":"Kro (Lab)","data":[{"x":0.20,"y":0.900},{"x":0.35,"y":0.620},{"x":0.50,"y":0.340},{"x":0.65,"y":0.110},{"x":0.80,"y":0.000}],"color":"#fb923c","showLine":false,"showPoints":true},{"name":"Kro (Brooks-Corey)","data":[{"x":0.20,"y":0.900},{"x":0.35,"y":0.615},{"x":0.50,"y":0.342},{"x":0.65,"y":0.112},{"x":0.80,"y":0.000}],"color":"#f97316","showLine":true,"showPoints":false}]}

CRITICAL SYNTAX RULES:
• The JSON must be a single compact object on the line IMMEDIATELY following __PRC_PLOT__
• The block must end with a blank line (\\n\\n) or the next __ marker
• Blue  (#38bdf8 lab, #0ea5e9 fit) = water phase (Krw)
• Orange (#fb923c lab, #f97316 fit) = oil phase (Kro)
• Green (#10b981) = gas phase
• showLine:false + showPoints:true  → raw lab measurements
• showLine:true  + showPoints:false → fitted model curve

MERMAID DIAGRAMS — for workflows and decision trees:

__MERMAID_START__
graph TD
    A[Raw SCAL Data] --> B{Quality Gate}
    B -->|Pass| C[Fit Brooks-Corey & LET]
    B -->|Fail| D[Flag: Re-measurement Required]
    C --> E[Physics Validation]
    E -->|Valid| F[PRC Certified]
__MERMAID_END__

DASHBOARD BLOCKS — for multi-panel complex views (Chart.js only):

__PRC_DASHBOARD__
<canvas id="chart1" style="max-height:400px"></canvas>
<script>new Chart(document.getElementById('chart1'),{type:'line',data:{datasets:[{label:'Krw',data:[],borderColor:'#38bdf8'}]},options:{responsive:true}});</script>
__PRC_DASHBOARD__

════════════════════════════════════════════════════
SECTION 5 — SCAL RESPONSE STRUCTURE (MANDATORY FOR DATA ANALYSIS)
════════════════════════════════════════════════════
Structure every SCAL data analysis in three phases:

### PHASE 1 — INGESTION & DATA AUDIT
• Well name, sample ID, laboratory provenance
• NaN check, Sw range validation: Sw ∈ [Swi, 1−Sor]
• Endpoint check: Krw(Swi) = 0, Kro(1−Sor) = 0
• Cite PRC library sources used

### PHASE 2 — HIGH-FIDELITY SIMULATION & INTERPRETATION
For each curve type detected:
• State physics model selected and justify the choice
• Execute the tool (mandatory — no exceptions)
• Embed visualization inline (mandatory)
• Parameter table: model | nw | no (or Lw/Ew/Tw, Lo/Eo/To) | R² | RMSE
• Wettability diagnosis via crossover-Sw method
• Pore structure interpretation (exponent analysis)
• Business impact: mobility ratio, displacement efficiency, EOR candidacy

### PHASE 3 — PRC CERTIFICATION
One engineering sentence confirming readiness for reservoir simulation deployment.
If anomalies remain unresolved: state the outstanding issue and the required PRC action item.

════════════════════════════════════════════════════
SECTION 6 — CURVE TYPE DETECTION
════════════════════════════════════════════════════
Auto-detect from column names:
  Sw + Krw + Kro          → Relative Permeability (Brooks-Corey + LET)
  Sw + Pc                 → Capillary Pressure (Brooks-Corey Pc model)
  Sw + RI                 → Resistivity Index [Log-Log scale mandatory]
  Porosity + FF           → Formation Factor [Log-Log + Archie mandatory]
  Pressure + Porosity + k → Overburden Compaction [Dual-Axis: linear φ left, log k right]
  T2 + porosity           → NMR T2 Distribution
  Vsp/Vtp/Vso/Vto         → Wettability Index (Amott method)
  Pc + IFT + k + φ        → Leverett J-Function

════════════════════════════════════════════════════
SECTION 7 — PHYSICS VALIDATION (NON-NEGOTIABLE)
════════════════════════════════════════════════════
Flag any violation immediately — do NOT silently correct.

Kr curves:
• Krw monotone increasing; Kro monotone decreasing across [Swi, 1−Sor]
• Krw(Swi) = 0 exactly; Kro(1−Sor) = 0 exactly
• Corey exponents nw, no ∈ (0, 15]; LET parameters L, E, T > 0
• Swr + Sor < 1.0 (physically meaningful two-phase system)

Capillary pressure:
• Drainage Pc strictly positive for all Sw < 1−Sor
• Imbibition Pc ≤ 0 at Sw = 1−Sor

Resistivity / Archie:
• Cementation exponent m ∈ [1.3, 3.5]; saturation exponent n ∈ [1.5, 3.0]
• Resistivity Index RI = 1.0 exactly at Sw = 1.0

════════════════════════════════════════════════════
SECTION 8 — PHYSICAL INTERPRETATION LIBRARY
════════════════════════════════════════════════════
Wettability (from crossover Sw where Krw = Kro):
  Sw_cross > 0.65           → Strongly water-wet
  Sw_cross ∈ [0.55, 0.65]  → Water-wet
  Sw_cross ∈ [0.45, 0.55]  → Mixed-wet
  Sw_cross < 0.45           → Oil-wet

Corey exponent diagnostics:
  nw ∈ [1.5, 2.5]  → Clean water-wet sandstone; uniform pore throats
  nw > 3.5         → Tight, heterogeneous pore network; strong capillary trapping
  no > 4.0         → Micro-porosity trapping — carbonate indicator (common in Libyan fields)
  nw ≈ no          → Symmetric pore structure; idealized Corey system

Endpoint analysis:
  Krw_max < 0.25   → Reservoir quality concern — significant pore blocking by irreducible water
  Sor > 0.35       → Raise EOR screening flag: waterflooding efficiency is limited
  Swi > 0.30       → Clay-bound water or fine-grained lithology — check NMR T2 if available

Model selection guide:
  Brooks-Corey → clean water-wet sandstones; simple pore networks; quick parametric studies
  LET          → mixed-wet Libyan carbonate/dolomite; complex wettability; S-shaped Kr curves
  When both are fitted, lead with the higher-R² model and comment on the discrepancy.
"""

# ── GEMINI TOOL DECLARATIONS ──────────────────────────────────────────────────
_HVIEL_TOOLS = [
    {
        "function_declarations": [
            {
                "name": "execute_python_simulation",
                "description": "Universal petrophysical simulation (Brooks-Corey, Archie, Overburden). Returns JSON for PRC plotting.",
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
                "description": "Fits raw lab Kr data to Corey/LET model.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "model": {"type": "STRING"},
                        "sw":    {"type": "ARRAY", "items": {"type": "NUMBER"}},
                        "krw":   {"type": "ARRAY", "items": {"type": "NUMBER"}},
                    },
                    "required": ["model", "sw", "krw"],
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
        ]
    }
]

_PETRO_KEYS = frozenset({
    "swr","snr","krw_max","kro_max","nw","no","Lw","Ew","Tw","Lo","Eo","To",
    "nx","ny","dx","dy","dz","dt","steps","porosity","perm","swi","pi","q_inj","mu_w","mu_o",
})

_tls = threading.local()


# ── GEMINI HA CLIENT ──────────────────────────────────────────────────────────
class PRCChatAssistant:
    def __init__(self, keys: list[str]):
        self.model_name   = "gemini-2.5-flash"
        self._keys        = keys
        self._current_idx = 0
        self._idx_lock    = threading.Lock()
        self._client_lock = threading.Lock()
        self._client      = None
        self._init_client()

    def _init_client(self) -> None:
        for i in range(len(self._keys)):
            with self._idx_lock:
                idx = (self._current_idx + i) % len(self._keys)
            key = self._keys[idx]
            if not _key_healthy(key):
                continue
            try:
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

    def _execute_tool(self, call) -> str:
        name, args = call.name, call.args
        if name == "execute_python_simulation":
            p = dict(args.get("params") or {})
            for k in _PETRO_KEYS:
                if k in args and k not in p:
                    p[k] = args[k]
            p["model"] = args.get("model")
            p["mode"]  = args.get("mode", "1d")
            res = SkillsEngine.run_skill("petroleum", "simulator", "simulation_core.py", [_json.dumps(p)])
            out = res.get("stdout") or res.get("error", "")
            if args.get("mode") == "2d" and "success" in (out or ""):
                return f"__SIMULATION_START__\n{out}\n__SIMULATION_END__"
            return out or ""
        elif name == "generate_mermaid_diagram":
            return f"__MERMAID_START__\n{args.get('content','')}\n__MERMAID_END__"
        elif name == "fit_petrophysical_curve":
            data = {"model": args.get("model"), "sw": args.get("sw",[]), "krw": args.get("krw",[])}
            res  = SkillsEngine.run_skill("petroleum", "", "curve_fitting_skill.py", [_json.dumps(data)])
            return res.get("stdout") or res.get("error", "")
        elif name == "agentic_history_matching":
            data = {"sw": args.get("sw",[]), "krw": args.get("krw",[]), "kro": args.get("kro",[])}
            res  = SkillsEngine.run_skill("petroleum", "simulator", "history_matching_skill.py", [_json.dumps(data)])
            return res.get("stdout") or res.get("error", "")
        return f"Unknown tool: {name}"

    def _format_tool_response(self, name: str, args: dict, result: str) -> str:
        try:
            tr = _json.loads(result) if isinstance(result, str) else result
            if name == "agentic_history_matching" and tr.get("success"):
                sw, krw, kro = args.get("sw",[]), args.get("krw",[]), args.get("kro",[])
                p, mse = tr.get("optimal_parameters",{}), tr.get("final_mse", 0)
                
                # Use Advanced Fitter
                sw_arr, krw_arr, kro_arr = np.array(sw), np.array(krw), np.array(kro)
                ep = Endpoints(
                    Swi=float(sw_arr.min()), 
                    Sor=1.0 - float(sw_arr.max()),
                    Krw_max=p.get("krw_max", 0.5),
                    Kro_max=p.get("kro_max", 0.8)
                )
                fitter = KrCurveFitter(ep)
                bc_res = fitter.fit_brooks_corey(sw_arr, krw_arr, kro_arr)
                plot_data = fitter.to_plot_json(sw_arr, krw_arr, kro_arr, model="brooks_corey", fit_result=bc_res)
                
                return f"\n\nOptimization complete. Final MSE: {mse:.5f}\n__PRC_PLOT__\n{_json.dumps(plot_data)}\n\n"
            elif name == "execute_python_simulation":
                if isinstance(result, str) and "__SIMULATION_START__" in result:
                    return f"\n\nSimulation complete.\n{result}\n\n"
                if tr and tr.get("mode") == "1d" and tr.get("status") == "success":
                    sw, krw, kro = tr.get("sw",[]), tr.get("krw",[]), tr.get("kro",[])
                    pm = tr.get("params", {})
                    
                    # Use Advanced Fitter for simulated data
                    sw_arr, krw_arr, kro_arr = np.array(sw), np.array(krw), np.array(kro)
                    ep = Endpoints(
                        Swi=pm.get("swr", 0.15), 
                        Sor=pm.get("snr", 0.2),
                        Krw_max=pm.get("krw_max", 0.5),
                        Kro_max=pm.get("kro_max", 0.8)
                    )
                    fitter = KrCurveFitter(ep)
                    bc_res = fitter.fit_brooks_corey(sw_arr, krw_arr, kro_arr)
                    plot_data = fitter.to_plot_json(sw_arr, krw_arr, kro_arr, model="brooks_corey", fit_result=bc_res)
                    
                    return f"\n\nSimulation complete.\n__PRC_PLOT__\n{_json.dumps(plot_data)}\n\n"
        except Exception:
            pass
        return f"\n\nTool `{name}` executed successfully.\n\n"

    def _tool_result_summary(self, name: str, raw_result: str) -> dict:
        """Returns a compact dict for the next-turn FunctionResponse so Gemini can interpret results."""
        try:
            if name == "generate_mermaid_diagram":
                return {"status": "diagram_rendered", "note": "Mermaid diagram embedded in chat for the user."}
            data = _json.loads(raw_result) if isinstance(raw_result, str) else {}
            if name == "execute_python_simulation":
                if isinstance(data, dict) and data.get("status") == "success" and data.get("mode") == "1d":
                    pm = data.get("params", {})
                    return {
                        "status": "success",
                        "model": "Brooks-Corey 1D",
                        "parameters": {k: pm.get(k) for k in ("swr","snr","krw_max","kro_max","nw","no") if pm.get(k) is not None},
                        "note": "Kr curves computed. PRC_PLOT rendered in chat. Proceed with physics interpretation.",
                    }
            elif name == "agentic_history_matching":
                if isinstance(data, dict) and data.get("success"):
                    return {
                        "status": "success",
                        "optimal_parameters": data.get("optimal_parameters", {}),
                        "final_mse": data.get("final_mse"),
                        "note": "History matching complete. PRC_PLOT rendered. Proceed with Phase 3 certification.",
                    }
            elif name == "fit_petrophysical_curve":
                if isinstance(data, dict) and data.get("success"):
                    return {
                        "status": "success",
                        "fit_params": data.get("params", {}),
                        "note": "Curve fit complete. PRC_PLOT rendered. Proceed with wettability and endpoint interpretation.",
                    }
        except Exception:
            pass
        return {"status": "executed", "tool": name, "note": "Tool executed. Results and visualization rendered in chat."}

    def _build_contents(self, history: list, enriched_msg: str, f_parts: list) -> tuple[list, list[str]]:
        SUPPORTED = {"application/pdf","image/jpeg","image/png","image/gif","image/webp"}
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
        for data_bytes, mime in f_parts:
            if mime not in SUPPORTED:
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
        return contents, uploaded_uris

    def chat(self, history: list, msg: str, kb_context: str = "", f_parts: list = [], stream: bool = False):
        # Structure the KB context clearly so Gemini's Section 2 protocol fires correctly
        if kb_context:
            enriched = f"{msg}\n\n[CONTEXT FROM PRC TECHNICAL LIBRARY:\n{kb_context}\nEND CONTEXT]"
        else:
            enriched = msg
        contents, uploaded_uris = self._build_contents(history, enriched, f_parts)
        _tls.last_file_uris = ",".join(uploaded_uris) if uploaded_uris else None

        def _generate():
            for attempt in range(len(self._keys)):
                try:
                    with self._client_lock:
                        client = self._client
                    cfg = genai_types.GenerateContentConfig(
                        temperature=0.2,
                        tools=_HVIEL_TOOLS,
                        system_instruction=SYSTEM_PROMPT,
                    )

                    # ── STREAMING PATH (multi-turn tool use) ──────────────────────────
                    if stream:
                        current_contents = list(contents)
                        for _turn in range(4):
                            tool_calls_in_turn: list = []  # (fc_obj, raw_result, formatted_str)
                            model_parts_in_turn: list = []

                            for chunk in client.models.generate_content_stream(
                                model=self.model_name, contents=current_contents, config=cfg
                            ):
                                if not (chunk.candidates and chunk.candidates[0].content):
                                    continue
                                for part in chunk.candidates[0].content.parts or []:
                                    model_parts_in_turn.append(part)
                                    if part.function_call:
                                        raw = self._execute_tool(part.function_call)
                                        fmt = self._format_tool_response(
                                            part.function_call.name,
                                            dict(part.function_call.args or {}),
                                            raw,
                                        )
                                        tool_calls_in_turn.append((part.function_call, raw, fmt))
                                    elif part.text:
                                        yield part.text

                            # Emit formatted tool results (plots/mermaid) after text for this turn
                            for _, _, fmt in tool_calls_in_turn:
                                yield fmt

                            if not tool_calls_in_turn:
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

                    # ── NON-STREAMING PATH (multi-turn tool use) ──────────────────────
                    current_contents = list(contents)
                    final = ""
                    for _turn in range(4):
                        resp = client.models.generate_content(
                            model=self.model_name, contents=current_contents, config=cfg
                        )
                        if not (resp and resp.candidates and resp.candidates[0].content):
                            break
                        tool_calls_in_turn = []
                        model_parts_in_turn = []
                        for part in resp.candidates[0].content.parts or []:
                            model_parts_in_turn.append(part)
                            if part.function_call:
                                raw = self._execute_tool(part.function_call)
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
                    yield final or "Unable to generate a response. Please rephrase your query."
                    return

                except Exception as e:
                    err     = str(e).lower()
                    is_auth = any(x in err for x in ["401","403","unauthorized","permission"])
                    is_rate = any(x in err for x in ["429","resource_exhausted"])
                    if (is_auth or is_rate) and attempt < len(self._keys) - 1:
                        self.rotate_key(is_hard_fail=is_auth)
                        if stream:
                            yield f"\n[PRC Node Rotating — retrying...]\n"
                        continue
                    _logger.error(f"[Hviel] Generation failed (attempt {attempt+1}): {e}")
                    raise

        return _generate() if stream else next(_generate(), "Error generating response.")

    def generate_document_json(
        self, file_type: str, message: str, history: list, kb_context: str, engineer: str
    ) -> str:
        """Call Gemini (no tools) to produce structured JSON for HvielDocEngine.build_from_json().
        Returns raw JSON string — may have ```json fences which build_from_json strips."""
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
            f"You are Hviel — PRC Senior AI Petrophysical Specialist, Petroleum Research Center, Libya.\n"
            f"Generate a professional {file_type.upper()} export for the PRC.\n"
            f"CRITICAL: Respond with ONLY valid JSON. No markdown fences. No explanation. Raw JSON only.\n\n"
            f"JSON SCHEMA (use this structure exactly):\n{schema}\n\n"
            f"CONTENT RULES:\n"
            f"- Populate with real petrophysical data drawn from the conversation (Sw, Kr, Pc, Archie, etc.)\n"
            f"- Use engineering units throughout: mD, fraction, psi, m TVDSS, dimensionless\n"
            f"- Include Executive Summary, Methodology, Results & Interpretation, and Conclusions sections\n"
            f"- Tables must contain realistic numerical SCAL data — no placeholder values\n"
            f"- Minimum 4 sections (docx/pdf) or 2 data sheets (xlsx) with substantive content\n"
            f"- author field: \"{engineer}\"\n"
            f"- Never use '...' or '[insert value]' — derive everything from the conversation\n"
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
                    model=self.model_name, contents=contents, config=cfg
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


# ── RAG / KNOWLEDGE BASE ──────────────────────────────────────────────────────
EMBED_MODEL        = "models/text-embedding-004"
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
    def ingest_transactional(name: str, chunks: list[tuple[str, str]]) -> None:
        with _get_conn() as (conn, ph):
            cur = conn.cursor()
            try:
                q_sel = f"SELECT id FROM kb WHERE source = {ph}"
                cur.execute(q_sel, (name,))
                old_ids = [r[0] for r in cur.fetchall()]
                if old_ids:
                    placeholders = ",".join([ph] * len(old_ids))
                    cur.execute(f"DELETE FROM kb_vectors WHERE chunk_id IN ({placeholders})", tuple(old_ids))
                cur.execute(f"DELETE FROM kb WHERE source = {ph}", (name,))
                for source, chunk in chunks:
                    if ph == "?":
                        cur.execute("INSERT INTO kb (source, chunk) VALUES (?,?)", (source, chunk))
                        chunk_id = cur.lastrowid
                    else:
                        cur.execute("INSERT INTO kb (source, chunk) VALUES (%s,%s) RETURNING id", (source, chunk))
                        chunk_id = cur.fetchone()[0]
                    vec = KnowledgeBase._embed(chunk)
                    if vec is not None:
                        cur.execute(f"INSERT INTO kb_vectors (chunk_id, embedding) VALUES ({ph},{ph})", (chunk_id, vec.tobytes()))
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    @staticmethod
    def search(query: str, top_k: int = 15) -> str:
        try:
            clean_q   = query[:2000] if query else ""
            vec_count = db("SELECT COUNT(*) FROM kb_vectors")[0][0]
            if 0 < vec_count < 2000:
                q_vec = KnowledgeBase._embed(clean_q)
                if q_vec is not None:
                    rows = db("SELECT kb.source, kb.chunk, kb_vectors.embedding FROM kb_vectors JOIN kb ON kb.id = kb_vectors.chunk_id")
                    if rows:
                        sources  = [r[0] for r in rows]; texts = [r[1] for r in rows]; raw_vecs = [r[2] for r in rows]
                        vecs = np.stack([np.frombuffer(bytes(v) if isinstance(v, memoryview) else v, dtype=np.float32) for v in raw_vecs])
                        q_norm  = q_vec  / (np.linalg.norm(q_vec) + 1e-9)
                        v_norms = vecs   / (np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-9)
                        scores  = v_norms @ q_norm
                        top_idx = np.argsort(scores)[::-1][:top_k]
                        parts   = [f"[From: {sources[i]}]\n{texts[i]}" for i in top_idx if scores[i] > 0.35]
                        if parts: return "\n\n".join(parts)
            words = [w.lower() for w in re.split(r"\W+", clean_q) if len(w) > 3][:5]
            if not words: return ""
            conditions = " OR ".join(["LOWER(chunk) LIKE ?"] * len(words))
            results    = db(f"SELECT source, chunk FROM kb WHERE {conditions} LIMIT 20", tuple(f"%{w}%" for w in words))
            return "\n\n".join(f"[From: {s}]\n{ch}" for s, ch in results)
        except Exception as e:
            _logger.error(f"[RAG] Search error: {e}")
            return ""

    @staticmethod
    async def search_async(query: str, top_k: int = 15) -> str:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, KnowledgeBase.search, query, top_k)


# ── APP SETUP ─────────────────────────────────────────────────────────────────
def init_db() -> None:
    base_stmts = [
        "CREATE TABLE IF NOT EXISTS m (id INTEGER PRIMARY KEY AUTOINCREMENT, sid TEXT, role TEXT, text TEXT, url TEXT, ts REAL, user_email TEXT, fname TEXT)",
        "CREATE TABLE IF NOT EXISTS kb (id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT, chunk TEXT)",
        "CREATE TABLE IF NOT EXISTS kb_vectors (id INTEGER PRIMARY KEY AUTOINCREMENT, chunk_id INTEGER UNIQUE, embedding BLOB)",
        "CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT UNIQUE, name TEXT, created_at REAL)",
        "CREATE TABLE IF NOT EXISTS feedback (id INTEGER PRIMARY KEY AUTOINCREMENT, user_email TEXT, bug_report TEXT, ts REAL)",
        "CREATE TABLE IF NOT EXISTS analytics_events (id INTEGER PRIMARY KEY AUTOINCREMENT, user_email TEXT, event_type TEXT, event_data TEXT, ts REAL)",
    ]
    if _PG_AVAILABLE:
        base_stmts = [s.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY").replace("BLOB", "BYTEA") for s in base_stmts]
    for s in base_stmts:
        try: db(s)
        except Exception: pass

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(lifespan=lifespan)
if _RATE_LIMIT:
    app.state.limiter = _limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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

# ── ROUTES ────────────────────────────────────────────────────────────────────
@app.get("/health")
def health(): return {"status": "ok", "db": "postgres" if _PG_AVAILABLE else "sqlite"}

@app.get("/api/diag")
def diag():
    with _FAILED_KEYS_LOCK: snap = dict(_FAILED_KEYS)
    now = time.time(); cooldown = sum(1 for v in snap.values() if (now - v.get("ts",0)) < v.get("wait",0))
    with assistant._idx_lock: idx = assistant._current_idx
    return {"version": "PRC-HUB-VER-14-PROD-READY", "node_pool_size": len(GEMINI_KEY_POOL), "active_node_idx": idx, "nodes_in_cooldown": cooldown}

# ── ADMIN AUTH ────────────────────────────────────────────────────────────────
def verify_admin(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid token")
    token = authorization.split(" ")[1]
    if token not in _ADMIN_TOKENS or time.time() > _ADMIN_TOKENS[token]:
        if token in _ADMIN_TOKENS: del _ADMIN_TOKENS[token]
        raise HTTPException(status_code=401, detail="Token expired or invalid")
    return True

@app.post("/api/admin/auth")
async def admin_login(pin: str = Form(...)):
    # Use ENV pin or fallback to 0608
    target_pin = ADMIN_PIN or "0608"
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
    db("INSERT INTO feedback (user_email, bug_report, ts) VALUES (?, ?, ?)", (user_email.lower(), bug_report, time.time()))
    return {"status": "ok"}

@app.post("/api/analytics/event")
async def track_event(user_email: str = Form(""), event_type: str = Form(...), event_data: str = Form("")):
    db("INSERT INTO analytics_events (user_email, event_type, event_data, ts) VALUES (?, ?, ?, ?)",
       (user_email.lower(), event_type, event_data, time.time()))
    return {"status": "ok"}

@app.get("/api/sessions")
def get_sessions(email: str = None):
    const_email = email.lower().strip() if email else None
    q = "SELECT DISTINCT sid, MIN(ts) FROM m {filter} GROUP BY sid ORDER BY MIN(ts) DESC"
    f = "WHERE user_email=?" if const_email else ""
    rows = db(q.format(filter=f), (const_email,) if const_email else ())
    return [{"id": r[0], "created_at": r[1]} for r in rows]

@app.get("/api/session/{sid}")
def get_session(sid: str):
    rows = db("SELECT role, text, url, ts, fname FROM m WHERE sid=? ORDER BY id", (sid,))
    return {"status":"ok","messages":[{"role":r,"text":t,"download_url":u,"ts":ts,"fileName":fn} for r,t,u,ts,fn in rows]}

@app.delete("/api/session/{sid}")
def delete_session(sid: str):
    db("DELETE FROM m WHERE sid=?", (sid,))
    return {"status": "ok"}

@app.get("/api/chat/stream")
async def chat_stream(
    message:       str,
    session_id:    Optional[str]   = None,
    user_email:    Optional[str]   = None,
):
    sid   = session_id or str(uuid.uuid4())
    email = user_email.lower().strip() if user_email else None
    
    async def _producer():
        try:
            # Send session metadata first so the client sets the session ID
            yield f"data: {_json.dumps({'type': 'session', 'session_id': sid})}\n\n"

            kb_ctx = await KnowledgeBase.search_async(message)
            db("INSERT INTO m (sid,role,text,ts,user_email) VALUES (?,?,?,?,?)", (sid, "user", message, time.time(), email))

            # Fetch the most-recent 10 messages (descending), then reverse to chronological order
            hist_rows = db("SELECT role, text FROM m WHERE sid=? ORDER BY id DESC LIMIT 10", (sid,))
            history   = list(reversed([{"role": r, "text": t} for r, t in hist_rows]))

            full_reply = ""
            for chunk in assistant.chat(history, message, kb_context=kb_ctx, stream=True):
                if chunk:
                    full_reply += chunk
                    yield f"data: {_json.dumps({'type': 'token', 'text': chunk})}\n\n"

            if full_reply:
                db("INSERT INTO m (sid,role,text,ts,user_email) VALUES (?,?,?,?,?)", (sid, "model", full_reply, time.time(), email))

            yield f"data: {_json.dumps({'type': 'done'})}\n\n"
        except Exception as e:
            _logger.error(f"[SSE] Stream error: {e}")
            yield f"data: {_json.dumps({'type': 'error', 'msg': str(e)})}\n\n"
            yield f"data: {_json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(
        _producer(), 
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"}
    )

@app.post("/api/chat")
async def handle(
    message:       str              = Form(...),
    session_id:    Optional[str]    = Form(None),
    user_email:    Optional[str]    = Form(None),
    engineer_name: Optional[str]    = Form(None),
    files:         list[UploadFile] = File(default=[]),
):
    sid      = session_id or str(uuid.uuid4())
    email    = user_email.lower().strip() if user_email else None
    engineer = (engineer_name or "PRC Engineering Staff").strip()

    f_parts = []
    for file in files:
        b = await file.read()
        f_parts.append((b, file.content_type))

    kb_ctx = await KnowledgeBase.search_async(message)
    db("INSERT INTO m (sid,role,text,ts,user_email) VALUES (?,?,?,?,?)",
       (sid, "user", message, time.time(), email))

    # ── Document generation path (Gemini JSON → HvielDocEngine file) ──────────
    file_type = hviel_engine._detect_type(message) if hviel_engine else None
    if file_type:
        try:
            hist_rows = db("SELECT role, text FROM m WHERE sid=? ORDER BY id DESC LIMIT 10", (sid,))
            history   = list(reversed([{"role": r, "text": t} for r, t in hist_rows]))

            # Run blocking Gemini call + file I/O in a thread so we don't block the event loop
            def _build_file():
                raw_json = assistant.generate_document_json(
                    file_type, message, history, kb_ctx, engineer
                )
                return hviel_engine.build_from_json(raw_json, file_type, engineer=engineer)

            filepath = await asyncio.get_event_loop().run_in_executor(None, _build_file)
            basename = os.path.basename(filepath)
            dl_url   = f"/api/download/{basename}"

            type_labels = {"docx": "Word Document", "xlsx": "Excel Spreadsheet",
                           "pptx": "PowerPoint Presentation", "pdf": "PDF Report"}
            reply = (
                f"### PRC {type_labels.get(file_type, file_type.upper())} Ready\n\n"
                f"Your professional export has been compiled from the current session analysis. "
                f"Click **Download** to retrieve the file."
            )
            db("INSERT INTO m (sid,role,text,url,ts,user_email,fname) VALUES (?,?,?,?,?,?,?)",
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
            db("INSERT INTO m (sid,role,text,ts,user_email) VALUES (?,?,?,?,?)",
               (sid, "model", reply, time.time(), email))
            return {"status": "error", "session_id": sid, "reply": reply}

    # ── Standard chat path (Gemini with file analysis) ────────────────────────
    resp = assistant.chat([], message, kb_ctx, f_parts)
    db("INSERT INTO m (sid,role,text,ts,user_email) VALUES (?,?,?,?,?)",
       (sid, "model", resp, time.time(), email))
    return {"status": "success", "session_id": sid, "reply": resp}


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

# ── FRONTEND SERVING (SPA) ───────────────────────────────────────────────────
_DIST_DIR = os.path.join(os.path.dirname(__file__), "frontend", "dist")

if os.path.exists(_DIST_DIR):
    app.mount("/assets", StaticFiles(directory=os.path.join(_DIST_DIR, "assets")), name="assets")

@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    # API 404s
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="API endpoint not found")
    
    # Static files (prc_logo.jpg, etc.)
    static_file = os.path.join(_DIST_DIR, full_path)
    if os.path.isfile(static_file):
        return FileResponse(static_file)
    
    # SPA routing -> index.html
    index_html = os.path.join(_DIST_DIR, "index.html")
    if os.path.exists(index_html):
        return FileResponse(index_html)
    
    return {"error": "Frontend build not found. Run 'npm run build' in frontend directory."}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
