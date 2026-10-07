"""No-flow exactness, cost-inclusive cash scaling and cohort conservation."""
import numpy as np
import pandas as pd
import pytest

from factor_portfolio.config import FeeSchedule
from factor_portfolio.historical import simulate
from factor_portfolio.coupled_inflow_accounting import flow_target,simulate_coupled

WEIGHTS=[.6,.15,.1,.15]


def fixture():
    dates=pd.bdate_range('2020-01-02',periods=6,name='date');ret=pd.DataFrame(0.,index=dates,columns=['core','momentum','quality','value']);ref=pd.Series(0.,index=pd.date_range(dates[0],dates[-1]));return ret,ref


def events(dates,subs,redemptions=None,fees=None):
    n=len(dates)
    return pd.DataFrame(dict(event_date=dates,month=list(range(1,n+1)),project_year=[1]*n,scheduled_subscription_usd=subs,
        monthly_external_unit_redemption_fraction=[0.]*n if redemptions is None else redemptions,
        proposed_fund_fee_fraction=[0.]*n if fees is None else fees))


def test_net_flow_preserves_mix_precost_leverage_and_finances_actual_costs():
    pos=np.array([60.,15.,10.,15.]);target,debt,cost,_=flow_target(pos,20.,40.,lambda delta:float(np.abs(delta).sum()*.01))
    expected=.0125*40
    assert cost==pytest.approx(expected,abs=1e-10)
    assert target.sum()-debt==pytest.approx(80+40-cost)
    np.testing.assert_allclose(target/target.sum(),WEIGHTS,atol=1e-15)
    assert target.sum()/(target.sum()-debt+cost)==pytest.approx(1.25)
    assert target.sum()/(target.sum()-debt)>1.25
    target,debt,_,_=flow_target(np.array([66.,16.5,11.,16.5]),10.,30.,lambda delta:0.)
    assert target.sum()/(target.sum()-debt)==pytest.approx(1.1)  # not reset to 1.25


def test_discontinuous_fee_step_posts_exact_cost_instead_of_forcing_a_fixed_point():
    pos=np.array([60.,15.,10.,15.])
    def stepped(delta):return 4. if np.abs(delta).sum()>45 else 1.
    target,debt,cost,_=flow_target(pos,20.,40.,stepped)
    assert cost==4. and debt==34.
    assert target.sum()-debt==116. and target.sum()==150.


def test_no_flow_zero_added_fee_matches_all_original_observations_and_events():
    ret,ref=fixture()
    for i,c in enumerate(ret):ret[c]=.03*np.sin(np.arange(len(ret))+i)
    ret.iloc[0]=0
    for policy in ['absolute_decoupled','hybrid20']:
        base=simulate(ret,ref,WEIGHTS,1.25,policy,initial_equity_usd=100000.)
        f=events([ret.index[2],ret.index[-1]],[0.,0.])
        run=simulate_coupled(ret,ref,WEIGHTS,1.25,policy,initial_equity_usd=100000.,flows=f)
        pd.testing.assert_frame_equal(run.history[base.history.columns],base.history,check_exact=True)
        pd.testing.assert_frame_equal(run.events,base.events,check_exact=True)
        assert len(run.monthly)==2


def test_subscription_and_redemption_reconcile_units_debt_and_cash():
    ret,ref=fixture();f=events([ret.index[2],ret.index[-1]],[5000.,0.],[0.,.2])
    run=simulate_coupled(ret,ref,WEIGHTS,1.25,'absolute_decoupled',margin=0.,initial_equity_usd=10000.,fee_schedule=FeeSchedule(),flows=f)
    first,last=run.monthly.iloc[0],run.monthly.iloc[1]
    assert first.owner_units==100 and first.external_units==50 and first.closing_aum_usd==15000
    assert last.redemptions_usd==1000 and last.external_units==40 and last.owner_equity_usd==10000
    assert last.closing_aum_usd==14000 and run.history.debt_usd.iloc[-1]==pytest.approx(3500)
    assert run.history.unit_nav.eq(100.).all()


def test_flow_trade_costs_dilute_remaining_units_and_are_not_duplicated():
    ret,ref=fixture();f=events([ret.index[-1]],[5000.])
    run=simulate_coupled(ret,ref,WEIGHTS,1.25,'absolute_decoupled',margin=0.,initial_equity_usd=10000.,fee_schedule=FeeSchedule(proportional_rate=.01),flows=f)
    m=run.monthly.iloc[0];h=run.history.iloc[-1]
    assert m.closing_unit_nav<m.quote_unit_nav and m.owner_units==100
    assert h.equity_usd==pytest.approx(15000-h.cumulative_transaction_cost_usd,abs=1e-7)
    assert run.events.fees_usd.sum()==pytest.approx(h.cumulative_transaction_cost_usd,abs=1e-7)
    assert m.owner_equity_usd+m.external_equity_usd==pytest.approx(m.closing_aum_usd)


def test_monthly_fund_fee_uses_previous_opening_assets_not_grown_closing_assets():
    ret,ref=fixture();ret.iloc[1]=.1;f=events([ret.index[-1]],[5000.],fees=[.001])
    run=simulate_coupled(ret,ref,WEIGHTS,1.25,'absolute_decoupled',margin=0.,initial_equity_usd=10000.,fee_schedule=FeeSchedule(),flows=f)
    m=run.monthly.iloc[0]
    assert m.owner_fee_usd==10 and m.external_fee_usd==0 and m.fund_fee_usd==10
    assert m.quote_unit_nav==pytest.approx(112.4)
    assert m.closing_aum_usd==pytest.approx(16240)


def test_invalid_or_off_calendar_flows_and_insolvent_redemption_are_rejected():
    ret,ref=fixture();f=events([pd.Timestamp('2021-01-01')],[1000.])
    with pytest.raises(ValueError,match='valuation dates'):simulate_coupled(ret,ref,WEIGHTS,flows=f)
    f=events([ret.index[-1]],[-10.])
    with pytest.raises(ValueError,match='amount/fraction'):simulate_coupled(ret,ref,WEIGHTS,flows=f)
    with pytest.raises(ArithmeticError,match='exhausts'):flow_target(np.array([60.,15.,10.,15.]),20.,-90.,lambda delta:0.)


def test_legacy_execution_version_and_existing_output_are_rejected(tmp_path):
    from pathlib import Path
    from factor_portfolio.historical_inflow_replay import run_replay
    root=Path(__file__).resolve().parents[1]/'config'
    paths=[root/n for n in ['backtest_absolute_decoupled_2026-10-05.json','backtest_sources.json','inflow_acquisition.json',
        'inflow_timing.json','historical_inflows_contract_2026-10-05.json','historical_inflows_execution_2026-10-05.json']]
    out=tmp_path/'rejected'
    with pytest.raises(ValueError,match='identify the preserved'):run_replay(tmp_path/'raw',*paths,out)
    assert not out.exists()
    out.mkdir()
    with pytest.raises(FileExistsError):run_replay(tmp_path/'raw',*paths,out)
