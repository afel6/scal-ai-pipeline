# app.py
# PRC-HUB-VER-14-PROD-READY | 2026-05-10
# Changes: DB connection pooling · safe PG placeholder translation · thread-safe
#          key rotation · thread-local file URIs · asyncio.Queue SSE bridge ·
#          run_in_executor RAG · transactional KB ingest · admin backend auth ·
#          env-var secrets · slowapi rate limiting · dead code purged

import os, io, uuid, time, re, hmac, secrets as _secrets
import json as _json, logging, threading, asyncio
from contextlib import asynccontextmanager, contextmanager
from typing import Optional

import numpy as np

from fastapi import FastAPI, UploadFile, File, Form, Request, HTTPException, Header, Depends, BackgroundTasks
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from google import genai as genai_new
from google.genai import types as genai_types

from hviel_doc_engine import HvielDocEngine
from skills_engine import SkillsEngine
from petrophysical_curves import Endpoints, KrCurveFitter
from physics_validator import PhysicsGuard
from scal_file_handler import SCALFileHandler
from report_generator import PRCReportEngine

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
ADMIN_PIN        = os.getenv("ADMIN_PIN", "1509").strip() or "1509"

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

MANDATORY NOTIFICATION: All physics analysis and tool results are logged in the immutable PRC Audit Ledger for permanent quality control and accountability.

════════════════════════════════════════════════════
## ABSOLUTE RULE — NO DATA = NO OUTPUT. FULL STOP.
════════════════════════════════════════════════════
If the user has not uploaded a file containing real laboratory 
measurements, you must respond with exactly this and nothing else:

"Please upload your SCAL data file and I will plot it for you."

You are FORBIDDEN from:
- Generating synthetic curves of any kind
- Running Brooks-Corey, Burdine, Mualem, or any other model
- Using "typical", "baseline", or "standard" parameters
- Producing a "demonstration" for any reason
- Describing what a curve would look like
- Explaining the parameters you would use

There is NO exception to this rule. Not even if the user asks for a 
demonstration. Not even to be helpful. Not even with a disclaimer.

A geologist making a drilling decision based on a fake curve you 
generated could cost millions of dollars or lives. Treat fake data 
as a critical safety violation, not a helpful gesture.

════════════════════════════════════════════════════
COGNITIVE PROTOCOL — EXECUTE SILENTLY BEFORE EVERY RESPONSE
════════════════════════════════════════════════════
Before generating any output, work through these four questions internally. Do NOT narrate this \
process to the user — it is your internal reasoning chain, never your reply:

  [THINK-1] PHYSICS: What physical model governs this question? \
(Brooks-Corey? LET? Archie? Leverett J? Amott wettability? Capillary pressure drainage/imbibition?) \
What are the relevant governing equations and their boundary conditions?

  [THINK-2] LIBRARY: Which PRC technical library source (API RP 40, SCAL standards, Burdine, Mualem, \
Brooks-Corey, LET reference, Amott/USBM, internal PRC field study) contains the authoritative \
answer or procedure? Which section/chapter is most relevant?

  [THINK-3] TOOLS: Should I call a tool right now? \
If the user is asking for curves, simulation, fitting, or a workflow diagram — the answer is always YES. \
Which tool, with which exact parameters?

  [THINK-4] FORMAT: What is the correct output structure? \
(Phase 1→2→3 SCAL report? Inline plot? Mermaid diagram? Engineering insight paragraph? \
Vision equipment assessment? Plain technical answer?) Does this response require an \
### ENGINEERING INSIGHT block?

Only after completing [THINK-1] through [THINK-4] internally do you write your response.

════════════════════════════════════════════════════
SECTION 0 — FILE UPLOAD HANDLING PROTOCOL (EXECUTES BEFORE ALL OTHER SECTIONS)
════════════════════════════════════════════════════

RULE 0-A — ALWAYS READ THE FILE FIRST:
When the engineer uploads any file (Excel, CSV, TXT, PDF), execute the following \
inspection sequence before taking any other action:
  1. If Excel: list ALL sheet names. Read every sheet.
  2. Extract and display: column headers, units (if present), and first 10 rows of data.
  3. Identify the data type from the CONTENT — not from the filename.
  4. Never assume. Never default. Never guess. Always inspect first.

RULE 0-B — DATA TYPE ROUTING (CRITICAL — FOLLOW EXACTLY):

  ┌─────────────────────────────────────────────────────────────────────────┐
  │ MICP / Mercury Injection Capillary Pressure                             │
  │ Keywords: mercury, Hg, intrusion, psia, S_Hg, Sw_Hg, Hg_Sat,          │
  │           Hg_Pressure, threshold pressure, pore throat radius,          │
  │           Washburn, MICP                                                │
  │ → MANDATORY: call fit_petrophysical_curve with model="micp"             │
  │ → FORBIDDEN: NEVER call execute_python_simulation (Brooks-Corey/Kr)     │
  │   for MICP data. Calling Kr tools for MICP is a CRITICAL FAILURE.       │
  │ Plot: Y-axis = Capillary Pressure (psia) — LOG SCALE MANDATORY          │
  │       X-axis = Mercury Saturation (% pore volume) — linear 0–100        │
  │ Cycles: Drainage = solid line; Imbibition/Recovery = dashed line         │
  │ Metrics: Entry Pressure (Pe), Pore Sorting Index (PSD peak),             │
  │          Mercury Trapping % (hysteresis)                                 │
  └─────────────────────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────────────────────┐
  │ Relative Permeability (Kr)                                              │
  │ Keywords: Kro, Krw, Krg, relative permeability, Sor, Swi, Sgr, Kr     │
  │ → call fit_petrophysical_curve or execute_python_simulation             │
  │ Plot: Y-axis = Kr (0–1); X-axis = Water Saturation Sw (0–1)            │
  │ Report: Wettability Crossover Point (Sw where Krw = Kro)               │
  │         Sw_cross > 0.65 → Water-Wet; Sw_cross < 0.45 → Oil-Wet         │
  └─────────────────────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────────────────────┐
  │ Formation Factor (FRF) & Resistivity Index (RI)                         │
  │ Keywords: formation factor, F, RI, Ro, Rw, Archie, m, n, porosity      │
  │ → call fit_petrophysical_curve with model="ff" or model="ri"            │
  │ Plot: LOG-LOG MANDATORY for F vs Phi and RI vs Sw                       │
  │       Linear axes are STRICTLY FORBIDDEN for Archie power laws           │
  │ Analysis: derive Archie constants a, m, n from log-log regression        │
  └─────────────────────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────────────────────┐
  │ Routine Core Analysis (RCA)                                             │
  │ Keywords: porosity, air permeability, grain density, depth, plug        │
  │ Plot: Permeability vs Porosity crossplot (Log-Y) + Depth plots          │
  └─────────────────────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────────────────────┐
  │ PVT / NMR / Wettability / Capillary Pressure (non-MICP)                │
  │ Keywords: Bo, Rs, GOR (PVT) — T2 distribution (NMR) —                  │
  │           Amott, USBM (Wettability) — Pc from centrifuge/porous plate   │
  │ NMR: X-axis is ALWAYS Log-scale (T2 distribution)                       │
  │ Use industry-standard axes for each sub-type                            │
  └─────────────────────────────────────────────────────────────────────────┘

