"""Render Times New Roman readers with black text and visible GitHub references."""
from pathlib import Path
from collections import Counter
import hashlib
import html
import json
import re

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (BaseDocTemplate, PageTemplate, Frame, Paragraph,
    Spacer, Table, TableStyle, Image, NextPageTemplate, PageBreak, KeepTogether)
from pypdf import PdfReader

SOURCE = Path('.')
SPECS = [
    ('report/BACKTEST_RESEARCH_2026-10-07.md',
     'MSCI_World_Factor_Strategy_Backtest.pdf', 'Portfolio backtest'),
    ('report/CAPITAL_INFLOWS_RESEARCH_2026-10-07.md',
     'Capital_Inflows_Fund_Economics.pdf', 'Capital inflows and fund economics')]
LINK_MAP = {Path(src).name: name for src, name, _ in SPECS}
LINK_MAP['ai_use_record.md'] = 'AI_USE_RECORD_2026-10-06.md'
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
            if target.startswith('https://github.com/TheAlegsx/1_Repository/blob/'):
                return hold(f'<link href="{html.escape(target, quote=True)}" color="#1e4d78">'
                            f'<font size="9" backColor="#edf4fa"><u>{label}</u></font></link>')
            return hold(f'<link href="{html.escape(target, quote=True)}" color="#000000">{label}</link>')
        if Path(target).name == 'source_register.md':
            return hold(f'<link href="#source-register" color="#000000">{label}</link>')
        if Path(target).name in LINK_MAP:
            return hold(f'<link href="{LINK_MAP[Path(target).name]}" color="#000000">{label}</link>')
        return hold(label)
    s = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', link, s)
    s = html.escape(s)
    s = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', s)
    s = re.sub(r'(?<!\*)\*([^*]+)\*(?!\*)', r'<i>\1</i>', s)
    for i, value in enumerate(protected):
        s = s.replace(f'ZZINLINE{i}ZZ', value)
    return s

STYLE = ParagraphStyle('Body', fontName='Reading', fontSize=11, leading=15,
                       textColor=NAVY, spaceAfter=8, splitLongWords=True,
                       bulletFontName='Reading', allowWidows=0, allowOrphans=0)
STYLES = {i: ParagraphStyle(f'H{i}', parent=STYLE, fontName='Reading-Bold',
    fontSize={1:23,2:15,3:12,4:11}.get(i,11),
    leading={1:28,2:20,3:16,4:15}.get(i,15),
    spaceBefore=15 if i>1 else 4, spaceAfter=10, keepWithNext=True) for i in range(1,7)}
CAPTION = ParagraphStyle('Caption', parent=STYLE, fontSize=9, leading=12,
                         textColor=GREY, spaceBefore=5, spaceAfter=13)
TABLE_CAPTION = ParagraphStyle('TableCaption', parent=STYLE, keepWithNext=True,
                              spaceBefore=4, spaceAfter=6)

