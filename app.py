# PRC-HUB-VER-13-PROD-READY - HEARTBEAT: 2026-05-09T23:20
print("[SYSTEM] app.py loading...")
from fastapi import FastAPI, UploadFile, File, Form
from contextlib import asynccontextmanager
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import os, uuid, time, re, json as _json, logging, threading, asyncio
import numpy as np
import pandas as pd
from typing import Optional
from bs4 import BeautifulSoup
from hviel_doc_engine import HvielDocEngine
from skills_engine import SkillsEngine
from docx import Document
from google import genai as genai_new
from google.genai import types as genai_types

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
_logger = logging.getLogger("PRC-Hub")
_USE_NEW_SDK = True

# -- Fix 3: PostgreSQL + SQLite unified DB layer --
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
_PG_AVAILABLE = False
if DATABASE_URL:
    try:
        import psycopg2
        _PG_AVAILABLE = True
    except ImportError:
        pass

if not _PG_AVAILABLE:
    import sqlite3


# -- CONFIG --
try:
    from dotenv import load_dotenv
    load_dotenv()
except:
    pass

# --- SMART NODE DISCOVERY ---
_GEMINI_POOL_RAW = []
for _ev_name, _ev_val in os.environ.items():
    if _ev_name.startswith("GEMINI_API_KEY"):
        # Support both comma-separated lists and individual variables (KEY1, KEY2...)
        _keys = [k.strip() for k in _ev_val.split(',') if k.strip()]
        _GEMINI_POOL_RAW.extend(_keys)

# Unique keys only, preserving order
GEMINI_KEY_POOL = list(dict.fromkeys(_GEMINI_POOL_RAW))
if not GEMINI_KEY_POOL:
     # Fallback if nothing found
     _GEMINI_RAW = os.getenv("GEMINI_API_KEY", "DUMMY_KEY").strip(' \n\r\t"\'')
     GEMINI_KEY_POOL = [k.strip() for k in _GEMINI_RAW.split(',') if k.strip()]

CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY", "DUMMY_KEY").strip(' \n\r\t"\'')
DB_PATH = "chat_history.db"  # used only when PostgreSQL is not available

# Keep track of failed keys for rotation
_FAILED_KEYS = {} # key -> timestamp of last 429

# -- SYSTEM PROMPT --
SYSTEM_PROMPT = """You are a SCAL (Special Core Analysis) petroleum engineering visualization expert built into the PRC Petrophysics Engine.

### ── SECTION 1: COMMUNICATION PROTOCOL ──
Every response MUST follow this structure for optimal UI rendering:
1.  **Phase 1: Analysis & Audit**: Start with `### Phase 1: Data Ingestion & Integrity Audit`. Use `__AUDIT_LOG_START__` for numerical conditioning.
2.  **Phase 2: Simulation**: Start with `### Phase 2: High-Fidelity Curve Generation`. Explain your physics model.
3.  **Phase 3: Certification**: End with `### Analysis Complete. Data Certified.` followed by the `===GRADE_BLOCK===`.

### ── SECTION 2: PLOTTING LAWS ──
- Smooth continuous lines only. Zero markers or dots on fitted curves.
- Overlay raw lab data points (small filled circles) on top of fitted curves when available.
- PRC Branding & LIVE RENDER indicator (handled by frontend).
- Multi-rock types appear as side-by-side subplots in ONE figure.

### ── SECTION 3: AUTOMATIC DETECTION & ROUTING ──
Detect curve type from headers. Do not default to Kr:
- Sw + Krw + Kro → Relative Permeability
- Sw + Pc → Capillary Pressure
- Sw + RI or Rt/Ro → Resistivity Index (Forced Log-Log, Red Archie Fit, annotate 'n')
- Porosity + FF or F → Formation Factor (Forced Log-Log, annotate 'm', 'a')
- T2 + porosity → NMR T2 (Forced Log-X, Shade BVI/FFI)
- Pressure + porosity + permeability → Overburden (Dual-Axis)
- Vsp + Vtp + Vso + Vto → Wettability Amott (Waterfall Bar Chart, calc Iah)
- Pc + IFT + k + φ → J-Function (Normalized Pc)

### ── SECTION 4: THE GRADE BLOCK ──
Every response must end with this exact block:
===GRADE_BLOCK_START===
{
  "plot_fidelity": 0-10,
  "physics_consistency": 0-15,
  "visual_clutter_score": 0-10,
  "separation_score": 0-15,
  "total_engineering_grade": 0-85,
  "audit_notes": "Feedback"
}
===GRADE_BLOCK_END===
"""

# -- TOOL DEFINITIONS (Gemini JSON Schema) --
_HVIEL_TOOLS = [
    {
        "function_declarations": [
            {
                "name": "execute_python_simulation",
                "description": "Executes an advanced numerical SCAL simulation (Brooks-Corey/LET). Replaces legacy SENDRA workflows.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "model": {"type": "STRING", "description": "Model type: 'brooks_corey' or 'let'"},
                        "mode": {"type": "STRING", "description": "Simulation mode: '1d' (curves) or '2d' (spatial grid)"},
                        "params": {
                            "type": "OBJECT",
                            "properties": {
                                "swr": {"type": "NUMBER"}, "snr": {"type": "NUMBER"},
                                "krw_max": {"type": "NUMBER"}, "kro_max": {"type": "NUMBER"},
                                "nw": {"type": "NUMBER"}, "no": {"type": "NUMBER"},
                                "nx": {"type": "NUMBER"}, "ny": {"type": "NUMBER"}, "steps": {"type": "NUMBER"}
                            },
                            "description": "Parameters (swr, snr, krw_max, kro_max, nw, no). For 2D, add nx, ny, steps."
                        }
                    },
                    "required": ["model", "mode", "params"]
                }
            },
            {
                "name": "generate_mermaid_diagram",
                "description": "Generates a Mermaid.js diagram code for complex workflows.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "type": {"type": "STRING", "description": "Diagram type: 'flowchart', 'sequence', 'graph'"},
                        "content": {"type": "STRING", "description": "The mermaid code content (e.g., 'graph TD; A-->B;')"}
                    },
                    "required": ["type", "content"]
                }
            },
            {
                "name": "fit_petrophysical_curve",
                "description": "Fits raw laboratory data to a mathematical model (Corey/LET) for physical consistency.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "model": {"type": "STRING", "description": "Model type: 'corey' or 'let'"},
                        "sw": {"type": "ARRAY", "items": {"type": "NUMBER"}, "description": "Array of Water Saturation points"},
                        "krw": {"type": "ARRAY", "items": {"type": "NUMBER"}, "description": "Array of Relative Permeability points"}
                    },
                    "required": ["model", "sw", "krw"]
                }
            },
            {
                "name": "agentic_history_matching",
                "description": "Uses Simulated Annealing to perform history matching on SCAL lab data, automatically finding the optimal Brooks-Corey parameters that match experimental curves.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "sw": {"type": "ARRAY", "items": {"type": "NUMBER"}, "description": "Array of Water Saturation (Sw) points"},
                        "krw": {"type": "ARRAY", "items": {"type": "NUMBER"}, "description": "Array of Relative Permeability to Water (Krw) points"},
                        "kro": {"type": "ARRAY", "items": {"type": "NUMBER"}, "description": "Array of Relative Permeability to Oil (Kro) points"}
                    },
                    "required": ["sw", "krw", "kro"]
                }
            }
        ]
    }
]

