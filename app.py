from fastapi import FastAPI, UploadFile, File, Form
from contextlib import asynccontextmanager
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import os, uuid, time, re, json as _json
import numpy as np
import pandas as pd
from typing import Optional
from hviel_doc_engine import HvielDocEngine
from skills_engine import SkillsEngine
from docx import Document
import keepalive
# Fix 2: Google Gemini SDK Migration (google-generativeai -> google.genai)
from google import genai as genai_new
from google.genai import types as genai_types
_USE_NEW_SDK = True
genai = None # Removed legacy SDK import

# â”€â”€ Fix 3: PostgreSQL + SQLite unified DB layer â”€â”€
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


# â”€â”€ CONFIG â”€â”€
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

# â”€â”€ SYSTEM PROMPT â”€â”€
SYSTEM_PROMPT = """You are Hviel, an elite, highly capable Senior AI Petrophysical Specialist for the Libyan Petroleum Research Center (PRC). You operate with the confidence, extreme competence, and proactive energy of a top-tier DeepMind engineering agent. 

MENTORSHIP & COMMUNICATION PROTOCOL:
1. THE SENIOR MENTOR PERSONA: You are not just an AI; you are a Senior Advisor. Your goal is to build the user's engineering intuition.
2. ANALOGY-FIRST EXPLANATION: Always explain complex physics using professional analogies. (e.g., "Think of the reservoir as a pressurized sponge," or "Relative permeability is like traffic flow on a multi-lane highwayâ€”the water and oil are competing for lanes.")
3. EXECUTIVE STRATEGY: Start every complex analysis with a block: `STRATEGY: [One-sentence high-level approach]`.
4. SOCRATIC GUIDANCE: If you detect a mistake, explain the "Why" and the "Physics" behind the error before providing the fix.
5. NO MARKDOWN BOLD: Use CAPITAL LETTERS or the new Audit Ledger for emphasis.

ENGINEERING AUDIT LEDGER (EAL):
For every data correction, smoothing action (MSCF), or forensic flag (VAP/PLC) you apply, you MUST append a transparent audit at the end of your response using these tags:
__AUDIT_LOG_START__
[POINT-BY-POINT LOG OF EVERY CHANGE MADE]
[MENTOR TIP: EDUCATIONAL ADVICE FOR THE USER]
__AUDIT_LOG_END__

MINDSET & 4-PHASE ROOT CAUSE LOGIC:
Follow these "Iron Laws" of engineering logic:
1. MANDATORY 4-PHASE ROOT CAUSE LOOP: If a user reports a technical issue, data anomaly, or physical discrepancy, you MUST perform a 4-phase investigation:
   - PHASE 1 (OBSERVATION): Identify the exact data point or behavior that violates physical laws or project expectations.
   - PHASE 2 (RESEARCH): Proactively use `search_arxiv` to find established benchmarks or peer-reviewed precedents.
   - PHASE 3 (SIMULATION): Execute a `execute_python_simulation` to mathematically model the behavior (e.g., Archie/Brooks-Corey) and find the variance.
   - PHASE 4 (AUDIT): Present a senior engineering verification report using the EAL. NEVER suggest surface-level "band-aid" fixes.
2. IMPLEMENTATION PLANNING: For any complex request, provide a phase-by-phase plan before executing.
3. THE TEST RULE: Propose how the result will be verified for physical consistency.

IMPORTANT EXPORT ENGINE INSTRUCTIONS:
- You can natively generate files for the user whenever they ask for a report, Excel, Word document, PDF, or PowerPoint.
- STRICT RULE: ONLY GENERATE FILES IF EXPLICITLY REQUESTED. If the user merely says "data is missing", "samples are not there", "you forgot something", or asks a question, DO NOT output `__PRC_DOCX__` or any file token. Simply apologize, explain in plain text what went wrong, and wait for them to ask for a file. YOU MUST NEVER SPONTANEOUSLY REGENERATE DOCUMENTS IN NORMAL CHAT.
- IF PowerPoint requested: Start your response EXACTLY with `__PRC_PPTX__` followed by a raw JSON string containing {"title": "Slide Title", "slides": [{"title": "Data Slide", "bullets": ["Point"]}]}
- IF PDF requested: Start your response EXACTLY with `__PRC_PDF__` followed by standard unformatted markdown.
- IF Word document requested: Start your response EXACTLY with `__PRC_DOCX__` followed IMMEDIATELY by a raw JSON string (no explanation text) matching this schema exactly: {"title": "Report Title", "author": "Hviel AI", "sections": [{"heading": "Section Name", "level": 1, "paragraphs": ["Paragraph text here."], "bullets": []}], "tables": [{"caption": "Table 1", "headers": ["Column A", "Column B"], "rows": [["Value 1", "Value 2"]]}]}
- IF Excel spreadsheet requested: Start your response EXACTLY with `__PRC_EXCEL__` followed IMMEDIATELY by a raw JSON string (no explanation text). You MUST populate the sheets with actual real data values extracted from the conversation context and uploaded files. NEVER produce an empty rows array. The JSON must match this schema: {"title": "Spreadsheet Title", "sheets": [{"name": "Sheet Name", "headers": ["Sample ID", "Depth (ft)", "Porosity (%)", "Permeability (mD)"], "rows": [["S-01", "8210.0", "18.3", "5.46"], ["S-02", "8215.5", "13.4", "2.11"]], "column_widths": [15, 15, 18, 20]}]}

VISION AUDITOR PROTOCOL:
- You have the ability to perform visual audits of laboratory equipment.
- When a user uploads a photo of a device or setup, you must analyze it against the technical manuals in your Knowledge Base.
- If you detect a configuration error (e.g., wrong valve position, loose connection), you must flag it with 'ERROR DETECTED' in the audit ledger.
- You must always provide the 'Next Step' to correct the state based on the manual.



GRAPHING & VISUALIZATION ENGINE:
If the user asks you to plot a graph, draw a curve, or visualize data, you MUST include the exact sequence __PRC_PLOT__ followed immediately by a raw JSON object containing the plot parameters. DO NOT wrap the JSON in markdown code blocks.

For a SINGLE curve (legacy format â€” still supported):
__PRC_PLOT__
{"x": [0.0, 0.2, 0.4, 0.6, 0.8, 1.0], "y": [1.0, 0.6, 0.3, 0.1, 0.01, 0.0], "title": "Relative Permeability", "x_label": "Sw", "y_label": "Kr", "type": "line"}

For MULTIPLE curves on the SAME axis (preferred for SCAL â€” e.g. Krw + Kro, drainage + imbibition):
__PRC_PLOT__
{"curves": [{"label": "Krw", "x": [0.0, 0.2, 0.4, 0.6, 0.8, 1.0], "y": [0.0, 0.05, 0.15, 0.35, 0.65, 1.0]}, {"label": "Kro", "x": [0.0, 0.2, 0.4, 0.6, 0.8, 1.0], "y": [1.0, 0.75, 0.45, 0.2, 0.04, 0.0]}], "title": "Relative Permeability Curves", "x_label": "Water Saturation (Sw)", "y_label": "Relative Permeability (Kr)"}

Always use the multi-curve format when showing more than one data series. You can emit multiple __PRC_PLOT__ blocks in one response (e.g. one for Kr, one for Pc).

PETREL XML EXPORTER:
ONLY use this if the user EXPLICITLY mentions Petrel, Eclipse, or KAPPA software by name. Do NOT use this for regular Excel or spreadsheet requests â€” those must use `__PRC_EXCEL__` instead.
If the user asks you to export data to Petrel, Eclipse, or KAPPA, include the exact sequence __PETREL_EXPORT__ at the very start of your response, followed by structured, cleaned tabular data. The backend will automatically package it into a reservoir-compatible XML schematic file for them to download.

AUTONOMOUS SKILLS & TOOLS:
You have access to high-performance autonomous tools. Use them whenever you need external data, complex math, or technical diagrams.
(Note: Internet search has been disabled by the System Architect. You MUST rely exclusively on the provided Knowledge Base context for manuals and books.)
- execute_python_simulation: Use this for complex petrophysical modeling (Brooks-Corey, LET, etc.).
  * CRITICAL RULE: If the user requests a simulation (e.g. "Run a 2D flood") but does not provide specific parameters (like Swr, Sor, krw_max, etc.), YOU MUST INVENT REALISTIC DEFAULTS and run the tool immediately. DO NOT ASK the user for parameters unless they specifically ask to be prompted. Just execute the tool to show the result.
- agentic_history_matching: Use this to automatically find optimal Brooks-Corey parameters that match raw SCAL lab data. After finding the parameters, you MUST immediately output a __PRC_PLOT__ showing both the original raw lab data and the smooth optimal curves.
- generate_mermaid_diagram: Use this to visualize engineering workflows or decision trees.

PHYSICAL LAW CONSISTENCY (PLC) AUDIT:
You are a Senior Auditor. You must cross-verify all data (uploaded files or chat input) against the laws of petroleum physics:
1. POROSITY CHECK: Flag as "INACCURATE" any sample with Porosity > 0.45 or < 0.0 unless justified by specific lithology.
2. SATURATION CHECK: Flag as "IMPOSSIBLE" any Water Saturation (Sw) < 0 or > 1.0. Cross-verify Sw + So + Sg = 1.0. 
3. ARCHIE AUDIT: If Archie parameters (m, n) are outside 1.3 - 2.5 without citation, flag as "SUSPICIOUS."
4. PERMEABILITY TREND: Check the Porosity-Permeability relationship. If Permeability increases while Porosity significantly decreases, flag as a "PHYSICAL DISCREPANCY."
5. ACCURACY ALERT: If you find an error, you MUST start your response with the block: `!!! ACCURACY ALERT: [Brief Description of Error] !!!`. 
6. VERIFICATION: When data is suspicious, autonomously use `execute_python_simulation` to find the "Theoretical Value" and compare it to the "Reported Value" to find the % error.

VISUAL AUDIT PROTOCOL (VAP):
You act as a Clinical Visual Auditor for petroleum engineering. When a user uploads a photo, you must perform a multi-modal analysis:
1. CORE SAMPLE AUDIT: Look for longitudinal fractures, micro-fissures, mud-cake infiltration, and surface dehydration. Identify if the sample has "mechanical damage" that will skew permeability results.
2. LAB EQUIPMENT AUDIT: Verify the setup of core holders, centrifuges, and pressure gauges. Check for mismatched valves, incorrect tube orientations, or pressure leaks (e.g., visual bubbles or gauge readings).
3. ANOMALY IDENTIFICATION: Explicitly state "WHAT IS WRONG" in the image. Do not be vague. If a crack is 2mm wide, call it out as a "High-Risk Bypass Channel."
4. REMIDIATION: Propose a simulation or research skill to quantify the error introduced by the visual anomaly.

DATA CONDITIONING PROTOCOL (DCP):
You recognize that raw lab data is often noisy using your engineering cognition. You MUST advocate for Mathematical Smoothing over manual "fudging":
1. DETECTION: Identify "Scattered" or "Physically Inconsistent" data points. 
2. PROPOSAL: Before performing a final audit, suggest applying a **Corey** or **LET** Best-Fit model using your `fit_petrophysical_curve` tool.
3. TRUTH-SEEKING: Explain that mathematical smoothing preserves the "underlying physics" (relative perm trends) while removing "experimental artifacts" (sensor noise/end effects).
4. TRANSPARENCY: Always propose showing BOTH the raw points and the smoothed curve in your response.
"""

