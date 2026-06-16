from pathlib import Path
import re
import json
import zipfile
import numpy as np


def _excel_engine(filepath):
    """Pick the pandas Excel engine by file CONTENT, not extension.

    Many core-lab exports are real .xlsx workbooks saved with a .xls name;
    xlrd 2.x rejects those (it only reads legacy OLE2 .xls). Sniff the magic
    bytes so both genuine .xls and mislabeled .xlsx ingest cleanly.
    """
    ext = Path(filepath).suffix.lower()
    if ext in (".xlsx", ".xlsm"):
        return "openpyxl"
    if ext == ".xlsb":
        return "pyxlsb"
    if ext == ".ods":
        return "odf"
    if ext == ".xls":
        try:
            if zipfile.is_zipfile(filepath):   # ZIP container => actually xlsx
                return "openpyxl"
        except Exception:
            pass
        return "xlrd"
    return "openpyxl"


def _read_excel(filepath):
    import pandas as pd
    ext = Path(filepath).suffix.lower()
    engine = _excel_engine(filepath)
    xl = pd.ExcelFile(filepath, engine=engine)
    result = {"type": "excel", "sheets": {}}

    for sheet_name in xl.sheet_names:
        try:
            df = pd.read_excel(xl, sheet_name=sheet_name, header=None, engine=engine)
            df = df.dropna(axis=0, how='all').dropna(axis=1, how='all').reset_index(drop=True)
            df.columns = range(df.shape[1])
        except Exception:
            continue

        labeled = {}
        columns = {}

        # Labeled key-value pairs
        vals_arr = df.values
        num_rows, num_cols = vals_arr.shape
        for i in range(num_rows):
            for j in range(num_cols):
                val = vals_arr[i, j]
                cell = str(val).strip() if pd.notna(val) else ""
                if cell in ("", "nan"):
                    continue
                is_label = cell.endswith(":") or any(kw in cell.lower() for kw in [
                    "well","sample","depth","company","length","diameter",
                    "porosity","permeability","pore vol","bulk vol","temperature",
                    "pressure","salinity","viscosity","density","weight",
                    "threshold","sor","swi","irr","residual","formation",
                    "date","job","analyst","cycle","name","id","no."
                ])
                if is_label:
                    for jj in range(j+1, min(j+6, num_cols)):
                        cand_val = vals_arr[i, jj]
                        cand = str(cand_val).strip() if pd.notna(cand_val) else ""
                        if cand not in ("", "nan"):
                            try:
                                labeled[cell] = round(float(cand), 6)
                            except ValueError:
                                labeled[cell] = cand
                            break

        # Numeric columns
        header_rows = []
        for i in range(num_rows):
            vals = [str(vals_arr[i, j]).strip() if pd.notna(vals_arr[i, j]) else "" for j in range(num_cols)]
            non_empty = [v for v in vals if v not in ("", "nan")]
            if len(non_empty) >= 2:
                num_count = sum(1 for v in non_empty if _is_number(v))
                if num_count <= len(non_empty) / 2:
                    header_rows.append(i)

        if header_rows:
            # Find the last consecutive block of header rows (closest to the data).
            # Many SCAL sheets use multi-row headers: row N has column names, row N+1
            # has sub-qualifiers, row N+2 has unit labels. Taking max() alone gives
            # only the unit row, collapsing every saturation column to "(%)".
            # We merge the whole block into compound names so each column is unique.
            sorted_hrs = sorted(set(header_rows))
            last_block = [sorted_hrs[-1]]
            for r in reversed(sorted_hrs[:-1]):
                if last_block[0] - r == 1:
                    last_block.insert(0, r)
                else:
                    break

            block_end = last_block[-1]

            # Build compound header per column: concatenate non-empty cells from
            # every row in the block, so "Sat. Hg" + "Pore Vol." + "(%)" becomes
            # "Sat. Hg Pore Vol. (%)" instead of just "(%)".
            headers = []
            for j in range(len(df.columns)):
                parts = []
                for row_idx in last_block:
                    cell = str(df.iloc[row_idx, j]).strip()
                    if cell not in ("", "nan"):
                        parts.append(cell)
                headers.append(" ".join(parts) if parts else "")

            # Deduplicate: columns that still collide after merging get a numeric suffix.
            seen: dict = {}
            unique_headers = []
            for h in headers:
                if h in ("", "nan"):
                    unique_headers.append(h)
                elif h in seen:
                    seen[h] += 1
                    unique_headers.append(f"{h}_{seen[h]}")
                else:
                    seen[h] = 1
                    unique_headers.append(h)
            headers = unique_headers

            col_data = {h: [] for h in headers if h not in ("", "nan")}
            for i in range(block_end + 1, len(df)):
                for j, h in enumerate(headers):
                    if h in ("", "nan") or j >= len(df.columns):
                        continue
                    try:
                        val_raw = df.iloc[i, j]
                        if pd.isna(val_raw):
                            col_data[h].append(None)
                        else:
                            v = float(val_raw)
                            if np.isnan(v):
                                col_data[h].append(None)
                            else:
                                col_data[h].append(round(v, 6))
                    except (ValueError, TypeError):
                        col_data[h].append(None)
            for h, vals in col_data.items():
                clean_vals = [v for v in vals if v is not None]
                if len(clean_vals) >= 2:
                    columns[h] = {
                        "count": len(vals),
                        "first": clean_vals[0],
                        "last": clean_vals[-1],
                        "min": round(min(clean_vals), 6),
                        "max": round(max(clean_vals), 6),
                        "values": vals
                    }

        raw_csv = df.head(500).to_csv(index=False, header=False)
        if not df.empty:
            result["sheets"][sheet_name] = {
                "labeled_values": labeled,
                "numeric_columns": columns,
                "raw_csv": raw_csv,
            }

    return result

def smart_read_csv(filepath: str, encodings: list = None, **kwargs):
    import pandas as pd
    import logging
    logger = logging.getLogger("HvielPipeline")
    if encodings is None:
        encodings = ["utf-8", "utf-8-sig", "latin1", "cp1252", "cp1256", "iso-8859-6", "utf-16"]
        
    for idx, encoding in enumerate(encodings):
        try:
            logger.info(f"Attempting CSV parsing using encoding scheme: {encoding}")
            df = pd.read_csv(filepath, encoding=encoding, **kwargs)
            logger.info(f"Successfully decoded and parsed CSV with {encoding}")
            return df
        except (UnicodeDecodeError, LookupError) as e:
            logger.warning(f"Encoding {encoding} failed to decode {filepath}. Error: {str(e)}")
            if idx == len(encodings) - 1:
                raise ValueError(
                    f"Failed to decode CSV file. File encoding is unsupported. "
                    f"Please save the data using standard UTF-8 or Latin1 format."
                ) from e

