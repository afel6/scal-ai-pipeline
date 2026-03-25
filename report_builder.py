from docx import Document
from docx.shared import Inches, Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH

class SCALReportBuilder:
    """
    Automated Microsoft Word (.docx) Draft Final Report Generator.
    Pipes all strictly formatted engineering mathematics and Natural Language 
    AI interpretations directly into readable PRC tables.
    """
    def __init__(self, well_name: str):
        self.doc = Document()
        self.well_name = well_name
        self._setup_formatting()

    def _setup_formatting(self):
        style = self.doc.styles['Normal']
        style.font.name = 'Arial'
        style.font.size = Pt(11)

    def build_title_page(self):
        self.doc.add_paragraph('\n\n\n')
        self.doc.add_heading('PETROLEUM RESEARCH CENTER', level=0).alignment = WD_ALIGN_PARAGRAPH.CENTER
        self.doc.add_paragraph('\n\n')
        self.doc.add_heading(f'DRAFT FINAL REPORT\nSPECIAL CORE ANALYSIS (SCAL)\n\nWELL: {self.well_name}', level=1).alignment = WD_ALIGN_PARAGRAPH.CENTER
        self.doc.add_page_break()

    def add_archies_table(self, archie_dict: dict):
        self.doc.add_heading('1. Electrical Properties (Archie\'s Parameters)', level=2)
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
        """Allows the LLM to actively co-author the Engineering report conclusions."""
        self.doc.add_heading('3. Artificial Intelligence Reservoir Interpretation', level=2)
        p = self.doc.add_paragraph(insight_text)
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY

    def export(self) -> str:
        file_name = f"{self.well_name}_SCAL_Final_Report.docx"
        self.doc.save(file_name)
        return file_name
