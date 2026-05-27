"""
SCAL AI - File Handler
======================
This is the exact logic used to read, identify, and extract
data from any SCAL file uploaded by an engineer.

Usage:
    handler = SCALFileHandler(file_path)
    result = handler.process()
    # result contains: data_type, dataframes, summary, raw_text
"""

import re
import io
from pathlib import Path
import pandas as pd
import numpy as np
import json
import os


class SCALFileHandler:

    def __init__(self, file_path: str):
        self.file_path = file_path
        self.extension = os.path.splitext(file_path)[1].lower()
        self.sheet_names = []
        self.raw_data = {}      # sheet_name -> DataFrame (raw, no header)
        self.data_type = None   # identified SCAL type
        self.extracted = {}     # cleaned, ready-to-plot data

    # ------------------------------------------------------------------ #
    # STEP 1 — READ THE FILE (extension-aware)
    # ------------------------------------------------------------------ #

    def read(self):
        """Read ALL sheets in the workbook without filtering by name.

        The previous optimisation that whitelisted sheet names by keyword
        silently dropped sheets named "Sample 1", "Sample 2", etc.
        For SCAL files we cannot afford silent data loss — read everything
        and let the extractor decide what is relevant.
        """
        if self.extension in ('.xlsx', '.xlsm', '.xls', '.ods'):
            engine = (
                'openpyxl' if self.extension in ('.xlsx', '.xlsm')
                else ('xlrd' if self.extension == '.xls' else 'odf')
            )
            xl = pd.ExcelFile(self.file_path, engine=engine)
            self.sheet_names = xl.sheet_names

            for sheet in self.sheet_names:
                self.raw_data[sheet] = pd.read_excel(
                    xl, sheet_name=sheet, header=None
                )

        elif self.extension == '.csv':
            df = pd.read_csv(self.file_path, header=None)
            self.sheet_names = ['Sheet1']
            self.raw_data['Sheet1'] = df

        else:
            raise ValueError(f"Unsupported file type: {self.extension}")

        return self

    # ------------------------------------------------------------------ #
    # STEP 2 — IDENTIFY DATA TYPE (keyword scan across all sheets)
    # ------------------------------------------------------------------ #

    KEYWORDS = {
        'MICP': [
            'mercury', 'hg', 'intrusion', 'psia', 'mpa', 'threshold pressure',
            'drainage', 'imbibition', 'cumulative intrusion',
            'capillary pressure', 'pore throat', 'washburn', 'saturation'
        ],
        'KR': [
            'kro', 'krw', 'krg', 'relative permeability',
            'end point', 'sor', 'swi', 'sgr', 'water flood', 'kr', 'permeability'
        ],
        'PC': [
            'porous plate', 'centrifuge', 'brine saturation', 'oil-brine', 'air-brine',
            'reservoir conditions', 'rpm', 'speed', 'produced volume', 'cc', 'g-force',
            'capillary pressure', 'drainage', 'imbibition', 'drainge', 'saturation'
        ],
        'FRF': [
            'formation factor', 'formation resistivity factor',
            'cementation', 'tortuosity', '100% brine', 'archie', 'rt', 'ro', 'phi', 'porosity'
        ],
        'RI': [
            'resistivity index', 'saturation exponent',
            'partial saturation', 'rt', 'ro', ' ri ', 'sw', 'saturation'
        ],
        'WETTABILITY': [
            'amott', 'usbm', 'wettability index', 'iw', 'io',
            'spontaneous imbibition', 'water wet', 'oil wet'
        ],
        'NMR': [
            'nmr', 't2', 't2 distribution', 'relaxation', 'bvi',
            'ffi', 'free fluid', 'bulk volume irreducible', 't2 cutoff'
        ],
        'PVT': [
            'bo', 'rs', 'gor', 'bubble point', 'dew point',
            'bg', 'formation volume factor', 'differential liberation'
        ],
        'RCAL': [
            'routine core', 'air permeability', 'klinkenberg',
            'grain density', 'plug', 'horizontal perm', 'vertical perm'
        ],
        # Formation-damage / sensitivity test: KL (mD) vs cumulative PV injected.
        # 'sensitivity test' and 'kl' are scored higher to beat KR/RCAL.
        'FDAM': [
            'kl', 'sensitivity test', 'formation damage',
            'fluid sensitivity', 'cum.pv.inj',
        ],
    }

    def identify(self):
        """Scan all sheets for keywords to identify the SCAL data type."""
        scores = {k: 0 for k in self.KEYWORDS}

        for sheet, df in self.raw_data.items():
            # Flatten all cell values to one big lowercase string
            text = ' '.join(
                str(v).lower()
                for v in df.values.flatten()
                if pd.notna(v)
            )
            for data_type, keywords in self.KEYWORDS.items():
                for kw in keywords:
                    if kw in text:
                        weight = (10 if kw in ['rpm', 'centrifuge', 'speed', 'produced volume', 'sensitivity test']
                                  else 5 if kw == 'kl'
                                  else 1)
                        scores[data_type] += weight

        best = max(scores, key=scores.get)
        if scores[best] == 0:
            self.data_type = 'UNKNOWN'
        else:
            self.data_type = best

        return self

    # ------------------------------------------------------------------ #
    # STEP 3 — EXTRACT DATA (type-specific parsers)
    # ------------------------------------------------------------------ #

    def extract(self):
        """Route to the correct extractor based on identified data type."""
        from extractors.micp import MICPExtractor
        from extractors.kr import KRExtractor
        from extractors.pc import PCExtractor
        from extractors.rcal import RCALExtractor
        from extractors.other import (
            FRFExtractor, RIExtractor, NMRExtractor,
            PVTExtractor, WettabilityExtractor, FDAMExtractor
        )

        extractors = {
            'MICP':        MICPExtractor,
            'KR':          KRExtractor,
            'FRF':         FRFExtractor,
            'RI':          RIExtractor,
            'NMR':         NMRExtractor,
            'PVT':         PVTExtractor,
            'RCAL':        RCALExtractor,
            'WETTABILITY': WettabilityExtractor,
            'PC':          PCExtractor,
            'FDAM':        FDAMExtractor,
        }

        extractor_class = extractors.get(self.data_type)
        if extractor_class:
            extractor = extractor_class(self.raw_data)
            self.extracted = extractor.extract()
        else:
            self.extracted = {'type': 'UNKNOWN', 'samples': {}}
        return self

    # ------------------------------------------------------------------ #
    # WELL NAME EXTRACTION
    # ------------------------------------------------------------------ #

    def _extract_well_name(self) -> str:
        """
        Identify the well name from sheet headers or the filename.
        Scans for 'Well', 'Field', 'Reservoir', 'Project', etc.
        """
        # ── 1. HEADER SCAN ──
        # Expanded keywords to catch legacy or non-standard reports
        patterns = [
            re.compile(r'well\s*[#:no.]*\s*', re.IGNORECASE),
            re.compile(r'field\s*', re.IGNORECASE),
            re.compile(r'reservoir\s*', re.IGNORECASE),
            re.compile(r'project\s*', re.IGNORECASE),
            re.compile(r'block\s*', re.IGNORECASE),
        ]

        for _sheet, _df in self.raw_data.items():
            # Scan top 15 rows of each sheet
            for i in range(min(50, len(_df))):
                _row = _df.iloc[i].tolist()
                for j, _cell in enumerate(_row):
                    if isinstance(_cell, str):
                        for pat in patterns:
                            if pat.search(_cell):
                                # Check next 3 cells for the value
                                for k in range(j + 1, min(j + 5, len(_row))):
                                    _val = str(_row[k]).strip()
                                    if _val and _val.lower() not in ('#', 'no.', 'name', 'well', 'field', 'nan'):
                                        # Validate value length and content
                                        if 1 < len(_val) < 40 and not _val.lower().startswith('unnamed'):
                                            return _val
        
        # ── 2. FILENAME FALLBACK ──
        _stem = os.path.splitext(os.path.basename(self.file_path))[0]
        # Common well patterns: T1-31, A-12, B_10, etc.
        well_match = re.search(r'([A-Z]{1,3}[-_]?\d{1,4}[A-Z]?)', _stem, re.IGNORECASE)
        if well_match:
            return well_match.group(1).upper()

        # Token based fallback
        for _token in re.split(r'[_\-\s]+', _stem):
            if 3 <= len(_token) <= 15 and re.search(r'[A-Za-z]', _token) and re.search(r'\d', _token):
                return _token

        return "PROVISIONAL WELL"

    def _extract_all_metadata(self) -> dict:
        """
        Bug 1 fix — extract well, company, and sample from labeled header cells.

        Scans every sheet for cells whose text matches a label pattern
        ('Well #:', 'Well No:', 'Company :', 'Sample    :', etc.) and reads
        the adjacent cell value.  Sample sheets are processed before
        viscosity/summary sheets so that the primary sample data wins.

        Returns: {'well': str|None, 'company': str|None, 'sample': str|None}
        """
        meta: dict = {'well': None, 'company': None, 'sample': None}

        label_re = {
            'well':    re.compile(r'well\s*[#no.:]*\s*$', re.IGNORECASE),
            'company': re.compile(r'company\s*[#:]*\s*$',  re.IGNORECASE),
            'sample':  re.compile(r'sample\s*[#:]*\s*$',   re.IGNORECASE),
        }

        def _priority(name: str) -> int:
            n = name.lower()
            if re.search(r'\bsample\b', n):
                return 0                                 # individual sample sheet
            if re.search(r'viscosity|summary|all\b|composite|sheet\d', n):
                return 2                                 # aggregate / ancillary
            return 1

        for _sheet, _df in sorted(self.raw_data.items(), key=lambda kv: _priority(kv[0])):
            if all(v is not None for v in meta.values()):
                break
            for i in range(min(40, len(_df))):
                _row = _df.iloc[i].tolist()
                for j, cell in enumerate(_row):
                    if not isinstance(cell, str):
                        continue
                    cell_s = cell.strip()
                    for field, pat in label_re.items():
                        if meta[field] is not None:
                            continue
                        if pat.search(cell_s):
                            for k in range(j + 1, min(j + 6, len(_row))):
                                val = str(_row[k]).strip()
                                if val and val.lower() not in ('nan', '', '#', 'no.'):
                                    meta[field] = val
                                    break

        if meta['well'] is None:
            meta['well'] = self._extract_well_name()

        return meta

    # ------------------------------------------------------------------ #
    # MAIN ENTRY POINT
    # ------------------------------------------------------------------ #

    def process(self):
        """Run the full pipeline: read → identify → extract."""
        self.read()
        self.identify()
        self.extract()
        meta = self._extract_all_metadata()
        return {
            'data_type':   self.data_type,
            'sheet_names': self.sheet_names,
            'extracted':   self.extracted,
            'row_count':   self._count_rows(self.extracted),
            'well_name':   meta.get('well') or 'PROVISIONAL WELL',
            'company':     meta.get('company') or '',
            'sample':      meta.get('sample') or '',
        }

    def _count_rows(self, data: dict) -> int:
        """Helper to count total data points for AI acknowledgment."""
        count = 0
        if isinstance(data, dict):
            for v in data.values():
                count += self._count_rows(v)
        elif isinstance(data, list):
            count += len(data)
        return count


