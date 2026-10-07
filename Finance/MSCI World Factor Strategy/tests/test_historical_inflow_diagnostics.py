"""Actual-date roots, explicit ambiguity and outside-fund manager budgets."""
import json
import math
from pathlib import Path

import pandas as pd
import pytest

from factor_portfolio.historical_inflow_diagnostics import dated_mwr,investor_diagnostics,manager_accounts,run_diagnostics

CONFIG=Path(__file__).resolve().parents[1]/'config'
SETTINGS=json.loads((CONFIG/'historical_inflows_diagnostics_2026-10-05.json').read_text())
BUSINESS=json.loads((CONFIG/'inflow_acquisition.json').read_text())


def test_actual_dates_and_same_date_aggregation_determine_annualisation():
    result=dated_mwr(['2022-01-01','2021-01-01','2021-01-01'],[110.,-60.,-40.],SETTINGS)
    assert result['annual_mwr']==pytest.approx(1.1**(365.2425/365)-1,abs=1e-14)
    assert result['status']=='unique_root_in_scanned_range'
    assert abs(result['npv_residual_usd'])<1e-10


def test_multiple_roots_are_retained_without_selecting_one():
    result=dated_mwr(['2021-01-01','2022-01-01','2023-01-01'],[-100.,230.,-132.],SETTINGS)
    assert result['status']=='multiple_scanned_roots' and result['annual_mwr'] is None
    expected=[math.log(1.1)*365.2425/365,math.log(1.2)*365.2425/365]
    assert [r['log_annual_discount'] for r in result['roots']]==pytest.approx(expected,abs=1e-13)


def test_outside_scanned_range_is_not_extrapolated():
    result=dated_mwr(['2021-01-01','2022-01-01'],[-100.,1000.],SETTINGS)
    assert result['status']=='no_root_in_scanned_range' and result['annual_mwr'] is None


def test_no_external_cash_has_no_investor_return():
    result=dated_mwr(['2021-01-01','2022-01-01'],[0.,0.],SETTINGS)
    assert result['status']=='undefined_no_invested_external_cohort' and result['annual_mwr'] is None


def test_investor_cash_includes_only_external_flows_and_terminal_external_value():
    coupled=pd.DataFrame(dict(run_id=['absolute_decoupled__acquisition__steady']*2,month=[1,2],
        event_date=['2021-01-01','2022-01-01'],closing_unit_nav=[100.,110.],quote_unit_nav=[100.,110.],
        subscriptions_usd=[100.,0.],redemptions_usd=[0.,22.],external_equity_usd=[100.,88.],owner_equity_usd=[700.,770.]))
    overlay=pd.DataFrame(columns=['run_id'])
    returns,cash,roots=investor_diagnostics(coupled,overlay,dict(start='2020-01-01',initial_unit_nav=100.),SETTINGS)
    assert cash.net_investor_cash_flow_usd.tolist()==[-100.,110.]
    assert cash.terminal_external_value_usd.tolist()==[0.,88.]
    assert returns.aggregate_external_mwr_annual.iloc[0]==pytest.approx(1.1**(365.2425/365)-1)
    assert returns.external_window_unit_twr_annual.iloc[0]==pytest.approx(returns.aggregate_external_mwr_annual.iloc[0])
    assert returns.fund_unit_twr_annual.iloc[0]==pytest.approx(1.1**(365.2425/731)-1)


def test_invalid_cash_and_conventions_are_rejected():
    with pytest.raises(ValueError):dated_mwr(['2021-01-01','2022-01-01'],[-100.,float('nan')],SETTINGS)
    with pytest.raises(ValueError):dated_mwr(['2021-01-01','2022-01-01'],[100.,110.],SETTINGS)
    with pytest.raises(ValueError):dated_mwr(['2021-01-01','2022-01-01'],[-100.,110.],dict(SETTINGS,year_days=365))


def test_manager_cash_distinguishes_external_receipts_and_conditional_owner_receipts():
    data=pd.DataFrame(dict(run_id=['test']*2,month=[1,13],project_year=[1,2],event_date=['2021-01-01','2022-01-01'],
        subscriptions_usd=[10000.,0.],opening_external_aum_usd=[0.,5000.],external_fee_usd=[10.,20.],owner_fee_usd=[30.,40.]))
    before=data.copy(deep=True)
    monthly,annual,head=manager_accounts(data,BUSINESS)
    pd.testing.assert_frame_equal(data,before,check_exact=True)
    g=monthly[monthly.manager_receipt_fraction==.5]
    assert g.external_fee_receipts_usd.tolist()==[5.,10.]
    assert g.conditional_owner_fee_receipts_usd.tolist()==[15.,20.]
    assert g.setup_cost_usd.tolist()==[25000.,0.]
    assert g.fixed_cost_usd.tolist()==pytest.approx([25000/12,25500/12])
    assert g.acquisition_cost_usd.tolist()==[50.,0.]
    assert g.servicing_cost_usd.tolist()==pytest.approx([0.,5000*.0002/12])
    h=head[head.manager_receipt_fraction==.5].iloc[0]
    assert h.conditional_total_fee_treasury_usd-h.cumulative_external_business_cash_usd==pytest.approx(35.)
    assert h.external_business_peak_funding_gap_usd==pytest.approx(-h.cumulative_external_business_cash_usd)
    assert annual[annual.manager_receipt_fraction==.5].external_fee_receipts_usd.sum()==15.


def test_existing_output_is_preserved(tmp_path):
    marker=tmp_path/'preserve.txt';marker.write_text('old evidence')
    with pytest.raises(FileExistsError):run_diagnostics(tmp_path/'raw',CONFIG,tmp_path)
    assert marker.read_text()=='old evidence'
