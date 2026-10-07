"""Joint-cost replacements, matched controls, strict risk criteria and preservation."""
import copy
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from factor_portfolio.backtest_joint_cost import validate_settings,joint_criterion,cost_comparison,run_joint_cost

CONFIG=Path(__file__).resolve().parents[1]/'config'
def configs():
    return [json.loads((CONFIG/name).read_text()) for name in ['backtest_absolute_decoupled_2026-10-05.json','backtest_joint_cost_2026-10-06.json']]


def test_original_cartesian_grid_policies_and_exposure_cannot_be_silently_changed():
    b,s=configs();validate_settings(s,b)
    for field,value in [('margin_bps',[300]),('one_way_spread_bps',[5]),('target_leverage',1.5),('factor_policies',['absolute_decoupled'])]:
        bad=copy.deepcopy(s);bad[field]=value
        with pytest.raises(ValueError,match='42-cell'):validate_settings(bad,b)


def test_joint_criterion_requires_strict_growth_and_correct_drawdown_sign():
    core=dict(cagr=.1,annualised_volatility=.2,maximum_drawdown=-.3)
    assert not joint_criterion(core,core)
    assert joint_criterion(dict(core,cagr=.1001),core)
    assert not joint_criterion(dict(core,cagr=.2,maximum_drawdown=-.31),core)
    assert not joint_criterion(dict(core,cagr=.2,annualised_volatility=.201),core)
    with pytest.raises(ValueError,match='finite'):joint_criterion(dict(core,cagr=float('nan')),core)


def test_matched_core_is_shared_baseline_costs_unchanged_and_scalar_daily_paths_match():
    b,s=configs();original=copy.deepcopy(b);dates=pd.bdate_range('2020-01-02',periods=18,name='date')
    b['periods']['full']=dict(start=str(dates[0].date()),end=str(dates[-1].date()))
    levels=pd.DataFrame({name:100*(1+.003+.008*np.sin(np.arange(len(dates))*.8+i)).cumprod()
        for i,name in enumerate(['core','momentum','quality','value','dimensional'])},index=dates)
    returns=levels.pct_change();returns.iloc[0]=0;reference=pd.Series(.02,index=pd.date_range(dates[0],dates[-1]))
    r=cost_comparison(returns,reference,levels,b,s)
    assert len(r['metrics'])==126 and len(r['pairs'])==84 and len(r['legacy'])==42
    assert r['metrics'].case_id.is_unique and r['comparisons'].passed.all() and r['paths'].daily_path_passed.all()
    assert len(r['comparisons'])==1008 and r['metrics'].financing_cost_usd.min()>0
    assert b['fee_schedule']==original['fee_schedule'] and b['borrowing_margin_annual']==original['borrowing_margin_annual']
    for _,g in r['pairs'].groupby(['margin_bps','one_way_spread_bps']):
        assert g.core_cagr.nunique()==g.core_fees.nunique()==1
    zero=r['fee_definitions'][r['fee_definitions'].one_way_spread_bps.eq(0)]
    assert zero.spread_rate.eq(0).all() and zero.stamp_duty_rate.eq(.0015).all()
    for strategy,policy in [('core','no_sleeve'),('factor','hybrid20'),('factor','absolute_decoupled')]:
        a=r['events'][r['events'].margin_bps.eq(300)&r['events'].one_way_spread_bps.eq(0)&r['events'].strategy.eq(strategy)&r['events'].policy.eq(policy)].iloc[0]
        c=r['events'][r['events'].margin_bps.eq(300)&r['events'].one_way_spread_bps.eq(5)&r['events'].strategy.eq(strategy)&r['events'].policy.eq(policy)].iloc[0]
        assert 0<a.fees_usd<c.fees_usd
    # Actual daily leverage survives metadata attachment; case target is separate.
    h=r['histories'];assert h.target_leverage.eq(1.25).all()
    np.testing.assert_allclose(h.leverage,h.gross_assets_usd/h.equity_usd,rtol=0,atol=1e-12)


def test_existing_outputs_and_failed_runs_are_preserved(tmp_path):
    from factor_portfolio.inflow_workflow import verify_run
    (tmp_path/'old').write_text('retain')
    args=[tmp_path/'raw',CONFIG/'backtest_absolute_decoupled_2026-10-05.json',CONFIG/'backtest_sources.json',CONFIG/'backtest_joint_cost_2026-10-06.json']
    with pytest.raises(FileExistsError):run_joint_cost(*args,tmp_path)
    assert (tmp_path/'old').read_text()=='retain'
    out=tmp_path/'failed'
    with pytest.raises(ValueError,match='source missing'):run_joint_cost(*args,out)
    assert json.loads((out/'run_manifest.json').read_text())['status']=='failed'
    with pytest.raises(ValueError,match='not complete'):verify_run(out)
