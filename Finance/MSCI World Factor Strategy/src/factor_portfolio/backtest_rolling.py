"""Fresh and continuing rolling windows with explicit, different wealth bases."""
from __future__ import annotations

from datetime import date
import math

import numpy as np
import pandas as pd

from .config import SwissquoteStandardFeeSchedule
from .historical import simulate, metrics


def validate_settings(settings, baseline):
    if settings['schema_version'] != 1:
        raise ValueError('unsupported rolling schema')
    policies = settings['factor_policies']
    primary = baseline.get('primary_policy', 'hybrid20')
    if (len(set(policies)) != len(policies) or primary not in policies
        or settings['comparison_policy'] not in policies or settings['comparison_policy'] == primary
        or any(p not in baseline.get('history_policies', ['hybrid20']) for p in policies)):
        raise ValueError('rolling policies need distinct primary/comparison and retained histories')
    if settings['study_leverage'] != baseline.get('primary_leverage', max(baseline['leverage_levels'])):
        raise ValueError('rolling study exposure disagrees with primary exposure')
    for grid_key in ['fresh_start_grid','ongoing_start_grid']:
        grid = settings[grid_key]
        start, end = date.fromisoformat(grid['start']), date.fromisoformat(grid['end'])
        if (start > end or start.day != 1 or end.day != 1
            or type(grid['step_months']) is not int or not 1 <= grid['step_months'] <= 12):
            raise ValueError('invalid month-start rolling grid')
    if type(settings['horizon_years']) is not int or settings['horizon_years'] <= 0:
        raise ValueError('rolling horizon must be a positive integer')
    if type(settings['minimum_fresh_levels']) is not int or settings['minimum_fresh_levels'] < 4:
        raise ValueError('rolling minimum observations must support risk metrics')
    tol = settings['comparison_cagr_tolerance']
    if not math.isfinite(tol) or tol <= 0:
        raise ValueError('rolling comparison tolerance must be finite and positive')
    horizons, exposures = settings['monthly_horizons_years'], settings['monthly_leverage_levels']
    if not horizons or len(set(horizons)) != len(horizons) or any(type(y) is not int or y <= 0 for y in horizons):
        raise ValueError('invalid monthly rolling horizons')
    if not exposures or len(set(exposures)) != len(exposures) or any(x not in baseline['leverage_levels'] for x in exposures):
        raise ValueError('invalid monthly rolling exposures')


def grid_dates(grid):
    return pd.date_range(grid['start'], grid['end'], freq=f"{grid['step_months']}MS")