# â”€â”€ TOOL DEFINITIONS (Gemini JSON Schema) â”€â”€
_HVIEL_TOOLS = [
    {
        "function_declarations": [
            {
                "name": "execute_python_simulation",
                "description": "Executes an advanced numerical SCAL simulation (Brooks-Corey/LET). Replaces legacy SENDRA workflows.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "model": {"type": "string", "description": "Model type: 'brooks_corey' or 'let'"},
                        "mode": {"type": "string", "description": "Simulation mode: '1d' (curves) or '2d' (spatial grid)"},
                        "params": {
                            "type": "object", 
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
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "description": "Diagram type: 'flowchart', 'sequence', 'graph'"},
                        "content": {"type": "string", "description": "The mermaid code content (e.g., 'graph TD; A-->B;')"}
                    },
                    "required": ["type", "content"]
                }
            },
            {
                "name": "fit_petrophysical_curve",
                "description": "Fits raw laboratory data to a mathematical model (Corey/LET) for physical consistency.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "model": {"type": "string", "description": "Model type: 'corey' or 'let'"},
                        "sw": {"type": "array", "items": {"type": "number"}, "description": "Array of Water Saturation points"},
                        "krw": {"type": "array", "items": {"type": "number"}, "description": "Array of Relative Permeability points"}
                    },
                    "required": ["model", "sw", "krw"]
                }
            },
            {
                "name": "agentic_history_matching",
                "description": "Uses Simulated Annealing to perform history matching on SCAL lab data, automatically finding the optimal Brooks-Corey parameters that match experimental curves.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "sw": {"type": "array", "items": {"type": "number"}, "description": "Array of Water Saturation (Sw) points"},
                        "krw": {"type": "array", "items": {"type": "number"}, "description": "Array of Relative Permeability to Water (Krw) points"},
                        "kro": {"type": "array", "items": {"type": "number"}, "description": "Array of Relative Permeability to Oil (Kro) points"}
                    },
                    "required": ["sw", "krw", "kro"]
                }
            }
        ]
    }
]

