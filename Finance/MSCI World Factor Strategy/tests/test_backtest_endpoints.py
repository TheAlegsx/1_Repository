"""Continuing capital, explicit entry-risk conventions and terminal crossings."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from factor_portfolio.backtest_endpoints import build_endpoints,endpoint_metrics,latest_crossing,validate_settings,run_endpoints

CONFIG=Path(__file__).resolve().parents[1]/'config'


def fixture():
    b=json.loads((CONFIG/'backtest_absolute_decoupled_2026-10-05.json').read_text())
    s=json.loads((CONFIG/'backtest_endpoints_absolute_decoupled_v2_2026-10-05.json').read_text())
    dates=pd.to_datetime(['2020-01-02','2020-01-03','2020-01-31','2020-02-28','2020-03-31'])
    b['initial_equity_usd']=100.;b['periods']['full']=dict(start='2020-01-02',end='2020-03-31')
    s['requested_endpoints']=['2020-02-29','2020-03-31']
    frame=pd.DataFrame({'date':dates})
    for lev in s['leverage_levels']:
        frame[f'full_factor_absolute_decoupled_{lev:.2f}']=[95,110,106,104,115]
        frame[f'full_factor_hybrid20_{lev:.2f}']=[95,108,104,102,112]
        frame[f'full_core_{lev:.2f}']=[99,105,106,106,110]
        frame[f'full_dimensional_{lev:.2f}']=[98,104,105,105,109]
    return frame,b,s


def test_existing_investor_risk_folds_opening_cost_without_an_extra_observation():
    dates=pd.to_datetime(['2020-01-02','2020-01-03','2020-01-31'])
    values=np.array([95.,104.5,114.95])
    a=endpoint_metrics(values,dates,100.,'committed_capital_first_interval')
    assert a['volatility']==pytest.approx(np.std([.045,.1],ddof=1)*np.sqrt(252))
    assert a['return_observations']==2 and a['drawdown']==pytest.approx(-.05)
    with pytest.raises(ValueError):endpoint_metrics(values,dates,100.,'extra_opening_observation')


def test_cutoff_maps_backward_without_capital_restart_and_keeps_partial_last_month():
    frame,b,s=fixture();before=frame.copy(deep=True);r=build_endpoints(frame,b,s)
    mapping=r['mapping'][0]
    assert mapping==dict(requested_end='2020-02-29',actual_end='2020-02-28',levels=4,days_before_requested=1)
    row=r['endpoints'].query("strategy=='factor' and policy=='absolute_decoupled' and leverage==1 and requested_end=='2020-02-29' and risk_convention=='committed_capital_first_interval'").iloc[0]
    assert row.cagr==pytest.approx((104/100)**(365.2425/57)-1)
    assert len(r['endpoints'])==16 and len(r['monthly'])==12
    assert r['monthly'].date.unique().tolist()==['2020-01-31','2020-02-28','2020-03-31']
    pd.testing.assert_frame_equal(frame,before,check_exact=True)


def test_latest_positive_run_is_distinct_from_first_outperformance_and_equality_is_nonpositive():
    dates=pd.bdate_range('2020-01-02',periods=5)
    r=latest_crossing([99.,101.,100.,102.,103.],[100.]*5,dates)
    assert r['last_nonpositive_date']==str(dates[2].date())
    assert r['next_positive_date']==str(dates[3].date()) and r['previous_positive_observations']==1
    assert r['status']=='terminal_positive_run'
    r=latest_crossing([101.]*5,[100.]*5,dates)
    assert r['status']=='positive_at_every_observation' and r['last_nonpositive_date'] is None
    r=latest_crossing([101.,102.,103.,104.,100.],[100.]*5,dates)
    assert r['status']=='terminal_not_positive' and r['next_positive_date'] is None


def test_monthly_joint_pass_uses_growth_volatility_and_drawdown_not_just_wealth():
    frame,b,s=fixture();r=build_endpoints(frame,b,s)
    row=r['monthly'].query("policy=='absolute_decoupled' and leverage==1 and risk_convention=='committed_capital_first_interval'").iloc[-1]
    assert row.cagr_gap_pp>0 and row.vol_gap_pp>0 and row.drawdown_gap_pp<0 and not row.joint_pass


def test_missing_duplicate_nonpositive_or_unordered_inputs_are_rejected():
    frame,b,s=fixture()
    with pytest.raises(ValueError,match='complete declared'):build_endpoints(frame.iloc[1:],b,s)
    bad=frame.copy();bad.loc[1,'date']=bad.loc[0,'date']
    with pytest.raises(ValueError,match='unique ordered'):build_endpoints(bad,b,s)
    bad=frame.copy();bad.iloc[2,1]=0
    with pytest.raises(ValueError,match='positive curves'):build_endpoints(bad,b,s)
    with pytest.raises(ValueError):endpoint_metrics([100,90,95],['2020-01-03','2020-01-02','2020-01-04'],100,'committed_capital_first_interval')


def test_settings_reject_mixed_policies_or_undeclared_cutoffs_and_risk_rules():
    _,b,s=fixture()
    for change in [dict(factor_policies=['hybrid20']),dict(requested_endpoints=['2020-04-01']),dict(risk_conventions=['extra_opening_observation']),dict(minimum_levels=2)]:
        with pytest.raises(ValueError):validate_settings(dict(s,**change),b)


def test_existing_output_is_preserved(tmp_path):
    p=tmp_path/'evidence';p.write_text('unchanged')
    with pytest.raises(FileExistsError):run_endpoints(tmp_path/'raw',CONFIG/'backtest_absolute_decoupled_2026-10-05.json',CONFIG/'backtest_sources.json',CONFIG/'backtest_endpoints_absolute_decoupled_v2_2026-10-05.json',tmp_path)
    assert p.read_text()=='unchanged'


def test_invalid_settings_make_no_output_and_missing_raw_run_is_marked_failed(tmp_path):
    from factor_portfolio.inflow_workflow import verify_run
    settings=json.loads((CONFIG/'backtest_endpoints_absolute_decoupled_v2_2026-10-05.json').read_text())
    settings['minimum_levels']=2;bad=tmp_path/'bad.json';bad.write_text(json.dumps(settings))
    out=tmp_path/'invalid'
    with pytest.raises(ValueError,match='three levels'):run_endpoints(tmp_path/'raw',CONFIG/'backtest_absolute_decoupled_2026-10-05.json',CONFIG/'backtest_sources.json',bad,out)
    assert not out.exists()
    out=tmp_path/'missing'
    with pytest.raises(ValueError,match='source missing'):run_endpoints(tmp_path/'raw',CONFIG/'backtest_absolute_decoupled_2026-10-05.json',CONFIG/'backtest_sources.json',CONFIG/'backtest_endpoints_absolute_decoupled_v2_2026-10-05.json',out)
    assert json.loads((out/'run_manifest.json').read_text())['status']=='failed'
    with pytest.raises(ValueError,match='not complete'):verify_run(out)
