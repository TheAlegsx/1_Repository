"""Independent margin units, case coverage and fixed-iteration search semantics."""
import copy
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from factor_portfolio.backtest_independent_funding import validate_pair,independent_crossing,compare_crossing,reconcile_funding,run_independent_funding
from factor_portfolio.backtest_funding import funding_comparison

CONFIG=Path(__file__).resolve().parents[1]/'config'


def configs():
    return [json.loads((CONFIG/n).read_text()) for n in ['backtest_absolute_decoupled_2026-10-05.json','backtest_baseline.json','backtest_funding_absolute_decoupled_2026-10-05.json','backtest_funding.json','independent_funding_2026-10-05.json']]


def test_only_policy_differs_between_matched_financing_branches():
    p,l,pf,lf,s=configs();validate_pair(p,l,pf,lf,s)
    altered=copy.deepcopy(l);altered['initial_equity_usd']=10000
    with pytest.raises(ValueError,match='economics differ'):validate_pair(p,altered,pf,lf,s)
    altered=copy.deepcopy(lf);altered['margin_bps']=[0,300]
    with pytest.raises(ValueError,match='grids differ'):validate_pair(p,l,pf,altered,s)


def test_separate_search_preserves_fixed_iterations_exact_midpoint_and_absent_roots():
    r=independent_crossing(lambda bp:bp-5,[0,10],2)
    assert r['margin_bps']==3.75 and len(r['evaluations'])==5
    assert independent_crossing(lambda bp:bp,[0,10],2)['status']=='endpoint_zero'
    r=independent_crossing(lambda bp:1.,[0,10],2)
    assert r['margin_bps'] is None and r['status']=='not_bracketed' and len(r['evaluations'])==2
    with pytest.raises(ValueError):independent_crossing(lambda bp:float('nan'),[0,10],2)
    with pytest.raises(ValueError):independent_crossing(lambda bp:bp,[0,float('inf')],2)


def test_crossing_comparison_uses_existing_limits_and_does_not_invent_a_missing_root():
    _,_,f,_,_=configs();limits=f['reconciliation_tolerances']
    a=dict(margin_bps=500.,difference_at_threshold=1e-10);b=dict(margin_bps=500.01,difference_at_threshold=1e-10)
    assert not compare_crossing(a,b,limits)['passed']
    assert compare_crossing(dict(margin_bps=None),dict(margin_bps=None),limits)['passed']
    assert not compare_crossing(dict(margin_bps=None),b,limits)['passed']


def test_zero_margin_still_accrues_reference_interest_and_full_case_scope_is_required():
    p,_,f,_,s=configs();p['initial_equity_usd']=12000.;dates=pd.bdate_range('2020-01-02',periods=20,name='date')
    p['periods']['full']=dict(start=str(dates[0].date()),end=str(dates[-1].date()));f['periods']=['full'];f['margin_bps']=[0]
    levels=pd.DataFrame({name:100*(1+.002+.007*np.sin(np.arange(len(dates))*.7+i)).cumprod() for i,name in enumerate(['core','momentum','quality','value','dimensional'])},index=dates)
    reference=pd.Series(.02,index=pd.date_range(dates[0],dates[-1]));returns=levels.pct_change(fill_method=None);returns.iloc[0]=0
    production=funding_comparison(returns,reference,p,f)['metrics'];r=reconcile_funding(levels,reference,production,p,f,s,'primary')
    assert r['checks'].passed.all() and len(r['metrics'])==3 and len(r['checks'])==24
    assert r['metrics'].financing_cost_usd.min()>0
    with pytest.raises(ValueError,match='complete declared'):reconcile_funding(levels,reference,production.iloc[:2],p,f,s,'primary')
    changed=production.copy();changed.loc[0,'start']=str(dates[1].date())
    with pytest.raises(ValueError,match='configured period'):reconcile_funding(levels,reference,changed,p,f,s,'primary')


def test_existing_output_and_missing_sources_are_preserved(tmp_path):
    from factor_portfolio.inflow_workflow import verify_run
    p=tmp_path/'preserve';p.write_text('old')
    with pytest.raises(FileExistsError):run_independent_funding(tmp_path/'raw',CONFIG,tmp_path)
    assert p.read_text()=='old'
    out=tmp_path/'missing'
    with pytest.raises(ValueError,match='source missing'):run_independent_funding(tmp_path/'raw',CONFIG,out)
    assert json.loads((out/'run_manifest.json').read_text())['status']=='failed'
    with pytest.raises(ValueError,match='not complete'):verify_run(out)