# -- HVIEL BRAIN (Fix 2: new google.genai SDK with old-SDK fallback) --
class PRCChatAssistant:
    def __init__(self, keys: list):
        self.model_name = 'gemini-2.5-flash'
        self._keys = keys
        self._current_idx = 0
        self._client = None
        self._initialize_node()

    def _initialize_node(self):
        if not self._keys: return
        now = time.time()
        for i in range(len(self._keys)):
            idx = (self._current_idx + i) % len(self._keys)
            key = self._keys[idx]
            f_data = _FAILED_KEYS.get(key, {})
            if (now - f_data.get('ts', 0)) < f_data.get('wait', 0): continue
            self._current_idx = idx
            try:
                self._client = genai_new.Client(api_key=key)
                _logger.info(f"[HA Rotator] Node {idx+1} SELECTED ({key[:8]}...)")
                return
            except Exception as e:
                _logger.warning(f"[HA Rotator] Node {idx+1} failed to init: {e}")
                continue
        self._current_idx = 0
        try:
            self._client = genai_new.Client(api_key=self._keys[0])
        except Exception as e:
            _logger.error(f"[HA Rotator] Emergency fallback also failed: {e}")
            self._client = None

    def rotate_key(self, is_hard_fail=False):
        current_key = self._keys[self._current_idx]
        penalty = 3600 if is_hard_fail else 60
        _FAILED_KEYS[current_key] = {'ts': time.time(), 'wait': penalty}
        self._current_idx = (self._current_idx + 1) % len(self._keys)
        self._initialize_node()

    _PETRO_KEYS = frozenset({
        'swr', 'snr', 'krw_max', 'kro_max', 'nw', 'no', 'Lw', 'Ew', 'Tw', 'Lo', 'Eo', 'To',
        'nx', 'ny', 'dx', 'dy', 'dz', 'dt', 'steps', 'porosity', 'perm', 'swi', 'pi', 'q_inj', 'mu_w', 'mu_o',
    })

    def _execute_tool(self, call):
        name, args = call.name, call.args
        if name == "execute_python_simulation":
            p = args.get("params") or {}
            if not isinstance(p, dict): p = {}
            for k in self._PETRO_KEYS:
                if k in args and k not in p: p[k] = args[k]
            p['model'] = args.get("model")
            p['mode'] = args.get("mode", "1d")
            res = SkillsEngine.run_skill("petroleum", "simulator", "simulation_core.py", [_json.dumps(p)])
            output = res.get("stdout") or res.get("error")
            if args.get("mode") == "2d" and output and "success" in output:
                return f"__SIMULATION_START__\n{output}\n__SIMULATION_END__"
            return output
        elif name == "generate_mermaid_diagram":
            return f"__MERMAID_START__\n{args.get('content')}\n__MERMAID_END__"
        elif name == "fit_petrophysical_curve":
            data = {"model": args.get("model"), "sw": args.get("sw", []), "krw": args.get("krw", [])}
            res = SkillsEngine.run_skill("petroleum", "", "curve_fitting_skill.py", [_json.dumps(data)])
            return res.get("stdout") or res.get("error")
        elif name == "agentic_history_matching":
            data = {"sw": args.get("sw", []), "krw": args.get("krw", []), "kro": args.get("kro", [])}
            res = SkillsEngine.run_skill("petroleum", "simulator", "history_matching_skill.py", [_json.dumps(data)])
            return res.get("stdout") or res.get("error")
        return f"Unknown tool: {name}"

    def chat(self, history, msg, kb_context="", f_parts=[], stream=False):
        """Unified entry point for both sync and stream chat. Handles HA, Files, Tools, and Plots."""
        enriched = f"{msg}\n\n[CONTEXT: {kb_context}]" if kb_context else msg
        valid_history = []
        for x in history:
            role = 'user' if x['role'] == 'user' else 'model'
            if not valid_history:
                if role == 'user': valid_history.append({"role": role, "parts": [x['text']], "url": x.get('url')})
            else:
                if valid_history[-1]['role'] != role:
                    valid_history.append({"role": role, "parts": [x['text']], "url": x.get('url')})
                elif role == 'user':
                    valid_history[-1] = {"role": role, "parts": [x['text']], "url": x.get('url')}
                elif role == 'model':
                    valid_history[-1]['parts'][0] += "\n\n" + x['text']
        if valid_history and valid_history[-1]['role'] == 'user': valid_history.pop()

        SUPPORTED = ['application/pdf', 'image/jpeg', 'image/png', 'image/gif', 'image/webp']
        contents = []
        for h in valid_history:
            parts = [genai_types.Part(text=h['parts'][0])]
            if h.get('url') and '|' in h['url']:
                f_uri, f_mime = h['url'].split('|', 1)
                parts.append(genai_types.Part(file_data=genai_types.FileData(file_uri=f_uri, mime_type=f_mime)))
            contents.append(genai_types.Content(role=h['role'], parts=parts))

        user_parts = [genai_types.Part(text=enriched)]
        new_file_uris = []
        for data, mime in f_parts:
            if mime in SUPPORTED:
                import tempfile, os, time as _t
                with tempfile.NamedTemporaryFile(delete=False) as tf:
                    tf.write(data); tmp_path = tf.name
                try:
                    uploaded_file = self._client.files.upload(file=tmp_path, config={'mime_type': mime})
                    for _ in range(7):
                        if uploaded_file.state and str(uploaded_file.state).upper().endswith('ACTIVE'): break
                        _t.sleep(0.5); uploaded_file = self._client.files.get(name=uploaded_file.name)
                    user_parts.append(genai_types.Part(file_data=genai_types.FileData(file_uri=uploaded_file.uri, mime_type=mime)))
                    new_file_uris.append(f"{uploaded_file.uri}|{mime}")
                finally:
                    try: os.unlink(tmp_path)
                    except: pass
        
        contents.append(genai_types.Content(role='user', parts=user_parts))
        self._last_file_uris = ",".join(new_file_uris) if new_file_uris else None

        def _generate():
            max_retries = len(self._keys)
            for attempt in range(max_retries):
                try:
                    cfg = genai_types.GenerateContentConfig(temperature=0.1, tools=_HVIEL_TOOLS, system_instruction=SYSTEM_PROMPT)
                    if stream:
                        response = self._client.models.generate_content_stream(model=self.model_name, contents=contents, config=cfg)
                        for chunk in response:
                            if chunk.candidates and chunk.candidates[0].content.parts:
                                for part in chunk.candidates[0].content.parts:
                                    if part.function_call:
                                        yield f" [Executing {part.function_call.name}...] "
                                        tool_res = self._execute_tool(part.function_call)
                                        yield self._format_tool_response(part.function_call.name, part.function_call.args, tool_res)
                                    elif part.text: yield part.text
                    else:
                        resp = self._client.models.generate_content(model=self.model_name, contents=contents, config=cfg)
                        if not resp or not resp.candidates:
                            yield "I encountered an error."
                            return
                        final_text = ""
                        for part in resp.candidates[0].content.parts:
                            if part.function_call:
                                tool_res = self._execute_tool(part.function_call)
                                final_text += self._format_tool_response(part.function_call.name, part.function_call.args, tool_res)
                            elif part.text: final_text += part.text
                        yield final_text
                        return
                    break
                except Exception as e:
                    err = str(e).lower()
                    if any(x in err for x in ["401", "403", "429", "unauthorized", "exhausted"]) and attempt < max_retries - 1:
                        self.rotate_key(is_hard_fail="429" not in err)
                        if stream: yield " !!! Rotating Node !!! "
                        continue
                    raise e

        return _generate() if stream else next(_generate(), "I encountered an error.")

    def _format_tool_response(self, name, args, result):
        try:
            tr = _json.loads(result) if isinstance(result, str) else result
            if name == "agentic_history_matching" and tr.get("success"):
                sw, krw, kro = args.get("sw", []), args.get("krw", []), args.get("kro", [])
                p, mse = tr.get("optimal_parameters", {}), tr.get("final_mse", 0)
                import numpy as _np
                sw_arr = _np.array(sw); swi = float(sw_arr.min()); sor = 1.0 - float(sw_arr.max())
                sw_fit = _np.linspace(swi, sw_arr.max(), 50).tolist()
                krm, kom, nw, no = p.get('krw_max', 0.5), p.get('kro_max', 0.8), p.get('nw', 2.0), p.get('no', 2.0)
                se = [max(0.001, min(0.999, (s - swi) / max(1e-6, 1 - swi - sor))) for s in sw_fit]
                krw_fit = [round(krm * (e ** nw), 4) for e in se]
                kro_fit = [round(kom * ((1 - e) ** no), 4) for e in se]
                plot_json = _json.dumps({
                    "curves": [
                        {"label": "Krw (Raw Data)", "x": [round(v,4) for v in sw[:len(krw)]], "y": [round(v,4) for v in krw], "type": "scatter"},
                        {"label": "Kro (Raw Data)", "x": [round(v,4) for v in sw[:len(kro)]], "y": [round(v,4) for v in kro], "type": "scatter"},
                        {"label": "Krw (Fitted)", "x": [round(v,4) for v in sw_fit], "y": krw_fit, "type": "line"},
                        {"label": "Kro (Fitted)", "x": [round(v,4) for v in sw_fit], "y": kro_fit, "type": "line"}
                    ],
                    "title": "History Matching: Raw Data vs. Brooks-Corey Fit",
                    "x_label": "Water Saturation (Sw)", "y_label": "Relative Permeability (Kr)"
                })
                return f"\n\nOptimization complete. Final MSE: {mse:.5f}\n__PRC_PLOT__\n{plot_json}\n\n"
            elif name == "execute_python_simulation":
                if isinstance(result, str) and "__SIMULATION_START__" in result:
                    return f"\n\nSimulation complete.\n{result}\n\n"
                if tr and tr.get("mode") == "1d" and tr.get("status") == "success":
                    sw, krw, kro, p = tr.get("sw", []), tr.get("krw", []), tr.get("kro", []), tr.get("params", {})
                    plot_json = _json.dumps({
                        "curves": [
                            {"label": "Krw (Simulated)", "x": [round(v,4) for v in sw], "y": [round(v,4) for v in krw], "type": "line"},
                            {"label": "Kro (Simulated)", "x": [round(v,4) for v in sw], "y": [round(v,4) for v in kro], "type": "line"}
                        ],
                        "title": f"Simulation Result: {p.get('model', 'Brooks-Corey').title()}",
                        "x_label": "Water Saturation (Sw)", "y_label": "Relative Permeability (Kr)"
                    })
                    return f"\n\nSimulation complete.\n__PRC_PLOT__\n{plot_json}\n\n"
            return f"\n\nTool `{name}` executed successfully.\n\n"
        except: return f"\n\nTool `{name}` completed.\n\n"