def _read_csv(filepath):
    import pandas as pd
    df = smart_read_csv(filepath)
    result = {"type": "csv", "columns": {}, "shape": df.shape}
    for col in df.columns:
        is_num = df[col].dtype in (float, int) or df[col].dropna().apply(_is_number).mean() > 0.8
        if is_num:
            vals = []
            for v in df[col]:
                if pd.isna(v):
                    vals.append(None)
                elif _is_number(str(v)):
                    vals.append(round(float(v), 6))
                else:
                    vals.append(None)
            clean_vals = [v for v in vals if v is not None]
            if clean_vals:
                result["columns"][col] = {
                    "count": len(vals),
                    "first": clean_vals[0],
                    "last": clean_vals[-1],
                    "min": round(min(clean_vals), 6),
                    "max": round(max(clean_vals), 6),
                    "values": vals,
                }
        else:
            result["columns"][col] = {
                "type": "text",
                "sample": df[col].dropna().head(5).tolist()
            }
    return result

def _read_pdf(filepath):
    _SAMPLE_ID_KEYWORDS = {"sample", "plug", "core", "id", "no.", "no", "#", "number"}

    def _format_pdf_table(table, table_idx):
        """Return a proper Markdown grid with outer pipes and a header separator."""
        if not table:
            return ""
        n_cols = max((len(row) for row in table), default=0)
        if n_cols == 0:
            return ""
        normalized = []
        for row in table:
            padded = list(row) + [None] * (n_cols - len(row))
            normalized.append(
                [str(c).replace("\n", " ").replace("\r", " ").strip() if c is not None else ""
                 for c in padded]
            )
        header = normalized[0] if normalized else []
        sample_id_cols = [
            (ci, cell)
            for ci, cell in enumerate(header)
            if any(kw in cell.lower() for kw in _SAMPLE_ID_KEYWORDS)
        ]
        lines = [f"[Table {table_idx + 1}]"]
        if sample_id_cols:
            col_desc = ", ".join(f'col {ci} = "{name}"' for ci, name in sample_id_cols)
            lines.append(
                f"[Sample Index: {col_desc} — verify this column before reading any row values]"
            )
        for ri, row in enumerate(normalized):
            lines.append("| " + " | ".join(row) + " |")
            if ri == 0:
                lines.append("| " + " | ".join(["---"] * n_cols) + " |")
        return "\n".join(lines)

    def _find_tables_strict(page):
        """Return pdfplumber Table objects sorted top-to-bottom, trying line geometry first."""
        for strategy in (
            {"vertical_strategy": "lines", "horizontal_strategy": "lines", "intersection_y_tolerance": 5, "snap_tolerance": 3},
            {"vertical_strategy": "text", "horizontal_strategy": "text", "snap_tolerance": 3, "join_tolerance": 3},
        ):
            try:
                found = page.find_tables(table_settings=strategy)
                if found:
                    return sorted(found, key=lambda t: t.bbox[1])
            except Exception:
                continue
        return []

    try:
        import pdfplumber
        text_pages = []
        with pdfplumber.open(filepath) as pdf:
            for i, page in enumerate(pdf.pages):
                parts = []
                found_tables = _find_tables_strict(page)

                if not found_tables:
                    # No tables: just emit the full page text
                    text = page.extract_text()
                    if text and text.strip():
                        parts.append(text.strip())
                else:
                    # Vertical slicing: interleave text zones and tables in reading order
                    last_y = 0
                    for ti, tbl_obj in enumerate(found_tables):
                        x0, top, x1, bottom = tbl_obj.bbox
                        # Text zone above this table
                        if top > last_y:
                            try:
                                zone = page.within_bbox((0, last_y, page.width, top))
                                zone_text = zone.extract_text()
                                if zone_text and zone_text.strip():
                                    parts.append(zone_text.strip())
                            except Exception:
                                pass
                        table_data = tbl_obj.extract()
                        if table_data:
                            parts.append(_format_pdf_table(table_data, ti))
                        last_y = bottom
                    # Text zone below the last table
                    if last_y < page.height:
                        try:
                            zone = page.within_bbox((0, last_y, page.width, page.height))
                            zone_text = zone.extract_text()
                            if zone_text and zone_text.strip():
                                parts.append(zone_text.strip())
                        except Exception:
                            pass

                if parts:
                    text_pages.append(f"[Page {i+1}]\n" + "\n\n".join(parts))
        return {"type": "pdf", "pages": len(text_pages), "text": "\n\n".join(text_pages)}
    except ImportError:
        try:
            import PyPDF2
            text_pages = []
            with open(filepath, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                for i, page in enumerate(reader.pages):
                    text = page.extract_text()
                    if text:
                        text_pages.append(f"[Page {i+1}]\n{text.strip()}")
            return {"type": "pdf", "pages": len(text_pages), "text": "\n\n".join(text_pages)}
        except ImportError:
            return {"type": "pdf", "error": "Install pdfplumber: pip install pdfplumber"}

def _read_docx(filepath, target_identifier=None):
    try:
        import docx
        from docx.oxml.ns import qn
        from docx.table import Table as DocxTable
        doc = docx.Document(filepath)
        _P   = qn("w:p")
        _TBL = qn("w:tbl")

        def _format_docx_table(tbl):
            """Convert a python-docx Table to clean markdown.
            
            Root-level fixes for complex DOCX tables:
            1. Multi-row headers → merged into single descriptive column names
            2. vMerge continuation → propagate parent cell text downward
            3. Empty first-row headers → detect real header row
            4. Full-width section rows → excluded from data
            5. Footnote markers (*, **) → stripped from values only, not headers
            """
            # ── Step 1: Build raw grid with vMerge and gridSpan tracking ──
            grid = {}
            v_merge_map = {}  # Track which cells are vMerge starts vs continuations
            
            for r_idx, tr in enumerate(tbl._tbl.tr_lst):
                c_idx = 0
                for tc in tr.tc_lst:
                    while (r_idx, c_idx) in grid:
                        c_idx += 1
                    
                    tcPr = tc.tcPr
                    grid_span = 1
                    v_merge = None
                    if tcPr is not None:
                        gridSpan_elem = tcPr.find(qn('w:gridSpan'))
                        if gridSpan_elem is not None:
                            val = gridSpan_elem.get(qn('w:val'))
                            if val:
                                grid_span = int(val)
                        
                        vMerge_elem = tcPr.find(qn('w:vMerge'))
                        if vMerge_elem is not None:
                            val = vMerge_elem.get(qn('w:val'))
                            v_merge = val if val else 'continue'
                    
                    # Always extract cell text (even for vMerge continuations)
                    text = "".join(
                        node.text for node in tc.iter(qn('w:t')) if node.text
                    ).replace("\n", " ").replace("\r", " ").strip()
                    
                    for i in range(grid_span):
                        cell_text = text if i == 0 else ""
                        grid[(r_idx, c_idx + i)] = cell_text
                        v_merge_map[(r_idx, c_idx + i)] = v_merge
                    
                    c_idx += grid_span
            
            if not grid:
                return ""
            
            max_r = max((r for r, c in grid.keys()), default=-1)
            max_c = max((c for r, c in grid.keys()), default=-1)
            
            if max_r < 0 or max_c < 0:
                return ""
            
            n_cols = max_c + 1
            
            # ── Step 2: Propagate vMerge parent text to continuation cells ──
            # When a cell has vMerge='continue' and is empty, copy from the
            # nearest vMerge='restart' cell above it in the same column.
            for c in range(n_cols):
                parent_text = ""
                for r in range(max_r + 1):
                    vm = v_merge_map.get((r, c))
                    if vm == 'restart' or (vm is None and grid.get((r, c), "")):
                        parent_text = grid.get((r, c), "")
                    elif vm == 'continue' and not grid.get((r, c), "").strip():
                        grid[(r, c)] = parent_text
            
            # ── Step 3: Detect how many rows are header rows ──
            # Header rows are rows where ANY cell has vMerge='restart' or
            # ALL cells match the vMerge pattern (start/continue).
            header_row_count = 0
            for r in range(min(max_r + 1, 5)):  # Check up to 5 rows
                has_vmerge = any(
                    v_merge_map.get((r, c)) in ('restart', 'continue')
                    for c in range(n_cols)
                )
                # Also detect empty-row-as-header: row 0 all empty, row 1 has content
                all_empty = all(not grid.get((r, c), "").strip() for c in range(n_cols))
                if has_vmerge or (r == 0 and all_empty and max_r > 1):
                    header_row_count = r + 1
                else:
                    break
            
            # Ensure at least 1 header row
            if header_row_count == 0:
                header_row_count = 1
            
            # ── Step 4: Merge multi-row headers into single descriptive names ──
            merged_headers = []
            for c in range(n_cols):
                parts = []
                for r in range(header_row_count):
                    cell_text = grid.get((r, c), "").strip()
                    if cell_text and cell_text not in parts:
                        parts.append(cell_text)
                merged = " - ".join(parts) if len(parts) > 1 else (parts[0] if parts else "")
                merged_headers.append(merged)
            
            # ── Step 5: Build data rows (skip headers and full-width separators) ──
            data_rows = []
            for r in range(header_row_count, max_r + 1):
                row_cells = [grid.get((r, c), "") for c in range(n_cols)]
                
                # Skip full-width separator/section rows: single non-empty cell
                # spanning the entire row (e.g., "Core # 2 (7685' – 7715') ft")
                non_empty_cells = [c for c in row_cells if c.strip()]
                if len(non_empty_cells) <= 1 and n_cols > 3:
                    # Check if the single cell text looks like a section title
                    single_text = non_empty_cells[0] if non_empty_cells else ""
                    if len(single_text) > 15 or not single_text:
                        continue  # Skip section separators and empty rows
                
                # Strip footnote asterisks from data values (not from headers)
                cleaned = []
                for cell in row_cells:
                    cleaned.append(cell.rstrip("*").strip() if cell else "")
                data_rows.append(cleaned)
            
            if not data_rows and not any(h.strip() for h in merged_headers):
                return ""
            
            # ── Step 6: Build markdown table ──
            md_lines = []
            # Header row
            md_lines.append("| " + " | ".join(merged_headers) + " |")
            md_lines.append("| " + " | ".join(["---"] * n_cols) + " |")
            # Data rows
            for row in data_rows:
                md_lines.append("| " + " | ".join(row) + " |")
            
            return "\n".join(md_lines)

        parts = []
        if target_identifier:
            if isinstance(target_identifier, str):
                targets = [target_identifier]
            elif isinstance(target_identifier, list):
                targets = target_identifier
            else:
                targets = []

            # Step 1: Collect all elements to allow proximity scanning
            elements = []
            for child in doc.element.body:
                if child.tag == _P:
                    text = "".join(node.text for node in child.iter(qn('w:t')) if node.text).strip()
                    if text:
                        elements.append(('P', text))
                elif child.tag == _TBL:
                    tbl = DocxTable(child, doc)
                    elements.append(('T', tbl))
            
            # Step 2: Find targets and grab associated elements (+/- 3 elements to catch both tables and geomechanics text)
            matched_indices = set()
            tbl_text_cache = {}
            for target in targets:
                target_lower = target.lower().replace('(', '').replace(')', '')
                for i, (etype, content) in enumerate(elements):
                    if etype == 'T':
                        if i not in tbl_text_cache:
                            tbl_text = ""
                            try:
                                for p_elem in content._element.iter(qn('w:t')):
                                    if p_elem.text:
                                        tbl_text += " " + p_elem.text
                            except Exception:
                                try:
                                    for row in content.rows:
                                        for cell in row.cells:
                                            tbl_text += " " + cell.text
                                except Exception:
                                    pass
                            tbl_text_cache[i] = tbl_text
                        tbl_text = tbl_text_cache[i]
                        clean_content = tbl_text.lower().replace('(', '').replace(')', '')
                    else:
                        clean_content = content.lower().replace('(', '').replace(')', '')
                        
                    if target_lower in clean_content:
                        # Include the matched element itself
                        matched_indices.add(i)
                        # Proximity scan: capture context +/- 5 elements (widened from ±3 to catch
                        # tables that may be separated from their heading by several paragraphs)
                        for j in range(max(0, i - 5), min(len(elements), i + 6)):
                            matched_indices.add(j)
            
            if not matched_indices:
                return {"type": "docx", "error": f"Target identifiers {targets} not found or no associated content."}
            
            for idx in sorted(matched_indices):
                etype, content = elements[idx]
                if etype == 'T':
                    formatted = _format_docx_table(content)
                    if formatted:
                        parts.append(formatted)
                else:
                    parts.append(content)
                
            return {"type": "docx", "content": "\n\n".join(parts)}
        else:
            for child in doc.element.body:
                if child.tag == _P:
                    text = "".join(node.text for node in child.iter(qn('w:t')) if node.text).strip()
                    if text:
                        parts.append(text)
                elif child.tag == _TBL:
                    tbl = DocxTable(child, doc)
                    formatted = _format_docx_table(tbl)
                    if formatted:
                        parts.append(formatted)
            return {"type": "docx", "content": "\n\n".join(parts)}
    except ImportError:
        return {"type": "docx", "error": "Install python-docx: pip install python-docx"}

def _read_txt(filepath):
    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()
    return {"type": "txt", "content": content}

def _read_image(filepath):
    import base64
    with open(filepath, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    ext = Path(filepath).suffix.lower().strip(".")
    mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg",
            "png": "image/png", "gif": "image/gif",
            "webp": "image/webp"}.get(ext, "image/png")
    return {"type": "image", "mime_type": mime, "base64": b64}

def _is_number(s):
    try:
        float(str(s).replace(",", ""))
        return True
    except (ValueError, TypeError):
        return False

_SAT_KEYWORDS = ("sat", " sw", "sw ", "s_w", "s_o", "s_g", "krw", "kro", "s_hg",
                 "hg frac", " hg", "hg ", "mercury", "wetting", "non-wetting",
                 "water sat", "oil sat")

def detect_and_normalize_column(col_name, values):
    """Detect units from the column name and normalize to engineering standard units.

    Rules:
      - Saturation column (name contains a saturation keyword) with max <= 1.0:
        fraction → multiply by 100 to get percent.
      - Saturation column with max <= 100: already percent, no conversion.
      - Pressure column whose name contains 'mpa': multiply by 145.038 to get psia.
      - All other columns: returned unchanged.

    Returns:
        (normalized_values, note) — note is an empty string when no conversion was applied.
    """
    if not values:
        return values, ""
    col_lower = col_name.lower()
    
    clean_vals = [v for v in values if v is not None]
    if not clean_vals:
        return values, ""
        
    max_val = max(abs(v) for v in clean_vals)

    is_sat = any(kw in col_lower for kw in _SAT_KEYWORDS)
    if is_sat and max_val <= 1.0:
        return [round(v * 100.0, 6) if v is not None else None for v in values], "[fraction->% x100]"

    if "mpa" in col_lower:
        return [round(v * 145.038, 4) if v is not None else None for v in values], "[MPa->psia x145.038]"

    return values, ""

_MAX_ARRAY_DISPLAY = 60  # truncate column arrays longer than this in prompt output

def _format_column_array(col_name, info):
    """Return a single prompt line for one numeric column.

    Applies unit normalization (RC2) and always binds values to the column name
    so the AI can never confuse columns by position (RC1).

    Both 'max' (true maximum across all rows) and 'last' (final measured state)
    are emitted as distinct labeled fields so the AI cannot substitute one for
    the other (RC4).

    Format:
        Column "<name>" [<unit note>] (n=N, min=A, max=B [maximum], last=C [final state]): [v1, ...]
    """
    vals = info.get("values", [])
    norm_vals, note = detect_and_normalize_column(col_name, vals)
    unit_tag = f" {note}" if note else ""

    if norm_vals:
        clean_norm = [v for v in norm_vals if v is not None]
        n_min  = round(min(clean_norm), 6) if clean_norm else 0.0
        n_max  = round(max(clean_norm), 6) if clean_norm else 0.0
        n_last = round(clean_norm[-1], 6) if clean_norm else 0.0
        display = norm_vals[:_MAX_ARRAY_DISPLAY]
        arr_str = "[" + ", ".join(str(v) if v is not None else "None" for v in display)
        if len(norm_vals) > _MAX_ARRAY_DISPLAY:
            arr_str += f", ...+{len(norm_vals) - _MAX_ARRAY_DISPLAY} more"
        arr_str += "]"
        return (f'    Column "{col_name}"{unit_tag}'
                f" (n={info['count']}, min={n_min},"
                f" max={n_max} [maximum], last={n_last} [final state]): {arr_str}")
    else:
        # No values stored — fall back to stored summary stats, still label both
        n_max  = info.get('max', 0.0)
        n_last = info.get('last', 0.0)
        n_min  = info.get('min', 0.0)
        return (f'    Column "{col_name}"{unit_tag}'
                f" (n={info.get('count', 0)}, min={n_min},"
                f" max={n_max} [maximum], last={n_last} [final state]): [no values]")


# ──────────────────────────────────────────────────────────────────────────────
# GENERIC SCAL EXTRACTION — 3-LAYER DETECTION SYSTEM
# ──────────────────────────────────────────────────────────────────────────────

# Layer 1: test-type keyword rules — checked in order, first match wins.
# Keywords are matched against the combined lowercase string of:
#   filename + sheet names + all column/label names in the file.
_TEST_TYPE_RULES = [
    ("MICP", [
        "mercury", "micp", "s_hg", "hg sat", "hg injection",
        "mercury injection", "capillary pressure hg",
    ]),
    ("KW_THROUGHPUT", [
        "throughput", "kw vs", "kw_vs", "formation damage",
        "sensitivity test", "cum.pv.inj", "fluid sensitivity",
        "kw throughput",
    ]),
    ("IMBIBITION", [
        "imbibition", "centrifuge", "w-o", "capillary pressure",
        "porous plate",
    ]),
    ("REL_PERM", [
        "relative perm", "kr data", " kro ", " krw ",
        "rel perm", "relative permeability",
    ]),
]

# Layer 2: semantic column aliases per test type.
# Each key is the canonical field name; the list is all known column-name variants.
_COLUMN_ALIASES = {
    "KW_THROUGHPUT": {
        "permeability": [
            "KL", "Kw", "K liquid", "Permeability", "Perm",
            "KL (mD)", "k_l", "liquid perm", "liquid permeability",
        ],
        "throughput": [
            "Cum.Pv.inj", "Cum. Pv. inj", "PV injected",
            "Throughput", "Cum PV", "cumulative pv",
            "pv inj", "pore volumes injected",
        ],
    },
    "IMBIBITION": {
        "sor_lab": [
            "Sor Lab", "Sor_Lab", "Sor Lab.", "Residual Oil Sat",
            "Sor(lab)", "Sor (lab)", "Sor Lab Frac", "Sor_laboratory",
        ],
        "sor_tc": [
            "Sor T.C.", "Sor_TC", "Sor T.C", "Sor corrected",
            "Sor(tc)", "Sor T.C ", "true closure", "sor tc",
        ],
        "capillary_pc": [
            "Pc", "Capillary Pressure", "signed Pc", "Cap Pressure",
            "Pc (psi)", "Pc (psia)", "Capillary", "cap. pressure",
            "capillary pressure (psi)",
        ],
        "liquid_sat": [
            "Liquid Sat", "Liquid Saturation", "Sw",
            "Water Sat", "Saturation", "Liquid Sat.", "liquid",
        ],
    },
    "MICP": {
        "threshold_pressure": [
            "Threshold Pressure", "Entry Pressure", "Pd",
            "threshold", "Pt", "Threshold P",
            "threshold pressure (psi)", "entry pressure (psia)",
        ],
        "hg_saturation": [
            "Hg Sat", "Mercury Sat", "SHg", "S_Hg",
            "Hg Saturation", "%Hg", "Sat. Hg", "Hg sat (%)",
            "S Hg", "Hg%", "hg pore vol", "sat hg",
            "cumulative hg", "hg saturation",
        ],
        "capillary_pressure": [
            "Pc", "Capillary Pressure", "Pressure (psia)",
            "Pc (psia)", "Cap. Pressure", "Pressure psia",
            "injection pressure",
        ],
    },
    "REL_PERM": {
        "sw":  ["Sw", "Water Sat", "Sw%", "Sw (fraction)", "Sw (%)"],
        "kro": ["Kro", "Kro/Kro_max", "Oil Kr", "K_ro", "kro"],
        "krw": ["Krw", "Krw/Krw_max", "Water Kr", "K_rw", "krw"],
    },
}

# Sheet names containing these keywords are aggregate/summary sheets — skip them
# when building per-sample results.
_SUMMARY_SHEET_KW = frozenset([
    "all data", "alldata", "all sheet", "all_data",
    "summary", "combined", "composite", "total",
    "overview", "aggregate", "report", "master",
])


def _is_summary_sheet(name: str) -> bool:
    n = name.lower().strip()
    return any(kw in n for kw in _SUMMARY_SHEET_KW)


def _clean(s: str) -> str:
    """Collapse whitespace, punctuation, and special chars for fuzzy comparison."""
    return re.sub(r'[\s\-_\.\(\)/\\%]+', '', str(s).lower())


def _fuzzy_match(col_name: str, aliases: list) -> bool:
    """Return True if col_name matches any alias (case-insensitive, partial substring)."""
    col_c = _clean(col_name)
    for alias in aliases:
        a_c = _clean(alias)
        if col_c == a_c or (a_c and a_c in col_c) or (col_c and col_c in a_c):
            return True
    return False


def _detect_test_type(filename: str, sheet_names: list, all_text: str) -> str:
    """Layer 1: detect SCAL test type from filename, sheet names, and header text."""
    combined = (filename + " " + " ".join(sheet_names) + " " + all_text).lower()
    for ttype, keywords in _TEST_TYPE_RULES:
        if any(k in combined for k in keywords):
            return ttype
    return "UNKNOWN"


def _extract_well(filename: str) -> str:
    """Extract well ID from filename (e.g. 'T1-31', 'CE03-41', 'Well_A12')."""
    stem = Path(filename).stem
    m = re.search(r'(?:well[_\s\-]*)?([A-Z]{1,3}[-_]?\d{1,5}(?:[-_]\d{1,3})?)',
                  stem, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    return ""


def _find_col(col_dict: dict, aliases: list):
    """Return (col_name, col_info_dict) for the first column matching any alias, or None."""
    for col_name, info in col_dict.items():
        if _fuzzy_match(col_name, aliases):
            return col_name, info
    return None


def _find_labeled(labeled: dict, aliases: list):
    """Return the float value from labeled_values whose key matches any alias, or None."""
    for label, val in labeled.items():
        if _fuzzy_match(label, aliases):
            try:
                return round(float(val), 6)
            except (TypeError, ValueError):
                pass
    return None


def _scal_extract_sheet(sheet_data: dict, sample_id: str,
                         test_type: str, warnings: list) -> dict:
    """
    Layer 3: extract per-sample values from one sheet's already-parsed data.

    Inputs come from _read_excel() output — no re-reading of the file needed.
    """
    col_dict = sheet_data.get("numeric_columns", {})
    labeled  = sheet_data.get("labeled_values",  {})
    result   = {}

    # ── KW_THROUGHPUT: initial/final KL, % change ──────────────────────────
    if test_type == "KW_THROUGHPUT":
        aliases = _COLUMN_ALIASES["KW_THROUGHPUT"]
        perm    = _find_col(col_dict, aliases["permeability"])
        thru    = _find_col(col_dict, aliases["throughput"])

        if perm is None:
            warnings.append(
                f"{sample_id}: permeability column not found "
                f"(available: {list(col_dict.keys())})"
            )
            return {}

        info    = perm[1]
        initial = info["first"]
        final   = info["last"]
        pct_chg = round((final - initial) / initial * 100, 2) if initial != 0 else None

        result["initial_KL"]    = {"value": initial,  "unit": "mD", "method": "first"}
        result["final_KL"]      = {"value": final,    "unit": "mD", "method": "last"}
        result["KL_change_pct"] = {"value": pct_chg,  "unit": "%",  "method": "derived"}
        result["KL_series"]     = {"values": info.get("values", []), "unit": "mD",
                                    "method": "series"}
        if thru:
            result["throughput_series"] = {
                "values": thru[1].get("values", []), "unit": "PV", "method": "series"
            }

    # ── IMBIBITION: Sor Lab, Sor TC, signed Pc series ──────────────────────
    elif test_type == "IMBIBITION":
        aliases = _COLUMN_ALIASES["IMBIBITION"]

        # Sor values come from labeled cells (_read_excel already extracted them)
        sor_lab = _find_labeled(labeled, aliases["sor_lab"])
        sor_tc  = _find_labeled(labeled, aliases["sor_tc"])

        if sor_lab is not None:
            # RC2: normalise fraction→%
            if sor_lab < 1.1:
                sor_lab = round(sor_lab * 100, 4)
            result["Sor_Lab"] = {"value": sor_lab, "unit": "fraction", "method": "labeled"}

        if sor_tc is not None:
            if sor_tc < 1.1:
                sor_tc = round(sor_tc * 100, 4)
            result["Sor_TC"] = {"value": sor_tc, "unit": "fraction", "method": "labeled"}

        # Pc series — negative values are CORRECT imbibition physics
        pc_match = _find_col(col_dict, aliases["capillary_pc"])
        if pc_match:
            result["Pc_series"] = {
                "values": pc_match[1].get("values", []),
                "unit":   "psi",
                "method": "series",
                "note":   "negative values are correct imbibition physics",
            }

        sat_match = _find_col(col_dict, aliases["liquid_sat"])
        if sat_match:
            result["liquid_sat_series"] = {
                "values": sat_match[1].get("values", []),
                "unit":   "fraction",
                "method": "series",
            }

        if not result:
            warnings.append(f"{sample_id}: no imbibition data extracted")

    # ── MICP: threshold pressure (labeled cell), max Hg sat (column max) ───
    elif test_type == "MICP":
        aliases = _COLUMN_ALIASES["MICP"]

        # Threshold pressure: ALWAYS from labeled cell — never column max (RC3)
        thresh = _find_labeled(labeled, aliases["threshold_pressure"])
        if thresh is not None:
            result["threshold_pressure"] = {"value": thresh, "unit": "psia",
                                             "method": "labeled"}
        else:
            warnings.append(f"{sample_id}: threshold pressure labeled cell not found")

        # Max Hg Sat: column MAXIMUM, not last row (RC4)
        hg_match = _find_col(col_dict, aliases["hg_saturation"])
        if hg_match:
            hg_info = hg_match[1]
            hg_vals = hg_info.get("values", [])
            if hg_vals:
                raw_max = hg_info["max"]
                # RC2: normalise fraction→%
                if raw_max <= 1.0:
                    hg_vals = [round(v * 100, 4) for v in hg_vals]
                    raw_max = round(raw_max * 100, 4)
                result["max_hg_sat"] = {"value": raw_max, "unit": "%", "method": "max"}
                result["hg_sat_series"] = {"values": hg_vals, "unit": "%",
                                            "method": "series"}
        else:
            warnings.append(f"{sample_id}: Hg saturation column not found")

        pc_match = _find_col(col_dict, aliases["capillary_pressure"])
        if pc_match:
            result["Pc_series"] = {
                "values": pc_match[1].get("values", []),
                "unit":   "psia",
                "method": "series",
            }

    # ── REL_PERM: Sw, Kro, Krw series ──────────────────────────────────────
    elif test_type == "REL_PERM":
        aliases = _COLUMN_ALIASES["REL_PERM"]
        for field, field_aliases in aliases.items():
            match = _find_col(col_dict, field_aliases)
            if match:
                vals = match[1].get("values", [])
                unit = "fraction"
                if field == "sw" and vals and max(vals) > 1.0:
                    vals = [round(v / 100.0, 6) for v in vals]
                    unit = "fraction (normalised from %)"
                result[field] = {"values": vals, "unit": unit, "method": "series"}

    return result


def _extract_scal_structured(xl_data: dict, filename: str) -> dict:
    """
    Run the 3-layer generic SCAL extraction on already-parsed Excel data.

    Called by read_file() for Excel/XLS files.  Works entirely from the
    _read_excel() output — no second file read.

    Returns the structured dict from STEP 5 of the spec:
        {file_name, test_type, well, samples, results, raw_columns,
         requires_review, warnings}
    """
    sheets      = xl_data.get("sheets", {})
    sheet_names = list(sheets.keys())
    warnings    = []

    # Gather all column/label names for type detection
    all_text = " ".join(
        " ".join(str(k) for k in sd.get("labeled_values",  {}).keys())
        + " "
        + " ".join(str(k) for k in sd.get("numeric_columns", {}).keys())
        for sd in sheets.values()
    )

    test_type = _detect_test_type(filename, sheet_names, all_text)
    well      = _extract_well(filename)

    # UNKNOWN fallback: return all numeric columns as raw data
    if test_type == "UNKNOWN":
        raw_cols: dict = {}
        for sname, sdata in sheets.items():
            for col, info in sdata.get("numeric_columns", {}).items():
                raw_cols[f"{sname}/{col}"] = info.get("values", [])
        return {
            "file_name":       filename,
            "test_type":       "UNKNOWN",
            "well":            well,
            "samples":         [],
            "results":         {},
            "raw_columns":     raw_cols,
            "requires_review": True,
            "warnings": [
                "File type not recognized. "
                "Raw columns returned for manual review."
            ],
        }

    results: dict = {}
    samples: list = []

    for sheet_name, sheet_data in sheets.items():
        if _is_summary_sheet(sheet_name):
            continue
        # Accept sheets that have numeric columns OR labeled values.
        # Imbibition samples sometimes carry Sor_Lab/Sor_TC in labeled cells only
        # (no numeric column arrays), so requiring numeric_columns would silently
        # drop those samples.
        if not (sheet_data.get("numeric_columns") or sheet_data.get("labeled_values")):
            continue

        sample_id = sheet_name          # sheet name = sample ID for multi-sheet SCAL files
        samples.append(sample_id)

        extracted = _scal_extract_sheet(sheet_data, sample_id, test_type, warnings)
        if extracted:
            results[sample_id] = extracted

    return {
        "file_name":       filename,
        "test_type":       test_type,
        "well":            well,
        "samples":         samples,
        "results":         results,
        "raw_columns":     {},
        "requires_review": bool(not results and warnings),
        "warnings":        warnings,
    }


def _format_scal_for_prompt(scal: dict) -> str:
    """
    Format the structured SCAL extraction as a prompt text block.
    Injected by to_prompt_string() so Gemini can populate table rows directly.
    """
    if not scal:
        return ""

    test_type = scal.get("test_type", "UNKNOWN")
    well      = scal.get("well", "")
    samples   = scal.get("samples", [])
    results   = scal.get("results", {})
    warnings  = scal.get("warnings", [])
    raw_cols  = scal.get("raw_columns", {})

    lines = ["\n[SCAL STRUCTURED EXTRACTION — use these values directly for table rows]"]
    lines.append(f"Test Type: {test_type}")
    if well:
        lines.append(f"Well: {well}")
    lines.append(f"Samples ({len(samples)}): {', '.join(samples) if samples else 'none detected'}")

    for sample_id, res in results.items():
        lines.append(f"\n--- Sample {sample_id} ---")
        for field, info in res.items():
            if not isinstance(info, dict):
                continue
            if "value" in info:
                v    = info["value"]
                unit = info.get("unit", "")
                meth = info.get("method", "")
                lines.append(f"  {field}: {v} {unit} [{meth}]")
            elif "values" in info:
                vals = info["values"]
                unit = info.get("unit", "")
                note = info.get("note", "")
                note_str = f"  NOTE: {note}" if note else ""
                n    = len(vals)
                frst = vals[0]  if vals else "n/a"
                lst  = vals[-1] if vals else "n/a"
                mx   = max(v for v in vals if v is not None) if vals else "n/a"
                mn   = min(v for v in vals if v is not None) if vals else "n/a"
                lines.append(
                    f"  {field} [{unit}]: n={n}, min={mn}, max={mx} [maximum],"
                    f" first={frst}, last={lst} [final state]"
                    + (f" — {note}" if note else "")
                )

    if warnings:
        lines.append("\nWarnings:")
        for w in warnings:
            lines.append(f"  • {w}")

    # UNKNOWN fallback: show raw column summary
    if scal.get("requires_review") and raw_cols:
        lines.append("\n[RAW COLUMNS — type unrecognized, for manual review]")
        for col, vals in raw_cols.items():
            if vals:
                clean_vals = [v for v in vals if v is not None]
                if clean_vals:
                    lines.append(
                        f"  {col}: n={len(vals)},"
                        f" min={min(clean_vals):.4g}, max={max(clean_vals):.4g}"
                    )
                else:
                    lines.append(
                        f"  {col}: n={len(vals)} (all null)"
                    )

    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# MAIN ENTRY POINTS (public API — signatures unchanged)
# ──────────────────────────────────────────────────────────────────────────────

def _df_columns_stats(df):
    """Summarize a DataFrame into the same column dict shape _read_csv produces:
    numeric columns -> {count,first,last,min,max,values}; text columns -> {type,sample}.
    Strings that look numeric are coerced (tolerating thousands separators)."""
    import pandas as pd
    cols = {}
    for col in df.columns:
        series = df[col]
        coerced = pd.to_numeric(
            series.astype(str).str.replace(",", "", regex=False).str.strip(),
            errors="coerce",
        )
        frac_num = float(coerced.notna().mean()) if len(coerced) else 0.0
        if frac_num > 0.6:
            vals = [None if pd.isna(x) else round(float(x), 6) for x in coerced]
            clean = [v for v in vals if v is not None]
            if clean:
                cols[str(col)] = {
                    "count": len(vals), "first": clean[0], "last": clean[-1],
                    "min": round(min(clean), 6), "max": round(max(clean), 6),
                    "values": vals,
                }
        else:
            cols[str(col)] = {
                "type": "text",
                "sample": series.dropna().astype(str).head(5).tolist(),
            }
    return cols


def _read_xml(filepath):
    """Parse PRC_Reservoir_Model / Petrel-KAPPA style XML exports.

    The petrophysical data is carried in a CDATA payload (markdown tables,
    CSV, or whitespace-delimited text), not as XML row/column elements — so we
    parse the envelope with ElementTree, pull the text, and route it through the
    existing tabular parsers. Returns an 'excel'-shaped dict (one sheet per
    markdown table), a 'csv'-shaped dict (single table), or 'txt' as a fallback,
    so to_prompt_string() and the SCAL extractor consume it unchanged.
    """
    import xml.etree.ElementTree as ET
    import io
    import pandas as pd

    try:
        root = ET.parse(filepath).getroot()
    except Exception as e:
        return {"error": f"XML parse failed: {e}"}

    well = ""
    well_el = root.find(".//Well")
    if well_el is not None:
        well = (well_el.get("name") or (well_el.text or "")).strip()

    # The measurement payload lives in <TabularData>; prefer it so Header/title
    # prose (e.g. "Petrel / KAPPA Compatible") never contaminates the table header.
    td = root.find(".//TabularData")
    if td is not None and td.text and td.text.strip():
        cdata = td.text.strip()
    else:
        payloads = [el.text.strip() for el in root.iter()
                    if el.text and len(el.text.strip()) > 20]
        cdata = "\n\n".join(payloads).strip()
    if not cdata:
        cdata = ET.tostring(root, encoding="unicode")

    # 1) Markdown pipe tables
    blocks, cur = [], []
    for ln in cdata.splitlines():
        if ln.lstrip().startswith("|"):
            cur.append(ln)
        elif cur:
            blocks.append(cur); cur = []
    if cur:
        blocks.append(cur)

    sheets = {}
    for block in blocks:
        rows = []
        for ln in block:
            cells = [c.strip() for c in ln.strip().strip("|").split("|")]
            if cells and set("".join(cells)) <= set("-: "):
                continue  # markdown separator row
            rows.append(cells)
        if len(rows) < 2:
            continue
        width = max(len(r) for r in rows)
        rows = [r + [""] * (width - len(r)) for r in rows]
        df = pd.DataFrame(rows[1:], columns=rows[0])
        sheets[f"Table_{len(sheets) + 1}"] = {
            "labeled_values": {},
            "numeric_columns": _df_columns_stats(df),
            "raw_csv": df.to_csv(index=False),
        }
    if sheets:
        return {"type": "excel", "sheets": sheets,
                "source_format": "petrel_xml", "well": well}

    # 2) Whitespace- or comma-delimited single table
    for sep in (r"\s+", ","):
        try:
            df = pd.read_csv(io.StringIO(cdata), sep=sep, engine="python",
                             na_values=["N/A", "NaN", "na", "-", ""], comment="#")
            if df.shape[1] >= 2 and df.shape[0] >= 1:
                return {"type": "csv", "columns": _df_columns_stats(df),
                        "shape": df.shape, "source_format": "petrel_xml", "well": well}
        except Exception:
            continue

    # 3) Fallback: hand the raw payload to the model as text
    return {"type": "txt", "content": cdata, "source_format": "petrel_xml"}


def read_file(filepath, target_identifier=None):
    if not Path(filepath).exists():
        return {"error": f"File not found: {filepath}"}
    ext = Path(filepath).suffix.lower()
    readers = {
        ".xlsx": _read_excel,
        ".xls":  _read_excel,
        ".xml":  _read_xml,
        ".csv":  _read_csv,
        ".pdf":  _read_pdf,
        ".docx": lambda fp: _read_docx(fp, target_identifier),
        ".doc":  lambda fp: _read_docx(fp, target_identifier),
        ".txt":  _read_txt,
        ".png":  _read_image,
        ".jpg":  _read_image,
        ".jpeg": _read_image,
        ".gif":  _read_image,
        ".webp": _read_image,
    }
    reader = readers.get(ext)
    if not reader:
        return {"error": f"Unsupported file type: {ext}"}
    try:
        data = reader(filepath)
        data["filename"] = Path(filepath).name
        # Add structured SCAL extraction for Excel files
        if data.get("type") == "excel":
            try:
                data["scal"] = _extract_scal_structured(data, data["filename"])
            except Exception as _se:
                data["scal"] = {
                    "file_name": data["filename"], "test_type": "UNKNOWN",
                    "well": "", "samples": [], "results": {}, "raw_columns": {},
                    "requires_review": True,
                    "warnings": [f"Structured extraction error: {_se}"],
                }
        return data
    except Exception as e:
        return {"error": str(e), "filename": Path(filepath).name}


def _build_markdown_table(columns_dict, max_rows=500):
    # Filter columns that have "values"
    valid_cols = {}
    for col, info in columns_dict.items():
        if "values" in info:
            vals = info["values"]
            norm_vals, note = detect_and_normalize_column(col, vals)
            col_name_with_unit = col
            if note:
                col_name_with_unit += f" {note}"
            valid_cols[col_name_with_unit] = norm_vals

    if not valid_cols:
        return ""

    headers = list(valid_cols.keys())
    num_rows = max(len(vals) for vals in valid_cols.values())

    markdown_lines = []
    markdown_lines.append("| " + " | ".join(headers) + " |")
    markdown_lines.append("| " + " | ".join(["---"] * len(headers)) + " |")

    if num_rows <= max_rows:
        for i in range(num_rows):
            row_vals = []
            for col in headers:
                vals = valid_cols[col]
                val = vals[i] if i < len(vals) else None
                row_vals.append(str(val) if val is not None else "")
            markdown_lines.append("| " + " | ".join(row_vals) + " |")
    else:
        half = max_rows // 2
        # First half
        for i in range(half):
            row_vals = []
            for col in headers:
                vals = valid_cols[col]
                val = vals[i] if i < len(vals) else None
                row_vals.append(str(val) if val is not None else "")
            markdown_lines.append("| " + " | ".join(row_vals) + " |")

        # Ellipsis row indicating how many rows were hidden
        hidden_count = num_rows - max_rows
        ellipsis_row = ["..."] * len(headers)
        ellipsis_row[0] = f"... [{hidden_count} rows hidden] ..."
        markdown_lines.append("| " + " | ".join(ellipsis_row) + " |")

        # Last half
        for i in range(num_rows - half, num_rows):
            row_vals = []
            for col in headers:
                vals = valid_cols[col]
                val = vals[i] if i < len(vals) else None
                row_vals.append(str(val) if val is not None else "")
            markdown_lines.append("| " + " | ".join(row_vals) + " |")

    return "\n".join(markdown_lines)


def to_prompt_string(data):
    t = data.get("type", "unknown")
    if "error" in data:
        return f"[File error: {data['error']}]", None
    if t == "image":
        return f"[Image file: {data.get('filename')}]", {
            "mime_type": data["mime_type"],
            "base64": data["base64"]
        }
    lines = [f"FILE: {data.get('filename', 'unknown')} ({t.upper()})"]
    if t == "excel":
        for sheet, content in data.get("sheets", {}).items():
            lines.append(f"\n--- Sheet: {sheet} ---")

            labeled = content.get("labeled_values", {})
            if labeled:
                lines.append("  [FINAL LAB RESULTS — labeled_values]"
                             " Report these values directly. Do NOT derive them from array first/last.")
                for k, v in labeled.items():
                    lines.append(f"    {k} = {v}")

            columns = content.get("numeric_columns", {})
            if columns:
                lines.append("  [TABULAR DATA GRID]")
                lines.append(_build_markdown_table(columns))
                lines.append("\n  [COLUMN ARRAYS — numeric_columns]"
                             " Use for fitting/plotting only."
                             " Match by column name, never by position."
                             " Never report the first or last value of these as a final result.")
                for col, info in columns.items():
                    lines.append(_format_column_array(col, info))

            raw_csv = content.get("raw_csv", "")
            if raw_csv:
                lines.append("  [RAW CSV DATA FALLBACK]")
                lines.append(raw_csv)

        # Structured SCAL extraction — provides explicit per-sample scalars
        # so Gemini can populate table rows without re-deriving from arrays
        scal = data.get("scal")
        if scal and scal.get("test_type") != "UNKNOWN" and scal.get("results"):
            lines.append(_format_scal_for_prompt(scal))
        elif scal and scal.get("requires_review"):
            lines.append(_format_scal_for_prompt(scal))

    elif t == "csv":
        lines.append(f"Shape: {data['shape'][0]} rows x {data['shape'][1]} cols")
        columns = data.get("columns", {})
        if columns:
            lines.append("  [TABULAR DATA GRID]")
            lines.append(_build_markdown_table(columns))
            lines.append("\n  [COLUMN ARRAYS] Match by column name, never by position.")
            for col, info in columns.items():
                if info.get("type") == "text":
                    lines.append(f'    Column "{col}" (text): sample={info["sample"]}')
                else:
                    lines.append(_format_column_array(col, info))

    elif t == "pdf":
        lines.append(f"Pages: {data.get('pages', '?')}")
        lines.append(data.get("text", ""))
    elif t == "docx":
        if "content" in data:
            # New sequential format: paragraphs and tables interleaved in document order
            lines.append(data["content"])
        else:
            # Legacy format: separate paragraphs and tables lists
            for p in data.get("paragraphs", []):
                lines.append(p)
            for table in data.get("tables", []):
                lines.append("\n[Table]")
                for row in table:
                    lines.append("  " + " | ".join(row))
    elif t == "txt":
        lines.append(data.get("content", ""))
    return "\n".join(lines), None

def build_gemini_message(user_message, filepath=None):
    if not filepath:
        return user_message, None
    data = read_file(filepath)
    text_context, image_part = to_prompt_string(data)
    if image_part:
        return user_message, image_part
    full_prompt = f"{text_context}\n\n{user_message}"
    return full_prompt, None
