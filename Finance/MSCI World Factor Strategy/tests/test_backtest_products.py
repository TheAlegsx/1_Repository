"""Extra source admission and separate post-entry short-window normalization."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from factor_portfolio import backtest_products as products

ROOT=Path(__file__).resolve().parents[1]


def test_additional_source_checksums_and_root_containment(tmp_path):
    settings=json.loads((ROOT/'config/backtest_products_absolute_decoupled_2026-10-05.json').read_text())
    for item in settings['sources']:
        path=tmp_path/item['path'];path.parent.mkdir(parents=True,exist_ok=True);path.write_text('admission fixture '+item['role'])
        item['sha256']=products.sha256(path)
    products.admit_sources(tmp_path,settings)
    first=settings['sources'][0];(tmp_path/first['path']).write_text('substituted source')
    with pytest.raises(ValueError,match='checksum mismatch'):products.admit_sources(tmp_path,settings)
    escaped=copy.deepcopy(settings);escaped['sources'][0]['path']='../outside'
    with pytest.raises(ValueError,match='outside raw root'):products.admit_sources(tmp_path,escaped)


def test_short_overlap_normalizes_without_changing_long_main_calendar():
    baseline=json.loads((ROOT/'config/backtest_absolute_decoupled_2026-10-05.json').read_text())
    baseline['initial_equity_usd']=12000
    settings=json.loads((ROOT/'config/backtest_products_absolute_decoupled_2026-10-05.json').read_text())
    dates=pd.bdate_range('2025-01-02',periods=40,name='date')
    ret=pd.DataFrame({c:.002+.003*np.sin(np.arange(40)+i) for i,c in enumerate(['core','momentum','quality','value'])},index=dates)
    ret.iloc[0]=0;nav=(1+ret).cumprod()*10
    common=dates[10:];short=common.delete(5)
    market=SimpleNamespace(benchmark_overlap=pd.DataFrame({
        'mxwoldnu_index_level_usd':100*(nav.core.loc[common]/nav.core.loc[common[0]])**2,
        'amundi_2x_nav_usd':90*(nav.core.loc[common]/nav.core.loc[common[0]])**1.9},index=common))
    # One ETF observation is absent: intersect levels, do not fill it.
    nav=nav.drop(common[5]);ret=nav.pct_change(fill_method=None);ret.iloc[0]=0
    dataset=SimpleNamespace(nav_usd=nav,returns_usd=ret)
    settings.update(expected_common=dict(start=str(short[0].date()),end=str(short[-1].date()),levels=len(short)),expected_market_levels=len(common))
    reference=pd.Series(.02,index=pd.date_range(dates[0],dates[-1]))
    original=copy.deepcopy(baseline)
    result=products.product_comparison(dataset,reference,market,baseline,settings)
    assert len(result['metrics'])==7 and len(result['curves'])==len(short)
    np.testing.assert_allclose(result['curves'].iloc[0,1:].to_numpy(float),1.,atol=0,rtol=0)
    assert result['definitions']['excluded_market_dates']==[str(common[5].date())]
    assert baseline==original
    # The privacy-neutral package default is USD 10k; explicit configured capital must win.
    entry=result['reference'].levels.core_banded_2x_equity_usd.iloc[0]
    assert 11000<entry<12000
    assert result['legacy_metrics'].strategy.iloc[0]=='factor_hybrid_1.25x'


def test_wrong_calendar_contract_is_rejected():
    baseline=json.loads((ROOT/'config/backtest_absolute_decoupled_2026-10-05.json').read_text())
    settings=json.loads((ROOT/'config/backtest_products_absolute_decoupled_2026-10-05.json').read_text())
    settings['expected_common']['levels']=1
    with pytest.raises(ValueError,match='calendar'):products.validate_settings(settings,baseline)