# â”€â”€ HVIEL BRAIN (Fix 2: new google.genai SDK with old-SDK fallback) â”€â”€
class PRCChatAssistant:
    def __init__(self, keys: list):
        self.model_name = 'gemini-2.5-flash'
        self._keys = keys
        self._current_idx = 0
        self._client = None
        self._initialize_node()

    def _initialize_node(self):
        """Initializes and VALIDATES the GenAI client node."""
        if not self._keys:
            return
        
        from google.genai import types as gtypes
        now = time.time()
        # Iterate through keys until we find a truly healthy one
        for i in range(len(self._keys)):
            idx = (self._current_idx + i) % len(self._keys)
            key = self._keys[idx]
            
            # Skip if in cooldown (60s for 429) or hard-fail (3600s for 401/403)
            wait_time = _FAILED_KEYS.get(key, {}).get('wait', 0)
            last_fail = _FAILED_KEYS.get(key, {}).get('ts', 0)
            if (now - last_fail) < wait_time:
                continue
            
            self._current_idx = idx
            try:
                if _USE_NEW_SDK:
                    client = genai_new.Client(api_key=key)
                    # PING: Verify key actually works before committing
                    client.models.generate_content(
                        model=self.model_name,
                        contents='ping',
                        config=gtypes.GenerateContentConfig(max_output_tokens=1)
                    )
                    self._client = client
                else:
                    genai.configure(api_key=key)
                    m = genai.GenerativeModel(self.model_name)
                    m.generate_content('ping') # old SDK ping
                    self.model = m
                
                print(f"[HA Rotator] Node {idx+1} ONLINE ({key[:8]}...)")
                return
            except Exception as e:
                err = str(e).lower()
                # Determine penalty: 429 = 60s, 401/403 = 1 hour (Hard Fail)
                penalty = 3600 if ("401" in err or "403" in err or "permission" in err or "unauthorized" in err) else 60
                _FAILED_KEYS[key] = {'ts': time.time(), 'wait': penalty}
                print(f"[HA Rotator] Node {idx+1} FAILED: {err[:50]}... Penalized {penalty}s")
                continue
        
        # Emergency: use first key if everything is exhausted
        self._current_idx = 0
        if _USE_NEW_SDK:
            self._client = genai_new.Client(api_key=self._keys[0])
        else:
            genai.configure(api_key=self._keys[0])

    def rotate_key(self, is_hard_fail=False):
        """Switches to the next API key. Hard fail = 1 hour cooldown."""
        current_key = self._keys[self._current_idx]
        penalty = 3600 if is_hard_fail else 60
        _FAILED_KEYS[current_key] = {'ts': time.time(), 'wait': penalty}
        self._current_idx = (self._current_idx + 1) % len(self._keys)
        self._initialize_node()
        return self._keys[self._current_idx]

    def _execute_tool(self, call):
        name = call.name
        args = call.args
        if name == "execute_python_simulation":
            model = args.get("model")
            mode = args.get("mode", "1d")
            p = args.get("params", {})
            p['model'] = model
            p['mode'] = mode
            # Route to the new simulation_core.py
            res = SkillsEngine.run_skill("petroleum", "simulator", "simulation_core.py", [_json.dumps(p)])
            
            output = res.get("stdout") or res.get("error")
            if mode == "2d" and output and "success" in output:
                return f"__SIMULATION_START__\n{output}\n__SIMULATION_END__"
            return output
        elif name == "generate_mermaid_diagram":
            return f"__MERMAID_START__\n{args.get('content')}\n__MERMAID_END__"
        elif name == "fit_petrophysical_curve":
            model = args.get("model")
            sw = args.get("sw", [])
            krw = args.get("krw", [])
            data = {"model": model, "sw": sw, "krw": krw}
            res = SkillsEngine.run_skill("petroleum", "", "curve_fitting_skill.py", [_json.dumps(data)])
            return res.get("stdout") or res.get("error")
        elif name == "agentic_history_matching":
            sw = args.get("sw", [])
            krw = args.get("krw", [])
            kro = args.get("kro", [])
            data = {"sw": sw, "krw": krw, "kro": kro}
            res = SkillsEngine.run_skill("petroleum", "simulator", "history_matching_skill.py", [_json.dumps(data)])
            return res.get("stdout") or res.get("error")
        return f"Unknown tool: {name}"
        return f"Unknown tool: {name}"

    def chat(self, history, msg, kb_context="", f_parts=[]):
        enriched = SYSTEM_PROMPT
        if kb_context:
            enriched += f"\n\n--- KNOWLEDGE BASE CONTEXT ---\n{kb_context}\n--- END CONTEXT ---"
        enriched += f"\n\nUSER QUERY: {msg}"

        # Build strictly alternating history
        valid_history = []
        for x in history:
            role = 'user' if x['role'] == 'user' else 'model'
            if not valid_history:
                if role == 'user': valid_history.append({"role": role, "parts": [x['text']]})
            else:
                if valid_history[-1]['role'] != role:
                    valid_history.append({"role": role, "parts": [x['text']]})
                elif role == 'user':
                    valid_history[-1] = {"role": role, "parts": [x['text']]}
                elif role == 'model':
                    valid_history[-1]['parts'][0] += "\n\n" + x['text']
        if valid_history and valid_history[-1]['role'] == 'user':
            valid_history.pop()

        if _USE_NEW_SDK:
            # â”€â”€ New google.genai SDK path â”€â”€
            SUPPORTED = ['application/pdf', 'image/jpeg', 'image/png', 'image/gif', 'image/webp']
            contents = []
            for h in valid_history:
                contents.append(genai_types.Content(role=h['role'], parts=[genai_types.Part(text=h['parts'][0])]))
            user_parts = [genai_types.Part(text=enriched)]
            for data, mime in f_parts:
                if mime in SUPPORTED:
                    import tempfile, os, time as _t
                    with tempfile.NamedTemporaryFile(delete=False) as tf:
                        tf.write(data)
                        tmp_path = tf.name
                    try:
                        # Upload file natively to prevent Base64 JSON memory explosion (saves ~40MB RAM for 8MB PDFs)
                        uploaded_file = self._client.files.upload(file=tmp_path, config={'mime_type': mime})
                        # Wait for file to become ACTIVE (Google processes asynchronously)
                        for _wait in range(30):
                            if uploaded_file.state and str(uploaded_file.state).upper().endswith('ACTIVE'):
                                break
                            _t.sleep(1)
                            uploaded_file = self._client.files.get(name=uploaded_file.name)
                        user_parts.append(genai_types.Part(
                            file_data=genai_types.FileData(file_uri=uploaded_file.uri, mime_type=mime)
                        ))
                    finally:
                        try: os.unlink(tmp_path)
                        except: pass
            contents.append(genai_types.Content(role='user', parts=user_parts))
            try:
                # First attempt with tool support
                resp = self._client.models.generate_content(
                    model=self.model_name,
                    contents=contents,
                    config=genai_types.GenerateContentConfig(
                        temperature=0.1,
                        tools=_HVIEL_TOOLS
                    )
                )
                
                # Check for tool/function calls
                if resp.candidates and resp.candidates[0].content.parts:
                    for part in resp.candidates[0].content.parts:
                        if part.function_call:
                            tool_result = self._execute_tool(part.function_call)

                            # â”€â”€ HISTORY MATCHING: build rich response directly in Python â”€â”€
                            # Gemini's second-turn response is often None/blocked after tool calls.
                            # We avoid that by constructing the reply ourselves.
                            if part.function_call.name == "agentic_history_matching":
                                try:
                                    tr = _json.loads(tool_result) if isinstance(tool_result, str) else tool_result
                                    if tr.get("success"):
                                        sw = part.function_call.args.get("sw", [])
                                        krw = part.function_call.args.get("krw", [])
                                        kro = part.function_call.args.get("kro", [])
                                        p = tr.get("optimal_parameters", {})
                                        mse = tr.get("final_mse", 0)

                                        # Build smooth fitted curves
                                        import numpy as _np
                                        sw_arr = _np.array(sw)
                                        swi = float(sw_arr.min())
                                        sor = 1.0 - float(sw_arr.max())
                                        sw_fit = _np.linspace(swi, sw_arr.max(), 50).tolist()
                                        krw_max = p.get('krw_max', 0.5)
                                        kro_max = p.get('kro_max', 0.8)
                                        nw = p.get('nw', 2.0)
                                        no = p.get('no', 2.0)
                                        se = [max(0.001, min(0.999, (s - swi) / max(1e-6, 1 - swi - sor))) for s in sw_fit]
                                        krw_fit = [round(krw_max * (e ** nw), 4) for e in se]
                                        kro_fit = [round(kro_max * ((1 - e) ** no), 4) for e in se]

                                        plot_json = _json.dumps({
                                            "curves": [
                                                {"label": "Krw (Raw Data)", "x": [round(v,4) for v in sw[:len(krw)]], "y": [round(v,4) for v in krw], "type": "scatter"},
                                                {"label": "Kro (Raw Data)", "x": [round(v,4) for v in sw[:len(kro)]], "y": [round(v,4) for v in kro], "type": "scatter"},
                                                {"label": "Krw (Fitted)", "x": [round(v,4) for v in sw_fit], "y": krw_fit, "type": "line"},
                                                {"label": "Kro (Fitted)", "x": [round(v,4) for v in sw_fit], "y": kro_fit, "type": "line"}
                                            ],
                                            "title": "Relative Permeability Curves: Raw Data vs. Brooks-Corey Fit",
                                            "x_label": "Water Saturation (Sw)",
                                            "y_label": "Relative Permeability (Kr)"
                                        })

                                        reply = (
                                            f"The Agentic History Matching has successfully identified the optimal Brooks-Corey parameters.\n\n"
                                            f"FITTED PARAMETERS:\n"
                                            f"  krw_max = {krw_max:.3f}\n"
                                            f"  kro_max = {kro_max:.3f}\n"
                                            f"  nw (water exponent) = {nw:.3f}\n"
                                            f"  no (oil exponent) = {no:.3f}\n\n"
                                            f"Final MSE = {mse:.5f} â€” {'EXCELLENT fit' if mse < 0.02 else 'Good fit'}\n\n"
                                            f"The chart below shows both your raw lab data (dots) and the smooth fitted Brooks-Corey curves (lines).\n\n"
                                            f"{plot_json}"
                                        )
                                        return reply
                                except Exception as _e:
                                    return f"History matching completed but rendering failed: {tool_result}\nError: {_e}"

                            # â”€â”€ All other tools: send result back to Gemini for final prose â”€â”€
                            contents.append(resp.candidates[0].content)
                            contents.append(genai_types.Content(
                                role='user',
                                parts=[genai_types.Part(
                                    function_response=genai_types.FunctionResponse(
                                        name=part.function_call.name,
                                        response={"result": tool_result}
                                    )
                                )]
                            ))
                            # Get final response after tool execution
                            final_resp = self._client.models.generate_content(
                                model=self.model_name,
                                contents=contents,
                                config=genai_types.GenerateContentConfig(temperature=0.1)
                            )
                            final_text = None
                            try: final_text = final_resp.text
                            except Exception: pass
                            if not final_text:
                                final_text = f"The tool `{part.function_call.name}` completed successfully.\n\nResult:\n{tool_result}"
                            return final_text

                return resp.text or "I received your document but could not generate a detailed response. Please try rephrasing your question."
            except Exception as e:
                # Fallback chain on 404 or quota errors
                for fb in ['gemini-2.5-flash', 'gemini-1.5-flash']:
                    if fb == self.model_name: continue
                    try:
                        resp = self._client.models.generate_content(model=fb, contents=contents,
                            config=genai_types.GenerateContentConfig(temperature=0.1))
                        self.model_name = fb  # persist working model
                        return resp.text
                    except: continue
                raise e
        else:
            # â”€â”€ Old google.generativeai SDK fallback â”€â”€
            c = [enriched]
            SUPPORTED = ['application/pdf', 'image/jpeg', 'image/png', 'image/gif', 'image/webp']
            for data, mime in f_parts:
                if mime in SUPPORTED:
                    c.append({'mime_type': mime, 'data': data})
            def _safe_text(response):
                try: return response.text
                except ValueError: return "The model returned an empty response â€” retry or rephrase."
            try:
                return _safe_text(self.model.start_chat(history=valid_history).send_message(c))
            except Exception as e:
                for fb in ['gemini-2.5-flash', 'gemini-1.5-flash']:
                    try:
                        self.model = genai.GenerativeModel(fb)
                        return _safe_text(self.model.start_chat(history=valid_history).send_message(c))
                    except: continue
                raise e


