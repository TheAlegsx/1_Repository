"""Date mapping and cash-account restarts, never slices of an ongoing portfolio."""
import copy
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from factor_portfolio import backtest_entries as entries
from factor_portfolio.historical import simulate, metrics

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def inputs():
    baseline = json.loads((ROOT/'config/backtest_absolute_decoupled_2026-10-05.json').read_text())
    dates = pd.bdate_range('2020-01-02',periods=32,name='date')
    baseline['initial_equity_usd'] = 12000
    baseline['periods']['full'] = dict(start=str(dates[0].date()),end=str(dates[-1].date()))
    ret = pd.DataFrame({c:.002+.003*np.sin(np.arange(32)+i)
        for i,c in enumerate(['core','momentum','quality','value','dimensional'])},index=dates)
    ret.iloc[0] = 0
    # Saturday entry is mapped to Monday; Monday's pre-entry return must be removed.
    settings = dict(schema_version=1,requested_starts=['2020-01-02','2020-01-18'],
        factor_policies=['absolute_decoupled','hybrid20'],leverage_levels=[1.,1.25],
        comparison_policy='hybrid20',comparison_cagr_tolerance=1e-9,
        research_reference_starts=['2020-01-02'],legacy_reference_starts=['2020-01-18'])
    ret.loc['2020-01-20','core'] = .3
    reference = pd.Series(.02,index=pd.date_range(dates[0],dates[-1]))
    return ret, reference, baseline, settings


def test_requested_weekend_maps_to_next_nav_and_restarts_entry_costs(inputs):
    ret, reference, baseline, settings = inputs
    original = ret.copy()
    result = entries.entry_comparison(*inputs)
    mapping = result['dates'][1]
    assert mapping['requested_entry']=='2020-01-18' and mapping['actual_entry']=='2020-01-20'
    assert mapping['independent_capital_debt_cost_restart']
    fresh = ret.loc['2020-01-20':].copy();fresh.iloc[0] = 0
    direct = simulate(fresh[['core']],reference,[1.],1.,'no_sleeve',initial_equity_usd=12000)
    expected = metrics(direct,reference,direct,[1.])
    row = result['metrics'].query("requested_entry=='2020-01-18' and strategy=='core' and leverage==1").iloc[0]
    assert row.ending_equity_usd==pytest.approx(expected['ending_equity_usd'])
    assert row.transaction_cost_usd>0
    ongoing = simulate(ret[['core']],reference,[1.],1.,'no_sleeve',initial_equity_usd=12000)
    assert row.ending_equity_usd!=pytest.approx(ongoing.history.equity_usd.iloc[-1])
    pd.testing.assert_frame_equal(ret,original)


def test_legacy_view_and_reference_subset_have_explicit_scope(inputs):
    result = entries.entry_comparison(*inputs)
    assert len(result['metrics'])==16
    assert len(result['legacy_metrics'])==6
    assert 'policy' not in result['legacy_metrics']
    assert result['summary']['all_requested_starts']['dates']==2
    assert result['summary']['original_research_starts']['dates']==1
    assert len(result['comparison'])==2


@pytest.mark.parametrize('change',['repeated_date','out_of_range','same_policy','unknown_reference'])
def test_ambiguous_entry_selection_is_rejected(inputs,change):
    _,_,baseline,source = inputs
    settings = copy.deepcopy(source)
    if change=='repeated_date': settings['requested_starts']*=2
    elif change=='out_of_range':settings['requested_starts'][1]='2030-01-01'
    elif change=='same_policy':settings['comparison_policy']='absolute_decoupled'
    else:settings['legacy_reference_starts']=['2020-01-03']
    with pytest.raises(ValueError):entries.validate_settings(settings,baseline)
