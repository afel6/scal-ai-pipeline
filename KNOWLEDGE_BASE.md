# KNOWLEDGE_BASE: ARCHITECTURAL SNAPSHOT

This document serves as the single, comprehensive, deterministic context file for AI consumption, capturing the true production architecture of the Special Core Analysis (SCAL) pipeline repository.

---

## 1. SESSION EVICTION & PIPELINE ISOLATION

### Eviction Utility Implementation
* **File Path**: `c:\Users\Asus\Downloads\scal-ai-pipeline\app.py`
* **Lock & Cache Declarations**:
  ```python
  SESSION_DATA_CACHE_LOCK: threading.Lock = threading.Lock()
  SESSION_DATA_CACHE: dict[str, dict] = {}
  ```
* **Full Production Source Code (`evict_session`)**:
  ```python
  def evict_session(session_id: str) -> None:
      """Single source of truth for destructive session eviction.
  
      Clears the session's cache dict in place (dropping ground truth, labeled
      values, and flat vectors), resets it to a clean empty shell, and forces an
      explicit garbage-collection pass so no ghost memory survives across sessions.
      Wired into chat init, file upload, and the explicit /api/clear-session route
      so eviction logic can never drift between call sites again.
      """
      if not session_id:
          return
      import gc
      with SESSION_DATA_CACHE_LOCK:
          if session_id not in SESSION_DATA_CACHE:
              SESSION_DATA_CACHE[session_id] = {}
          SESSION_DATA_CACHE[session_id].clear()
          SESSION_DATA_CACHE[session_id]["labeled_values"] = {}
      gc.collect()
  ```

---

### Route Mapping Integration

#### A. Chat Routing Endpoint (`/api/chat`)
* **File Path**: `c:\Users\Asus\Downloads\scal-ai-pipeline\app.py`
* **Integration Code**:
  ```python
  @app.post("/api/chat")
  async def handle(
      background_tasks: BackgroundTasks,
      message:       Optional[str]    = Form(None),
      session_id:    Optional[str]    = Form(None),
      user_email:    Optional[str]    = Form(None),
      engineer_name: Optional[str]    = Form(None),
      files:         list[UploadFile] = File(default=[]),
  ):
      try:
          _tls.breadcrumbs = []
          _add_breadcrumb("Chat request received")
  
          sid      = session_id or str(uuid.uuid4())
  
          # Destructive memory eviction protocol on new study / file upload
          is_new_session = session_id in ("null", "undefined", "", None) or not session_id
          valid_files = [f for f in files if getattr(f, "filename", "")]
          if is_new_session or valid_files:
              evict_session(sid)
  ```

#### B. File Upload Route (`/api/v1/analyze-scal`)
* **File Path**: `c:\Users\Asus\Downloads\scal-ai-pipeline\app.py`
* **Integration Code**:
  ```python
  @app.post("/api/v1/analyze-scal")
  async def analyze_scal(
      background_tasks: BackgroundTasks,
      file: UploadFile = File(...),
      session_id: Optional[str] = Form(None),
      user_email: Optional[str] = Form(None),
      message: Optional[str] = Form(None),
  ):
      try:
          sid = session_id or str(uuid.uuid4())
  
          # Destructive memory eviction protocol on new file ingestion
          evict_session(sid)
  ```

#### C. Explicit Clear Session Route (`/api/clear-session`)
* **File Path**: `c:\Users\Asus\Downloads\scal-ai-pipeline\app.py`
* **Integration Code**:
  ```python
  @app.post("/api/clear-session")
  async def clear_session(session_id: str = Form(...)):
      """Explicit destructive eviction of a session's cached SCAL data.
      Enforces absolute isolation: clears the dict and forces gc.collect()."""
      import re as _re
      if not _re.match(r"^(report-)?[a-zA-Z0-9\-]+$", session_id):
          raise HTTPException(status_code=400, detail="Invalid session_id format")
      evict_session(session_id)
      return {"status": "cleared", "session_id": session_id}
  ```

---

## 2. CACHE RETRIEVAL & TOKEN MATCHING LOGIC

