"""Separate cost mathematics, explicit day funding and independent state timing."""
import ast
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from factor_portfolio import independent_scalar as scalar
from factor_portfolio.backtest_independent_core import comparison_rows,run_independent_core

FEE=dict(usd_per_chf=1.,platform_fee_usd=.85,stamp_duty_rate=.0015,spread_rate=.0005)


def levels(columns=('core',),periods=4):
    dates=pd.bdate_range('2020-01-03',periods=periods,name='date');l=pd.DataFrame(100.,index=dates,columns=columns)
    r=pd.Series(.02,index=pd.date_range(dates[0],dates[-1]));return l,r


def test_no_production_imports_and_independent_fee_brackets():
    tree=ast.parse(Path(scalar.__file__).read_text())
    imports=[x.module for x in ast.walk(tree) if isinstance(x,ast.ImportFrom)]
    assert imports==['__future__']
    assert scalar.charge([0.,1e-13],FEE)==0
    assert scalar.charge([500.],FEE)==pytest.approx(4.85)
    assert scalar.charge([-501.],FEE)==pytest.approx(6.852)
    assert scalar.charge([500.],FEE,.01)==pytest.approx(9.85)


def test_flat_unlevered_initial_fee_solves_analytic_capital_identity():
    l,r=levels();out,h,e=scalar.calculate(l,r,[1.],1.,'no_sleeve',initial_equity_usd=10000.,fee_parameters=FEE)
    cost=(29.85+.002*10000)/1.002
    assert e.fees_usd.iloc[0]==pytest.approx(cost,abs=1e-9)
    assert h.equity_usd.eq(h.equity_usd.iloc[0]).all() and h.debt_usd.abs().max()<1e-7
    assert out['ending_equity_usd']==pytest.approx(10000-cost) and out['trades_after_entry']==0
    assert out['maximum_drawdown']==pytest.approx(-cost/10000)


def test_borrowing_uses_prior_debt_and_actual_weekend_days():
    l,r=levels();out,h,e=scalar.calculate(l,r,[1.],1.25,'no_sleeve',initial_equity_usd=12000.,fee_parameters=FEE)
    assert (h.date.iloc[1]-h.date.iloc[0]).days==3
    assert h.financing_cost_usd.iloc[1]==pytest.approx(h.debt_usd.iloc[0]*.05*3/360,abs=1e-10)
    assert h.financing_cost_usd.iloc[2]==pytest.approx(h.debt_usd.iloc[1]*.05/360,abs=1e-10)
    assert out['financing_cost_usd']>0 and len(e)==1


def test_sleeve_signal_executes_at_following_observation_and_preserves_debt():
    l,r=levels(('core','momentum','quality','value'));l.loc[l.index[1]:,'momentum']=170.
    _,h,e=scalar.calculate(l,r,[.6,.15,.1,.15],1.25,'absolute_decoupled',initial_equity_usd=12000.,fee_parameters=FEE)
    assert h.pending_signal.iloc[1]=='sleeve' and e.reason.tolist()==['initialise','sleeve']
    assert e.date.iloc[1]==l.index[2]
    assert h.debt_usd.iloc[2]==pytest.approx(h.debt_usd.iloc[1]+h.financing_cost_usd.iloc[2],abs=1e-7)


def test_leverage_only_current_mix_and_coupled_legacy_targets_are_distinct():
    l,r=levels(('core','momentum','quality','value'));l.loc[l.index[1]:,'core']=112.;l.loc[l.index[1]:,'momentum']=106.
    for policy in ['absolute_decoupled','legacy_absolute']:
        _,h,e=scalar.calculate(l,r,[.6,.15,.1,.15],1.25,policy,initial_equity_usd=12000.,fee_parameters=FEE,sleeve_band=.3,leverage_band=.01)
        assert h.pending_signal.iloc[1]=='leverage' and e.date.iloc[1]==l.index[2]
        weights=h.filter(regex='^position_').to_numpy()/h.gross_assets_usd.to_numpy()[:,None]
        np.testing.assert_allclose(weights[2],weights[1] if policy=='absolute_decoupled' else [.6,.15,.1,.15],atol=1e-13)


def test_maintenance_priority_and_bad_inputs_are_rejected_or_recorded():
    l,r=levels(('core',));l.loc[l.index[1]:,'core']=70.
    _,h,e=scalar.calculate(l,r,[1.],1.25,'no_sleeve',initial_equity_usd=12000.,fee_parameters=FEE,maintenance=.25)
    assert h.pending_signal.iloc[1]=='margin_call' and e.reason.iloc[1]=='margin_call'
    with pytest.raises(ValueError):scalar.calculate(l.iloc[:2],r,[1.],1.,'no_sleeve',initial_equity_usd=12000.,fee_parameters=FEE)
    with pytest.raises(ValueError):scalar.calculate(l,r.iloc[:1],[1.],1.,'no_sleeve',initial_equity_usd=12000.,fee_parameters=FEE)
    with pytest.raises(ValueError):scalar.calculate(l,r,[1.],1.,'unknown',initial_equity_usd=12000.,fee_parameters=FEE)


def test_comparison_uses_unchanged_currency_metric_and_exact_count_tolerances():
    import json
    cfg=Path(__file__).resolve().parents[1]/'config';b=json.loads((cfg/'backtest_absolute_decoupled_2026-10-05.json').read_text());s=json.loads((cfg/'independent_core_2026-10-05.json').read_text())
    expected={field:1. for field in s['comparison_fields']};observed=dict(expected);observed['trades_after_entry']=2.;observed['cagr']+=2e-9
    rows=comparison_rows(expected,observed,b,s,'test')
    assert not next(x['passed'] for x in rows if x['field']=='trades_after_entry')
    assert not next(x['passed'] for x in rows if x['field']=='cagr')
    assert next(x['allowed_difference'] for x in rows if x['field']=='transaction_cost_usd')==pytest.approx(1e-6+2e-12)


def test_existing_output_and_missing_source_failure(tmp_path):
    import json
    from factor_portfolio.inflow_workflow import verify_run
    cfg=Path(__file__).resolve().parents[1]/'config';paths=[cfg/n for n in ['backtest_absolute_decoupled_2026-10-05.json','backtest_sources.json','independent_core_2026-10-05.json']]
    p=tmp_path/'preserve';p.write_text('old')
    with pytest.raises(FileExistsError):run_independent_core(tmp_path/'raw',*paths,tmp_path)
    assert p.read_text()=='old'
    out=tmp_path/'missing'
    with pytest.raises(ValueError,match='source missing'):run_independent_core(tmp_path/'raw',*paths,out)
    assert json.loads((out/'run_manifest.json').read_text())['status']=='failed'
    with pytest.raises(ValueError,match='not complete'):verify_run(out)