# ------------------------------------------------------------------ #
# SEND TO AI — build the prompt with extracted data
# ------------------------------------------------------------------ #

def build_prompt_for_ai(processed: dict) -> str:
    """
    Takes the output of SCALFileHandler.process() and builds a structured
    prompt for the AI so it can analyse and plot the data correctly.

    MICP data is routed through a purpose-built prompt that handles
    summary-sheet disambiguation, correct Pd extraction, and an explicit
    anti-fabrication guardrail for geological interpretation.
    """
    data_type = processed['data_type']
    extracted  = processed['extracted']

    if data_type == 'UNKNOWN':
        return (
            "I could not identify the data type in this file. "
            "Please check the file and re-upload."
        )

    _well    = processed.get('well_name', 'PROVISIONAL WELL')
    _company = processed.get('company', '')
    _sample  = processed.get('sample', '')
    _meta_header = (
        f"SOURCE WELL: {_well}\n"
        + (f"COMPANY: {_company}\n" if _company else "")
        + (f"SAMPLE: {_sample}\n"   if _sample  else "")
    )

    if data_type in ('PDF', 'DOCX'):
        raw_text = extracted.get('raw_text', '')
        return (
            f"The engineer has uploaded a {data_type} document for petrophysical analysis.\n"
            f"{_meta_header}\n"
            f"DOCUMENT CONTENT:\n{raw_text}\n\n"
            f"Instructions:\n"
            f"1. Identify all SCAL measurements, parameters, and petrophysical data present.\n"
            f"2. State every value with its units explicitly as written in the document.\n"
            f"3. If tables or curves are described, reproduce the key values in structured form.\n"
            f"4. Do NOT fabricate data not present in the document."
        )

    if data_type == 'MICP':
        return _build_micp_prompt(extracted, _well, _company)

    if data_type == 'FDAM':
        return _build_fdam_prompt(extracted, _well, _company)

    # Generic prompt for all other data types
    data_json = json.dumps(extracted, indent=2)
    return f"""
You are a petrophysics AI assistant. The engineer has uploaded a SCAL file.
I have already read and extracted the data for you. Do not read the file again.

{_meta_header}
Data type identified: {data_type}

Extracted data (each top-level key is the Excel sheet name the data came from):
{data_json}

Instructions:
1. Plot the appropriate curve for {data_type} data using the extracted values above.
2. Use the correct axis scales and labels as per petroleum engineering standards.
   If a 'units_detected' field is present, state the original units in chart axis labels
   and note if values were normalised from percent to fraction.
3. After the chart, give 3-5 bullet points of key observations.
4. Do NOT generate or invent any data. Use only what is provided above.
5. All data comes from the same well. Do not fabricate geological differences
   between sheets just because values differ — sample-to-sample variation is normal.
"""


