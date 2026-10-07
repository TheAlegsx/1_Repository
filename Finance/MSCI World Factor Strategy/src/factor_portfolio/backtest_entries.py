"""Fresh-entry date sensitivity with explicit independent capital and debt restarts."""
from __future__ import annotations

from datetime import date
import math

import pandas as pd

from .config import SwissquoteStandardFeeSchedule
from .historical import simulate, metrics


def validate_settings(settings, baseline):
    if settings['schema_version'] != 1:
        raise ValueError('unsupported entry schema')
    starts = settings['requested_starts']
    parsed = [date.fromisoformat(x) for x in starts]
    period = baseline['periods']['full']
    if (not starts or len(set(starts)) != len(starts) or parsed != sorted(parsed)
        or any(x < date.fromisoformat(period['start']) or x >= date.fromisoformat(period['end']) for x in parsed)):
        raise ValueError('entry dates must be unique, ordered and within the baseline period')
    policies = settings['factor_policies']
    primary = baseline.get('primary_policy', 'hybrid20')
    comparison = settings['comparison_policy']
    if (len(set(policies)) != len(policies) or primary not in policies or comparison not in policies
        or primary == comparison or any(p not in baseline['policies'] for p in policies)):
        raise ValueError('entry policies must include distinct calculated primary/comparison rules')
    exposures = settings['leverage_levels']
    if (not exposures or len(set(exposures)) != len(exposures)
        or any(x not in baseline['leverage_levels'] for x in exposures)
        or baseline.get('primary_leverage', max(baseline['leverage_levels'])) not in exposures):
        raise ValueError('entry exposures must include the selected primary exposure')
    tolerance = settings['comparison_cagr_tolerance']
    if not math.isfinite(tolerance) or tolerance <= 0:
        raise ValueError('entry comparison tolerance must be finite and positive')
    for key in ['research_reference_starts', 'legacy_reference_starts']:
        selected = settings[key]
        if len(set(selected)) != len(selected) or any(x not in starts for x in selected):
            raise ValueError('reference start selection contains unknown or repeated dates')
    if settings['legacy_reference_starts'] and 'hybrid20' not in policies:
        raise ValueError('legacy entry reference requires calculated hybrid comparison')


def entry_comparison(returns, reference, baseline, settings):
    validate_settings(settings, baseline)
    sleeves = list(baseline['target_weights'])
    weights = list(baseline['target_weights'].values())
    fee = SwissquoteStandardFeeSchedule(**baseline['fee_schedule'])
    primary = baseline.get('primary_policy', 'hybrid20')
    exposure = baseline.get('primary_leverage', max(baseline['leverage_levels']))
    rows, dates, comparisons = [], [], []

    def run(ret, cols, target, lev, policy):
        result = simulate(ret[cols], reference, target, lev, policy,
            margin=baseline['borrowing_margin_annual'], sleeve_band=baseline['sleeve_band'],
            leverage_band=baseline['leverage_band'], initial_equity_usd=baseline['initial_equity_usd'], fee_schedule=fee)
        if result.status != 'complete':
            raise ValueError('incomplete fresh-entry path; comparison cannot be accepted')
        return result

    for requested in settings['requested_starts']:
        ret = returns.loc[requested:baseline['periods']['full']['end']].copy()
        if len(ret) < 4:
            raise ValueError('entry period needs sufficient observations')
        ret.iloc[0] = 0
        dates.append(dict(requested_entry=requested, actual_entry=str(ret.index[0].date()),
            end=str(ret.index[-1].date()), levels=len(ret), independent_capital_debt_cost_restart=True))
        market = run(ret, ['core'], [1.], 1., 'no_sleeve')
        selected_rows = {}
        for lev in settings['leverage_levels']:
            for policy in settings['factor_policies']:
                result = run(ret, sleeves, weights, lev, policy)
                values = metrics(result, reference, market, weights)
                rows.append(dict(requested_entry=requested, strategy='factor', leverage=lev, policy=policy, **values))
                if lev == exposure:
                    selected_rows[policy] = values
            for strategy in ['core','dimensional']:
                result = run(ret, [strategy], [1.], lev, 'no_sleeve')
                rows.append(dict(requested_entry=requested, strategy=strategy, leverage=lev,
                    policy='leverage_managed', **metrics(result, reference, market, [1.])))
        a, b = selected_rows[primary], selected_rows[settings['comparison_policy']]
        difference = a['cagr']-b['cagr']
        tol = settings['comparison_cagr_tolerance']
        comparisons.append(dict(requested_entry=requested, actual_entry=a['start'], end=a['end'],
            levels=a['observations'], primary_policy=primary, comparison_policy=settings['comparison_policy'],
            leverage=exposure, primary_cagr=a['cagr'], comparison_cagr=b['cagr'], cagr_difference=difference,
            result='tie' if abs(difference) <= tol else 'primary_higher' if difference > 0 else 'primary_lower'))
    table = pd.DataFrame(rows)
    legacy = table[table.requested_entry.isin(settings['legacy_reference_starts'])
        & ((table.strategy != 'factor') | (table.policy == 'hybrid20'))].drop(columns='policy')

    def summary(selected):
        subset = [row for row in comparisons if row['requested_entry'] in selected]
        return dict(dates=len(subset), primary_higher=sum(x['result']=='primary_higher' for x in subset),
            primary_lower=sum(x['result']=='primary_lower' for x in subset), ties=sum(x['result']=='tie' for x in subset))

    return dict(metrics=table, legacy_metrics=legacy, dates=dates, comparison=pd.DataFrame(comparisons),
        summary=dict(all_requested_starts=summary(settings['requested_starts']),
            original_research_starts=summary(settings['research_reference_starts']),
            comparison_cagr_tolerance=settings['comparison_cagr_tolerance'],
            interpretation='Retrospective, unequal overlapping horizons; counts are descriptive, not probabilities or independent validation.'))