def rolling_comparison(returns, reference, baseline, settings, histories, curves):
    validate_settings(settings, baseline)
    fee = SwissquoteStandardFeeSchedule(**baseline['fee_schedule'])
    sleeves, weights = list(baseline['target_weights']), list(baseline['target_weights'].values())
    primary, comparison = baseline.get('primary_policy','hybrid20'), settings['comparison_policy']
    lev = settings['study_leverage']
    fresh, ongoing, pairs, exclusions = [], [], [], []
    elapsed_year_days = baseline['measurement']['cagr_calendar_year_days']

    def account(ret, cols, target, exposure, policy):
        run = simulate(ret[cols], reference, target, exposure, policy,
            margin=baseline['borrowing_margin_annual'], sleeve_band=baseline['sleeve_band'],
            leverage_band=baseline['leverage_band'], initial_equity_usd=baseline['initial_equity_usd'], fee_schedule=fee)
        if run.status != 'complete':
            raise ValueError('incomplete rolling path; comparison cannot be accepted')
        return run

    def equity(policy, exposure):
        name = f'full_factor_{policy}_{exposure:.2f}_history.csv'
        frame = histories[name].set_index('date')
        if not frame.index.equals(returns.index):
            raise ValueError('rolling history must match the current common calendar')
        return frame.equity_usd

    def pair(mode, requested, end, records):
        a, b = records[primary], records[comparison]
        delta = a['cagr']-b['cagr'];tol = settings['comparison_cagr_tolerance']
        pairs.append(dict(mode=mode, requested_start=str(requested.date()), requested_end=str(end.date()),
            start=a['start'],end=a['end'],primary_policy=primary,comparison_policy=comparison,
            primary_cagr=a['cagr'],comparison_cagr=b['cagr'],cagr_difference=delta,
            result='tie' if abs(delta)<=tol else 'primary_higher' if delta>0 else 'primary_lower'))

    for requested in grid_dates(settings['fresh_start_grid']):
        end = requested + pd.DateOffset(years=settings['horizon_years'])
        ret = returns.loc[requested:end].copy()
        if len(ret)<settings['minimum_fresh_levels']:
            exclusions.append(dict(mode='fresh',requested_start=str(requested.date()),requested_end=str(end.date()),
                levels=len(ret),reason='insufficient_observations'))
            continue
        ret.iloc[0] = 0
        market = account(ret,['core'],[1.],1.,'no_sleeve')
        records = {}
        for policy in settings['factor_policies']:
            values = metrics(account(ret,sleeves,weights,lev,policy),reference,market,weights)
            fresh.append(dict(policy=policy,requested_start=str(requested.date()),requested_end=str(end.date()),**values))
            records[policy] = values
        pair('fresh',requested,end,records)

    for requested in grid_dates(settings['ongoing_start_grid']):
        end = requested + pd.DateOffset(years=settings['horizon_years'])
        records = {}
        for policy in settings['factor_policies']:
            eq = equity(policy,lev).loc[requested:end]
            if len(eq)<2:
                raise ValueError('ongoing rolling window needs at least two observations')
            years=(eq.index[-1]-eq.index[0]).days/elapsed_year_days
            values=dict(start=str(eq.index[0].date()),end=str(eq.index[-1].date()),observations=len(eq),
                start_equity_usd=float(eq.iloc[0]),end_equity_usd=float(eq.iloc[-1]),
                cagr=float((eq.iloc[-1]/eq.iloc[0])**(1/years)-1))
            ongoing.append(dict(policy=policy,requested_start=str(requested.date()),requested_end=str(end.date()),**values))
            records[policy]=values
        pair('ongoing',requested,end,records)

    monthly=[]
    curve_panel=curves.set_index('date')
    if not curve_panel.index.equals(returns.index):
        raise ValueError('Core curves must match the current common calendar')
    for policy in settings['factor_policies']:
        for exposure in settings['monthly_leverage_levels']:
            fac=equity(policy,exposure);core=curve_panel[f'full_core_{exposure:.2f}']
            ends=fac.groupby(fac.index.to_period('M')).tail(1).index
            for years in settings['monthly_horizons_years']:
                for end in ends:
                    requested=end-pd.DateOffset(years=years)
                    if requested<fac.index[0]:continue
                    start=fac.index[fac.index.searchsorted(requested)]
                    a,b=fac.loc[start:end],core.loc[start:end]
                    duration=(end-start).days/elapsed_year_days
                    ca=(a.iloc[-1]/a.iloc[0])**(1/duration)-1;cb=(b.iloc[-1]/b.iloc[0])**(1/duration)-1
                    va=a.pct_change().iloc[1:].std()*np.sqrt(252);vb=b.pct_change().iloc[1:].std()*np.sqrt(252)
                    da=(a/a.cummax()-1).min();db=(b/b.cummax()-1).min()
                    monthly.append(dict(policy=policy,leverage=exposure,horizon_years=years,start=start,end=end,
                        cagr_difference=ca-cb,volatility_difference=va-vb,drawdown_difference=da-db))
    table=pd.DataFrame(monthly)
    if table.empty:raise ValueError('configured monthly horizons produce no complete windows')
    summary=table.groupby(['policy','leverage','horizon_years']).apply(lambda g:pd.Series(dict(
        windows=len(g),higher_cagr_share=(g.cagr_difference>0).mean(),median_cagr_difference=g.cagr_difference.median(),
        no_higher_volatility_share=(g.volatility_difference<=0).mean(),no_deeper_drawdown_share=(g.drawdown_difference>=0).mean())),include_groups=False).reset_index()
    legacy=table[table.policy=='hybrid20'].drop(columns='policy')
    legacy_summary=summary[summary.policy=='hybrid20'].drop(columns='policy')
    return dict(fresh=pd.DataFrame(fresh),ongoing=pd.DataFrame(ongoing),pairs=pd.DataFrame(pairs),
        monthly=table,monthly_summary=summary,legacy_monthly=legacy,legacy_summary=legacy_summary,
        definitions=dict(fresh_equity_basis='New committed capital and entry charges, zero first return; no inherited debt.',
            ongoing_equity_basis='Observed account wealth at each window start; inherited holdings/debt; no new entry charge.',
            grid_difference='Research fresh grid uses six-month anchors; ongoing grid uses yearly anchors. Their aggregate counts are not same-sample comparisons.',
            monthly_policy='Observed monthly-end common NAVs, including final partial month; one/three/five-year continuing-account comparisons against same-exposure Core.',
            exclusions=exclusions,interpretation='Retrospective overlapping windows and descriptive shares; not independent samples or future probabilities.'))
