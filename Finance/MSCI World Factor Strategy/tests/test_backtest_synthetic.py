"""Declared analytical endpoints, no assumed factor premium, and censored recovery."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from factor_portfolio import backtest_synthetic as synthetic

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture
def settings():
    baseline=json.loads((ROOT/'config/backtest_absolute_decoupled_2026-10-05.json').read_text())
    config=json.loads((ROOT/'config/backtest_synthetic_absolute_decoupled_2026-10-05.json').read_text())
    return baseline,config


def test_analytical_endpoints_and_common_regimes_have_no_factor_premium(settings):
    baseline,config=settings;paths,rates=synthetic.synthetic_inputs(config,baseline)
    for name,end in [('flat',1.),('volatile_sideways',1.),('sustained_decline',.65),
                     ('prolonged_weakness',.65),('fast_recovery',1.2),('slow_recovery',1.2)]:
        frame=paths[name]
        np.testing.assert_allclose(frame.iloc[0],1.,atol=0,rtol=0)
        np.testing.assert_allclose(frame.iloc[-1],end,atol=2e-15,rtol=0)
        for column in ['momentum','quality','value']:np.testing.assert_array_equal(frame[column],frame.core)
        returns=frame.pct_change(fill_method=None);returns.iloc[0]=0
        np.testing.assert_allclose((1+returns).cumprod(),frame,atol=2e-13,rtol=2e-13)
    np.testing.assert_array_equal(paths['factor_rotation'].iloc[-1],np.full(4,paths['factor_rotation'].core.iloc[-1]))
    assert (paths['factor_lag'].iloc[-1,1:]<=1).all()
    assert len(rates)>len(paths['flat'])


def test_same_crash_and_endpoint_keep_different_recovery_paths(settings):
    baseline,config=settings;paths,_=synthetic.synthetic_inputs(config,baseline)
    fast,slow=paths['fast_recovery'],paths['slow_recovery']
    t=(fast.index-fast.index[0]).days/(fast.index[-1]-fast.index[0]).days
    np.testing.assert_array_equal(fast.loc[t<=.21],slow.loc[t<=.21])
    np.testing.assert_array_equal(fast.iloc[-1],slow.iloc[-1])
    assert (fast.loc[(t>.21)&(t<1)].core>slow.loc[(t>.21)&(t<1)].core).all()


def test_unresolved_recovery_is_censored_and_recovered_date_is_explicit():
    dates=pd.bdate_range('2030-01-02',periods=4)
    unresolved=pd.Series([100.,80.,60.,70.],index=dates)
    row=synthetic.recovery_metrics(unresolved,100.)
    assert row['recovery_censored'] and row['recovery_date']==''
    resolved=pd.Series([100.,80.,60.,110.],index=dates)
    row=synthetic.recovery_metrics(resolved,100.)
    assert not row['recovery_censored'] and row['recovery_date']==str(dates[-1].date())


def test_flat_unlevered_costs_and_borrowing_drag_remain_distinct(settings,monkeypatch):
    baseline,config=settings;paths,rates=synthetic.synthetic_inputs(config,baseline)
    monkeypatch.setattr(synthetic,'synthetic_inputs',lambda *args:({'flat':paths['flat']},rates))
    reduced=dict(config,regimes=['flat'])
    result=synthetic.synthetic_comparison(baseline,reduced)
    table=result['metrics'].query("strategy=='factor_absolute'")
    unlevered=table.query('leverage==1').iloc[0]
    levered=table.query('leverage==1.25 and total_borrow_rate==.06').iloc[0]
    assert unlevered.financing_cost_usd==0 and unlevered.ending_equity_usd<baseline['initial_equity_usd']
    assert levered.financing_cost_usd>0 and levered.ending_equity_usd<unlevered.ending_equity_usd
    assert result['definitions']['unlevered_debt_and_financing_zero']


def test_negative_funding_margin_is_rejected(settings):
    baseline,config=settings;config['exposure_funding_pairs']=[[1.25,.01]]
    with pytest.raises(ValueError,match='funding'):synthetic.validate_settings(config,baseline)