### Ground Truth Inventory Parser
* **File Path**: `c:\Users\Asus\Downloads\scal-ai-pipeline\scal_file_handler.py`
* **Full Production Source Code (`extract_absolute_file_truth`)**:
  ```python
  def extract_absolute_file_truth(temp_file_paths: list) -> str:
      """Pure Python deterministic pre-parser that extracts un-bypassable
      ground truth metadata from uploaded files BEFORE the LLM is called.
  
      This function uses raw pandas calls (pd.ExcelFile, pd.read_excel, 
      smart_read_csv) with ZERO SCALFileHandler dependency.
  
      Args:
          temp_file_paths: List of (file_path, original_filename) tuples.
  
      Returns:
          A formatted MANDATORY_GROUND_TRUTH_INVENTORY text block suitable
          for direct injection into the LLM system instruction.
      """
      lines = [
          "╔══════════════════════════════════════════════════════════════════════╗",
          "║  MANDATORY_GROUND_TRUTH_INVENTORY                                  ║",
          "║  Generated programmatically by the Python server.                   ║",
          "║  This inventory is ABSOLUTE TRUTH. You MUST NOT contradict it.      ║",
          "╚══════════════════════════════════════════════════════════════════════╝",
          "",
      ]
  
      for file_path, original_filename in temp_file_paths:
          ext = Path(original_filename).suffix.lower()
          lines.append(f"═══ FILE: {original_filename} ═══")
  
          try:
              if ext in ('.xlsx', '.xlsm', '.xls', '.ods'):
                  engine = (
                      'openpyxl' if ext in ('.xlsx', '.xlsm')
                      else ('xlrd' if ext == '.xls' else 'odf')
                  )
                  xl = pd.ExcelFile(file_path, engine=engine)
                  sheet_names = xl.sheet_names
                  lines.append(f"TOTAL SHEETS: {len(sheet_names)}")
                  lines.append(f"SHEET NAMES: {sheet_names}")
                  lines.append("")
  
                  for sheet in sheet_names:
                      df = pd.read_excel(xl, sheet_name=sheet, engine=engine)
                      full_df_shape = pd.read_excel(xl, sheet_name=sheet, header=None, engine=engine).shape
                      columns = list(df.columns)
                      lines.append(f"  SHEET: \"{sheet}\"")
                      lines.append(f"    COLUMNS ({len(columns)}): {columns}")
                      lines.append(f"    FULL SHAPE: ({full_df_shape[0]} rows × {full_df_shape[1]} cols)")
                      # Print all rows as raw values to completely hydrate the data cache
                      for row_idx in range(len(df)):
                          row_vals = df.iloc[row_idx].tolist()
                          # Convert NaN to None for clarity
                          row_vals = [
                              None if pd.isna(v) else (float(v) if isinstance(v, (int, float, np.integer, np.floating)) else str(v))
                              for v in row_vals
                          ]
                          lines.append(f"    ROW {row_idx}: {row_vals}")
                      lines.append("")
  
                  xl.close()
  
              elif ext == '.csv':
                  df = smart_read_csv(file_path)
                  columns = list(df.columns)
                  lines.append(f"TOTAL SHEETS: 1 (CSV)")
                  lines.append(f"SHEET NAMES: ['Sheet1']")
                  lines.append(f"  SHEET: \"Sheet1\"")
                  lines.append(f"    COLUMNS ({len(columns)}): {columns}")
                  lines.append(f"    FULL SHAPE: ({len(df)} rows × {len(columns)} cols)")
                  # Print all rows as raw values to completely hydrate the data cache
                  for row_idx in range(len(df)):
                      row_vals = df.iloc[row_idx].tolist()
                      row_vals = [
                          None if pd.isna(v) else (float(v) if isinstance(v, (int, float, np.integer, np.floating)) else str(v))
                          for v in row_vals
                      ]
                      lines.append(f"    ROW {row_idx}: {row_vals}")
                  lines.append("")
  
              else:
                  lines.append(f"  [Non-tabular file, no sheet/column inventory applicable]")
                  lines.append("")
  
          except Exception as e:
              lines.append(f"  [ERROR reading file: {e}]")
              lines.append("")
  
      lines.append("═══════════════════════════════════════════════════════════════")
      lines.append("END OF MANDATORY_GROUND_TRUTH_INVENTORY")
      lines.append("═══════════════════════════════════════════════════════════════")
      return "\n".join(lines)
  ```

