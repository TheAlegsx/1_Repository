"""Comparator-only zero costs, preserved funding and baseline account identity."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from factor_portfolio.backtest_comparator_costs import comparator_cost_comparison,validate_settings,run_comparator_costs
from factor_portfolio.config import SwissquoteStandardFeeSchedule
from factor_portfolio.historical import simulate

CONFIG=Path(__file__).resolve().parents[1]/'config'


def fixture():
    b=json.loads((CONFIG/'backtest_absolute_decoupled_2026-10-05.json').read_text());s=json.loads((CONFIG/'backtest_comparator_costs_absolute_decoupled_2026-10-05.json').read_text())
    dates=pd.bdate_range('2020-01-02',periods=45,name='date');b['initial_equity_usd']=100000.
    b['periods']['full']=dict(start=str(dates[0].date()),end=str(dates[-1].date()))
    ret=pd.DataFrame({name:.001+.004*np.sin(np.arange(len(dates))*.8+i) for i,name in enumerate(['core','momentum','quality','value','dimensional'])},index=dates);ret.iloc[0]=0.
    ref=pd.Series(.02,index=pd.date_range(dates[0],dates[-1]));return ret,ref,b,s


def test_zero_cost_unlevered_comparator_matches_analytic_nav_compounding():
    ret,ref,b,s=fixture();before=ret.copy(deep=True);r=comparator_cost_comparison(ret,ref,b,s)
    h=r['histories'].query("run_id=='dimensional__no_sleeve__zero_external__1.00'")
    np.testing.assert_allclose(h.equity_usd,b['initial_equity_usd']*(1+ret.dimensional).cumprod(),rtol=1e-14,atol=1e-7)
    assert h.cumulative_transaction_cost_usd.eq(0).all() and h.debt_usd.eq(0).all()
    assert len(r['metrics'])==8 and len(r['comparison'])==4 and len(r['legacy'])==2
    pd.testing.assert_frame_equal(ret,before,check_exact=True)


def test_borrowed_free_comparator_keeps_actual_day_funding_and_margin():
    ret,ref,b,s=fixture();r=comparator_cost_comparison(ret,ref,b,s)
    h=r['histories'].query("run_id=='dimensional__no_sleeve__zero_external__1.25'").set_index('date')
    first=h.iloc[0];assert first.gross_assets_usd==125000 and first.debt_usd==25000 and first.equity_usd==100000
    expected=h.debt_usd.shift(1)*(.02+b['borrowing_margin_annual'])*h.index.to_series().diff().dt.days/360
    np.testing.assert_allclose(h.financing_cost_usd.iloc[1:],expected.iloc[1:],rtol=1e-13,atol=1e-8)
    assert h.cumulative_financing_cost_usd.iloc[-1]>0 and h.transaction_cost_usd.eq(0).all()


def test_factor_paths_and_charges_match_unchanged_baseline_simulator_exactly():
    ret,ref,b,s=fixture();r=comparator_cost_comparison(ret,ref,b,s);fee=SwissquoteStandardFeeSchedule(**b['fee_schedule'])
    for policy in s['factor_policies']:
        for lev in s['leverage_levels']:
            base=simulate(ret[list(b['target_weights'])],ref,list(b['target_weights'].values()),lev,policy,
                margin=b['borrowing_margin_annual'],sleeve_band=b['sleeve_band'],leverage_band=b['leverage_band'],initial_equity_usd=b['initial_equity_usd'],fee_schedule=fee)
            label=f'factor__{policy}__baseline__{lev:.2f}';h=r['histories'].query('run_id==@label').drop(columns='run_id').set_index('date')[base.history.columns]
            e=r['events'].query('run_id==@label').drop(columns='run_id').reset_index(drop=True)
            pd.testing.assert_frame_equal(h,base.history,check_exact=True,check_dtype=False,check_freq=False)
            pd.testing.assert_frame_equal(e,base.events,check_exact=True)
            assert base.history.cumulative_transaction_cost_usd.iloc[-1]>0


def test_summary_keeps_risk_test_and_actual_financing_amounts_separate():
    ret,ref,b,s=fixture();r=comparator_cost_comparison(ret,ref,b,s)
    for row in r['comparison'].itertuples(index=False):
        assert row.factor_cagr_gap==pytest.approx(row.factor_baseline_cagr-row.dimensional_zero_external_cost_cagr)
        assert row.factor_joint_growth_risk_pass==bool(row.factor_cagr_gap>0 and row.factor_volatility<=row.dimensional_zero_external_cost_volatility and row.factor_drawdown>=row.dimensional_zero_external_cost_drawdown)
        assert row.dimensional_baseline_transaction_cost_usd>0 and row.dimensional_zero_external_transaction_cost_usd==0
    borrowed=r['comparison'].query('leverage==1.25')
    assert (borrowed.dimensional_baseline_financing_cost_usd!=borrowed.dimensional_zero_external_financing_cost_usd).all()


def test_invalid_scope_and_incomplete_calendar_are_rejected():
    ret,ref,b,s=fixture()
    for change in [dict(comparator='core'),dict(factor_baseline_transaction_costs=False),dict(retain_reference_and_margin=False),dict(factor_policies=['hybrid20']),dict(leverage_levels=[2.])]:
        with pytest.raises(ValueError):validate_settings(dict(s,**change),b)
    with pytest.raises(ValueError,match='full-period calendar'):comparator_cost_comparison(ret.iloc[1:],ref,b,s)


def test_output_preservation_and_missing_source_failure(tmp_path):
    from factor_portfolio.inflow_workflow import verify_run
    paths=[CONFIG/n for n in ['backtest_absolute_decoupled_2026-10-05.json','backtest_sources.json','backtest_comparator_costs_absolute_decoupled_2026-10-05.json']]
    marker=tmp_path/'existing';marker.write_text('preserved')
    with pytest.raises(FileExistsError):run_comparator_costs(tmp_path/'raw',*paths,tmp_path)
    assert marker.read_text()=='preserved'
    out=tmp_path/'failed'
    with pytest.raises(ValueError,match='source missing'):run_comparator_costs(tmp_path/'raw',*paths,out)
    assert json.loads((out/'run_manifest.json').read_text())['status']=='failed'
    with pytest.raises(ValueError,match='not complete'):verify_run(out)
