"""Primary selection and unchanged absolute/decoupled accounting semantics."""
import copy
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from factor_portfolio import backtest_workflow as workflow
from factor_portfolio import backtest_funding, backtest_bridge
from factor_portfolio.historical import simulate

ROOT = Path(__file__).resolve().parents[1]
WEIGHTS = np.array([.6, .15, .1, .15])
SLEEVES = ['core', 'momentum', 'quality', 'value']


def inputs():
    dates = pd.bdate_range('2020-01-02', periods=8, name='date')
    return pd.DataFrame(0., index=dates, columns=SLEEVES), pd.Series(0., index=pd.date_range(dates[0], dates[-1]))


@pytest.mark.parametrize('sleeve', range(4))
def test_uniform_absolute_boundary_is_strict_and_executes_next_observation(sleeve):
    ret, reference = inputs()
    w = WEIGHTS[sleeve]
    boundary = w + .05
    ret.iloc[2, sleeve] = boundary*(1-w)/(w*(1-boundary))-1
    equal = simulate(ret, reference, WEIGHTS, 1., 'absolute_decoupled', fee_free=True)
    assert len(equal.events) == 1
    ret.iloc[3, sleeve] = 1e-8
    breached = simulate(ret, reference, WEIGHTS, 1., 'absolute_decoupled', fee_free=True)
    assert breached.events.iloc[1]['date'] == ret.index[4]
    assert breached.events.iloc[1]['reason'] == 'sleeve'
    np.testing.assert_allclose(breached.history.loc[ret.index[4], [f'weight_{s}' for s in SLEEVES]].to_numpy(float), WEIGHTS, atol=1e-12)


def test_absolute_sleeve_only_trade_preserves_debt_after_costs():
    ret, reference = inputs()
    ret.loc[ret.index[2], 'quality'] = .8
    result = simulate(ret, reference, WEIGHTS, 1.25, 'absolute_decoupled', margin=0, initial_equity_usd=7e6)
    assert result.events.iloc[1]['reason'] == 'sleeve'
    assert result.history.loc[ret.index[3], 'transaction_cost_usd'] > 0
    assert result.history.loc[ret.index[2], 'debt_usd'] == pytest.approx(result.history.loc[ret.index[3], 'debt_usd'], abs=1e-6)


def test_absolute_leverage_only_trade_preserves_current_mix():
    ret, reference = inputs()
    ret.loc[ret.index[2]] = -.30
    ret.loc[ret.index[2], 'momentum'] = -.10
    result = simulate(ret, reference, WEIGHTS, 1.25, 'absolute_decoupled', margin=0, initial_equity_usd=7e6)
    assert result.events.iloc[1]['reason'] == 'leverage'
    columns = [f'weight_{s}' for s in SLEEVES]
    before = result.history.loc[ret.index[2], columns].to_numpy(float)
    after = result.history.loc[ret.index[3], columns].to_numpy(float)
    np.testing.assert_allclose(before, after, atol=1e-12)
    assert not np.allclose(after, WEIGHTS)
    assert result.history.loc[ret.index[3], 'leverage'] == pytest.approx(1.25)


def test_versioned_selection_changes_no_economic_inputs():
    old = json.loads((ROOT / 'config/backtest_baseline.json').read_text())
    new = json.loads((ROOT / 'config/backtest_absolute_decoupled_2026-10-05.json').read_text())
    for key in old:
        if key != 'scope':
            assert old[key] == new[key], key
    workflow.validate_config(new)
    assert new['primary_policy'] == 'absolute_decoupled'
    assert new['history_policies'] == ['absolute_decoupled', 'hybrid20']


@pytest.mark.parametrize('component,name', [(backtest_funding,'backtest_funding.json'), (backtest_bridge,'backtest_bridge.json')])
def test_followup_stages_support_absolute_and_reject_mixed_policies(component, name):
    baseline = json.loads((ROOT / 'config/backtest_absolute_decoupled_2026-10-05.json').read_text())
    legacy = json.loads((ROOT / 'config'/name).read_text())
    with pytest.raises(ValueError, match='disagrees'):
        component.validate_settings(legacy, baseline)
    changed = copy.deepcopy(legacy)
    changed['factor_policy'] = 'absolute_decoupled'
    component.validate_settings(changed, baseline)


def test_unknown_primary_or_missing_primary_history_is_rejected():
    settings = json.loads((ROOT / 'config/backtest_absolute_decoupled_2026-10-05.json').read_text())
    settings['history_policies'] = ['hybrid20']
    with pytest.raises(ValueError, match='retained account history'):
        workflow.validate_config(settings)
    settings['history_policies'] = ['absolute_decoupled','hybrid20']
    settings['primary_policy'] = 'undeclared_policy'
    with pytest.raises(ValueError, match='must be calculated'):
        workflow.validate_config(settings)
