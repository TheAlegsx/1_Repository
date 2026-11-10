"""Paired account and stationary-bootstrap functions used by the report."""

import math
import numpy as np
import pandas as pd

from .config import SwissquoteStandardFeeSchedule
from .historical import simulate
from .coupled_inflow_accounting import simulate_coupled


def fee_calendar(dates, annual_fee, year_days=365.2425):
    """Original monthly payments plus one explicitly specified terminal accrual."""
    dates = pd.DatetimeIndex(dates)
    if len(dates) < 2 or not dates.is_unique or not dates.is_monotonic_increasing:
        raise ValueError('ordered common NAV dates required')
    if not math.isfinite(annual_fee) or annual_fee < 0:
        raise ValueError('nonnegative annual fund fee required')
    start, end = dates[0], dates[-1]
    rows=[]; month=1; prior=start
    while True:
        nominal=start+pd.DateOffset(months=month)
        position=dates.searchsorted(nominal)
        if position>=len(dates):break
        actual=dates[position]
        if actual<=prior:raise ValueError('anniversary payments require distinct common NAVs')
        rows.append(dict(event_date=actual,month=month,project_year=(month-1)//12+1,
            scheduled_subscription_usd=0.,monthly_external_unit_redemption_fraction=0.,
            proposed_fund_fee_fraction=annual_fee/12,payment_kind='regular_month',
            nominal_date=str(nominal.date()),stub_calendar_days=0))
        prior=actual;month+=1
    if end>prior:
        days=(end-prior).days
        rows.append(dict(event_date=end,month=month,project_year=(month-1)//12+1,
            scheduled_subscription_usd=0.,monthly_external_unit_redemption_fraction=0.,
            proposed_fund_fee_fraction=annual_fee*days/year_days,payment_kind='terminal_stub',
            nominal_date=None,stub_calendar_days=days))
    return pd.DataFrame(rows)


def run_account(returns, reference, baseline, case, strategy):
    cols=list(baseline['target_weights']) if strategy=='factor' else ['core']
    weights=list(baseline['target_weights'].values()) if strategy=='factor' else [1.]
    policy='absolute_decoupled' if strategy=='factor' else 'no_sleeve'
    kwargs=dict(leverage=1.25,policy=policy,margin=case['margin_bps']/10000,
        sleeve_band=case['sleeve_band'],leverage_band=case['leverage_band'],
        initial_equity_usd=baseline['initial_equity_usd'],
        fee_schedule=SwissquoteStandardFeeSchedule(**baseline['fee_schedule']))
    ret=returns[cols].copy();ret.iloc[0]=0.
    plan=fee_calendar(ret.index,case['fund_fee_bps']/10000,
        baseline['measurement']['cagr_calendar_year_days'])
    result=simulate_coupled(ret,reference,weights,flows=plan,initial_unit_nav=100.,**kwargs)
    if result.status!='complete' or len(result.history)!=len(ret):
        raise ValueError('complete paired account required')
    if case['fund_fee_bps']==0:
        original=simulate(ret,reference,weights,**kwargs)
        pd.testing.assert_frame_equal(result.history[original.history.columns],original.history,check_exact=True)
        pd.testing.assert_frame_equal(result.events,original.events,check_exact=True)
    return result,plan


def stationary_draws(log_pairs, entry_factors, years, block_length, replications, seed):
    """Paired stationary circular blocks; opening charges remain fixed once."""
    pairs=np.asarray(log_pairs,dtype=float);entry=np.asarray(entry_factors,dtype=float)
    if pairs.ndim!=2 or pairs.shape[1]!=2 or len(pairs)<2 or not np.isfinite(pairs).all():
        raise ValueError('finite two-column aligned log-return pair required')
    if entry.shape!=(2,) or (entry<=0).any() or years<=0 or block_length<1 or replications<1:
        raise ValueError('valid entry factors and bootstrap controls required')
    rng=np.random.default_rng(seed);n=len(pairs);index=rng.integers(0,n,size=replications)
    totals=np.tile(np.log(entry),(replications,1))
    for t in range(n):
        if t:
            restart=rng.random(replications)<1/block_length
            replacement=rng.integers(0,n,size=replications)
            index=np.where(restart,replacement,(index+1)%n)
        totals+=pairs[index]
    return np.expm1(totals/years)
