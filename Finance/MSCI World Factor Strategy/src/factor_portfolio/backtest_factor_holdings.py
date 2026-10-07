"""Dated factor equity schedules and contemporaneous security-name overlap."""
from __future__ import annotations

from datetime import date
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd

from .backtest_annual_holdings import (PDF_VERSION, COUNTRY_COLUMNS, MEASUREMENT as CORE_MEASUREMENT,
    admit_sources as admit_pdf_sources, parse_core_schedule, require_reader)
from .inflow_workflow import sha256

FACTORS = ['momentum', 'quality', 'value']
FUND_NAMES = {fund:'iShares Edge MSCI World '+fund.capitalize()+' Factor UCITS ETF' for fund in FACTORS}
MEASUREMENT = {k:v for k,v in CORE_MEASUREMENT.items() if k != 'fund'} | dict(funds=FACTORS,
    snapshot_month_day='05-31', overlap_key='exact reported name with whitespace normalized + trading currency',
    overlap_denominator='summed equity fair value in each dated fund',
    overlap='sum of smaller matched equity-normalized weights')


def validate_settings(settings, baseline):
    if settings['schema_version'] != 1 or settings['measurement'] != MEASUREMENT:
        raise ValueError('unsupported historical factor holdings contract')
    sources = settings['sources'];schedules = settings['schedules']
    if not sources or len({s['path'] for s in sources}) != len(sources) or len({s['snapshot_date'] for s in sources}) != len(sources):
        raise ValueError('factor PDF paths and source dates must be distinct')
    source_map = {s['path']:s for s in sources}
    dates = {s['snapshot_date'] for s in sources}
    expected = {(d,f) for d in dates for f in FACTORS}
    actual = {(s['snapshot_date'],s['fund']) for s in schedules}
    if actual != expected or len(schedules) != len(expected):
        raise ValueError('each factor date requires exactly the three contemporaneous fund schedules')
    for source in sources:
        d = date.fromisoformat(source['snapshot_date'])
        if (d.month,d.day) != (5,31) or d > date.fromisoformat(baseline['periods']['full']['end']):
            raise ValueError('factor annual snapshot must be a May year end before the backtest cutoff')
        if Path(source['path']).name != f'ishares_iv_annual_{d.year}.pdf':
            raise ValueError('factor annual report filename/date mismatch')
    for s in schedules:
        if s['path'] not in source_map or s['snapshot_date'] != source_map[s['path']]['snapshot_date'] or s['fund_identity'] != FUND_NAMES[s['fund']]:
            raise ValueError('factor PDF/subfund/date identity mismatch')
        pages = s['pages_1based']
        if not pages or any(type(p) is not int or p < 1 for p in pages) or pages != list(range(pages[0],pages[-1]+1)):
            raise ValueError('factor schedule needs positive contiguous physical pages')
        if s['expected_holdings'] < 1 or s['expected_country_groups'] < 1:
            raise ValueError('factor schedule counts must be positive')


def admit_sources(raw_root, settings):
    # One source record per PDF/date, with three separately declared subfunds.
    return admit_pdf_sources(raw_root, {'reports':settings['sources']})


def historical_factor_overlap(holdings):
    """Use contemporaneous factor dates only; no Core/Dimensional synchronization."""
    rows = []
    if holdings.empty or not set(holdings.fund).issubset(FACTORS):
        raise ValueError('historical overlap requires factor security lines only')
    for snapshot in sorted(holdings.snapshot_date.unique()):
        frames = {}
        for fund in FACTORS:
            h = holdings[(holdings.fund == fund) & (holdings.snapshot_date == snapshot)].copy()
            if h.empty or not np.isfinite(h.fair_value_000_usd.to_numpy()).all() or (h.fair_value_000_usd < 0).any():
                raise ValueError('historical overlap needs complete finite contemporaneous factor equity values')
            h['key'] = h.name.str.replace(r'\s+', ' ', regex=True).str.strip()+'|'+h.currency.fillna('')
            grouped = h.groupby('key').fair_value_000_usd.sum()
            if grouped.sum() <= 0:raise ValueError('historical overlap equity denominator must be positive')
            frames[fund] = grouped/grouped.sum()
        for a,b in combinations(FACTORS,2):
            x,y = frames[a],frames[b];common = x.index.intersection(y.index)
            rows.append(dict(snapshot_date=snapshot, fund_a=a, fund_b=b,
                security_key='exact reported name and trading currency', matched_keys=len(common),
                holdings_keys_a=len(x), holdings_keys_b=len(y),
                weighted_equity_overlap=sum(min(x[k],y[k]) for k in common)))
    return pd.DataFrame(rows)


