"""Loss timing, fee transfers and working-capital distinctions."""
import json
from pathlib import Path

import pytest

from factor_portfolio.inflow_controls import independent_accounts, solve_fee
from factor_portfolio.inflow_treasury import treasury_cash

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / 'config/inflow_acquisition.json').read_text())
SETTINGS = json.loads((ROOT / 'config/inflow_controls.json').read_text())


def test_same_net_annual_loss_preserves_owner_wealth_but_changes_external_wealth():
    fee = CONFIG['annual_fee'] / 12
    smooth = .7 ** (1 / 12) - 1
    matched = (1 + smooth - fee) ** 12 / (1 - fee) ** 11 - 1 + fee
    subscriptions = [1000] * 120
    redemptions = [.1] * 120
    baseline, _, _ = independent_accounts(CONFIG, [smooth] * 12 + [0] * 108, subscriptions, redemptions)
    early, _, _ = independent_accounts(CONFIG, [matched] + [0] * 119, subscriptions, redemptions)
    late, _, _ = independent_accounts(CONFIG, [0] * 11 + [matched] + [0] * 108, subscriptions, redemptions)
    assert early['owner_equity'] == pytest.approx(baseline['owner_equity'], abs=1e-7)
    assert late['owner_equity'] == pytest.approx(baseline['owner_equity'], abs=1e-7)
    assert early['external_equity'] > late['external_equity']


def test_receipt_fraction_changes_business_cash_without_changing_investor_assets():
    full, _, _ = independent_accounts(CONFIG, [.005] * 120, [1000] * 120, [.1] * 120)
    half, _, _ = independent_accounts(CONFIG, [.005] * 120, [1000] * 120, [.1] * 120, receipt=.5)
    assert full['owner_equity'] == half['owner_equity']
    assert full['external_equity'] == half['external_equity']
    assert full['manager_cash'] - half['manager_cash'] == pytest.approx(full['external_fees'] / 2)


def test_internal_fee_receipts_are_a_transfer_from_owner_invested_equity():
    config = dict(CONFIG, initial_owner_capital_usd=100, annual_fixed_manager_cost_usd=0,
                  setup_cost_usd=0, acquisition_cost_fraction_of_gross_subscriptions=0,
                  annual_servicing_cost_fraction_of_opening_external_assets=0,
                  annual_returns={'growth': [0] * 10},
                  annual_new_client_equivalents={'steady': [0] * 10})
    fee = .12
    result = treasury_cash(config, fee)
    invested, _, _ = independent_accounts(config, [0] * 120, [0] * 120, [0] * 120, fee=fee)
    assert result['excluded_owner_fee_cash'] == 0
    assert result['including_owner_fee_peak_funding'] == 0
    assert invested['owner_equity'] + result['including_owner_fee_cash'] == pytest.approx(100)


def test_profitable_final_year_can_still_require_material_interim_funding():
    value = treasury_cash(CONFIG, .005)
    assert value['including_owner_fee_cash'] > 0
    assert value['year10_total_manager_result'] > 0
    assert value['including_owner_fee_peak_funding'] > 20000
    assert value['peak_month'] == 1


def test_fee_solver_requires_a_bracket_and_solves_the_selected_cash_target():
    evaluator = lambda fee: {'cash': 1000000 * (fee - .01)}
    assert solve_fee(evaluator, 'cash', SETTINGS) == pytest.approx(.01)
    with pytest.raises(ValueError, match='straddle'):
        solve_fee(lambda fee: {'cash': fee - .03}, 'cash', SETTINGS)
