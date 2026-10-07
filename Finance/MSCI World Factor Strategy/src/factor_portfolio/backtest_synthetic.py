"""Analytical artificial market paths and prespecified portfolio mechanics controls."""
from __future__ import annotations

from datetime import date
import math

import numpy as np
import pandas as pd

from .config import SwissquoteStandardFeeSchedule
from .historical import simulate, metrics

REGIMES=['flat','volatile_sideways','sustained_decline','prolonged_weakness',
         'fast_recovery','slow_recovery','factor_lag','factor_rotation']


def validate_settings(settings,baseline):
    if settings['schema_version']!=1 or settings['regimes']!=REGIMES:
        raise ValueError('unsupported synthetic schema or regime order')
    date.fromisoformat(settings['start'])
    if type(settings['levels']) is not int or settings['levels']<4:
        raise ValueError('synthetic paths need at least four observations')
    reference=settings['reference_rate']
    if not math.isfinite(reference) or reference<0:
        raise ValueError('invalid artificial reference rate')
    pairs=settings['exposure_funding_pairs']
    if not pairs or len({tuple(x) for x in pairs})!=len(pairs):
        raise ValueError('synthetic exposure/funding pairs must be unique')
    for leverage,funding in pairs:
        if leverage not in baseline['leverage_levels'] or not math.isfinite(funding) or funding<reference:
            raise ValueError('invalid synthetic exposure or funding rate')
    for path in settings['piecewise_paths'].values():
        knots,levels=path['knots'],path['levels']
        if (len(knots)!=len(levels) or len(knots)<2 or knots[0]!=0 or knots[-1]!=1
            or any(not math.isfinite(x) for x in knots) or any(b<=a for a,b in zip(knots,knots[1:]))
            or levels[0]!=1 or any(not math.isfinite(x) or x<=0 for x in levels)):
            raise ValueError('invalid fixed log-interpolation path')
    scalar_values=[settings['sideways']['amplitude'],settings['sideways']['pi_multiplier'],
        settings['decline_endpoint'],settings['rotation']['amplitude'],settings['rotation']['pi_multiplier'],
        settings['rotation']['phase_denominator']]
    if any(not math.isfinite(x) or x<=0 for x in scalar_values):
        raise ValueError('invalid analytic synthetic path parameters')
    if (len(settings['factor_lag_annual_returns'])!=4 or any(not math.isfinite(x) or x<=-1 for x in settings['factor_lag_annual_returns'])
        or not math.isfinite(settings['rotation']['core_annual_return']) or settings['rotation']['core_annual_return']<=-1
        or len(settings['rotation']['phase_numerators'])!=3):
        raise ValueError('invalid artificial factor path definitions')
    strategies=settings['strategies'];names=[s['id'] for s in strategies]
    if not names or len(set(names))!=len(names) or any(not isinstance(n,str) or not n.isidentifier() for n in names):
        raise ValueError('synthetic strategies require unique identifiers')
    primary=baseline.get('primary_policy','hybrid20')
    if not any(s['portfolio']=='factor' and s['policy']==primary and not s['passive_debt'] and s['maintenance_ltv'] is None for s in strategies):
        raise ValueError('synthetic controls must include the selected primary')
    for strategy in strategies:
        limit=strategy['maintenance_ltv']
        if (strategy['portfolio'] not in {'factor','core'} or strategy['policy'] not in baseline['policies']
            or type(strategy['passive_debt']) is not bool
            or strategy['passive_debt'] and strategy['policy']!='no_sleeve'
            or limit is not None and (not math.isfinite(limit) or not 0<limit<1)):
            raise ValueError('invalid artificial strategy definition')
    legacy=settings['legacy_strategies']
    if len(set(legacy))!=len(legacy) or any(n not in names for n in legacy):
        raise ValueError('unknown or repeated legacy synthetic strategy')
    if any(not math.isfinite(x) or x<reference for x in settings['borrow_rate_columns'].values()):
        raise ValueError('invalid artificial rate column')


def synthetic_inputs(settings,baseline):
    validate_settings(settings,baseline)
    sleeves=list(baseline['target_weights'])
    dates=pd.bdate_range(settings['start'],periods=settings['levels'],name='date')
    t=((dates-dates[0]).days/(dates[-1]-dates[0]).days).to_numpy()
    years=(dates[-1]-dates[0]).days/baseline['measurement']['cagr_calendar_year_days']
    common=dict(flat=np.ones(len(t)),
        volatile_sideways=np.exp(settings['sideways']['amplitude']*np.sin(settings['sideways']['pi_multiplier']*np.pi*t)),
        sustained_decline=np.exp(t*np.log(settings['decline_endpoint'])))
    for name,path in settings['piecewise_paths'].items():
        common[name]=np.exp(np.interp(t,path['knots'],np.log(path['levels'])))
    common['volatile_sideways'][[0,-1]]=1.0
    paths={name:pd.DataFrame({s:level.copy() for s in sleeves},index=dates) for name,level in common.items()}
    paths['factor_lag']=pd.DataFrame({s:(1+r)**(t*years) for s,r in zip(sleeves,settings['factor_lag_annual_returns'])},index=dates)
    rotation=settings['rotation'];core=(1+rotation['core_annual_return'])**(t*years)
    levels={'core':core.copy()}
    for sleeve,numerator in zip(sleeves[1:],rotation['phase_numerators']):
        phase=numerator*np.pi/rotation['phase_denominator']
        offset=rotation['amplitude']*(np.sin(rotation['pi_multiplier']*np.pi*t+phase)-np.sin(phase))
        offset[[0,-1]]=0.
        levels[sleeve]=core*np.exp(offset)
    paths['factor_rotation']=pd.DataFrame(levels,index=dates)
    paths={name:paths[name] for name in settings['regimes']}
    calendar=pd.date_range(dates[0],dates[-1],name='date')
    rates=pd.DataFrame(dict(reference_rate=settings['reference_rate'],**settings['borrow_rate_columns']),index=calendar)
    return paths,rates


