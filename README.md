# 🚀 PRC AI Pipeline: Sovereign Petrophysical Agent (v2.2)

![PRC Logo](file:///c:/Users/Asus/Downloads/scal-ai-pipeline/prc_logo.png)

A fully autonomous, multi-modal engineering agent designed specifically for the **Petroleum Research Center (PRC) in Libya**. This system transforms standard RAG applications into a high-performance engineering tool capable of literature research, mathematical simulation, and professional reporting.

## 🏗 Architecture v2.2 Overview

### 💡 Multi-LLM Expert Routing
- **Conversational Core**: Powered by **Google Gemini** for real-time, low-latency analysis and SSE streaming.
- **Document Generation Engine**: Computationally heavy data-structuring tasks are routed to **Claude 3.5 Sonnet**, enabling precise .docx and .xlsx exports with complex petrophysical tables and charts.

### 👁 The Visual Cortex
- **Interactive Diagramming**: Native React integration with `Mermaid.jsx`.
- **Autonomous Visualization**: Hviel generates flowcharts, decision trees, and sequence diagrams to illustrate engineering verification strategies directly in the chat interface.

### 🛠 Agentic Skills Engine (Hermes)
The system is equipped with proactive engineering tools:
- `search_arxiv`: Semantic discovery of petroleum engineering literature.
- `execute_python_simulation`: Sandboxed execution of models including **Simulated Annealing**, **Brooks-Corey**, and **Archie's Law**.
- **Skills Dashboard**: Real-time discovery UI panel in the Library sidebar for monitoring agent capabilities.

### 🧠 Cognitive Engineering Discipline
- **Mandatory 4-Phase Root Cause Loop**: Implementation of a senior engineering auditor mental model. The system refuses "band-aid" fixes for data anomalies.
- **Systematic Debugging**: Strict adherence to root cause tracing before suggesting adjustments.

### 🔐 Security & Hardening
- **Unified 1509 Credential**: Administrative interfaces, book uploads, and backend ingestion pipelines are dynamically locked behind private credentials.
- **Production-Grade Stability**: Optimized FastAPI asynchronous streaming for high-reliability deployments.

---

## 🛠 Tech Stack
- **Backend**: FastAPI (Python 3.10+)
- **Frontend**: Vite + React + TailwindCSS
- **Database**: PostgreSQL (Production) / SQLite (Local Fallback)
- **AI Layers**: Google GenAI (Gemini) + Anthropic (Claude)
- **Visuals**: Matplotlib + Mermaid.js

## 📦 Deployment
See [README_DEPLOYMENT.md](file:///c:/Users/Asus/Downloads/scal-ai-pipeline/README_DEPLOYMENT.md) for detailed environment setup and server configuration.

---
*Petroleum Research Center — Engineering the future of energy.*
