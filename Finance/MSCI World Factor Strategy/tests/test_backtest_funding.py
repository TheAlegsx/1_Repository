"""Search edge cases and economic distinction between reference rates and margins."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from factor_portfolio import backtest_funding as funding
from factor_portfolio.config import SwissquoteStandardFeeSchedule

ROOT = Path(__file__).resolve().parents[1]


def test_bracketed_linear_crossing_and_search_resolution():
    crossing, trace = funding.bracketed_crossing(lambda x: .037 - x / 10000, [0, 1000], 22)
    assert crossing['margin_bps'] == pytest.approx(370, abs=1000/2**22)
    assert trace['status'] == 'bracketed_estimate'
    assert trace['final_bracket_width_bps'] == pytest.approx(1000/2**22)
    assert len(trace['evaluations']) == 25


def test_absent_bracket_does_not_extrapolate_a_threshold():
    crossing, trace = funding.bracketed_crossing(lambda x: .01 + x/10000, [0, 1000], 22)
    assert crossing == dict(margin_bps=None, difference_at_threshold=None)
    assert trace['status'] == 'not_bracketed'
    assert len(trace['evaluations']) == 2


def test_exact_endpoint_is_retained():
    crossing, trace = funding.bracketed_crossing(lambda x: 1000-x, [0, 1000], 22)
    assert crossing['margin_bps'] == 1000
    assert crossing['difference_at_threshold'] == 0
    assert trace['status'] == 'endpoint_zero'


def test_discontinuous_objective_exposes_nonzero_residual():
    crossing, trace = funding.bracketed_crossing(lambda x: 1 if x < 500 else -1, [0, 1000], 22)
    assert abs(crossing['difference_at_threshold']) == 1
    assert trace['status'] == 'bracketed_estimate'


def test_nonfinite_objective_cannot_be_accepted():
    with pytest.raises(ValueError, match='nonfinite'):
        funding.bracketed_crossing(lambda x: float('nan'), [0, 1000], 22)


def test_zero_margin_preserves_reference_financing_and_fixed_entry_capital():
    baseline = json.loads((ROOT / 'config/backtest_baseline.json').read_text())
    settings = json.loads((ROOT / 'config/backtest_funding.json').read_text())
    dates = pd.bdate_range('2020-01-02', periods=32, name='date')
    baseline['initial_equity_usd'] = 12000
    baseline['periods'] = {
        'full': dict(start=str(dates[0].date()), end=str(dates[-1].date())),
        'calibration': dict(start=str(dates[0].date()), end=str(dates[15].date())),
        'confirmation': dict(start=str(dates[16].date()), end=str(dates[-1].date()))}
    settings['margin_bps'] = [0, 300]
    settings['threshold']['iterations'] = 4
    returns = pd.DataFrame({c: .002 + .003*np.sin(np.arange(32)+i)
        for i,c in enumerate(['core','momentum','quality','value','dimensional'])}, index=dates)
    returns.iloc[0] = 0
    reference = pd.Series(.02, index=pd.date_range(dates[0], dates[-1]))
    result = funding.funding_comparison(returns, reference, baseline, settings)
    table = result['metrics']
    core = table.query("period == 'full' and strategy == 'core'").set_index('margin_bps')
    assert core.loc[0, 'financing_cost_usd'] > 0
    assert core.loc[300, 'financing_cost_usd'] > core.loc[0, 'financing_cost_usd']
    assert core.loc[300, 'ending_equity_usd'] < core.loc[0, 'ending_equity_usd']
    assert len(table) == 12
    # For this small-drift path there is only entry. Solve its fee independently,
    # then compound the reference charge over each actual observation interval.
    assert core.loc[0, 'trades_after_entry'] == 0
    fee = SwissquoteStandardFeeSchedule(**baseline['fee_schedule'])
    charge = 0.
    for _ in range(100):
        charge = fee.cost(1.25 * (12000-charge))
    debt = .25 * (12000-charge)
    gaps = np.diff(dates.to_numpy()).astype('timedelta64[D]').astype(float)
    finance = debt * (np.prod(1 + .02*gaps/360)-1)
    assert core.loc[0, 'financing_cost_usd'] == pytest.approx(finance, abs=1e-9)
    confirmation = table.query("period == 'confirmation' and strategy == 'core' and margin_bps == 0").iloc[0]
    assert confirmation['observations'] == 16
    assert confirmation['financing_cost_usd'] < core.loc[0, 'financing_cost_usd']


def test_invalid_search_cannot_start():
    with pytest.raises(ValueError, match='bracket'):
        funding.bracketed_crossing(lambda x: x, [1000, 0], 22)
    with pytest.raises(ValueError, match='iteration'):
        funding.bracketed_crossing(lambda x: x, [0, 1000], 0)