def _build_fdam_prompt(extracted: dict, well_name: str = "PROVISIONAL WELL",
                       company: str = "") -> str:
    """Prompt for Formation Damage (Sensitivity Test / Kw vs Throughput) data."""
    data_json = json.dumps(extracted, indent=2)
    meta_line = f"SOURCE WELL: {well_name}" + (f"\nCOMPANY: {company}" if company else "")
    return f"""
You are a petrophysics AI assistant. The engineer has uploaded a Formation Damage
(Sensitivity Test / Kw vs Throughput) file. The data has been pre-extracted below.

{meta_line}

EXTRACTED DATA (one entry per Excel sheet = one core plug):
{data_json}

Each sample entry contains:
  KL_mD           — list of liquid permeability (mD) values in measurement order
  Cum_PV_injected — cumulative pore volumes injected at each measurement point
  initial_KL_mD   — baseline permeability (first measurement)
  final_KL_mD     — permeability after flooding (last measurement)
  KL_change_pct   — % change = (final − initial) / initial × 100

INSTRUCTIONS:
1. For EVERY sample sheet, report initial KL, final KL, and KL change (%) to 3 d.p.
   Use ONLY the values in initial_KL_mD and final_KL_mD — do NOT re-derive them.
2. Plot KL (mD) on the Y-axis vs Cumulative PV Injected on the X-axis, all samples.
3. Classify formation damage severity per sample:
     < 0 % change       → permeability improvement (note if observed)
     0 – 20 % reduction → minor damage
     20 – 50 % reduction → moderate damage
     > 50 % reduction   → severe damage
4. Do NOT invent or interpolate values. Every number must come from the extracted data.
"""


