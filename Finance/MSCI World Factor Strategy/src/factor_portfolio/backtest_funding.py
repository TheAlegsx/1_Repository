"""Configured historical funding experiments, without saved-result dependencies."""
from __future__ import annotations

import math
import pandas as pd

from .config import SwissquoteStandardFeeSchedule
from .historical import simulate, metrics


def validate_settings(settings, baseline):
    if settings['schema_version'] != 1 or settings['factor_policy'] not in {'hybrid20', 'absolute_decoupled'}:
        raise ValueError('unsupported funding schema or factor policy')
    if settings['factor_policy'] != baseline.get('primary_policy', 'hybrid20'):
        raise ValueError('funding factor policy disagrees with the selected primary policy')
    periods = settings['periods']
    if not periods or len(set(periods)) != len(periods) or any(p not in baseline['periods'] for p in periods):
        raise ValueError('invalid funding periods')
    margins = settings['margin_bps']
    if not margins or len(set(margins)) != len(margins) or any(not math.isfinite(x) or x < 0 for x in margins):
        raise ValueError('funding margins must be unique, finite and nonnegative')
    if not math.isfinite(settings['target_leverage']) or settings['target_leverage'] <= 1:
        raise ValueError('funding experiment requires a borrowed exposure above one')
    threshold = settings['threshold']
    if threshold['period'] != 'full':
        raise ValueError('current threshold comparison requires the full period')
    validate_search(threshold['bracket_bps'], threshold['iterations'])
    for tolerance in settings['reconciliation_tolerances'].values():
        if not math.isfinite(tolerance) or tolerance <= 0:
            raise ValueError('reconciliation tolerances must be finite and positive')


def validate_search(bracket, iterations):
    if (len(bracket) != 2 or any(not math.isfinite(x) or x < 0 for x in bracket)
        or bracket[0] >= bracket[1] or type(iterations) is not int or not 1 <= iterations <= 60):
        raise ValueError('invalid funding search bracket or iteration count')


def bracketed_crossing(difference, bracket, iterations):
    """Preserve fixed-iteration reference bisection; disclose rather than invent a root."""
    validate_search(bracket, iterations)
    evaluations = []

    def evaluate(bp):
        value = float(difference(bp))
        if not math.isfinite(value):
            raise ValueError('nonfinite funding CAGR difference')
        evaluations.append(dict(margin_bps=bp, cagr_difference=value))
        return value

    lo, hi = map(float, bracket)
    flo, fhi = evaluate(lo), evaluate(hi)
    initial_values = [flo, fhi]
    root = residual = None
    status = 'not_bracketed'
    if flo == 0 or fhi == 0:
        root, residual = (lo, flo) if flo == 0 else (hi, fhi)
        status = 'endpoint_zero'
    elif flo * fhi <= 0:
        for _ in range(iterations):
            mid = (lo + hi) / 2
            fm = evaluate(mid)
            if fm * flo > 0:
                lo, flo = mid, fm
            else:
                hi, fhi = mid, fm
        root = (lo + hi) / 2
        residual = evaluate(root)
        status = 'bracketed_estimate'
    return dict(margin_bps=root, difference_at_threshold=residual), dict(
        status=status, initial_bracket_bps=list(bracket), initial_cagr_differences=initial_values,
        final_bracket_bps=[lo, hi], final_bracket_width_bps=hi-lo,
        requested_iterations=iterations, evaluations=evaluations,
        interpretation='Local fixed-iteration crossing estimate only; no guarantee of a unique root, continuity, global monotonicity or attainable financing terms.')


def funding_comparison(returns, reference, baseline, settings):
    validate_settings(settings, baseline)
    sleeves = list(baseline['target_weights'])
    weights = list(baseline['target_weights'].values())
    fee = SwissquoteStandardFeeSchedule(**baseline['fee_schedule'])

    def run(ret, cols, target, exposure, policy, margin):
        result = simulate(ret[cols], reference, target, exposure, policy, margin=margin,
            sleeve_band=baseline['sleeve_band'], leverage_band=baseline['leverage_band'],
            initial_equity_usd=baseline['initial_equity_usd'], fee_schedule=fee)
        if result.status != 'complete':
            raise ValueError('incomplete funding path; comparison cannot be accepted')
        return result

    def period_returns(name):
        boundaries = baseline['periods'][name]
        ret = returns.loc[boundaries['start']:boundaries['end']].copy()
        if len(ret) < 4:
            raise ValueError('funding period needs sufficient observations')
        ret.iloc[0] = 0
        return ret

    rows = []
    for period in settings['periods']:
        ret = period_returns(period)
        core1 = run(ret, ['core'], [1.], 1., 'no_sleeve', baseline['borrowing_margin_annual'])
        for bp in settings['margin_bps']:
            for strategy, cols, target in [('factor', sleeves, weights), ('core', ['core'], [1.]),
                                           ('dimensional', ['dimensional'], [1.])]:
                result = run(ret, cols, target, settings['target_leverage'],
                    settings['factor_policy'] if strategy == 'factor' else 'no_sleeve', bp / 1e4)
                rows.append(dict(period=period, strategy=strategy, margin_bps=bp,
                    **metrics(result, reference, core1, target)))

    ret = period_returns('full')
    core1 = run(ret, ['core'], [1.], 1., 'no_sleeve', baseline['borrowing_margin_annual'])
    unlevered = run(ret, sleeves, weights, 1., settings['factor_policy'], baseline['borrowing_margin_annual'])
    target = metrics(unlevered, reference, core1)['cagr']

    def difference(bp):
        leveraged = run(ret, sleeves, weights, settings['target_leverage'], settings['factor_policy'], bp / 1e4)
        return metrics(leveraged, reference, core1)['cagr'] - target

    search = settings['threshold']
    crossing, diagnostics = bracketed_crossing(difference, search['bracket_bps'], search['iterations'])
    threshold = dict(margin_bps=crossing['margin_bps'], bracket_bps=search['bracket_bps'],
        comparison=f"{settings['factor_policy']} factor {settings['target_leverage']:g}x CAGR minus {settings['factor_policy']} factor 1.0x CAGR",
        sample='full common calendar', difference_at_threshold=crossing['difference_at_threshold'])
    diagnostics.update(unlevered_factor_cagr=target, start=str(ret.index[0].date()),
        end=str(ret.index[-1].date()), levels=len(ret), margin_units='basis points above observed reference rate',
        reference_rate_preserved=True, grid_cases=len(rows))
    return dict(metrics=pd.DataFrame(rows), threshold=threshold, diagnostics=diagnostics)