class ReadingDocument(BaseDocTemplate):
    def __init__(self, path, title):
        self.short_title = title
        self.heading_index = 0
        super().__init__(str(path), pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN,
            topMargin=51, bottomMargin=49, title=title, author='Alex Weber',
            subject='Research report, 7 October 2026', pageCompression=1)
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
        canvas.drawRightString(w-MARGIN,h-24,'Research report | 7 October 2026')
        canvas.drawString(MARGIN,27,'Research report | Sources and calculation materials recorded')
        canvas.drawRightString(w-MARGIN,27,str(doc.page))
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
            cell_style=ParagraphStyle('Cell',parent=STYLE,fontSize=size,leading=size+3,
                spaceAfter=0,spaceBefore=0)
            # Weight text columns by typical content, rather than the longest outlier.
            weights=[]
            for col in range(n):
                lens=sorted(len(re.sub(r'\[([^]]+)\]\([^)]+\)',r'\1',r[col])) for r in rows)
                typical=lens[min(len(lens)-1,int(len(lens)*.75))]
                weights.append(max(9,min(42,typical**.75+len(rows[0][col])**.55)))
            widths=[width*x/sum(weights) for x in weights]
            if source_table:widths=[180,170,100,width-450]
            paragraphs=[[Paragraph(('<b>'+inline(c)+'</b>') if r==0 else inline(c),cell_style)
                         for c in row] for r,row in enumerate(rows)]
            t=Table(paragraphs,colWidths=widths,repeatRows=1,hAlign='LEFT',splitByRow=1)
            t.setStyle(TableStyle([
                ('BACKGROUND',(0,0),(-1,0),colors.HexColor('#EEEEEE')),
                ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#F8F8F8')]),
                ('LINEBELOW',(0,0),(-1,0),.7,TEAL),
                ('LINEBELOW',(0,1),(-1,-1),.25,colors.HexColor('#DDDDDD')),
                ('VALIGN',(0,0),(-1,-1),'TOP'),
                ('LEFTPADDING',(0,0),(-1,-1),6),('RIGHTPADDING',(0,0),(-1,-1),6),
                ('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),6)]))
            if len(rows)<=8:
                group=[t]
                if story and isinstance(story[-1],Paragraph) and story[-1].style.name=='TableCaption':
                    group.insert(0,story.pop())
                while story and isinstance(story[-1],Paragraph) and story[-1].style.name.startswith('H'):
                    group.insert(0,story.pop())
                story.extend([KeepTogether(group),Spacer(1,10)])
            else:story.extend([t,Spacer(1,10)])
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

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def render_readers(source, destination, font_directory):
    global SOURCE
    from .security_io import require_runtime
    require_runtime()
    from .inflow_workflow import verify_run
    from .research_reader_reports import inventory, write_json, copy_bytes
    SOURCE=Path(source).resolve();destination=Path(destination).resolve()
    verify_run(SOURCE)
    if destination.exists():raise FileExistsError('Choose a new PDF destination')
    register_fonts(font_directory)
    before=inventory(SOURCE);records=[]
    destination.mkdir(parents=True)
    ai_record = SOURCE / 'evidence/ai_use_record.md'
    copy_bytes(ai_record, destination / LINK_MAP['ai_use_record.md'])
    for src,name,title in SPECS:
        path=SOURCE/src;story=[]
        audit={'tables':0,'table_cells':0,'table_values':[],'images':[]}
        convert(path.read_text(),path.parent,story,audit)
        output=destination/name
        ReadingDocument(output,title).build(story)
        pdf=PdfReader(output)
        extracted=normalise('\n'.join(page.extract_text() or '' for page in pdf.pages))
        numbers=lambda s:Counter(re.findall(r'(?<![A-Za-z])[-+]?\d[\d,]*(?:\.\d+)?%?',s))
        visible_cells=re.sub(r'\[([^\]]+)\]\(([^)]+)\)',r'\1',' '.join(audit['table_values']))
        missing=numbers(normalise(visible_cells))-numbers(extracted)
        if missing:raise ValueError(f'PDF numerical table tokens missing: {dict(missing)}')
        image_count=sum(len(page.images) for page in pdf.pages)
        if image_count!=len(audit['images']):raise ValueError('PDF figure count differs')
        if "This declaration concerns Alex's research contribution." not in (pdf.pages[-1].extract_text() or ''):
            raise ValueError('Final PDF page must contain the end of the AI declaration')
        records.append(dict(file=name,sha256=sha(output),source=src,source_sha256=sha(path),
            pages=len(pdf.pages),tables=audit['tables'],figures=image_count,
            table_numeric_tokens_checked=True,final_page_ai_disclosure=True,
            landscape_pages=[i+1 for i,p in enumerate(pdf.pages) if float(p.mediabox.width)>float(p.mediabox.height)]))
    if inventory(SOURCE)!=before:raise RuntimeError('Reader source changed during PDF rendering')
    write_json(destination/'pdf_manifest.json',dict(source_run_id=json.loads((SOURCE/'run_manifest.json').read_text())['run_id'],
        reports=records,font='Times New Roman',document_text='black body; blue, underlined GitHub reference links with pale blue background',font_files_sha256={p.name:sha(p) for p in Path(font_directory).glob('Times New Roman*.ttf')},
        source_files_unchanged=len(before),renderer_sha256=sha(Path(__file__)),visual_review='pending',
        accompanying_ai_record=dict(file=LINK_MAP['ai_use_record.md'],sha256=sha(ai_record)),
        scope='Curated research readers; original chart bitmaps preserved. Detailed evidence is retained separately, not bundled into PDFs.'))
    print(json.dumps(records,indent=2))
    return records


def main():
    import argparse
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--font-directory',type=Path,default=Path('/System/Library/Fonts/Supplemental'))
    a=p.parse_args();render_readers(a.source,a.output,a.font_directory)

if __name__=='__main__':main()
