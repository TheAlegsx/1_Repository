"""Configured allocation/trading/financing counterfactuals on one historical sample."""
from __future__ import annotations

import math
import pandas as pd

from .config import SwissquoteStandardFeeSchedule
from .historical import simulate, metrics


def validate_settings(settings, baseline):
    if settings['schema_version'] != 1 or settings['period'] != 'full' or settings['factor_policy'] not in {'hybrid20', 'absolute_decoupled'}:
        raise ValueError('unsupported counterfactual schema, period or factor policy')
    if settings['factor_policy'] != baseline.get('primary_policy', 'hybrid20'):
        raise ValueError('counterfactual factor policy disagrees with the selected primary policy')
    cases = settings['cases']
    names = [case['id'] for case in cases]
    if not names or len(set(names)) != len(names) or any(not isinstance(n, str) or not n.isidentifier() for n in names):
        raise ValueError('counterfactual cases require unique identifier labels')
    for case in cases:
        if (case['strategy'] not in {'core', 'factor'} or case['margin_source'] not in {'baseline', 'zero'}
            or not math.isfinite(case['leverage']) or case['leverage'] < 1
            or type(case['reference_interest']) is not bool or type(case['transaction_costs']) is not bool):
            raise ValueError('invalid counterfactual economic settings')
    sequence = settings['sequence']
    if len(sequence) < 2 or len(set(sequence)) != len(sequence) or any(n not in names for n in sequence):
        raise ValueError('sequence must select distinct declared cases')
    controls = settings['controls']
    ids = [control['id'] for control in controls]
    if len(set(ids)) != len(ids) or any(not isinstance(n, str) or not n.isidentifier() for n in ids):
        raise ValueError('controls require unique identifier labels')
    for control in controls:
        if control['from'] not in names or control['to'] not in names or control['from'] == control['to']:
            raise ValueError('control must compare two distinct declared cases')
    if 'full' not in baseline['periods']:
        raise ValueError('counterfactual period is absent from the baseline')


def bridge_comparison(returns, reference, baseline, settings):
    validate_settings(settings, baseline)
    boundaries = baseline['periods'][settings['period']]
    ret = returns.loc[boundaries['start']:boundaries['end']].copy()
    if len(ret) < 4:
        raise ValueError('counterfactual period needs sufficient observations')
    ret.iloc[0] = 0
    fee = SwissquoteStandardFeeSchedule(**baseline['fee_schedule'])
    sleeves = list(baseline['target_weights'])
    weights = list(baseline['target_weights'].values())

    def run(cols, target, exposure, policy, rate, margin, fee_free=False):
        result = simulate(ret[cols], rate, target, exposure, policy, margin=margin,
            sleeve_band=baseline['sleeve_band'], leverage_band=baseline['leverage_band'],
            fee_free=fee_free, initial_equity_usd=baseline['initial_equity_usd'], fee_schedule=fee)
        if result.status != 'complete':
            raise ValueError('incomplete counterfactual path; comparison cannot be accepted')
        return result

    core1 = run(['core'], [1.], 1., 'no_sleeve', reference, baseline['borrowing_margin_annual'])
    rows = []
    for case in settings['cases']:
        cols, target = (sleeves, weights) if case['strategy'] == 'factor' else (['core'], [1.])
        # Labels never determine economics. Financing and risk-reference roles differ.
        rate = reference if case['reference_interest'] else reference * 0
        margin = baseline['borrowing_margin_annual'] if case['margin_source'] == 'baseline' else 0.
        result = run(cols, target, case['leverage'],
            settings['factor_policy'] if case['strategy'] == 'factor' else 'no_sleeve',
            rate, margin, fee_free=not case['transaction_costs'])
        rows.append(dict(counterfactual=case['id'], **metrics(result, reference, core1, target)))
    lookup = {row['counterfactual']: row for row in rows}
    differences = []

    def compare(label, kind, before, after):
        a, b = lookup[before], lookup[after]
        fields = ['ending_equity_usd', 'cagr', 'transaction_cost_usd', 'financing_cost_usd']
        differences.append(dict(comparison=label, kind=kind, from_case=before, to_case=after,
            **{f'change_{field}': b[field]-a[field] for field in fields}))

    for i, (before, after) in enumerate(zip(settings['sequence'], settings['sequence'][1:]), start=1):
        compare(f'step_{i}', 'sequential', before, after)
    for control in settings['controls']:
        compare(control['id'], 'control', control['from'], control['to'])
    return dict(metrics=pd.DataFrame(rows), differences=pd.DataFrame(differences))
