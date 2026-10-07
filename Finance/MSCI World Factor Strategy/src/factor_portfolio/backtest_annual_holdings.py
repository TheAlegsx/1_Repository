"""Historical Core equity schedules reconstructed directly from admitted annual PDFs."""
from __future__ import annotations

from datetime import date
import importlib.metadata
from pathlib import Path
import re

import pandas as pd

from .inflow_workflow import sha256
from .security_io import require_runtime, bounded_input

PDF_VERSION = '6.19.0'
FUND_NAME = 'iShares Core MSCI World UCITS ETF'
MEASUREMENT = dict(fund='core', scope='Equities only', currency='USD',
    value_units='USD thousands', shares_units='units', weights='fair value divided by disclosed fund NAV',
    equity_total='exact published equity value', country_totals='exact published country values',
    rounding_tolerance='(security lines + 1) * 0.5 + 1 USD thousands',
    country_percent_tolerance_base=.006, country_percent_precision='0.01 percentage points',
    top_positions=10, sector_attribution=False, synchronize_snapshots=False)
COUNTRY_COLUMNS = ['country', 'reported_weight_pct', 'page', 'fund', 'snapshot_date', 'source_file',
    'nav_000_usd', 'reconstructed_value_000_usd', 'reconstructed_weight', 'reported_value_000_usd']


def require_reader():
    require_runtime()
    try:
        version = importlib.metadata.version('pypdf')
    except importlib.metadata.PackageNotFoundError:
        raise ValueError('annual PDF reconstruction requires the optional pinned pdf extra') from None
    if version != PDF_VERSION:
        raise ValueError('annual PDF reader version must match the declared optional dependency')
    return version


def validate_settings(settings, baseline):
    if settings['schema_version'] != 1 or settings['measurement'] != MEASUREMENT:
        raise ValueError('unsupported historical Core holdings contract')
    reports = settings['reports']
    if not reports or len({r['snapshot_date'] for r in reports}) != len(reports) or len({r['path'] for r in reports}) != len(reports):
        raise ValueError('annual snapshots and PDF paths must be distinct')
    for r in reports:
        d = date.fromisoformat(r['snapshot_date'])
        if d.month != 6 or d.day != 30 or d > date.fromisoformat(baseline['periods']['full']['end']):
            raise ValueError('historical Core snapshot must be a June year end within the backtest cutoff')
        if Path(r['path']).name != f'ishares_iii_annual_{d.year}.pdf' or r['fund_identity'] != FUND_NAME:
            raise ValueError('annual report identity/date/filename mismatch')
        pages = r['pages_1based']
        if not pages or any(type(p) is not int or p < 1 for p in pages) or pages != list(range(pages[0], pages[-1]+1)):
            raise ValueError('annual schedule pages must be positive contiguous physical PDF pages')
        if r['expected_holdings'] < 1 or r['expected_country_groups'] < 1:
            raise ValueError('annual schedule counts must be positive')


def admit_sources(raw_root, settings):
    root = Path(raw_root).resolve();paths = {}
    for r in settings['reports']:
        path = (root/r['path']).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError('annual PDF missing or outside declared raw root')
        bounded_input(path)
        if sha256(path) != r['sha256']:
            raise ValueError('annual PDF checksum mismatch')
        if path.read_bytes()[:5] != b'%PDF-':
            raise ValueError('admitted annual report is not a PDF')
        paths[r['snapshot_date']] = path
    return paths


