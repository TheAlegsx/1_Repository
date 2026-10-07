"""Forced-call priority, next-observation gaps, pro-rata cure and extra friction."""
import copy
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from factor_portfolio import backtest_margin as margin
from factor_portfolio.historical import simulate

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture
def inputs():
    baseline=json.loads((ROOT/'config/backtest_absolute_decoupled_2026-10-05.json').read_text())
    settings=json.loads((ROOT/'config/backtest_margin_absolute_decoupled_2026-10-05.json').read_text())
    dates=pd.bdate_range('2020-01-02',periods=12,name='date')
    ret=pd.DataFrame(0.,index=dates,columns=['core','momentum','quality','value','dimensional'])
    ret.loc[dates[2]]=-.3;ret.loc[dates[2],'momentum']=-.1
    reference=pd.Series(0.,index=pd.date_range(dates[0],dates[-1]))
    baseline['initial_equity_usd']=12000;baseline['borrowing_margin_annual']=0
    baseline['periods']['full']=dict(start=str(dates[0].date()),end=str(dates[-1].date()))
    return ret,reference,baseline,settings


def test_call_has_priority_and_proportional_next_observation_cure(inputs):
    ret,reference,baseline,_=inputs
    cols=list(baseline['target_weights']);weights=list(baseline['target_weights'].values())
    run=simulate(ret[cols],reference,weights,1.25,'absolute_decoupled',margin=0,
        maintenance=.25,initial_equity_usd=12000)
    assert run.history.loc[ret.index[2],'pending_signal']=='margin_call'
    assert run.events.iloc[1]['date']==ret.index[3] and run.events.iloc[1]['reason']=='margin_call'
    assert run.history.loc[ret.index[3],'leverage']==pytest.approx(1.25)
    before=run.history.loc[ret.index[2],[f'weight_{s}' for s in cols]].to_numpy(float)
    after=run.history.loc[ret.index[3],[f'weight_{s}' for s in cols]].to_numpy(float)
    np.testing.assert_allclose(before,after,atol=1e-12)
    assert not np.allclose(after,weights)
    assert run.history.loc[ret.index[3],'debt_usd']<run.history.loc[ret.index[2],'debt_usd']


def test_next_observation_gap_can_exhaust_equity_before_cure(inputs):
    ret,reference,baseline,_=inputs
    cols=list(baseline['target_weights']);ret.loc[ret.index[3],cols]=-.9
    run=simulate(ret[cols],reference,list(baseline['target_weights'].values()),1.25,
        'absolute_decoupled',margin=0,maintenance=.25,initial_equity_usd=12000)
    assert run.status=='insolvent'
    assert len(run.history)==3
    assert not (run.events.reason=='margin_call').any()


def test_extra_liquidation_cost_reduces_wealth_only_when_forced(inputs):
    result=margin.margin_comparison(*inputs)
    table=result['metrics'].query("variant=='absolute_primary'").set_index(['maintenance_ltv','extra_liquidation_spread'])
    assert table.loc[(.25,0.),'margin_calls']>0
    assert table.loc[(.25,.01),'transaction_cost_usd']>table.loc[(.25,0.),'transaction_cost_usd']
    assert table.loc[(.25,.01),'ending_equity_usd']<table.loc[(.25,0.),'ending_equity_usd']
    assert table.loc[(.6,.01),'transaction_cost_usd']==table.loc[(.6,0.),'transaction_cost_usd']
    assert len(result['legacy_metrics'])==18


def test_gap_states_classify_zero_and_negative_equity_before_liquidation():
    table=margin.gap_probes(7e6,[.25,.6],[.2,.4,.85])
    assert table.query('maintenance_ltv==.6 and gap_loss==.4').iloc[0].status=='insolvent'
    assert table.query('maintenance_ltv==.25 and gap_loss==.2').iloc[0].status=='solvent_before_liquidation'
    assert table.query('gap_loss==.85').post_gap_equity.lt(0).all()


def test_invalid_maintenance_or_passive_policy_is_rejected(inputs):
    _,_,baseline,settings=inputs
    bad=copy.deepcopy(settings);bad['maintenance_ltv']=[.2]
    with pytest.raises(ValueError,match='exceed'):margin.validate_settings(bad,baseline)
    bad=copy.deepcopy(settings);bad['variants'][0]['passive_debt']=True
    with pytest.raises(ValueError,match='invalid'):margin.validate_settings(bad,baseline)
