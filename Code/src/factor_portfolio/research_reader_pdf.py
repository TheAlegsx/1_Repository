"""Render Times New Roman readers with black text and visible GitHub references."""
from pathlib import Path
import html
import re

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (BaseDocTemplate, PageTemplate, Frame, Paragraph,
    Spacer, Table, TableStyle, Image, NextPageTemplate, PageBreak, KeepTogether)

SOURCE = Path('.')
NAVY = colors.black
TEAL = colors.black
GREY = colors.black
MARGIN = 43

def register_fonts(directory):
    for name, filename in [('Reading', 'Times New Roman.ttf'), ('Reading-Bold', 'Times New Roman Bold.ttf'),
                           ('Reading-Italic', 'Times New Roman Italic.ttf'), ('Reading-BoldItalic', 'Times New Roman Bold Italic.ttf')]:
        path=Path(directory)/filename
        if not path.is_file():
            raise FileNotFoundError(f'Supply a font directory containing {filename}')
        pdfmetrics.registerFont(TTFont(name, str(path)))
    pdfmetrics.registerFontFamily('Reading', normal='Reading', bold='Reading-Bold', italic='Reading-Italic', boldItalic='Reading-BoldItalic')

def normalise(s):
    return s.translate(str.maketrans({'–':'-', '—':'-', '−':'-', '\u2011':'-', '\u00a0':' '}))

def inline(s):
    s = normalise(s)
    protected = []
    def hold(value):
        protected.append(value)
        return f'ZZINLINE{len(protected)-1}ZZ'
    s = re.sub(r'`([^`]+)`', lambda m: hold('<font size="9">'+html.escape(m[1])+'</font>'), s)
    def link(m):
        label, target = m[1], m[2]
        label = html.escape(label)
        if target.startswith(('https://', 'http://')):
            return hold(f'<link href="{html.escape(target, quote=True)}" color="#000000">{label}</link>')
        return hold(label)
    s = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', link, s)
    s = html.escape(s)
    s = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', s)
    s = re.sub(r'(?<!\*)\*([^*]+)\*(?!\*)', r'<i>\1</i>', s)
    for i, value in enumerate(protected):
        s = s.replace(f'ZZINLINE{i}ZZ', value)
    return s

STYLE = ParagraphStyle('Body', fontName='Reading', fontSize=11, leading=15,
                       textColor=NAVY, spaceAfter=6, splitLongWords=True,
                       bulletFontName='Reading', allowWidows=0, allowOrphans=0)
STYLES = {i: ParagraphStyle(f'H{i}', parent=STYLE, fontName='Reading-Bold',
    fontSize={1:23,2:15,3:12,4:11}.get(i,11),
    leading={1:28,2:20,3:16,4:15}.get(i,15),
    spaceBefore=12 if i>1 else 4, spaceAfter=8, keepWithNext=True) for i in range(1,7)}
CAPTION = ParagraphStyle('Caption', parent=STYLE, fontSize=9, leading=12,
                         textColor=GREY, spaceBefore=5, spaceAfter=13)
TABLE_CAPTION = ParagraphStyle('TableCaption', parent=STYLE, keepWithNext=True,
                              spaceBefore=4, spaceAfter=6)

class ReadingDocument(BaseDocTemplate):
    def __init__(self, path, title, total_pages=None, report_date="9 October 2026"):
        self.total_pages = total_pages
        self.report_date = report_date
        self.short_title = title
        self.heading_index = 0
        super().__init__(str(path), pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN,
            topMargin=51, bottomMargin=49, title=title, author='Alex Weber',
            subject=f'Research report, {report_date}', pageCompression=1)
        templates = []
        for name, size in [('portrait', A4), ('landscape', landscape(A4))]:
            w,h=size
            templates.append(PageTemplate(name, [Frame(MARGIN,49,w-2*MARGIN,h-100,
                leftPadding=0,rightPadding=0,topPadding=0,bottomPadding=0)],
                onPage=self.decorate, pagesize=size))
        self.addPageTemplates(templates)
    def decorate(self, canvas, doc):
        w,h=canvas._pagesize
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor('#CCCCCC'))
        canvas.line(MARGIN,h-33,w-MARGIN,h-33)
        canvas.setFont('Reading',8)
        canvas.setFillColor(GREY)
        canvas.drawString(MARGIN,h-24,self.short_title)
        canvas.drawRightString(w-MARGIN,h-24,f'Research report | {self.report_date}')
        canvas.drawString(MARGIN,27,self.short_title)
        canvas.drawRightString(w-MARGIN,27,f'Page {doc.page} of {self.total_pages}' if self.total_pages else str(doc.page))
        canvas.restoreState()
    def afterFlowable(self, flowable):
        if getattr(flowable,'outline_level',None) is not None:
            key=f'heading-{self.heading_index}'
            self.heading_index+=1
            self.canv.bookmarkPage(key)
            # PDF outlines use a flat section list so heading gaps cannot invalidate it.
            self.canv.addOutlineEntry(flowable.getPlainText(),key,0,False)

