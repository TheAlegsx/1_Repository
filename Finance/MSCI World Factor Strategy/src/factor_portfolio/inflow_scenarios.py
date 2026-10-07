"""Configured acquisition/timing calculations; no private-project dependencies."""
from __future__ import annotations

import argparse
import csv
import json
import math
from decimal import Decimal, localcontext
from pathlib import Path

from .inflows import simulate


def acquisition(config, return_id, flow_id, *, fee=None, ticket=None,
                receipt=1.0, coupled=True):
    fee = config['annual_fee'] if fee is None else fee
    ticket = config['ticket_usd'] if ticket is None else ticket
    returns = config['annual_returns'][return_id]
    clients = config['annual_new_client_equivalents'][flow_id]
    if len(returns) != len(clients) or not returns:
        raise ValueError('return and acquisition horizons must match')
    capital = config['initial_owner_capital_usd']
    nav = 100.0
    owner_units = capital / nav
    external_units = 0.0
    contributed, profit, cash = capital, 0.0, 0.0
    rows = []
    active_months = config['first_year_subscription_months']
    if not active_months or len(set(active_months)) != len(active_months) or any(m not in range(1, 13) for m in active_months):
        raise ValueError('invalid first-year subscription months')
    for month in range(1, len(returns) * 12 + 1):
        year = (month - 1) // 12
        annual = returns[year]
        monthly = (1 + annual) ** (1 / 12) - 1
        stressed = coupled and annual < 0
        scheduled = clients[year] * ticket
        subscription = (scheduled / len(active_months) if month in active_months else 0.0) if year == 0 else scheduled / 12
        if stressed:
            subscription *= config['bad_year_subscription_multiplier']
        redemption = 0 if flow_id == 'no_flows' else (
            config['sales_stop_annual_redemption'] if flow_id == 'sales_stop'
            else config['normal_annual_redemption'])
        if stressed and flow_id != 'no_flows':
            redemption = config['bad_year_annual_redemption']
        fraction = 1 - (1 - redemption) ** (1 / 12)
        opening = (owner_units + external_units) * nav
        opening_external = external_units * nav
        owner_fee = owner_units * nav * fee / 12
        external_fee = opening_external * fee / 12
        next_nav = nav * (1 + monthly - fee / 12)
        if not math.isfinite(next_nav) or next_nav <= 0:
            raise ValueError('non-positive unit NAV')
        redeemed = external_units * next_nav * fraction
        external_units = external_units * (1 - fraction) + subscription / next_nav
        nav = next_nav
        closing = (owner_units + external_units) * nav
        contributed += subscription - redeemed
        profit += opening * monthly - owner_fee - external_fee
        if not math.isclose(closing, contributed + profit, rel_tol=1e-12, abs_tol=1e-5):
            raise AssertionError('acquisition accounting identity')
        cost = (config['annual_fixed_manager_cost_usd'] * (1 + config['fixed_cost_inflation']) ** year / 12
                + config['acquisition_cost_fraction_of_gross_subscriptions'] * subscription
                + config['annual_servicing_cost_fraction_of_opening_external_assets'] * opening_external / 12
                + (config['setup_cost_usd'] if month == 1 else 0))
        business = external_fee * receipt - cost
        cash += business
        rows.append(dict(return_scenario=return_id, flow_scenario=flow_id,
            month=month, year=year + 1, opening_aum_usd=opening,
            opening_external_aum_usd=opening_external, monthly_return=monthly,
            subscriptions_usd=subscription, redemptions_usd=redeemed,
            annual_redemption_assumption=redemption, owner_fee_usd=owner_fee,
            external_fee_usd=external_fee, closing_aum_usd=closing,
            owner_equity_usd=owner_units * nav, external_equity_usd=external_units * nav,
            unit_nav=nav, manager_cost_usd=cost, manager_net_cash_usd=business,
            cumulative_manager_cash_usd=cash, cumulative_net_contributions_usd=contributed,
            cumulative_net_investment_profit_usd=profit))
    return rows


def timing(business, config, return_id, timing_id):
    returns = business['annual_returns'][return_id]
    if config['annual_returns'] != business['annual_returns'] or config['annual_fee'] != business['annual_fee']:
        raise ValueError('timing and business return/fee assumptions disagree')
    if config['owner_capital_usd'] != business['initial_owner_capital_usd']:
        raise ValueError('timing and business capital assumptions disagree')
    monthly = [(1 + r) ** (1 / 12) - 1 for r in returns for _ in range(12)]
    subscriptions = config['monthly_schedules_usd'][timing_id]
    redemption = 1 - (1 - config['annual_external_unit_redemption']) ** (1 / 12)
    rows = simulate(initial_aum=config['owner_capital_usd'], initial_nav=100,
                    annual_fee=config['annual_fee'], monthly_returns=monthly,
                    subscriptions=subscriptions, redemption_fraction=redemption)
    cash = fees = reds = subs = 0.0
    # Retain the original decimal opening-cohort convention for business servicing.
    with localcontext() as ctx:
        ctx.prec = 45
        nav, external = Decimal(100), Decimal(0)
        d = Decimal(str(redemption))
        for row in rows:
            opening_external = float(external * nav)
            nav *= 1 + Decimal(str(row['assumed_monthly_return'])) - Decimal(str(config['annual_fee'])) / 12
            external = external * (1 - d) + Decimal(str(row['subscriptions_usd'])) / nav
            year = row['year'] - 1
            cost = (business['annual_fixed_manager_cost_usd'] * (1 + business['fixed_cost_inflation']) ** year / 12
                    + business['acquisition_cost_fraction_of_gross_subscriptions'] * row['subscriptions_usd']
                    + business['annual_servicing_cost_fraction_of_opening_external_assets'] * opening_external / 12
                    + (business['setup_cost_usd'] if row['month'] == 1 else 0))
            net = row['fee_new_cohort_usd'] - cost
            cash += net
            fees += row['fee_new_cohort_usd']
            reds += row['new_cohort_redemptions_usd']
            subs += row['subscriptions_usd']
            row.update(return_scenario=return_id, timing_scenario=timing_id,
                manager_cost_usd=cost, manager_net_cash_usd=net,
                cumulative_manager_cash_usd=cash, cumulative_external_fees_usd=fees,
                cumulative_external_redemptions_usd=reds,
                cumulative_gross_subscriptions_usd=subs)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--acquisition-config', type=Path, required=True)
    parser.add_argument('--timing-config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    business = json.loads(args.acquisition_config.read_text())
    config = json.loads(args.timing_config.read_text())
    acquisition_rows = [row for rid in business['annual_returns']
        for sid in business['annual_new_client_equivalents'] for row in acquisition(business, rid, sid)]
    timing_rows = [row for rid in business['annual_returns']
        for sid in config['monthly_schedules_usd'] for row in timing(business, config, rid, sid)]
    from .inflow_results import build_results
    tables = build_results(business, config, acquisition_rows, timing_rows)
    args.output.mkdir(parents=True, exist_ok=False)
    for filename, rows in tables.items():
        with (args.output / filename).open('x', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator='\n')
            writer.writeheader()
            writer.writerows(rows)
    print(f'Created {len(tables)} tables: {len(acquisition_rows)} acquisition and {len(timing_rows)} timing monthly rows.')


if __name__ == '__main__':
    main()
