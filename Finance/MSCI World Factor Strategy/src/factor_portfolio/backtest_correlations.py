"""Descriptive product-return correlations with explicit common-level calendars."""
from __future__ import annotations

from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd

PRODUCTS = ['core', 'momentum', 'quality', 'value', 'dimensional']
PANELS = ['long_full', 'long_calibration', 'long_confirmation', 'long_monthly',
          'market_negative_intervals', 'short_with_amundi', 'short_without_amundi']
MEASUREMENT = dict(alignment='intersect_positive_levels_before_returns',
    returns='simple_excluding_first_level', methods=['pearson', 'spearman'],
    rank_ties='average', monthly='last_common_observed_level',
    negative_condition='core_return_strictly_negative', rolling_observations=252,
    fill_missing=False, investor_costs=False)


def validate_settings(settings, baseline, product_settings):
    if settings['schema_version'] != 1 or settings['measurement'] != MEASUREMENT:
        raise ValueError('unsupported correlation measurement contract')
    if product_settings is None:
        raise ValueError('correlations require the admitted product stage and fresh Amundi NAV')
    if list(settings['expected_panels']) != PANELS:
        raise ValueError('correlation contract must enumerate all seven panels')
    for name, expected in settings['expected_panels'].items():
        if expected['return_observations'] < 3:
            raise ValueError('correlation panel needs at least three return observations: ' + name)
    full = settings['expected_panels']['long_full']
    if full['level_start'] != baseline['periods']['full']['start'] or full['last_return_end'] != baseline['periods']['full']['end']:
        raise ValueError('correlation long window must match the main common period')
    if settings['excluded_month'] != full['last_return_end'][:7]:
        raise ValueError('monthly exclusion must identify the final partial common month')


def _validate_levels(levels, columns):
    if (list(levels.columns) != columns or len(levels) < 4
        or not isinstance(levels.index, pd.DatetimeIndex) or levels.index.hasnans
        or not levels.index.is_unique or not levels.index.is_monotonic_increasing
        or not np.isfinite(levels.to_numpy()).all() or not (levels > 0).all().all()):
        raise ValueError('invalid complete positive ordered common-level panel')


def _matrix(returns, method):
    if (len(returns) < 3 or not np.isfinite(returns.to_numpy()).all()
        or not (returns.std(ddof=1) > 0).all()):
        raise ValueError('correlations require finite nonconstant aligned returns')
    if method == 'pearson':
        result = returns.corr(method='pearson')
    else:
        # Average ranks retain tied published observations. This is Spearman's
        # rank-Pearson definition, with no optional SciPy runtime dependency.
        ranked = returns.rank(method='average').to_numpy()
        result = pd.DataFrame(np.corrcoef(ranked, rowvar=False),
            index=returns.columns, columns=returns.columns)
    values = result.to_numpy()
    if (not np.isfinite(values).all() or not np.allclose(values, values.T, atol=1e-12, rtol=0)
        or not np.allclose(np.diag(values), 1, atol=1e-12, rtol=0)
        or np.abs(values).max() > 1 + 1e-12 or np.linalg.eigvalsh(values).min() < -1e-10):
        raise ValueError('invalid correlation matrix')
    return result.rename_axis('product')