def table_cells(line):
    return [c.strip() for c in line.strip().strip('|').split('|')]

def convert(text, parent, story, audit, initial_orientation='portrait'):
    lines=text.splitlines(); i=0; orientation=initial_orientation
    def switch(target):
        nonlocal orientation
        if target != orientation:
            story.extend([NextPageTemplate(target),PageBreak()]);orientation=target
    while i<len(lines):
        line=lines[i].strip()
        if not line or re.fullmatch(r'<a\s+id="[^"]+"\s*></a>',line):
            i+=1;continue
        if line.startswith('|'):
            rows=[]
            while i<len(lines) and lines[i].strip().startswith('|'):
                cells=table_cells(lines[i])
                if not all(re.fullmatch(r':?-+:?',c) for c in cells):rows.append(cells)
                i+=1
            n=len(rows[0]); assert all(len(row)==n for row in rows)
            mode='landscape' if n>=7 else 'portrait'
            source_table=rows[0][0]=='Source / role'
            if source_table:mode='landscape'
            # Long multi-column financial headers need more width for reading.
            if n>=5 and sum(len(c) for c in rows[0])>160:mode='landscape'
            # The section heading chooses page orientation, so table notes and
            # neighbouring tables remain together instead of creating sparse pages.
            mode=orientation
            width=(landscape(A4)[0] if mode=='landscape' else A4[0])-2*MARGIN
            size=9.3 if mode=='landscape' else 9
            cell_style=ParagraphStyle('Cell',parent=STYLE,fontSize=size,leading=size+2,
                spaceAfter=0,spaceBefore=0)
            # Weight text columns by typical content, rather than the longest outlier.
            weights=[]
            for col in range(n):
                lens=sorted(len(re.sub(r'\[([^]]+)\]\([^)]+\)',r'\1',r[col])) for r in rows)
                typical=lens[min(len(lens)-1,int(len(lens)*.75))]
                weights.append(max(9,min(42,typical**.75+len(rows[0][col])**.55)))
            widths=[width*x/sum(weights) for x in weights]
            if source_table:widths=[180,170,100,width-450]
            parameter_table = rows[0] == ['Parameter', 'Selected value']
            numeric_pattern = re.compile(r'(?:USD )?[-+±]?\d[\d,.]*(?:%| pp| bp|x|/\d+)?')
            numeric_columns = [
                not parameter_table and all(numeric_pattern.fullmatch(row[col]) for row in rows[1:])
                for col in range(n)
            ]
            numeric_style = ParagraphStyle('NumericCell', parent=cell_style, alignment=TA_RIGHT)
            paragraphs=[]
            for r, row in enumerate(rows):
                formatted=[]
                for col, c in enumerate(row):
                    style = numeric_style if numeric_columns[col] else cell_style
                    rendered = ('<b>'+inline(c)+'</b>') if r==0 else inline(c)
                    if r>0 and len(rows[0])>1 and rows[0][1].startswith('Annual client equivalents') and len(formatted)==1:
                        rendered = '<font name="Courier" size="8.5">' + html.escape(c).replace(' ', '&#160;') + '</font>'
                    formatted.append(Paragraph(rendered,style))
                paragraphs.append(formatted)
            t=Table(paragraphs,colWidths=widths,repeatRows=1,hAlign='LEFT',splitByRow=1)
            t.setStyle(TableStyle([
                ('BACKGROUND',(0,0),(-1,0),colors.HexColor('#EEEEEE')),
                ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#F8F8F8')]),
                ('LINEBELOW',(0,0),(-1,0),.7,TEAL),
                ('LINEBELOW',(0,1),(-1,-1),.25,colors.HexColor('#DDDDDD')),
                ('VALIGN',(0,0),(-1,-1),'TOP'),
                ('LEFTPADDING',(0,0),(-1,-1),6),('RIGHTPADDING',(0,0),(-1,-1),6),
                ('TOPPADDING',(0,0),(-1,-1),4),('BOTTOMPADDING',(0,0),(-1,-1),4)]))
            # Keep a short comparison table with its first explanatory paragraph.
            j=i
            while j<len(lines) and not lines[j].strip():j+=1
            following=[]
            if len(rows)<=4 and j<len(lines) and not re.match(r'^(#|\||!\[|<|\*\*Table)', lines[j].strip()):
                while j<len(lines) and lines[j].strip():
                    if re.match(r'^(#|\||!\[|<)', lines[j].strip()):break
                    following.append(lines[j].strip());j+=1
            if following:
                paragraph=Paragraph(inline(' '.join(following)), STYLE)
                group=[t,Spacer(1,7),paragraph]
                if story and isinstance(story[-1],Paragraph) and story[-1].style.name=='TableCaption':
                    group.insert(0,story.pop())
                story.append(KeepTogether(group));i=j
            else:
                story.extend([t,Spacer(1,7)])
            audit['tables']+=1; audit['table_cells']+=sum(map(len,rows))
            audit['table_values'].extend(c for row in rows for c in row)
            continue
        heading=re.match(r'^(#{1,6})\s+(.*)$',line)
        if heading:
            level=len(heading[1])
            target=orientation
            if level==2 or heading[2].startswith('Appendix ') or heading[2]=='Sources and Download Evidence':
                target='portrait'
                for subsequent in lines[i+1:]:
                    nextheading=re.match(r'^(#{1,6})\s+',subsequent)
                    if nextheading and len(nextheading[1])<=level:break
                    if subsequent.strip().startswith('|'):
                        cells=table_cells(subsequent)
                        if len(cells)>=7 or cells[0]=='Source / role' or (len(cells)>=5 and sum(map(len,cells))>160):
                            target='landscape';break
                # Begin references on a clean page, and retain the section/subsection
                # heading chain with a following short table rather than orphaning it.
                if heading[2] == 'Sources and Data' and target == orientation and story:
                    story.append(PageBreak())
                switch(target)
            p=Paragraph(inline(heading[2]),STYLES[len(heading[1])])
            if len(heading[1])<=2:p.outline_level=0
            story.append(p);i+=1;continue
        img=re.fullmatch(r'!\[([^]]*)\]\(([^)]+)\)',line)
        if img:
            path=(parent/img[2]).resolve();assert path.is_file(),path
            from PIL import Image as PILImage
            with PILImage.open(path) as im:w,h=im.size
            framewidth=(landscape(A4)[0] if orientation=='landscape' else A4[0])-2*MARGIN
            scale=min(framewidth/w,(380 if orientation=='landscape' else 470)/h)
            figure=Image(str(path),width=w*scale,height=h*scale)
            figure.keepWithNext=True
            gap=Spacer(1,7);gap.keepWithNext=True
            story.extend([figure,gap])
            audit['images'].append(str(path.relative_to(SOURCE)))
            i+=1;continue
        parts=[line];i+=1
        if line=='---':
            story.append(Spacer(1,10));continue
        while i<len(lines) and lines[i].strip() and not re.match(r'^(#{1,6}\s|\||!\[|<a\s)',lines[i].strip()):
            # Preserve standalone list entries without merging numbering.
            if re.match(r'^([-*]|\d+\.)\s',lines[i].strip()):break
            parts.append(lines[i].strip());i+=1
        paragraph=' '.join(parts)
        bullet=re.match(r'^([-*]|\d+\.)\s+(.*)',paragraph)
        if bullet:
            paragraph=bullet[2]
            bs=ParagraphStyle('List',parent=STYLE,leftIndent=16,bulletIndent=0)
            story.append(Paragraph(inline(paragraph),bs,bulletText='-' if bullet[1] in '-*' else bullet[1]))
        else:
            following = next((item.strip() for item in lines[i:] if item.strip()), '')
            is_table_label = (re.match(r'^\*\*Table\s', paragraph)
                or (re.fullmatch(r'\*\*[^*]+\*\*', paragraph) and following.startswith('|')))
            style = TABLE_CAPTION if is_table_label else CAPTION if paragraph.startswith('*Figure ') else STYLE
            story.append(Paragraph(inline(paragraph),style))

