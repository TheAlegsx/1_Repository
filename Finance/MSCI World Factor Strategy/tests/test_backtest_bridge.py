"""Economic controls for interest, risk references, free trading and case labels."""
import copy
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from factor_portfolio import backtest_bridge as bridge

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def inputs():
    baseline = json.loads((ROOT / 'config/backtest_baseline.json').read_text())
    settings = json.loads((ROOT / 'config/backtest_bridge.json').read_text())
    dates = pd.bdate_range('2020-01-02', periods=32, name='date')
    baseline['initial_equity_usd'] = 12000
    baseline['periods']['full'] = dict(start=str(dates[0].date()), end=str(dates[-1].date()))
    returns = pd.DataFrame({c: .002+.003*np.sin(np.arange(32)+i)
        for i,c in enumerate(['core','momentum','quality','value','dimensional'])}, index=dates)
    returns.iloc[0] = 0
    returns.loc[dates[3], 'value'] = .4  # Force sleeve intervention in both fee controls.
    reference = pd.Series(.02, index=pd.date_range(dates[0], dates[-1]))
    return returns, reference, baseline, settings


def test_removing_borrowing_interest_does_not_remove_risk_reference(inputs):
    returns, reference, baseline, settings = inputs
    original = returns.copy()
    actual = bridge.bridge_comparison(*inputs)['metrics'].set_index('counterfactual')
    without_reference = bridge.bridge_comparison(returns, reference*0, baseline, settings)['metrics'].set_index('counterfactual')
    name = 'factor_levered_zero_interest'
    assert actual.loc[name, 'financing_cost_usd'] == 0
    assert actual.loc[name, 'ending_equity_usd'] == without_reference.loc[name, 'ending_equity_usd']
    assert actual.loc[name, 'sharpe_ratio'] != pytest.approx(without_reference.loc[name, 'sharpe_ratio'])
    assert actual.loc['factor_levered_reference_only', 'financing_cost_usd'] > 0
    assert actual.loc['factor_levered_baseline', 'financing_cost_usd'] > actual.loc['factor_levered_reference_only', 'financing_cost_usd']
    pd.testing.assert_frame_equal(returns, original)


def test_free_trading_keeps_policy_interventions_and_financing(inputs):
    table = bridge.bridge_comparison(*inputs)['metrics'].set_index('counterfactual')
    for free, charged in [('factor_unlevered_zero_trading', 'factor_unlevered_net'),
                          ('factor_levered_zero_trading', 'factor_levered_baseline')]:
        assert table.loc[free, 'transaction_cost_usd'] == 0
        assert table.loc[charged, 'transaction_cost_usd'] > 0
        assert table.loc[free, 'trades_after_entry'] > 0
        assert table.loc[free, 'ending_equity_usd'] > table.loc[charged, 'ending_equity_usd']
    assert table.loc['factor_levered_zero_trading', 'financing_cost_usd'] > 0
    assert table.loc['factor_unlevered_zero_trading', 'financing_cost_usd'] == 0


def test_renaming_labels_cannot_change_economics(inputs):
    returns, reference, baseline, settings = inputs
    expected = bridge.bridge_comparison(*inputs)['metrics'].drop(columns='counterfactual')
    renamed = copy.deepcopy(settings)
    mapping = {case['id']: 'alternative_'+str(i) for i,case in enumerate(renamed['cases'])}
    for case in renamed['cases']:
        case['id'] = mapping[case['id']]
    renamed['sequence'] = [mapping[n] for n in renamed['sequence']]
    for control in renamed['controls']:
        control['from'], control['to'] = mapping[control['from']], mapping[control['to']]
    actual = bridge.bridge_comparison(returns, reference, baseline, renamed)['metrics'].drop(columns='counterfactual')
    pd.testing.assert_frame_equal(actual, expected)


@pytest.mark.parametrize('change', ['duplicate_case', 'unknown_sequence', 'string_flag'])
def test_ambiguous_or_invalid_settings_are_rejected(inputs, change):
    _, _, baseline, settings = inputs
    if change == 'duplicate_case':
        settings['cases'][1]['id'] = settings['cases'][0]['id']
    elif change == 'unknown_sequence':
        settings['sequence'][0] = 'undeclared_case'
    else:
        settings['cases'][2]['reference_interest'] = 'false'
    with pytest.raises(ValueError):
        bridge.validate_settings(settings, baseline)
