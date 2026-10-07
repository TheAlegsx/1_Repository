"""Dimensional common-stock schedules with a separate PDF layout reader."""
from __future__ import annotations

from collections import Counter
from datetime import date
import importlib.metadata
from pathlib import Path
import re

import pandas as pd

from .backtest_annual_holdings import PDF_VERSION, COUNTRY_COLUMNS, require_reader, admit_sources as admit_pdf_sources
from .inflow_workflow import sha256

LAYOUT_VERSIONS = {'pdfplumber':'0.11.9','pdfminer.six':'20251230','pypdfium2':'5.13.0',
                   'Pillow':'12.3.0','charset-normalizer':'3.5.1','cryptography':'50.0.2','cffi':'2.1.1','pycparser':'3.0'}
MEASUREMENT = dict(fund='dimensional', identity='Global Core Equity Fund', scope='Common Stock only',
    currency='USD', value_units='USD thousands', shares_units='000',
    weights='line fair value divided by disclosed fund NAV',
    rounding_tolerance='(security lines + 1) * 0.5 + 1 USD thousands',
    country_percent_tolerance_base=.006, top_positions=10,
    layout_boxes=[[0,100,305,790],[305,100,597,790]],layout_x_tolerance=1,
    second_reader='shares/value/reported-weight multiset by physical stock-containing page',
    synchronize_snapshots=False, sector_attribution=False)


def require_layout_reader():
    require_reader()
    for package,version in LAYOUT_VERSIONS.items():
        try:observed = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            raise ValueError('Dimensional extraction requires the pinned optional layout-pdf extra') from None
        if observed != version:raise ValueError('layout PDF dependency version differs from declared contract: '+package)
    return dict(LAYOUT_VERSIONS)


def validate_settings(settings,baseline):
    if settings['schema_version'] != 1 or settings['measurement'] != MEASUREMENT:
        raise ValueError('unsupported Dimensional holdings contract')
    reports = settings['reports']
    if not reports or len({r['path'] for r in reports}) != len(reports) or len({r['snapshot_date'] for r in reports}) != len(reports):
        raise ValueError('Dimensional annual paths and dates must be distinct')
    for r in reports:
        d = date.fromisoformat(r['snapshot_date'])
        if (d.month,d.day) != (11,30) or d > date.fromisoformat(baseline['periods']['full']['end']):
            raise ValueError('Dimensional snapshot requires November year end before backtest cutoff')
        if Path(r['path']).name != f'dimensional_annual_{d.year}.pdf' or r['fund_identity'] != MEASUREMENT['identity']:
            raise ValueError('Dimensional filename/date/subfund mismatch')
        for field in ['pages_1based','layout_pages_1based']:
            p = r[field]
            if not p or any(type(v) is not int or v < 1 for v in p) or p != list(range(p[0],p[-1]+1)):
                raise ValueError('Dimensional physical pages must be positive and contiguous')
        if not set(r['layout_pages_1based']).issubset(r['pages_1based']):
            raise ValueError('second-reader stock pages must lie within the primary schedule')
        if r['expected_holdings'] < 1 or r['expected_country_groups'] < 1:
            raise ValueError('Dimensional counts must be positive')


def admit_sources(raw_root,settings):
    return admit_pdf_sources(raw_root,settings)


def number(text):
    return 0. if str(text) == '-' else float(str(text).replace(',',''))


