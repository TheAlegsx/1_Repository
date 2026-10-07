"""Independent rounding intervals, calendar-year scope and visible mismatches."""
import copy
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from factor_portfolio.backtest_issuer_returns import validate_settings,rounding_comparison,issuer_comparison,run_issuer_returns

CONFIG=Path(__file__).resolve().parents[1]/'config'


def fixture():
    s=json.loads((CONFIG/'issuer_annual_returns_2026-10-05.json').read_text());sources=json.loads((CONFIG/'backtest_sources.json').read_text())
    dates=pd.to_datetime([f'{y}-12-31' for y in range(2015,2026)]+['2026-08-28'])
    levels=pd.DataFrame({'date':dates})
    for name,p in s['products'].items():levels[name]=100*1.1**np.arange(len(dates));p['published_returns_pct']=[10.]*10
    return levels,s,sources


def test_ratio_bounds_intersect_published_rounding_and_are_not_exact_equality():
    r=rounding_comparison(10.,11.,10.1,.005,.05)
    assert r['compatible_with_rounding'] and r['difference_percentage_points']==pytest.approx(-.1)
    assert r['nav_rounding_lower_pct']<r['reconstructed_return_pct']<r['nav_rounding_upper_pct']
    assert not rounding_comparison(100.,110.,10.1,.005,.05)['compatible_with_rounding']
    loss=rounding_comparison(100.,90.,-10.,.005,.05)
    assert loss['compatible_with_rounding'] and loss['reconstructed_return_pct']==pytest.approx(-10.)


def test_prior_year_endpoint_and_partial_final_year_scope_preserve_inputs():
    levels,s,sources=fixture();before=levels.copy(deep=True);validate_settings(s,sources)
    table,ends=issuer_comparison(levels,s)
    assert len(table)==40 and len(ends)==44 and table.compatible_with_rounding.all()
    assert table.year.min()==2016 and table.year.max()==2025 and ends.year.min()==2015 and ends.year.max()==2025
    assert table.reconstructed_return_pct.to_numpy()==pytest.approx([10.]*40)
    pd.testing.assert_frame_equal(levels,before,check_exact=True)


def test_common_nav_year_end_deferral_is_visible_and_mismatch_not_suppressed():
    levels,s,_=fixture();levels.loc[levels.date.eq(pd.Timestamp('2016-12-31')),'date']=pd.Timestamp('2016-12-30');s['products']['core']['published_returns_pct'][0]=12.
    table,ends=issuer_comparison(levels,s)
    assert int(ends[(ends.sleeve=='core')&(ends.year==2016)].deferral_days.iloc[0])==1
    assert not bool(table[(table.sleeve=='core')&(table.year==2016)].compatible_with_rounding.iloc[0])
    assert table.compatible_with_rounding.sum()==39


def test_missing_prior_year_truncation_duplicate_or_invalid_nav_is_rejected():
    levels,s,_=fixture()
    with pytest.raises(ValueError,match='calendar-year endpoints'):issuer_comparison(levels.iloc[1:],s)
    bad=levels.copy();bad.loc[0,'date']=pd.Timestamp('2015-11-30')
    with pytest.raises(ValueError,match='truncated'):issuer_comparison(bad,s)
    bad=levels.copy();bad.loc[1,'date']=bad.date.iloc[0]
    with pytest.raises(ValueError,match='ordered NAV calendar'):issuer_comparison(bad,s)
    bad=levels.copy();bad.loc[1,'core']=0.
    with pytest.raises(ValueError,match='positive NAVs'):issuer_comparison(bad,s)
    with pytest.raises(ValueError):rounding_comparison(.005,1.,10.,.005,.05)


def test_identity_precision_and_one_decimal_reference_contract_is_enforced():
    _,s,sources=fixture()
    for field,value in [('isin','wrong'),('nav_rounding_half_width_usd',.005),('published_returns_pct',[10.01]*10)]:
        bad=copy.deepcopy(s);bad['products']['core'][field]=value
        with pytest.raises(ValueError):validate_settings(bad,sources)
    with pytest.raises(ValueError):validate_settings(dict(s,years=list(range(2017,2027))),sources)


def test_existing_output_and_missing_source_failure_are_preserved(tmp_path):
    from factor_portfolio.inflow_workflow import verify_run
    paths=[CONFIG/n for n in ['backtest_absolute_decoupled_2026-10-05.json','backtest_sources.json','issuer_annual_returns_2026-10-05.json']]
    p=tmp_path/'preserve';p.write_text('old')
    with pytest.raises(FileExistsError):run_issuer_returns(tmp_path/'raw',*paths,tmp_path)
    assert p.read_text()=='old'
    out=tmp_path/'missing'
    with pytest.raises(ValueError,match='source missing'):run_issuer_returns(tmp_path/'raw',*paths,out)
    assert json.loads((out/'run_manifest.json').read_text())['status']=='failed'
    with pytest.raises(ValueError,match='not complete'):verify_run(out)