def parse_core_schedule(texts, report):
    """Preserve the legacy ETF line grammar and source taxonomy, with explicit failures."""
    num = r'(?:[0-9][0-9,]*|-)';pct = r'(?:[0-9]+\.[0-9]+|-)'
    def value(s):return 0. if s == '-' else float(s.replace(',', ''))
    whole = ' '.join(' '.join(text.split()) for _, text in texts)
    nav_match = re.search(r'Net asset value attributable to redeemable\s+shareholders(?: at the end of the financial year)?\s+([\d,]+)\s+100\.00', whole)
    if not nav_match or value(nav_match[1]) <= 0:
        raise ValueError('annual schedule needs disclosed positive USD fund NAV')
    nav = value(nav_match[1])
    fallback = re.search(r'Total transferable securities admitted to an official stock exchange\s+listing(?: and dealt in on another regulated market)?\s+([\d,]+)\s+[\d.]+', whole)
    state = False;country = None;pending = '';stocks = [];countries = {};total = None
    for page, text in texts:
        for raw in text.splitlines():
            line = re.sub(r'\s+', ' ', raw.replace('^', '').replace('*', '').strip()).strip()
            if line.startswith('Total transferable securities admitted') and total is None and fallback:
                if pending:raise ValueError('unparsed equity line before schedule total')
                total = value(fallback[1]);state = False;continue
            if total is None and line.startswith('Equities'):
                state = True;continue
            end = re.match(r'Total (?:investments in )?Equities\s+('+num+r')\s+('+pct+r')$', line, re.I)
            if end:
                if pending:raise ValueError('unparsed equity line before equity total')
                total = value(end[1]);state = False;continue
            if line.startswith(('Warrants', 'Rights', 'Preferred Stock', 'Exchange traded', 'Forward Currency', 'Financial derivative', 'Over-the-counter')):
                if pending:raise ValueError('unparsed equity line at asset-class boundary')
                state = False
            if not state:continue
            heading = re.match(r'^(.+?) \((?:31 May|30 June) \d{4}:', line)
            if heading and not heading[1].startswith(('Transferable', 'Equities')):
                if pending:raise ValueError('unparsed equity line before country heading')
                country = heading[1];continue
            heading = re.match(r'^([A-Za-z ]+) \(continued\)$', line)
            if heading and not heading[1].startswith(('Equities', 'Transferable')):
                country = heading[1];continue
            subtotal = re.match(r'^Total (.+?)\s+('+num+r')\s+('+pct+r')$', line)
            if subtotal:
                if pending:raise ValueError('unparsed equity line before country subtotal')
                countries[subtotal[1]] = dict(country=subtotal[1], reported_weight_pct=value(subtotal[3]),
                    reported_value_000_usd=value(subtotal[2]), page=page)
                continue
            start = bool(re.match(r'^[A-Z]{3} [\d,]+ ', line))
            if pending:
                if start:raise ValueError('unparsed equity line before next security line')
                if line.startswith(('Currency', 'Fair value', 'USD', '%o', 'asset', 'value', 'Shares', 'Portfolio', 'Dimensional', 'iSHARES', 'SCHEDULE', 'As at', 'NM', '[')):
                    continue
                pending += ' '+line
            elif start:
                pending = line
            if pending:
                match = re.match(r'^([A-Z]{3}) ([\d,]+) (.+?)\s+('+num+r')\s+('+pct+r')$', pending)
                if match:
                    if country is None:raise ValueError('equity security line has no country heading')
                    fv = value(match[4])
                    stocks.append(dict(fund='core', snapshot_date=report['snapshot_date'], name=match[3],
                        country=country, currency=match[1], shares_reported=match[2], shares_units='units',
                        fair_value_000_usd=fv, reported_weight_pct=value(match[5]), reconstructed_weight=fv/nav,
                        pdf_page=page, source_file=Path(report['path']).name))
                    pending = ''
    if pending or total is None or len(stocks) != report['expected_holdings'] or len(countries) != report['expected_country_groups']:
        raise ValueError('annual schedule incomplete or counts differ from admitted reference')
    extracted = sum(r['fair_value_000_usd'] for r in stocks)
    if extracted != total:
        raise ValueError('historical ETF equity values do not equal published total')
    country_rows = []
    for row in countries.values():
        own = sum(r['fair_value_000_usd'] for r in stocks if r['country'] == row['country'])
        if own != row['reported_value_000_usd']:
            raise ValueError('historical ETF country values do not equal published subtotal')
        if abs(own/nav*100-row['reported_weight_pct']) > .006+len(stocks)*.5/nav*100:
            raise ValueError('historical country percentage exceeds published rounding tolerance')
        row.update(fund='core', snapshot_date=report['snapshot_date'], source_file=Path(report['path']).name,
            nav_000_usd=nav, reconstructed_value_000_usd=own, reconstructed_weight=own/nav)
        country_rows.append(row)
    summary = dict(fund='core', snapshot_date=report['snapshot_date'], source_file=Path(report['path']).name,
        pages_1based=','.join(map(str, report['pages_1based'])), nav_000_usd=nav,
        reported_equity_value_000_usd=total, extracted_equity_value_000_usd=extracted,
        difference_000_usd=extracted-total, rounding_tolerance_000_usd=(len(stocks)+1)*.5+1,
        equity_weight=total/nav, holdings=len(stocks), country_groups=len(countries),
        top10_security_line_weight=sum(sorted((r['reconstructed_weight'] for r in stocks), reverse=True)[:10]))
    return stocks, country_rows, summary