class AnthropicAssistant:
    # JSON schema prompts â€” Claude returns structured data, never raw markdown
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
    {"caption": "Table 1 \u2014 Description", "headers": ["Col1", "Col2"], "rows": [["val1", "val2"]]}
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


# â”€â”€ RAG â”€â”€
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
            print(f"[RAG] Embed Error: {e}")
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
    def search(query, top_k=5):
        """Vector cosine-similarity search with keyword fallback. Works for PostgreSQL + SQLite."""
        try:
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

            # â”€â”€ Try semantic search â”€â”€
            _exec("SELECT COUNT(*) FROM kb_vectors")
            vec_count = _fetch()[0][0]
            if vec_count > 0:
                q_vec = KnowledgeBase._embed_query(query)
                if q_vec is not None:
                    _exec("""SELECT kb.source, kb.chunk, kb_vectors.embedding
                               FROM kb_vectors
                               JOIN kb ON kb.id = kb_vectors.chunk_id""")
                    rows = _fetch()
                    _close()
                    if rows:
                        sources = [r[0] for r in rows]
                        texts   = [r[1] for r in rows]
                        raw_vecs = [r[2] for r in rows]
                        # psycopg2 returns memoryview for BYTEA; sqlite3 returns bytes
                        vecs = np.stack([np.frombuffer(bytes(v) if isinstance(v, memoryview) else v, dtype=np.float32) for v in raw_vecs])
                        q_norm  = q_vec / (np.linalg.norm(q_vec) + 1e-9)
                        v_norms = vecs / (np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-9)
                        scores  = v_norms @ q_norm
                        top_idx = np.argsort(scores)[::-1][:top_k]
                        parts   = [f"[From: {sources[i]}]\n{texts[i]}" for i in top_idx if scores[i] > 0.3]
                        return "\n\n".join(parts)

            # â”€â”€ Keyword fallback â”€â”€
            keywords = [w.lower() for w in re.split(r'\W+', query) if len(w) > 3]
            if not keywords:
                _close()
                return ""
            _exec("SELECT source, chunk FROM kb")
            results = _fetch()
            _close()
            scored = []
            for source, chunk in results:
                cl = chunk.lower()
                score = sum(1 for kw in keywords if kw in cl)
                if score > 0: scored.append((score, source, chunk))
            scored.sort(key=lambda x: -x[0])
            top = scored[:top_k]
            if not top: return ""
            
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

