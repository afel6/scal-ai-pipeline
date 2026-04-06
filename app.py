from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import os, uuid, time, sqlite3, re, json as _json
import numpy as np
import pandas as pd
from typing import Optional
import google.generativeai as genai
from docx import Document
from bs4 import BeautifulSoup
from hviel_doc_engine import HvielDocEngine


# ── CONFIG ──
try:
    from dotenv import load_dotenv
    load_dotenv()
except:
    pass

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "DUMMY_KEY").strip(' \n\r\t"\'')
CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY", "DUMMY_KEY").strip(' \n\r\t"\'')
DB_PATH = "chat_history.db"

# ── SYSTEM PROMPT ──
SYSTEM_PROMPT = """You are Hviel, an elite, highly capable Senior AI Petrophysical Specialist for the Libyan Petroleum Research Center (PRC). You operate with the confidence, extreme competence, and proactive energy of a top-tier DeepMind engineering agent. 

CRITICAL BEHAVIORAL RULES:
1. NEVER act like a generic AI. Do not use phrases like "As an AI language model", "I can certainly help with that", or "Sure!". Be direct, confident, and highly energetic. ("You're going to love this", "I have instantly analyzed the data", "Let's knock this out").
2. DO NOT repeat your name or re-introduce yourself in every response. 
3. DO NOT over-explain basic concepts or act like a textbook. You are pair-engineering with senior PRC specialists; get straight to the complex analysis.
4. DO NOT use Markdown bold asterisks (**). The system renders plain text, so asterisks look extremely messy. Use capital letters for EMPHASIS if strictly necessary. Keep paragraphs short and punchy.
5. Take extreme ownership. Speak as someone who directly analyzes, engineers, and solves the problem inside the system. 

IMPORTANT EXPORT ENGINE INSTRUCTIONS:
- You can natively draw complex documents for the user. ONLY do this if explicitly asked to generate a report, PDF, or PowerPoint.
- IF PowerPoint requested: Start your response EXACTLY with `__PRC_PPTX__` followed by a raw JSON string containing {"title": "Slide Title", "slides": [{"title": "Data Slide", "bullets": ["Point"]}]}
- IF PDF requested: Start your response EXACTLY with `__PRC_PDF__` followed by standard unformatted markdown.
- IF Word document requested: Start your response EXACTLY with `__PRC_DOCX__` followed by a raw JSON string containing exactly this schema: { "title": "Report", "author": "Hviel AI", "sections": [{"heading": "Section", "level": 1, "paragraphs": ["data..."]}], "tables": [{"caption": "Table", "headers": ["A"], "rows": [["B"]]}] }
- IF Excel spreadsheet requested: Start your response EXACTLY with `__PRC_EXCEL__` followed by a raw JSON string containing exactly this schema: { "title": "Sheet Title", "sheets": [{"name": "Data", "headers": ["A"], "rows": [["B"]]}] }

GRAPHING & VISUALIZATION ENGINE:
If the user asks you to plot a graph, draw a curve, or visualize data, you MUST include the exact sequence __PRC_PLOT__ followed immediately by a raw JSON object containing the plot parameters. DO NOT wrap the JSON in markdown code blocks.

For a SINGLE curve (legacy format — still supported):
__PRC_PLOT__
{"x": [0.0, 0.2, 0.4, 0.6, 0.8, 1.0], "y": [1.0, 0.6, 0.3, 0.1, 0.01, 0.0], "title": "Relative Permeability", "x_label": "Sw", "y_label": "Kr", "type": "line"}

For MULTIPLE curves on the SAME axis (preferred for SCAL — e.g. Krw + Kro, drainage + imbibition):
__PRC_PLOT__
{"curves": [{"label": "Krw", "x": [0.0, 0.2, 0.4, 0.6, 0.8, 1.0], "y": [0.0, 0.05, 0.15, 0.35, 0.65, 1.0]}, {"label": "Kro", "x": [0.0, 0.2, 0.4, 0.6, 0.8, 1.0], "y": [1.0, 0.75, 0.45, 0.2, 0.04, 0.0]}], "title": "Relative Permeability Curves", "x_label": "Water Saturation (Sw)", "y_label": "Relative Permeability (Kr)"}

Always use the multi-curve format when showing more than one data series. You can emit multiple __PRC_PLOT__ blocks in one response (e.g. one for Kr, one for Pc).

PETREL XML EXPORTER:
If the user asks you to export data to Petrel, Eclipse, or KAPPA, include the exact sequence __PETREL_EXPORT__ at the very start of your response, followed by structured, cleaned tabular data. The backend will automatically package it into a reservoir-compatible XML schematic file for them to download."""

