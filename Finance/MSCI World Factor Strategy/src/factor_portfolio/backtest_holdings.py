"""Later issuer snapshot: target-weight concentration and security-line overlap."""
from __future__ import annotations

from datetime import date
from itertools import combinations
import math

import numpy as np
import pandas as pd

from .data import _read_root, _worksheets
from .inflow_workflow import sha256

SLEEVES = ['core', 'momentum', 'quality', 'value']
MEASUREMENT = dict(equity_scope='Asset Class exactly Equity',
    identifier='strip ticker + name + market currency; exact case; no ISIN reconciliation',
    overlap='sum of smaller matched fund weights; no equity renormalization',
    portfolio_weights='source fund weights times configured target sleeve weights',
    core_exposures='aggregate equity holdings only',
    factor_exposures='supplied rounded Exposure Breakdowns including cash/derivatives',
    top_positions=10, equity_coverage_bounds=[.90, 1.02])
FILES = ['equity_holdings.csv', 'combined_equity_holdings.csv', 'country_by_sleeve.csv',
         'country_combined.csv', 'sector_by_sleeve.csv', 'sector_combined.csv', 'pairwise_overlap.csv']


def validate_settings(settings, baseline):
    if settings['schema_version'] != 1 or settings['measurement'] != MEASUREMENT:
        raise ValueError('unsupported later holdings measurement contract')
    snapshot = date.fromisoformat(settings['snapshot_date'])
    if snapshot <= date.fromisoformat(baseline['periods']['full']['end']):
        raise ValueError('later holdings snapshot must remain outside the backtest')
    if list(baseline['target_weights']) != SLEEVES:
        raise ValueError('later holdings study requires the four ordered sleeves')
    if list(settings['expected_rows']) != FILES or any(type(n) is not int or n < 1 for n in settings['expected_rows'].values()):
        raise ValueError('declare the seven positive holdings table row counts')


def _source_date(text):
    months = dict(Jan=1, Feb=2, Mar=3, Apr=4, May=5, Jun=6, Jul=7, Aug=8, Sept=9, Oct=10, Nov=11, Dec=12)
    try:
        day, month, year = text.split('/')
        return date(int(year), months[month], int(day)).isoformat()
    except (KeyError, ValueError):
        raise ValueError('unsupported issuer snapshot date') from None


def _check_dates(rows, label, expected):
    dates = [r[1] for r in rows if len(r) > 1 and r[0] == label]
    if not dates or any(_source_date(d) != expected for d in dates):
        raise ValueError('holdings/exposure valuation date differs from admitted snapshot')


def _weight(text, *, equity):
    try:
        weight = float(text)/100
    except (TypeError, ValueError):
        raise ValueError('invalid issuer snapshot weight') from None
    if not math.isfinite(weight) or abs(weight) > 1.02 or (equity and weight < 0):
        raise ValueError('invalid issuer snapshot weight')
    return weight


