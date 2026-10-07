"""Continuing wealth ratios are distinct from new cash accounts and repeated entry costs."""
import copy
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from factor_portfolio import backtest_workflow as workflow
from factor_portfolio import backtest_rolling as rolling

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture
def inputs():
    baseline=json.loads((ROOT/'config/backtest_absolute_decoupled_2026-10-05.json').read_text())
    dates=pd.bdate_range('2018-01-02',periods=800,name='date')
    baseline['initial_equity_usd']=12000
    baseline['periods']['full']=dict(start=str(dates[0].date()),end=str(dates[-1].date()))
    baseline['periods']['calibration']=dict(start=str(dates[0].date()),end=str(dates[399].date()))
    baseline['periods']['confirmation']=dict(start=str(dates[400].date()),end=str(dates[-1].date()))
    ret=pd.DataFrame({c:.0005+.002*np.sin(np.arange(800)+i)
        for i,c in enumerate(['core','momentum','quality','value','dimensional'])},index=dates)
    ret.iloc[0]=0;ret.loc['2018-12-31'] = .12
    reference=pd.Series(.02,index=pd.date_range(dates[0],dates[-1]))
    settings=json.loads((ROOT/'config/backtest_rolling_absolute_decoupled_2026-10-05.json').read_text())
    settings.update(horizon_years=1,minimum_fresh_levels=4,monthly_horizons_years=[1])
    for key in ['fresh_start_grid','ongoing_start_grid']:
        settings[key]=dict(start='2019-01-01',end='2019-01-01',step_months=12)
    comparison=workflow.policy_comparison(ret,reference,baseline)
    return ret,reference,baseline,settings,comparison


def test_ongoing_ratio_keeps_observed_wealth_and_differs_from_fresh_account(inputs):
    ret,reference,baseline,settings,paths=inputs
    result=rolling.rolling_comparison(ret,reference,baseline,settings,paths['histories'],paths['curves'])
    for policy in settings['factor_policies']:
        eq=paths['histories'][f'full_factor_{policy}_1.25_history.csv'].set_index('date').equity_usd.loc['2019-01-01':'2020-01-01']
        row=result['ongoing'].query('policy==@policy').iloc[0]
        years=(eq.index[-1]-eq.index[0]).days/365.2425
        assert row.start_equity_usd==pytest.approx(eq.iloc[0])
        assert row.cagr==pytest.approx((eq.iloc[-1]/eq.iloc[0])**(1/years)-1)
        fresh=result['fresh'].query('policy==@policy').iloc[0]
        assert fresh.cagr!=pytest.approx(row.cagr)
    assert len(result['fresh'])==2 and len(result['ongoing'])==2
    assert set(result['pairs']['mode'])=={'fresh','ongoing'}


def test_monthly_windows_share_dates_between_policies_and_legacy_view_is_explicit(inputs):
    ret,reference,baseline,settings,paths=inputs
    result=rolling.rolling_comparison(ret,reference,baseline,settings,paths['histories'],paths['curves'])
    table=result['monthly']
    absolute=table.query("policy=='absolute_decoupled'")[['leverage','horizon_years','start','end']].reset_index(drop=True)
    hybrid=table.query("policy=='hybrid20'")[['leverage','horizon_years','start','end']].reset_index(drop=True)
    pd.testing.assert_frame_equal(absolute,hybrid)
    assert len(result['legacy_monthly'])*2==len(table)
    assert 'policy' not in result['legacy_monthly']
    assert len(result['monthly_summary'])==4


def test_missing_retained_history_and_invalid_grid_fail_before_calculation(inputs):
    _,_,baseline,settings,_=inputs
    baseline['history_policies']=['absolute_decoupled']
    with pytest.raises(ValueError,match='retained histories'):rolling.validate_settings(settings,baseline)
    baseline['history_policies']=['absolute_decoupled','hybrid20']
    bad=copy.deepcopy(settings);bad['fresh_start_grid']['step_months']=0
    with pytest.raises(ValueError,match='grid'):rolling.validate_settings(bad,baseline)