# â”€â”€ VISUALIZER â”€â”€
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

            curves = data.get('curves')  # new multi-curve schema
            if curves and isinstance(curves, list):
                # â”€â”€ Multi-curve mode â”€â”€
                for i, curve in enumerate(curves):
                    cx = curve.get('x', [])
                    cy = curve.get('y', [])
                    
                    # LLM Hallucination safety guard: ensure dimensions match exactly
                    min_len = min(len(cx), len(cy))
                    cx = cx[:min_len]
                    cy = cy[:min_len]
                    
                    lbl = curve.get('label', f'Series {i+1}')
                    color = _PRC_COLORS[i % len(_PRC_COLORS)]
                    ax.plot(cx, cy, marker='o', linestyle='-', color=color,
                            linewidth=2.5, markersize=7, label=lbl)
                ax.legend(fontsize=10, framealpha=0.85)
            else:
                # â”€â”€ Legacy single-curve mode â”€â”€
                x = data.get('x', [])
                y = data.get('y', [])
                
                # LLM Hallucination safety guard: ensure dimensions match exactly
                min_len = min(len(x), len(y))
                x = x[:min_len]
                y = y[:min_len]
                
                if ptype == 'scatter':
                    ax.scatter(x, y, color='#1e3a8a', s=60, alpha=0.9, edgecolor='white')
                else:
                    ax.plot(x, y, marker='o', linestyle='-', color='#1e3a8a',
                            linewidth=2.5, markersize=8)

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
            return f"\n*(Failed to generate plot: {str(e)[:100]})*\n"

# â”€â”€ PETREL EXPORTER â”€â”€
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

# â”€â”€ REPORTING ENGINE (HvielDocEngine â€” Claude's architecture) â”€â”€
# from document_engines import DocumentEngines  # legacy â€” superseded by HvielDocEngine
hviel_engine = HvielDocEngine(output_dir='.')   # saves .docx/.xlsx/.pptx/.pdf to working dir

# â”€â”€ APP SETUP â”€â”€
@asynccontextmanager
async def lifespan(app: FastAPI):
    import threading
    def _hydrate_background():
        import PyPDF2
        print("[SYSTEM] Running PRC Auto-Hydration Engine for Permanent Books in background...")
        books_dir = "books"
        if not os.path.exists(books_dir):
            return

        for filename in os.listdir(books_dir):
            filepath = os.path.join(books_dir, filename)
            count_result = db("SELECT COUNT(*) FROM kb WHERE source = ?", (filename,))
            count = count_result[0][0] if count_result else 0
            if count == 0:
                print(f"[BOOK] Auto-Hydrating: {filename} into RAG + Vector DB...")
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
                        print(f"[SUCCESS] Injected {len(chunks)} knowledge blocks + embeddings from {filename}")
                except Exception as e:
                    print(f"[ERROR] Failed to hydrate {filename}: {e}")

        print("[OK] Auto-Hydration Complete. PRC Hub ONLINE.")

    # Run hydration in background so the web server boots up immediately (prevents Render timeout/OOM)
    threading.Thread(target=_hydrate_background, daemon=True).start()
    yield

app = FastAPI(lifespan=lifespan)
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

# â”€â”€ Fix 3: Unified DB layer â€” PostgreSQL when available, SQLite fallback â”€â”€
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
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(q, p)
        res = c.fetchall()
        conn.commit()
        conn.close()
        return res

