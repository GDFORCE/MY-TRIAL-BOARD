"""Export Profile as CV (BRD 22): turns the CV model built in mtb_profile.cv_model() into a PDF or a Word file.

The model is plain data:
  {template, name, headline, contact: [..], extras: [(label, text)], signature: bool, generated: '11 Nov 2026',
   blocks: [{title, kind: 'text', text} | {title, kind: 'tags', tags: [..]} | {title, kind: 'entries', items: [{title, tag, sub, meta, text, link}]}]}
Two looks: 'professional' (left-aligned, coloured rules) and 'clinical' (centred "Curriculum Vitae" heading, shaded section bands,
signature and date lines as is usual for investigator CVs).
"""
import io
from pathlib import Path
from xml.sax.saxutils import escape

NAVY, CORAL, MUTED, RULE, BAND = '#14213D', '#D9483B', '#5B667A', '#C9CFD9', '#EEF1F6'
SIGN_TEXT = 'I confirm that the information in this curriculum vitae is accurate and current.'


# ------------------------------------------------------------------ PDF (reportlab)
_fonts = None


def pdf_fonts():
    """A Unicode font when the machine has one (names with accents print correctly); otherwise the built-in Helvetica."""
    global _fonts
    if _fonts: return _fonts
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    pairs = [('C:/Windows/Fonts/arial.ttf', 'C:/Windows/Fonts/arialbd.ttf'),
             ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'),
             ('/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf', '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf'),
             ('/Library/Fonts/Arial.ttf', '/Library/Fonts/Arial Bold.ttf'), ('/System/Library/Fonts/Supplemental/Arial.ttf', '/System/Library/Fonts/Supplemental/Arial Bold.ttf')]
    _fonts = ('Helvetica', 'Helvetica-Bold')
    for regular, bold in pairs:
        if Path(regular).is_file() and Path(bold).is_file():
            try:
                pdfmetrics.registerFont(TTFont('MTBSans', regular)); pdfmetrics.registerFont(TTFont('MTBSans-Bold', bold))
                _fonts = ('MTBSans', 'MTBSans-Bold'); break
            except Exception: continue
    return _fonts


