"""Hypothetical margin-call paths and static gap insolvency probes."""
from __future__ import annotations

import math
import pandas as pd

from .config import SwissquoteStandardFeeSchedule
from .historical import simulate, metrics


def validate_settings(settings, baseline):
    if settings['schema_version']!=1 or settings['period']!='full':
        raise ValueError('unsupported margin schema or period')
    leverage=settings['target_leverage']
    if not math.isfinite(leverage) or leverage<=1 or leverage!=baseline.get('primary_leverage',max(baseline['leverage_levels'])):
        raise ValueError('margin study must use the selected borrowed exposure')
    variants=settings['variants'];names=[v['id'] for v in variants]
    pairs=[(v['policy'],v['passive_debt']) for v in variants]
    if (not variants or len(set(names))!=len(names) or len(set(pairs))!=len(pairs)
        or any(not isinstance(n,str) or not n.isidentifier() for n in names)):
        raise ValueError('margin variants require unique labels and policy/debt pairs')
    for variant in variants:
        if (variant['policy'] not in baseline['policies'] or type(variant['passive_debt']) is not bool
            or variant['passive_debt'] and variant['policy']!='no_sleeve'):
            raise ValueError('invalid margin policy or passive flag')
    if (baseline.get('primary_policy','hybrid20'),False) not in pairs:
        raise ValueError('margin variants must include the selected managed primary policy')
    initial_ltv=1-1/leverage
    for key in ['maintenance_ltv','extra_liquidation_spreads','gap_losses']:
        values=settings[key]
        if not values or len(set(values))!=len(values) or any(not math.isfinite(x) for x in values):
            raise ValueError('margin sensitivity values must be unique and finite')
    if any(not initial_ltv+1e-12<x<1 for x in settings['maintenance_ltv']):
        raise ValueError('maintenance ratios must exceed target initial LTV and remain below one')
    if any(x<0 for x in settings['extra_liquidation_spreads']) or any(not 0<=x<1 for x in settings['gap_losses']):
        raise ValueError('invalid liquidation spread or gap loss')


def gap_probes(capital, limits, losses):
    capital=float(capital)  # Preserve the archived twelve-decimal USD column schema.
    rows=[]
    for limit in limits:
        for loss in losses:
            assets=capital/(1-limit);debt=assets*limit;after=assets*(1-loss);equity=after-debt
            rows.append(dict(maintenance_ltv=limit,gap_loss=loss,pre_gap_equity=capital,
                post_gap_equity=equity,post_gap_ltv=debt/after,
                status='insolvent' if equity<=0 else 'solvent_before_liquidation',equity_loss=equity/capital-1))
    return pd.DataFrame(rows)


def margin_comparison(returns, reference, baseline, settings):
    validate_settings(settings,baseline)
    bounds=baseline['periods'][settings['period']]
    ret=returns.loc[bounds['start']:bounds['end']].copy()
    if len(ret)<4:raise ValueError('margin period needs sufficient observations')
    ret.iloc[0]=0
    weights=list(baseline['target_weights'].values());sleeves=list(baseline['target_weights'])
    fee=SwissquoteStandardFeeSchedule(**baseline['fee_schedule'])
    shared=dict(margin=baseline['borrowing_margin_annual'],sleeve_band=baseline['sleeve_band'],
        leverage_band=baseline['leverage_band'],initial_equity_usd=baseline['initial_equity_usd'],fee_schedule=fee)
    market=simulate(ret[['core']],reference,[1.],1.,'no_sleeve',**shared)
    rows=[];events=[]
    for variant in settings['variants']:
        policy,passive=variant['policy'],variant['passive_debt']
        for limit in settings['maintenance_ltv']:
            for extra in settings['extra_liquidation_spreads']:
                run=simulate(ret[sleeves],reference,weights,settings['target_leverage'],policy,
                    passive=passive,maintenance=limit,extra_liquidation_spread=extra,**shared)
                if run.status!='complete':
                    raise ValueError('incomplete historical margin path; full-period metrics cannot be accepted')
                rows.append(dict(policy=policy,passive_debt=passive,maintenance_ltv=limit,
                    extra_liquidation_spread=extra,**metrics(run,reference,market,weights),variant=variant['id']))
                label=f'{policy}_passive{passive}_ltv{limit}_extra{extra}'
                events.append(run.events.assign(run_id=label,variant=variant['id']))
    table=pd.DataFrame(rows);all_events=pd.concat(events,ignore_index=True)
    # Existing archive contains the three unchanged hybrid/no-sleeve controls.
    legacy_variants=[v['id'] for v in settings['variants']
        if (v['policy'],v['passive_debt']) in {('hybrid20',False),('no_sleeve',False),('no_sleeve',True)}]
    old=table[table.variant.isin(legacy_variants)].drop(columns='variant')
    old_events=all_events[all_events.variant.isin(legacy_variants)].drop(columns='variant')
    return dict(metrics=table,events=all_events,legacy_metrics=old,legacy_events=old_events,
        gaps=gap_probes(baseline['initial_equity_usd'],settings['maintenance_ltv'],settings['gap_losses']),
        definitions=dict(hypothetical_terms=True,call_priority='Margin before voluntary sleeve/leverage intervention.',
            detection_execution='Detect after NAV marking and prior-interval financing; execute at next observed NAV.',
            cure='Sell current sleeves pro rata and repay debt to configured target leverage after charges; no cash top-up.',
            passive_control='No voluntary leverage or sleeve reset; maintenance calls remain active.',
            gap_basis='Independent state at maintenance boundary with configured committed equity, then simultaneous loss in all sleeves; before liquidation.',
            limitations='NAV observations omit intraday risk; gaps can exhaust equity before the next-observation cure. Actual bank limits, collateral terms and liquidation timing are unverified.'))
