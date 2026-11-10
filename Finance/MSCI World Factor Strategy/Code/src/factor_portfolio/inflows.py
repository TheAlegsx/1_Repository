"""Monthly unit/cohort accounting extracted without report or filesystem side effects."""
from __future__ import annotations
import math
import csv

def nonnegative(value, name):
    value = float(value)
    if not math.isfinite(value) or value < 0:
        raise ValueError(name + ' must be finite and non-negative')
    return value

def simulate(*, initial_aum, initial_nav, annual_fee, monthly_returns,
             subscriptions, redemption_fraction=0.0, seed_redemptions=None):
    initial_aum = nonnegative(initial_aum, 'initial_aum')
    initial_nav = nonnegative(initial_nav, 'initial_nav')
    annual_fee = nonnegative(annual_fee, 'annual_fee')
    redemption_fraction = nonnegative(redemption_fraction, 'redemption_fraction')
    if initial_aum == 0 or initial_nav == 0 or annual_fee >= 1 or redemption_fraction >= 1:
        raise ValueError('invalid initial capital, NAV, fee or redemption fraction')
    n = len(monthly_returns)
    seed_redemptions = [0.0] * n if seed_redemptions is None else seed_redemptions
    if n == 0 or len(subscriptions) != n or len(seed_redemptions) != n:
        raise ValueError('nonempty monthly paths must have matching lengths')
    nav, seed_units, new_units = initial_nav, initial_aum / initial_nav, 0.0
    contributed, profit, fees = initial_aum, 0.0, 0.0
    rows = []
    for month, (r, sub, seed_red) in enumerate(zip(monthly_returns, subscriptions, seed_redemptions), 1):
        r = float(r)
        if not math.isfinite(r) or r <= -1:
            raise ValueError('invalid monthly return')
        sub = nonnegative(sub, 'subscription')
        seed_red = nonnegative(seed_red, 'seed_redemption')
        opening = (seed_units + new_units) * nav
        start_fee = seed_units * nav * annual_fee / 12
        new_fee = new_units * nav * annual_fee / 12
        fee = start_fee + new_fee
        pnl = opening * r
        next_nav = nav * (1 + r - annual_fee / 12)
        if not math.isfinite(next_nav) or next_nav <= 0:
            raise ValueError('non-positive unit NAV after return/fee')
        if seed_red > seed_units * next_nav:
            raise ValueError('seed redemption exceeds available capital')
        new_red = new_units * next_nav * redemption_fraction
        new_units *= 1 - redemption_fraction
        seed_units -= seed_red / next_nav
        new_units += sub / next_nav
        if seed_units + new_units <= 0:
            raise ValueError('complete liquidation requires a separate policy')
        contributed += sub - new_red - seed_red
        profit += pnl
        fees += fee
        closing = (seed_units + new_units) * next_nav
        expected = opening + pnl - fee + sub - new_red - seed_red
        if not math.isclose(closing, expected, rel_tol=1e-12, abs_tol=1e-6):
            raise AssertionError('monthly accounting identity')
        if not math.isclose(closing, contributed + profit - fees, rel_tol=1e-12, abs_tol=1e-6):
            raise AssertionError('cumulative accounting identity')
        rows.append(dict(month=month, year=(month - 1) // 12 + 1,
            opening_net_aum_usd=opening, assumed_monthly_return=r,
            investment_pnl_before_admin_usd=pnl, administrative_fee_usd=fee,
            fee_start_cohort_usd=start_fee, fee_new_cohort_usd=new_fee,
            subscriptions_usd=sub, new_cohort_redemptions_usd=new_red,
            start_cohort_redemptions_usd=seed_red, closing_net_aum_usd=closing,
            start_cohort_equity_usd=seed_units * next_nav,
            new_cohort_equity_usd=new_units * next_nav, nav_per_unit=next_nav,
            start_units=seed_units, new_units=new_units,
            unit_return_after_admin=next_nav / nav - 1,
            cumulative_net_contributed_usd=contributed,
            cumulative_investment_pnl_after_admin_usd=profit-fees,
            cumulative_admin_fee_usd=fees))
        nav = next_nav
    return rows

def summary(rows, initial_aum, initial_nav):
    output = []
    for year in range(1, len(rows)//12 + 1):
        group = rows[(year-1)*12:year*12]
        last = group[-1]
        output.append(dict(year=year, closing_net_aum_usd=last['closing_net_aum_usd'],
            start_cohort_equity_usd=last['start_cohort_equity_usd'],
            new_cohort_equity_usd=last['new_cohort_equity_usd'],
            annual_subscriptions_usd=math.fsum(r['subscriptions_usd'] for r in group),
            annual_redemptions_usd=math.fsum(r['new_cohort_redemptions_usd']+r['start_cohort_redemptions_usd'] for r in group),
            annual_admin_fee_usd=math.fsum(r['administrative_fee_usd'] for r in group),
            annual_fee_start_cohort_usd=math.fsum(r['fee_start_cohort_usd'] for r in group),
            annual_fee_new_cohort_usd=math.fsum(r['fee_new_cohort_usd'] for r in group),
            cumulative_net_contributed_usd=last['cumulative_net_contributed_usd'],
            cumulative_investment_pnl_after_admin_usd=last['cumulative_investment_pnl_after_admin_usd'],
            cumulative_admin_fee_usd=last['cumulative_admin_fee_usd'],
            nav_per_unit=last['nav_per_unit'],
            unit_cumulative_return_after_admin=last['nav_per_unit']/initial_nav-1,
            unit_cagr_after_admin=(last['nav_per_unit']/initial_nav)**(1/year)-1))
    return output

def csv_bytes(rows):
    import io
    f = io.StringIO(newline='')
    writer = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator='\n')
    writer.writeheader()
    for row in rows:
        writer.writerow({k: format(v, '.12f') if isinstance(v, float) else v for k,v in row.items()})
    return f.getvalue().encode()
