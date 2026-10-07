"""Independent cash-asset controls for loss placement and external funding.

This recurrence deliberately does not call the production unit-accounting engine.
Generated baseline tables are comparison inputs, not inputs to the recurrence.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path


def acquisition_schedule(config, rid, sid, *, ticket=None):
    ticket = config['ticket_usd'] if ticket is None else ticket
    annual = config['annual_returns'][rid]
    clients = config['annual_new_client_equivalents'][sid]
    active = config['first_year_subscription_months']
    if len(annual) != len(clients) or not active or len(set(active)) != len(active) or any(m not in range(1, 13) for m in active):
        raise ValueError('invalid acquisition schedule')
    subscriptions, redemptions = [], []
    for i in range(len(annual) * 12):
        year = i // 12
        sub = clients[year] * ticket
        sub = (sub / len(active) if i + 1 in active else 0) if year == 0 else sub / 12
        red = (0 if sid == 'no_flows' else config['sales_stop_annual_redemption']
               if sid == 'sales_stop' else config['normal_annual_redemption'])
        if annual[year] < 0:
            sub *= config['bad_year_subscription_multiplier']
            if sid != 'no_flows':
                red = config['bad_year_annual_redemption']
        subscriptions.append(sub)
        redemptions.append(red)
    return subscriptions, redemptions


def independent_accounts(config, path, subscriptions, redemptions, *, fee=None, receipt=1):
    fee = config['annual_fee'] if fee is None else fee
    if len(path) != 120 or len(subscriptions) != len(path) or len(redemptions) != len(path):
        raise ValueError('current diagnostic schema requires 120 matching months')
    external = 0.0
    own = float(config['initial_owner_capital_usd'])
    cash = fees = reds = low = 0.0
    netprefix = survivalprefix = 1.0
    deposits, rows = [], []
    cohort_error = 0.0
    for i, (r, sub, redannual) in enumerate(zip(path, subscriptions, redemptions)):
        g = 1 + r - fee / 12
        if not math.isfinite(g) or g <= 0 or not 0 <= redannual < 1:
            raise ValueError('invalid net return or redemption fraction')
        opening = external
        externalfee = opening * fee / 12
        ownerfee = own * fee / 12
        survival = (1 - redannual) ** (1 / 12)
        red = opening * g * (1 - survival)
        external = opening * g * survival + sub
        own *= g
        cost = (config['annual_fixed_manager_cost_usd'] * (1 + config['fixed_cost_inflation']) ** (i // 12) / 12
                + config['acquisition_cost_fraction_of_gross_subscriptions'] * sub
                + config['annual_servicing_cost_fraction_of_opening_external_assets'] * opening / 12
                + (config['setup_cost_usd'] if i == 0 else 0))
        netprefix *= g
        survivalprefix *= survival
        prefix = netprefix * survivalprefix
        deposits.append((sub, prefix))
        cohort = math.fsum(amount * prefix / issued for amount, issued in deposits)
        cohort_error = max(cohort_error, abs(cohort - external))
        net = externalfee * receipt - cost
        cash += net
        low = min(low, cash)
        fees += externalfee
        reds += red
        rows.append(dict(owner=own, external=external, total=own + external,
            fee=externalfee, owner_fee=ownerfee, manager_cost=cost,
            manager_cash=cash, redemptions=red, manager_net=net))
    result = dict(owner_equity=own, external_equity=external, total_aum=own + external,
        external_fees=fees, redemptions=reds, manager_cash=cash,
        peak_funding=-low, year10_result=math.fsum(x['manager_net'] for x in rows[-12:]))
    return result, rows, cohort_error


def solve_fee(evaluate, target, settings):
    lo, hi = settings['break_even_fee_lower'], settings['break_even_fee_upper']
    if not 0 <= lo < hi or not evaluate(lo)[target] < 0 < evaluate(hi)[target]:
        raise ValueError('fee bracket must straddle a negative-to-positive target')
    iterations = settings['bisection_iterations']
    if not isinstance(iterations, int) or iterations <= 0:
        raise ValueError('bisection iterations must be positive')
    for _ in range(iterations):
        mid = (lo + hi) / 2
        if evaluate(mid)[target] > 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def loss_controls(config, timing, tables, settings):
    if timing['annual_returns'] != config['annual_returns'] or timing['annual_fee'] != config['annual_fee'] or timing['owner_capital_usd'] != config['initial_owner_capital_usd']:
        raise ValueError('timing and acquisition assumptions disagree')
    cases = []
    baseline_error = cohort_error = owner_error = 0.0

    def run(path, subs, reds, fee=None):
        nonlocal cohort_error
        result, rows, error = independent_accounts(config, path, subs, reds, fee=fee)
        cohort_error = max(cohort_error, error)
        return result, rows

    for layer in ['acquisition', 'timing']:
        scenario_key = 'flow_scenario' if layer == 'acquisition' else 'timing_scenario'
        scenarios = config['annual_new_client_equivalents'] if layer == 'acquisition' else timing['monthly_schedules_usd']
        for rid, annual in config['annual_returns'].items():
            path = [(1 + r) ** (1 / 12) - 1 for r in annual for _ in range(12)]
            for sid in scenarios:
                if layer == 'acquisition':
                    subs, reds = acquisition_schedule(config, rid, sid)
                else:
                    subs = timing['monthly_schedules_usd'][sid]
                    reds = [timing['annual_external_unit_redemption']] * len(path)
                base, monthly = run(path, subs, reds)
                saved = [z for z in tables[layer] if z['return_scenario'] == rid and z[scenario_key] == sid]
                if [int(z['month']) for z in saved] != list(range(1, 121)):
                    raise ValueError('baseline comparison requires 120 ordered account months')
                fields = (dict(owner='owner_equity_usd', external='external_equity_usd', total='closing_aum_usd', fee='external_fee_usd', redemptions='redemptions_usd')
                    if layer == 'acquisition' else dict(owner='start_cohort_equity_usd', external='new_cohort_equity_usd', total='closing_net_aum_usd', fee='fee_new_cohort_usd', redemptions='new_cohort_redemptions_usd'))
                fields['manager_cash'] = 'cumulative_manager_cash_usd'
                for z, value in zip(saved, monthly):
                    for a, b in fields.items():
                        baseline_error = max(baseline_error, abs(value[a] - float(z[b])))
                cases.append(dict(layer=layer, return_scenario=rid, flow=sid, mode='baseline', shock_month=None, **base))
                if rid not in settings['loss_year_by_return_scenario']:
                    continue
                loss_year = settings['loss_year_by_return_scenario'][rid]
                if loss_year not in range(1, len(annual) + 1) or annual[loss_year - 1] >= 0:
                    raise ValueError('configured loss year must identify a negative-return year')
                start = (loss_year - 1) * 12
                f = config['annual_fee'] / 12
                target = (1 + path[start] - f) ** 12
                matched = target / (1 - f) ** 11 - 1 + f
                for mode, shock in [('same_gross_annual_return', annual[loss_year - 1]), ('same_net_annual_return', matched)]:
                    for j in range(12):
                        altered = path.copy()
                        altered[start:start + 12] = [0.0] * 12
                        altered[start + j] = shock
                        value, _ = run(altered, subs, reds)
                        if mode == 'same_net_annual_return':
                            owner_error = max(owner_error, abs(value['owner_equity'] - base['owner_equity']))
                        cases.append(dict(layer=layer, return_scenario=rid, flow=sid,
                            mode=mode, shock_month=j + 1, shock_return=shock, **value))
    rid, sid = config['sensitivity_return_scenario'], config['sensitivity_flow_scenario']
    path = [(1 + r) ** (1 / 12) - 1 for r in config['annual_returns'][rid] for _ in range(12)]
    subs, reds = acquisition_schedule(config, rid, sid)
    roots = []
    for field in ['year10_result', 'manager_cash']:
        fee = solve_fee(lambda f: run(path, subs, reds, f)[0], field, settings)
        value, monthly = run(path, subs, reds, fee)
        low = min(enumerate(monthly, 1), key=lambda x: x[1]['manager_cash'])
        roots.append(dict(target=field, annual_fee_bps=fee * 10000, peak_month=low[0], **value))
    illustration, monthly = run(path, subs, reds, settings['illustrative_fee'])
    illustration['peak_month'] = min(enumerate(monthly, 1), key=lambda x: x[1]['manager_cash'])[0]
    tolerance = settings['comparison_tolerance_usd']
    if max(baseline_error, cohort_error, owner_error) >= tolerance:
        raise AssertionError('independent baseline/cohort/owner comparison failed')
    summary = dict(baseline_cases=sum(c['mode'] == 'baseline' for c in cases),
        loss_sensitivity_cases=sum(c['mode'] != 'baseline' for c in cases),
        monthly_rows_per_case=120, baseline_max_error_usd=baseline_error,
        independent_cohort_max_error_usd=cohort_error, same_net_owner_max_error_usd=owner_error,
        break_even_fees=roots, illustrative_fee=settings['illustrative_fee'], illustrative_fee_result=illustration)
    return dict(summary=summary, cases=cases)


def read_csv(path):
    with Path(path).open() as f:
        return list(csv.DictReader(f))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--acquisition-config', type=Path, required=True)
    parser.add_argument('--timing-config', type=Path, required=True)
    parser.add_argument('--controls-config', type=Path, required=True)
    parser.add_argument('--tables', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(args.acquisition_config.read_text())
    timing = json.loads(args.timing_config.read_text())
    settings = json.loads(args.controls_config.read_text())
    tables = {layer: read_csv(args.tables / f'{layer}_monthly.csv') for layer in ['acquisition', 'timing']}
    result = loss_controls(config, timing, tables, settings)
    from .inflow_treasury import treasury_controls, sensitivity_controls
    cash = treasury_controls(config, settings, result['summary']['break_even_fees'])
    sensitivity = sensitivity_controls(config, settings, args.tables)
    args.output.mkdir(parents=True, exist_ok=False)
    for name, payload in [('loss_controls.json', result), ('treasury_controls.json', cash), ('funding_sensitivity.json', sensitivity), ('control_settings.json', settings)]:
        (args.output / name).write_text(json.dumps(payload, indent=2) + '\n')
    print(f"Created {result['summary']['loss_sensitivity_cases']} loss controls, treasury roots and funding sensitivities.")


if __name__ == '__main__':
    main()