def parse_common_stock(texts,report):
    num = r'(?:[0-9][0-9,]*|-)';pct = r'(?:[0-9]+\.[0-9]+|-)'
    whole = ' '.join(' '.join(t.split()) for _,t in texts)
    nav_match = re.search(r'Total Net Assets\s+([\d,]+)\s+100\.00',whole)
    if not nav_match or number(nav_match[1]) <= 0:raise ValueError('Dimensional positive disclosed USD NAV missing')
    nav = number(nav_match[1]);active = False;country = None;pending = '';total = None
    stocks = [];countries = {};repairs = []
    for page,text in texts:
        for raw in text.splitlines():
            line = re.sub(r'\s+',' ',raw.replace('^','').replace('*','').strip()).strip()
            if report['snapshot_date']=='2025-11-30' and page==223 and line=='2R H 3 6 7 -':
                repairs.append(dict(page=page,before=line,after='2 RH 367 -',basis='Preserved character-spacing correction; independent layout reader must confirm numeric tuple.'))
                line = '2 RH 367 -'
            if total is None and line.startswith('Common Stock'):active = True;continue
            end = re.match(r'Total Common Stock\s*-\s*([\d.]+)%.*?\s('+num+r')\s('+pct+r')$',line)
            if end:
                if pending:raise ValueError('unparsed Dimensional stock before common-stock total')
                total = number(end[2]);active = False;continue
            if line.startswith(('Warrants','Rights','Preferred Stock','Exchange traded','Forward Currency','Financial derivative','Over-the-counter')):
                if pending:raise ValueError('unparsed Dimensional stock at asset-class boundary')
                active = False
            if not active:continue
            heading = re.match(r'^(.+?) - ([\d.]+)%',line)
            if heading and not heading[1].startswith(('Total','Common')):
                if pending:raise ValueError(f'unparsed Dimensional stock before country heading on physical page {page}: {pending}')
                country = heading[1];countries.setdefault(country,dict(country=country,reported_weight_pct=float(heading[2]),page=page));continue
            # Unnamed country subtotal: only value and percentage, no shares or
            # security name. The original parser discarded it at the heading.
            if not pending and re.fullmatch(num+r'\s+'+pct,line):continue
            start = bool(re.match(r'^[\d,-]+ [A-Za-z0-9]',line))
            if pending:
                # Continued company names can begin with a year (e.g. 2006
                # Ltd.); preserve the legacy join rather than guessing shares.
                if line.startswith(('Currency','Fair value','USD','%o','asset','value','Shares','Portfolio','Dimensional','iSHARES','SCHEDULE','As at','NM','[')):continue
                pending += ' '+line
            elif start:pending = line
            if pending:
                match = re.match(r'^([\d,-]+) (.+?)\s+('+num+r')\s+('+pct+r')$',pending)
                if match:
                    if country is None:raise ValueError('Dimensional common stock lacks country context')
                    fair = number(match[3])
                    stocks.append(dict(fund='dimensional',snapshot_date=report['snapshot_date'],name=match[2],country=country,
                        currency=None,shares_reported=match[1],shares_units='000',fair_value_000_usd=fair,
                        reported_weight_pct=number(match[4]),reconstructed_weight=fair/nav,pdf_page=page,source_file=Path(report['path']).name))
                    pending = ''
    if pending or total is None or len(stocks)!=report['expected_holdings'] or len(countries)!=report['expected_country_groups']:
        raise ValueError('Dimensional extraction incomplete or counts differ from contract')
    extracted = sum(r['fair_value_000_usd'] for r in stocks);allowed = (len(stocks)+1)*.5+1
    if abs(extracted-total)>allowed:raise ValueError('Dimensional common-stock residual exceeds disclosed rounding tolerance')
    country_rows = []
    for row in countries.values():
        own = sum(r['fair_value_000_usd'] for r in stocks if r['country']==row['country'])
        if abs(own/nav*100-row['reported_weight_pct'])>.006+len(stocks)*.5/nav*100:
            raise ValueError('Dimensional country percentage exceeds rounding tolerance')
        row.update(fund='dimensional',snapshot_date=report['snapshot_date'],source_file=Path(report['path']).name,
            nav_000_usd=nav,reconstructed_value_000_usd=own,reconstructed_weight=own/nav);country_rows.append(row)
    summary = dict(fund='dimensional',snapshot_date=report['snapshot_date'],source_file=Path(report['path']).name,
        pages_1based=','.join(map(str,report['pages_1based'])),nav_000_usd=nav,reported_equity_value_000_usd=total,
        extracted_equity_value_000_usd=extracted,difference_000_usd=extracted-total,rounding_tolerance_000_usd=allowed,
        equity_weight=total/nav,holdings=len(stocks),country_groups=len(countries),
        top10_security_line_weight=sum(sorted((r['reconstructed_weight'] for r in stocks),reverse=True)[:10]))
    return stocks,country_rows,summary,repairs


def parse_layout_lines(lines,active=False):
    rows = [];pending = ''
    for line in lines:
        if line.startswith('Total Common Stock'):active=False;pending='';continue
        if line.startswith('Common Stock'):active=True;continue
        if not active:continue
        if re.match(r'^.+? - [0-9.]+%',line):pending='';continue
        if not pending and re.match(r'^[0-9,-]+ [A-Za-z0-9]',line):pending=line
        elif pending:pending += ' '+line
        if pending:
            match = re.match(r'^([0-9,-]+) (.+?) ([0-9,]+|-) ([0-9.]+|-)$',pending)
            if match:
                rows.append(dict(name=match[2],shares=number(match[1]),value=number(match[3]),weight=number(match[4])));pending=''
    return rows,active


def compare_page(primary,layout,year,page):
    expected = Counter((number(r.shares_reported),r.fair_value_000_usd,r.reported_weight_pct) for r in primary.itertuples())
    observed = Counter((r['shares'],r['value'],r['weight']) for r in layout)
    missing = list((expected-observed).elements());extra = list((observed-expected).elements())
    check = dict(year=year,page=page,pypdf_count=len(primary),layout_count=len(layout),missing=missing,extra=extra)
    if missing or extra:raise ValueError(f'independent layout numeric tuples disagree on {year} physical page {page}')
    return check


