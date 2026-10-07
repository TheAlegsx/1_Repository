"""Finite crossing semantics, fee-aware no-cash cures and raw-run preservation."""
import copy
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from factor_portfolio.backtest_funding_scan_gap import (validate_settings,crossing_scan,gap_cure,
    gap_comparison,funding_comparison,run_funding_scan_gap)
from factor_portfolio.independent_gap_cure import solve_gap
from factor_portfolio.config import SwissquoteStandardFeeSchedule
from factor_portfolio.historical import simulate,metrics

CONFIG=Path(__file__).resolve().parents[1]/'config'
def configs():
    return [json.loads((CONFIG/n).read_text()) for n in ['backtest_absolute_decoupled_2026-10-05.json','backtest_funding_scan_gap_2026-10-06.json']]


def test_preserved_scan_and_gap_protocol_cannot_be_silently_replaced():
    b,s=configs();validate_settings(s,b)
    for k,v in [('scan_step_bps',20),('refinement_iterations',22),('base_cagr_decimal_places',17),
        ('approximate_zero_residual',1e-4),('maintenance_ltv',[.25]),('liquidation_extra_spread',0),('factor_policies',['absolute_decoupled'])]:
        wrong=copy.deepcopy(s);wrong[k]=v
        with pytest.raises(ValueError,match='preserved'):validate_settings(wrong,b)


def test_finite_scan_distinguishes_zero_and_jump_and_does_not_infer_unseen_roots():
    zero=crossing_scan(lambda x:.003*(x-.371),[0.,1.]);assert len(zero)==1 and zero.type.iloc[0]=='approximate_zero'
    assert abs(zero.crossing_bps.iloc[0]-.371)<=1/2**26
    jump=crossing_scan(lambda x:-.001 if x<.371 else .002,[0.,1.]);assert jump.type.iloc[0]=='policy_discontinuity'
    assert jump.left_difference.iloc[0]<0<jump.right_difference.iloc[0]
    assert crossing_scan(lambda x:(x-.2)*(x-.8),[0.,1.]).empty  # Coarse scan misses two changes.
    with pytest.raises(ValueError,match='nonfinite'):crossing_scan(lambda x:float('nan'),[0.,1.])
    with pytest.raises(ValueError,match='invalid'):crossing_scan(lambda x:x,[1.,1.])


def test_grid_endpoint_is_retained_with_the_original_local_refinement_semantics():
    result=crossing_scan(lambda x:x,[0.,1.]);assert result.type.iloc[0]=='approximate_zero'
    assert result.crossing_bps.iloc[0]==1/2**26 and result.left_difference.iloc[0]==0.
    assert crossing_scan(lambda x:x+1,[0.,1.]).empty


def test_fifteen_cures_are_shared_static_scenarios_with_no_cash_and_independent_fee_solution():
    b,s=configs();before=copy.deepcopy(b);r=gap_comparison(b,s)
    assert b==before and len(r['gaps'])==15 and r['gap_checks'].passed.all()
    assert r['gaps'].status.value_counts().to_dict()==dict(insolvent_before_cure=9,cured_at_assumed_next_NAV=6)
    dead=r['gaps'][r['gaps'].status.eq('insolvent_before_cure')]
    assert dead[['cure_sale_usd','liquidation_cost_usd','post_cure_debt_usd']].isna().all().all()
    live=r['gap_checks'].dropna(subset=['post_cure_leverage'])
    np.testing.assert_allclose(live.post_cure_leverage,1.25,rtol=0,atol=1e-9)
    assert r['gap_checks'].external_cash_usd.eq(0).all() and live.ordinary_trade_cost_usd.gt(0).all()
    assert live.extra_liquidation_cost_usd.gt(live.ordinary_trade_cost_usd).all()


