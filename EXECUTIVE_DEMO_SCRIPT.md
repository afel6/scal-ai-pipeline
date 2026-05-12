# PRC SCAL AI Pipeline — Executive Board Demo Script

**Presenter:** [Your Name], PRC Petrophysics Lead  
**Audience:** PRC Executive Board  
**Duration:** ~20 minutes  
**URL:** https://scal-ai.onrender.com

---

## Pre-Demo Setup (5 minutes before the room fills)

1. Open the app in Chrome, **full screen** (F11). Dark background should fill the monitor edge-to-edge.
2. Log in with your PRC credentials. Confirm the session panel on the left is empty (or has only your own prior sessions).
3. Have this file ready on a second screen or printed.
4. Sample files to have open in File Explorer, ready to drag-and-drop:
   - Any `.csv` with columns: `Sw`, `Krw`, `Kro` (a SCAL Kr table)
   - Any MICP report `.csv` with `Pc` and `Sw` columns
   - *(If available)* a short PDF from the PRC technical library

---

## Act 1 — Opening (say out loud, ~2 minutes)

> "What you're looking at is the PRC Petrophysics Intelligence Engine — codename Hviel.
> It is not a chatbot. It is a **physics-enforced AI agent** purpose-built for Libyan reservoir
> SCAL analysis. Every number it produces is validated against physical law before it reaches you.
> Let me show you how."

**Click:** "New Study" in the top-left panel.

> "This creates an isolated audit session. Everything said and every calculation performed
> in this session is logged to the PRC Audit Ledger — immutably and automatically."

---

## Act 2 — The Physics Watchtower (say out loud, ~6 minutes)

### Step 2A — Run a Kr simulation from scratch

**Type into the chat box and press Enter:**

```
Run a Brooks-Corey relative permeability simulation with Swr=0.18, Snr=0.20, krw_max=0.55, kro_max=0.95, nw=2.2, no=3.1
```

**Wait for the plot to render, then say:**

> "The agent did not just draw curves. It ran the data through the Physics Watchtower —
> seven physical law checks: endpoint constraints, monotonicity, Corey exponent bounds,
> residual saturation validity. You can see the health score in the response."

**Point to the health score badge in the response, then say:**

> "If any check had failed — if, for example, Kro did not reach zero at residual oil saturation —
> the agent would have flagged a violation and refused to present the result as valid.
> That is not a soft warning. It blocks the output."

---

### Step 2B — Demonstrate the Audit Ledger

**Type into the chat box:**

```
Show me my audit history for this session.
```

**When the table renders, say:**

> "Every tool call that touches physics data writes a permanent, timestamped record
> to the PRC Audit Ledger. The ledger is append-only — no record can be deleted or modified,
> not even by me. If a field engineer uploads corrupted Kr data three months from now,
> the board will be able to trace exactly when the violation was flagged and what the score was."

---

### Step 2C — Upload a real Kr dataset (live upload)

**Drag your Kr CSV onto the chat input area (or click the paperclip icon and select the file), then type:**

```
Analyse this Kr dataset. Run physics validation and fit a Brooks-Corey model.
```

**While the agent processes, say:**

> "It is parsing the laboratory columns, running the Physics Watchtower on the raw data,
> fitting the Corey exponents via numerical optimisation, and logging the audit — all in
> one tool-chain call to Gemini 2.5 Flash."

**When the result renders:**

> "There is the fitted model. Grade, health score, and the exact parameters extracted.
> Note the parameter table uses four decimal places — this is not a summary; it is the
> engineering output."

---

## Act 3 — The Anti-Hallucination Guarantee (say out loud, ~4 minutes)

**Type into the chat box:**

```
What is the standard definition of the Archie cementation exponent and what typical range should I use for Libyan sandstone?
```

**When the response arrives, say:**

> "Notice the citation at the top of that answer. The agent answered from the PRC Technical
> Knowledge Base — 196 chunks of peer-reviewed SCAL literature ingested from our own library.
> It did not guess. It cited the source."

**Now test the boundary. Type:**

```
What is the exact porosity of the Waha field Block 59 Upper Cretaceous?
```

**When the response arrives, say:**

> "The agent just told you it does not have that value in the knowledge base and refused to
> fabricate one. That is the non-negotiable design contract: if the data is not in the RAG
> library or in a file you uploaded, Hviel says 'I don't know' rather than inventing a number
> that an engineer might trust with a well decision."

> "In petrophysics, a hallucinated porosity or Sw value could justify a multi-million dollar
> completion that should never have been drilled. That failure mode does not exist here."

---

## Act 4 — The Dual-Engine Database (say out loud, ~3 minutes)

**Type into the chat box:**

```
Run a J-Leverett capillary pressure calculation using IFT=35, contact_angle=40, permeability=85, porosity=0.21
```

**While it runs, say:**

> "The pipeline runs on two database engines simultaneously.
> SQLite handles the real-time chat history and session state — sub-millisecond writes
> for every message token, so the stream never stalls waiting for a database write.
> PostgreSQL on Neon handles the structured physics audit ledger — ACID-compliant,
> cloud-replicated, the permanent record of every calculation this system has ever made."

**When the result renders, point to the J-function output:**

> "The capillary pressure, the Amott-Harvey wettability index, and the Leverett J-function
> — all calculated, all validated, all logged. One prompt."

---

## Act 5 — Close (say out loud, ~2 minutes)

> "What we built is not a demo. It is a production system. The same code running here
> right now is what runs at scal-ai.onrender.com, served globally, with Row-Level Security
> ensuring that each engineer can only read their own sessions."

> "Three things make this unique in the PRC portfolio:"

> "One — Physics Integrity. No simulation output leaves the system without passing the
> Physics Watchtower. The validator is not optional and cannot be bypassed."

> "Two — Immutable Accountability. The Audit Ledger records every physical interpretation
> with a timestamp and health score. The board has a permanent, tamper-proof trail."

> "Three — Honest Intelligence. The RAG knowledge hierarchy means Hviel cites its sources
> or admits ignorance. It does not fill gaps with confident fabrication."

> "This is the PRC Petrophysics Engine. It is ready."

---

## Backup — If the audience asks questions

| Question | Talking point |
|---|---|
| "What if Gemini is down?" | The system retries across multiple API keys automatically. If all are unavailable, it shows a retry message rather than crashing. |
| "Can it read Arabic field reports?" | Not yet — documents must be translated before ingestion. Arabic-language RAG is on the roadmap. |
| "Who can see my sessions?" | Only you. Row-Level Security ties every session to your email. The admin view requires the KB ingest password. |
| "How do we add our own documents to the knowledge base?" | `POST /api/kb/ingest` with the ingest password. PRC-approved documents only — API RP 40, SCAL standards, internal field studies. |
| "What model is it running?" | Gemini 2.5 Flash via the Google Gen AI SDK. Model selection is locked in the codebase; the CLAUDE.md engineering spec documents the exact version and why. |

---

## Emergency fallback (if internet is slow or Render is cold-starting)

If the first message takes > 30 seconds, say:

> "The server is waking from standby — Render's free tier spins down after 15 minutes of
> inactivity. In the production deployment this is a paid instance with no cold starts."

While it loads, show the board the **Physics Watchtower diagram** from `SOVEREIGN_SCAL_OPERATORS_MANUAL.md`.
