from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import os, uuid, time, sqlite3, re
import pandas as pd
from typing import Optional
import google.generativeai as genai
from docx import Document
from bs4 import BeautifulSoup

# ── CONFIG ──
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "DUMMY_KEY")
DB_PATH = "chat_history.db"

# ── SYSTEM PROMPT ──
SYSTEM_PROMPT = """You are Hviel, the Senior AI Petrophysical Specialist at the Petroleum Research Center (PRC) of Libya.
You are a world-class expert in SCAL (Special Core Analysis), petrophysics, reservoir engineering, and petroleum geology.
Your role is to assist PRC engineers with technical analysis, data interpretation, and generating professional reports.
When a user asks a technical question, you must use the KNOWLEDGE BASE context provided below (if any) to give an expert, detailed, and accurate answer.
Always respond professionally and in English. If generating a report, include __PRC_REPORT__ at the start of your response."""

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

    def chat(self, history, msg, kb_context="", f=None, m=None):
        # Build system + context enriched message
        enriched = SYSTEM_PROMPT
        if kb_context:
            enriched += f"\n\n--- KNOWLEDGE BASE CONTEXT ---\n{kb_context}\n--- END CONTEXT ---"
        enriched += f"\n\nUSER QUERY: {msg}"
        
        h = [{"role":'user' if x['role']=='user' else 'model', "parts":[x['text']]} for x in history]
        c = [enriched]
        SUPPORTED = ['application/pdf', 'image/jpeg', 'image/png', 'image/gif', 'image/webp']
        if f and m in SUPPORTED:
            c.append({'mime_type': m, 'data': f})
        return self.model.start_chat(history=h).send_message(c).text

# ── RAG ──
class KnowledgeBase:
    CHUNK_SIZE = 600  # words per chunk

    @staticmethod
    def chunk_text(text, source):
        words = text.split()
        chunks = []
        for i in range(0, len(words), KnowledgeBase.CHUNK_SIZE):
            chunk = " ".join(words[i:i + KnowledgeBase.CHUNK_SIZE])
            chunks.append((source, chunk))
        return chunks

    @staticmethod
    def search(query, top_k=4):
        """Keyword-based retrieval from SQLite."""
        try:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            # Score each chunk by how many query words appear in it
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
                if score > 0:
                    scored.append((score, source, chunk))
            scored.sort(key=lambda x: -x[0])
            top = scored[:top_k]
            if not top:
                return ""
            parts = [f"[From: {s}]\n{ch}" for _, s, ch in top]
            return "\n\n".join(parts)
        except Exception as e:
            return ""

# ── REPORTING ──
class Reporter:
    @staticmethod
    def build(well, engineer, insight):
        doc = Document()
        doc.add_heading(f'PRC TECHNICAL EVALUATION: {well}', 0)
        doc.add_paragraph(f"Engineer: {engineer}\nDate: {time.strftime('%Y-%m-%d')}\n")
        doc.add_heading('Analysis & Findings', 1)
        doc.add_paragraph(insight.replace('__PRC_REPORT__', '').strip())
        fname = f"PRC_{int(time.time())}.docx"
        doc.save(fname)
        return fname

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

# ── ROUTES: SESSIONS ──
@app.get("/api/sessions")
def get_sessions(): return []

@app.delete("/api/session/{sid}")
def del_session(sid: str): return {"status": "ok"}

@app.get("/api/session/{sid}")
def get_session(sid: str): return {"status": "ok", "messages": []}

# ── ROUTE: KNOWLEDGE BASE STATUS ──
@app.get("/api/kb/status")
def kb_status():
    try:
        rows = db("SELECT source, COUNT(*) FROM kb GROUP BY source")
        books = [{"name": r[0], "chunks": r[1]} for r in rows]
        total = db("SELECT COUNT(*) FROM kb")[0][0]
        return {"total_chunks": total, "books": books}
    except Exception as e:
        return {"error": str(e)}

