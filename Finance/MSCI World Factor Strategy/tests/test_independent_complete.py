"""Independent audit membership, source parsing, risk and forced-execution contracts."""
import ast
import copy
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from factor_portfolio.backtest_independent_complete import (
    case_definitions, validate_case_tables, validate_scope, run_complete,
    account_checks, compare_event_paths, compare_artificial_daily, ENTRY, MARGIN, GRID, SYNTHETIC, KEYS)
from factor_portfolio.independent_validation import risk_statistics, spreadsheet_nav
from factor_portfolio.independent_scalar import calculate
from factor_portfolio.historical import simulate
from factor_portfolio.config import SwissquoteStandardFeeSchedule

CONFIG=Path(__file__).resolve().parents[1]/'config'
def load(name): return json.loads((CONFIG/name).read_text())


def test_declared_families_cover_original_508_remaining_without_counting_extensions():
    baseline=load('backtest_absolute_decoupled_2026-10-05.json')
    cases=case_definitions(baseline,*[load(n) for n in [ENTRY,MARGIN,GRID,SYNTHETIC]])
    assert len(cases)==636
    assert {f:sum(c['retained'] for c in cases if c['family']==f) for f in KEYS}==dict(entry=30,margin=18,grid=300,synthetic=160)
    assert len({(c['family'],c['key']) for c in cases})==636
    c=next(c for c in cases if c['family']=='grid' and c['key']==('W13-SB05-LB10',1.25))
    assert c['policy']=='legacy_absolute' and c['weights']==[.6,.15,.1,.15]
    validate_scope(load('independent_complete_2026-10-06.json'))
    bad=load('independent_complete_2026-10-06.json');bad['retained_case_families']['synthetic']=159
    with pytest.raises(ValueError,match='complete original'):validate_scope(bad)


def test_missing_duplicate_and_failed_case_membership_are_rejected():
    b=load('backtest_absolute_decoupled_2026-10-05.json');cases=case_definitions(b,*[load(n) for n in [ENTRY,MARGIN,GRID,SYNTHETIC]])
    tables={f:pd.DataFrame([dict(zip(KEYS[f],c['key']),status='complete') for c in cases if c['family']==f]) for f in KEYS}
    validate_case_tables(cases,tables)
    missing=dict(tables,entry=tables['entry'].iloc[:-1])
    with pytest.raises(ValueError,match='unique independent'):validate_case_tables(cases,missing)
    duplicate=dict(tables,margin=pd.concat([tables['margin'],tables['margin'].iloc[:1]]))
    with pytest.raises(ValueError,match='unique independent'):validate_case_tables(cases,duplicate)
    failed=copy.deepcopy(tables);failed['grid'].loc[0,'status']='insolvent'
    with pytest.raises(ValueError,match='complete production'):validate_case_tables(cases,failed)


def test_centered_regression_known_beta_and_committed_capital_cost_convention():
    dates=pd.date_range('2020-01-01',periods=10);r=np.array([.01,-.02,.015,.006,-.008,.03,.002,-.01,.013])
    market=pd.Series(np.r_[100,100*np.cumprod(1+r)],index=dates)
    equity=pd.Series(np.r_[100,100*np.cumprod(1+2*r)],index=dates);ref=pd.Series(0.,index=dates)
    result=risk_statistics(equity,market,ref,100)
    assert result['beta_vs_unlevered_core']==pytest.approx(2,abs=1e-12)
    assert abs(result['jensen_alpha'])<1e-12 and result['alpha_hac_se']<1e-12
    changed=equity.copy();changed.iloc[0]=99
    adjusted=risk_statistics(changed,market,ref,100)
    assert adjusted['annualised_volatility']==result['annualised_volatility']
    with pytest.raises(ValueError,match='reference intervals'):risk_statistics(equity,market,ref.drop(dates[3]),100)


def test_separate_source_reader_handles_sparse_cells_and_rejects_currency_and_duplicates(tmp_path):
    def xml(currency='USD',repeat=False):
        row=f'<Row><Cell><Data>03/Oct/2014</Data></Cell><Cell><Data>{currency}</Data></Cell><Cell ss:Index="3"><Data>12.5</Data></Cell></Row>'
        return '<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet" xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet"><Worksheet ss:Name="Historical"><Table>'+row+(row if repeat else '')+'</Table></Worksheet></Workbook>'
    p=tmp_path/'source.xls';p.write_text(xml());s=spreadsheet_nav(p,'core')
    assert s.loc['2014-10-03']==12.5
    p.write_text(xml('CHF'))
    with pytest.raises(ValueError,match='currency'):spreadsheet_nav(p,'core')
    p.write_text(xml(repeat=True))
    with pytest.raises(ValueError,match='duplicate'):spreadsheet_nav(p,'core')


