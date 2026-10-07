"""Economic controls for configured acquisition and timing experiments."""
import json
from pathlib import Path
import pytest
from factor_portfolio.inflow_scenarios import acquisition, timing

CONFIG = Path(__file__).resolve().parents[1] / 'config'


def configs():
    return (json.loads((CONFIG / 'inflow_acquisition.json').read_text()),
            json.loads((CONFIG / 'inflow_timing.json').read_text()))


def test_acquisition_keeps_owner_performance_independent_of_fundraising():
    business, _ = configs()
    for rid in business['annual_returns']:
        baseline = acquisition(business, rid, 'no_flows')
        for sid in business['annual_new_client_equivalents']:
            rows = acquisition(business, rid, sid)
            assert [r['owner_equity_usd'] for r in rows] == [r['owner_equity_usd'] for r in baseline]
            assert [r['unit_nav'] for r in rows] == [r['unit_nav'] for r in baseline]


def test_loss_feedback_changes_sales_and_retention():
    business, _ = configs()
    stressed = acquisition(business, 'late_loss', 'steady')
    control = acquisition(business, 'late_loss', 'steady', coupled=False)
    for a, b in zip(stressed[36:48], control[36:48]):
        assert a['subscriptions_usd'] == b['subscriptions_usd'] * .5
        assert a['annual_redemption_assumption'] == .3
        assert b['annual_redemption_assumption'] == .1


def test_timing_preserves_owner_nav_and_matched_gross_subscriptions():
    business, config = configs()
    baseline = timing(business, config, 'late_loss', 'no_flows')
    for sid in config['monthly_schedules_usd']:
        rows = timing(business, config, 'late_loss', sid)
        assert [r['nav_per_unit'] for r in rows] == [r['nav_per_unit'] for r in baseline]
        assert [r['start_cohort_equity_usd'] for r in rows] == [r['start_cohort_equity_usd'] for r in baseline]
        expected = 0 if sid == 'no_flows' else config['total_gross_subscriptions_per_timing_case_usd']
        assert sum(r['subscriptions_usd'] for r in rows) == pytest.approx(expected)
        assert all(r['subscriptions_usd'] == 0 for r in rows[:6])


def test_initial_capital_and_business_costs_come_from_configuration():
    business, _ = configs()
    business = dict(business, initial_owner_capital_usd=1000,
                    annual_fixed_manager_cost_usd=120, setup_cost_usd=25)
    row = acquisition(business, 'flat', 'no_flows')[0]
    assert row['opening_aum_usd'] == 1000
    assert row['manager_cost_usd'] == 35
    assert row['manager_net_cash_usd'] == -35