def build_factor_annual_study(raw_root, settings, output):
    require_reader()
    from pypdf import PdfReader
    paths = admit_sources(raw_root,settings)
    destination = Path(output)/'annual_factors';(destination/'extracted_pages').mkdir(parents=True)
    readers = {};stocks = [];countries = [];summaries = [];pages = []
    for schedule in settings['schedules']:
        snapshot = schedule['snapshot_date'];fund = schedule['fund']
        if snapshot not in readers:readers[snapshot] = PdfReader(paths[snapshot])
        reader = readers[snapshot];texts = []
        for page in schedule['pages_1based']:
            if page > len(reader.pages):raise ValueError('factor schedule page outside PDF')
            text = reader.pages[page-1].extract_text();norm = ' '.join(text.split()).upper()
            expected_date = f'As at 31 May {date.fromisoformat(snapshot).year}'.upper()
            if FUND_NAMES[fund].upper() not in norm or expected_date not in norm or 'SCHEDULE OF INVESTMENTS' not in norm:
                raise ValueError('factor PDF page fund/date/schedule identity mismatch')
            target = destination/'extracted_pages'/f"{Path(schedule['path']).stem}_page_{page}.txt"
            if target.exists():raise ValueError('factor schedule physical pages must not overlap')
            target.write_text(text,encoding='utf-8')
            pages.append(dict(source_file=Path(schedule['path']).name, physical_page_1based=page,
                text_sha256=sha256(target), snapshot_date=snapshot, fund=fund))
            texts.append((page,text))
        h,c,s = parse_core_schedule(texts,schedule)
        # The preserved helper implements the common ETF grammar/accounting.
        # Its Core label is replaced by the explicitly admitted subfund identity.
        for row in h+c+[s]:row['fund'] = fund
        stocks.extend(h);countries.extend(c);summaries.append(s)
    holdings = pd.DataFrame(stocks);country = pd.DataFrame(countries)[COUNTRY_COLUMNS];summary = pd.DataFrame(summaries)
    for name,frame in [('historical_equity_holdings.csv',holdings),('historical_country_exposures.csv',country),('historical_snapshot_summary.csv',summary)]:
        frame.to_csv(destination/name,index=False,lineterminator='\n')
    # Keep the original derived-table CSV boundary, including overlap inputs.
    persisted_h = pd.read_csv(destination/'historical_equity_holdings.csv')
    persisted_c = pd.read_csv(destination/'historical_country_exposures.csv')
    persisted_s = pd.read_csv(destination/'historical_snapshot_summary.csv')
    us = persisted_c[persisted_c.country == 'United States'][['fund','snapshot_date','reconstructed_weight']].rename(columns={'reconstructed_weight':'us_equity_weight_of_nav'})
    concentration = persisted_s.merge(us,on=['fund','snapshot_date'],validate='one_to_one')
    if len(concentration) != len(summary):raise ValueError('factor annual US geography missing')
    top = persisted_h.sort_values(['fund','snapshot_date','reconstructed_weight'],ascending=[True,True,False]).groupby(['fund','snapshot_date']).head(10)
    overlap = historical_factor_overlap(persisted_h)
    admit_sources(raw_root,settings)
    return dict(frames={'historical_equity_holdings.csv':holdings,'historical_country_exposures.csv':country,
        'historical_snapshot_summary.csv':summary,'historical_concentration_summary.csv':concentration,
        'historical_top10_security_lines.csv':top,'factor_name_overlap.csv':overlap},
        definitions=dict(measurement=MEASUREMENT,parser=dict(package='pypdf',version=PDF_VERSION,method='extract_text default'),
            sources=settings['sources'],schedules=settings['schedules'],extracted_pages=pages,
            csv_precision='Full-float extraction; derived tables and overlap consume newly serialized inputs with pandas default float reader.',
            independent_of_backtest_policy=True,interpretation=settings['interpretation']))
