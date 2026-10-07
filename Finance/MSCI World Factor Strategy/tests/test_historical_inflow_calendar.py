"""Actual anniversary valuations, entry-cost preservation and untouched flow totals."""
import copy
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from factor_portfolio.historical_inflow_calendar import historical_calendar,return_basis,flow_plans,validate_contract

ROOT=Path(__file__).resolve().parents[1]


def test_anniversary_boundary_defers_to_available_nav_without_future_return_selection():
    dates=pd.bdate_range('2014-10-03','2015-11-04')
    dates=dates[~dates.isin(pd.to_datetime(['2015-05-04']))]
    c=historical_calendar(dates,'2014-10-03',12)
    assert c.iloc[6].nominal_end=='2015-05-03' and c.iloc[6].actual_end=='2015-05-05'
    assert c.iloc[11].actual_end=='2015-10-05'
    assert c.actual_start.iloc[0]=='2014-10-03' and c.actual_end.is_unique
    with pytest.raises(ValueError,match='cover'):historical_calendar(dates,'2014-10-03',120)
    with pytest.raises(ValueError,match='ordered'):historical_calendar(dates[::-1],'2014-10-03',12)


def test_opening_cost_occurs_once_and_monthly_gains_compound_to_source_wealth():
    dates=pd.bdate_range('2014-10-03','2015-11-04');calendar=historical_calendar(dates,'2014-10-03',12)
    eq=990.*np.exp(np.arange(len(dates))*.001)
    h=pd.DataFrame({'date':dates,'equity_usd':eq,'transaction_cost_usd':[10.]+[0.]*(len(dates)-1)})
    basis,check=return_basis(h,calendar,1000.,'absolute_decoupled')
    assert check['initial_unit_nav_after_cost']==99. and check['owner_units']==10.
    last=float(h.set_index('date').loc[calendar.actual_end.iloc[-1],'equity_usd'])
    assert basis.no_flow_zero_added_fee_owner_equity_usd.iloc[-1]==pytest.approx(last,abs=1e-9)
    assert 1000*np.prod(1+basis.strategy_net_interval_return)!=pytest.approx(last,abs=1e-6)
    h.loc[0,'transaction_cost_usd']=0.
    with pytest.raises(ValueError,match='exactly once'):return_basis(h,calendar,1000.,'absolute_decoupled')


def test_flow_mapping_retains_all_gross_totals_launch_delay_and_no_stress_feedback():
    b=json.loads((ROOT/'config/inflow_acquisition.json').read_text());t=json.loads((ROOT/'config/inflow_timing.json').read_text())
    dates=pd.bdate_range('2014-10-03','2024-10-08');c=historical_calendar(dates,'2014-10-03')
    original_b=copy.deepcopy(b);original_t=copy.deepcopy(t);plans,totals=flow_plans(c,b,t)
    assert len(plans)==1320 and totals['acquisition/steady']==27500000
    assert totals['acquisition/limited']==4000000 and totals['acquisition/strong']==55000000
    assert all(totals['timing/'+k]==27500000 for k in t['monthly_schedules_usd'] if k!='no_flows')
    assert plans[plans.month<=6].scheduled_subscription_usd.eq(0).all()
    assert not plans.future_return_conditioning.any() and not plans.executed_cash_flow.any()
    assert b==original_b and t==original_t


def test_contract_rejects_unmatched_capital_and_changed_horizon():
    b=json.loads((ROOT/'config/backtest_absolute_decoupled_2026-10-05.json').read_text());a=json.loads((ROOT/'config/inflow_acquisition.json').read_text());t=json.loads((ROOT/'config/inflow_timing.json').read_text());c=json.loads((ROOT/'config/historical_inflows_contract_2026-10-05.json').read_text())
    validate_contract(c,b,a,t)
    changed=copy.deepcopy(c);changed['project_months']=143
    with pytest.raises(ValueError,match='120'):validate_contract(changed,b,a,t)
    changed=copy.deepcopy(a);changed['initial_owner_capital_usd']=10000
    with pytest.raises(ValueError,match='owner capital'):validate_contract(c,b,changed,t)