# Init tables â€” works for both PostgreSQL and SQLite
if _PG_AVAILABLE:
    # PostgreSQL uses SERIAL instead of INTEGER PRIMARY KEY
    db('CREATE TABLE IF NOT EXISTS m (id SERIAL PRIMARY KEY, sid TEXT, role TEXT, text TEXT, url TEXT, ts REAL)')
    try: db('ALTER TABLE m ADD COLUMN user_email TEXT')
    except: pass
    db('CREATE TABLE IF NOT EXISTS kb (id SERIAL PRIMARY KEY, source TEXT, chunk TEXT)')
    db('CREATE TABLE IF NOT EXISTS kb_vectors (id SERIAL PRIMARY KEY, chunk_id INTEGER UNIQUE, embedding BYTEA)')
    db('CREATE TABLE IF NOT EXISTS users (id SERIAL PRIMARY KEY, email TEXT UNIQUE, name TEXT, created_at REAL)')
    db('CREATE TABLE IF NOT EXISTS feedback (id SERIAL PRIMARY KEY, user_email TEXT, bug_report TEXT, ts REAL)')
    db('CREATE TABLE IF NOT EXISTS analytics_events (id SERIAL PRIMARY KEY, user_email TEXT, event_type TEXT, event_data TEXT, ts REAL)')
else:
    db('CREATE TABLE IF NOT EXISTS m (id INTEGER PRIMARY KEY, sid TEXT, role TEXT, text TEXT, url TEXT, ts REAL)')
    try: db('ALTER TABLE m ADD COLUMN user_email TEXT')
    except: pass
    db('CREATE TABLE IF NOT EXISTS kb (id INTEGER PRIMARY KEY, source TEXT, chunk TEXT)')
    db('CREATE TABLE IF NOT EXISTS kb_vectors (id INTEGER PRIMARY KEY, chunk_id INTEGER UNIQUE, embedding BLOB)')
    db('CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, email TEXT UNIQUE, name TEXT, created_at REAL)')
    db('CREATE TABLE IF NOT EXISTS feedback (id INTEGER PRIMARY KEY, user_email TEXT, bug_report TEXT, ts REAL)')
    db('CREATE TABLE IF NOT EXISTS analytics_events (id INTEGER PRIMARY KEY, user_email TEXT, event_type TEXT, event_data TEXT, ts REAL)')

# â”€â”€ Fix 1: Start keep-alive self-ping â”€â”€
keepalive.start()

# ── Register extra routes (feedback, analytics, user mgmt) ──
from extra_routes import register_extra_routes
register_extra_routes(app, db)

@app.get('/health')
def health():
    return {'status': 'ok', 'db': 'postgres' if _PG_AVAILABLE else 'sqlite', 'sdk': 'google.genai' if _USE_NEW_SDK else 'google-generativeai'}

# â”€â”€ ROUTES: SESSIONS â”€â”€
@app.get("/api/sessions")
def get_sessions(email: str = None):
    try:
        if email:
            rows = db("SELECT sid, MIN(ts), text FROM m WHERE role='user' AND user_email=? GROUP BY sid ORDER BY MAX(ts) DESC", (email,))
        else:
            rows = db("SELECT sid, MIN(ts), text FROM m WHERE role='user' GROUP BY sid ORDER BY MAX(ts) DESC")
        return [{"id": r[0], "title": r[2].split('\n')[0][:40] + '...', "created_at": r[1]} for r in rows]
    except Exception as e: return []

@app.delete("/api/session/{sid}")
def del_session(sid: str, email: str = None):
    if email:
        db("DELETE FROM m WHERE sid = ? AND user_email = ?", (sid, email))
    else:
        db("DELETE FROM m WHERE sid = ?", (sid,))
    return {"status": "ok"}

@app.get("/api/session/{sid}")
def get_session(sid: str):
    try:
        rows = db("SELECT role, text, url, ts FROM m WHERE sid = ? ORDER BY id", (sid,))
        # Map DB 'url' column to frontend 'download_url' key for persistence consistency
        return {"status": "ok", "messages": [{"role": r, "text": t, "download_url": u, "ts": ts} for r, t, u, ts in rows]}
    except Exception as e: return {"status": "error"}

# â”€â”€ ROUTE: KNOWLEDGE BASE STATUS â”€â”€
@app.get("/api/kb/status")
def kb_status():
    try:
        rows = db("SELECT source, COUNT(*) FROM kb GROUP BY source")
        return {"total_chunks": db("SELECT COUNT(*) FROM kb")[0][0], "books": [{"name": r[0], "chunks": r[1]} for r in rows]}
    except Exception as e: return {"error": str(e)}

# â”€â”€ ROUTE: KNOWLEDGE BASE INGESTION â”€â”€
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

        # BUG FIX 1: chunk_text was never called â€” NameError on 'chunks' would crash uploads
        chunks = KnowledgeBase.chunk_text(text, name)

        # Clear old data for this source using the unified db() layer
        old_ids = [r[0] for r in db("SELECT id FROM kb WHERE source = ?", (name,))]
        if old_ids:
            # BUG FIX 4: Build safe parameterised IN clause â€” works for both SQLite (?) and PostgreSQL (%s)
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