def snapshot_comparison(sources, baseline, settings):
    validate_settings(settings, baseline)
    weights = baseline['target_weights']
    holdings, country, sector, hashes = [], [], [], {}
    for sleeve in SLEEVES:
        path = sources[sleeve]
        hashes[sleeve] = dict(filename=path.name, sha256=sha256(path))
        sheets = _worksheets(_read_root(path))
        rows = sheets['Holdings']
        _check_dates(rows, 'Fund Holdings as of' if sleeve == 'core' else 'as of', settings['snapshot_date'])
        header_rows = [i for i, row in enumerate(rows) if 'Weight (%)' in row and 'Issuer Ticker' in row]
        if len(header_rows) != 1:
            raise ValueError('ambiguous issuer holdings header')
        first = header_rows[0];header = rows[first]
        required = {'Name', 'Issuer Ticker', 'Market Currency', 'Sector', 'Asset Class', 'Weight (%)'}
        if sleeve == 'core':
            required.add('Location')
        if not required.issubset(header) or len(set(header)) != len(header):
            raise ValueError('missing or repeated issuer holdings columns')
        for row in rows[first+1:]:
            entry = dict(zip(header, row))
            if entry.get('Asset Class') != 'Equity':
                continue
            if any(not entry.get(key, '').strip() for key in required):
                raise ValueError('incomplete equity security-line classification')
            weight = _weight(entry['Weight (%)'], equity=True)
            proxy = '|'.join(entry[key].strip() for key in ['Issuer Ticker', 'Name', 'Market Currency'])
            holdings.append(dict(sleeve=sleeve, identifier_proxy=proxy, name=entry['Name'],
                ticker=entry['Issuer Ticker'], currency=entry['Market Currency'], sector=entry['Sector'],
                location=entry.get('Location'), fund_weight=weight, portfolio_weight=weight*weights[sleeve]))
        if sleeve != 'core':
            rows = sheets['Exposure Breakdowns']
            _check_dates(rows, 'as of', settings['snapshot_date'])
            state = 'sector';seen_country = False
            for row in rows:
                if row and row[0] == 'Geography/Locations':
                    state = 'country';seen_country = True
                if len(row) < 2 or row[0] in {'as of', 'Type'}:
                    continue
                weight = _weight(row[1], equity=False)
                target = sector if state == 'sector' else country
                target.append(dict(sleeve=sleeve, category=row[0], fund_weight=weight,
                    portfolio_weight=weight*weights[sleeve]))
            if not seen_country:
                raise ValueError('factor snapshot requires its separate geography section')
    holdings = pd.DataFrame(holdings)
    if holdings.empty or set(holdings.sleeve) != set(SLEEVES):
        raise ValueError('each sleeve requires equity security lines')
    coverage = holdings.groupby('sleeve').fund_weight.sum()
    if not coverage.between(*MEASUREMENT['equity_coverage_bounds']).all():
        raise ValueError('equity snapshot weight coverage outside declared bounds')
    core = holdings[holdings.sleeve == 'core']
    for column, target in [('sector', sector), ('location', country)]:
        for category, weight in core.groupby(column).fund_weight.sum().items():
            target.append(dict(sleeve='core', category=category, fund_weight=weight,
                portfolio_weight=weight*weights['core']))
    combined = holdings.groupby('identifier_proxy', as_index=False).agg(name=('name', 'first'),
        ticker=('ticker', 'first'), currency=('currency', 'first'), portfolio_weight=('portfolio_weight', 'sum'),
        sleeves=('sleeve', 'nunique')).sort_values('portfolio_weight', ascending=False)
    frames = {'equity_holdings.csv': holdings, 'combined_equity_holdings.csv': combined}
    for name, rows in [('country', country), ('sector', sector)]:
        table = pd.DataFrame(rows)
        frames[name+'_by_sleeve.csv'] = table
        frames[name+'_combined.csv'] = table.groupby('category', as_index=False).portfolio_weight.sum().sort_values('portfolio_weight', ascending=False)
    overlap = []
    for a, b in combinations(SLEEVES, 2):
        x = holdings[holdings.sleeve == a].groupby('identifier_proxy').fund_weight.sum()
        y = holdings[holdings.sleeve == b].groupby('identifier_proxy').fund_weight.sum()
        common = x.index.intersection(y.index)
        overlap.append(dict(sleeve_a=a, sleeve_b=b, matched_equity_lines=len(common),
            sum_min_fund_weight=float(np.minimum(x.reindex(common), y.reindex(common)).sum())))
    frames['pairwise_overlap.csv'] = pd.DataFrame(overlap)
    for name in FILES:
        if len(frames[name]) != settings['expected_rows'][name]:
            raise ValueError('holdings table differs from admitted row count: '+name)
    total = float(holdings.portfolio_weight.sum())
    if not np.isclose(total, combined.portfolio_weight.sum(), atol=1e-12, rtol=0):
        raise ValueError('combined security-line weights do not reconcile')
    summary = dict(snapshot_date=settings['snapshot_date'], after_backtest_cutoff=True,
        selected_target_weights=weights, top10_combined_equity_weight=float(combined.head(10).portfolio_weight.sum()),
        equity_weight_coverage=coverage.to_dict(),
        identifier_policy='Exact issuer ticker + name + market currency; no ISIN/security-master reconciliation; may miss equivalent listings/classes or name variations.',
        core_country_sector_policy='Equity holdings aggregation, excluding non-equity; other sleeves use supplied Exposure Breakdowns which include cash/derivatives and rounded source values.',
        missing='This stage excludes historical annual-report schedules and Dimensional holdings, which remain separate reconstruction work; no historical attribution claim.')
    return dict(frames=frames, summary=summary, definitions=dict(measurement=MEASUREMENT,
        source_files=hashes, snapshot_date=settings['snapshot_date'], target_weight_equity_total=total,
        no_leverage_multiplier=True, no_backtest_holdings_attribution=True,
        exclusions=['non-equity holdings from the security-line aggregation', 'historical schedules', 'Dimensional holdings'],
        interpretation=settings['interpretation']))
