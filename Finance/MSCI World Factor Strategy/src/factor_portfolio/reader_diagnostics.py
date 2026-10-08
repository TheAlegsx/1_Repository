"""Descriptive reader summaries from admitted investment paths, without reruns."""
from pathlib import Path
import hashlib
import json
import pandas as pd


def summaries(source):
    source = Path(source)
    curves_file = source / 'backtest/evidence/equity_curves.csv'
    history_file = source / 'backtest/evidence/primary_history.csv'
    metrics_file = source / 'backtest/evidence/main.csv'
    curves = pd.read_csv(curves_file, index_col='date', parse_dates=True, float_precision='round_trip')
    history = pd.read_csv(history_file, index_col='date', parse_dates=True, float_precision='round_trip')
    metrics = pd.read_csv(metrics_file, float_precision='round_trip')
    if not curves.index.equals(history.index) or not history.index.is_unique or not history.index.is_monotonic_increasing:
        raise ValueError('diagnostics require identical ordered common observations')
    main = curves['full_factor_absolute_decoupled_1.25']
    core = curves['full_core_1.25']
    if (main <= 0).any() or (core <= 0).any():
        raise ValueError('relative wealth requires positive account equity')

    def cell(value, display, file, field, row=None, expression=None):
        return dict(value=value, display=display, origins=[dict(artifact=str(file.relative_to(source)),
                    field=field, row=row)], expression=expression)

    endpoints = []
    for year in [2022, 2023, 2024, 2025, None]:
        date = curves.index[-1] if year is None else curves.loc[:f'{year}-12-31'].index[-1]
        value = float((main.loc[date] / core.loc[date] - 1) * 100)
        endpoints.append([cell(str(date.date()), str(date.date()), curves_file, 'date', str(date.date())),
                          cell(value, f'{value:+.2f}%', curves_file, 'factor/Core equity', str(date.date()),
                               '100 * (factor_equity / core_equity - 1)')])
    lev = history.leverage
    descriptions = [('Observation mean', float(lev.mean()), None, 'arithmetic mean across common NAV observations'),
                    ('Minimum', float(lev.min()), str(lev.idxmin().date()), 'minimum observed leverage'),
                    ('Maximum', float(lev.max()), str(lev.idxmax().date()), 'maximum observed leverage'),
                    ('Final observation', float(lev.iloc[-1]), str(lev.index[-1].date()), 'last observed leverage')]
    leverage = [[cell(label, label, history_file, 'leverage', date),
                 cell(value, f'{value:.3f}x', history_file, 'leverage', date, expression),
                 cell(date, date or 'All observations', history_file, 'date', date)]
                for label, value, date, expression in descriptions]
    retail = []
    for strategy, policy, exposure, label in [('factor', 'absolute_decoupled', 1.25, 'Factor portfolio'),
                                            ('core', 'leverage_managed', 1., 'MSCI World Core')]:
        found = metrics[(metrics.period == 'full') & (metrics.strategy == strategy)
                        & (metrics.policy == policy) & (metrics.leverage == exposure)]
        if len(found) != 1:
            raise ValueError('retail comparison requires one exact existing strategy row')
        row = found.iloc[0]; index = int(found.index[0])
        retail.append([cell(label, label, metrics_file, 'strategy', index),
                       cell(exposure, f'{exposure:g}x', metrics_file, 'leverage', index)] +
                      [cell(float(row[field]), f'{float(row[field])*100:.2f}%' if field != 'sharpe_ratio'
                            else f'{float(row[field]):.3f}', metrics_file, field, index)
                       for field in ['cagr', 'annualised_volatility', 'sharpe_ratio']])
    core_row = metrics[(metrics.period == 'full') & (metrics.strategy == 'core') & (metrics.leverage == 1.25)]
    if len(core_row) != 1:
        raise ValueError('one matched-target Core account required')
    core_mean = float(core_row.iloc[0].mean_leverage)
    payload = {
        'endpoints': dict(kind='table', headers=['Last common NAV', 'Relative wealth vs Core 1.25x'], rows=endpoints),
        'leverage': dict(kind='table', headers=['Observed portfolio leverage', 'Value', 'Date / scope'], rows=leverage),
        'retail': dict(kind='table', headers=['Investment', 'Target', 'CAGR', 'Volatility', 'Sharpe'], rows=retail),
        'core_mean': dict(kind='claim', **cell(core_mean, f'{core_mean:.3f}x', metrics_file, 'mean_leverage', int(core_row.index[0])))}
    payload['source_files_sha256'] = {str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest()
                                     for p in [curves_file, history_file, metrics_file]}
    return payload
