"""Annual summaries and sensitivity tables from newly computed monthly accounts."""
from __future__ import annotations

from collections import defaultdict
import math

from .inflow_scenarios import acquisition


def annual_and_headline(rows, *, layer):
    """Retain original reported definitions, including year-two operating recovery."""
    if layer not in {'acquisition', 'timing'}:
        raise ValueError('unknown flow layer')
    scenario = 'flow_scenario' if layer == 'acquisition' else 'timing_scenario'
    groups = defaultdict(list)
    for row in rows:
        groups[(row['return_scenario'], row[scenario])].append(row)
    annual, headlines = [], []
    for series in groups.values():
        if len(series) % 12 or [r['month'] for r in series] != list(range(1, len(series) + 1)):
            raise ValueError('monthly accounts must contain complete ordered years')
        if layer == 'acquisition':
            keep = ['return_scenario', scenario, 'year', 'closing_aum_usd',
                    'owner_equity_usd', 'external_equity_usd', 'unit_nav',
                    'cumulative_manager_cash_usd']
            sums = ['subscriptions_usd', 'redemptions_usd', 'external_fee_usd',
                    'manager_cost_usd', 'manager_net_cash_usd']
        else:
            keep = ['return_scenario', scenario, 'year', 'closing_net_aum_usd',
                    'start_cohort_equity_usd', 'new_cohort_equity_usd',
                    'cumulative_manager_cash_usd', 'cumulative_external_fees_usd',
                    'cumulative_external_redemptions_usd', 'cumulative_gross_subscriptions_usd']
            sums = ['subscriptions_usd', 'new_cohort_redemptions_usd',
                    'fee_new_cohort_usd', 'manager_cost_usd', 'manager_net_cash_usd']
        for start in range(0, len(series), 12):
            group = series[start:start + 12]
            item = {k: group[-1][k] for k in keep}
            for field in sums:
                item['annual_' + field] = math.fsum(r[field] for r in group)
            annual.append(item)
        head = annual[-1].copy()
        if layer == 'acquisition':
            # Keep historical field names for the declared ten-year experiment.
            head['gross_subscriptions_10y_usd'] = sum(r['subscriptions_usd'] for r in series)
            head['external_fees_10y_usd'] = sum(r['external_fee_usd'] for r in series)
        head['peak_business_funding_gap_usd'] = max(0, -min(r['cumulative_manager_cash_usd'] for r in series))
        if layer == 'acquisition':
            head['first_annual_operating_breakeven_year'] = next(
                (y for y in range(2, len(series) // 12 + 1)
                 if sum(r['manager_net_cash_usd'] for r in series[(y - 1) * 12:y * 12]) >= 0), 'none')
        headlines.append(head)
    return annual, headlines


def sensitivity_tables(config):
    rid = config['sensitivity_return_scenario']
    sid = config['sensitivity_flow_scenario']
    if len(config['annual_returns'][rid]) != 10:
        raise ValueError('year10 sensitivity schema requires a ten-year horizon')
    fees = []
    for fee in config['fee_sensitivity']:
        for ticket in config['ticket_sensitivity_usd']:
            for receipt in config['manager_fee_receipt_fractions']:
                rows = acquisition(config, rid, sid, fee=fee, ticket=ticket, receipt=receipt)
                last = rows[-12:]
                fees.append(dict(annual_fee=fee, ticket_usd=ticket,
                    manager_receipt_fraction=receipt,
                    external_aum_year10_usd=rows[-1]['external_equity_usd'],
                    owner_equity_year10_usd=rows[-1]['owner_equity_usd'],
                    external_fee_year10_usd=sum(r['external_fee_usd'] for r in last),
                    manager_net_year10_usd=sum(r['manager_net_cash_usd'] for r in last),
                    cumulative_manager_cash_usd=rows[-1]['cumulative_manager_cash_usd']))
    costs = []
    grid = config['business_cost_sensitivity']
    for fixed in grid['first_year_fixed_cost_usd']:
        for acquisition_cost in grid['acquisition_fraction']:
            for servicing in grid['servicing_fraction']:
                adjusted = dict(config, annual_fixed_manager_cost_usd=fixed,
                    acquisition_cost_fraction_of_gross_subscriptions=acquisition_cost,
                    annual_servicing_cost_fraction_of_opening_external_assets=servicing)
                rows = acquisition(adjusted, rid, sid)
                costs.append(dict(first_year_fixed_cost_usd=fixed,
                    acquisition_fraction=acquisition_cost, servicing_fraction=servicing,
                    external_fees_year10_usd=sum(r['external_fee_usd'] for r in rows[-12:]),
                    manager_result_year10_usd=sum(r['manager_net_cash_usd'] for r in rows[-12:]),
                    cumulative_manager_cash_usd=rows[-1]['cumulative_manager_cash_usd']))
    return fees, costs


def build_results(business, timing_config, acquisition_rows, timing_rows):
    if any(len(path) != 10 for path in business['annual_returns'].values()):
        raise ValueError('current reported table schema requires ten-year paths')
    annual_a, headline_a = annual_and_headline(acquisition_rows, layer='acquisition')
    annual_t, headline_t = annual_and_headline(timing_rows, layer='timing')
    fees, costs = sensitivity_tables(business)
    schedules = timing_config['monthly_schedules_usd']
    if any(len(path) != 120 for path in schedules.values()):
        raise ValueError('current schedule schema requires 120 months')
    return {
        'acquisition_monthly.csv': acquisition_rows,
        'acquisition_annual.csv': annual_a,
        'acquisition_headline.csv': headline_a,
        'fee_ticket_receipt_sensitivity.csv': fees,
        'business_cost_sensitivity.csv': costs,
        'timing_monthly.csv': timing_rows,
        'timing_annual.csv': annual_t,
        'timing_headline.csv': headline_t,
        'subscription_schedule.csv': [dict(month=m, **{k: v[m - 1] for k, v in schedules.items()}) for m in range(1, 121)],
    }