def pdf(model):
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, KeepTogether

    regular, bold = pdf_fonts()
    clinical = model['template'] == 'clinical'
    centre = {'alignment': TA_CENTER} if clinical else {}
    P = lambda name, **kw: ParagraphStyle(name, fontName=kw.pop('font', regular), textColor=colors.HexColor(kw.pop('color', '#1F2937')), **kw)
    st = {
        'label': P('label', fontSize=8.5, leading=12, color=MUTED, alignment=TA_CENTER, spaceAfter=3),
        'name': P('name', font=bold, fontSize=21, leading=25, color=NAVY, **centre),
        'headline': P('headline', fontSize=11, leading=15, color=CORAL, spaceBefore=2, **centre),
        'contact': P('contact', fontSize=9, leading=13, color=MUTED, spaceBefore=3, **centre),
        'extra': P('extra', fontSize=9.5, leading=13.5, spaceBefore=2),
        'section': P('section', font=bold, fontSize=10.5, leading=13, color=NAVY),
        'title': P('title', font=bold, fontSize=10, leading=13.5),
        'meta': P('meta', fontSize=9, leading=13.5, color=MUTED, alignment=TA_RIGHT),
        'sub': P('sub', fontSize=9, leading=12.5, color=MUTED),
        'body': P('body', fontSize=9.5, leading=14),
        'small': P('small', fontSize=8.5, leading=12, color=MUTED),
    }
    e = lambda v: escape(str(v or ''))
    width = A4[0] - 36 * mm
    story = []
    if clinical: story.append(Paragraph('C U R R I C U L U M &nbsp; V I T A E', st['label']))
    story.append(Paragraph(e(model['name']), st['name']))
    if model['headline']: story.append(Paragraph(e(model['headline']), st['headline']))
    if model['contact']: story.append(Paragraph(' &nbsp;|&nbsp; '.join(e(x) for x in model['contact']), st['contact']))
    story.append(Spacer(1, 5))
    story.append(HRFlowable(width='100%', thickness=1.2, color=colors.HexColor(NAVY), spaceAfter=4))
    for label, value in model['extras']:
        story.append(Paragraph(f'<font name="{bold}">{e(label)}:</font> {e(value)}', st['extra']))

    def heading(title):
        if clinical:
            t = Table([[Paragraph(e(title).upper(), st['section'])]], colWidths=[width])
            t.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, -1), colors.HexColor(BAND)), ('LEFTPADDING', (0, 0), (-1, -1), 6),
                                   ('TOPPADDING', (0, 0), (-1, -1), 3), ('BOTTOMPADDING', (0, 0), (-1, -1), 4)]))
            return [Spacer(1, 11), t, Spacer(1, 5)]
        return [Spacer(1, 12), Paragraph(e(title).upper(), st['section']),
                HRFlowable(width='100%', thickness=0.6, color=colors.HexColor(RULE), spaceBefore=3, spaceAfter=5)]

    for blk in model['blocks']:
        head = heading(blk['title'])
        if blk['kind'] == 'text':
            paras = [Paragraph(e(p).replace('\n', '<br/>'), st['body']) for p in blk['text'].split('\n\n') if p.strip()]
            story.append(KeepTogether(head + paras[:1])); story.extend(paras[1:])
        elif blk['kind'] == 'tags':
            story.append(KeepTogether(head + [Paragraph(' &nbsp;·&nbsp; '.join(e(t) for t in blk['tags']), st['body'])]))
        else:
            for i, it in enumerate(blk['items']):
                title = e(it['title']) + (f' <font name="{regular}" color="{MUTED}" size="8.5">&nbsp; {e(it["tag"])}</font>' if it.get('tag') else '')
                row = Table([[Paragraph(title, st['title']), Paragraph(e(it.get('meta')), st['meta'])]], colWidths=[width * 0.72, width * 0.28])
                row.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                                         ('TOPPADDING', (0, 0), (-1, -1), 0), ('BOTTOMPADDING', (0, 0), (-1, -1), 0)]))
                parts = [row]
                if it.get('sub'): parts.append(Paragraph(e(it['sub']), st['sub']))
                if it.get('text'): parts.append(Paragraph(e(it['text']).replace('\n', '<br/>'), st['body']))
                if it.get('link'): parts.append(Paragraph(f'<link href="{e(it["link"]).replace(chr(34), "%22")}" color="{CORAL}">{e(it["link"])}</link>', st['small']))
                parts.append(Spacer(1, 6))
                story.append(KeepTogether((head if i == 0 else []) + parts))
    if model.get('signature'):
        line = Table([['Signature', '', 'Date', '']], colWidths=[20 * mm, 75 * mm, 14 * mm, 45 * mm])
        line.setStyle(TableStyle([('FONT', (0, 0), (-1, -1), regular, 9.5), ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor(MUTED)),
                                  ('LINEBELOW', (1, 0), (1, 0), 0.7, colors.HexColor('#6B7280')), ('LINEBELOW', (3, 0), (3, 0), 0.7, colors.HexColor('#6B7280')),
                                  ('LEFTPADDING', (0, 0), (-1, -1), 0), ('BOTTOMPADDING', (0, 0), (-1, -1), 2)]))
        story.append(KeepTogether([Spacer(1, 22), Paragraph(SIGN_TEXT, st['body']), Spacer(1, 26), line]))

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont(regular, 7.5); canvas.setFillColor(colors.HexColor('#8A93A3'))
        canvas.drawString(18 * mm, 10 * mm, f'Generated from My Trial Board on {model["generated"]}')
        canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f'Page {doc.page}')
        canvas.restoreState()

    out = io.BytesIO()
    doc = SimpleDocTemplate(out, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=18 * mm,
                            title=f'CV - {model["name"]}', author=model['name'], creator='My Trial Board')
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return out.getvalue()