def test_independent_maintenance_priority_next_observation_costs_and_corrupted_events():
    b=load('backtest_absolute_decoupled_2026-10-05.json');b['initial_equity_usd']=100000
    dates=pd.date_range('2020-01-01',periods=7,name='date');levels=pd.DataFrame({'core':[100,100,78,79,80,81,82],'momentum':[100,100,77,80,81,82,83]},index=dates)
    ref=pd.Series(.03,index=dates);returns=levels.pct_change();returns.iloc[0]=0
    production=simulate(returns,ref,[.6,.4],1.25,'absolute_decoupled',maintenance=.25,extra_liquidation_spread=.01,
        initial_equity_usd=b['initial_equity_usd'],fee_schedule=SwissquoteStandardFeeSchedule(**b['fee_schedule']))
    metrics,h,e=calculate(levels,ref,[.6,.4],1.25,'absolute_decoupled',maintenance=.25,extra=.01,initial_equity_usd=b['initial_equity_usd'],fee_parameters=b['fee_schedule'])
    assert h.pending_signal.iloc[2]=='margin_call' and e[e.reason.eq('margin_call')].date.iloc[0]==dates[3]
    assert metrics['margin_calls']==1 and account_checks(h,e,b)['passed']
    compare_event_paths(e,production.events,b)
    damaged=production.events.copy();damaged.loc[1,'date']=dates[4]
    with pytest.raises(ValueError,match='date/reason'):compare_event_paths(e,damaged,b)
    damaged=production.events.copy();damaged.loc[1,'fees_usd']+=1
    with pytest.raises(ValueError,match='trade values'):compare_event_paths(e,damaged,b)


def test_existing_destinations_and_failed_runs_are_preserved(tmp_path):
    from factor_portfolio.inflow_workflow import verify_run
    (tmp_path/'original').write_text('preserve')
    with pytest.raises(FileExistsError):run_complete(tmp_path/'raw',CONFIG,tmp_path)
    assert (tmp_path/'original').read_text()=='preserve'
    out=tmp_path/'failed'
    with pytest.raises(ValueError,match='source missing'):run_complete(tmp_path/'raw',CONFIG,out)
    assert json.loads((out/'run_manifest.json').read_text())['status']=='failed'
    with pytest.raises(ValueError,match='not complete'):verify_run(out)


def test_artificial_target_metadata_is_distinct_from_actual_account_leverage():
    b=load('backtest_absolute_decoupled_2026-10-05.json')
    h=pd.DataFrame(dict(date=pd.date_range('2020-01-01',periods=3),gross_assets_usd=[125.,120.,110.],
        equity_usd=[100.,95.,85.],leverage=[1.25,120/95,110/85],pending_signal=['','','']))
    saved=h.copy();saved['leverage']=1.25
    assert compare_artificial_daily(h,saved,b)['passed']
    damaged=h.copy();damaged.loc[2,'leverage']+=.01
    with pytest.raises(ValueError,match='account/signal'):compare_artificial_daily(damaged,saved,b)


def test_independent_numeric_modules_have_no_production_model_reader_or_metric_imports():
    source=Path(__file__).resolve().parents[1]/'src/factor_portfolio'
    for name in ['independent_scalar.py','independent_validation.py']:
        tree=ast.parse((source/name).read_text())
        imports=[n for n in ast.walk(tree) if isinstance(n,(ast.Import,ast.ImportFrom))]
        assert all(not isinstance(n,ast.ImportFrom) or n.level==0
            or (n.level==1 and n.module=='security_io'
                and {a.name for a in n.names}.issubset({'read_bounded_bytes','parse_bounded_xml',
                    'validate_xlsx','MAX_SHEET_COLUMNS'})) for n in imports)
        assert not any(isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id in {'exec','eval'} for n in ast.walk(tree))
    # The one shared boundary utility must not introduce a production model,
    # data-column reader or metrics dependency into the separate calculation.
    boundary=ast.parse((source/'security_io.py').read_text())
    for node in ast.walk(boundary):
        if isinstance(node,ast.Import):
            assert all(a.name.split('.')[0] in __import__('sys').stdlib_module_names for a in node.names)
        elif isinstance(node,ast.ImportFrom):
            assert node.level==0 and node.module.split('.')[0] in __import__('sys').stdlib_module_names
