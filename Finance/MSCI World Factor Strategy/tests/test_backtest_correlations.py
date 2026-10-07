"""Calendar conditioning, tied-rank algebra and complete matrix admission."""
import copy
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from factor_portfolio import backtest_correlations as correlations

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def panels():
    dates = pd.bdate_range('2020-01-02', periods=800, name='date')
    ret = pd.DataFrame({c: .002 + .008*np.sin(np.arange(800)/3+i)
        for i, c in enumerate(correlations.PRODUCTS)}, index=dates)
    ret.iloc[0] = 0
    levels = (1+ret).cumprod()*10
    # Published ties are retained; one Amundi date is absent, without filling.
    amundi = (levels.core**1.8).iloc[600:].drop(dates[700])
    base = dict(periods=dict(full=dict(start=str(dates[0].date()), end=str(dates[-1].date())),
        calibration=dict(start=str(dates[0].date()), end=str(dates[399].date())),
        confirmation=dict(start=str(dates[400].date()), end=str(dates[-1].date()))))
    short = levels.loc[amundi.index].copy();short['amundi_2x'] = amundi
    monthly = levels.groupby(levels.index.to_period('M')).tail(1).iloc[:-1]
    selected = dict(long_full=levels, long_calibration=levels.iloc[:400], long_confirmation=levels.iloc[400:],
        long_monthly=monthly, market_negative_intervals=None, short_with_amundi=short,
        short_without_amundi=short.drop(columns='amundi_2x'))
    settings = json.loads((ROOT/'config/backtest_correlations_2026-10-05.json').read_text())
    settings['excluded_month'] = str(dates[-1].to_period('M'))
    for name, nav in selected.items():
        returns = nav.pct_change(fill_method=None).iloc[1:] if nav is not None else ret.iloc[1:].loc[ret.core.iloc[1:] < 0]
        settings['expected_panels'][name] = dict(first_return_end=str(returns.index[0].date()),
            last_return_end=str(returns.index[-1].date()), return_observations=len(returns),
            products=list(returns.columns), level_start=str(nav.index[0].date()) if nav is not None else None,
            level_observations=len(nav) if nav is not None else None)
    return levels, amundi, base, settings, dates


def test_returns_follow_level_intersection_and_confirmation_excludes_opening_interval(panels):
    levels, amundi, base, settings, dates = panels
    result = correlations.correlation_comparison(levels, amundi, base, settings)
    six = result['frames']['short_with_amundi_returns.csv']
    five = result['frames']['short_without_amundi_returns.csv']
    pd.testing.assert_frame_equal(six.drop(columns='amundi_2x'), five)
    assert dates[700] not in six.index
    assert six.loc[dates[701], 'core'] == pytest.approx(levels.loc[dates[701], 'core']/levels.loc[dates[699], 'core']-1)
    confirmation = result['frames']['long_confirmation_returns.csv']
    assert confirmation.index[0] == dates[401] and dates[400] not in confirmation.index
    assert result['definitions']['primary_policy_independent'] is True


def test_monthly_negative_and_rolling_samples_are_separate(panels):
    levels, amundi, base, settings, dates = panels
    result = correlations.correlation_comparison(levels, amundi, base, settings)
    monthly = result['frames']['long_monthly_levels.csv']
    assert str(monthly.index[-1].to_period('M')) != settings['excluded_month']
    assert monthly.index[0] == levels.loc['2020-01'].index[-1]
    negative = result['frames']['market_negative_intervals_returns.csv']
    assert (negative.core < 0).all()
    roll = result['frames']['rolling_252.csv']
    assert len(roll) == (len(levels)-1-251)*10
    assert roll.date.iloc[0] == dates[252]
    for name, matrix in result['frames'].items():
        if name.endswith(('_pearson.csv', '_spearman.csv')):
            np.testing.assert_allclose(np.diag(matrix), 1., atol=1e-12)
            assert np.linalg.eigvalsh(matrix).min() > -1e-10


def test_tied_rank_identity_inverse_and_magnitude_distinction():
    # Average ranks [1,2.5,2.5,4] and [4,2.5,2.5,1] give exactly -1.
    x = pd.DataFrame(dict(x=[1.,2.,2.,9.], same=[1.,2.,2.,9.], inverse=[9.,2.,2.,1.]))
    rank = correlations._matrix(x, 'spearman')
    assert rank.loc['x','same'] == pytest.approx(1.)
    assert rank.loc['x','inverse'] == pytest.approx(-1.)
    assert correlations._matrix(x, 'pearson').loc['x','inverse'] > -.8
    x['constant'] = 1.
    with pytest.raises(ValueError, match='nonconstant'):correlations._matrix(x, 'pearson')


def test_missing_duplicate_nonpositive_levels_and_changed_calendar_are_rejected(panels):
    levels, amundi, base, settings, _ = panels
    bad = levels.copy();bad.iloc[3, 0] = np.nan
    with pytest.raises(ValueError, match='positive'):correlations.correlation_comparison(bad, amundi, base, settings)
    bad = levels.copy();bad.iloc[3, 0] = 0
    with pytest.raises(ValueError, match='positive'):correlations.correlation_comparison(bad, amundi, base, settings)
    with pytest.raises(ValueError, match='positive'):correlations.correlation_comparison(pd.concat([levels.iloc[:1], levels]), amundi, base, settings)
    changed = copy.deepcopy(settings);changed['expected_panels']['short_with_amundi']['return_observations'] += 1
    with pytest.raises(ValueError, match='calendar/count'):correlations.correlation_comparison(levels, amundi, base, changed)


def test_admission_requires_fresh_product_stage_and_explicit_measurement(panels):
    _, _, base, settings, _ = panels
    with pytest.raises(ValueError, match='require'):correlations.validate_settings(settings, base, None)
    correlations.validate_settings(settings, base, {})
    changed = copy.deepcopy(settings);changed['measurement']['fill_missing'] = True
    with pytest.raises(ValueError, match='measurement'):correlations.validate_settings(changed, base, {})