def _build_micp_prompt(extracted: dict, well_name: str = "PROVISIONAL WELL",
                       company: str = "") -> str:
    """
    Purpose-built MICP prompt that enforces:
      FIX 2 — summary vs. sample sheet disambiguation
      FIX 4 — anti-hallucination guardrail for geological interpretation
    """
    samples = extracted.get('samples', {})

    sample_sheets  = [k for k, v in samples.items() if isinstance(v, dict) and v.get('sheet_type') == 'sample']
    summary_sheets = [k for k, v in samples.items() if isinstance(v, dict) and v.get('sheet_type') == 'summary']

    sample_list_str  = '\n'.join(f'  - "{s}"' for s in sample_sheets)  or '  (none detected)'
    summary_list_str = '\n'.join(f'  - "{s}"' for s in summary_sheets) or '  (none)'

    data_json = json.dumps(extracted, indent=2)

    meta_line = f"SOURCE WELL: {well_name}" + (f"\nCOMPANY: {company}" if company else "")
    return f"""
You are a petrophysics AI assistant performing MICP (Mercury Injection Capillary Pressure) analysis.
The file has already been parsed. The extracted data is below. Do NOT re-read the file.

{meta_line}
═══════════════════════════════════════════════════════════
SHEET CLASSIFICATION (determined by sheet name)
═══════════════════════════════════════════════════════════
Individual sample sheets — use ONLY these for per-sample analysis:
{sample_list_str}

Summary / aggregate sheets — these consolidate data across samples.
Do NOT treat them as distinct rock samples or distinct data sources:
{summary_list_str}

═══════════════════════════════════════════════════════════
EXTRACTED DATA  (keyed by exact Excel sheet name)
═══════════════════════════════════════════════════════════
{data_json}

═══════════════════════════════════════════════════════════
MANDATORY ANALYSIS INSTRUCTIONS
═══════════════════════════════════════════════════════════

1. PER-SAMPLE ANALYSIS ONLY
   Analyse and report results individually for each sheet listed under
   "Individual sample sheets" above. Do NOT analyse summary/aggregate
   sheets as independent rock samples. If a summary sheet is present,
   note it exists but do not compare its aggregated values against
   individual sample curves as if they represent different rocks.

2. SATURATION COLUMN VALIDATION
   Each sample entry includes a "sat_column_used" field — the exact
   column header extracted from the file.
   • If "sat_is_percent" is true, values are already in % (0–100). Use as-is.
   • If "sat_is_percent" is false, values are fractional (0–1). Multiply by 100
     before reporting or plotting.
   Report the maximum Hg saturation reached (%) for every sample.

3. ENTRY (THRESHOLD) PRESSURE Pd PER SAMPLE
   Each sample entry includes a 'threshold_pressure_psi' field read directly
   from the labeled cell in the file. Use that value as Pd — do NOT re-derive it.
   If the field is null, infer Pd from the drainage curve as the pressure at which
   Hg saturation first rises meaningfully (the "knee" of the curve).
   State Pd clearly as: "Sample X (sheet: <sheet_name>): Pd = N psia"

4. PORE THROAT SIZE ESTIMATE
   Using the Washburn equation (assuming IFT = 485 dyne/cm, contact angle = 140°):
     r_μm ≈ 107 / Pc_psia
   Categorise dominant pore throats as:
     macro (>10 μm) | meso (1–10 μm) | micro (0.1–1 μm) | nano (<0.1 μm)

5. PLOT
   Generate a semi-log plot:
     X-axis: Hg Saturation (%)  — linear scale, 0 to 100
     Y-axis: Capillary Pressure — log scale
   One curve per individual sample sheet. Use distinct colours. Mark Pd
   for each sample with a vertical dashed line or annotation.

6. ══ ANTI-FABRICATION GUARDRAIL — READ AND ENFORCE ══
   • ALL data comes from the SAME well.
   • Different threshold pressures (Pd) between samples are NORMAL —
     they reflect natural pore-size heterogeneity within the same formation.
   • Do NOT interpret differing Pd values as evidence of different rock
     types, different facies, or different geological formations UNLESS
     the uploaded data explicitly contains depth intervals or lithology
     annotations that support such a conclusion.
   • Do NOT hallucinate geological facies names, formation names, or
     depositional environment descriptions.
   • Confine all geological language strictly to what the numbers directly
     support — e.g. "Sample 3 has a higher Pd (smaller pore throats) than
     Sample 1" is correct. "Sample 3 represents a tighter, lower-quality
     facies from a different stratigraphic interval" is fabrication unless
     depth data is present.
   • Every number you report must be directly traceable to the extracted
     data above. Do not invent, interpolate, or extrapolate values.
"""