def correlation_comparison(long, amundi, baseline, settings):
    """No simulated wealth, financing or portfolio-policy returns enter this study."""
    _validate_levels(long, PRODUCTS)
    if (not amundi.index.is_unique or not amundi.index.is_monotonic_increasing
        or amundi.index.hasnans or not np.isfinite(amundi.to_numpy()).all() or not (amundi > 0).all()):
        raise ValueError('invalid Amundi NAV observations')
    common = long.index.intersection(amundi.index)
    short = long.loc[common].copy()
    short['amundi_2x'] = amundi.loc[common]
    _validate_levels(short, PRODUCTS + ['amundi_2x'])
    frames, records, panels, pairs = {}, {}, {}, []

    def add(name, levels=None, returns=None):
        if levels is not None:
            _validate_levels(levels, list(levels.columns))
            returns = levels.pct_change(fill_method=None).iloc[1:]
            frames[name + '_levels.csv'] = levels.rename_axis('date')
        if returns is None or len(returns) < 3:
            raise ValueError('insufficient aligned returns for correlation panel: ' + name)
        record = dict(first_return_end=str(returns.index[0].date()),
            last_return_end=str(returns.index[-1].date()), return_observations=len(returns),
            products=list(returns.columns), level_start=str(levels.index[0].date()) if levels is not None else None,
            level_observations=len(levels) if levels is not None else None)
        if record != settings['expected_panels'][name]:
            raise ValueError('correlation calendar/count differs from admitted panel: ' + name)
        records[name] = record
        panels[name] = returns
        frames[name + '_returns.csv'] = returns.rename_axis('date')
        for method in MEASUREMENT['methods']:
            corr = _matrix(returns, method)
            frames[name + '_' + method + '.csv'] = corr
            for a, b in combinations(returns.columns, 2):
                pairs.append(dict(panel=name, method=method, product_a=a, product_b=b,
                    correlation=corr.loc[a, b], return_observations=len(returns)))

    add('long_full', long)
    add('long_calibration', long.loc[baseline['periods']['calibration']['start']:baseline['periods']['calibration']['end']])
    add('long_confirmation', long.loc[baseline['periods']['confirmation']['start']:baseline['periods']['confirmation']['end']])
    monthly = long.groupby(long.index.to_period('M')).tail(1)
    excluded = monthly.index[-1]
    if str(excluded.to_period('M')) != settings['excluded_month']:
        raise ValueError('unexpected ending monthly valuation')
    add('long_monthly', monthly.iloc[:-1])
    ret = panels['long_full']
    add('market_negative_intervals', returns=ret.loc[ret.core < 0])
    add('short_with_amundi', short)
    add('short_without_amundi', short.drop(columns='amundi_2x'))
    if not panels['short_with_amundi'].drop(columns='amundi_2x').equals(panels['short_without_amundi']):
        raise ValueError('short horizon controls must use identical intervals')
    rolling = []
    window = MEASUREMENT['rolling_observations']
    if len(ret) < window:
        raise ValueError('insufficient history for the fixed rolling observation window')
    for a, b in combinations(long.columns, 2):
        corr = ret[a].rolling(window, min_periods=window).corr(ret[b]).dropna()
        if len(corr) != len(ret) - window + 1 or not np.isfinite(corr.to_numpy()).all() or corr.abs().max() > 1 + 1e-10:
            raise ValueError('invalid or incomplete rolling correlations')
        rolling.extend(dict(date=d, product_a=a, product_b=b, correlation=v) for d, v in corr.items())
    rolling = pd.DataFrame(rolling)
    frames['rolling_252.csv'] = rolling
    frames['rolling_summary.csv'] = rolling.groupby(['product_a', 'product_b']).correlation.agg(['count', 'min', 'median', 'max']).reset_index()
    frames['pairwise_correlations.csv'] = pd.DataFrame(pairs)
    return dict(frames=frames, definitions=dict(panels=records,
        excluded_final_monthly_level=str(excluded.date()), measurement=MEASUREMENT,
        interpretation=settings['interpretation'], primary_policy_independent=True,
        source_inputs=['inputs/common_nav_usd.csv', 'products/market_data/amundi_2x_nav_usd.csv']))


def build_correlation_study(output, baseline, settings):
    output = Path(output)
    long = pd.read_csv(output / 'inputs/common_nav_usd.csv', index_col='date', parse_dates=True, float_precision='round_trip')
    nav = pd.read_csv(output / 'products/market_data/amundi_2x_nav_usd.csv', index_col='date', parse_dates=True, float_precision='round_trip')
    if list(nav.columns) != ['amundi_2x_nav_usd']:
        raise ValueError('unexpected fresh Amundi NAV columns')
    return correlation_comparison(long, nav.iloc[:, 0], baseline, settings)
