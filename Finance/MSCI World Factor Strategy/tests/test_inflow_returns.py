"""Return economics rather than table-format checks."""
import json
from pathlib import Path
import pytest

from factor_portfolio.inflow_returns import external_investor_returns, money_weighted_return
from factor_portfolio.inflow_scenarios import timing

ROOT = Path(__file__).resolve().parents[1]
SETTINGS = json.loads((ROOT / 'config/inflow_returns.json').read_text())


@pytest.mark.parametrize('terminal,monthly', [(105, .05), (95, -.05), (100, 0)])
def test_known_monthly_cash_flow_returns_and_exact_zero_root(terminal, monthly):
    result = money_weighted_return([-100, terminal], SETTINGS)
    assert result['annual_return'] == pytest.approx((1 + monthly) ** 12 - 1, abs=1e-12)
    assert abs(result['npv_residual_usd']) < 1e-10


def test_multiple_irr_roots_are_rejected_instead_of_arbitrarily_selected():
    wide = dict(SETTINGS, log_monthly_discount_min=-.5, log_monthly_discount_max=.5)
    # Polynomial -100 + 230/(1+r) - 132/(1+r)^2 has roots 10% and 20%.
    with pytest.raises(ValueError, match='one IRR root'):
        money_weighted_return([-100, 230, -132], wide)


def test_constant_growth_investor_mwr_equals_unit_twr_across_arrival_schedules():
    business = json.loads((ROOT / 'config/inflow_acquisition.json').read_text())
    config = json.loads((ROOT / 'config/inflow_timing.json').read_text())
    rows = [r for sid in config['monthly_schedules_usd'] for r in timing(business, config, 'growth', sid)]
    results = external_investor_returns(rows, SETTINGS)
    assert len(results) == 5  # No-flow control has no external investor return.
    assert len({r['twr_annual_pct'] for r in results}) == 1
    for result in results:
        assert result['aggregate_external_mwr_annual_pct'] == pytest.approx(result['twr_annual_pct'], abs=1e-10)


def test_twr_annualisation_uses_actual_horizon_and_cash_arrival():
    rows = [dict(return_scenario='example', timing_scenario='example', month=m,
            subscriptions_usd=100 if m == 1 else 0, new_cohort_redemptions_usd=0,
            new_cohort_equity_usd=110, nav_per_unit=121, closing_net_aum_usd=231)
            for m in range(1, 25)]
    result = external_investor_returns(rows, SETTINGS)[0]
    assert result['twr_annual_pct'] == pytest.approx(10)
    assert result['aggregate_external_mwr_annual_pct'] == pytest.approx(100 * (1.1 ** (12 / 23) - 1))
    with pytest.raises(ValueError, match='ordered consecutive'):
        external_investor_returns(rows[:-2] + rows[-1:], SETTINGS)
