"""Financial distinctions preserved by the report tables."""
import json
from pathlib import Path
import pytest
from factor_portfolio.inflow_scenarios import acquisition
from factor_portfolio.inflow_results import annual_and_headline, sensitivity_tables

CONFIG = Path(__file__).resolve().parents[1] / 'config/inflow_acquisition.json'


def test_receipt_fraction_changes_manager_cash_not_investor_assets():
    config = json.loads(CONFIG.read_text())
    config = dict(config, fee_sensitivity=[.0005], ticket_sensitivity_usd=[250000],
                  manager_fee_receipt_fractions=[1, .5])
    fees, _ = sensitivity_tables(config)
    full, half = fees
    assert full['external_aum_year10_usd'] == half['external_aum_year10_usd']
    assert full['owner_equity_year10_usd'] == half['owner_equity_year10_usd']
    assert full['external_fee_year10_usd'] == half['external_fee_year10_usd']
    assert full['manager_net_year10_usd'] - half['manager_net_year10_usd'] == pytest.approx(full['external_fee_year10_usd'] / 2)


def test_annual_totals_and_peak_gap_keep_cash_path_distinct_from_final_cash():
    config = json.loads(CONFIG.read_text())
    rows = acquisition(config, 'growth', 'steady', fee=.005)
    annual, heads = annual_and_headline(rows, layer='acquisition')
    assert sum(r['annual_subscriptions_usd'] for r in annual) == pytest.approx(sum(r['subscriptions_usd'] for r in rows))
    assert heads[0]['peak_business_funding_gap_usd'] > -heads[0]['cumulative_manager_cash_usd']
    assert heads[0]['first_annual_operating_breakeven_year'] != 'none'


def test_cost_sensitivity_preserves_investor_fee_revenue():
    config = json.loads(CONFIG.read_text())
    _, costs = sensitivity_tables(config)
    assert len(costs) == 18
    assert len({r['external_fees_year10_usd'] for r in costs}) == 1
    assert len({r['manager_result_year10_usd'] for r in costs}) > 1


def test_summary_rejects_incomplete_year():
    config = json.loads(CONFIG.read_text())
    rows = acquisition(config, 'flat', 'no_flows')
    with pytest.raises(ValueError, match='complete ordered years'):
        annual_and_headline(rows[:-1], layer='acquisition')
