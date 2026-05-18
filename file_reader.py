import os
import json
import numpy as np

def _read_excel(filepath):
    import pandas as pd
    ext = os.path.splitext(filepath)[1].lower()
    engine = "xlrd" if ext == ".xls" else "openpyxl"
    xl = pd.ExcelFile(filepath, engine=engine)
    result = {"type": "excel", "sheets": {}}

    for sheet_name in xl.sheet_names:
        try:
            df = pd.read_excel(xl, sheet_name=sheet_name, header=None)
        except Exception:
            continue

        labeled = {}
        columns = {}

        # Labeled key-value pairs
        for i, row in df.iterrows():
            for j, val in enumerate(row):
                cell = str(val).strip()
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
                    for jj in range(j+1, min(j+6, len(row))):
                        cand = str(df.iloc[i, jj]).strip()
                        if cand not in ("", "nan"):
                            try:
                                labeled[cell] = round(float(cand), 6)
                            except ValueError:
                                labeled[cell] = cand
                            break

        # Numeric columns
        header_rows = []
        for i, row in df.iterrows():
            vals = [str(v).strip() for v in row]
            non_empty = [v for v in vals if v not in ("", "nan")]
            if len(non_empty) >= 2:
                num_count = sum(1 for v in non_empty if _is_number(v))
                if num_count <= len(non_empty) / 2:
                    header_rows.append(i)

        if header_rows:
            hr = max(header_rows)
            headers = [str(df.iloc[hr, j]).strip() for j in range(len(df.columns))]
            col_data = {h: [] for h in headers if h not in ("", "nan")}
            for i in range(hr+1, len(df)):
                for j, h in enumerate(headers):
                    if h in ("", "nan") or j >= len(df.columns):
                        continue
                    try:
                        v = float(df.iloc[i, j])
                        if not np.isnan(v):
                            col_data[h].append(round(v, 6))
                    except (ValueError, TypeError):
                        pass
            for h, vals in col_data.items():
                if len(vals) >= 2:
                    columns[h] = {
                        "count": len(vals), "first": vals[0], "last": vals[-1],
                        "min": round(min(vals), 6), "max": round(max(vals), 6),
                        "values": vals
                    }

        if labeled or columns:
            result["sheets"][sheet_name] = {
                "labeled_values": labeled,
                "numeric_columns": columns
            }

    return result

def _read_csv(filepath):
    import pandas as pd
    df = pd.read_csv(filepath)
    result = {"type": "csv", "columns": {}, "shape": df.shape}
    for col in df.columns:
        if df[col].dtype in (float, int) or df[col].apply(_is_number).mean() > 0.8:
            vals = [round(float(v), 6) for v in df[col].dropna() if _is_number(str(v))]
            if vals:
                result["columns"][col] = {
                    "count": len(vals), "first": vals[0], "last": vals[-1],
                    "min": round(min(vals), 6), "max": round(max(vals), 6)
                }
        else:
            result["columns"][col] = {
                "type": "text",
                "sample": df[col].dropna().head(5).tolist()
            }
    return result

def _read_pdf(filepath):
    try:
        import pdfplumber
        text_pages = []
        with pdfplumber.open(filepath) as pdf:
            for i, page in enumerate(pdf.pages):
                text = page.extract_text()
                if text:
                    text_pages.append(f"[Page {i+1}]\n{text.strip()}")
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

def _read_docx(filepath):
    try:
        import docx
        doc = docx.Document(filepath)
        paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
        tables = []
        for t in doc.tables:
            rows = []
            for row in t.rows:
                rows.append([cell.text.strip() for cell in row.cells])
            tables.append(rows)
        return {"type": "docx", "paragraphs": paragraphs, "tables": tables}
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
    ext = os.path.splitext(filepath)[1].lower().strip(".")
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

def read_file(filepath):
    if not os.path.exists(filepath):
        return {"error": f"File not found: {filepath}"}
    ext = os.path.splitext(filepath)[1].lower()
    readers = {
        ".xlsx": _read_excel,
        ".xls":  _read_excel,
        ".csv":  _read_csv,
        ".pdf":  _read_pdf,
        ".docx": _read_docx,
        ".doc":  _read_docx,
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
        data["filename"] = os.path.basename(filepath)
        return data
    except Exception as e:
        return {"error": str(e), "filename": os.path.basename(filepath)}

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
            for k, v in content.get("labeled_values", {}).items():
                lines.append(f"  {k} = {v}")
            for col, info in content.get("numeric_columns", {}).items():
                lines.append(
                    f"  [{col}] {info['count']} values | "
                    f"first={info['first']} last={info['last']} "
                    f"min={info['min']} max={info['max']}"
                )
    elif t == "csv":
        lines.append(f"Shape: {data['shape'][0]} rows x {data['shape'][1]} cols")
        for col, info in data.get("columns", {}).items():
            if info.get("type") == "text":
                lines.append(f"  [{col}] text — sample: {info['sample']}")
            else:
                lines.append(
                    f"  [{col}] {info['count']} values | "
                    f"first={info['first']} last={info['last']} "
                    f"min={info['min']} max={info['max']}"
                )
    elif t == "pdf":
        lines.append(f"Pages: {data.get('pages', '?')}")
        lines.append(data.get("text", ""))
    elif t == "docx":
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