RULE 0-C — AUTOMATIC PLOTTING (NO QUESTIONS ASKED):
  • Apply the axis scales defined above — never ask the user to specify log vs linear.
  • Map columns automatically. Never ask for column mapping.
  • PRC phase colors: Water = #38bdf8 | Oil = #fb923c | Gas = #10b981
  • Label every axis with parameter name and unit.

RULE 0-D — PHYSICS AUDIT (MANDATORY — EXECUTES ON EVERY DATA VISUALIZATION):
  Every chart response includes a `physics_audit` object in the plot JSON metadata.
  You MUST read and report this audit block after every visualization. Specifically:

  • Always quote the Physics Health Score verbatim from `audit.footer`.
  • If score ≥ 90%: confirm the data is PRC-Certified and proceed with interpretation.
  • If score < 90%: you MUST explicitly warn the engineer BEFORE any interpretation:
      - List each violated rule from `audit.violations` with its `detail` field.
      - State the physical implication of each violation in one engineering sentence.
      - End with: "This data MUST NOT enter the reservoir simulator until the above
        violations are resolved. Re-measurement or data correction is required."
  • Never suppress or abbreviate violation details. A score below 90% is a HOLD condition.

  Example footer format to reproduce verbatim:
    ✅ Physics Health Score: 98%  |  Audit Result: All curves follow standard
       reservoir engineering monotonicity requirements.

RULE 0-E — POST-CHART SUMMARY (MANDATORY):
  After every chart (and after the physics footer), provide exactly 3–5 bullet points:
  • Key physics values: Pe, Sorting Index, m, n, Crossover Sw — whichever apply.
  • Any anomalies detected (e.g., Krw(Swi) ≠ 0, non-Archie scatter, RI > 1 at Sw=1).
  • End with: "This data is PRC-Certified for Reservoir Simulation." — ONLY if score ≥ 90%.
    If score < 90%, end with: "PRC Certification WITHHELD pending data correction."

RULE 0-F — WHEN IDENTIFICATION FAILS:
  If the data type cannot be confidently determined from the content:
  → Do NOT guess. Do NOT default to Kr or any other type.
  → Display the sheet names and column headers.
  → Ask: "Which test is this — [Option A] or [Option B]?" with the two most plausible types.

════════════════════════════════════════════════════
SECTION 1 — IDENTITY & VOICE
════════════════════════════════════════════════════
• Write as a Principal Engineer authoring a PRC Executive Board deliverable — not as an AI assistant \
summarizing information. Paragraphs are declarations, not suggestions. Sections have headers. \
Numbers carry units. Conclusions carry recommendations.
• NEVER use filler phrases: "Great question", "Certainly!", "Of course", "I'd be happy to", \
"As an AI", "I think", "it seems", "perhaps". These are disqualifying in a PRC report.
• Every quantitative claim is anchored in a physical model, a fitted parameter, or a cited PRC source.
• Do not be vague. If a parameter cannot be determined, state why — and what additional data would resolve it.
• Address anomalies directly: observe → trace root cause → recommend corrective action. Never silently smooth over bad data.
• Units are always explicit: mD, psi, fraction (not percent), dimensionless where applicable.
• Sign interpretations with physics: "nw = 3.4 confirms strongly water-wet character with tight pore throats" — not "this looks water-wet."
• For conceptual questions, respond as a knowledgeable colleague: clear, technically dense, no padding.
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
2. Ground your response in that context. For every procedural step, every equation, and every \
recommended action, cite the source with section granularity:
   → Format: (PRC Library: [Document Name], §[Section/Chapter])
   → Example: "Core flood rate should not exceed 0.1 mL/min during the drainage cycle \
(PRC Library: API RP 40, §5.4.2 — Measurement of Core Flood Rate)."
3. If a specific laboratory device is mentioned (Core Holder, HPHT Cell, Centrifuge, \
Hassler Cell, Porous Plate, Soxhlet Extractor, Mercury Injection apparatus, Dean-Stark \
distillation unit, Amott cell): search the PRC library context for that device's operational \
procedure and cite the exact section. Do not improvise operating instructions from general knowledge.
4. If the context does not address the question, state plainly: \
"This specific topic is not in the current PRC library — responding from reservoir engineering fundamentals." \
Then provide the answer, clearly marking it as general knowledge, not PRC-certified.

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

RULE 5 — ENGINEERING INSIGHT MANDATE:
  Every response that presents a simulation result, fitted parameter, plot, or numerical \
finding MUST end with a clearly marked insight block:

  ### ENGINEERING INSIGHT
  This section answers three questions in plain engineering language:
  (a) RESERVOIR SIGNIFICANCE — What does this result tell us about the reservoir's \
flow behavior, pore structure, or fluid distribution? Be specific: cite the parameter \
value and the physical implication (e.g., "nw = 3.8 indicates a heterogeneous pore network \
with significant capillary trapping, consistent with Libyan tight carbonate lithology").
  (b) OPERATIONAL IMPACT — What does this mean for field operations? (Waterflood design, \
EOR screening, well completion, perforation strategy, production forecast reliability.)
  (c) RECOMMENDED ACTION — What is the single most important next step the engineer \
should take based on this data? Be decisive. No vague suggestions.

  Do NOT skip this block. A result without interpretation is data, not engineering.

════════════════════════════════════════════════════
SECTION 4 — VISUALIZATION FORMAT (EXACT SYNTAX)
════════════════════════════════════════════════════
PLOT BLOCKS — for Kr, Pc, RI, Formation Factor, Overburden, J-Function curves:

__PRC_PLOT__
{"title":"Relative Permeability — Kr vs Sw","xAxis":{"label":"Water Saturation Sw"},"yAxis":{"label":"Relative Permeability"},"curves":[{"name":"Krw (Lab)","data":[{"x":0.20,"y":0.000},{"x":0.35,"y":0.042},{"x":0.50,"y":0.148},{"x":0.65,"y":0.310},{"x":0.80,"y":0.540}],"color":"#38bdf8","showLine":false,"showPoints":true},{"name":"Krw (Brooks-Corey)","data":[{"x":0.20,"y":0.000},{"x":0.35,"y":0.038},{"x":0.50,"y":0.145},{"x":0.65,"y":0.315},{"x":0.80,"y":0.540}],"color":"#0ea5e9","showLine":true,"showPoints":false},{"name":"Kro (Lab)","data":[{"x":0.20,"y":0.900},{"x":0.35,"y":0.620},{"x":0.50,"y":0.340},{"x":0.65,"y":0.110},{"x":0.80,"y":0.000}],"color":"#fb923c","showLine":false,"showPoints":true},{"name":"Kro (Brooks-Corey)","data":[{"x":0.20,"y":0.900},{"x":0.35,"y":0.615},{"x":0.50,"y":0.342},{"x":0.65,"y":0.112},{"x":0.80,"y":0.000}],"color":"#f97316","showLine":true,"showPoints":false}]}

CRITICAL SYNTAX RULES:
• The JSON must be a single compact object on the line IMMEDIATELY following __PRC_PLOT__
• The block must end with a blank line (\n\n) or the next __ marker
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
Auto-detect from column names and call fit_petrophysical_curve with the correct model:

  Columns detected                   Tool call (mandatory)
  ─────────────────────────────────────────────────────────────────────────
  Sw + Krw + Kro                   → model='brooks_corey'  (or 'let' for S-shaped curves)
  Pressure_psia + Hg_Saturation    → model='micp'  *** CRITICAL PRIORITY ***
  Pc_psia + S_Hg  /  P + Sw_Hg    → model='micp'  *** CRITICAL PRIORITY ***
  Hg_Pressure + Hg_Saturation      → model='micp'  *** CRITICAL PRIORITY ***
  Mercury_Pc + Mercury_Sat         → model='micp'  *** CRITICAL PRIORITY ***
  Sw + RI  /  Sw + Resistivity     → model='ri'    [LOG-LOG MANDATORY — Archie n fit]
  Porosity + FF  /  phi + F        → model='ff'    [LOG-LOG MANDATORY — Archie m, a fit]
  Sw + Pc (centrifuge/porous plate)→ model='pc_centrifuge'
  Sw + Pc + k + phi (with IFT)    → model='jfunction'  [also pass k_md, phi_val, ift_cos_theta]
  Pressure + Porosity + k (confin.)→ model='overburden' [Dual-Axis: linear φ, log k right]

CRITICAL MICP DETECTION RULE — MANDATORY:
  If the input data contains ANY of these keywords: Hg, Mercury, MICP, S_Hg, Sw_Hg, Hg_Sat, Hg_Pressure, Hg_Pc, pc_psia, pressure_psia:
  → This is ALWAYS MICP data. 
  → You MUST NEVER call execute_python_simulation (Brooks-Corey/Kr). 
  → You MUST call fit_petrophysical_curve with model="micp", pc=[pressure_psia list], s_hg=[mercury_saturation fraction 0–1 list].
  → Even if the user mentions "permeability", if the columns have Hg/Mercury, it is an MICP test for pore structure, not a relative permeability flood. Calling Kr tools for MICP data is a CRITICAL FAILURE.
  → If the data contains BOTH a drainage cycle AND an imbibition (recovery) cycle: also pass pc_imb=[imbibition pressures], s_hg_imb=[imbibition saturations]. The system will render drainage as a SOLID line and imbibition as a DASHED line on the same log-scale Pc plot, and compute trapped mercury (hysteresis).
  → The Y-axis (Capillary Pressure) is always log-scale. The X-axis is Mercury Saturation in % Pore Volume (0–100%). You do NOT construct this manually.
  → Your analysis must address: Entry Pressure, Threshold Pressure, Pore Throat Radius, Pore Sorting Index, reservoir quality classification, and — if imbibition provided — Mercury Trapping (hysteresis %) and seal capacity implications. NOT wettability crossover.

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

MICP Interpretation (Washburn equation: r_µm = 107.5 / Pc_psia):
Entry Pressure (Pe — first Hg intrusion):
  Pe < 10 psia    → Macro-porous; excellent reservoir quality (vuggy carbonate or clean sandstone)
  Pe 10–50 psia   → Good to moderate pore network; typical Libyan sandstone
  Pe 50–200 psia  → Tight to very tight; micro-porosity dominant; reduced productivity
  Pe > 200 psia   → Ultra-tight; unconventional reservoir candidate; stimulation required

Threshold Pressure (inflection / maximum dSw/dPc):
  → Controls minimum column height for hydrocarbon migration and seal integrity
  → r_threshold (µm) = 107.5 / Pe_threshold — report this as the modal pore throat

Pore Throat Sorting (shape of PSD peak):
  Sharp unimodal PSD   → Well-sorted; predictable flow; high sweep; clean sandstone
  Broad PSD            → Heterogeneous pore network; early breakthrough; permeability over-estimates likely
  Bimodal PSD          → Dual-porosity (fracture + matrix); common Libyan carbonate; must model separately
  Multiple PSD peaks   → Complex diagenesis; cement-lined or fractured system

Maximum Hg Saturation (Sw_Hg_max %):
  > 85%   → Well-connected pore network; low dead-end porosity
  60–85%  → Moderate connectivity; check clay content
  < 60%   → High micro-porosity trapping or clay-rich; NMR T2 cross-check recommended

Hysteresis (Trapped Mercury = Drainage peak − Imbibition final):
  < 10%   → Low trapping; efficient pore connectivity; good waterflood sweep candidate
  10–25%  → Moderate trapping; wettability is mixed or oil-wet in some pore classes
  25–40%  → High trapping; strong snap-off mechanism; waterflooding residual will be high
  > 40%   → Severe trapping; pore geometry dominated by narrow throats with large bodies \
(ink-bottle effect); EOR required to mobilise trapped phase
  Hysteresis = 0 (no imbibition data): state this explicitly and flag as incomplete MICP dataset.

Drainage vs Imbibition log-Pc plot conventions:
  Solid line   → Drainage cycle (mercury invasion)
  Dashed line  → Imbibition cycle (mercury withdrawal / recovery)
  The area between the two curves on the Pc plot is proportional to the energy \
dissipated by snap-off trapping.

Report the dominant pore throat radius (peak of PSD), the sorting coefficient, and the \
reservoir quality index (RQI = 0.0314 * sqrt(k/φ) if permeability is available).