def test_insolvency_before_and_after_fees_and_unsolved_fixed_point_are_explicit():
    b,s=configs();w=list(b['target_weights'].values());fee=SwissquoteStandardFeeSchedule(**b['fee_schedule'])
    a=gap_cure(7e6,.4,.6,w,1.25,fee,.01);assert a['status']=='insolvent_before_cure' and a['post_gap_equity']==0
    expensive=gap_cure(7e6,.6,.2,w,1.25,fee,.3)
    independent=solve_gap(7e6,.6,.2,w,1.25,b['fee_schedule'],.3)
    assert expensive['status']==independent['status']=='insolvent_after_liquidation_costs'
    assert expensive['post_cure_debt_usd'] is expensive['liquidation_cost_usd'] is None
    with pytest.raises(ArithmeticError,match='convergence'):gap_cure(7e6,.25,.2,w,1.25,fee,.01,iterations=1)
    with pytest.raises(ValueError,match='invalid'):gap_cure(7e6,.25,float('nan'),w,1.25,fee,.01)


def test_independent_piecewise_solution_handles_small_notional_commission_tiers():
    b,s=configs();w=list(b['target_weights'].values());fee=SwissquoteStandardFeeSchedule(**b['fee_schedule'])
    for capital in [1e4,5e4,2e5,7e6]:
        a=gap_cure(capital,.4,.2,w,1.25,fee,.01);z=solve_gap(capital,.4,.2,w,1.25,b['fee_schedule'],.01)
        assert a['status']==z['status']=='cured_at_assumed_next_NAV'
        for k in ['cure_sale_usd','liquidation_cost_usd','post_cure_debt_usd']:
            assert abs(a[k]-z[k])<=1e-6+2e-12*abs(a[k])


def test_fresh_funding_scan_uses_each_rules_own_rounded_base_and_verifies_accounts():
    b,s=configs();dates=pd.bdate_range('2020-01-02',periods=8,name='date')
    b['periods']['full']=dict(start=str(dates[0].date()),end=str(dates[-1].date()))
    levels=pd.DataFrame({name:100*np.cumprod(1+.003+.006*np.sin(np.arange(8)+i))
        for i,name in enumerate(b['target_weights'])},index=dates)
    ret=levels.pct_change();ret.iloc[0]=0;reference=pd.Series(.02,index=pd.date_range(dates[0],dates[-1]))
    fee=SwissquoteStandardFeeSchedule(**b['fee_schedule']);weights=list(b['target_weights'].values())
    shared=dict(initial_equity_usd=b['initial_equity_usd'],fee_schedule=fee,sleeve_band=b['sleeve_band'],leverage_band=b['leverage_band'])
    market=simulate(ret[['core']],reference,[1.],1.,'no_sleeve',**shared);bases=[]
    for policy in s['factor_policies']:
        r=simulate(ret,reference,weights,1.,policy,**shared);v=metrics(r,reference,market,weights)
        v['cagr']=float(f"{v['cagr']:.12f}")
        bases.append(dict(period='full',strategy='factor',policy=policy,leverage=1.,**v))
    result=funding_comparison(ret,reference,levels,pd.DataFrame(bases),b,s)
    assert len(result['scan'])>=202 and result['comparisons'].passed.all() and result['paths'].daily_path_passed.all()
    assert len(result['comparisons'])==8*(len(result['metrics'])+2)
    assert result['metrics'].case_id.is_unique and result['paths'].observations.eq(8).all()
    assert (result['crossings'].type==result['crossings'].independent_type).all()
    with pytest.raises(ValueError,match='unique'):funding_comparison(ret,reference,levels,pd.DataFrame(bases[:-1]),b,s)


def test_existing_and_failed_outputs_remain_reviewable(tmp_path):
    from factor_portfolio.inflow_workflow import verify_run
    (tmp_path/'retain').write_text('old')
    args=[tmp_path/'raw',CONFIG/'backtest_absolute_decoupled_2026-10-05.json',CONFIG/'backtest_sources.json',CONFIG/'backtest_funding_scan_gap_2026-10-06.json']
    with pytest.raises(FileExistsError):run_funding_scan_gap(*args,tmp_path)
    assert (tmp_path/'retain').read_text()=='old'
    out=tmp_path/'failed'
    with pytest.raises(ValueError,match='source missing'):run_funding_scan_gap(*args,out)
    assert json.loads((out/'run_manifest.json').read_text())['status']=='failed'
    with pytest.raises(ValueError,match='not complete'):verify_run(out)