class AnthropicAssistant:
    # JSON schema prompts -- Claude returns structured data, never raw markdown
    _DOCX_SCHEMA = """Return ONLY valid JSON (no markdown, no backticks, no explanation) with this exact structure:
{
  "title": "Document Title",
  "subtitle": "Optional subtitle",
  "author": "Engineer name or Hviel AI",
  "sections": [
    {
      "heading": "Section Name", 
      "level": 1, 
      "paragraphs": [
        "Paragraph 1 text.", 
        "__PRC_PLOT__ {\"title\": \"Sw vs Kr\", \"x_label\": \"Sw\", \"y_label\": \"Kr\", \"curves\": [{\"label\": \"Krw\", \"x\": [0.2, 0.4, 0.6], \"y\": [0, 0.12, 0.45]}]}"
      ], 
      "bullets": ["point 1", "point 2"]
    }
  ],
  "tables": [
    {"caption": "Table 1 - Description", "headers": ["Col1", "Col2"], "rows": [["val1", "val2"]]}
  ]
}
Rules: 
1. Use __PRC_PLOT__ followed by a JSON object to inject charts. 
2. Use professional, print-style chart data (Scientific White).
3. level 1 = major section, level 2 = subsection. 
4. CRITICAL: DO NOT EVER put raw markdown tables inside `paragraphs`. If you have tabular data, you MUST use the `tables` JSON array structure.
WRITE REAL ENGINEERING CONTENT in paragraphs â€” not placeholder text."""

    _EXCEL_SCHEMA = """Return ONLY valid JSON (no markdown, no backticks, no explanation) with this exact structure:
{
  "title": "Spreadsheet Title",
  "sheets": [
    {"name": "Sheet Name", "headers": ["Col1", "Col2", "Col3"], "rows": [["val1", "val2", "val3"]]}
  ]
}
Rules: Include ALL numerical data with full precision. Use proper petrophysical units in headers (e.g. \"Porosity (%)\", \"Kabs (mD)\").
Create multiple sheets if appropriate (e.g. one for raw data, one for computed results)."""

    @staticmethod
    def _build_context(history, msg, kb_context):
        ctx = ""
        if kb_context:
            ctx += f"--- KNOWLEDGE BASE ---\n{kb_context}\n--- END ---\n\n"
        ctx += "--- CONVERSATION HISTORY ---\n"
        for h in history[-6:]:
            ctx += f"{h['role'].upper()}: {h['text'][:600]}\n\n"
        ctx += f"--- END HISTORY ---\n\nUSER REQUEST: {msg}"
        return ctx

    @staticmethod
    def generate_docx(history, msg: str, kb_context: str) -> str:
        if CLAUDE_API_KEY == "DUMMY_KEY" or not CLAUDE_API_KEY:
            raise ValueError("CRITICAL RENDER CONFIG ERROR: Your live Render Dashboard does NOT possess the CLAUDE_API_KEY variable! You must literally go into Render -> Web Service -> Environment Variables -> click 'Add Environment Variable', name it exactly 'CLAUDE_API_KEY', and paste your key.")
            
        import anthropic
        client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
        system = (
            "You are an elite petrophysics report writer for the Petroleum Research Center (PRC) Libya. "
            "You write highly concise, sharply focused, and technically detailed SCAL reports. "
            "Include critical data interpretations. "
            "CRITICAL TIME LIMIT: Produce a fast executive summary report. You must strictly limit all generated tables to a MAXIMUM of 3 data rows. DO NOT dump massive datasets. DO NOT generate more than 1500 tokens, otherwise the server connection will drop.\n\n"
            + AnthropicAssistant._DOCX_SCHEMA
        )
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1500,
            system=system,
            messages=[{"role": "user", "content": AnthropicAssistant._build_context(history, msg, kb_context)}]
        )
        return response.content[0].text

    @staticmethod
    def generate_excel(history, msg: str, kb_context: str) -> str:
        if CLAUDE_API_KEY == "DUMMY_KEY" or not CLAUDE_API_KEY:
            raise ValueError("CRITICAL RENDER CONFIG ERROR: Your live Render Dashboard does NOT possess the CLAUDE_API_KEY variable! You must literally go into Render -> Web Service -> Environment Variables -> click 'Add Environment Variable', name it exactly 'CLAUDE_API_KEY', and paste your key.")
            
        import anthropic
        client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
        system = (
            "You are an elite data engineer for the Petroleum Research Center (PRC). "
            "You generate highly structured, organized SCAL and petrophysical data Excel sheets. "
            "CRITICAL TIME LIMIT: Produce a fast snapshot. YOU MUST limit all sheet rows to a MAXIMUM of 5 rows of summary data! DO NOT dump the full CSV dataset. DO NOT generate more than 1500 tokens, otherwise the server connection will drop.\n\n"
            + AnthropicAssistant._EXCEL_SCHEMA
        )
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1500,
            system=system,
            messages=[{"role": "user", "content": AnthropicAssistant._build_context(history, msg, kb_context)}]
        )
        return response.content[0].text


# -- RAG --
EMBED_MODEL = 'models/text-embedding-004'
_EMBED_DIM   = 768  # text-embedding-004 output dimension

