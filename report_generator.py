import os
import sqlite3
import json
from datetime import datetime
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
import matplotlib.pyplot as plt
import io

class PRCReportEngine:
    def __init__(self, db_path="chat_history.db"):
        self.db_path = db_path
        self.navy = RGBColor(30, 27, 75)   # #1e1b4b
        self.gold = RGBColor(255, 215, 0) # #ffd700

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

        # --- SECTION 1: PHYSICS AUDIT ---
        doc.add_page_break()
        doc.add_heading('Section 1: Physics Integrity Audit', 1)
        self._build_audit_section(doc, messages)

        # --- SECTION 2: PETROPHYSICAL ANALYSIS ---
        doc.add_page_break()
        doc.add_heading('Section 2: Petrophysical Analysis', 1)
        self._build_analysis_section(doc, messages)

        # --- FOOTER ---
        self._add_footer(doc)

        filename = f"PRC_Executive_Report_{session_id[:8]}.docx"
        output_path = os.path.join(os.getcwd(), "reports", filename)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        doc.save(output_path)
        return filename

    def _build_cover(self, doc, well_name):
        # Header bar (simulated with a paragraph + shading)
        p = doc.add_paragraph()
        run = p.add_run("PETROLEUM RESEARCH CENTER (PRC), LIBYA")
        run.bold = True
        run.font.size = Pt(24)
        run.font.color.rgb = self.navy
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER

        doc.add_paragraph().add_run().add_break()
        
        title = doc.add_paragraph()
        run = title.add_run("EXECUTIVE SCAL SUMMARY REPORT")
        run.bold = True
        run.font.size = Pt(36)
        title.alignment = WD_ALIGN_PARAGRAPH.CENTER

        doc.add_paragraph().add_run().add_break()

        # Metadata Table
        table = doc.add_table(rows=4, cols=2)
        table.style = 'Table Grid'
        
        cells = [
            ("Well Name:", well_name),
            ("Report Date:", datetime.now().strftime("%Y-%m-%d %H:%M")),
            ("Classification:", "Strictly Confidential / Sovereign"),
            ("Specialist:", "Hviel (AI Petrophysical Specialist)")
        ]
        
        for i, (label, val) in enumerate(cells):
            table.cell(i, 0).text = label
            table.cell(i, 1).text = val

    def _build_audit_section(self, doc, messages):
        doc.add_paragraph("The following quality gates were applied to the laboratory data uploaded during this session.")
        
        table = doc.add_table(rows=1, cols=3)
        table.style = 'Table Grid'
        hdr_cells = table.rows[0].cells
        hdr_cells[0].text = 'Data Type'
        hdr_cells[1].text = 'Health Score'
        hdr_cells[2].text = 'Status'

        for role, text, url in messages:
            if "PHYSICS HEALTH AUDIT:" in text:
                try:
                    # Extract score and status
                    score_part = text.split("PHYSICS HEALTH AUDIT:")[1].split("|")[0].strip()
                    status_part = text.split("STATUS:")[1].split("\n")[0].strip()
                    dtype = "SCAL Data" # Simplified
                    
                    row_cells = table.add_row().cells
                    row_cells[0].text = dtype
                    row_cells[1].text = score_part
                    row_cells[2].text = status_part
                except:
                    pass

    def _build_analysis_section(self, doc, messages):
        import re
        import numpy as np
        
        for i, (role, text, url) in enumerate(messages):
            if role == "model" and "__PRC_PLOT__" in text:
                doc.add_heading(f"Analysis Chapter {i}", 2)
                
                # 1. Extract JSON data
                try:
                    json_str = text.split("__PRC_PLOT__")[1].strip().split("\n\n")[0]
                    plot_data = json.loads(json_str)
                    dtype = plot_data.get("metadata", {}).get("type", "SCAL")
                    
                    # 2. Render Plot to memory buffer
                    plt.figure(figsize=(6, 4))
                    plt.style.use('seaborn-v0_8-whitegrid') # Professional look
                    
                    if dtype == "KR":
                        sw = np.array(plot_data['sw'])
                        plt.plot(sw, plot_data['krw'], 'b-', label='Krw', linewidth=2)
                        plt.plot(sw, plot_data['kro'], 'r-', label='Kro', linewidth=2)
                        if 'krw_fit' in plot_data:
                            plt.plot(sw, plot_data['krw_fit'], 'b--', alpha=0.5)
                        if 'kro_fit' in plot_data:
                            plt.plot(sw, plot_data['kro_fit'], 'r--', alpha=0.5)
                        plt.xlabel('Water Saturation (Sw)')
                        plt.ylabel('Relative Permeability (Kr)')
                        plt.title(f'Kr Analysis: {plot_data.get("metadata",{}).get("well","")}')
                    elif dtype == "MICP":
                        # Simple MICP plot reconstruction
                        for sample_name, sdata in plot_data.get('samples', {}).items():
                            plt.semilogy(sdata['drainage']['sat_pv'], sdata['drainage']['pressure'], label=f'{sample_name} (D)')
                        plt.xlabel('Mercury Saturation (% PV)')
                        plt.ylabel('Capillary Pressure (psia)')
                        plt.title('MICP Capillary Pressure')
                    
                    plt.legend()
                    plt.grid(True, which="both", ls="-", alpha=0.2)
                    
                    img_stream = io.BytesIO()
                    plt.savefig(img_stream, format='png', dpi=150, bbox_inches='tight')
                    plt.close()
                    img_stream.seek(0)
                    
                    # 3. Insert into Word
                    doc.add_picture(img_stream, width=Inches(5.5))
                except Exception as e:
                    doc.add_paragraph(f"[Error rendering plot: {e}]")

                # 4. Extract and add interpretation text
                # Usually interpretation is after the plot
                parts = text.split("__PRC_PLOT__")
                if len(parts) > 1:
                    interpretation = parts[1].split("}")[1].strip() if "}" in parts[1] else ""
                    if interpretation:
                        doc.add_paragraph("Interpretation:", style='Intense Quote')
                        doc.add_paragraph(interpretation)

    def _add_footer(self, doc):
        section = doc.sections[0]
        footer = section.footer
        p = footer.paragraphs[0]
        p.text = "Hviel | Senior Petrophysicist | PRC Libya | Sovereign Analysis Pipeline"
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 2:
        engine = PRCReportEngine()
        engine.generate(sys.argv[1], sys.argv[2])
