
    @staticmethod
    def build_docx(well, engineer, raw_content):
        """
        PRC-branded Word document using Claude's exact styling engine.
        Navy banner cover page, light-blue info table, running header/footer
        with auto page numbers, JSON-driven sections and styled tables.
        Falls back to markdown parsing if Claude's JSON is invalid.
        """
        # ── Parse Claude JSON ──
        text = raw_content.strip().replace('```json', '').replace('```', '').strip()
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            m = re.search(r'\{.*\}', text, re.DOTALL)
            try:
                data = json.loads(m.group(0)) if m else None
            except Exception:
                data = None

        doc = Document()

        # ── Global document styles ──
        ns = doc.styles['Normal']
        ns.font.name = 'Arial'
        ns.font.size = DocxPt(10.5)
        ns.font.color.rgb = _GRAY_RGB
        ns.paragraph_format.space_after = DocxPt(6)
        for lvl in range(1, 4):
            hs = doc.styles[f'Heading {lvl}']
            hs.font.name = 'Arial'
            hs.font.color.rgb = _NAVY_RGB
        for sec in doc.sections:
            sec.top_margin    = Cm(2.54)
            sec.bottom_margin = Cm(2.54)
            sec.left_margin   = Cm(2.54)
            sec.right_margin  = Cm(2.54)

        # ══════════════════════════════════════════════════
        # COVER PAGE
        # ══════════════════════════════════════════════════

        # Navy top banner
        banner = doc.add_table(rows=1, cols=1)
        banner.alignment = WD_TABLE_ALIGNMENT.CENTER
        bc = banner.rows[0].cells[0]
        _shd(bc, _NAVY_HEX)
        bc.height = Cm(3.0)
        bp = bc.paragraphs[0]
        bp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        bp.space_before = DocxPt(18)
        run = bp.add_run('PETROLEUM RESEARCH CENTER')
        run.bold = True
        run.font.size = DocxPt(22)
        run.font.color.rgb = _WHITE_RGB
        run.font.name = 'Arial'
        bp2 = bc.add_paragraph()
        bp2.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run2 = bp2.add_run('Tripoli, Libya')
        run2.font.size = DocxPt(12)
        run2.font.color.rgb = DocxRGB(0xAA, 0xCC, 0xDD)
        run2.font.name = 'Arial'

        doc.add_paragraph()

        # Logo (real file or empty space)
        logo_p = doc.add_paragraph()
        logo_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        logo_p.space_after = DocxPt(4)
        for lp in ['prc_logo.png', 'prc_logo.jpg']:
            if os.path.exists(lp):
                try:
                    logo_p.add_run().add_picture(lp, width=DocxInches(2.0))
                    break
                except Exception:
                    pass

        # Decorative blue divider line
        line_p = doc.add_paragraph()
        line_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        line_p._element.get_or_add_pPr().append(parse_xml(
            f'<w:pBdr {nsdecls("w")}>'
            f'<w:bottom w:val="single" w:sz="12" w:space="8" w:color="{_BLUE_HEX}"/>'
            f'</w:pBdr>'
        ))
        doc.add_paragraph()

        # Main title
        doc_title = data.get('title', well) if data else well
        title_p = doc.add_paragraph()
        title_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        title_p.space_after = DocxPt(4)
        tr2 = title_p.add_run(doc_title)
        tr2.bold = True
        tr2.font.size = DocxPt(24)
        tr2.font.color.rgb = _NAVY_RGB
        tr2.font.name = 'Arial'

        # Info metadata table (light-blue label column)
        doc.add_paragraph()
        report_num = (
            data.get('report_number', f'PRC-SCAL-{datetime.now().year}-AUTO')
            if data else f'PRC-SCAL-{datetime.now().year}-AUTO'
        )
        info_items = [
            ('Well / Project', well),
            ('Prepared By',    engineer),
            ('Report No.',     report_num),
            ('Date',           datetime.now().strftime('%d %B %Y')),
            ('Classification', 'CONFIDENTIAL \u2014 PRC Internal Use Only'),
        ]
        itbl = doc.add_table(rows=len(info_items), cols=2)
        itbl.alignment = WD_TABLE_ALIGNMENT.CENTER
        itbl.autofit   = False
        for row in itbl.rows:
            row.cells[0].width = DocxInches(2.2)
            row.cells[1].width = DocxInches(4.0)
        for i, (label, value) in enumerate(info_items):
            row = itbl.rows[i]
            row.height = Cm(0.65)
            c0 = row.cells[0]
            c0.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            _shd(c0, _LTBLUE_HEX)
            p0 = c0.paragraphs[0]
            p0.space_before = DocxPt(2)
            p0.space_after  = DocxPt(2)
            r0 = p0.add_run(label)
            r0.bold = True
            r0.font.name = 'Arial'
            r0.font.size = DocxPt(10)
            r0.font.color.rgb = _NAVY_RGB
            c1 = row.cells[1]
            c1.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            p1 = c1.paragraphs[0]
            p1.space_before = DocxPt(2)
            p1.space_after  = DocxPt(2)
            r1 = p1.add_run(str(value))
            r1.font.name = 'Arial'
            r1.font.size = DocxPt(10)
            r1.font.color.rgb = _RED_RGB if i == 4 else _GRAY_RGB
            for cell in [c0, c1]:
                _brd_custom(cell,
                    top   ={'sz': '2', 'color': 'CCCCCC'},
                    bottom={'sz': '2', 'color': 'CCCCCC'},
                    left  ={'sz': '2', 'color': 'CCCCCC'},
                    right ={'sz': '2', 'color': 'CCCCCC'},
                )

        doc.add_page_break()

        # ══════════════════════════════════════════════════
        # RUNNING HEADER & FOOTER (all pages after cover)
        # ══════════════════════════════════════════════════
        section = doc.sections[-1]
        section.different_first_page_header_footer = False

        ftr = section.footer
        ftr.is_linked_to_previous = False
        fp = ftr.paragraphs[0] if ftr.paragraphs else ftr.add_paragraph()
        fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        fp.clear()
        fp._element.get_or_add_pPr().append(parse_xml(
            f'<w:pBdr {nsdecls("w")}>'
            f'<w:top w:val="single" w:sz="4" w:space="4" w:color="{_BLUE_HEX}"/>'
            f'</w:pBdr>'
        ))
        r1a = fp.add_run('Petroleum Research Center \u2014 Confidential')
        r1a.font.name = 'Arial'
        r1a.font.size = DocxPt(8)
        r1a.font.color.rgb = _LTGRAY_RGB
        r2a = fp.add_run('    |    Page ')
        r2a.font.name = 'Arial'
        r2a.font.size = DocxPt(8)
        r2a.font.color.rgb = _LTGRAY_RGB
        _page_num_field(fp)   # auto page number

        hdr = section.header
        hdr.is_linked_to_previous = False
        hp = hdr.paragraphs[0] if hdr.paragraphs else hdr.add_paragraph()
        hp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        hp.clear()
        hp._element.get_or_add_pPr().append(parse_xml(
            f'<w:pBdr {nsdecls("w")}>'
            f'<w:bottom w:val="single" w:sz="4" w:space="4" w:color="{_BLUE_HEX}"/>'
            f'</w:pBdr>'
        ))
        hr2 = hp.add_run(f'PRC SCAL  |  Well {well}  |  {report_num}')
        hr2.font.name = 'Arial'
        hr2.font.size = DocxPt(7.5)
        hr2.font.color.rgb = _LTGRAY_RGB
        hr2.italic = True

        # ══════════════════════════════════════════════════
        # DOCUMENT BODY
        # ══════════════════════════════════════════════════
        if data:
            sc = [0]   # section auto-number counter

            for sect in data.get('sections', []):
                lvl  = min(max(int(sect.get('level', 1)), 1), 3)
                htxt = sect.get('heading', '')
                if lvl == 1:
                    sc[0] += 1
                    htxt = f'{sc[0]}. {htxt}'
                _heading(doc, htxt, level=lvl)

                content = (sect.get('content') or '').strip()
                if '__PRC_PLOT__' in content:
                    try:
                        pjs = content.split('__PRC_PLOT__', 1)[1].strip()
                        chart_data, _ = json.JSONDecoder().raw_decode(pjs)
                        buf = DocumentEngines._draw_chart_for_doc(chart_data)
                        if buf:
                            p2 = doc.add_paragraph()
                            p2.alignment = WD_ALIGN_PARAGRAPH.CENTER
                            p2.add_run().add_picture(buf, width=DocxInches(5.8))
                    except Exception:
                        if content:
                            _body(doc, content.split('__PRC_PLOT__')[0].strip())
                elif content:
                    _body(doc, content)

                for bul in (sect.get('bullets') or []):
                    _bullet(doc, str(bul))

            # Data tables (placed after all sections)
            for tbl in data.get('tables', []):
                if tbl.get('title'):
                    _body(doc, tbl['title'], bold=True, italic=True)
                hdrs  = tbl.get('headers', [])
                rows_ = tbl.get('rows',    [])
                if not hdrs:
                    continue
                nc = len(hdrs)
                aw = [round(6.0 / nc, 2)] * nc
                _styled_table(doc, hdrs, rows_, col_widths_inches=aw)
                doc.add_paragraph()

        else:
            # ── Legacy markdown fallback ──
            _heading(doc, 'ANALYSIS & FINDINGS', level=1)
            tlines = []

            def _flush():
                if not tlines:
                    return
                parsed = []
                for tl in tlines:
                    tl = tl.strip().strip('|')
                    parsed.append([c.strip() for c in tl.split('|')])
                actual = [r for i, r in enumerate(parsed) if i != 1]
                if not actual:
                    return
                nc = max(len(r) for r in actual)
                aw = [round(6.0 / nc, 2)] * nc
                _styled_table(doc, actual[0], actual[1:], col_widths_inches=aw)
                tlines.clear()
                doc.add_paragraph()

            for line in raw_content.split('\n'):
                line = line.replace('**', '').strip()
                if line.startswith('|') and '|' in line[1:]:
                    tlines.append(line)
                    continue
                elif tlines and '|' in line and not line.startswith('#'):
                    tlines[-1] += ' ' + line
                    continue
                else:
                    if tlines:
                        _flush()
                if not line:
                    doc.add_paragraph()
                elif line.startswith('#'):
                    _heading(doc, line.replace('#', '').strip(),
                             level=min(len(line.split(' ')[0]), 3))
                elif line.startswith(('* ', '- ')):
                    _bullet(doc, line[2:])
                else:
                    _body(doc, line)
            if tlines:
                _flush()

        # ── Signature block ──
        doc.add_paragraph()
        doc.add_paragraph()
        sep2 = doc.add_paragraph()
        sep2._element.get_or_add_pPr().append(parse_xml(
            f'<w:pBdr {nsdecls("w")}>'
            f'<w:top w:val="single" w:sz="4" w:space="8" w:color="{_BLUE_HEX}"/>'
            f'</w:pBdr>'
        ))
        sig = doc.add_table(rows=3, cols=2)
        sig.alignment = WD_TABLE_ALIGNMENT.CENTER
        for row in sig.rows:
            row.cells[0].width = DocxInches(3.0)
            row.cells[1].width = DocxInches(3.0)
        sig_data = [
            ('Prepared by:', engineer,                    'Hviel \u2014 PRC AI Petrophysical Specialist'),
            ('Reviewed by:', 'PRC Technical Review Board', 'Chief Petrophysicist'),
        ]
        for ci, (role, name, ttl) in enumerate(sig_data):
            for ri, lbl in enumerate([role, name, ttl]):
                p_ = sig.rows[ri].cells[ci].paragraphs[0]
                r_ = p_.add_run(lbl)
                r_.font.name = 'Arial'
                if ri == 0:
                    r_.font.size = DocxPt(9)
                    r_.font.color.rgb = _LTGRAY_RGB
                elif ri == 1:
                    r_.bold = True
                    r_.font.size = DocxPt(10)
                    r_.font.color.rgb = _NAVY_RGB
                else:
                    r_.font.size = DocxPt(9)
                    r_.font.color.rgb = _GRAY_RGB
        for row in sig.rows:
            for cell in row.cells:
                _brd_none(cell)

        fname = f'PRC_Report_{int(time.time())}.docx'
        doc.save(fname)
        return fname

