# 🖥️ HVIEL petrophysical pipeline: HOST SYSTEM PROFILE

This profile maps the optimized host environment layout for the PRC SCAL AI Pipeline (Hviel). All automated pipelines, developer commands, and multi-agent loops must align with these system parameters.

---

## 🛠️ HOST OPTIMIZATION SPECIFICATION
*Optimized via Chris Titus's WinUtil (Windows Utility)*

| Parameter | Configuration Map State | Active Operational Rules |
| :--- | :--- | :--- |
| **Process Budget** | Tight execution budget (~70-80 active background tasks) | Spawn zero telemetry processes; immediately reap dead threads |
| **Filesystem State** | Explicit transparency (File Extensions & Hidden files enabled) | Clear, direct path traversals for config maps, `.env`, `.gemini` |
| **Host Console** | GPU-accelerated Windows Terminal | Direct command routing; clean monospace outputs |
| **Update Protocol** | Restricted to Security Settings (Delayed Feature updates - 365 Days) | Guaranteed stability of stable runtime dependencies & drivers |
| **Disk Utility** | WizTree installed via WinGet | Keep track of testing cache assets and DB temp dumps for cleanup |

---

## ⚡ OPERATIONAL DIRECTIVES

### 1. PROCESS AND RAM BUDGET
> [!IMPORTANT]
> The host machine is configured for high performance, maintaining massive raw CPU cycles and physical RAM overhead.
- All Python analysis routines (such as Simulated Annealing for Brooks-Corey curves and LET optimization) must be memory-efficient.
- Implement immediate context compression and manual garbage collection `gc.collect()` following heavy file uploads.
- Strictly avoid spinning up parallel worker pools that exceed the host hardware thread boundaries.

### 2. FILESYSTEM INTERACTION & DIRECT CONFIG ACCESS
- All configuration paths are transparent and fully mapped.
- Native `pathlib.Path` objects must be used exclusively inside all file-system actions (no `os` namespace functions) to guarantee high-performance, exception-free traversals.
- Direct path lookups to hidden dotfiles (`.env`, `.gitignore`, `.vercel`, etc.) should be maintained safely.

### 3. WINDOWS TERMINAL COMMAND ROUTING
- Windows Terminal serves as our primary GPU-accelerated command console.
- Run the full physics test suite natively in it:
  ```powershell
  python -m pytest tests/
  ```
- Always ensure console output is clean, omitting large raw matrix dumps by utilizing our backend pagination utilities (`format_and_truncate_json_table`).

### 4. CACHE TRACKING & WIZTREE DISK CLEANUP PLAN
As the pipeline processes raw centrifuge, MICP, and water flooding spreadsheets, local temporary databases and cache files will accumulate. Keep them mapped here to ensure a clean environment:

- **Active Cache Databases:**
  - `c:\Users\Asus\Downloads\scal-ai-pipeline\prc_hub.db`
  - `c:\Users\Asus\Downloads\scal-ai-pipeline\prc_local_cache.db`
  - `c:\Users\Asus\Downloads\scal-ai-pipeline\chat_history.db`
- **Temp Uploads Directory:**
  - `c:\Users\Asus\Downloads\scal-ai-pipeline\uploads\`
- **Temp Output Reports:**
  - `c:\Users\Asus\Downloads\scal-ai-pipeline\reports\`
- **Cleanup Strategy:**
  - If test logs or database cache sizes grow beyond reasonable bounds, utilize **WizTree** to instantly scan the folders and execute the cleanup plan.