---

### Key Parameter Retrieval
* **File Path**: `c:\Users\Asus\Downloads\scal-ai-pipeline\app.py`
* **Full Production Source Code (`get_param` + `opt` inside `calculate_derived_value`)**:
  As of commit `0fbff88`: the `default` parameter is REMOVED entirely — a missing
  parameter ALWAYS raises `_MissingParam` (never substitutes a constant like 2.65 and
  never fabricates a `| CACHED |` provenance marker). Cache matching is whole-token only.
  The optional Ri/Ro/Rt chain in `archie_sw` flows through the new `opt()` helper, which
  returns `None` on absence instead of a fabricated value.
  ```python
      # STRICT: no `default` parameter at all. A missing parameter ALWAYS raises
      # _MissingParam — never substitutes a constant, never fabricates provenance.
      def get_param(name: str) -> float:
          name_lower = name.lower()
          if name_lower in inputs:
              return inputs[name_lower]
          # Fallback strictly to validated cache lookup only
          with SESSION_DATA_CACHE_LOCK:
              cache = SESSION_DATA_CACHE.get(session_id, {})
              labeled = cache.get("labeled_values", {})
              if name_lower in labeled:
                  return float(labeled[name_lower])
              # whole-token (word-boundary) match only — never substring,
              # so 'm' cannot bind to 'rm' or 'cementation_m'.
              for ck, cv in labeled.items():
                  if name_lower in re.split(r'[^a-z0-9]+', str(ck).lower()):
                      return float(cv)
          raise _MissingParam(name)

      def opt(name: str):
          """Optional input: returns the value if present in inputs/cache, else None
          (never a fabricated constant). Used only for the archie_sw alternative-input
          chain (Ri vs Ro/Rt vs Rw)."""
          try:
              return get_param(name)
          except _MissingParam:
              return None
  ```

---

### Non-Fuzzy Whole-Token Regular Expression Matching Engine
* **File Path**: `c:\Users\Asus\Downloads\scal-ai-pipeline\app.py`
* **RegEx Segmentation Implementation**:
  ```python
      # 1. Parse Cache Lookups: {{val:cache_key}}
      def replace_cache(match):
          cache_key = match.group(1).strip()
          cache_key_lower = cache_key.lower()
          
          val = None
          with SESSION_DATA_CACHE_LOCK:
              cache = SESSION_DATA_CACHE.get(session_id, {})
              labeled = cache.get("labeled_values", {})
              if cache_key_lower in labeled:
                  val = labeled[cache_key_lower]
              else:
                  # whole-token match only — never substring. Prevents {{val:grain_density}}
                  # from fabricating a | CACHED | citation off an unrelated key. If the key is
                  # not in the session's cell index, val stays None -> unverified marker below.
                  import re as _re
                  for k, v in labeled.items():
                      if cache_key_lower in _re.split(r'[^a-z0-9]+', str(k).lower()):
                          val = v
                          break
  ```
  * **Proof of Robustness**: By matching strictly against elements returned by splitting the key strings with `re.split(r'[^a-z0-9]+', ...)`, substring pairings such as matching the request variable `'m'` against `'final_KL_mD'` are completely bypassed. Only absolute, exact token matches are honored.

---

### Strict Cache-Deficit Refusal Pathway
* **File Path**: `c:\Users\Asus\Downloads\scal-ai-pipeline\app.py`
* **Refusal Output Execution**:
  ```python
          if val is None:
              with SESSION_DATA_CACHE_LOCK:
                  gt = cache.get("ground_truth", "")
              if gt:
                  import re
                  match_gt = re.search(rf'(?i)\b{re.escape(cache_key)}\b.*?[:=]\s*(\d+(?:\.\d+)?)', gt)
                  if match_gt:
                      val = match_gt.group(1)
                      
          if val is not None:
              try:
                  val_float = float(val)
                  if val_float.is_integer():
                      val_str = str(int(val_float))
                  else:
                      val_str = f"{val_float:.3f}"
              except Exception:
                  val_str = str(val)
              return f"{val_str} | CACHED | HIGH"
          return "[unverified — absent from cache]"
  ```
  * **Behavior**: If the parameter is not present in both the labeled cache and the programmatic raw spreadsheet text block, the pipeline completely bypasses default constants and returns `[unverified — absent from cache]`.