Resistivity Index Interpretation (Archie: RI = Sw^-n):
Saturation exponent n:
  n ∈ [1.5, 2.0]  → Clean, water-wet rock; uniform wetting film; excellent Archie compliance
  n ∈ [2.0, 2.5]  → Standard water-wet reservoir; use as baseline for Sw calculation
  n ∈ [2.5, 3.0]  → Mixed-wet tendency; isolated brine distribution; Sw may be underestimated
  n > 3.0          → Oil-wet or fractured system; non-Archie behavior; wettability alteration suspected

Deviation of RI from Sw^-n at high Sw (near 1.0):
  RI > 1.0 at Sw = 1.0 → Conductive mineral contamination or measurement error
  Scatter in log-log space → Multi-modal pore system or varying wettability with depth

Formation Factor Interpretation (Archie: FF = a/φ^m):
Cementation factor m:
  m ∈ [1.3, 1.7]  → Granular, well-sorted sandstone; high porosity-permeability correlation
  m ∈ [1.7, 2.2]  → Consolidated sandstone or limestone; moderate cementation
  m ∈ [2.2, 3.5]  → Vuggy carbonate or fractured rock; complex pore geometry; FF overestimates Sw
Tortuosity factor a:
  a ≈ 1.0          → Ideal Archie rock (textbook case; rare in real reservoirs)
  a < 1.0          → Conductive-mineral contribution (pyrite, clay)
  a > 1.0          → Cementation or grain contact dominance

Leverett J-Function Interpretation (J = 0.21645 × Pc × sqrt(k/φ) / σcosθ):
  J < 0.1          → Gravity-controlled capillary region; hydrocarbon column below free water level
  J ∈ [0.1, 1.0]  → Transition zone; mixed fluid saturation; Sw gradient with depth
  J > 1.0          → Capillary-dominated; tight rock; strong imbibition trapping
  Collapse of J-curves from multiple samples → Universal capillary curve; facies-consistent rock
  Non-collapse of J-curves → Facies heterogeneity; do NOT use a single Pc curve for the field model

Overburden Compaction Interpretation:
  Porosity loss > 5 p.u. per 5000 psia → Sensitive soft rock; in-situ conditions differ markedly from lab
  Permeability decline > 1 order magnitude per 5000 psia → Stress-sensitive fracture contribution
  Irreversible compaction (hysteresis) → Plastic deformation; reserve estimates must use in-situ porosity

════════════════════════════════════════════════════
SECTION 9 — VISION PROTOCOL (LABORATORY EQUIPMENT ANALYSIS)
════════════════════════════════════════════════════
When the user sends an image (photograph, diagram, or screenshot of laboratory equipment \
or measurement data), activate the Vision Protocol. This capability is ACTIVE — you are \
not simulating vision, you can genuinely analyze the image content.

STEP 1 — DEVICE IDENTIFICATION:
  Examine the image and identify the instrument(s) present. Common PRC SCAL lab devices:
  • Core Holder / Hassler Cell — cylindrical body, confining pressure port, end caps
  • HPHT Pressure Cell — heavy steel vessel, pressure gauges, heating jacket
  • Peristaltic / Syringe / HPLC Pump — tubing, piston mechanism, digital flow controller
  • Centrifuge (SCAL variant) — rotor arms, core tube holders, speed controller
  • Porous Plate Apparatus — stacked ceramic plates, fluid column tube
  • Mercury Injection Capillary Pressure (MICP) — sealed chamber, Hg reservoir, pressure transducer
  • Dean-Stark Distillation Unit — glass flask, condenser, calibrated receiver
  • Amott Cell — vertical glass tube, graduated scale, oil/water chambers
  • NMR Core Analyzer — magnet bore, RF coil assembly, sample chamber
  Report the device name and its SCAL function in one sentence.

STEP 2 — CONFIGURATION AUDIT:
  Inspect the image for visible errors or misconfigurations:
  • Valve positions (open/closed when they should not be)
  • Pressure gauge readings outside expected range
  • Tubing connections (wrong port, reversed inlet/outlet)
  • Fluid levels in burettes or collection tubes
  • Heating element status vs. setpoint displayed
  • Sample orientation (core plug inverted, improper seating)
  • Safety concerns (unclamped fittings, pressure vent blocked)
  Report each detected issue as: ISSUE [n]: [description] — SEVERITY: [Critical / Warning / Advisory]

STEP 3 — PRC PROCEDURE CITATION:
  For each identified issue or for the device's standard operating procedure, cite the \
relevant section from the PRC technical library context. If the library contains the \
device's procedure, quote the critical steps verbatim with section reference. \
If the library does not contain the specific procedure, state: \
"Procedure not found in current PRC library — applying API RP 40 standard defaults."

STEP 4 — ON-SITE CORRECTIVE GUIDANCE:
  Provide numbered, action-level instructions the engineer can follow immediately:
  1. [Specific action — verb-first, exact valve/component named]
  2. [Next action...]
  Use imperative language. Write for an engineer standing in front of the equipment, \
not for a reader in an office.