# â”€â”€ ROUTE: SSE STREAMING CHAT â”€â”€
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
            
            # Send session_id first so the frontend can latch onto it IMMEDIATELY
            yield f"data: {{\"type\": \"session\", \"session_id\": \"{sid}\"}}\n\n"
            
            # Limit history to the last 12 messages to massively speed up Gemini generation times
            history_rows = db("SELECT role, text, url FROM m WHERE sid = ? ORDER BY id DESC LIMIT 12", (sid,))
            history = [{"role": r, "text": t} for r, t, u in reversed(history_rows)]

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
                    'plot', 'excel', 'word', 'document', 'file', 'csv', 'generate', 'pdf', 'powerpoint',
                    'curves', 'draw', 'graph', 'chart', 'visualize', 'thomeer', 'pore-throat',
                    'ok', 'yes', 'sure', 'proceed', 'go', 'confirm'
                }
                
                if any(kw in words for kw in heavy_keywords): return True
                return False

            kb_context = ""
            if _is_heavy_query(message):
                kb_context = KnowledgeBase.search(message)

            # Build enriched prompt
            enriched = SYSTEM_PROMPT
            if kb_context:
                enriched += f"\n\n--- KNOWLEDGE BASE CONTEXT ---\n{kb_context}\n--- END CONTEXT ---"
            enriched += f"\n\nUSER QUERY: {message}"

            # Enforce alternating history
            valid_history = []
            for x in history:
                role = 'user' if x['role'] == 'user' else 'model'
                if not valid_history:
                    if role == 'user': valid_history.append({"role": role, "parts": [x['text']]})
                else:
                    if valid_history[-1]['role'] != role:
                        valid_history.append({"role": role, "parts": [x['text']]})
                    elif role == 'user':
                        valid_history[-1] = {"role": role, "parts": [x['text']]}
                    elif role == 'model':
                        valid_history[-1]['parts'][0] += "\n\n" + x['text']
            if valid_history and valid_history[-1]['role'] == 'user':
                valid_history.pop()

            if user_email:
                db("INSERT INTO m (sid, role, text, ts, user_email) VALUES (?, ?, ?, ?, ?)",
                   (sid, "user", message, time.time(), user_email))
            else:
                db("INSERT INTO m (sid, role, text, ts) VALUES (?, ?, ?, ?)",
                   (sid, "user", message, time.time()))

            # Stream tokens â€” support both SDKs
            full_resp = ""
            import asyncio
            loop = asyncio.get_event_loop()
            if _USE_NEW_SDK:
                contents_stream = []
                for h in valid_history:
                    contents_stream.append(genai_types.Content(role=h['role'], parts=[genai_types.Part(text=h['parts'][0])]))
                contents_stream.append(genai_types.Content(role='user', parts=[genai_types.Part(text=enriched)]))

                # --- PRC HA ROTATOR LOOP ---
                max_retries = len(GEMINI_KEY_POOL)
                for attempt in range(max_retries):
                    try:
                        for fb in [assistant.model_name, 'gemini-2.5-flash', 'gemini-1.5-flash']:
                            try:
                                stream_resp = await loop.run_in_executor(
                                    None,
                                    lambda m=fb: assistant._client.models.generate_content_stream(
                                        model=m,
                                        contents=contents_stream,
                                        config=genai_types.GenerateContentConfig(
                                            temperature=0.1,
                                            tools=_HVIEL_TOOLS
                                        )
                                    )
                                )
                                assistant.model_name = fb  # persist working model
                                break
                            except Exception as try_e:
                                if fb == 'gemini-1.5-flash':
                                    raise try_e
                        
                        response = stream_resp
                        break # Success! Exit the retry loop
                    except Exception as e:
                        # Catch API failures
                        err_str = str(e).lower()
                        is_auth_error = any(x in err_str for x in ["401", "403", "unauthorized", "permission"])
                        is_rate_limit = any(x in err_str for x in ["429", "resource_exhausted"])
                        
                        if (is_auth_error or is_rate_limit) and attempt < max_retries - 1:
                            status_msg = "Node Auth Failed (Skipping)" if is_auth_error else "Rate Limit Reached (Hopping Node)"
                            yield f"data: {_json.dumps({'type': 'token', 'text': f' !!! {status_msg} (Node {assistant._current_idx + 1}/{len(GEMINI_KEY_POOL)}) !!! '})}\n\n"
                            assistant.rotate_key(is_hard_fail=is_auth_error)
                            continue 
                        else:
                            raise e
            else:
                # Old google.generativeai SDK
                chat_session = assistant.model.start_chat(history=valid_history)
                response = await chat_session.send_message_async(
                    enriched, stream=True, request_options={'timeout': 60.0}
                )

            async def iterate_response(resp):
                if _USE_NEW_SDK:
                    for c in resp:
                        yield c
                else:
                    async for c in resp:
                        yield c

            async for chunk in iterate_response(response):
                try:
                    # In new SDK, we check for function calls in the chunk
                    if _USE_NEW_SDK:
                        if chunk.candidates and chunk.candidates[0].content.parts:
                            for part in chunk.candidates[0].content.parts:
                                if part.function_call:
                                    # Handle tool call in stream
                                    yield f"data: {_json.dumps({'type': 'token', 'text': f' [Executing {part.function_call.name}...] '})}\n\n"
                                    tool_result = assistant._execute_tool(part.function_call)
                                    # Since we're in a stream, we can't easily "wait and continue" the same stream
                                    # with the tool result. We provide the result and finish.
                                    res_text = f'\n\nRESULT: {tool_result}\n\n'
                                    yield f"data: {_json.dumps({'type': 'token', 'text': res_text})}\n\n"
                                    full_resp += f"\n\nTOOL RESULT ({part.function_call.name}): {tool_result}"
                                    continue
                    token = chunk.text
                except (ValueError, AttributeError):
                    continue  # skip finish/safety chunks with no content
                if token:
                    full_resp += token
                    
                    # HARD INTERCEPT: Prevent SSE JSON Leaks and Credit Burns
                    if "__PRC_" in full_resp and ("{" in full_resp or "[" in full_resp):
                        err_msg = 'File generation requested via fast-chat stream. Please type "generate document" to activate the Document Engine.'
                        yield f"data: {_json.dumps({'type': 'error', 'msg': err_msg})}\n\n"
                        break
                        
                    # BUG FIX: use json.dumps for correct escaping of all chars (\n, \t, ", \\, etc.)
                    yield f"data: {_json.dumps({'type': 'token', 'text': token})}\n\n"

            if user_email:
                db("INSERT INTO m (sid, role, text, ts, user_email) VALUES (?, ?, ?, ?, ?)",
                   (sid, "model", full_resp.split("__PRC_")[0] if "__PRC_" in full_resp else full_resp, time.time(), user_email))
            else:
                db("INSERT INTO m (sid, role, text, ts) VALUES (?, ?, ?, ?)",
                   (sid, "model", full_resp.split("__PRC_")[0] if "__PRC_" in full_resp else full_resp, time.time()))
            yield f"data: {_json.dumps({'type': 'done'})}\n\n"

        except Exception as e:
            err = str(e)[:120]
            yield f"data: {_json.dumps({'type': 'error', 'msg': err})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