def recovery_metrics(equity,capital):
    highs=equity.cummax().clip(lower=capital);drawdown=equity/highs-1
    trough=drawdown.idxmin();prior_high=float(highs.loc[trough])
    hits=equity.loc[:trough];hits=hits[hits>=prior_high]
    peak=hits.index[-1] if len(hits) else equity.index[0]
    recovered=equity.loc[trough:];recovered=recovered[recovered>=prior_high]
    recovery=recovered.index[0] if len(recovered) else None
    finish=recovery if recovery is not None else equity.index[-1]
    return dict(worst_drawdown_peak_date=str(peak.date()),worst_drawdown_trough_date=str(trough.date()),
        recovery_date='' if recovery is None else str(recovery.date()),recovery_censored=recovery is None,
        peak_to_recovery_or_end_calendar_days=int((finish-peak).days),trough_to_recovery_or_end_calendar_days=int((finish-trough).days))


def synthetic_comparison(baseline,settings):
    paths,rates=synthetic_inputs(settings,baseline)
    fee=SwissquoteStandardFeeSchedule(**baseline['fee_schedule'])
    sleeves=list(baseline['target_weights']);weights=list(baseline['target_weights'].values())
    rows=[];levels=[];returns=[];histories=[];events=[];recoveries=[];failures=[]
    capital=baseline['initial_equity_usd'];max_error=0.
    shared=dict(sleeve_band=baseline['sleeve_band'],leverage_band=baseline['leverage_band'],initial_equity_usd=capital,fee_schedule=fee)
    for name,level in paths.items():
        ret=level.pct_change(fill_method=None);ret.iloc[0]=0
        if not np.isfinite(ret.to_numpy()).all() or not (ret>-1).all().all():
            raise ValueError('artificial returns must be finite and above minus one')
        levels.append(level.assign(regime=name).reset_index());returns.append(ret.assign(regime=name).reset_index())
        reference=rates.reference_rate
        market=simulate(ret[['core']],reference,[1.],1.,'no_sleeve',margin=baseline['borrowing_margin_annual'],**shared)
        for leverage,funding in settings['exposure_funding_pairs']:
            for strategy in settings['strategies']:
                metadata=dict(regime=name,strategy=strategy['id'],leverage=leverage,total_borrow_rate=funding)
                cols,target=(['core'],[1.]) if strategy['portfolio']=='core' else (sleeves,weights)
                run=simulate(ret[cols],reference,target,leverage,strategy['policy'],margin=funding-settings['reference_rate'],
                    passive=strategy['passive_debt'],maintenance=strategy['maintenance_ltv'],**shared)
                histories.append(run.history.reset_index().assign(**metadata))
                events.append(run.events.assign(**metadata))
                error=float(abs(run.history.equity_usd-(run.history.gross_assets_usd-run.history.debt_usd)).max())
                if error>1e-7:raise AssertionError('synthetic accounting identity exceeded USD 1e-7')
                max_error=max(max_error,error)
                if leverage==1 and (run.history.debt_usd.abs().max()>1e-8 or run.history.cumulative_financing_cost_usd.abs().max()>1e-8):
                    raise AssertionError('unlevered artificial path carried debt or financing')
                if run.status=='complete':
                    values=metrics(run,reference,market,target)
                    recoveries.append(dict(**metadata,**recovery_metrics(run.history.equity_usd,capital)))
                elif run.status=='insolvent':
                    values=dict(status=run.status,end=str(run.history.index[-1].date()))
                    failures.append(dict(**metadata,last_recorded_solvent_date=values['end'],status=run.status))
                else:raise ValueError('unsupported artificial run status')
                rows.append(dict(**metadata,**values))
    table=pd.DataFrame(rows)
    expected_cases=len(settings['regimes'])*len(settings['exposure_funding_pairs'])*len(settings['strategies'])
    if len(table)!=expected_cases:raise AssertionError('missing artificial scenario runs')
    return dict(metrics=table,legacy_metrics=table[table.strategy.isin(settings['legacy_strategies'])],
        levels=pd.concat(levels,ignore_index=True),returns=pd.concat(returns,ignore_index=True),rates=rates.reset_index(),
        histories=pd.concat(histories,ignore_index=True),events=pd.concat(events,ignore_index=True),recoveries=pd.DataFrame(recoveries),
        definitions=dict(artificial_data=True,stochastic_seeds_used=False,calendar='Fictional weekdays, not exchange sessions or a forecast.',
            administrative_fee=0.,external_flows=0.,reference_rate=settings['reference_rate'],expected_cases=expected_cases,
            complete_cases=int((table.status=='complete').sum()),failures=failures,max_accounting_error_usd=max_error,
            unlevered_debt_and_financing_zero=True,interpretation='Prespecified mechanical controls, not probabilities, fitted factor premia, worst-case bounds or synthetic Dimensional forecasts.'))