# ── HVIEL BRAIN ──
class PRCChatAssistant:
    def __init__(self, key):
        self.model_name = 'gemini-1.5-flash'
        if key and key != "DUMMY_KEY":
            genai.configure(api_key=key)
            try:
                avail = [m.name for m in genai.list_models()]
                if 'models/gemini-2.5-flash' in avail: self.model_name = 'gemini-2.5-flash'
                elif 'models/gemini-2.0-flash' in avail: self.model_name = 'gemini-2.0-flash'
                elif 'models/gemini-1.5-flash' in avail: self.model_name = 'gemini-1.5-flash'
                elif 'models/gemini-pro' in avail: self.model_name = 'gemini-pro'
            except: pass
            self.model = genai.GenerativeModel(self.model_name)

    def chat(self, history, msg, kb_context="", f_parts=[]):
        # Build system + context enriched message
        enriched = SYSTEM_PROMPT
        if kb_context:
            enriched += f"\n\n--- KNOWLEDGE BASE CONTEXT ---\n{kb_context}\n--- END CONTEXT ---"
        enriched += f"\n\nUSER QUERY: {msg}"

        # Enforce strictly alternating history (User -> Model -> User -> Model)
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

        c = [enriched]
        SUPPORTED = ['application/pdf', 'image/jpeg', 'image/png', 'image/gif', 'image/webp']
        for data, mime in f_parts:
            if mime in SUPPORTED:
                c.append({'mime_type': mime, 'data': data})

        def _safe_text(response):
            """Extract text safely — handles safety-filtered or empty Gemini responses."""
            try:
                return response.text
            except ValueError:
                # Response was blocked by safety filters or returned no content parts
                if hasattr(response, 'prompt_feedback') and response.prompt_feedback:
                    return f"That query hit a safety threshold on the model side. Feedback: {response.prompt_feedback}. Rework the phrasing and I'll run it again."
                return "The model returned an empty response on that one — likely a transient quota or safety issue. Hit retry or rephrase the query."

        try:
            return _safe_text(self.model.start_chat(history=valid_history).send_message(c))
        except Exception as e:
            if "404" in str(e) or "not found" in str(e).lower():
                fallbacks = ['gemini-2.0-flash', 'gemini-1.5-pro', 'gemini-1.5-flash-latest', 'gemini-pro', 'models/gemini-1.5-flash']
                for fb in fallbacks:
                    try:
                        self.model = genai.GenerativeModel(fb)
                        return _safe_text(self.model.start_chat(history=valid_history).send_message(c))
                    except: continue

                try:
                    avail = [m.name.replace('models/', '') for m in genai.list_models()]
                    raise Exception(f"API Key Restrict Error: Google blocked all standard models. Available on your key: {', '.join(avail)}")
                except Exception as ex:
                    if "API Key Restrict Error" in str(ex): raise ex
                    raise Exception("Google API Key highly restricted. Failed to find any compatible model.")
            raise e


class AnthropicAssistant:
    # JSON schema prompts — Claude returns structured data, never raw markdown
    _DOCX_SCHEMA = """Return ONLY valid JSON (no markdown, no backticks, no explanation) with this exact structure:
{
  "title": "Document Title",
  "subtitle": "Optional subtitle",
  "author": "Engineer name or Hviel AI",
  "sections": [
    {"heading": "Section Name", "level": 1, "paragraphs": ["Paragraph 1 text.", "Paragraph 2 text."], "bullets": ["point 1", "point 2"]}
  ],
  "tables": [
    {"caption": "Table 1 \u2014 Description", "headers": ["Col1", "Col2"], "rows": [["val1", "val2"]]}
  ]
}
Rules: level 1 = major section, level 2 = subsection. bullets is optional. tables is optional.
CRITICAL: DO NOT EVER put raw markdown tables (e.g. `| Col | Col |`) inside `paragraphs`. If you have tabular data, you MUST use the `tables` JSON array structure.
For petrophysical data tables include ALL calculated values with proper units in the headers.
WRITE REAL ENGINEERING CONTENT in paragraphs — not placeholder text."""

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