# ------------------------------------------------------------------ Word (python-docx)
def docx(model):
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Mm, Pt, RGBColor

    clinical = model['template'] == 'clinical'
    rgb = lambda h: RGBColor.from_string(h.lstrip('#'))
    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Mm(210), Mm(297)
    sec.left_margin = sec.right_margin = Mm(18); sec.top_margin = Mm(16); sec.bottom_margin = Mm(18)
    text_width = sec.page_width - sec.left_margin - sec.right_margin
    base = doc.styles['Normal']
    base.font.name = 'Calibri'; base.font.size = Pt(10.5)
    base.element.rPr.rFonts.set(qn('w:eastAsia'), 'Calibri')
    doc.core_properties.title = f'CV - {model["name"]}'; doc.core_properties.author = model['name']

    def para(text='', size=10.5, bold=False, color=None, before=0, after=0, align=None, keep=False):
        p = doc.add_paragraph()
        f = p.paragraph_format
        f.space_before, f.space_after, f.line_spacing = Pt(before), Pt(after), 1.12
        if align == 'center': p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        if keep: f.keep_with_next = True
        if text: run(p, text, size, bold, color)
        return p

    def run(p, text, size=10.5, bold=False, color=None):
        lines = str(text).split('\n')
        for i, line in enumerate(lines):
            r = p.add_run(line)
            r.font.size = Pt(size); r.bold = bold
            if color: r.font.color.rgb = rgb(color)
            if i < len(lines) - 1: r.add_break()
        return p

    def border(p, colour, size=6, shade=None):
        pPr = p._p.get_or_add_pPr()
        if shade:
            shd = OxmlElement('w:shd'); shd.set(qn('w:val'), 'clear'); shd.set(qn('w:color'), 'auto'); shd.set(qn('w:fill'), shade.lstrip('#')); pPr.append(shd)
        else:
            box = OxmlElement('w:pBdr'); line = OxmlElement('w:bottom')
            for k, v in (('val', 'single'), ('sz', str(size)), ('space', '2'), ('color', colour.lstrip('#'))): line.set(qn('w:' + k), v)
            box.append(line); pPr.append(box)

    centre = 'center' if clinical else None
    if clinical: para('C U R R I C U L U M   V I T A E', 8.5, color=MUTED, align='center', after=2)
    para(model['name'], 22, True, NAVY, align=centre)
    if model['headline']: para(model['headline'], 11.5, color=CORAL, align=centre)
    if model['contact']: para('  |  '.join(model['contact']), 9.5, color=MUTED, align=centre, before=2)
    border(para(after=3), NAVY, 10)
    for label, value in model['extras']:
        run(run(para(), label + ': ', 10, True), value, 10)

    def heading(title):
        p = para(title.upper(), 10.5, True, NAVY, before=12, after=4, keep=True)
        border(p, RULE, 6, BAND if clinical else None)

    for blk in model['blocks']:
        heading(blk['title'])
        if blk['kind'] == 'text':
            for chunk in [c for c in blk['text'].split('\n\n') if c.strip()]: para(chunk, 10.5, after=4)
        elif blk['kind'] == 'tags':
            para('  ·  '.join(blk['tags']), 10.5)
        else:
            for it in blk['items']:
                p = para(keep=bool(it.get('sub') or it.get('text')))
                p.paragraph_format.tab_stops.add_tab_stop(text_width, WD_TAB_ALIGNMENT.RIGHT)
                run(p, it['title'], 10.5, True)
                if it.get('tag'): run(p, '   ' + it['tag'], 9, color=MUTED)
                if it.get('meta'): run(p, '\t' + it['meta'], 9.5, color=MUTED)
                if it.get('sub'): para(it['sub'], 9.5, color=MUTED, keep=bool(it.get('text')))
                if it.get('text'): para(it['text'], 10)
                if it.get('link'): para(it['link'], 9, color=CORAL)
                doc.paragraphs[-1].paragraph_format.space_after = Pt(6)
    if model.get('signature'):
        para(SIGN_TEXT, 10.5, before=22, after=24, keep=True)
        para('Signature: ______________________________          Date: ____________________', 10, color=MUTED)
    foot = sec.footer.paragraphs[0]
    run(foot, f'Generated from My Trial Board on {model["generated"]}', 8, color='#8A93A3')
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()
