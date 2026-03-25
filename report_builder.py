from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
import matplotlib.pyplot as plt
import numpy as np
import os
import pandas as pd

class SCALReportBuilder:
    """
    Automated Elite Microsoft Word (.docx) Generator for the PRC.
    Constructs highly visual, fully styled engineering deliverables.
    """
    def __init__(self, well_name: str, raw_df: pd.DataFrame):
        self.doc = Document()
        self.well_name = well_name
        self.raw_df = raw_df
        self._setup_enterprise_formatting()

    def _setup_enterprise_formatting(self):
        # Master Style overrides
        style = self.doc.styles['Normal']
        style.font.name = 'Arial'
        style.font.size = Pt(11)
        style.font.color.rgb = RGBColor(40, 40, 40)
        
        # Heading 1
        h1 = self.doc.styles['Heading 1']
        h1.font.name = 'Arial'
        h1.font.size = Pt(24)
        h1.font.bold = True
        h1.font.color.rgb = RGBColor(0, 102, 51) # Emerald Green for PRC

        # Heading 2
        h2 = self.doc.styles['Heading 2']
        h2.font.name = 'Arial'
        h2.font.size = Pt(14)
        h2.font.bold = True
        h2.font.color.rgb = RGBColor(0, 51, 102) # Deep Professional Navy

    def build_title_page(self):
        self.doc.add_paragraph('\n\n\n\n\n')
        title = self.doc.add_heading('PETROLEUM RESEARCH CENTER', level=0)
        title.alignment = WD_ALIGN_PARAGRAPH.CENTER
        
        self.doc.add_paragraph('\n\n')
        subtitle = self.doc.add_heading(f'ENTERPRISE FINAL REPORT\nSPECIAL CORE ANALYSIS (SCAL)\n\nWELL: {self.well_name}', level=1)
        subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
        self.doc.add_page_break()

    def generate_archie_matplotlib(self, params: dict):
        """Builds breathtaking Log-Log Plots proving the AI derived parameters."""
        # Check if we have valid Electrical data
        ff_df = self.raw_df.dropna(subset=['Porosity', 'Formation_Factor'])
        ri_df = self.raw_df.dropna(subset=['Brine_Saturation', 'Resistivity_Index'])
        
        img_paths = []
        
        # 1. Formation Factor Plot (m)
        if len(ff_df) > 1:
            plt.figure(figsize=(6, 4), dpi=150)
            plt.style.use('ggplot')
            plt.scatter(ff_df['Porosity'], ff_df['Formation_Factor'], color='#0f766e', edgecolor='black', s=80, alpha=0.9, label='Core Samples')
            
            # Trendline
            x_trend = np.linspace(min(ff_df['Porosity']), max(ff_df['Porosity']), 100)
            a_val = float(params.get('a_tortuosity', 1.0))
            m_val = float(params.get('m_cementation', 2.0))
            y_trend = a_val / (x_trend ** m_val)
            plt.plot(x_trend, y_trend, color='#e11d48', linewidth=2.5, linestyle='--', label=f'AI Fit (m={m_val})')
            
            plt.xscale('log')
            plt.yscale('log')
            plt.xlabel('Porosity (Fraction)', fontweight='bold')
            plt.ylabel('Formation Factor (FF)', fontweight='bold')
            plt.title("Formation Factor vs Porosity\nArchie's Cementation Exponent", fontweight='bold')
            plt.grid(True, which="both", ls="--", alpha=0.5)
            plt.legend()
            plt.tight_layout()
            
            p1 = 'temp_ff_plot.png'
            plt.savefig(p1)
            img_paths.append(p1)
            plt.close()
            
        # 2. Resistivity plot (n)
        if len(ri_df) > 1:
            plt.figure(figsize=(6, 4), dpi=150)
            plt.style.use('ggplot')
            plt.scatter(ri_df['Brine_Saturation'], ri_df['Resistivity_Index'], color='#4338ca', edgecolor='black', s=80, alpha=0.9, label='Core Samples')
            
            x_trend = np.linspace(min(ri_df['Brine_Saturation']), max(ri_df['Brine_Saturation']), 100)
            n_val = float(params.get('n_saturation', 2.0))
            y_trend = x_trend ** -n_val
            plt.plot(x_trend, y_trend, color='#e11d48', linewidth=2.5, linestyle='--', label=f'AI Fit (n={n_val})')
            
            plt.xscale('log')
            plt.yscale('log')
            plt.xlabel('Brine Saturation (Sw)', fontweight='bold')
            plt.ylabel('Resistivity Index (RI)', fontweight='bold')
            plt.title("Resistivity Index vs Sw\nArchie's Saturation Exponent", fontweight='bold')
            plt.grid(True, which="both", ls="--", alpha=0.5)
            plt.legend()
            plt.tight_layout()
            
            p2 = 'temp_ri_plot.png'
            plt.savefig(p2)
            img_paths.append(p2)
            plt.close()
            
        return img_paths

    def add_archies_table(self, archie_dict: dict):
        self.doc.add_heading('1. Electrical Properties (Archie\'s Analysis)', level=2)
        
        # Inject the breathtaking graphs!
        img_paths = self.generate_archie_matplotlib(archie_dict)
        if img_paths:
            self.doc.add_paragraph('Figure 1: Mathematical regressions for Archie\'s coefficients derived from valid core data.')
            for img in img_paths:
                self.doc.add_picture(img, width=Inches(5.0))
                # Delete temp image explicitly to prevent IO Lock issues later
                try:
                    os.remove(img)
                except:
                    pass
        
        self.doc.add_paragraph('\nCalculated Results:')
        table = self.doc.add_table(rows=2, cols=3)
        table.style = 'Light Shading Accent 1' 
        
        hdr = table.rows[0].cells
        hdr[0].text = 'Tortuosity Factor (a)'
        hdr[1].text = 'Cementation Exponent (m)'
        hdr[2].text = 'Saturation Exponent (n)'
        
        row = table.rows[1].cells
        row[0].text = str(archie_dict['a_tortuosity'])
        row[1].text = str(archie_dict['m_cementation'])
        row[2].text = str(archie_dict['n_saturation'])
        self.doc.add_paragraph('\n')

    def add_saturation_endpoints(self, endpoints: dict):
        self.doc.add_heading('2. Capillary Pressure Saturation Limits', level=2)
        table = self.doc.add_table(rows=2, cols=2)
        table.style = 'Light Shading Accent 1'
        
        table.rows[0].cells[0].text = 'Irreducible Water Saturation (Swi)'
        table.rows[0].cells[1].text = 'Residual Oil Saturation (Sor)'
        
        table.rows[1].cells[0].text = str(endpoints['Swi'])
        table.rows[1].cells[1].text = str(endpoints['Sor'])
        self.doc.add_paragraph('\n')

    def add_ai_conclusion(self, insight_text: str):
        self.doc.add_heading('3. Artificial Intelligence Reservoir Interpretation', level=2)
        p = self.doc.add_paragraph(insight_text)
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY

    def export(self) -> str:
        file_name = f"{self.well_name}_SCAL_Final_Report.docx"
        self.doc.save(file_name)
        return file_name