# ------------------------------------------------------------------ #
# ROBUST FALLBACK EXTRACTOR (unchanged — do not modify)
# ------------------------------------------------------------------ #

# ── Unicode and composite-label normalisation ─────────────────────────────────

_UNICODE_TRANS = str.maketrans({
    'φ': 'phi', 'Φ': 'Phi',   # φ / Φ  (porosity)
    'ρ': 'rho',                     # ρ  (density)
    '²': '2',                       # ²  (squared)
    'µ': 'u',                       # μ  (micro)
    '°': 'deg',                     # °
})

_HDR_NORMS = [
    # Composite tokens that appear in multi-row / merged-cell headers
    (re.compile(r'\(\s*%\s*\)'),                                    'pct'),
    (re.compile(r'cementation\s+(?:factor|exp(?:onent)?)',re.I),    'cementation_m'),
    (re.compile(r'formation\s+(?:resistivity\s+)?factor',  re.I),  'ff'),
    (re.compile(r'exponent\s*["\']?\s*m\s*["\']?',         re.I),  'exp_m'),
    (re.compile(r'confin(?:ing)?\s*(?:pres(?:sure)?)?',    re.I),  'confining_psi'),
    (re.compile(r'over\s*burden',                          re.I),  'obp_psi'),
]


def _normalize_header_cell(label: str) -> str:
    """Translate Unicode code-points and normalize composite SCAL column labels."""
    label = label.translate(_UNICODE_TRANS)
    for pat, replacement in _HDR_NORMS:
        label = pat.sub(replacement, label)
    return re.sub(r'\s+', ' ', label).strip()