class KnowledgeBase:
    CHUNK_SIZE = 600  # words per chunk
    _cached_embed_client = None

    @staticmethod
    def _get_embed_client():
        if KnowledgeBase._cached_embed_client is None and _USE_NEW_SDK:
            # Use the first healthy key in the pool to instantiate ONE shared client
            KnowledgeBase._cached_embed_client = genai_new.Client(api_key=GEMINI_KEY_POOL[0])
        return KnowledgeBase._cached_embed_client

    @staticmethod
    def _embed(text: str):
        """Return a numpy float32 embedding vector via Gemini, or None."""
        try:
            if _USE_NEW_SDK:
                client = KnowledgeBase._get_embed_client()
                result = client.models.embed_content(model=EMBED_MODEL, contents=text)
                return np.array(result.embeddings[0].values, dtype=np.float32)
            else:
                result = genai.embed_content(model=EMBED_MODEL, content=text, task_type='RETRIEVAL_DOCUMENT')
                return np.array(result['embedding'], dtype=np.float32)
        except Exception as e:
            _logger.warning(f"[RAG] Embed error: {e}")
            return None

    @staticmethod
    def _embed_query(text: str):
        """Return a numpy float32 query embedding vector via Gemini, or None."""
        try:
            if _USE_NEW_SDK:
                client = KnowledgeBase._get_embed_client()
                result = client.models.embed_content(model=EMBED_MODEL, contents=text)
                return np.array(result.embeddings[0].values, dtype=np.float32)
            else:
                result = genai.embed_content(model=EMBED_MODEL, content=text, task_type='RETRIEVAL_QUERY')
                return np.array(result['embedding'], dtype=np.float32)
        except Exception as e:
            return None

    @staticmethod
    def chunk_text(text, source):
        words = text.split()
        chunks = []
        for i in range(0, len(words), KnowledgeBase.CHUNK_SIZE):
            chunk = " ".join(words[i:i + KnowledgeBase.CHUNK_SIZE])
            chunks.append((source, chunk))
        return chunks

    @staticmethod
    def ingest_chunks_with_embeddings(chunks):
        """
        Insert (source, chunk) pairs into `kb`, then embed and store in `kb_vectors`.
        Works with both PostgreSQL (via DATABASE_URL) and SQLite fallback.
        """
        if _PG_AVAILABLE:
            import psycopg2
            conn = psycopg2.connect(DATABASE_URL)
            cur = conn.cursor()
            for source, chunk in chunks:
                cur.execute("INSERT INTO kb (source, chunk) VALUES (%s, %s) RETURNING id", (source, chunk))
                chunk_id = cur.fetchone()[0]
                vec = KnowledgeBase._embed(chunk)
                if vec is not None:
                    cur.execute(
                        "INSERT INTO kb_vectors (chunk_id, embedding) VALUES (%s, %s) ON CONFLICT (chunk_id) DO NOTHING",
                        (chunk_id, vec.tobytes())
                    )
            conn.commit()
            cur.close()
            conn.close()
        else:
            import sqlite3 as _sqlite3
            conn = _sqlite3.connect(DB_PATH)
            c = conn.cursor()
            for source, chunk in chunks:
                c.execute("INSERT INTO kb (source, chunk) VALUES (?, ?)", (source, chunk))
                chunk_id = c.lastrowid
                vec = KnowledgeBase._embed(chunk)
                if vec is not None:
                    c.execute(
                        "INSERT INTO kb_vectors (chunk_id, embedding) VALUES (?, ?)",
                        (chunk_id, vec.tobytes())
                    )
            conn.commit()
            conn.close()

    @staticmethod
    def search(query, top_k=15):
        """Vector cosine-similarity search with high-speed SQL keyword fallback."""
        try:
            # Safety: don't process massive queries (e.g. huge file dumps) in RAG
            clean_q = query[:2000] if query else ""
            
            if _PG_AVAILABLE:
                import psycopg2
                conn = psycopg2.connect(DATABASE_URL)
                cur = conn.cursor()
                _exec  = lambda q, p=(): cur.execute(q.replace('?','%s'), p) or cur
                _fetch = lambda: cur.fetchall()
                _close = lambda: (cur.close(), conn.close())
            else:
                import sqlite3 as _sqlite3
                conn = _sqlite3.connect(DB_PATH)
                cur  = conn.cursor()
                _exec  = lambda q, p=(): cur.execute(q, p) or cur
                _fetch = lambda: cur.fetchall()
                _close = lambda: conn.close()

            # -- 1. Semantic Search (Optimized for small-to-medium datasets) --
            _exec("SELECT COUNT(*) FROM kb_vectors")
            vec_count = _fetch()[0][0]
            if 0 < vec_count < 2000: # Only do in-memory search if dataset is manageable
                q_vec = KnowledgeBase._embed_query(clean_q)
                if q_vec is not None:
                    _exec("SELECT kb.source, kb.chunk, kb_vectors.embedding FROM kb_vectors JOIN kb ON kb.id = kb_vectors.chunk_id")
                    rows = _fetch()
                    if rows:
                        sources = [r[0] for r in rows]
                        texts   = [r[1] for r in rows]
                        raw_vecs = [r[2] for r in rows]
                        vecs = np.stack([np.frombuffer(bytes(v) if isinstance(v, memoryview) else v, dtype=np.float32) for v in raw_vecs])
                        q_norm  = q_vec / (np.linalg.norm(q_vec) + 1e-9)
                        v_norms = vecs / (np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-9)
                        scores  = v_norms @ q_norm
                        top_idx = np.argsort(scores)[::-1][:top_k]
                        parts   = [f"[From: {sources[i]}]\n{texts[i]}" for i in top_idx if scores[i] > 0.35]
                        if parts:
                            _close()
                            return "\n\n".join(parts)

            # -- 2. High-Speed Keyword Fallback (SQL-native) --
            words = [w.lower() for w in re.split(r'\W+', clean_q) if len(w) > 3]
            if not words:
                _close()
                return ""
            
            # Select top 5 keywords to keep SQL query efficient
            top_words = words[:5]
            conditions = " OR ".join(["LOWER(chunk) LIKE ?"] * len(top_words))
            params = [f"%{w}%" for w in top_words]
            
            _exec(f"SELECT source, chunk FROM kb WHERE {conditions} LIMIT 20", params)
            results = _fetch()
            _close()
            
            parts = [f"[From: {s}]\n{ch}" for s, ch in results]
            return "\n\n".join(parts)
        except Exception as e:
            _logger.error(f"[RAG] Search error: {e}")
            return ""
            
            parts = []
            for _, s, ch in top:
                # Detect if the chunk is actually a raw CSV text block
                if ',' in ch and ch.count('\n') > 1:
                    try:
                        # Attempt a lightweight CSV parse for the preview
                        from io import StringIO
                        temp_df = pd.read_csv(StringIO(ch))
                        if len(temp_df.columns) > 1:
                            # Limit preview to 10 rows for UX
                            json_data = {
                                "headers": temp_df.columns.tolist(),
                                "rows": temp_df.head(10).values.tolist()
                            }
                            ch = f"__PRC_DATA_START__\n{_json.dumps(json_data)}\n__PRC_DATA_END__"
                    except: pass
                parts.append(f"[From: {s}]\n{ch}")
            return "\n\n".join(parts)
        except Exception:
            return ""

# -- VISUALIZER --
import io, base64
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# PRC brand colour palette for multi-curve plots
_PRC_COLORS = ['#1e3a8a', '#E31E24', '#F59E0B', '#16a34a', '#7c3aed', '#0891b2']