---

## 3. MATHEMATICAL DETERMINISM & HARDENED FITTERS

### Hardened Archie Resistivity Index (RI) Fitter
* **File Path**: `c:\Users\Asus\Downloads\scal-ai-pipeline\app.py`
* **Full Production Source Code**:
  ```python
              # ── RESISTIVITY INDEX (Archie n fit, log-log) ───────────────────────────────
  
              if name == "fit_petrophysical_curve" and args.get("model") == "ri":
  
                  sid = getattr(_tls, 'current_session_id', None)
  
                  # STRICT CACHE-ONLY: fit exclusively on the verified cached column vectors
                  # the report engine uses. NO LLM/inline-arg fallback. No cache -> terminate.
                  sw_raw, ri_raw = [], []
                  if sid:
                      sw_raw = find_cached_vector(sid, ["sw", "water saturation", "saturation"])
                      ri_raw = find_cached_vector(sid, ["ri", "resistivity index", "index"])
                  if not sw_raw or not ri_raw:
                      return (
                          "⚠️ Resistivity Index fit aborted: no verified Sw / RI vectors are present "
                          "in the session cache. Upload the SCAL file so the fit runs strictly on "
                          "cached laboratory data — inline or model-supplied values are not accepted."
                      )
  
                  sample = args.get("sample_name", "Core")
  
                  if len(sw_raw) > 1 and len(ri_raw) > 1 and len(sw_raw) == len(ri_raw):
  
                      sw_a = np.array(sw_raw, dtype=float)
                      ri_a = np.array(ri_raw, dtype=float)
                      # Sort by Sw WITHOUT severing the measured Sw<->RI pairing
                      # (the prior independent re-sort of RI fabricated the lab scatter).
                      idx_sort = np.argsort(sw_a)
                      sw_a = sw_a[idx_sort]
                      ri_a = ri_a[idx_sort]
  
                      mask     = (sw_a > 0) & (ri_a > 0)
                      n_arch   = float(-np.polyfit(np.log(sw_a[mask]), np.log(ri_a[mask]), 1)[0])
  
                      # Physics boundary: Archie n in [1.5, 3.0]. Do NOT clamp-and-synthesize.
                      # Intercept gracefully so the text answer and the chart can never disagree.
                      if not (1.5 <= n_arch <= 3.0):
                          _audit_fail = PhysicsGuard().validate_archie(sw_a, ri_a, "RI").generate_health_score()
                          _log_physics_audit(getattr(_tls, 'current_session_id', 'ANONYMOUS'), "ri",
                                             _audit_fail, getattr(_tls, 'last_file_name', None))
                          return (
                              f"⚠️ Physics boundary check failed for the Resistivity Index fit: "
                              f"the fitted Archie saturation exponent n={n_arch:.3f} falls outside the valid "
                              f"reservoir-rock range [1.5, 3.0]. No RI chart was generated, to avoid emitting "
                              f"fabricated data points. Please verify the raw Sw / RI columns for sample '{sample}'."
                          )
  
                      sw_fit   = np.linspace(float(sw_a.min()), 1.0, 80)
                      ri_fit   = sw_fit ** (-n_arch)
  
                      plot_ri  = {
  
                          "title":    f"Resistivity Index  -  RI vs Sw ({sample})",
  
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
  
                      # ── Physics Guard ──────────────────────────────────────────────
  
                      audit = PhysicsGuard().validate_archie(sw_a, ri_a, "RI").generate_health_score()
  
                      plot_ri["metadata"]["physics_audit"] = audit
  
                      _log_physics_audit(
  
                          getattr(_tls, 'current_session_id', 'ANONYMOUS'), 
  
                          "ri", 
  
                          audit, 
  
                          getattr(_tls, 'last_file_name', None)
  
                      )
  
                      if sid:
  
                          with SESSION_DATA_CACHE_LOCK:
  
                              if sid not in SESSION_DATA_CACHE:
  
                                  SESSION_DATA_CACHE[sid] = {}
  
                              if "labeled_values" not in SESSION_DATA_CACHE[sid]:
  
                                  SESSION_DATA_CACHE[sid]["labeled_values"] = {}
  
                              SESSION_DATA_CACHE[sid]["labeled_values"]["n"] = n_arch
  
                              SESSION_DATA_CACHE[sid]["labeled_values"]["n_arch"] = n_arch
  
                              SESSION_DATA_CACHE[sid]["labeled_values"]["saturation_exponent"] = n_arch
  
                      return (
  
                          f"__PRC_PLOT__\n{_safe_json_dumps(plot_ri)}\n\n"
  
                      )
  ```