# ── RAG ──
EMBED_MODEL = 'models/text-embedding-004'
_EMBED_DIM   = 768  # text-embedding-004 output dimension

class KnowledgeBase:
    CHUNK_SIZE = 600  # words per chunk

    @staticmethod
    def _embed(text: str):
        """Return a numpy float32 embedding vector via Gemini, or None on failure."""
        try:
            result = genai.embed_content(model=EMBED_MODEL, content=text,
                                          task_type='RETRIEVAL_DOCUMENT')
            return np.array(result['embedding'], dtype=np.float32)
        except Exception:
            return None

    @staticmethod
    def _embed_query(text: str):
        """Return a numpy float32 query embedding vector via Gemini, or None on failure."""
        try:
            result = genai.embed_content(model=EMBED_MODEL, content=text,
                                          task_type='RETRIEVAL_QUERY')
            return np.array(result['embedding'], dtype=np.float32)
        except Exception:
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
        Skips chunks that already have an embedding.
        """
        conn = sqlite3.connect(DB_PATH)
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
        """Vector cosine-similarity search with keyword fallback."""
        try:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()

            # ── Try semantic search ──
            vec_count = c.execute("SELECT COUNT(*) FROM kb_vectors").fetchone()[0]
            if vec_count > 0:
                q_vec = KnowledgeBase._embed_query(query)
                if q_vec is not None:
                    # Load all embedded chunks
                    rows = c.execute(
                        """SELECT kb.source, kb.chunk, kb_vectors.embedding
                           FROM kb_vectors
                           JOIN kb ON kb.id = kb_vectors.chunk_id"""
                    ).fetchall()
                    conn.close()
                    if rows:
                        sources  = [r[0] for r in rows]
                        texts    = [r[1] for r in rows]
                        vecs     = np.stack([np.frombuffer(r[2], dtype=np.float32) for r in rows])
                        # Cosine similarity
                        q_norm   = q_vec / (np.linalg.norm(q_vec) + 1e-9)
                        v_norms  = vecs / (np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-9)
                        scores   = v_norms @ q_norm
                        top_idx  = np.argsort(scores)[::-1][:top_k]
                        parts    = [f"[From: {sources[i]}]\n{texts[i]}" for i in top_idx if scores[i] > 0.3]
                        return "\n\n".join(parts)

            # ── Keyword fallback ──
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            keywords = [w.lower() for w in re.split(r'\W+', query) if len(w) > 3]
            if not keywords:
                conn.close()
                return ""
            results = c.execute("SELECT source, chunk FROM kb").fetchall()
            conn.close()
            scored = []
            for source, chunk in results:
                cl = chunk.lower()
                score = sum(1 for kw in keywords if kw in cl)
                if score > 0: scored.append((score, source, chunk))
            scored.sort(key=lambda x: -x[0])
            top = scored[:top_k]
            if not top: return ""
            parts = [f"[From: {s}]\n{ch}" for _, s, ch in top]
            return "\n\n".join(parts)
        except Exception:
            return ""

# ── VISUALIZER ──
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
                # ── Multi-curve mode ──
                for i, curve in enumerate(curves):
                    cx = curve.get('x', [])
                    cy = curve.get('y', [])
                    lbl = curve.get('label', f'Series {i+1}')
                    color = _PRC_COLORS[i % len(_PRC_COLORS)]
                    ax.plot(cx, cy, marker='o', linestyle='-', color=color,
                            linewidth=2.5, markersize=7, label=lbl)
                ax.legend(fontsize=10, framealpha=0.85)
            else:
                # ── Legacy single-curve mode ──
                x = data.get('x', [])
                y = data.get('y', [])
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

# ── PETREL EXPORTER ──
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

# ── REPORTING ENGINE (HvielDocEngine — Claude's architecture) ──
# from document_engines import DocumentEngines  # legacy — superseded by HvielDocEngine
hviel_engine = HvielDocEngine(output_dir='.')   # saves .docx/.xlsx/.pptx/.pdf to working dir

# ── APP SETUP ──
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
assistant = PRCChatAssistant(GEMINI_API_KEY)

def db(q, p=()):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(q, p)
    res = c.fetchall()
    conn.commit()
    conn.close()
    return res

# Init tables
db('CREATE TABLE IF NOT EXISTS m (id INTEGER PRIMARY KEY, sid TEXT, role TEXT, text TEXT, url TEXT, ts REAL)')
db('CREATE TABLE IF NOT EXISTS kb (id INTEGER PRIMARY KEY, source TEXT, chunk TEXT)')
db('CREATE TABLE IF NOT EXISTS kb_vectors (id INTEGER PRIMARY KEY, chunk_id INTEGER UNIQUE, embedding BLOB)')

@app.on_event("startup")
async def startup_event():
    import PyPDF2
    print("🚀 Running PRC Auto-Hydration Engine for Permanent Books...")
    books_dir = "books"
    if not os.path.exists(books_dir):
        return

    for filename in os.listdir(books_dir):
        filepath = os.path.join(books_dir, filename)
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        count = c.execute("SELECT COUNT(*) FROM kb WHERE source = ?", (filename,)).fetchone()[0]
        conn.close()
        if count == 0:
            print(f"📚 Auto-Hydrating: {filename} into RAG + Vector DB...")
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
                    print(f"✅ Injected {len(chunks)} knowledge blocks + embeddings from {filename}")
            except Exception as e:
                print(f"❌ Failed to hydrate {filename}: {e}")

    print("✅ Auto-Hydration Complete. PRC Hub ONLINE.")

# ── ROUTES: SESSIONS ──
@app.get("/api/sessions")
def get_sessions():
    try:
        rows = db("SELECT sid, MIN(ts), text FROM m WHERE role='user' GROUP BY sid ORDER BY MIN(ts) DESC")
        return [{"id": r[0], "title": r[2].split('\n')[0][:40] + '...', "created_at": r[1]} for r in rows]
    except Exception as e: return []

@app.delete("/api/session/{sid}")
def del_session(sid: str):
    db("DELETE FROM m WHERE sid = ?", (sid,))
    return {"status": "ok"}

@app.get("/api/session/{sid}")
def get_session(sid: str):
    try:
        rows = db("SELECT role, text, url, ts FROM m WHERE sid = ? ORDER BY id", (sid,))
        return {"status": "ok", "messages": [{"role": r[0], "text": r[1], "url": r[2], "ts": r[3]} for r in rows]}
    except Exception as e: return {"status": "error"}

# ── ROUTE: KNOWLEDGE BASE STATUS ──
@app.get("/api/kb/status")
def kb_status():
    try:
        rows = db("SELECT source, COUNT(*) FROM kb GROUP BY source")
        return {"total_chunks": db("SELECT COUNT(*) FROM kb")[0][0], "books": [{"name": r[0], "chunks": r[1]} for r in rows]}
    except Exception as e: return {"error": str(e)}

# ── ROUTE: KNOWLEDGE BASE INGESTION ──
@app.post("/api/kb/ingest")
async def kb_ingest(file: UploadFile = File(...), password: str = Form(...)):
    if password != "0608":
        return {"status": "error", "message": "Unauthorized"}
    try:
        content = await file.read()
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

        chunks = KnowledgeBase.chunk_text(text, name)
        # Clear old data for this source
        conn = sqlite3.connect(DB_PATH)
        old_ids = [r[0] for r in conn.execute("SELECT id FROM kb WHERE source = ?", (name,)).fetchall()]
        if old_ids:
            conn.execute(f"DELETE FROM kb_vectors WHERE chunk_id IN ({','.join('?'*len(old_ids))})", old_ids)
        conn.execute("DELETE FROM kb WHERE source = ?", (name,))
        conn.commit()
        conn.close()
        # Ingest with embeddings
        KnowledgeBase.ingest_chunks_with_embeddings(chunks)
        return {"status": "success", "book": name, "chunks_stored": len(chunks), "words": len(text.split()), "semantic_rag": True}
    except Exception as e:
        return {"status": "error", "message": str(e)[:100]}

# ── ROUTE: SSE STREAMING CHAT ──
@app.get("/api/chat/stream")
async def stream_chat(
    message: str,
    session_id: str = "",
    engineer_name: str = "PRC Engineer"
):
    """Server-Sent Events endpoint for real-time Gemini token streaming."""
    async def event_generator():
        try:
            sid = session_id if (session_id and session_id != "undefined") else str(uuid.uuid4())
            history = [{"role": r, "text": t} for r, t, u in
                       db("SELECT role, text, url FROM m WHERE sid = ? ORDER BY id", (sid,))]

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

            db("INSERT INTO m (sid, role, text, ts) VALUES (?, ?, ?, ?)",
               (sid, "user", message, time.time()))

            # Send session_id first so the frontend can latch onto it
            yield f"data: {{\"type\": \"session\", \"session_id\": \"{sid}\"}}\n\n"

            # Stream tokens
            full_resp = ""
            chat_session = assistant.model.start_chat(history=valid_history)
            for chunk in chat_session.send_message(enriched, stream=True):
                # BUG FIX: chunk.text raises ValueError on finish chunks (no content parts)
                # — must be caught explicitly, not with `or ""`
                try:
                    token = chunk.text
                except (ValueError, AttributeError):
                    continue  # skip finish/safety chunks with no content
                if token:
                    full_resp += token
                    # BUG FIX: use json.dumps for correct escaping of all chars (\n, \t, ", \\, etc.)
                    yield f"data: {_json.dumps({'type': 'token', 'text': token})}\n\n"

            db("INSERT INTO m (sid, role, text, ts) VALUES (?, ?, ?, ?)",
               (sid, "model", full_resp, time.time()))
            yield f"data: {_json.dumps({'type': 'done'})}\n\n"

        except Exception as e:
            err = str(e)[:120]
            yield f"data: {_json.dumps({'type': 'error', 'msg': err})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

# ── ROUTE: CHAT ──
@app.post("/api/chat")
async def handle(
    message: str = Form(...),
    session_id: Optional[str] = Form(None),
    engineer_name: str = Form("PRC Engineer"),
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
                message += f"\n[EXCEL — {fname}]:\n{df.head(10).to_string()}"
            elif fname.endswith('.csv'):
                df = pd.read_csv(pd.io.common.BytesIO(f_bytes))
                message += f"\n[CSV — {fname}]:\n{df.head(10).to_string()}"
            
            # --- TEXT DOCUMENTS ---
            elif fname.endswith('.docx'):
                doc = Document(pd.io.common.BytesIO(f_bytes))
                doc_text = "\n".join([p.text for p in doc.paragraphs if p.text.strip()])
                message += f"\n[WORD DOC — {fname}]:\n{doc_text[:15000]}"
            elif fname.endswith('.txt'):
                message += f"\n[TEXT FILE — {fname}]:\n{f_bytes.decode('utf-8', errors='ignore')[:15000]}"
            
            # --- BINARY (VISION / NATIVE PDF) ---
            else:
                SUPPORTED = ['application/pdf', 'image/jpeg', 'image/png', 'image/gif', 'image/webp']
                if mime in SUPPORTED:
                    f_parts.append((f_bytes, mime))

        # Retrieve relevant knowledge base context
        kb_context = KnowledgeBase.search(message)

        # SAVE USER MESSAGE TO DB
        db("INSERT INTO m (sid, role, text, ts) VALUES (?, ?, ?, ?)", (sid, "user", message, time.time()))

        resp = assistant.chat(history, message, kb_context=kb_context, f_parts=f_parts)

        # ── GEMINI NATIVE ENGINE ──

        # Handle Graphs — iterate over ALL __PRC_PLOT__ tokens in one response
        _plot_attempts = 0
        while '__PRC_PLOT__' in resp and _plot_attempts < 10:
            _plot_attempts += 1
            try:
                before, after = resp.split('__PRC_PLOT__', 1)
                after_stripped = after.lstrip()
                # BUG FIX: old regex \{.*?\} (non-greedy) stopped at the FIRST }
                # inside a nested JSON (e.g. inside the curves array), producing
                # invalid partial JSON.  raw_decode() correctly finds the matching
                # closing brace regardless of nesting depth.
                try:
                    plot_data, end_idx = _json.JSONDecoder().raw_decode(after_stripped)
                except _json.JSONDecodeError:
                    # No valid JSON object after this token — strip the dangling token and stop
                    resp = before + after
                    break
                img_md = Visualizer.build_plot(plot_data)
                consumed_len = (len(after) - len(after_stripped)) + end_idx
                resp = before + img_md + after[consumed_len:]
            except Exception as e:
                resp += f"\n*(Plot Error: {str(e)[:60]})*"
                break

        # Handle Documents (routed through HvielDocEngine)
        doc_type = None
        clean_resp = None
        if '__PRC_PPTX__' in resp:
            clean_resp = resp.replace('__PRC_PPTX__', '').strip()
            path = hviel_engine.build_from_json(
                clean_resp, 'pptx', well=f"Study_{int(time.time())}", engineer=engineer_name
            )
            doc_type = "pptx"
        elif '__PRC_PDF__' in resp:
            clean_resp = resp.replace('__PRC_PDF__', '').strip()
            path = hviel_engine.build_from_json(
                clean_resp, 'pdf', well=f"Study_{int(time.time())}", engineer=engineer_name
            )
            doc_type = "pdf"
        elif '__PRC_DOCX__' in resp or '__PRC_REPORT__' in resp:
            clean_resp = resp.replace('__PRC_DOCX__', '').replace('__PRC_REPORT__', '').strip()
            path = hviel_engine.build_from_json(
                clean_resp, 'docx', well=f"Study_{int(time.time())}", engineer=engineer_name
            )
            doc_type = "docx"
        elif '__PRC_EXCEL__' in resp:
            clean_resp = resp.replace('__PRC_EXCEL__', '').strip()
            path = hviel_engine.build_from_json(
                clean_resp, 'xlsx', well=f"Study_{int(time.time())}", engineer=engineer_name
            )
            doc_type = "excel"

        if doc_type:
            url = f"/api/download/{path}"
            db("INSERT INTO m (sid, role, text, url, ts) VALUES (?, ?, ?, ?, ?)", (sid, "model", clean_resp, url, time.time()))
            return {"status": "success", "is_report_ready": True, "download_url": url, "doc_type": doc_type, "session_id": sid, "reply": clean_resp}

        # Handle Petrel Exports
        if '__PETREL_EXPORT__' in resp:
            clean_resp = resp.replace('__PETREL_EXPORT__', '').strip()
            path = PetrelExporter.build_xml(f"Study_{int(time.time())}", clean_resp)
            url = f"/api/download/{path}"
            db("INSERT INTO m (sid, role, text, url, ts) VALUES (?, ?, ?, ?, ?)", (sid, "model", clean_resp, url, time.time()))
            return {"status": "success", "is_report_ready": True, "download_url": url, "session_id": sid, "reply": clean_resp}

        db("INSERT INTO m (sid, role, text, ts) VALUES (?, ?, ?, ?)", (sid, "model", resp, time.time()))
        return {"status": "success", "session_id": sid, "reply": resp}

    except Exception as e:
        return {"status": "error", "is_error": True, "reply": f"SYSTEM EXCEPTION: {str(e)[:80]}"}

# ── DIAG ──
@app.get("/api/diag")
def diag():
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        return {
            "version": "PRC-HUB-VER-11-SEMANTIC-RAG-STREAMING",
            "models": [m.name for m in genai.list_models()],
            "active_model": assistant.model_name,
            "kb_chunks": len(db("SELECT id FROM kb")),
            "kb_vectors": len(db("SELECT id FROM kb_vectors")),
            "semantic_rag": True,
            "streaming": True,
            "anthropic_model": "claude-sonnet-4-6",
            "env_fix_applied": True,
            "smart_routing": True
        }
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/download/{filename}")
async def dl(filename: str): return FileResponse(path=filename, filename=filename)

@app.get("/")
def root(): return {"v": "PRC-HUB-VER-11-SEMANTIC-RAG-STREAMING", "model": assistant.model_name}