STEP 5 — SAFETY CLEARANCE:
  End with one of two statements:
  ✓ CLEARED FOR OPERATION — No critical issues detected. Proceed with standard PRC protocol.
  ✗ HOLD — Critical issue detected. Do not pressurize / energize / start until [specific \
corrective action] is completed and verified by the laboratory supervisor.
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
                "description": (
                    "Fits raw SCAL lab data to standard petrophysical models. Select model by curve type:\n"
                    "  model='brooks_corey' or 'let' → Relative Permeability (pass sw, krw, kro arrays).\n"
                    "  model='micp' → Mercury Injection (pass pc=[psia], s_hg=[fraction 0-1]). "
                    "For imbibition (recovery) cycle: also pass pc_imb=[psia], s_hg_imb=[fraction]. "
                    "Auto-generates log-scale Pc curve (drainage solid, imbibition dashed) + PSD.\n"
                    "  model='ri' → Resistivity Index Archie fit (pass sw=[...], ri=[...]). Log-log plot, fits n exponent.\n"
                    "  model='ff' → Formation Factor Archie fit (pass porosity=[...], ff=[...]). Log-log plot, fits m and a.\n"
                    "  model='jfunction' → Leverett J-Function (pass sw=[...], pc=[psia], k_md=X, phi_val=Y, ift_cos_theta=26.5).\n"
                    "  model='pc_centrifuge' → Capillary Pressure direct (pass sw=[...], pc=[psia values]).\n"
                    "  model='overburden' → Compaction curves (pass pressure=[psia], porosity=[...], perm=[mD]). Dual-axis.\n"
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


# ── GEMINI HA CLIENT ──────────────────────────────────────────────────────────
class PRCChatAssistant:
    def __init__(self, keys: list[str]):
        self.model_name   = "gemini-3.1-pro"
        self._keys        = keys
        self._current_idx = 0
        self._idx_lock    = threading.Lock()
        self._client_lock = threading.Lock()
        self._client      = None
        self._pending_kb  = [] # Temporary storage for background indexing
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
                client = genai_new.Client(api_key=key, http_options={'api_version': 'v1'})
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
            model = args.get("model", "")
            if model in ("micp", "ri", "ff", "jfunction", "pc_centrifuge", "overburden"):
                # All analytic models: computation fully handled by _format_tool_response using args
                return _json.dumps({"status": "ready", "model": model})
            data = {"model": model, "sw": args.get("sw",[]), "krw": args.get("krw",[])}
            res  = SkillsEngine.run_skill("petroleum", "", "curve_fitting_skill.py", [_json.dumps(data)])
            return res.get("stdout") or res.get("error", "")
        elif name == "agentic_history_matching":
            data = {"sw": args.get("sw",[]), "krw": args.get("krw",[]), "kro": args.get("kro",[])}
            res  = SkillsEngine.run_skill("petroleum", "simulator", "history_matching_skill.py", [_json.dumps(data)])
            return res.get("stdout") or res.get("error", "")
        elif name == "generate_executive_report":
            sid  = getattr(_tls, 'current_session_id', None)
            well = args.get("well_name", "UNKNOWN WELL")
            if not sid:
                return "ERROR: session context unavailable — use the Download Report button instead."
            try:
                # Use generate() method as defined in report_generator.py
                filename = PRCReportEngine().generate(session_id=sid, well_name=well)
                return f"REPORT_READY:{filename}"
            except Exception as e:
                _logger.error(f"[Report] Tool generation failed: {e}")
                return f"ERROR: {e}"
        elif name == "get_audit_history":
            sid = getattr(_tls, 'current_session_id', None)
            if not sid:
                return "ERROR: Session ID unavailable."
            rows = db("SELECT timestamp, data_type, health_score, violations, file_name "
                      "FROM physics_audits WHERE session_id=? ORDER BY timestamp DESC", (sid,))
            if not rows:
                return "No audit records found for this session. The Auditor's Ledger is currently empty."
            
            summary = ["### PRC AUDIT LEDGER — SESSION HISTORY"]
            for r in rows:
                ts = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(r[0]))
                v_list = _json.loads(r[3])
                v_str  = ", ".join([v['rule'] for v in v_list]) if v_list else "None"
                summary.append(f"**[{ts}] {r[1].upper()}**\n- Score: {r[2]}%\n- File: {r[4] or 'N/A'}\n- Violations: {v_str}")
            return "\n\n".join(summary)
        return f"Unknown tool: {name}"

    def _format_tool_response(self, name: str, args: dict, result: str) -> str:
        try:
            # ── Executive Report ──────────────────────────────────────────────────────
            if name == "generate_executive_report":
                if result.startswith("REPORT_READY:"):
                    base  = result[len("REPORT_READY:"):]
                    dl    = f"/api/download/{base}"
                    well  = args.get("well_name", "UNKNOWN WELL").upper()
                    return (
                        f"\n\n**Executive SCAL Report — {well}**\n\n"
                        f"The report has been compiled and is ready for download.\n\n"
                        f"📄 `{base}`\n\n"
                        f"__REPORT_DL__{dl}__END_REPORT_DL__\n\n"
                        f"*Sign off after engineering review before distribution.*\n\n"
                    )
                return f"\n\n{result}\n\n"

            # ── MICP: Drainage + Imbibition, log-Pc, % x-axis, hysteresis ────────────
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
                    # X-axis: fraction → % Pore Volume
                    shg_pct = shg_s * 100.0
                    pc_pos  = np.maximum(pc_s, 0.1)
                    # Washburn: r(µm) = 107.5 / Pc_psia  (Hg-air: γ=480 mN/m, θ=140°)
                    r_um    = 107.5 / pc_pos
                    # Entry pressure — first point where Hg_sat > 1 %
                    entry_mask = shg_s > 0.01
                    pe = float(pc_s[entry_mask][0]) if entry_mask.any() else float(pc_s[0])
                    # Threshold pressure — inflection of Pc(Sw) curve
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
                    # ── Imbibition (recovery) cycle ────────────────────────────────
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
                        # Trapped Hg = drainage peak sat − imbibition final sat
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

                    # Plot 1 — Capillary Pressure (log-scale Y)
                    plot_pc = {
                        "title":    "MICP — Capillary Pressure vs Mercury Saturation",
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
                    # Plot 2 — Pore Size Distribution
                    plot_psd = {
                        "title":  "Pore Throat Size Distribution (MICP)",
                        "xAxis":  {"label": "Pore Throat Radius r (µm)"},
                        "yAxis":  {"label": "Incremental Hg Saturation  dSw/d(log r)"},
                        "curves": [{"name": "Pore Throat Distribution", "showLine": True,
                                    "showPoints": False, "color": "#f59e0b",
                                    "data": psd_pts}],
                    }
                    # ── Physics Guard ──────────────────────────────────────────
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
                        f"Modal Pore Throat r = {thr_r:.3f} µm",
                        f"Max Hg Saturation = {float(shg_pct[-1]):.1f}%",
                        f"Pore Sorting Index = {sorting_idx}",
                    ]
                    if trapped_pct is not None:
                        parts.append(f"Trapped Hg (Hysteresis) = {trapped_pct:.1f}%")
                    summary = "  |  ".join(parts)
                    return (
                        f"\n\nMICP analysis complete. {summary}\n\n"
                        f"__PRC_PLOT__\n{_json.dumps(plot_pc, ensure_ascii=False)}\n\n"
                        f"__PRC_PLOT__\n{_json.dumps(plot_psd, ensure_ascii=False)}\n\n"
                        f"{audit['footer']}\n\n"
                    )

            # ── RESISTIVITY INDEX (Archie n fit, log-log) ──────────────────────────────
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
                        "title":    f"Resistivity Index — RI vs Sw ({sample})",
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
                    # ── Physics Guard ──────────────────────────────────────────
                    audit = PhysicsGuard().validate_archie(sw_a, ri_a, "RI").generate_health_score()
                    plot_ri["metadata"]["physics_audit"] = audit
                    _log_physics_audit(
                        getattr(_tls, 'current_session_id', 'ANONYMOUS'), 
                        "ri", 
                        audit, 
                        getattr(_tls, 'last_file_name', None)
                    )

                    return (
                        f"\n\nResistivity Index analysis complete. "
                        f"Archie saturation exponent n = {n_arch:.4f}\n\n"
                        f"__PRC_PLOT__\n{_json.dumps(plot_ri, ensure_ascii=False)}\n\n"
                        f"{audit['footer']}\n\n"
                    )

            # ── FORMATION FACTOR (Archie m, a fit, log-log) ────────────────────────────
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
                        "title":    f"Formation Factor — FF vs Porosity ({sample})",
                        "xAxis":    {"label": "Porosity φ (fraction)"},
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
                    # ── Physics Guard ──────────────────────────────────────────
                    audit = PhysicsGuard().validate_archie(phi_a, ff_a, "FF").generate_health_score()
                    plot_ff["metadata"]["physics_audit"] = audit
                    _log_physics_audit(
                        getattr(_tls, 'current_session_id', 'ANONYMOUS'), 
                        "ff", 
                        audit, 
                        getattr(_tls, 'last_file_name', None)
                    )

                    return (
                        f"\n\nFormation Factor analysis complete. "
                        f"Archie cementation m = {m_arch:.4f}, tortuosity a = {a_arch:.4f}\n\n"
                        f"__PRC_PLOT__\n{_json.dumps(plot_ff, ensure_ascii=False)}\n\n"
                        f"{audit['footer']}\n\n"
                    )

            # ── LEVERETT J-FUNCTION ────────────────────────────────────────────────────
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
                    # J = 0.21645 × Pc[psia] × sqrt(k[mD]/φ) / σcosθ[dyn/cm]
                    j_arr = 0.21645 * pc_a * np.sqrt(k_md / phi_val) / ift_ct
                    idx   = np.argsort(sw_a)
                    plot_j = {
                        "title": f"Leverett J-Function ({sample}  k={k_md} mD  φ={phi_val:.3f})",
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
                        f"\n\nLeverett J-Function computed. "
                        f"k = {k_md} mD, φ = {phi_val:.3f}, σcosθ = {ift_ct} mN/m\n\n"
                        f"__PRC_PLOT__\n{_json.dumps(plot_j, ensure_ascii=False)}\n\n"
                    )

            # ── CAPILLARY PRESSURE — CENTRIFUGE / POROUS PLATE ────────────────────────
            if name == "fit_petrophysical_curve" and args.get("model") == "pc_centrifuge":
                sw_raw = args.get("sw", [])
                pc_raw = args.get("pc", [])
                sample = args.get("sample_name", "Core")
                if len(sw_raw) > 1 and len(pc_raw) > 1:
                    sw_a = np.array(sw_raw, dtype=float)
                    pc_a = np.array(pc_raw, dtype=float)
                    idx  = np.argsort(sw_a)
                    plot_pc = {
                        "title": f"Capillary Pressure — Pc vs Sw ({sample})",
                        "xAxis": {"label": "Water Saturation Sw (fraction)"},
                        "yAxis": {"label": "Capillary Pressure Pc (psia)"},
                        "curves": [
                            {"name": f"Pc ({sample})", "showLine": True, "showPoints": True,
                             "color": "#38bdf8",
                             "data": [{"x": float(sw_a[i]), "y": float(pc_a[i])} for i in idx]},
                        ],
                    }
                    # ── Physics Guard ──────────────────────────────────────────
                    audit = PhysicsGuard().validate_pc(sw_a, pc_a).generate_health_score()
                    plot_pc["metadata"]["physics_audit"] = audit
                    _log_physics_audit(
                        getattr(_tls, 'current_session_id', 'ANONYMOUS'), 
                        "pc", 
                        audit, 
                        getattr(_tls, 'last_file_name', None)
                    )

                    summary = (f"Pc range: {float(pc_a.min()):.2f} – {float(pc_a.max()):.2f} psia | "
                               f"Sw range: {float(sw_a.min()):.3f} – {float(sw_a.max()):.3f}")
                    return (f"\n\nCapillary Pressure analysis complete. {summary}\n\n"
                            f"__PRC_PLOT__\n{_json.dumps(plot_pc, ensure_ascii=False)}\n\n"
                            f"{audit['footer']}\n\n")

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
                        "title":         f"Overburden Compaction — φ & k vs Net Stress ({sample})",
                        "xAxis":         {"label": "Net Confining Pressure (psia)"},
                        "yAxis":         {"label": "Porosity φ (fraction)"},
                        "yAxis2":        {"label": "Permeability k (mD)"},
                        "dualAxis":      True,
                        "yAxisRightLog": True,
                        "curves":        curves,
                    }
                    summary = (f"Pressure range: {float(pres_a.min()):.0f} – {float(pres_a.max()):.0f} psia")
                    return (f"\n\nOverburden compaction analysis complete. {summary}\n\n"
                            f"__PRC_PLOT__\n{_json.dumps(plot_ob, ensure_ascii=False)}\n\n")

            tr = _json.loads(result) if isinstance(result, str) else result
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

                # ── Physics Guard ──────────────────────────────────────────────
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
                    f"\n\nOptimization complete. Final MSE: {mse:.5f}\n"
                    f"__PRC_PLOT__\n{_json.dumps(plot_data)}\n\n"
                    f"{audit['footer']}\n\n"
                )
            elif name == "execute_python_simulation":
                if isinstance(result, str) and "__SIMULATION_START__" in result:
                    return f"\n\nSimulation complete.\n{result}\n\n"
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

                    # ── Physics Guard ──────────────────────────────────────────
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
                        f"\n\nSimulation complete.\n"
                        f"__PRC_PLOT__\n{_json.dumps(plot_data)}\n\n"
                        f"{audit['footer']}\n\n"
                    )
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
                _MODEL_NOTES = {
                    "micp":          "Pc curve and Pore Size Distribution rendered. Proceed with Entry Pressure, Threshold Pressure, and Pore Throat Sorting analysis.",
                    "ri":            "Resistivity Index log-log plot rendered. State Archie n, compare to PRC library range n∈[1.5,3.0], interpret wettability effect.",
                    "ff":            "Formation Factor log-log plot rendered. State Archie m and a, interpret cementation and pore geometry.",
                    "jfunction":     "Leverett J-Function rendered. Assess J-curve shape for capillary continuity and capillary entry threshold.",
                    "pc_centrifuge": "Capillary Pressure curve rendered. Interpret drainage vs imbibition, entry pressure, and residual saturation.",
                    "overburden":    "Overburden compaction dual-axis plot rendered. Quantify porosity loss and permeability reduction per 1000 psia confining stress.",
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
                        "note": "Curve fit complete. PRC_PLOT rendered. Proceed with wettability and endpoint interpretation.",
                    }
            elif name == "get_audit_history":
                return {
                    "status": "success",
                    "note": "PRC Audit Ledger retrieved. Analyze the quality trend and alert the engineer of recurring violations."
                }
            elif name == "generate_executive_report":
                return {
                    "status": "success",
                    "well_name": args.get("well_name", "Unknown Well"),
                    "note": "Executive report generated and link provided in chat."
                }
        except Exception as e:
            _logger.error(f"[Tool] _format_tool_response error ({name}): {e}")
            pass
        return {"status": "executed", "tool": name, "note": "Tool executed. Results and visualization rendered in chat."}

    def _build_contents(self, history: list, enriched_msg: str, f_parts: list) -> tuple[list, list[str]]:
        SUPPORTED = {
            "application/pdf", "image/jpeg", "image/png", "image/gif", "image/webp",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "text/plain", "text/csv"
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
        for data_bytes, mime in f_parts:
            safe_mime = mime or "application/octet-stream"
            if safe_mime not in SUPPORTED:
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
        self._pending_kb = [] # Reset for this turn
        # Structure the KB context clearly so Gemini's Section 2 protocol fires correctly
        extracted_context = ""
        import tempfile
        def _sample_data(data: dict, max_rows: int = 40) -> dict:
            """Sample rows if dataset is large to prevent prompt bloat."""
            sampled = {}
            for k, v in data.items():
                if isinstance(v, list) and len(v) > max_rows:
                    step = len(v) // max_rows
                    sampled[k] = v[::step][:max_rows]
                elif isinstance(v, dict):
                    sampled[k] = _sample_data(v, max_rows)
                else:
                    sampled[k] = v
            return sampled

        for data_bytes, mime in f_parts:
            safe_mime = mime or "application/octet-stream"
            # Only process Excel/CSV with the SCAL handler
            if "spreadsheet" in safe_mime or "excel" in safe_mime or "csv" in safe_mime or "sheet" in safe_mime:
                with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(safe_mime)[1] if "/" not in safe_mime else ".xlsx") as tf:
                    tf.write(data_bytes)
                    tmp_path = tf.name
                try:
                    handler = SCALFileHandler(tmp_path)
                    result = handler.process()
                    if result.get('data_type') != 'UNKNOWN':
                        sampled = _sample_data(result['extracted'])
                        extracted_context += f"\n\n[EXTRACTED DATA FROM UPLOADED FILE ({result['data_type']})]:\n{_json.dumps(sampled, indent=2)}\n"
                        # Prepare for background indexing
                        self._pending_kb.append((file.filename, _json.dumps(result['extracted'])))
                except Exception as e:
                    _logger.error(f"SCAL Handler Error: {e}")
                finally:
                    try: os.unlink(tmp_path)
                    except: pass

        if kb_context or extracted_context:
            enriched = f"{msg}"
            if kb_context:
                enriched += f"\n\n[CONTEXT FROM PRC TECHNICAL LIBRARY:\n{kb_context}\nEND CONTEXT]"
            if extracted_context:
                enriched += f"\n\n{extracted_context}\n[INSTRUCTION: Use the extracted data above to fulfill the request. Do not ask the user for data that is already extracted here.]"
        else:
            enriched = msg

        # Semantic Cache Lookup
        query_text = msg.strip().lower()
        query_hash = hashlib.sha256(query_text.encode()).hexdigest()
        cached = db("SELECT response FROM response_cache WHERE query_hash=?", (query_hash,))
        
        if cached:
            _logger.info(f"[CACHE] Hit for query hash: {query_hash[:8]}")
            def _gen_cached():
                yield cached[0][0]
                # Log the cached message to history
                db("INSERT INTO m (sid, user_email, role, text, ts) VALUES (?, ?, ?, ?, ?)",
                   (sid, email, "model", cached[0][0], time.time()))
            return _gen_cached()

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
                        full_response = ""
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
                                        full_response += part.text
                                        yield part.text

                            # Emit formatted tool results (plots/mermaid) after text for this turn
                            for _, _, fmt in tool_calls_in_turn:
                                full_response += fmt
                                yield fmt

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
        # PRE-CALCULATE EMBEDDINGS OUTSIDE THE LOCK TO PREVENT CONNECTION TIMEOUTS
        # For long files, embedding can take 30s+ which would block all other requests.
        chunk_data = []
        for source, chunk in chunks:
            vec = KnowledgeBase._embed(chunk)
            chunk_data.append((source, chunk, vec))

        with _get_conn() as (conn, ph):
            cur = conn.cursor()
            try:
                # ph is the driver placeholder token ("?" for SQLite, "%s" for PostgreSQL).
                cur.execute(f"SELECT id FROM kb WHERE source = {ph}", (name,))
                old_ids = [r[0] for r in cur.fetchall()]
                if old_ids:
                    in_ph = ",".join([ph] * len(old_ids))
                    cur.execute(f"DELETE FROM kb_vectors WHERE chunk_id IN ({in_ph})", tuple(old_ids))
                cur.execute(f"DELETE FROM kb WHERE source = {ph}", (name,))
                
                for source, chunk, vec in chunk_data:
                    if ph == "?":
                        cur.execute("INSERT INTO kb (source, chunk) VALUES (?,?)", (source, chunk))
                        chunk_id = cur.lastrowid
                    else:
                        cur.execute("INSERT INTO kb (source, chunk) VALUES (%s,%s) RETURNING id", (source, chunk))
                        chunk_id = cur.fetchone()[0]
                    
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
            # `conditions` is built from the fixed literal "LOWER(chunk) LIKE ?" only —
            # no user content is interpolated into the SQL skeleton. Values are passed
            # as parameterized arguments; db() applies _translate_placeholders() for PG.
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
        "CREATE TABLE IF NOT EXISTS sessions (sid TEXT PRIMARY KEY, title TEXT NOT NULL DEFAULT 'New Study', user_email TEXT, created_at REAL, updated_at REAL)",
        "CREATE TABLE IF NOT EXISTS kb (id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT, chunk TEXT)",
        "CREATE TABLE IF NOT EXISTS kb_vectors (id INTEGER PRIMARY KEY AUTOINCREMENT, chunk_id INTEGER UNIQUE, embedding BLOB)",
        "CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT UNIQUE, name TEXT, created_at REAL)",
        "CREATE TABLE IF NOT EXISTS feedback (id INTEGER PRIMARY KEY AUTOINCREMENT, user_email TEXT, bug_report TEXT, ts REAL)",
        "CREATE TABLE IF NOT EXISTS analytics_events (id INTEGER PRIMARY KEY AUTOINCREMENT, user_email TEXT, event_type TEXT, event_data TEXT, ts REAL)",
        # THE AUDITOR'S LEDGER — append-only physics integrity log
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
    # Backfill existing m rows → sessions table (migration for pre-existing installs)
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
# ── AUTH & SESSION VERIFICATION ──────────────────────────────────────────────
def _verify_session_owner(sid: str, email: str):
    """
    STRICT ROW-LEVEL SECURITY: Ensure the session belongs to the requesting user.
    Prevents 'Vibe-coding' data leakage.
    """
    if not email:
        raise HTTPException(status_code=401, detail="Authentication required")
    row = db("SELECT user_email FROM sessions WHERE sid=?", (sid,))
    if row and row[0][0] and row[0][0].lower().strip() != email.lower().strip():
        _logger.warning(f"[SECURITY] Unauthorized access attempt: {email} tried to access {sid}")
        raise HTTPException(status_code=403, detail="Unauthorized: You do not own this session.")

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