def _merge_header_rows(df_raw, header_row: int, data_start: int) -> list:
    """Build a column-label list by merging rows [header_row, data_start).

    For each column, the first non-empty string value across those rows wins.
    Subsequent non-empty strings in later rows are appended only when they add
    new information (avoids duplicating merged-cell content read by xlrd/openpyxl).
    All labels are Unicode-normalized via _normalize_header_cell.
    """
    n_cols = df_raw.shape[1]
    merged = [f"col_{c}" for c in range(n_cols)]

    for row_idx in range(header_row, data_start):
        row = df_raw.iloc[row_idx].tolist()
        for c, val in enumerate(row):
            if c >= n_cols:
                break
            if not (isinstance(val, str) and val.strip()):
                continue
            norm = _normalize_header_cell(val.strip())
            if merged[c] == f"col_{c}":
                merged[c] = norm
            elif norm.lower() not in merged[c].lower():
                # Append context from a second header row (e.g. "(mD)" after "Perm")
                merged[c] = f"{merged[c]} {norm}"

    return merged


def _detect_data_block(df_raw):
    n_rows, n_cols = df_raw.shape
    if n_rows < 2 or n_cols < 2:
        return None, None, None

    numeric_counts = []
    for i in range(n_rows):
        row = df_raw.iloc[i]
        count = sum(1 for v in row if pd.notna(v) and isinstance(v, (int, float)) and not isinstance(v, bool))
        numeric_counts.append(count)

    for i in range(n_rows - 2):
        if numeric_counts[i] >= 3 and numeric_counts[i+1] >= 3:
            data_start = i
            data_end = data_start
            for j in range(data_start, n_rows):
                if numeric_counts[j] >= 2:
                    data_end = j
                else:
                    if data_end - data_start >= 2:
                        break

            # Scan backward up to 5 rows for the last text-rich header row.
            # "Text-rich" = has ≥2 string values and more strings than bare numbers —
            # this skips single-cell annotations like "R² =" or "slope =" that often
            # sit between the real column labels and the data block in lab spreadsheets.
            header_row = max(0, data_start - 1)
            for back in range(1, min(data_start + 1, 6)):
                candidate = data_start - back
                if candidate < 0:
                    break
                row_vals = df_raw.iloc[candidate].tolist()
                str_count = sum(1 for v in row_vals
                                if isinstance(v, str) and v.strip())
                num_count = sum(1 for v in row_vals
                                if pd.notna(v) and isinstance(v, (int, float))
                                and not isinstance(v, bool))
                if str_count >= 2 and str_count >= num_count:
                    header_row = candidate
                    break

            return header_row, data_start, data_end
    return None, None, None


