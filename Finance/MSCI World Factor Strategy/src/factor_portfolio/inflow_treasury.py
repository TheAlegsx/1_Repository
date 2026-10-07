"""Conditional owner-fee treasury and independent sensitivity funding checks."""
from __future__ import annotations

import math

from .inflow_controls import acquisition_schedule, independent_accounts, read_csv, solve_fee


def treasury_cash(config, fee):
    rid, sid = config['sensitivity_return_scenario'], config['sensitivity_flow_scenario']
    annual = config['annual_returns'][rid]
    if len(annual) != 10:
        raise ValueError('current treasury schema requires a ten-year horizon')
    subs, reds = acquisition_schedule(config, rid, sid)
    own = float(config['initial_owner_capital_usd'])
    ext = cum = excluded = internal = low = 0.0
    peak = 0
    rows = []
    for i, (sub, redannual) in enumerate(zip(subs, reds)):
        year = i // 12
        r = (1 + annual[year]) ** (1 / 12) - 1
        survival = (1 - redannual) ** (1 / 12)
        ownerfee = own * fee / 12
        extfee = ext * fee / 12
        cost = (config['annual_fixed_manager_cost_usd'] * (1 + config['fixed_cost_inflation']) ** year / 12
                + config['acquisition_cost_fraction_of_gross_subscriptions'] * sub
                + config['annual_servicing_cost_fraction_of_opening_external_assets'] * ext / 12
                + (config['setup_cost_usd'] if i == 0 else 0))
        cum += ownerfee + extfee - cost
        excluded += extfee - cost
        internal += ownerfee
        if cum < low:
            low, peak = cum, i + 1
        rows.append(ownerfee + extfee - cost)
        own *= 1 + r - fee / 12
        ext = ext * (1 + r - fee / 12) * survival + sub
    return dict(annual_fee_bps=fee * 10000, excluded_owner_fee_cash=excluded,
        cumulative_owner_fees=internal, including_owner_fee_cash=cum,
        including_owner_fee_peak_funding=-low, peak_month=peak,
        year10_total_manager_result=sum(rows[-12:]))


def treasury_controls(config, settings, external_roots):
    # Production accounting is used only as an independent comparison here.
    from .inflow_scenarios import acquisition
    rid, sid = config['sensitivity_return_scenario'], config['sensitivity_flow_scenario']
    recovery = next(r['annual_fee_bps'] / 10000 for r in external_roots if r['target'] == 'manager_cash')
    values = []
    error = 0.0

    def check(value):
        nonlocal error
        rows = acquisition(config, rid, sid, fee=value['annual_fee_bps'] / 10000)
        expected = sum(r['manager_net_cash_usd'] + r['owner_fee_usd'] for r in rows)
        final_year = sum(r['manager_net_cash_usd'] + r['owner_fee_usd'] for r in rows[-12:])
        error = max(error, abs(value['including_owner_fee_cash'] - expected),
                    abs(value['year10_total_manager_result'] - final_year))
        if error >= settings['comparison_tolerance_usd']:
            raise AssertionError('production versus conditional treasury comparison failed')

    for fee in config['fee_sensitivity'] + [recovery]:
        value = treasury_cash(config, fee)
        check(value)
        values.append(value)
    roots = []
    for target in ['year10_total_manager_result', 'including_owner_fee_cash']:
        fee = solve_fee(lambda f: treasury_cash(config, f), target, settings)
        value = treasury_cash(config, fee)
        value['target'] = target
        check(value)
        roots.append(value)
    return dict(conditions='100% internal owner-fee receipts available to the manager at monthly accrual; no distribution of these receipts back to owners; no tax or cash-settlement delay. Fund NAV is already reduced by these fees.',
        max_production_cash_error_usd=error, fee_cases=values,
        conditional_total_receipt_break_even=roots)


def sensitivity_controls(config, settings, tables):
    rid, sid = config['sensitivity_return_scenario'], config['sensitivity_flow_scenario']
    path = [(1 + r) ** (1 / 12) - 1 for r in config['annual_returns'][rid] for _ in range(12)]

    def run(*, fee=None, ticket=None, receipt=1, adjusted=None):
        business = config if adjusted is None else adjusted
        subs, reds = acquisition_schedule(business, rid, sid, ticket=ticket)
        result, rows, _ = independent_accounts(business, path, subs, reds, fee=fee, receipt=receipt)
        return dict(external_aum_year10_usd=result['external_equity'],
            owner_equity_year10_usd=result['owner_equity'],
            external_fee_year10_usd=sum(r['fee'] for r in rows[-12:]),
            manager_net_year10_usd=sum(r['manager_net'] for r in rows[-12:]),
            cumulative_manager_cash_usd=result['manager_cash'],
            peak_funding_gap=result['peak_funding'], ownerfees=sum(r['owner_fee'] for r in rows))

    error = 0.0
    count = 0
    detail = []
    for row in read_csv(tables / 'fee_ticket_receipt_sensitivity.csv'):
        fee, ticket, receipt = (float(row[k]) for k in ['annual_fee', 'ticket_usd', 'manager_receipt_fraction'])
        calc = run(fee=fee, ticket=ticket, receipt=receipt)
        for key in ['external_aum_year10_usd', 'owner_equity_year10_usd', 'external_fee_year10_usd', 'manager_net_year10_usd', 'cumulative_manager_cash_usd']:
            error = max(error, abs(calc[key] - float(row[key])))
        count += 1
        if ticket == config['ticket_usd'] and receipt == 1:
            detail.append(dict(annual_fee=fee, **calc))
    for row in read_csv(tables / 'business_cost_sensitivity.csv'):
        adjusted = dict(config, annual_fixed_manager_cost_usd=float(row['first_year_fixed_cost_usd']),
            acquisition_cost_fraction_of_gross_subscriptions=float(row['acquisition_fraction']),
            annual_servicing_cost_fraction_of_opening_external_assets=float(row['servicing_fraction']))
        calc = run(adjusted=adjusted)
        for key, field in [('external_fees_year10_usd', 'external_fee_year10_usd'), ('manager_result_year10_usd', 'manager_net_year10_usd'), ('cumulative_manager_cash_usd', 'cumulative_manager_cash_usd')]:
            error = max(error, abs(calc[field] - float(row[key])))
        count += 1
    if not count or not math.isfinite(error) or error >= settings['comparison_tolerance_usd']:
        raise AssertionError('independent sensitivity comparison failed')
    return dict(independently_recomputed_sensitivity_cases=count, max_difference_usd=error,
        fee_cases_with_peak_funding=detail)