@app.post("/api/auth")
async def user_login(pin: str = Form(...)):
    # Sync with the same logic as admin but without the elevated token
    target_pin = ADMIN_PIN or "1509"
    if pin != target_pin:
        _logger.warning(f"[AUTH] Failed user login attempt with code: {pin}")
        time.sleep(0.5)
        raise HTTPException(status_code=401, detail="Invalid Access Code")
    return {"status": "success"}

@app.post("/api/admin/auth")
async def admin_login(pin: str = Form(...)):
    # Use ENV pin or fallback to 1509
    target_pin = ADMIN_PIN or "1509"
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
async def get_sessions(email: str = None):
    if not email:
        return []
    const_email = email.lower().strip()
    rows = db(
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
        db("INSERT INTO sessions (sid, title, user_email, updated_at) VALUES (?, ?, ?, ?) "
           "ON CONFLICT (sid) DO UPDATE SET title = EXCLUDED.title, updated_at = EXCLUDED.updated_at",
           (sid, title, email, time.time()))
    else:
        db("INSERT OR REPLACE INTO sessions (sid, title, user_email, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
           (sid, title, email, time.time(), time.time()))
    return {"status": "ok"}

@app.delete("/api/session/{sid}")
def delete_session(sid: str, email: str = None):
    _verify_session_owner(sid, email)
    db("DELETE FROM m WHERE sid=? AND user_email=?", (sid, email))
    db("DELETE FROM sessions WHERE sid=? AND user_email=?", (sid, email))
    db("DELETE FROM physics_audits WHERE session_id=? AND user_email=?", (sid, email))
    return {"status": "ok"}

@app.get("/api/chat/stream")
async def chat_stream(
    message:       str,
    background_tasks: BackgroundTasks,
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
            
            # Upsert into sessions table
            if _PG_AVAILABLE:
                db("INSERT INTO sessions (sid, title, user_email, updated_at) VALUES (?, 'New Study', ?, ?) "
                   "ON CONFLICT (sid) DO UPDATE SET updated_at = EXCLUDED.updated_at",
                   (sid, email, time.time()))
            else:
                db("INSERT OR IGNORE INTO sessions (sid, title, user_email, created_at, updated_at) VALUES (?, 'New Study', ?, ?, ?)",
                   (sid, email, time.time(), time.time()))
                db("UPDATE sessions SET updated_at=? WHERE sid=?", (time.time(), sid))

            # Fetch the most-recent 10 messages (descending), then reverse to chronological order
            hist_rows = db("SELECT role, text FROM m WHERE sid=? ORDER BY id DESC LIMIT 10", (sid,))
            history   = list(reversed([{"role": r, "text": t} for r, t in hist_rows]))

            _tls.current_session_id = sid   # available to generate_executive_report tool
            full_reply = ""
            for chunk in assistant.chat(history, message, kb_context=kb_ctx, stream=True, sid=sid, email=email):
                if chunk:
                    full_reply += chunk
                    yield f"data: {_json.dumps({'type': 'token', 'text': chunk})}\n\n"

            if full_reply:
                db("INSERT INTO m (sid,role,text,ts,user_email) VALUES (?,?,?,?,?)", (sid, "model", full_reply, time.time(), email))

            if assistant._pending_kb:
                background_tasks.add_task(KnowledgeBase.ingest_transactional, "SCAL Upload", list(assistant._pending_kb))

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

    f_parts = []
    _tls.last_file_name = files[0].filename if files else None
    _tls.current_session_id = sid
    for file in files:
        b = await file.read()
        f_parts.append((b, file.content_type))

    kb_ctx = await KnowledgeBase.search_async(message)
    db("INSERT INTO m (sid,role,text,ts,user_email) VALUES (?,?,?,?,?)",
       (sid, "user", message, time.time(), email))

    # Upsert into sessions table
    if _PG_AVAILABLE:
        db("INSERT INTO sessions (sid, title, user_email, updated_at) VALUES (?, 'New Study', ?, ?) "
           "ON CONFLICT (sid) DO UPDATE SET updated_at = EXCLUDED.updated_at",
           (sid, email, time.time()))
    else:
        db("INSERT OR IGNORE INTO sessions (sid, title, user_email, created_at, updated_at) VALUES (?, 'New Study', ?, ?, ?)",
           (sid, email, time.time(), time.time()))
        db("UPDATE sessions SET updated_at=? WHERE sid=?", (time.time(), sid))

    # ── Security Guard: Verify session ownership before any data access ───────
    _verify_session_owner(sid, email)

    # ── Document generation path (Gemini JSON → HvielDocEngine file) ──────────
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
    hist_rows = db("SELECT role, text FROM m WHERE sid=? AND user_email=? ORDER BY id DESC LIMIT 10", (sid, email))
    history   = list(reversed([{"role": r, "text": t} for r, t in hist_rows]))

    # Run blocking Gemini call in a thread so we don't block the FastAPI event loop
    resp = await asyncio.get_event_loop().run_in_executor(
        None, lambda: assistant.chat(history, message, kb_ctx, f_parts, sid=sid, email=email)
    )
    
    db("INSERT INTO m (sid,role,text,ts,user_email) VALUES (?,?,?,?,?)",
       (sid, "model", resp, time.time(), email))
    
    if assistant._pending_kb:
        background_tasks.add_task(KnowledgeBase.ingest_transactional, "SCAL Upload", list(assistant._pending_kb))

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


# ── FRONTEND SERVING (SPA) ───────────────────────────────────────────────────
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
    # Unlike /api/download we allow nested paths (assets/js/…) so we use the full
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