def _extract_metadata(df_raw, data_start_idx):
    meta = {}
    patterns = {
        "well":       re.compile(r"well\s*[#:]*", re.IGNORECASE),
        "company":    re.compile(r"company", re.IGNORECASE),
        "analyst":    re.compile(r"analyst", re.IGNORECASE),
        "date":       re.compile(r"\bdate\b", re.IGNORECASE),
        "n_samples":  re.compile(r"no\.?\s*of\s*samples|number of samples", re.IGNORECASE),
        "brine_res":  re.compile(r"brine.*resist", re.IGNORECASE),
        "salinity":   re.compile(r"salinity", re.IGNORECASE),
        "pressure":   re.compile(r"\bpressure\b|overburden", re.IGNORECASE),
        "temperature":re.compile(r"\btemp(?:erature)?\b", re.IGNORECASE),
    }
    scan_rows = min(data_start_idx, 50)
    for i in range(scan_rows):
        row = df_raw.iloc[i].tolist()
        for j, cell in enumerate(row):
            if isinstance(cell, str):
                for field, pat in patterns.items():
                    if pat.search(cell) and field not in meta:
                        for k in range(j+1, min(j+5, len(row))):
                            v = row[k]
                            if pd.notna(v) and (not isinstance(v, str) or v.strip()):
                                meta[field] = v
                                break
    return meta


def _classify_track(headers, data):
    header_str = " ".join(str(h).lower() for h in headers if pd.notna(h))

    # FF checked before RI: "porosity" contains "ri" as a substring, which would
    # cause a false-positive RI match for Formation Factor sheets.
    # Post-normalization, "Formation factor" → "ff" and "Cementation factor" → "cementation_m".
    if ("formation factor" in header_str or "cementation" in header_str
            or "cementation_m" in header_str
            or re.search(r'\bff\b', header_str)):
        return "FF"
    # Abbreviated composite labels: "factor" + "exponent / exp_m" → FF summary table
    if "factor" in header_str and any(k in header_str for k in ["exponent", "exp_m"]):
        return "FF"
    if any(k in header_str for k in ["ri", "resistivity index", "sw", "rt", "ro"]) and "i" in header_str:
        return "RI"
    if any(k in header_str for k in ["s_hg", "mercury", "hg sat", "pc (psia)", "psia"]) and any(k in header_str for k in ["hg", "mercury", "saturation"]):
        return "MICP"
    if "krw" in header_str and "kro" in header_str:
        return "KR"
    if "rpm" in header_str and any(k in header_str for k in ["volume", "cc", "ml", "produced"]):
        return "CENTRIFUGE"
    if "pc" in header_str and "sw" in header_str:
        return "PC"
    if "porosity" in header_str and ("permeability" in header_str or " k " in header_str or "ka" in header_str):
        return "BCA"
    return "UNKNOWN"