# ── ROUTE: INGEST BOOK ──
@app.post("/api/kb/ingest")
async def ingest_book(file: UploadFile = File(...)):
    try:
        content = await file.read()
        name = file.filename or "Unknown Book"
        
        # Parse HTML books
        if name.endswith(('.html', '.htm')) or 'text/html' in (file.content_type or ''):
            soup = BeautifulSoup(content, 'lxml')
            # Remove scripts/styles
            for tag in soup(['script', 'style', 'nav', 'footer', 'header']):
                tag.decompose()
            text = soup.get_text(separator=' ', strip=True)
        elif name.endswith('.txt'):
            text = content.decode('utf-8', errors='ignore')
        else:
            text = content.decode('utf-8', errors='ignore')

        # Clean up whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        if len(text) < 100:
            return {"status": "error", "message": "File too short or unreadable"}

        # Chunk and store
        chunks = KnowledgeBase.chunk_text(text, name)
        # Delete old chunks for this book if re-ingesting
        db("DELETE FROM kb WHERE source = ?", (name,))
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.executemany("INSERT INTO kb (source, chunk) VALUES (?, ?)", chunks)
        conn.commit()
        conn.close()

        return {"status": "success", "book": name, "chunks_stored": len(chunks), "words": len(text.split())}
    except Exception as e:
        return {"status": "error", "message": str(e)[:100]}

# ── ROUTE: CHAT ──
@app.post("/api/chat")
async def handle(
    message: str = Form(...),
    session_id: Optional[str] = Form(None),
    engineer_name: str = Form("PRC Engineer"),
    file: Optional[UploadFile] = File(None)
):
    try:
        sid = session_id if (session_id and session_id != "undefined") else str(uuid.uuid4())
        history = [{"role": r, "text": t} for r, t, u in db("SELECT role, text, url FROM m WHERE sid = ? ORDER BY id", (sid,))]
        
        f_b, m_t = None, None
        if file:
            f_b = await file.read()
            m_t = file.content_type
            fname = file.filename or ""
            if "sheet" in (m_t or '') or fname.endswith(('.xlsx', '.xls')):
                df = pd.read_excel(pd.io.common.BytesIO(f_b))
                message += f"\n[EXCEL DATA]:\n{df.head(10).to_string()}"
                f_b = None
            elif fname.endswith('.csv'):
                df = pd.read_csv(pd.io.common.BytesIO(f_b))
                message += f"\n[CSV DATA]:\n{df.head(10).to_string()}"
                f_b = None

        # Retrieve relevant knowledge base context
        kb_context = KnowledgeBase.search(message)

        resp = assistant.chat(history, message, kb_context=kb_context, f=f_b, m=m_t)

        if '__PRC_REPORT__' in resp:
            path = Reporter.build(f"Study_{int(time.time())}", engineer_name, resp)
            url = f"/api/download/{path}"
            db("INSERT INTO m (sid, role, text, url, ts) VALUES (?, ?, ?, ?, ?)", (sid, "model", "Report Ready", url, time.time()))
            return {"status": "success", "is_report_ready": True, "download_url": url, "session_id": sid, "reply": "Your PRC Report is ready. Click Download below."}

        db("INSERT INTO m (sid, role, text, ts) VALUES (?, ?, ?, ?)", (sid, "model", resp, time.time()))
        return {"status": "success", "session_id": sid, "reply": resp}

    except Exception as e:
        return {"status": "error", "is_error": True, "reply": f"SYSTEM EXCEPTION: {str(e)[:80]}"}

# ── DIAG ──
@app.get("/api/diag")
def diag():
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        models = [m.name for m in genai.list_models()]
        kb_count = db("SELECT COUNT(*) FROM kb")[0][0]
        return {"models": models, "active_model": assistant.model_name, "kb_chunks": kb_count}
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/download/{filename}")
async def dl(filename: str): return FileResponse(path=filename, filename=filename)

@app.get("/")
def root(): return {"v": "PRC-HUB-VER-10-RAG-ACTIVE", "model": assistant.model_name}