---

### Hardened Archie Formation Factor (FF) Fitter
* **File Path**: `c:\Users\Asus\Downloads\scal-ai-pipeline\app.py`
* **Full Production Source Code**:
  ```python
              # ── FORMATION FACTOR (Archie m, a fit, log-log) ───────────────────────────────
  
              if name == "fit_petrophysical_curve" and args.get("model") == "ff":
  
                  sid = getattr(_tls, 'current_session_id', None)
  
                  # STRICT CACHE-ONLY: fit exclusively on the verified cached column vectors
                  # the report engine uses. NO LLM/inline-arg fallback. No cache -> terminate.
                  phi_raw, ff_raw = [], []
                  if sid:
                      phi_raw = find_cached_vector(sid, ["porosity", "phi"])
                      ff_raw  = find_cached_vector(sid, ["ff", "formation factor"])
                  if not phi_raw or not ff_raw:
                      return (
                          "⚠️ Formation Factor fit aborted: no verified porosity / FF vectors are "
                          "present in the session cache. Upload the SCAL file so the fit runs strictly "
                          "on cached laboratory data — inline or model-supplied values are not accepted."
                      )
  
                  sample  = args.get("sample_name", "Core")
  
                  if len(phi_raw) > 1 and len(ff_raw) > 1 and len(phi_raw) == len(ff_raw):
  
                      phi_a   = np.array(phi_raw, dtype=float)
                      ff_a    = np.array(ff_raw,  dtype=float)
                      # Sort by porosity WITHOUT severing the measured phi<->FF pairing.
                      idx_sort = np.argsort(phi_a)
                      phi_a = phi_a[idx_sort]
                      ff_a = ff_a[idx_sort]
  
                      mask    = (phi_a > 0) & (ff_a > 0)
                      coeffs  = np.polyfit(np.log(phi_a[mask]), np.log(ff_a[mask]), 1)
                      m_arch  = float(-coeffs[0])
                      a_arch  = float(np.exp(coeffs[1]))
  
                      # Physics boundary: cementation m in [1.3, 3.5], tortuosity a in [0.3, 2.5].
                      # Intercept gracefully rather than clamping into range and synthesizing a curve.
                      if not (1.3 <= m_arch <= 3.5 and 0.3 <= a_arch <= 2.5):
                          _audit_fail = PhysicsGuard().validate_archie(phi_a, ff_a, "FF").generate_health_score()
                          _log_physics_audit(getattr(_tls, 'current_session_id', 'ANONYMOUS'), "ff",
                                             _audit_fail, getattr(_tls, 'last_file_name', None))
                          return (
                              f"⚠️ Physics boundary check failed for the Formation Factor fit: "
                              f"fitted m={m_arch:.3f}, a={a_arch:.3f} fall outside valid reservoir-rock ranges "
                              f"(m∈[1.3,3.5], a∈[0.3,2.5]). No FF chart was generated, to avoid emitting "
                              f"fabricated data points. Please verify the raw porosity / FF columns for sample '{sample}'."
                          )
  
                      phi_fit = np.linspace(float(phi_a.min()), float(phi_a.max()), 80)
                      ff_fit  = a_arch / (phi_fit ** m_arch)
  
                      plot_ff = {
  
                          "title":    f"Formation Factor  -  FF vs Porosity ({sample})",
  
                          "xAxis":    {"label": "Porosity Ï† (fraction)"},
  
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
  
                      # ── Physics Guard ──────────────────────────────────────────────
  
                      audit = PhysicsGuard().validate_archie(phi_a, ff_a, "FF").generate_health_score()
  
                      plot_ff["metadata"]["physics_audit"] = audit
  
                      _log_physics_audit(
  
                          getattr(_tls, 'current_session_id', 'ANONYMOUS'), 
  
                          "ff", 
  
                          audit, 
  
                          getattr(_tls, 'last_file_name', None)
  
                      )
  
                      if sid:
                          with SESSION_DATA_CACHE_LOCK:
                              if sid not in SESSION_DATA_CACHE:
                                  SESSION_DATA_CACHE[sid] = {}
                              if "labeled_values" not in SESSION_DATA_CACHE[sid]:
                                  SESSION_DATA_CACHE[sid]["labeled_values"] = {}
                              SESSION_DATA_CACHE[sid]["labeled_values"]["m"] = m_arch
                              SESSION_DATA_CACHE[sid]["labeled_values"]["a"] = a_arch
                              SESSION_DATA_CACHE[sid]["labeled_values"]["cementation_exponent"] = m_arch
                              SESSION_DATA_CACHE[sid]["labeled_values"]["tortuosity_factor"] = a_arch
  
                      return (
  
                          f"__PRC_PLOT__\n{_safe_json_dumps(plot_ff)}\n\n"
  
                      )
  ```