def robust_extract_scal(filepath):
    result = {
        "filename": os.path.basename(filepath),
        "engine_used": None,
        "sheets": [],
        "errors": []
    }

    ext = Path(filepath).suffix.lower()
    engines_to_try = []
    if ext == ".xls":
        engines_to_try = ["xlrd"]
    elif ext == ".xlsx" or ext == ".xlsm":
        engines_to_try = ["openpyxl"]
    elif ext == ".xlsb":
        engines_to_try = ["pyxlsb"]
    elif ext in (".csv", ".tsv"):
        engines_to_try = ["csv"]
    else:
        engines_to_try = ["openpyxl", "xlrd", "pyxlsb"]

    xls_obj = None
    sheets_dict = None
    last_err = None
    for eng in engines_to_try:
        try:
            if eng == "csv":
                sep = "," if ext == ".csv" else "\t"
                df = pd.read_csv(filepath, header=None, sep=sep)
                sheets_dict = {"Sheet1": df}
                result["engine_used"] = "csv"
                break
            else:
                sheets_dict = pd.read_excel(filepath, sheet_name=None, header=None, engine=eng)
                result["engine_used"] = eng
                break
        except Exception as e:
            last_err = f"{eng}: {type(e).__name__}: {e}"
            result["errors"].append(last_err)
            continue

    if sheets_dict is None:
        result["errors"].append(f"All parsers failed for {filepath}")
        return result

    for sheet_name, df_raw in sheets_dict.items():
        sheet_info = {
            "name": sheet_name,
            "raw_shape": list(df_raw.shape),
            "metadata": {},
            "data_block": None,
            "track": "UNKNOWN",
            "notes": []
        }

        header_row, data_start, data_end = _detect_data_block(df_raw)
        if data_start is None:
            sheet_info["notes"].append("No numeric data block detected.")
            result["sheets"].append(sheet_info)
            continue

        sheet_info["metadata"] = _extract_metadata(df_raw, data_start)

        headers = (_merge_header_rows(df_raw, header_row, data_start)
                   if header_row >= 0
                   else [f"col_{i}" for i in range(df_raw.shape[1])])
        data_rows = df_raw.iloc[data_start:data_end+1].values.tolist()
        clean_rows = []
        for row in data_rows:
            clean_row = []
            for v in row:
                if pd.isna(v):
                    clean_row.append(None)
                elif isinstance(v, (int, float, np.integer, np.floating)):
                    clean_row.append(float(v))
                else:
                    clean_row.append(str(v))
            clean_rows.append(clean_row)

        sheet_info["data_block"] = {
            "header_row": int(header_row),
            "data_start": int(data_start),
            "data_end": int(data_end),
            "headers": [str(h) if pd.notna(h) else f"col_{i}" for i, h in enumerate(headers)],
            "n_rows": len(clean_rows),
            "rows": clean_rows,
        }
        sheet_info["track"] = _classify_track(headers, clean_rows)
        result["sheets"].append(sheet_info)

    return result


def _extract_pdf(file_bytes: bytes) -> str:
    """Extract all text from PDF for Gemini to analyze directly."""
    import pdfplumber
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


def _extract_docx(file_bytes: bytes) -> str:
    """Extract all text from Word document."""
    from docx import Document
    doc = Document(io.BytesIO(file_bytes))
    return "\n".join(para.text for para in doc.paragraphs if para.text.strip())


def extract_file_data(filepath):
    ext = Path(filepath).suffix.lower()

    if ext == '.pdf':
        try:
            with open(filepath, 'rb') as f:
                text = _extract_pdf(f.read())
            return {
                "data_type": "PDF", "sheet_names": [], "row_count": len(text),
                "extracted": {"raw_text": text}, "status": "success",
            }
        except Exception as e:
            return {
                "status": "parsing_failed", "data_type": "UNKNOWN",
                "sheet_names": [], "row_count": 0, "extracted": {}, "errors": [str(e)],
            }

    if ext in ('.docx', '.doc'):
        try:
            with open(filepath, 'rb') as f:
                text = _extract_docx(f.read())
            return {
                "data_type": "DOCX", "sheet_names": [], "row_count": len(text),
                "extracted": {"raw_text": text}, "status": "success",
            }
        except Exception as e:
            return {
                "status": "parsing_failed", "data_type": "UNKNOWN",
                "sheet_names": [], "row_count": 0, "extracted": {}, "errors": [str(e)],
            }

    try:
        handler = SCALFileHandler(filepath)
        result = handler.process()
        if result and result.get("row_count", 0) > 0:
            return result
    except Exception as e:
        pass

    robust_result = robust_extract_scal(filepath)
    if any(s.get("data_block") for s in robust_result["sheets"]):
        data_types = [s["track"] for s in robust_result["sheets"] if s.get("data_block") and s["track"] != "UNKNOWN"]
        dt = data_types[0] if data_types else "UNKNOWN"
        return {
            "data_type": dt,
            "sheet_names": [s["name"] for s in robust_result["sheets"]],
            "row_count": sum(s["data_block"]["n_rows"] for s in robust_result["sheets"] if s.get("data_block")),
            "extracted": robust_result,
            "status": "success"
        }
    return {
        "status": "parsing_failed",
        "data_type": "UNKNOWN",
        "sheet_names": [],
        "row_count": 0,
        "extracted": robust_result,
        "filename": robust_result["filename"],
        "engines_tried": [e.split(":")[0] for e in robust_result["errors"]],
        "errors": robust_result["errors"],
    }