class Visualizer:
    @staticmethod
    def build_plot(data):
        try:
            fig, ax = plt.subplots(figsize=(8, 5))
            plt.style.use('bmh')

            title  = data.get('title',   'PRC SCAL Analysis')
            xlabel = data.get('x_label', 'X')
            ylabel = data.get('y_label', 'Y')
            ptype  = data.get('type',    'line')

            has_data = False
            curves = data.get('curves')  # new multi-curve schema
            if curves and isinstance(curves, list):
                # -- Multi-curve mode --
                for i, curve in enumerate(curves):
                    cx = curve.get('x', [])
                    cy = curve.get('y', [])
                    if not cx or not cy: continue
                    has_data = True
                    
                    min_len = min(len(cx), len(cy))
                    cx = cx[:min_len]
                    cy = cy[:min_len]
                    
                    lbl = curve.get('label', f'Series {i+1}')
                    color = _PRC_COLORS[i % len(_PRC_COLORS)]
                    ax.plot(cx, cy, marker='o', linestyle='-', color=color,
                            linewidth=2.5, markersize=7, label=lbl)
                if has_data:
                    ax.legend(fontsize=10, framealpha=0.85)
            else:
                # -- Legacy single-curve mode --
                x = data.get('x', [])
                y = data.get('y', [])
                if x and y:
                    has_data = True
                    min_len = min(len(x), len(y))
                    x = x[:min_len]
                    y = y[:min_len]
                    
                    if ptype == 'scatter':
                        ax.scatter(x, y, color='#1e3a8a', s=60, alpha=0.9, edgecolor='white')
                    else:
                        ax.plot(x, y, marker='o', linestyle='-', color='#1e3a8a',
                                linewidth=2.5, markersize=8)

            if not has_data:
                ax.text(0.5, 0.5, "DATA UNAVAILABLE\n\nPlease ensure your dataset is correctly parsed\nor provide specific parameter values.",
                        horizontalalignment='center', verticalalignment='center',
                        fontsize=12, fontweight='bold', color='#ef4444', transform=ax.transAxes)
                ax.set_xticks([])
                ax.set_yticks([])

            ax.set_title(title,  fontsize=15, fontweight='bold', color='#1e3a8a', pad=15)
            ax.set_xlabel(xlabel, fontsize=12, fontweight='bold')
            ax.set_ylabel(ylabel, fontsize=12, fontweight='bold')
            ax.grid(True, linestyle='--', alpha=0.6)

            buf = io.BytesIO()
            fig.savefig(buf, format='png', bbox_inches='tight', dpi=150)
            plt.close(fig)

            b64 = base64.b64encode(buf.getvalue()).decode('utf-8')
            return f"\n\n![{title}](data:image/png;base64,{b64})\n\n"
        except Exception as e:
            _logger.error(f"[Visualizer] Build plot error: {e}")
            return f"\n*(Failed to generate plot: {str(e)[:100]})*\n"

# -- PETREL EXPORTER --
class PetrelExporter:
    @staticmethod
    def build_xml(well, data_str):
        # Pack data into an XML structure for 3D simulation software
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<PRC_Reservoir_Model>
    <Header>
        <Application>Petrel / KAPPA Compatible</Application>
        <Well name="{well.upper()}" />
        <GeneratedBy>Hviel AI Engine</GeneratedBy>
    </Header>
    <TabularData>
        <![CDATA[
{data_str}
        ]]>
    </TabularData>