def build_annual_core_study(raw_root, settings, output):
    require_reader()
    from pypdf import PdfReader
    paths = admit_sources(raw_root, settings)
    destination = Path(output)/'annual_core';(destination/'extracted_pages').mkdir(parents=True)
    stocks = [];countries = [];summaries = [];pages = []
    for report in settings['reports']:
        reader = PdfReader(paths[report['snapshot_date']])
        texts = []
        for page in report['pages_1based']:
            if page > len(reader.pages):raise ValueError('annual schedule page outside PDF')
            text = reader.pages[page-1].extract_text()
            norm = ' '.join(text.split()).upper()
            expected_date = f"As at 30 June {date.fromisoformat(report['snapshot_date']).year}".upper()
            if FUND_NAME.upper() not in norm or expected_date not in norm or 'SCHEDULE OF INVESTMENTS' not in norm:
                raise ValueError('annual PDF page fund/date/schedule identity mismatch')
            target = destination/'extracted_pages'/f"{Path(report['path']).stem}_page_{page}.txt"
            target.write_text(text, encoding='utf-8')
            pages.append(dict(source_file=Path(report['path']).name, physical_page_1based=page,
                text_sha256=sha256(target), snapshot_date=report['snapshot_date']))
            texts.append((page, text))
        h, c, s = parse_core_schedule(texts, report)
        stocks.extend(h);countries.extend(c);summaries.append(s)
    holdings = pd.DataFrame(stocks);country = pd.DataFrame(countries)[COUNTRY_COLUMNS];summary = pd.DataFrame(summaries)
    # The original concentration/top-ten script consumed serialized extraction
    # tables with pandas' default float reader. Repeat that documented boundary
    # on this run's newly generated files, without reading archived outputs.
    for name, frame in [('historical_equity_holdings.csv', holdings),
                        ('historical_country_exposures.csv', country),
                        ('historical_snapshot_summary.csv', summary)]:
        frame.to_csv(destination/name, index=False, lineterminator='\n')
    persisted_h = pd.read_csv(destination/'historical_equity_holdings.csv')
    persisted_c = pd.read_csv(destination/'historical_country_exposures.csv')
    persisted_s = pd.read_csv(destination/'historical_snapshot_summary.csv')
    us = persisted_c[persisted_c.country == 'United States'][['fund', 'snapshot_date', 'reconstructed_weight']].rename(columns={'reconstructed_weight':'us_equity_weight_of_nav'})
    concentration = persisted_s.merge(us, on=['fund', 'snapshot_date'], validate='one_to_one')
    if len(concentration) != len(summary):raise ValueError('annual Core US geography missing')
    top = persisted_h.sort_values(['fund', 'snapshot_date', 'reconstructed_weight'], ascending=[True, True, False]).groupby(['fund', 'snapshot_date']).head(10)
    admit_sources(raw_root, settings)
    return dict(frames={'historical_equity_holdings.csv':holdings, 'historical_country_exposures.csv':country,
        'historical_snapshot_summary.csv':summary, 'historical_concentration_summary.csv':concentration,
        'historical_top10_security_lines.csv':top}, definitions=dict(measurement=MEASUREMENT,
            parser=dict(package='pypdf', version=PDF_VERSION, method='extract_text default'), extracted_pages=pages,
            csv_precision='Full Python-float extraction serialization; concentration and top-ten views consume newly serialized tables with the original pandas default float reader.',
            sources=settings['reports'], interpretation=settings['interpretation'], independent_of_backtest_policy=True))
