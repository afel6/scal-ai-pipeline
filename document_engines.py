import time, json, re, io
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# PowerPoint Dependencies
from pptx import Presentation
from pptx.util import Inches, Pt as PtxPt
from pptx.dml.color import RGBColor as PtxRGB

# Word Dependencies
from docx import Document
from docx.shared import Pt as DocxPt, RGBColor as DocxRGB
from docx.enum.text import WD_ALIGN_PARAGRAPH

# PDF Dependencies
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors as rl_colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

class DocumentEngines:
    @staticmethod
    def _draw_chart_for_doc(data, format='png'):
        """Creates a chart image buffer suitable for injection into DOC/PPT/PDF."""
        _COLORS = ['#1e3a8a', '#E31E24', '#F59E0B', '#16a34a', '#7c3aed', '#0891b2']
        try:
            fig, ax = plt.subplots(figsize=(7, 4.5), dpi=150)
            plt.style.use('bmh')
            title  = data.get('title', 'PRC Analysis')
            xlabel = data.get('x_label', 'X')
            ylabel = data.get('y_label', 'Y')

            curves = data.get('curves')  # multi-curve schema
            if curves and isinstance(curves, list):
                for i, curve in enumerate(curves):
                    ax.plot(curve.get('x', []), curve.get('y', []),
                            marker='o', linestyle='-', linewidth=2.5, markersize=7,
                            color=_COLORS[i % len(_COLORS)], label=curve.get('label', f'Series {i+1}'))
                ax.legend(fontsize=9, framealpha=0.85)
            else:
                ax.plot(data.get('x', []), data.get('y', []),
                        marker='o', linestyle='-', color='#1e3a8a', linewidth=2.5, markersize=8)

            ax.set_title(title, fontsize=15, fontweight='bold', color='#1e3a8a')
            ax.set_xlabel(xlabel, fontsize=11, fontweight='bold')
            ax.set_ylabel(ylabel, fontsize=11, fontweight='bold')
            ax.grid(True, linestyle='--', alpha=0.6)
            buf = io.BytesIO()
            fig.savefig(buf, format=format, bbox_inches='tight')
            plt.close(fig)
            buf.seek(0)
            return buf
        except:
            return None

    @staticmethod
    def build_pptx(well, engineer, json_str):
        prs = Presentation()
        # Create Title Slide (Layout 0)
        title_slide = prs.slides.add_slide(prs.slide_layouts[0])
        title_slide.shapes.title.text = "PRC TECHNICAL EVALUATION"
        title_slide.placeholders[1].text = f"Well: {well.upper()}\nPrepared by: {engineer}\n"
        
        # Override Title Slide text colors
        title_slide.shapes.title.text_frame.paragraphs[0].font.color.rgb = PtxRGB(227, 30, 36) # Red
        title_slide.placeholders[1].text_frame.paragraphs[0].font.color.rgb = PtxRGB(45, 53, 142) # Blue
        
        try:
            deck = json.loads(json_str)
            slides_data = deck.get('slides', [])
        except:
            slides_data = [{"title": "Analysis Error", "bullets": ["Failed to parse PPTX JSON scheme."]}]

        for slide_data in slides_data:
            # Bullet Slide (Layout 1)
            slide = prs.slides.add_slide(prs.slide_layouts[1])
            slide.shapes.title.text = slide_data.get('title', 'Analysis Details')
            slide.shapes.title.text_frame.paragraphs[0].font.color.rgb = PtxRGB(45, 53, 142)
            
            tf = slide.placeholders[1].text_frame
            bullets = slide_data.get('bullets', [])
            
            # The first bullet populates the existing first paragraph
            if bullets:
                tf.text = bullets[0]
                for b in bullets[1:]:
                    p = tf.add_paragraph()
                    p.text = b
                    p.level = 0
            
            # If chart data is provided
            if 'chart' in slide_data:
                buf = DocumentEngines._draw_chart_for_doc(slide_data['chart'])
                if buf:
                    slide.shapes.add_picture(buf, Inches(1), Inches(2.5), width=Inches(8))

        fname = f"PRC_Presentation_{int(time.time())}.pptx"
        prs.save(fname)
        return fname

    @staticmethod
    def build_pdf(well, engineer, md_text):
        fname = f"PRC_Report_{int(time.time())}.pdf"
        doc = SimpleDocTemplate(fname, pagesize=letter)
        styles = getSampleStyleSheet()
        
        # Custom Title Style
        title_style = ParagraphStyle(
            'PRCTitle', parent=styles['Heading1'], fontSize=20, textColor=rl_colors.HexColor('#E31E24'),
            alignment=1, spaceAfter=20
        )
        sub_style = ParagraphStyle(
            'PRCSub', parent=styles['Normal'], fontSize=12, textColor=rl_colors.HexColor('#2D358E'),
            alignment=1, spaceAfter=30
        )
        h2_style = ParagraphStyle(
            'PRCH2', parent=styles['Heading2'], fontSize=16, textColor=rl_colors.HexColor('#2D358E'),
            spaceBefore=15, spaceAfter=10
        )
        body_style = ParagraphStyle('PRCBody', parent=styles['Normal'], fontSize=11, spaceAfter=10)
        
        elements = []
        elements.append(Paragraph("PETROLEUM RESEARCH CENTER", title_style))
        elements.append(Paragraph(f"Well / Project: {well.upper()}", sub_style))
        elements.append(Paragraph(f"Prepared by: {engineer}", sub_style))

        for line in md_text.split('\n'):
            line = line.replace('**', '').strip()
            if not line: continue
            
            if line.startswith('#'):
                clean_text = line.replace('#', '').strip()
                elements.append(Paragraph(clean_text, h2_style))
            elif line.startswith('- ') or line.startswith('* '):
                clean_text = line[2:].strip()
                elements.append(Paragraph(f"• {clean_text}", body_style))
            else:
                elements.append(Paragraph(line, body_style))
                
        doc.build(elements)
        return fname

    @staticmethod
    def build_docx(well, engineer, insight):
        import os
        from docx.oxml.ns import qn
        from docx.oxml import OxmlElement

        def set_cell_bg(cell, hex_color):
            """Apply a solid background colour to a table cell."""
            tc = cell._tc
            tcPr = tc.get_or_add_tcPr()
            shd = OxmlElement('w:shd')
            shd.set(qn('w:val'), 'clear')
            shd.set(qn('w:color'), 'auto')
            shd.set(qn('w:fill'), hex_color)
            tcPr.append(shd)

        doc = Document()
        # ── Cover Page ──
        title = doc.add_heading('PRC TECHNICAL EVALUATION REPORT', 0)
        title.alignment = WD_ALIGN_PARAGRAPH.CENTER
        title.runs[0].font.color.rgb = DocxRGB(227, 30, 36)  # PRC Red

        # PRC Logo
        logo_paths = ['prc_logo.png', 'prc_logo.jpg']
        for lp in logo_paths:
            if os.path.exists(lp):
                try:
                    from docx.shared import Inches as docxInches
                    logo_para = doc.add_paragraph()
                    logo_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    logo_run = logo_para.add_run()
                    logo_run.add_picture(lp, width=docxInches(2.0))
                    break
                except: pass

        subtitle = doc.add_paragraph(f'Well / Project: {well.upper()}')
        subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
        subtitle.runs[0].font.size = DocxPt(14)
        subtitle.runs[0].font.bold = True
        subtitle.runs[0].font.color.rgb = DocxRGB(45, 53, 142)  # PRC Navy

        meta = doc.add_paragraph(f"Prepared by: {engineer}\nDate: {time.strftime('%B %d, %Y')}")
        meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
        meta.runs[0].font.italic = True

        doc.add_page_break()
        h1 = doc.add_heading('EXECUTIVE SUMMARY & ANALYSIS', 1)
        h1.runs[0].font.color.rgb = DocxRGB(45, 53, 142)

        clean_text = insight.strip()
        lines = clean_text.split('\n')

        table_lines = []

        def render_table():
            nonlocal table_lines, doc
            if not table_lines: return

            parsed = []
            for tline in table_lines:
                tline = tline.strip()
                if tline.startswith('|'): tline = tline[1:]
                if tline.endswith('|'): tline = tline[:-1]
                cells = [c.strip() for c in tline.split('|')]
                parsed.append(cells)

            if len(parsed) > 1:
                # Remove the markdown separator row (e.g. |---|---|)
                actual_data = [row for i, row in enumerate(parsed) if i != 1]
                if not actual_data: return

                num_cols = max(len(r) for r in actual_data)
                table = doc.add_table(rows=len(actual_data), cols=num_cols)
                table.style = 'Table Grid'

                # Zebra-stripe colours
                _HEADER_HEX = '2D358E'   # PRC Navy
                _ALT_HEX    = 'EEF1FA'   # light periwinkle

                for r_idx, row_data in enumerate(actual_data):
                    for c_idx in range(num_cols):
                        cell_value = row_data[c_idx] if c_idx < len(row_data) else ''
                        cell = table.cell(r_idx, c_idx)
                        cell.text = cell_value
                        if r_idx == 0:
                            # Header row — navy bg, white bold text
                            set_cell_bg(cell, _HEADER_HEX)
                            run = cell.paragraphs[0].runs
                            if run:
                                run[0].font.bold = True
                                run[0].font.color.rgb = DocxRGB(255, 255, 255)
                        elif r_idx % 2 == 0:
                            set_cell_bg(cell, _ALT_HEX)

            table_lines.clear()
            doc.add_paragraph()

        i = 0
        while i < len(lines):
            raw_line = lines[i]
            line = raw_line.replace('**', '').strip()

            # Detect Markdown Table Row (including Hard-wrapped text)
            if line.startswith('|') and '|' in line[1:]:
                table_lines.append(line)
                i += 1
                continue
            elif table_lines and '|' in line and not line.startswith('#'):
                # Line continuation for hard-wrapped Markdown!
                table_lines[-1] += " " + line
                i += 1
                continue
            else:
                if table_lines:
                    render_table()

            if not line:
                doc.add_paragraph()
            elif '__PRC_PLOT__' in line:
                plot_str = line.split('__PRC_PLOT__')[-1]
                json_text = ""
                j = i
                while j < len(lines):
                    json_text += lines[j]
                    if '}' in lines[j]:
                        i = j
                        break
                    j += 1

                m = re.search(r'\{.*\}', json_text, re.DOTALL)
                if m:
                    try:
                        chart_data = json.loads(m.group(0))
                        buf = DocumentEngines._draw_chart_for_doc(chart_data)
                        if buf:
                            p = doc.add_paragraph()
                            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                            from docx.shared import Inches as docxInches
                            p.add_run().add_picture(buf, width=docxInches(6.0))
                    except: pass
            elif line.startswith('#'):
                level = len(line.split(' ')[0])
                text = line.replace('#', '').strip()
                h = doc.add_heading(text, level=min(level, 3))
                h.runs[0].font.color.rgb = DocxRGB(45, 53, 142)
            elif line.startswith('* ') or line.startswith('- '):
                doc.add_paragraph(line[2:], style='List Bullet')
            else:
                doc.add_paragraph(line)

            i += 1

        if table_lines:
            render_table()

        fname = f"PRC_Report_{int(time.time())}.docx"
        doc.save(fname)
        return fname

    @staticmethod
    def build_excel(well, engineer, csv_text):
        import pandas as pd
        import openpyxl
        from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
        import io

        # ── Parse CSV from Claude ──
        csv_text = csv_text.strip()
        if ',' not in csv_text and len(csv_text.split()) > 10:
            df = pd.DataFrame({'Data': [csv_text]})
        else:
            try:
                df = pd.read_csv(io.StringIO(csv_text))
            except Exception:
                df = pd.DataFrame({'RAW_TEXT': csv_text.split('\n')})

        fname = f"PRC_Dataset_{int(time.time())}.xlsx"

        # ── Write with openpyxl for full styling control ──
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = 'PRC SCAL Data'

        # Style constants
        NAVY   = 'FF2D358E'  # PRC Navy
        WHITE  = 'FFFFFFFF'
        ALT    = 'FFEEF1FA'  # subtle periwinkle alternate row
        BORDER = Side(style='thin', color='FFB0B8D0')
        thin_border = Border(left=BORDER, right=BORDER, top=BORDER, bottom=BORDER)

        header_font = Font(name='Calibri', bold=True, color=WHITE, size=11)
        header_fill = PatternFill('solid', fgColor=NAVY)
        header_align = Alignment(horizontal='center', vertical='center', wrap_text=True)
        cell_align   = Alignment(horizontal='left',   vertical='center', wrap_text=True)
        alt_fill     = PatternFill('solid', fgColor=ALT)

        # Write header row (row 1)
        for col_idx, col_name in enumerate(df.columns, start=1):
            cell = ws.cell(row=1, column=col_idx, value=str(col_name))
            cell.font   = header_font
            cell.fill   = header_fill
            cell.border = thin_border
            cell.alignment = header_align

        # Write data rows
        for row_idx, row in enumerate(df.itertuples(index=False), start=2):
            is_alt = (row_idx % 2 == 1)  # alternate every other data row
            for col_idx, value in enumerate(row, start=1):
                cell = ws.cell(row=row_idx, column=col_idx, value=value)
                cell.border    = thin_border
                cell.alignment = cell_align
                if is_alt:
                    cell.fill = alt_fill

        # Freeze header row
        ws.freeze_panes = 'A2'

        # Auto-fit column widths (cap at 45 chars)
        for col_cells in ws.columns:
            max_len = 0
            col_letter = col_cells[0].column_letter
            for cell in col_cells:
                try:
                    max_len = max(max_len, len(str(cell.value or '')))
                except:
                    pass
            ws.column_dimensions[col_letter].width = min(max_len + 4, 45)

        # Row height for header
        ws.row_dimensions[1].height = 22

        # Add metadata on a second sheet
        meta_ws = wb.create_sheet('Report Info')
        meta_ws['A1'] = 'PRC SCAL AI Export'
        meta_ws['A2'] = f'Well / Project: {well}'
        meta_ws['A3'] = f'Prepared by: {engineer}'
        meta_ws['A4'] = f'Generated: {time.strftime("%B %d, %Y")}'
        meta_ws['A1'].font = Font(bold=True, color=NAVY[2:], size=14)

        wb.save(fname)
        return fname