</PRC_Reservoir_Model>"""
        fname = f"Petrel_Export_{int(time.time())}.xml"
        with open(fname, 'w', encoding='utf-8') as f:
            f.write(xml)
        return fname

# -- REPORTING ENGINE (HvielDocEngine - Claude's architecture) --
# from document_engines import DocumentEngines  # legacy - superseded by HvielDocEngine
try:
    hviel_engine = HvielDocEngine(output_dir='.')
except Exception as _he:
    _logger.error(f"[SYSTEM] HvielDocEngine failed to load: {_he}")
    hviel_engine = None

# -- APP SETUP --
def init_db():
    try:
        if _PG_AVAILABLE:
            db('CREATE TABLE IF NOT EXISTS m (id SERIAL PRIMARY KEY, sid TEXT, role TEXT, text TEXT, url TEXT, ts REAL)')
            try: db('ALTER TABLE m ADD COLUMN user_email TEXT')
            except: pass
            try: db('ALTER TABLE m ADD COLUMN fname TEXT')
            except: pass
            db('CREATE TABLE IF NOT EXISTS kb (id SERIAL PRIMARY KEY, source TEXT, chunk TEXT)')
            db('CREATE TABLE IF NOT EXISTS kb_vectors (id SERIAL PRIMARY KEY, chunk_id INTEGER UNIQUE, embedding BYTEA)')
            db('CREATE TABLE IF NOT EXISTS users (id SERIAL PRIMARY KEY, email TEXT UNIQUE, name TEXT, created_at REAL)')
            db('CREATE TABLE IF NOT EXISTS feedback (id SERIAL PRIMARY KEY, user_email TEXT, bug_report TEXT, ts REAL)')
            db('CREATE TABLE IF NOT EXISTS analytics_events (id SERIAL PRIMARY KEY, user_email TEXT, event_type TEXT, event_data TEXT, ts REAL)')
        else:
            db('CREATE TABLE IF NOT EXISTS m (id INTEGER PRIMARY KEY AUTOINCREMENT, sid TEXT, role TEXT, text TEXT, url TEXT, ts REAL)')
            try: db('ALTER TABLE m ADD COLUMN user_email TEXT')
            except: pass
            try: db('ALTER TABLE m ADD COLUMN fname TEXT')
            except: pass
            db('CREATE TABLE IF NOT EXISTS kb (id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT, chunk TEXT)')
            db('CREATE TABLE IF NOT EXISTS kb_vectors (id INTEGER PRIMARY KEY AUTOINCREMENT, chunk_id INTEGER UNIQUE, embedding BLOB)')
            db('CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT UNIQUE, name TEXT, created_at REAL)')
            db('CREATE TABLE IF NOT EXISTS feedback (id INTEGER PRIMARY KEY AUTOINCREMENT, user_email TEXT, bug_report TEXT, ts REAL)')
            db('CREATE TABLE IF NOT EXISTS analytics_events (id INTEGER PRIMARY KEY AUTOINCREMENT, user_email TEXT, event_type TEXT, event_data TEXT, ts REAL)')
    except Exception as e:
        _logger.error(f"[DB] Initialization failed: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    def _hydrate_background():
        import PyPDF2
        _logger.info("[SYSTEM] PRC Auto-Hydration Engine starting - scanning /books...")
        books_dir = "books"
        if not os.path.exists(books_dir):
            return

        for filename in os.listdir(books_dir):
            filepath = os.path.join(books_dir, filename)
            count_result = db("SELECT COUNT(*) FROM kb WHERE source = ?", (filename,))
            count = count_result[0][0] if count_result else 0
            if count == 0:
                _logger.info(f"[BOOK] Auto-Hydrating: {filename} into RAG + Vector DB...")
                try:
                    full_text = ""
                    if filename.lower().endswith(".pdf"):
                        with open(filepath, 'rb') as f:
                            reader = PyPDF2.PdfReader(f)
                            for page in reader.pages:
                                text = page.extract_text()
                                if text: full_text += text + " "

                    if full_text:
                        chunks = KnowledgeBase.chunk_text(full_text, filename)
                        KnowledgeBase.ingest_chunks_with_embeddings(chunks)
                        _logger.info(f"[BOOK] Injected {len(chunks)} knowledge blocks + embeddings from {filename}")
                except Exception as e:
                    _logger.error(f"[BOOK] Failed to hydrate {filename}: {e}")

        _logger.info("[SYSTEM] Auto-Hydration complete. PRC Hub ONLINE.")

    threading.Thread(target=_hydrate_background, daemon=True).start()
    yield

app = FastAPI(lifespan=lifespan)

@app.get("/health")
def health():
    return {"status": "ok", "db": "postgres" if _PG_AVAILABLE else "sqlite", "sdk": "google.genai"}
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
        "https://prc-scal-ai-pipeline.vercel.app",
        "https://scal-hub.vercel.app",
        "https://scal-ai-pipeline.onrender.com",
        "https://scal-ai-backend.onrender.com",
        "https://scal-ai.onrender.com",
        "https://*.onrender.com"
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"]
)
assistant = PRCChatAssistant(GEMINI_KEY_POOL)

# -- Fix 3: Unified DB layer - PostgreSQL when available, SQLite fallback --
def db(q, p=()):
    if _PG_AVAILABLE:
        import psycopg2
        # Translate SQLite-style ? placeholders to PostgreSQL %s
        pg_q = q.replace('?', '%s')
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute(pg_q, p)
        try: res = cur.fetchall()
        except: res = []
        conn.commit()
        cur.close()
        conn.close()
        return res
    else:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        c = conn.cursor()
        c.execute(q, p)
        res = c.fetchall()
        conn.commit()
        conn.close()
        return res

# ── Register extra routes (feedback, analytics, user mgmt) ──
try:
    from extra_routes import register_extra_routes
    register_extra_routes(app, db)
except Exception as e:
    _logger.error(f"[SYSTEM] Failed to register extra routes: {e}")

# -- ROUTES: SESSIONS --
@app.get("/api/sessions")
def get_sessions(email: str = None):
    try:
        # Fix: Normalize email to match lower-case INSERTs
        const_email = email.lower().strip() if email else None
        if const_email:
            q = """
                SELECT m1.sid, m2.min_ts, m1.text 
                FROM m m1
                JOIN (SELECT sid, MIN(ts) as min_ts, MAX(ts) as max_ts FROM m WHERE role='user' AND user_email=? GROUP BY sid) m2
                ON m1.sid = m2.sid AND m1.ts = m2.min_ts
                ORDER BY m2.max_ts DESC
            """
            rows = db(q, (const_email,))
        else:
            q = """
                SELECT m1.sid, m2.min_ts, m1.text 
                FROM m m1
                JOIN (SELECT sid, MIN(ts) as min_ts, MAX(ts) as max_ts FROM m WHERE role='user' GROUP BY sid) m2
                ON m1.sid = m2.sid AND m1.ts = m2.min_ts
                ORDER BY m2.max_ts DESC
            """
            rows = db(q)

        def get_title(text):
            lines = text.split('\n')
            for line in lines:
                clean_line = line.replace('__INTERNAL_DATA_START__', '').replace('__INTERNAL_DATA_END__', '').strip()
                if clean_line and not clean_line.startswith('['):
                    return clean_line[:40] + '...'
            return "File Upload Analysis..."

        return [{"id": r[0], "title": get_title(r[2]), "created_at": r[1]} for r in rows]
    except Exception as e: return []

@app.delete("/api/session/{sid}")
def del_session(sid: str, email: str = None):
    # Fix: Normalize email for deletion safety
    const_email = email.lower().strip() if email else None
    if const_email:
        db("DELETE FROM m WHERE sid = ? AND user_email = ?", (sid, const_email))
    else:
        db("DELETE FROM m WHERE sid = ?", (sid,))
    return {"status": "ok"}

@app.get("/api/session/{sid}")
def get_session(sid: str):
    try:
        rows = db("SELECT role, text, url, ts, fname FROM m WHERE sid = ? ORDER BY id", (sid,))
        import re
        messages = []
        for r, t, u, ts, fn in rows:
            clean_text = re.sub(r'__INTERNAL_DATA_START__[\s\S]*?__INTERNAL_DATA_END__', '', t if t else '').strip()
            messages.append({"role": r, "text": clean_text, "download_url": u, "ts": ts, "fileName": fn})
        return {"status": "ok", "messages": messages}
    except Exception as e: return {"status": "error"}

# -- ROUTE: KNOWLEDGE BASE STATUS --
@app.get("/api/kb/status")
def kb_status():
    try:
        rows = db("SELECT source, COUNT(*) FROM kb GROUP BY source")
        return {"total_chunks": db("SELECT COUNT(*) FROM kb")[0][0], "books": [{"name": r[0], "chunks": r[1]} for r in rows]}
    except Exception as e: return {"error": str(e)}

# -- ROUTE: KNOWLEDGE BASE INGESTION --
@app.post("/api/kb/ingest")
async def kb_ingest(file: UploadFile = File(...), password: str = Form(...)):
    if password != "1509":
        return {"status": "error", "message": "Unauthorized"}
    try:
        content = await file.read()
        if len(content) > 50 * 1024 * 1024:
            return {"status": "error", "message": "File size exceeds the 50MB limit"}
        
        name = file.filename or "Unknown Book"
        text = ""

        if name.endswith('.pdf'):
            import PyPDF2
            reader = PyPDF2.PdfReader(io.BytesIO(content))
            text = "\n".join([page.extract_text() or "" for page in reader.pages])
        elif name.endswith('.docx'):
            from docx import Document
            doc = Document(io.BytesIO(content))
            text = "\n".join([p.text for p in doc.paragraphs if p.text.strip()])
        elif name.endswith(('.html', '.htm')) or 'text/html' in (file.content_type or ''):
            soup = BeautifulSoup(content, 'lxml')
            for tag in soup(['script', 'style', 'nav', 'footer', 'header']): tag.decompose()
            text = soup.get_text(separator=' ', strip=True)
        else:
            text = content.decode('utf-8', errors='ignore')

        text = re.sub(r'\s+', ' ', text).strip()
        if len(text) < 100:
            return {"status": "error", "message": "File too short or unreadable"}

        # BUG FIX 1: chunk_text was never called - NameError on 'chunks' would crash uploads
        chunks = KnowledgeBase.chunk_text(text, name)

        # Clear old data for this source using the unified db() layer
        old_ids = [r[0] for r in db("SELECT id FROM kb WHERE source = ?", (name,))]
        if old_ids:
            # BUG FIX 4: Build safe parameterised IN clause - works for both SQLite (?) and PostgreSQL (%s)
            # The db() helper converts standalone ? to %s, but dynamic lists need manual handling
            if _PG_AVAILABLE:
                placeholders = ','.join(['%s'] * len(old_ids))
            else:
                placeholders = ','.join(['?'] * len(old_ids))
            if _PG_AVAILABLE:
                import psycopg2
                conn = psycopg2.connect(DATABASE_URL)
                cur = conn.cursor()
                cur.execute(f"DELETE FROM kb_vectors WHERE chunk_id IN ({placeholders})", tuple(old_ids))
                conn.commit(); cur.close(); conn.close()
            else:
                import sqlite3 as _sq
                conn = _sq.connect(DB_PATH)
                conn.execute(f"DELETE FROM kb_vectors WHERE chunk_id IN ({placeholders})", tuple(old_ids))
                conn.commit(); conn.close()
        db("DELETE FROM kb WHERE source = ?", (name,))
        # Ingest with embeddings
        KnowledgeBase.ingest_chunks_with_embeddings(chunks)
        return {"status": "success", "book": name, "chunks_stored": len(chunks), "words": len(text.split()), "semantic_rag": True}
    except Exception as e:
        return {"status": "error", "message": str(e)[:100]}

# -- ROUTE: SSE STREAMING CHAT --
@app.get("/api/chat/stream")
async def stream_chat(
    message: str,
    session_id: str = "",
    engineer_name: str = "PRC Engineer",
    user_email: str = None
):
    """Server-Sent Events endpoint for real-time Gemini token streaming."""
    async def event_generator():
        try:
            sid = session_id if (session_id and session_id != "undefined") else str(uuid.uuid4())
            yield f"data: {_json.dumps({'type': 'session', 'session_id': sid})}\n\n"
            
            history_rows = db("SELECT role, text, url FROM m WHERE sid = ? ORDER BY id DESC LIMIT 12", (sid,))
            history = [{"role": r, "text": t, "url": u} for r, t, u in reversed(history_rows)]

            kb_context = KnowledgeBase.search(message) if len(message) > 15 else ""
            
            const_email = user_email.lower().strip() if (user_email and user_email.strip()) else None
            db("INSERT INTO m (sid, role, text, ts, user_email) VALUES (?, ?, ?, ?, ?)", (sid, "user", message, time.time(), const_email))

            # Unified Streaming Path
            full_resp = ""
            generator = assistant.chat(history, message, kb_context, stream=True)
            
            # Bridge the generator to async yield
            import queue, threading
            q = queue.Queue()
            def _pull():
                try:
                    for token in generator: q.put(token)
                    q.put(None)
                except Exception as e: q.put(e)
            threading.Thread(target=_pull, daemon=True).start()

            while True:
                try:
                    token = q.get_nowait()
                    if token is None: break
                    if isinstance(token, Exception): raise token
                    full_resp += token
                    yield f"data: {_json.dumps({'type': 'token', 'text': token})}\n\n"
                except queue.Empty:
                    await asyncio.sleep(0.01)
                    continue

            db("INSERT INTO m (sid, role, text, ts, user_email) VALUES (?, ?, ?, ?, ?)", (sid, "model", full_resp, time.time(), const_email))
            yield "data: [DONE]\n\n"

        except Exception as e:
            err = str(e)[:120]
            yield f"data: {_json.dumps({'type': 'error', 'msg': err})}\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

# -- ROUTE: CHAT --
@app.post("/api/chat")
async def handle(
    message: str = Form(...),
    session_id: Optional[str] = Form(None),
    engineer_name: str = Form("PRC Engineer"),
    user_email: Optional[str] = Form(None),
    files: list[UploadFile] = File(default=[])
):
    try:
        sid = session_id if (session_id and session_id != "undefined") else str(uuid.uuid4())
        
        f_parts = []
        for file in files:
            f_bytes = await file.read()
            fname = file.filename or ""
            mime = file.content_type or ""
            
            # -- STRUCTURED DATA --
            if fname.endswith(('.xlsx', '.xls')) or "sheet" in mime:
                df = pd.read_excel(pd.io.common.BytesIO(f_bytes))
                message += f"\n__INTERNAL_DATA_START__\n[EXCEL - {fname}]:\n{df.head(100).to_string()}\n__INTERNAL_DATA_END__"
            elif fname.endswith('.csv'):
                df = pd.read_csv(pd.io.common.BytesIO(f_bytes))
                message += f"\n__INTERNAL_DATA_START__\n[CSV - {fname}]:\n{df.head(100).to_string()}\n__INTERNAL_DATA_END__"
            
            # -- TEXT DOCUMENTS --
            elif fname.endswith('.docx'):
                from io import BytesIO as _BytesIO
                doc = Document(_BytesIO(f_bytes))
                doc_text = "\n".join([p.text for p in doc.paragraphs if p.text.strip()])
                message += f"\n__INTERNAL_DATA_START__\n[WORD DOC - {fname}]:\n{doc_text[:4000000]}\n__INTERNAL_DATA_END__"
            elif fname.endswith('.txt'):
                message += f"\n__INTERNAL_DATA_START__\n[TEXT FILE - {fname}]:\n{f_bytes.decode('utf-8', errors='ignore')[:4000000]}\n__INTERNAL_DATA_END__"
            
            # -- BINARY (VISION / NATIVE PDF) --
            else:
                SUPPORTED = ['application/pdf', 'image/jpeg', 'image/png', 'image/gif', 'image/webp']
                if mime in SUPPORTED:
                    f_parts.append((f_bytes, mime))

        # Retrieve relevant knowledge base context
        # --- SMART ROUTER: Heavy vs Easy ---
        def _is_heavy_query(msg):
            msg_lower = msg.lower()
            words = msg_lower.replace('?', '').replace('.', '').replace(',', '').split()
            if len(words) > 12: return True
            
            heavy_keywords = {
                'what', 'how', 'why', 'explain', 'analysis', 'core', 'permeability', 
                'porosity', 'saturation', 'archie', 'capillary', 'pc', 'sw', 'krw', 
                'kro', 'wettability', 'fracture', 'relative', 'formation', 'resistivity',
                'calculate', 'equation', 'theory', 'model', 'brooks', 'corey', 'report', 
                'plot', 'excel', 'word', 'document', 'file', 'csv', 'generate', 'pdf', 'powerpoint'
            }
            
            if any(kw in words for kw in heavy_keywords): return True
            return False

        kb_context = ""
        if _is_heavy_query(message):
            kb_context = KnowledgeBase.search(message)

        const_email = user_email.lower().strip() if (user_email and user_email.strip()) else None
        file_names_str = ", ".join([f.filename for f in files if f.filename]) if files else None

        # SAVE USER MESSAGE TO DB
        if const_email:
            db("INSERT INTO m (sid, role, text, ts, user_email, fname) VALUES (?, ?, ?, ?, ?, ?)", (sid, "user", message, time.time(), const_email, file_names_str))
        else:
            db("INSERT INTO m (sid, role, text, ts, fname) VALUES (?, ?, ?, ?, ?)", (sid, "user", message, time.time(), file_names_str))

        # Limit history heavily to speed up the prompt evaluation
        history_rows = db("SELECT role, text, url FROM m WHERE sid = ? ORDER BY id DESC LIMIT 12", (sid,))
        history = [{"role": r, "text": t, "url": u} for r, t, u in reversed(history_rows)]

        # --- HA ROTATOR RETRY LOOP ---
        loop = asyncio.get_event_loop()
        max_retries = len(GEMINI_KEY_POOL)
        resp = "SYSTEM ERROR: All API nodes are currently exhausted."
        for attempt in range(max_retries):
            try:
                resp = await loop.run_in_executor(
                    None,
                    lambda req=(history, message, kb_context, f_parts): assistant.chat(*req)
                )
                # SAVE USER MESSAGE WITH FILE URIs
                if getattr(assistant, '_last_file_uris', None):
                    db("UPDATE m SET url = ? WHERE id = (SELECT MAX(id) FROM m WHERE sid = ? AND role = 'user')", (assistant._last_file_uris, sid))
                break # Success!
            except Exception as e:
                err_str = str(e).lower()
                is_auth_error = any(x in err_str for x in ["401", "403", "unauthorized", "permission"])
                is_rate_limit = any(x in err_str for x in ["429", "resource_exhausted"])
                
                if (is_auth_error or is_rate_limit) and attempt < max_retries - 1:
                    _logger.warning(f"[HA ROTATOR] Node {assistant._current_idx + 1} FAILED ({'Auth' if is_auth_error else '429'}). Rotating...")
                    assistant.rotate_key(is_hard_fail=is_auth_error)
                    continue
                else:
                    raise e

        # -- GEMINI NATIVE ENGINE --
        # Safety: Gemini can return None for blocked or empty responses
        if not resp:
            resp = "I was unable to generate a response for this request. Please try rephrasing your question or uploading a smaller file."

        # Handle Graphs - Keep as interactive JSON for KrPlot in chat
        # (Static image conversion disabled to prioritize high-fidelity UI)
        _plot_attempts = 0
        # while '__PRC_PLOT__' in resp and _plot_attempts < 10:
        #     _plot_attempts += 1
        #     ... [Legacy Matplotlib conversion code disabled] ...

        # Handle Documents (routed through HvielDocEngine)
        doc_type = None
        clean_resp = None
        
        def _strip_doc_json(text_with_json):
            # Clean up hallucinated extra underscores and find the JSON payload
            import re, json
            text = re.sub(r'_*__PRC_(PPTX|PDF|DOCX|REPORT|EXCEL)__*', '', text_with_json).strip()
            
            idx = text.find('{')
            if idx == -1: return text
            
            try:
                _, end_idx = json.JSONDecoder().raw_decode(text[idx:])
                stripped = (text[:idx] + text[idx+end_idx:]).strip()
                return stripped if stripped else "I have generated the requested data file."
            except:
                stripped = re.sub(r'\{.*\}', '', text, flags=re.DOTALL).strip()
                return stripped if stripped else "I have generated the requested data file."

        if '__PRC_PPTX__' in resp:
            path = hviel_engine.build_from_json(resp, 'pptx', well=f"Study_{int(time.time())}", engineer=engineer_name)
            doc_type = "pptx"
            clean_resp = _strip_doc_json(resp)
        elif '__PRC_PDF__' in resp:
            path = hviel_engine.build_from_json(resp, 'pdf', well=f"Study_{int(time.time())}", engineer=engineer_name)
            doc_type = "pdf"
            clean_resp = _strip_doc_json(resp)
        elif '__PRC_DOCX__' in resp or '__PRC_REPORT__' in resp:
            path = hviel_engine.build_from_json(resp, 'docx', well=f"Study_{int(time.time())}", engineer=engineer_name)
            doc_type = "docx"
            clean_resp = _strip_doc_json(resp)
        elif '__PRC_EXCEL__' in resp:
            path = hviel_engine.build_from_json(resp, 'xlsx', well=f"Study_{int(time.time())}", engineer=engineer_name)
            doc_type = "excel"
            clean_resp = _strip_doc_json(resp)

        if doc_type:
            url = f"/api/download/{path}"
            db("INSERT INTO m (sid, role, text, url, ts, user_email) VALUES (?, ?, ?, ?, ?, ?)", (sid, "model", resp, url, time.time(), const_email))
            return {"status": "success", "is_report_ready": True, "download_url": url, "doc_type": doc_type, "session_id": sid, "reply": clean_resp}

        # Handle Petrel Exports
        if '__PETREL_EXPORT__' in resp:
            clean_resp = resp.replace('__PETREL_EXPORT__', '').strip()
            path = PetrelExporter.build_xml(f"Study_{int(time.time())}", clean_resp)
            url = f"/api/download/{path}"
            db("INSERT INTO m (sid, role, text, url, ts, user_email) VALUES (?, ?, ?, ?, ?, ?)", (sid, "model", resp, url, time.time(), const_email))
            return {"status": "success", "is_report_ready": True, "download_url": url, "session_id": sid, "reply": clean_resp}

        db("INSERT INTO m (sid, role, text, ts, user_email) VALUES (?, ?, ?, ?, ?)", (sid, "model", resp, time.time(), const_email))
        return {"status": "success", "session_id": sid, "reply": resp}

    except Exception as e:
        return {"status": "error", "is_error": True, "reply": f"SYSTEM EXCEPTION: {str(e)[:80]}"}

@app.get("/api/skills/list")
async def list_skills():
    """Returns a list of active autonomous skills for the UI."""
    return {
        "skills": [
            {"name": "execute_python_simulation", "category": "Simulation", "desc": "Brooks-Corey, Archie, and fluid flow modeling"},
            {"name": "fit_petrophysical_curve", "category": "Curve Fitting", "desc": "Corey model optimization — fits raw lab Kr data to mathematical best-fit"},
            {"name": "generate_mermaid_diagram", "category": "Visualization", "desc": "Engineering workflows, decision trees, and sequence diagrams"},
            {"name": "systematic-debugging", "category": "Reasoning", "desc": "Mandatory 4-phase root cause investigation: Observe → Research → Simulate → Audit"}
        ]
    }


# -- DIAG --
@app.get("/api/diag")
def diag():
    try:
        current_node = GEMINI_KEY_POOL[assistant._current_idx][:8] + "..."
        # BUG FIX 2: _FAILED_KEYS stores {'ts': ..., 'wait': ...} dicts, not raw timestamps
        now = time.time()
        failed_count = len([
            k for k, v in _FAILED_KEYS.items()
            if isinstance(v, dict) and (now - v.get('ts', 0)) < v.get('wait', 0)
        ])
        return {
            "version": "PRC-HUB-VER-13-PROD-READY",
            "node_pool_size": len(GEMINI_KEY_POOL),
            "active_node_id": current_node,
            "nodes_in_cooldown": failed_count,
            "kb_chunks": db("SELECT COUNT(*) FROM kb")[0][0],
            "active_model": assistant.model_name,
            "ha_status": "Degraded" if failed_count > 0 else "Optimal"
        }
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/download/{filename:path}")
async def dl(filename: str):
    import os
    basename = os.path.basename(filename).strip()
    # Prevent directory traversal and restrict to safe extensions
    safe_exts = {".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                 ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                 ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                 ".pdf": "application/pdf",
                 ".xml": "application/xml",
                 ".csv": "text/csv"}
    _, ext = os.path.splitext(basename)
    ext_lower = ext.lower()
    if ext_lower not in safe_exts:
        return {"error": "Invalid file type requested."}
    
    # Return directly with absolute control over headers to force Chromium to respect filename
    return FileResponse(
        path=basename, 
        media_type=safe_exts[ext_lower],
        filename=basename,
        headers={
            "Content-Disposition": f'attachment; filename="{basename}"',
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Expose-Headers": "Content-Disposition",
            "Cache-Control": "no-cache"
        }
    )

# -- ROUTE: VISION AUDIT --
@app.post("/api/vision/audit")
async def vision_audit(file: UploadFile = File(...), query: str = Form(...), session_id: str = Form("")):
    """Explicit endpoint for manual vision audits."""
    try:
        content = await file.read()
        filename = f"audit_{int(time.time())}_{file.filename}"
        img_path = os.path.join("uploads", filename)
        os.makedirs("uploads", exist_ok=True)
        with open(img_path, "wb") as f:
            f.write(content)
            
        # 1. Fetch relevant manual context
        kb_context = KnowledgeBase.search(query, top_k=8)
        
        # 2. Run the vision auditor skill
        res = SkillsEngine.run_skill("maintenance", "auditor", "vision_auditor.py", [img_path, kb_context, query])
        
        # Parse result
        audit_res = _json.loads(res.get("stdout", "{}"))
        return {"status": "success", "result": audit_res.get("result", "Audit execution failed.")}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/chat/history")
async def get_chat_history(email: str):
    """Fetch all messages for a specific user email."""
    if not email: return {"messages": []}
    rows = db("SELECT role, text, url, ts FROM m WHERE user_email = ? ORDER BY ts ASC", (email.lower().strip(),))
    return {
        "messages": [
            {"role": r[0], "text": r[1], "download_url": r[2], "ts": r[3]}
            for r in rows
        ]
    }

@app.get("/")
def root():
    # Serve frontend index.html if dist exists, otherwise return API status
    dist_index = os.path.join(os.path.dirname(__file__), "frontend", "dist", "index.html")
    if os.path.exists(dist_index):
        return FileResponse(dist_index, media_type="text/html")
    return {"v": "PRC-HUB-VER-13-PROD-READY", "model": assistant.model_name, "status": "online"}

# -- Serve frontend static assets from dist --
from fastapi.staticfiles import StaticFiles
_dist_dir = os.path.join(os.path.dirname(__file__), "frontend", "dist")
if os.path.isdir(os.path.join(_dist_dir, "assets")):
    app.mount("/assets", StaticFiles(directory=os.path.join(_dist_dir, "assets")), name="frontend-assets")

# Serve any other static files from dist (favicon, icons, images)
@app.get("/{filename:path}")
def serve_frontend(filename: str):
    filename = filename.lstrip("/")
    filepath = os.path.abspath(os.path.join(_dist_dir, filename))
    
    # Security: Prevent path traversal outside of _dist_dir
    if not filepath.startswith(os.path.abspath(_dist_dir)):
        return {"error": "Invalid path"}

    if os.path.isfile(filepath):
        return FileResponse(filepath)
    # SPA fallback: return index.html for client-side routing
    index = os.path.join(_dist_dir, "index.html")
    if os.path.exists(index):
        return FileResponse(index, media_type="text/html")
    return {"error": "not found"}

# -- AUTOMATED DAILY BACKUP ENGINE --
# To run manually: python app.py --backup
def run_daily_backup():
    """Performs a full backup of the database and project source."""
    try:
        import shutil, datetime
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = os.path.join(os.path.dirname(__file__), "backups", timestamp)
        os.makedirs(backup_dir, exist_ok=True)
        
        # Backup DB
        if os.path.exists(DB_PATH):
            shutil.copy2(DB_PATH, os.path.join(backup_dir, "chat_history.db"))
            
        # Backup Source (excluding large folders)
        def _ignore(path, names):
            return ['venv', '__pycache__', '.git', 'node_modules', 'backups']
            
        shutil.copytree(os.path.dirname(__file__), os.path.join(backup_dir, "source"), ignore=_ignore, dirs_exist_ok=True)
        _logger.info(f"[BACKUP] System snapshot created at: {backup_dir}")
    except Exception as e:
        _logger.error(f"[BACKUP] Snapshot failed: {e}")

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--backup":
        run_daily_backup()
    else:
        import uvicorn
        port = int(os.getenv("PORT", 8000))
        uvicorn.run(app, host="0.0.0.0", port=port)