---

### Displacement Efficiency Math Formula
* **File Path**: `c:\Users\Asus\Downloads\scal-ai-pipeline\app.py`
* **Hardcoded Expression**:
  ```python
      elif formula_id == "displacement_efficiency":
          sor = get_param("sor")
          swi = get_param("swi")
          if sor > 1.0: sor /= 100.0
          if swi > 1.0: swi /= 100.0
          return (1.0 - swi - sor) / (1.0 - swi)
  ```

---

### Scoped Fluid Saturation Validation Gate
* **File Path**: `c:\Users\Asus\Downloads\scal-ai-pipeline\data_validator.py`
* **Full Production Source Code**:
  ```python
  def validate_scal_data(json_data: List[Dict[str, Any]]) -> dict:
      """
      Validates a list of SCAL data extracted into JSON format by checking physical bounds and sequence logic.
      
      Validation Checks:
      1. Porosity Bounds: Porosity_percent must be between 0 and 100.
      2. Air Permeability Bounds: Air_Permeability_md must be >= 0.
      3. Pressure Sequence: Pressure_psi must be strictly increasing.
      4. Null Handling: Flags any missing (null) data points (Required keys vs Optional keys).
      
      Returns:
          {"status": "success", "data": json_data, "warnings": warnings} if valid.
          {"status": "error", "errors": errors, "warnings": warnings} if invalid.
      """
      errors = []
      warnings = []
      
      if not isinstance(json_data, list):
          return {"status": "error", "errors": ["Input must be a JSON array (list of objects)."], "warnings": []}
          
      previous_pressure = None
      
      # Core keys that we *prefer* for SCAL plotting, but will only warn if missing to prevent data loss
      PREFERRED_KEYS = {"Pressure_psi", "Porosity_percent", "Air_Permeability_md"}
      
      for idx, row in enumerate(json_data):
          sample_num = idx + 1
          pressure = row.get("Pressure_psi")
          porosity = row.get("Porosity_percent")
          perm = row.get("Air_Permeability_md")
          
          pressure_label = f"{pressure} psi" if pressure is not None else "Unknown psi"
          prefix = f"Sample {sample_num}, {pressure_label}"
          
          # 1. Null checking (Required keys are errors, optional keys are warnings)
          for key in ["Pressure_psi", "Porosity_percent"]:
              if row.get(key) is None:
                  errors.append(f"{prefix}: Missing data (null) found for required key '{key}'.")
          if row.get("Air_Permeability_md") is None and row.get("Pressure_psi") != 0.0:
              warnings.append(f"{prefix}: Missing data (null) found for key 'Air_Permeability_md'.")
              
          for key, value in row.items():
              if value is None and key not in PREFERRED_KEYS:
                  warnings.append(f"{prefix}: Missing data (null) found for key '{key}'.")
                  
          # 2. Porosity Bounds (Physical impossibility -> hard error)
          if porosity is not None:
              if not isinstance(porosity, (int, float)) or porosity < 0 or porosity > 100:
                  errors.append(f"{prefix}: Porosity value out of bounds (must be 0-100%, got {porosity}).")
                  
          # 3. Permeability Bounds (Physical impossibility -> hard error)
          if perm is not None:
              if not isinstance(perm, (int, float)) or perm < 0:
                  errors.append(f"{prefix}: Air_Permeability_md cannot be negative (got {perm}).")
                  
          # 4. Pressure Sequence (must be strictly increasing within each sweep)
          if pressure is not None:
              if not isinstance(pressure, (int, float)):
                  errors.append(f"{prefix}: Pressure_psi must be a number.")
              else:
                  if previous_pressure is not None and pressure <= previous_pressure:
                      errors.append(f"{prefix}: Pressure_psi must be strictly increasing (previous={previous_pressure}, current={pressure}).")
                  previous_pressure = pressure
  
      if errors:
          return {
              "status": "error",
              "errors": errors,
              "warnings": warnings
          }
  
      # ── PHASE 2: CROSS-FIELD PHYSICS DOMAIN BOUNDARIES ──────────────────────
      # These hardcoded checks catch hallucinated values BEFORE the Expert Insight
      # node can write its summary. No LLM prompt — pure Python logic gates.
  
      for idx, row in enumerate(json_data):
          sample_num = idx + 1
          pressure = row.get("Pressure_psi")
          pressure_label = f"{pressure} psi" if pressure is not None else "Unknown psi"
          prefix = f"Sample {sample_num}, {pressure_label}"
  
          # 5. Formation Factor must be >= 1.0 (by definition: FF = Ro/Rw >= 1)
          ff = row.get("Formation_Factor")
          if ff is not None and isinstance(ff, (int, float)):
              if ff < 1.0:
                  errors.append(f"{prefix}: Formation Factor = {ff} < 1.0 — physically impossible (FF = Ro/Rw ≥ 1.0 by definition).")
  
          # 6. Water Saturation must be in [0, 1] (fraction) or [0, 100] (percent)
          sw = row.get("Water_Saturation_fraction")
          if sw is not None and isinstance(sw, (int, float)):
              if sw < 0 or sw > 1.0:
                  # Check if it's in percent
                  if sw > 1.0 and sw <= 100.0:
                      warnings.append(f"{prefix}: Water_Saturation_fraction = {sw} appears to be in percent, not fraction.")
                  elif sw > 100.0 or sw < 0:
                      errors.append(f"{prefix}: Water_Saturation_fraction = {sw} outside valid range [0, 1].")
  
          # 7. Klinkenberg Permeability should be <= Air Permeability (gas slippage correction)
          kl = row.get("Klinkenberg_Permeability_md")
          ka = row.get("Air_Permeability_md")
          if kl is not None and ka is not None and isinstance(kl, (int, float)) and isinstance(ka, (int, float)):
              if kl > ka * 1.05:  # 5% tolerance for measurement uncertainty
                  warnings.append(f"{prefix}: Klinkenberg Perm ({kl} mD) > Air Perm ({ka} mD) — Klinkenberg correction should reduce permeability, not increase it.")
  
          # 8. Pore Volume Compressibility bounds (if present)
          cp = row.get("Pore_Volume_Compressibility_psi_inv")
          if cp is not None and isinstance(cp, (int, float)):
              if cp < 0:
                  errors.append(f"{prefix}: Cp = {cp:.2e} psi⁻¹ is negative — pore volume cannot expand under compression.")
              elif cp > 50.0e-6:
                  errors.append(f"{prefix}: Cp = {cp:.2e} psi⁻¹ exceeds 50×10⁻⁶ — physically implausible for any reservoir rock.")
              elif cp > 30.0e-6:
                  warnings.append(f"{prefix}: Cp = {cp:.2e} psi⁻¹ is very high (>30×10⁻⁶) — only valid for unconsolidated chalk/diatomite.")
  
          # 9. Resistivity Index must be >= 1.0 (by definition)
          ri = row.get("Resistivity_Index")
          if ri is not None and isinstance(ri, (int, float)):
              if ri < 1.0:
                  errors.append(f"{prefix}: Resistivity Index = {ri} < 1.0 — physically impossible (RI = Rt/Ro ≥ 1.0 by definition).")
  
      # 10. Drainage Physics Validation: Water saturation must not increase as capillary pressure increases
      previous_sw = None
      previous_pc = None
      for idx, row in enumerate(json_data):
          sample_num = idx + 1
          pc = row.get("Capillary_Pressure_psi") or row.get("Pc_psi") or row.get("Pressure_psi")
          sw = row.get("Water_Saturation_fraction") or row.get("Water_Saturation_percent") or row.get("Water_Saturation")
          
          if pc is not None and sw is not None and isinstance(pc, (int, float)) and isinstance(sw, (int, float)):
              sw_frac = sw / 100.0 if sw > 1.0 else sw
              # Reset tracking if a new sweep starts (e.g. pressure drops)
              if previous_pc is not None and pc < previous_pc:
                  previous_sw = None
                  previous_pc = None
                  
              if previous_sw is not None and previous_pc is not None:
                  if pc > previous_pc and sw_frac > previous_sw + 0.001:
                      errors.append(
                          f"Sample {sample_num}: Drainage physics violation — water saturation increased "
                          f"({previous_sw:.4f} -> {sw_frac:.4f}) as capillary pressure increased ({previous_pc} -> {pc} psi)."
                      )
              previous_sw = sw_frac
              previous_pc = pc
  
      if errors:
          return {
              "status": "error",
              "errors": errors,
              "warnings": warnings
          }
          
      return {
          "status": "success",
          "data": json_data,
          "warnings": warnings
      }
  ```