def verify_layout(raw_root,settings,holdings):
    import pdfplumber
    paths = admit_sources(raw_root,settings);checks = [];allrows = []
    for report in settings['reports']:
        snapshot = report['snapshot_date'];year = date.fromisoformat(snapshot).year
        target = holdings[holdings.snapshot_date==snapshot]
        pages = list(range(int(target.pdf_page.min()),int(target.pdf_page.max())+1))
        if pages != report['layout_pages_1based']:raise ValueError('Dimensional stock-page span differs from second-reader contract')
        active = False
        with pdfplumber.open(paths[snapshot]) as pdf:
            for page in pages:
                rows = []
                for box in MEASUREMENT['layout_boxes']:
                    text = pdf.pages[page-1].crop(tuple(box)).extract_text(x_tolerance=MEASUREMENT['layout_x_tolerance']) or ''
                    parsed,active = parse_layout_lines(text.splitlines(),active)
                    rows.extend(parsed);allrows.extend(dict(year=year,page=page,**row) for row in parsed)
                checks.append(compare_page(target[target.pdf_page==page],rows,year,page))
    return pd.DataFrame(allrows),checks


def build_dimensional_study(raw_root,settings,output):
    require_layout_reader()
    from pypdf import PdfReader
    paths = admit_sources(raw_root,settings);destination = Path(output)/'annual_dimensional'
    (destination/'extracted_pages').mkdir(parents=True);stocks=[];countries=[];summaries=[];pages=[];repairs=[]
    for report in settings['reports']:
        reader = PdfReader(paths[report['snapshot_date']]);texts=[]
        for page in report['pages_1based']:
            if page>len(reader.pages):raise ValueError('Dimensional schedule page outside PDF')
            text = reader.pages[page-1].extract_text();norm=' '.join(text.split()).upper()
            expected = f"Portfolio of Investments as at 30 November {date.fromisoformat(report['snapshot_date']).year}".upper()
            if MEASUREMENT['identity'].upper() not in norm or expected not in norm or 'DIMENSIONAL FUNDS PLC' not in norm:
                raise ValueError('Dimensional PDF page subfund/date/author identity mismatch')
            target = destination/'extracted_pages'/f"{Path(report['path']).stem}_page_{page}.txt";target.write_text(text,encoding='utf-8')
            pages.append(dict(source_file=Path(report['path']).name,physical_page_1based=page,text_sha256=sha256(target),snapshot_date=report['snapshot_date']))
            texts.append((page,text))
        h,c,s,fixes = parse_common_stock(texts,report);stocks.extend(h);countries.extend(c);summaries.append(s);repairs.extend(fixes)
    holdings=pd.DataFrame(stocks);country=pd.DataFrame(countries).reindex(columns=COUNTRY_COLUMNS);summary=pd.DataFrame(summaries)
    for name,frame in [('historical_equity_holdings.csv',holdings),('historical_country_exposures.csv',country),('historical_snapshot_summary.csv',summary)]:
        frame.to_csv(destination/name,index=False,lineterminator='\n')
    # In the original mixed ETF/Dimensional table this label column contained
    # both "units" and "000". Preserve "000" as text in the isolated panel.
    ph=pd.read_csv(destination/'historical_equity_holdings.csv',dtype={'shares_units':str});pc=pd.read_csv(destination/'historical_country_exposures.csv');ps=pd.read_csv(destination/'historical_snapshot_summary.csv')
    us=pc[pc.country=='United States'][['fund','snapshot_date','reconstructed_weight']].rename(columns={'reconstructed_weight':'us_equity_weight_of_nav'})
    concentration=ps.merge(us,on=['fund','snapshot_date'],validate='one_to_one')
    if len(concentration)!=len(summary):raise ValueError('Dimensional US geography missing')
    top=ph.sort_values(['fund','snapshot_date','reconstructed_weight'],ascending=[True,True,False]).groupby(['fund','snapshot_date']).head(10)
    layout,checks=verify_layout(raw_root,settings,ph)
    admit_sources(raw_root,settings)
    return dict(frames={'historical_equity_holdings.csv':holdings,'historical_country_exposures.csv':country,
        'historical_snapshot_summary.csv':summary,'historical_concentration_summary.csv':concentration,
        'historical_top10_security_lines.csv':top,'dimensional_second_reader_rows.csv':layout},checks=checks,
        definitions=dict(measurement=MEASUREMENT,sources=settings['reports'],extracted_pages=pages,character_spacing_repairs=repairs,
            reader_versions={'pypdf':PDF_VERSION,**LAYOUT_VERSIONS},csv_precision='Full-float extraction; derived views use original fresh CSV/default pandas float reader, with shares_units label kept as text.',
            second_reader_scope='Numeric shares/value/reported-weight tuples by page, preserving multiplicities; not independent name/country/ISIN or unrounded-books validation.',
            interpretation=settings['interpretation'],independent_of_backtest_policy=True))
