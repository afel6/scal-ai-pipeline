from docx import Document
from docx.shared import Inches, Pt, RGBColor, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
import matplotlib.pyplot as plt
import numpy as np
import os
import pandas as pd
from datetime import datetime

# Official PRC Brand Colors
PRC_RED    = RGBColor(227, 30, 36)   # #E31E24
PRC_BLUE   = RGBColor(45, 53, 142)   # #2D358E
PRC_YELLOW = RGBColor(251, 191, 36) # #fbbf24 (Gold Accent)
PRC_BLACK  = RGBColor(0, 0, 0)       # #000000
PRC_DARK   = RGBColor(40, 40, 40)    # Sub-text
PRC_LIGHT  = RGBColor(245, 245, 245)  # Bg

LOGO_PATH = os.path.join(os.path.dirname(__file__), 'prc_logo.jpg')


def _set_cell_background(cell, hex_color: str):
    """Set a table cell's background colour via XML."""
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'), hex_color)
    tcPr.append(shd)


class SCALReportBuilder:
    """
    Automated Professional Microsoft Word (.docx) Generator for the PRC.
    Aligned with official institutional branding (Red/Blue/Black).
    """
    def __init__(self, well_name: str, raw_df: pd.DataFrame, engineer_name: str = "PRC Engineering Staff"):
        self.doc = Document()
        self.well_name = well_name
        self.raw_df = raw_df
        self.engineer_name = engineer_name
        self.generated_date = datetime.now().strftime("%B %d, %Y")
        self._setup_page_margins()
        self._setup_enterprise_formatting()

    def _setup_page_margins(self):
        for section in self.doc.sections:
            section.top_margin    = Cm(2.0)
            section.bottom_margin = Cm(2.0)
            section.left_margin   = Cm(2.5)
            section.right_margin  = Cm(2.5)

    def _setup_enterprise_formatting(self):
        style = self.doc.styles['Normal']
        style.font.name = 'Arial'
        style.font.size = Pt(11)
        style.font.color.rgb = PRC_DARK

        h1 = self.doc.styles['Heading 1']
        h1.font.name = 'Arial'
        h1.font.size = Pt(20)
        h1.font.bold = True
        h1.font.color.rgb = PRC_RED

        h2 = self.doc.styles['Heading 2']
        h2.font.name = 'Arial'
        h2.font.size = Pt(13)
        h2.font.bold = True
        h2.font.color.rgb = PRC_BLUE

    def build_title_page(self):
        # ── Official Logo ──
        if os.path.exists(LOGO_PATH):
            logo_para = self.doc.add_paragraph()
            logo_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = logo_para.add_run()
            run.add_picture(LOGO_PATH, width=Inches(3.5))

        self.doc.add_paragraph('\n')

        # ── Institutional Header ──
        header_tbl = self.doc.add_table(rows=1, cols=1)
        header_tbl.alignment = WD_ALIGN_PARAGRAPH.CENTER
        cell = header_tbl.rows[0].cells[0]
        _set_cell_background(cell, 'E31E24') # Official Red
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run('PETROLEUM RESEARCH CENTER (PRC)')
        run.bold = True
        run.font.name = 'Arial'
        run.font.size = Pt(16)
        run.font.color.rgb = RGBColor(255, 255, 255)

        self.doc.add_paragraph()

        # ── Report Metadata Block ──
        meta = self.doc.add_table(rows=5, cols=2)
        meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
        labels = [
            'Well / Project Name:', 
            'Submission Date:', 
            'Authorizing Engineer:', 
            'System Developer:',
            'Classification Status:'
        ]
        values = [
            self.well_name.upper(),
            self.generated_date,
            self.engineer_name,
            'Raouf Elkabir',
            'CONFIDENTIAL — LIBYAN NOC INTERNAL'
        ]
        for i, (lbl, val) in enumerate(zip(labels, values)):
            lc = meta.rows[i].cells[0]
            vc = meta.rows[i].cells[1]
            _set_cell_background(lc, 'F0F0F0')
            lp = lc.paragraphs[0]
            lr = lp.add_run(lbl)
            lr.bold = True; lr.font.name = 'Arial'; lr.font.size = Pt(10); lr.font.color.rgb = PRC_BLUE
            vp = vc.paragraphs[0]
            vr = vp.add_run(val)
            vr.font.name = 'Arial'; vr.font.size = Pt(10); vr.font.color.rgb = PRC_BLACK

        self.doc.add_paragraph('\n\n')
        disclaimer = self.doc.add_paragraph('This Technical Evaluation Report has been compiled utilizing the PRC AI Co-Authoring Engine. All analysis is verified through petrophysical regression of submitted core laboratory data.')
        disclaimer.alignment = WD_ALIGN_PARAGRAPH.CENTER
        disclaimer.runs[0].font.size = Pt(8)
        disclaimer.runs[0].font.italic = True

        self.doc.add_page_break()

    def generate_archie_matplotlib(self, params: dict):
        ff_df = self.raw_df.dropna(subset=['Porosity', 'Formation_Factor'])
        ri_df = self.raw_df.dropna(subset=['Brine_Saturation', 'Resistivity_Index'])
        img_paths = []

        if len(ff_df) > 1:
            fig, ax = plt.subplots(figsize=(7, 4.5), dpi=150)
            ax.scatter(ff_df['Porosity'], ff_df['Formation_Factor'], color='#E31E24', edgecolor='black', s=80, alpha=0.9, label='Core Data')
            x_trend = np.linspace(min(ff_df['Porosity']), max(ff_df['Porosity']), 100)
            a_val, m_val = float(params.get('a_tortuosity', 1.0)), float(params.get('m_cementation', 2.0))
            y_trend = a_val / (x_trend ** m_val)
            ax.plot(x_trend, y_trend, color='#fbbf24', linewidth=3, linestyle='-', label=f'AI Fit (m = {m_val:.3f})')
            ax.set_xscale('log'); ax.set_yscale('log')
            ax.set_xlabel('Porosity (Fraction)', fontweight='bold')
            ax.set_ylabel('Formation Factor (FF)', fontweight='bold')
            ax.set_title("PRC Analysis: Formation Factor vs Porosity", fontweight='bold', color='#fbbf24')
            ax.grid(True, which='both', ls='--', alpha=0.3)
            ax.legend()
            p1 = 'temp_ff_plot.png'
            plt.savefig(p1, bbox_inches='tight')
            img_paths.append(p1); plt.close()

        if len(ri_df) > 1:
            fig, ax = plt.subplots(figsize=(7, 4.5), dpi=150)
            ax.scatter(ri_df['Brine_Saturation'], ri_df['Resistivity_Index'], color='#E31E24', edgecolor='black', s=80, alpha=0.9, label='Core Data')
            x_trend = np.linspace(min(ri_df['Brine_Saturation']), max(ri_df['Brine_Saturation']), 100)
            n_val = float(params.get('n_saturation', 2.0))
            y_trend = x_trend ** -n_val
            ax.plot(x_trend, y_trend, color='#2D358E', linewidth=2.5, linestyle='--', label=f'AI Fit (n = {n_val:.3f})')
            ax.set_xscale('log'); ax.set_yscale('log')
            ax.set_xlabel('Sw (Brine Saturation)', fontweight='bold')
            ax.set_ylabel('Resistivity Index (RI)', fontweight='bold')
            ax.set_title("PRC Analysis: Resistivity Index vs Sw", fontweight='bold', color='#2D358E')
            ax.grid(True, which='both', ls='--', alpha=0.3)
            ax.legend()
            p2 = 'temp_ri_plot.png'
            plt.savefig(p2, bbox_inches='tight')
            img_paths.append(p2); plt.close()

        return img_paths

    def add_archies_table(self, archie_dict: dict):
        self.doc.add_heading('1. ARCHIE ELECTRICAL PROPERTIES ANALYSIS', level=2)
        img_paths = self.generate_archie_matplotlib(archie_dict)
        if img_paths:
            for img in img_paths:
                p = self.doc.add_paragraph()
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                p.add_run().add_picture(img, width=Inches(5.0))
                try: os.remove(img)
                except: pass

        self.doc.add_paragraph('Mathematical Exponents Summary:')
        table = self.doc.add_table(rows=2, cols=3)
        table.style = 'Light List Accent 1'
        hdrs = ['Tortuosity (a)', 'Cementation (m)', 'Saturation (n)']
        vals = [str(archie_dict['a_tortuosity']), str(archie_dict['m_cementation']), str(archie_dict['n_saturation'])]
        for i, (h, v) in enumerate(zip(hdrs, vals)):
            _set_cell_background(table.rows[0].cells[i], 'fbbf24') # Yellow Accent
            r1 = table.rows[0].cells[i].paragraphs[0].add_run(h)
            r1.bold = True; r1.font.color.rgb = PRC_BLACK
            r2 = table.rows[1].cells[i].paragraphs[0].add_run(v)
            r2.bold = True; r2.font.color.rgb = PRC_BLACK

    def add_saturation_endpoints(self, endpoints: dict):
        self.doc.add_heading('2. SATURATION ENDPOINTS (Swi / Sor)', level=2)
        table = self.doc.add_table(rows=2, cols=2)
        table.style = 'Light List Accent 1'
        hdrs = ['Irreducible Water (Swi)', 'Residual Oil (Sor)']
        vals = [str(endpoints['Swi']), str(endpoints['Sor'])]
        for i, (h, v) in enumerate(zip(hdrs, vals)):
            _set_cell_background(table.rows[0].cells[i], 'fbbf24')
            r1 = table.rows[0].cells[i].paragraphs[0].add_run(h)
            r1.bold = True; r1.font.color.rgb = PRC_BLACK
            r2 = table.rows[1].cells[i].paragraphs[0].add_run(v)
            r2.bold = True; r2.font.color.rgb = PRC_BLACK

    def add_ai_conclusion(self, insight_text: str):
        self.doc.add_heading('3. EXECUTIVE CORE EXEGESIS & SUMMARY', level=2)
        p = self.doc.add_paragraph(insight_text)
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY

        self.doc.add_paragraph()
        # Footer signature block
        sig_tbl = self.doc.add_table(rows=1, cols=1)
        sig_tbl.style = 'Table Grid'
        sig_cell = sig_tbl.rows[0].cells[0]
        _set_cell_background(sig_cell, '2D358E')
        sp = sig_cell.paragraphs[0]
        sp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        sr = sp.add_run(f'PRC AI Hub v2.5  ·  Developed by Raouf Elkabir  ·  CONFIDENTIAL')
        sr.font.name = 'Arial'; sr.font.size = Pt(8)
        sr.font.color.rgb = RGBColor(255, 255, 255)

    def export(self) -> str:
        f = f"{self.well_name}_PRC_Technical_Report.docx"
        self.doc.save(f)
        return f