---

## 4. SYSTEM PROMPT PERSISTENCE

### Phase 6: Refusal Protocol & Confidence Declaration
* **File Path**: `c:\Users\Asus\Downloads\scal-ai-pipeline\prompts\hviel_system_prompt.md`
* **Raw Prompts Content (Phase 6)**:
  ```markdown
  # PHASE 6: REFUSAL PROTOCOL
  
  You MUST refuse, and report the refusal in the UI structure above, when:
  
  - The uploaded file cannot be parsed. State which engines were tried (openpyxl, xlrd, pyxlsb, csv) and the exact error from each.
  
  - The user references a file not currently uploaded in this chat.
  
  - The user requests SCAL parameters but no SCAL data was uploaded. If a parameter or file is not present, write `[NOT IN THIS UPLOAD]` or `[NOT IN DATA]`.
  
  - The data contradicts physics (RI < 1 at Sw < 1, Pc decreasing during drainage, negative saturations, etc.). Flag the violation and stop - do not smooth, interpolate, or "fix" the data silently.
  
  - The USER'S PREMISE contradicts the cached data trend. Before agreeing with any claimed change ("permeability increased ~2000%", "porosity doubled", "Sw improved"), compute the actual direction and magnitude from the cached raw vectors / labeled values for that property. If the user's asserted direction or magnitude disagrees with the cache (e.g. the user says "increase" but the cached series decreases), you MUST NOT confirm the premise: trigger a critical violation flag, state the actual cached trend with its numbers, and reject the false claim. Never affirm an engineering result you cannot reproduce from the session cache.
  
  
  
  When refusing, still fill every UI section with the specific reason that section is empty, so the user knows exactly what is missing.
  ```

  ```markdown
  ═══════════════════════════════════════════════════════════════
  PHASE 6 — CONFIDENCE DECLARATION
  ═══════════════════════════════════════════════════════════════
  
  Before any result leaves your hands, declare for each output:
  
      UNIT CONFIDENCE    : HIGH / MEDIUM / LOW
      FORMULA VERIFIED   : YES / NO
      PHYSICS CHECK      : PASSED / FAILED / N/A
      CROSS-VALIDATED    : YES / NO / NOT POSSIBLE
      ASSUMPTIONS MADE   : [list every one]
      RISK FLAGS         : [list anything uncertain]
  
  Any LOW, FAILED, or NO must be flagged at the TOP of the
  response, not buried at the bottom.
  
  NO PLACEHOLDERS. Strings like "[NOT YET CHECKED]" or
  "[TBD]" must never appear in the final output. If you
  cannot compute a value, omit the field and explain why.
  ```
