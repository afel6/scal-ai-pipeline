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
                    # Drop previous unanswered user prompt to maintain sequence
                    valid_history[-1] = {"role": role, "parts": [x['text']]}
                elif role == 'model':
                    # Merge consecutive model responses
                    valid_history[-1]['parts'][0] += "\n\n" + x['text']
        
        if valid_history and valid_history[-1]['role'] == 'user':
            valid_history.pop()  # History must end with a model turn before sending a new user message

        c = [enriched]
        SUPPORTED = ['application/pdf', 'image/jpeg', 'image/png', 'image/gif', 'image/webp']
        for data, mime in f_parts:
            if mime in SUPPORTED:
                c.append({'mime_type': mime, 'data': data})
        return self.model.start_chat(history=valid_history).send_message(c).text


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
            keywords = [w.lower() for w in re.split(r'\W+', query) if len(w) > 3]
            if not keywords: return ""
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
        except Exception as e: return ""

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

# ── ROUTE: INGEST BOOK ──
@app.post("/api/kb/ingest")
async def ingest_book(file: UploadFile = File(...)):
    try:
        content = await file.read()
        name = file.filename or "Unknown Book"
        if name.endswith(('.html', '.htm')) or 'text/html' in (file.content_type or ''):
            soup = BeautifulSoup(content, 'lxml')
            for tag in soup(['script', 'style', 'nav', 'footer', 'header']): tag.decompose()
            text = soup.get_text(separator=' ', strip=True)
        else:
            text = content.decode('utf-8', errors='ignore')
        text = re.sub(r'\s+', ' ', text).strip()
        if len(text) < 100: return {"status": "error", "message": "File too short or unreadable"}
        chunks = KnowledgeBase.chunk_text(text, name)
        db("DELETE FROM kb WHERE source = ?", (name,))
        conn = sqlite3.connect(DB_PATH)
        conn.executemany("INSERT INTO kb (source, chunk) VALUES (?, ?)", chunks)
        conn.commit(); conn.close()
        return {"status": "success", "book": name, "chunks_stored": len(chunks), "words": len(text.split())}
    except Exception as e: return {"status": "error", "message": str(e)[:100]}

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

        if '__PRC_REPORT__' in resp:
            clean_resp = resp.replace('__PRC_REPORT__', '').strip()
            path = Reporter.build(f"Study_{int(time.time())}", engineer_name, resp)
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
        models = [m.name for m in genai.list_models()]
        kb_count = db("SELECT COUNT(*) FROM kb")[0][0]
        return {"models": models, "active_model": assistant.model_name, "kb_chunks": kb_count}
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/download/{filename}")
async def dl(filename: str): return FileResponse(path=filename, filename=filename)

@app.get("/")
def root(): return {"v": "PRC-HUB-VER-10-RAG-ACTIVE", "model": assistant.model_name}
