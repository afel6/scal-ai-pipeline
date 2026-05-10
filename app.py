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

CLAUDE_API_KEY   = os.getenv("CLAUDE_API_KEY",   "").strip()
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
    """Convert SQLite ? placeholders to PostgreSQL $N."""
    out, n, in_str, quote = [], 0, False, None
    for ch in query:
        if in_str:
            out.append(ch)
            if ch == quote:
                in_str = False
        elif ch in ("'", '"'):
            in_str, quote = True, ch
            out.append(ch)
        elif ch == "?":
            n += 1
            out.append(f"${n}")
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
SYSTEM_PROMPT = """You are a Senior AI Petrophysical Specialist embedded in the PRC SCAL Pipeline.

### DIRECTIVE 1 — AUTOMATIC CURVE DETECTION
Inspect data and categorise immediately:
  Sw + Krw + Kro          → Relative Permeability
  Sw + Pc                 → Capillary Pressure
  Sw + RI                 → Resistivity Index    [Log-Log mandatory]
  Porosity + FF           → Formation Factor     [Log-Log / Archie mandatory]
  Pressure + Porosity + k → Overburden Compaction [Dual-Axis mandatory]
  T2 + porosity           → NMR T2
  Vsp/Vtp/Vso/Vto         → Wettability (Amott)
  Pc + IFT + k + φ        → J-Function

### DIRECTIVE 2 — VISUALIZATION PROTOCOL (__PRC_PLOT__ & __PRC_DASHBOARD__)
Embed a visualization block for every dataset:

- **PRC_PLOT**: For standard SCAL curves. Use JSON schema: `{"curves": [...], "xAxis": {...}, "yAxis": {...}}`.
- **PRC_DASHBOARD**: For complex, "no compaction" industrial dashboards. Return raw HTML/JS using Chart.js inside `__PRC_DASHBOARD__` tags. Example:
  __PRC_DASHBOARD__
  <canvas id="myChart"></canvas>
  <script>
    new Chart(document.getElementById('myChart'), { type: 'line', data: {...}, options: {...} });
  </script>
  __PRC_DASHBOARD__

Rules:
- showLine:true  + showPoints:false → fitted model (smooth curve only)
- showLine:false + showPoints:true  → raw lab data (filled circles only)
- Blue = water, Red/Orange = oil, Green = gas
- Log-Log required for RI vs Sw and FF vs Phi
- Dual-Axis required for Overburden (Phi left-linear, k right-log)

### DIRECTIVE 3 — 3-PHASE RESPONSE STRUCTURE

### PHASE 1: INGESTION & AUDIT
Source, sample ID, detected NaN values, data quality.

### PHASE 2: HIGH-FIDELITY SIMULATION
**1. [Curve Type Name]**
Physics Model: [e.g. Archie's Law, Brooks-Corey]
Visualization Spec: [scale types, dual-axis status, or dashboard mode]
__PRC_PLOT__ { ... } OR __PRC_DASHBOARD__ ... __PRC_DASHBOARD__

### PHASE 3: CERTIFICATION
One-sentence engineering summary confirming readiness for PRC Executive Board.
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
        self.model_name   = "gemini-2.0-flash"
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
        enriched = f"{msg}\n\n[CONTEXT: {kb_context}]" if kb_context else msg
        contents, uploaded_uris = self._build_contents(history, enriched, f_parts)
        _tls.last_file_uris = ",".join(uploaded_uris) if uploaded_uris else None

        def _generate():
            for attempt in range(len(self._keys)):
                try:
                    with self._client_lock:
                        client = self._client
                    cfg = genai_types.GenerateContentConfig(
                        temperature=0.1,
                        tools=_HVIEL_TOOLS,
                        system_instruction=SYSTEM_PROMPT,
                    )
                    if stream:
                        for chunk in client.models.generate_content_stream(model=self.model_name, contents=contents, config=cfg):
                            if not (chunk.candidates and chunk.candidates[0].content):
                                continue
                            for part in chunk.candidates[0].content.parts or []:
                                if part.function_call:
                                    yield f" [Executing {part.function_call.name}...] "
                                    res = self._execute_tool(part.function_call)
                                    yield self._format_tool_response(part.function_call.name, part.function_call.args, res)
                                elif part.text:
                                    yield part.text
                    else:
                        resp = client.models.generate_content(model=self.model_name, contents=contents, config=cfg)
                        if not (resp and resp.candidates and resp.candidates[0].content):
                            yield "Unable to generate a response. Please rephrase your query."
                            return
                        final = ""
                        for part in resp.candidates[0].content.parts or []:
                            if part.function_call:
                                res    = self._execute_tool(part.function_call)
                                final += self._format_tool_response(part.function_call.name, part.function_call.args, res)
                            elif part.text:
                                final += part.text
                        yield final
                        return
                    return
                except Exception as e:
                    err      = str(e).lower()
                    is_auth  = any(x in err for x in ["401","403","unauthorized","permission"])
                    is_rate  = any(x in err for x in ["429","resource_exhausted"])
                    if (is_auth or is_rate) and attempt < len(self._keys) - 1:
                        self.rotate_key(is_hard_fail=is_auth)
                        if stream:
                            yield " !!! Rotating Node !!! "
                        continue
                    raise
        return _generate() if stream else next(_generate(), "Error generating response.")


# ── ANTHROPIC DOCUMENT ENGINE ─────────────────────────────────────────────────
class AnthropicAssistant:
    _DOCX_SCHEMA = """Return ONLY valid JSON (no markdown fences, no explanation):
{
  "title": "Document Title",
  "subtitle": "Optional subtitle",
  "author": "Engineer name",
  "sections": [
    {
      "heading": "Section Name",
      "level": 1,
      "paragraphs": ["Paragraph text or __PRC_PLOT__ {...}"],
      "bullets": ["bullet point"]
    }
  ],
  "tables": [
    {"caption": "Table caption", "headers": ["Col1","Col2"], "rows": [["v1","v2"]]}
  ]
}
Rules:
1. Max 3 data rows per table.
2. NO raw markdown tables inside paragraphs — use the tables array.
3. level 1 = major section, level 2 = subsection.
4. Embed charts as: __PRC_PLOT__ followed by a JSON object on the same line."""

    _EXCEL_SCHEMA = """Return ONLY valid JSON:
{
  "title": "Spreadsheet Title",
  "sheets": [
    {"name": "Sheet Name", "headers": ["Col1 (unit)","Col2 (unit)"], "rows": [["v1","v2"]]}
  ]
}
Rules: Full numerical precision. Max 5 data rows. Multiple sheets if appropriate."""

    @staticmethod
    def _build_context(history: list, msg: str, kb_context: str) -> str:
        ctx = f"--- KNOWLEDGE BASE ---\n{kb_context}\n---\n\n" if kb_context else ""
        ctx += "--- CONVERSATION HISTORY ---\n"
        for h in history[-6:]:
            ctx += f"{h['role'].upper()}: {h.get('text','')[:600]}\n\n"
        return ctx + f"--- END ---\n\nUSER REQUEST: {msg}"

    @staticmethod
    def _call(system: str, msg: str, history: list, kb_context: str) -> str:
        if not CLAUDE_API_KEY:
            raise ValueError("CLAUDE_API_KEY environment variable is not set.")
        import anthropic
        client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
        resp   = client.messages.create(
            model="claude-3-5-sonnet-20241022", max_tokens=1500, system=system,
            messages=[{"role":"user","content": AnthropicAssistant._build_context(history, msg, kb_context)}])
        return resp.content[0].text

    @classmethod
    def generate_docx(cls, history, msg, kb_context) -> str:
        system = "You are an elite petrophysics report writer for the PRC. " + cls._DOCX_SCHEMA
        return cls._call(system, msg, history, kb_context)

    @classmethod
    def generate_excel(cls, history, msg, kb_context) -> str:
        system = "You are an elite data engineer for the PRC. " + cls._EXCEL_SCHEMA
        return cls._call(system, msg, history, kb_context)


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
    if not ADMIN_PIN or pin != ADMIN_PIN:
        time.sleep(1) # Throttling
        raise HTTPException(status_code=401, detail="Invalid Admin PIN")
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

@app.post("/api/chat")
async def handle(
    message:       str             = Form(...),
    session_id:    Optional[str]   = Form(None),
    user_email:    Optional[str]   = Form(None),
    files:         list[UploadFile] = File(default=[]),
):
    sid = session_id or str(uuid.uuid4())
    email = user_email.lower().strip() if user_email else None
    f_parts = []
    for file in files:
        b = await file.read()
        f_parts.append((b, file.content_type))
    
    kb_ctx = await KnowledgeBase.search_async(message)
    db("INSERT INTO m (sid,role,text,ts,user_email) VALUES (?,?,?,?,?)", (sid, "user", message, time.time(), email))
    
    resp = assistant.chat([], message, kb_ctx, f_parts)
    db("INSERT INTO m (sid,role,text,ts,user_email) VALUES (?,?,?,?,?)", (sid, "model", resp, time.time(), email))
    
    return {"status":"success","session_id":sid,"reply":resp}

@app.get("/api/download/{filename:path}")
async def dl(filename: str):
    path = os.path.abspath(os.path.basename(filename))
    if not os.path.isfile(path): return {"error": "File not found"}
    return FileResponse(path)

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
