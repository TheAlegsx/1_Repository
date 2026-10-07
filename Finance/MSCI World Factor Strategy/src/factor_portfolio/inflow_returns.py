"""Unit TWR and aggregate external MWR on equal end-month periods."""
from __future__ import annotations

import argparse
from collections import defaultdict
import csv
import json
import math
from pathlib import Path

import numpy as np


def money_weighted_return(cash_flows, settings):
    """Scan and solve a monthly log-discount root; no global uniqueness claim."""
    cf = [float(x) for x in cash_flows]
    if not cf or not all(math.isfinite(x) for x in cf):
        raise ValueError('cash flows must be nonempty and finite')
    nonzero = [x for x in cf if x != 0]
    if not nonzero or nonzero[0] >= 0 or not any(x > 0 for x in cf):
        raise ValueError('external investor flows must start with an outflow and include an inflow')
    lower = settings['log_monthly_discount_min']
    upper = settings['log_monthly_discount_max']
    count = settings['scan_points']
    iterations = settings['bisection_iterations']
    tolerance = settings['npv_residual_tolerance_usd']
    periods = settings['months_per_year']
    if not (math.isfinite(lower) and math.isfinite(upper) and lower < upper
            and isinstance(count, int) and count >= 2
            and isinstance(iterations, int) and iterations > 0
            and math.isfinite(tolerance) and tolerance > 0
            and isinstance(periods, int) and periods > 0):
        raise ValueError('invalid return diagnostic settings')

    def npv(q):
        return math.fsum(z * math.exp(-q * (m + 1)) for m, z in enumerate(cf))

    grid = np.linspace(lower, upper, count)
    values = [npv(q) for q in grid]
    exact = [float(q) for q, value in zip(grid, values) if value == 0]
    brackets = [(a, b) for a, b, fa, fb in
                zip(grid[:-1], grid[1:], values[:-1], values[1:]) if fa * fb < 0]
    if len(exact) + len(brackets) != 1:
        raise ValueError('expected one IRR root on the scanned log-discount grid')
    if exact:
        q = exact[0]
    else:
        lo, hi = brackets[0]
        flo = npv(lo)
        for _ in range(iterations):
            mid = (lo + hi) / 2
            fmid = npv(mid)
            if (fmid > 0) == (flo > 0):
                lo, flo = mid, fmid
            else:
                hi = mid
        q = float((lo + hi) / 2)
    residual = npv(q)
    if abs(residual) >= tolerance:
        raise ValueError('IRR cash-flow residual exceeds the configured tolerance')
    return dict(annual_return=math.expm1(periods * q),
                npv_residual_usd=residual, scanned_root_count=len(exact) + len(brackets))


def external_investor_returns(rows, settings):
    """Derive returns from generated timing accounts, excluding no-flow controls."""
    groups = defaultdict(list)
    for row in rows:
        groups[(row['return_scenario'], row['timing_scenario'])].append(row)
    initial_nav = settings['initial_unit_nav']
    if not math.isfinite(initial_nav) or initial_nav <= 0:
        raise ValueError('initial unit NAV must be positive and finite')
    result = []
    for (rid, sid), series in groups.items():
        if [int(r['month']) for r in series] != list(range(1, len(series) + 1)):
            raise ValueError('return accounts must contain ordered consecutive months')
        subscriptions = [float(r['subscriptions_usd']) for r in series]
        if any(x < 0 or not math.isfinite(x) for x in subscriptions):
            raise ValueError('subscriptions must be nonnegative and finite')
        if not any(subscriptions):
            continue  # No invested external cohort: aggregate MWR is undefined.
        cf = [float(r['new_cohort_redemptions_usd']) - sub
              for r, sub in zip(series, subscriptions)]
        cf[-1] += float(series[-1]['new_cohort_equity_usd'])
        solved = money_weighted_return(cf, settings)
        nav = float(series[-1]['nav_per_unit'])
        if not math.isfinite(nav) or nav <= 0:
            raise ValueError('terminal unit NAV must be positive and finite')
        twr = (nav / initial_nav) ** (settings['months_per_year'] / len(series)) - 1
        result.append(dict(return_path=rid, timing=sid, twr_annual_pct=100 * twr,
            aggregate_external_mwr_annual_pct=100 * solved['annual_return'],
            npv_residual_usd=solved['npv_residual_usd'],
            sign_change_brackets_on_scanned_log_discount_grid=solved['scanned_root_count'],
            terminal_aum=float(series[-1]['closing_net_aum_usd'])))
    return result


def return_diagnostics(rows, settings):
    results = external_investor_returns(rows, settings)
    return dict(external_investor_returns=results, settings=settings, limitations=[
        'Equal end-month scenario periods; these are not dated transaction XIRRs.',
        'MWR aggregates external subscriptions, redemptions and terminal external equity; it is not an individual investor return.',
        'Unit TWR uses terminal versus initial NAV and the full model horizon.',
        'The grid checks sign changes and exact grid roots; uniqueness outside the grid and unsampled tangential roots are not established.',
        'Researcher-imposed scenarios are not forecasts or evidence of future performance.',
    ])


def write_results(payload, output):
    results = payload['external_investor_returns']
    if not results:
        raise ValueError('no external-investor return cases to write')
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    (output / 'return_diagnostics.json').write_text(json.dumps(payload, indent=2) + '\n')
    with (output / 'external_investor_returns.csv').open('x', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(results[0]), lineterminator='\n')
        writer.writeheader()
        writer.writerows(results)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--monthly', type=Path, required=True)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    with args.monthly.open() as f:
        rows = list(csv.DictReader(f))
    payload = return_diagnostics(rows, json.loads(args.config.read_text()))
    write_results(payload, args.output)
    print(f"Created unit TWR and aggregate external MWR diagnostics for {len(payload['external_investor_returns'])} cases.")


if __name__ == '__main__':
    main()