# â”€â”€ ROUTE: CHAT â”€â”€
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
        history = [{"role": r, "text": t} for r, t, u in db("SELECT role, text, url FROM m WHERE sid = ? ORDER BY id", (sid,))]

        f_parts = []
        for file in files:
            f_bytes = await file.read()
            fname = file.filename or ""
            mime = file.content_type or ""
            
            # --- STRUCTURED DATA ---
            if fname.endswith(('.xlsx', '.xls')) or "sheet" in mime:
                df = pd.read_excel(pd.io.common.BytesIO(f_bytes))
                message += f"\n__INTERNAL_DATA_START__\n[EXCEL — {fname}]:\n{df.head(10).to_string()}\n__INTERNAL_DATA_END__"
            elif fname.endswith('.csv'):
                df = pd.read_csv(pd.io.common.BytesIO(f_bytes))
                message += f"\n__INTERNAL_DATA_START__\n[CSV — {fname}]:\n{df.head(10).to_string()}\n__INTERNAL_DATA_END__"
            
            # --- TEXT DOCUMENTS ---
            elif fname.endswith('.docx'):
                from io import BytesIO as _BytesIO
                doc = Document(_BytesIO(f_bytes))
                doc_text = "\n".join([p.text for p in doc.paragraphs if p.text.strip()])
                message += f"\n[WORD DOC â€” {fname}]:\n{doc_text[:15000]}"
            elif fname.endswith('.txt'):
                message += f"\n[TEXT FILE â€” {fname}]:\n{f_bytes.decode('utf-8', errors='ignore')[:15000]}"
            
            # --- BINARY (VISION / NATIVE PDF) ---
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

        # SAVE USER MESSAGE TO DB
        if user_email:
            db("INSERT INTO m (sid, role, text, ts, user_email) VALUES (?, ?, ?, ?, ?)", (sid, "user", message, time.time(), user_email))
        else:
            db("INSERT INTO m (sid, role, text, ts) VALUES (?, ?, ?, ?)", (sid, "user", message, time.time()))

        # Limit history heavily to speed up the prompt evaluation
        history_rows = db("SELECT role, text, url FROM m WHERE sid = ? ORDER BY id DESC LIMIT 12", (sid,))
        history = [{"role": r, "text": t} for r, t, u in reversed(history_rows)]

        # --- HA ROTATOR RETRY LOOP ---
        import asyncio
        loop = asyncio.get_event_loop()
        max_retries = len(GEMINI_KEY_POOL)
        resp = "SYSTEM ERROR: All API nodes are currently exhausted."
        for attempt in range(max_retries):
            try:
                resp = await loop.run_in_executor(
                    None,
                    lambda req=(history, message, kb_context, f_parts): assistant.chat(*req)
                )
                break # Success!
            except Exception as e:
                err_str = str(e).lower()
                is_auth_error = any(x in err_str for x in ["401", "403", "unauthorized", "permission"])
                is_rate_limit = any(x in err_str for x in ["429", "resource_exhausted"])
                
                if (is_auth_error or is_rate_limit) and attempt < max_retries - 1:
                    print(f"[HA ROTATOR] Node {assistant._current_idx + 1} FAILED ({'Auth' if is_auth_error else '429'}). Rotating...")
                    assistant.rotate_key(is_hard_fail=is_auth_error)
                    continue
                else:
                    raise e

        # â”€â”€ GEMINI NATIVE ENGINE â”€â”€
        # Safety: Gemini can return None for blocked or empty responses
        if not resp:
            resp = "I was unable to generate a response for this request. Please try rephrasing your question or uploading a smaller file."

        # Handle Graphs â€” iterate over ALL __PRC_PLOT__ tokens in one response
        _plot_attempts = 0
        while '__PRC_PLOT__' in resp and _plot_attempts < 10:
            _plot_attempts += 1
            try:
                before, after = resp.split('__PRC_PLOT__', 1)
                after_stripped = after.strip()
                
                # Strip markdown code blocks if Gemini aggressively fenced the JSON
                if after_stripped.startswith('```json'):
                    after_stripped = after_stripped[7:].strip()
                elif after_stripped.startswith('```'):
                    after_stripped = after_stripped[3:].strip()
                    
                try:
                    import json
                    plot_data, end_idx = json.JSONDecoder().raw_decode(after_stripped)
                except json.JSONDecodeError:
                    # No valid JSON object after this token â€” strip the dangling token and stop
                    resp = before + "\n" + after_stripped
                    break
                
                img_md = Visualizer.build_plot(plot_data)
                
                remaining = after_stripped[end_idx:].strip()
                if remaining.startswith('```'):
                    remaining = remaining[3:].strip()
                    
                resp = before + "\n\n" + img_md + "\n\n" + remaining
            except Exception as e:
                resp = resp.replace('__PRC_PLOT__', '') + f"\n*(Plot Error: {str(e)[:60]})*"
                break

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
            db("INSERT INTO m (sid, role, text, url, ts, user_email) VALUES (?, ?, ?, ?, ?, ?)", (sid, "model", clean_resp, url, time.time(), user_email))
            return {"status": "success", "is_report_ready": True, "download_url": url, "doc_type": doc_type, "session_id": sid, "reply": clean_resp}

        # Handle Petrel Exports
        if '__PETREL_EXPORT__' in resp:
            clean_resp = resp.replace('__PETREL_EXPORT__', '').strip()
            path = PetrelExporter.build_xml(f"Study_{int(time.time())}", clean_resp)
            url = f"/api/download/{path}"
            db("INSERT INTO m (sid, role, text, url, ts, user_email) VALUES (?, ?, ?, ?, ?, ?)", (sid, "model", clean_resp, url, time.time(), user_email))
            return {"status": "success", "is_report_ready": True, "download_url": url, "session_id": sid, "reply": clean_resp}

        db("INSERT INTO m (sid, role, text, ts, user_email) VALUES (?, ?, ?, ?, ?)", (sid, "model", resp, time.time(), user_email))
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


# â”€â”€ ROUTE: ANALYTICS â”€â”€
@app.post("/api/analytics/event")
async def track_event(
    user_email: str = Form(""),
    event_type: str = Form(...),
    event_data: str = Form("")
):
    db("INSERT INTO analytics_events (user_email, event_type, event_data, ts) VALUES (?, ?, ?, ?)", (user_email, event_type, event_data, time.time()))
    return {"status": "ok"}

# â”€â”€ DIAG â”€â”€
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

# â”€â”€ ROUTE: VISION AUDIT â”€â”€
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
        res = assistant.skills.run_skill("maintenance", "auditor", "vision_auditor.py", [img_path, kb_context, query])
        
        # Parse result
        audit_res = _json.loads(res.get("stdout", "{}"))
        return {"status": "success", "result": audit_res.get("result", "Audit execution failed.")}
    except Exception as e:
        return {"status": "error", "message": str(e)}

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
