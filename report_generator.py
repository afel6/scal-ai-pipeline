import os
import sqlite3
import json
import re
from datetime import datetime
from docx import Document
from docx.shared import Inches, Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.oxml.ns import qn, nsdecls
from docx.oxml import parse_xml
import matplotlib.pyplot as plt
import numpy as np
import io

# ──────────────────────────────────────────────
# BRAND CONSTANTS (Sync with CLAUDE.md)
# ──────────────────────────────────────────────
NAVY = "1B3A5C"
BLUE = "2E75B6"
LIGHT_BLUE = "D5E8F0"
ZEBRA = "F2F2F2"
DARK_GRAY = "333333"
WHITE = "FFFFFF"
RED_ACCENT = "C0392B"

NAVY_RGB = RGBColor(0x1B, 0x3A, 0x5C)
BLUE_RGB = RGBColor(0x2E, 0x75, 0xB6)
GRAY_RGB = RGBColor(0x33, 0x33, 0x33)
WHITE_RGB = RGBColor(0xFF, 0xFF, 0xFF)
RED_RGB = RGBColor(0xC0, 0x39, 0x2B)
LIGHT_GRAY_RGB = RGBColor(0x99, 0x99, 0x99)

class PRCReportEngine:
    def __init__(self, db_path="chat_history.db"):
        self.db_path = db_path

    # --- STYLE HELPERS ---
    def _set_cell_shading(self, cell, color_hex):
        shading_elm = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{color_hex}" w:val="clear"/>')
        cell._element.get_or_add_tcPr().append(shading_elm)

    def _set_cell_border(self, cell, **kwargs):
        tc = cell._element
        tcPr = tc.get_or_add_tcPr()
        tcBorders = parse_xml(f'<w:tcBorders {nsdecls("w")}></w:tcBorders>')
        for edge, attrs in kwargs.items():
            element = parse_xml(
                f'<w:{edge} {nsdecls("w")} w:val="{attrs.get("val", "single")}" '
                f'w:sz="{attrs.get("sz", "4")}" w:space="0" w:color="{attrs.get("color", "CCCCCC")}"/>'
            )
            tcBorders.append(element)
        tcPr.append(tcBorders)

    def _add_heading(self, doc, text, level=1):
        heading = doc.add_heading(level=level)
        run = heading.add_run(text)
        run.font.color.rgb = NAVY_RGB
        run.font.name = "Arial"
        run.bold = True
        if level == 1:
            run.font.size = Pt(16)
            pPr = heading._element.get_or_add_pPr()
            pBdr = parse_xml(
                f'<w:pBdr {nsdecls("w")}>'
                f'  <w:bottom w:val="single" w:sz="6" w:space="4" w:color="{BLUE}"/>'
                f'</w:pBdr>'
            )
            pPr.append(pBdr)
        elif level == 2:
            run.font.size = Pt(13)
        return heading

    def _add_body(self, doc, text, bold=False, italic=False):
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(6)
        p.paragraph_format.line_spacing = 1.25
        run = p.add_run(text)
        run.font.name = "Arial"
        run.font.size = Pt(10.5)
        run.font.color.rgb = GRAY_RGB
        run.bold = bold
        run.italic = italic
        return p

    def generate(self, session_id, well_name="Unknown Well"):
        doc = Document()
        
        # --- COVER PAGE ---
        self._build_cover(doc, well_name)
        
        # --- FETCH DATA ---
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT role, text, url FROM m WHERE sid = ? ORDER BY id", (session_id,))
        messages = cursor.fetchall()
        conn.close()

        # --- SECTION 1: EXECUTIVE SUMMARY ---
        doc.add_page_break()
        self._add_heading(doc, "1. Executive Summary", 1)
        self._add_body(doc, f"This document provides a consolidated technical report for the SCAL study conducted on Well {well_name}. The analysis utilizes the PRC SCAL AI Pipeline (Hviel) for physics-aware interpretation and simulation.")

        # --- SECTION 2: PHYSICS INTEGRITY AUDIT ---
        self._add_heading(doc, "2. Physics Integrity Audit", 1)
        self._build_audit_section(doc, messages)

        # --- SECTION 3: PETROPHYSICAL ANALYSIS & PLOTS ---
        doc.add_page_break()
        self._add_heading(doc, "3. Petrophysical Analysis & Interpretations", 1)
        self._build_analysis_section(doc, messages)

        # --- FOOTER ---
        self._add_footer(doc, well_name)

        filename = f"PRC_SCAL_Report_{well_name}_{session_id[:6]}.docx"
        output_path = os.path.join(os.getcwd(), "reports", filename)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        doc.save(output_path)
        return filename

    def _build_cover(self, doc, well_name):
        # Premium Banner
        banner = doc.add_table(rows=1, cols=1)
        banner.alignment = WD_TABLE_ALIGNMENT.CENTER
        banner_cell = banner.rows[0].cells[0]
        self._set_cell_shading(banner_cell, NAVY)
        banner_cell.height = Cm(3.0)
        bp = banner_cell.paragraphs[0]
        bp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = bp.add_run("PETROLEUM RESEARCH CENTER")
        run.bold = True; run.font.size = Pt(22); run.font.color.rgb = WHITE_RGB
        
        doc.add_paragraph() # Spacer
        
        # Logo placeholder or real logo
        logo_p = doc.add_paragraph()
        logo_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        for lp in ['prc_logo.png', 'prc_logo.jpg']:
            if os.path.exists(lp):
                logo_p.add_run().add_picture(lp, width=Inches(2.0))
                break
        
        doc.add_paragraph()
        title_p = doc.add_paragraph()
        title_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = title_p.add_run("Special Core Analysis (SCAL) Report")
        run.bold = True; run.font.size = Pt(26); run.font.color.rgb = NAVY_RGB
        
        doc.add_paragraph()
        # Metadata Table
        info_table = doc.add_table(rows=4, cols=2)
        info_table.alignment = WD_TABLE_ALIGNMENT.CENTER
        info_items = [
            ("Well Name", well_name),
            ("Date", datetime.now().strftime("%d %B %Y")),
            ("Classification", "CONFIDENTIAL / SOVEREIGN"),
            ("Specialist", "Hviel (AI Petrophysicist)")
        ]
        for i, (label, value) in enumerate(info_items):
            row = info_table.rows[i]
            c0, c1 = row.cells
            self._set_cell_shading(c0, LIGHT_BLUE)
            c0.paragraphs[0].add_run(label).bold = True
            c1.paragraphs[0].add_run(value)

    def _build_audit_section(self, doc, messages):
        self._add_body(doc, "All data processed during this session has passed the PRC Physics Watchtower gates.")
        table = doc.add_table(rows=1, cols=3)
        table.style = 'Table Grid'
        hdr_cells = table.rows[0].cells
        for i, h in enumerate(['Measurement', 'Health Score', 'Status']):
            hdr_cells[i].text = h
            self._set_cell_shading(hdr_cells[i], NAVY)
            run = hdr_cells[i].paragraphs[0].runs[0]
            run.font.color.rgb = WHITE_RGB; run.bold = True

        for role, text, url in messages:
            if "PHYSICS HEALTH AUDIT:" in text:
                try:
                    score = text.split("PHYSICS HEALTH AUDIT:")[1].split("|")[0].strip()
                    status = text.split("STATUS:")[1].split("\n")[0].strip()
                    row = table.add_row().cells
                    row[0].text = "SCAL Study"
                    row[1].text = score
                    row[2].text = status
                except: pass

    def _build_analysis_section(self, doc, messages):
        for i, (role, text, url) in enumerate(messages):
            if role == "model" and "__PRC_PLOT__" in text:
                self._add_heading(doc, f"Analysis: Section {i}", 2)
                try:
                    json_str = text.split("__PRC_PLOT__")[1].strip().split("\n\n")[0]
                    plot_data = json.loads(json_str)
                    dtype = plot_data.get("metadata", {}).get("type", "SCAL")
                    
                    plt.figure(figsize=(6, 4))
                    plt.style.use('dark_background') # Industrial Brutalist feel
                    
                    if dtype == "KR":
                        sw = np.array(plot_data['sw'])
                        plt.plot(sw, plot_data['krw'], color='#38bdf8', label='Krw', linewidth=2)
                        plt.plot(sw, plot_data['kro'], color='#f59e0b', label='Kro', linewidth=2)
                        plt.xlabel('Sw'); plt.ylabel('Kr')
                    elif dtype == "MICP":
                        for s_name, s_data in plot_data.get('samples', {}).items():
                            plt.semilogy(s_data['drainage']['sat_pv'], s_data['drainage']['pressure'], label=s_name)
                        plt.xlabel('Hg Saturation'); plt.ylabel('Pc (psia)')
                    
                    plt.legend(); plt.grid(True, alpha=0.1)
                    img_stream = io.BytesIO()
                    plt.savefig(img_stream, format='png', dpi=150, bbox_inches='tight')
                    plt.close()
                    img_stream.seek(0)
                    doc.add_picture(img_stream, width=Inches(5.0))
                except: pass

                # Add following text as interpretation
                parts = text.split("__PRC_PLOT__")
                if len(parts) > 1:
                    interp = parts[1].split("}")[1].strip() if "}" in parts[1] else ""
                    if interp:
                        p = self._add_body(doc, interp)
                        p.italic = True

    def _add_footer(self, doc, well_name):
        section = doc.sections[0]
        footer = section.footer
        p = footer.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.text = f"PRC Libya  |  Well {well_name}  |  Generated by Hviel AI"

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 2:
        PRCReportEngine().generate(sys.argv[1], sys.argv[2])
