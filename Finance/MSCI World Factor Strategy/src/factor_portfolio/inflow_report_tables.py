"""Twelve report-table fragments from calculated inflow outputs and assumptions."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

from .inflow_figures import ACQUISITION_LABELS, TIMING_LABELS, read_table


def select_one(rows, **filters):
    matches = [r for r in rows if all(
        math.isclose(r[k], v, rel_tol=0, abs_tol=1e-12)
        if isinstance(v, (int, float)) else r[k] == v for k, v in filters.items())]
    if len(matches) != 1:
        raise ValueError(f'expected one source row for {filters}, found {len(matches)}')
    return matches[0]


def format_value(value, style):
    if style == 'text':
        return str(value)
    if style == 'clients':
        return ', '.join(f'{x:g}' for x in value)
    if not math.isfinite(value):
        raise ValueError('non-finite report value')
    if style == 'million2':
        return f'{value / 1e6:.2f}'
    if style == 'usd0':
        return f'{value:,.0f}'
    if style == 'usd2':
        return f'{value:,.2f}'
    if style == 'pct2':
        return f'{value * 100:.2f}%'
    if style == 'return_pct2':
        return f'{value:.2f}%'
    raise ValueError(f'unknown report format: {style}')


def schedule_definition(schedule):
    if len(schedule) != 120 or any(not math.isfinite(x) or x < 0 for x in schedule):
        raise ValueError('schedule presentation requires 120 nonnegative finite amounts')
    entries = [(m, x) for m, x in enumerate(schedule, 1) if x != 0]
    if not entries:
        return 'USD 0; separate reference, not a matched-volume case'
    months, values = zip(*entries)
    equal = all(math.isclose(x, values[0], rel_tol=1e-12, abs_tol=1e-6) for x in values)
    consecutive = list(months) == list(range(months[0], months[-1] + 1))
    if consecutive and equal:
        return f'USD {values[0]:,.0f} each month, months {months[0]}–{months[-1]}; cumulative subscriptions grow linearly'
    if consecutive and len(values) > 2:
        delta = values[1] - values[0]
        if delta > 0 and all(math.isclose(b - a, delta, rel_tol=1e-10, abs_tol=1e-6) for a, b in zip(values, values[1:])):
            return f'Monthly amounts increase linearly from USD {values[0]:,.0f} in month {months[0]} to USD {values[-1]:,.0f} in month {months[-1]}; cumulative subscriptions accelerate'
    if equal:
        listed = ', '.join(str(m) for m in months[:-1]) + (' and ' if len(months) > 1 else '') + str(months[-1])
        return f'USD {values[0] / 1e6:g} million at the end of months {listed}'
    return f'Configured month-end subscriptions, USD {math.fsum(schedule):,.0f} total; see the exact monthly schedule'


def report_tables(business, timing, selection, tables, investor, loss, treasury, funding):
    if any(len(path) != 10 for path in business['annual_returns'].values()):
        raise ValueError('current report presentation requires ten-year paths')
    result = []

    def add(name, section, title, columns, rows, sources, *, evidence=None, note=''):
        result.append(dict(id=name, section=section, title=title,
            columns=[dict(heading=h, format=f) for h, f in columns],
            rows=rows, sources=sources, evidence=evidence, note=note))

    acquisition_ids = list(business['annual_new_client_equivalents'])
    timing_ids = list(timing['monthly_schedules_usd'])
    paths = list(business['annual_returns'])
    main = selection['main_return_scenario']
    if main != business['sensitivity_return_scenario']:
        raise ValueError('main presentation and fee-sensitivity return scenarios must agree')
    labels_a, labels_t = ACQUISITION_LABELS, TIMING_LABELS
    a = tables['acquisition_headline.csv']
    t = tables['timing_headline.csv']
    for row in a + t:
        if row['year'] != 10:
            raise ValueError('headline table must end in year 10')

    add('01_acquisition_assumptions', '3.1', 'External client acquisition',
        [('Case', 'text'), ('Annual new client equivalents, years 1–10', 'clients'),
         ('Scheduled ten-year gross subscriptions (USD m), before stress cuts', 'million2')],
        [[labels_a[sid], business['annual_new_client_equivalents'][sid],
          math.fsum(business['annual_new_client_equivalents'][sid]) * business['ticket_usd']] for sid in acquisition_ids],
        ['inflow_acquisition.json'], note='Scheduled gross amounts precede stress cuts; counts are proposed client equivalents.')

    money = lambda x: f'USD {x:,.0f}'
    percent = lambda x: f'{x * 100:.2f}%'
    pct_general = lambda x: f'{x * 100:g}%'
    other_fees = [x for x in business['fee_sensitivity'] if x != business['annual_fee']]
    other_receipts = [x for x in business['manager_fee_receipt_fractions'] if x != 1]
    business_rows = [
        ['Annual fixed manager cost', f"{money(business['annual_fixed_manager_cost_usd'])} in year 1, rising {pct_general(business['fixed_cost_inflation'])} annually", 'Explicit lean-budget sensitivity; no provider quotation and no full-time salary provision'],
        ['Setup cost', f"{money(business['setup_cost_usd'])} paid in month 1", 'Makes initial funding visible; illustrative, no fund-formation quote'],
        ['Acquisition spending', f"{percent(business['acquisition_cost_fraction_of_gross_subscriptions'])} of gross subscriptions", 'Links fundraising to costs; includes no assumed asset-based perpetual commission'],
        ['Servicing cost', f"{percent(business['annual_servicing_cost_fraction_of_opening_external_assets'])} annually of opening external assets", 'Illustrates variable scale cost; not an actual administration tariff'],
        ['Manager receives investor fee', f"100% centrally; {', '.join(pct_general(x) for x in other_receipts)} sensitivity", 'Separates investor fee from manager receipts; actual contract unknown'],
        ['Investor fee', f"{percent(business['annual_fee'])} centrally; {', '.join(percent(x) for x in other_fees)} sensitivities", 'Tests economics and investor drag together; no fee proposal adopted'],
    ]
    add('02_business_assumptions', '3.3', 'Business costs and fee receipt',
        [('Input', 'text'), ('Central discussion assumption', 'text'), ('Why included / challenge', 'text')],
        business_rows, ['inflow_acquisition.json'], evidence={k: business[k] for k in [
            'annual_fixed_manager_cost_usd', 'fixed_cost_inflation', 'setup_cost_usd',
            'acquisition_cost_fraction_of_gross_subscriptions', 'annual_servicing_cost_fraction_of_opening_external_assets',
            'annual_fee', 'fee_sensitivity', 'manager_fee_receipt_fractions']},
        note='Costs are paid outside the fund; assumptions are illustrative and prose requires editorial review when scope changes.')

    def acquisition_row(sid):
        r = select_one(a, return_scenario=main, flow_scenario=sid)
        return [labels_a[sid]] + [r[k] for k in ['owner_equity_usd', 'external_equity_usd', 'annual_external_fee_usd', 'annual_manager_net_cash_usd', 'cumulative_manager_cash_usd']]

    add('03_acquisition_outcomes', '6.1', 'Client-acquisition outcomes',
        [('Case', 'text'), ('Owner equity, year 10 (USD m)', 'million2'), ('External equity, year 10 (USD m)', 'million2'),
         ('External fees, year 10 (USD)', 'usd0'), ('Manager result, year 10 (USD)', 'usd0'), ('Cumulative manager cash, ten years (USD)', 'usd0')],
        [acquisition_row(sid) for sid in acquisition_ids], ['acquisition_headline.csv'], evidence={'return_scenario': main})

    def timing_rows(ids):
        rows = []
        for sid in ids:
            r = select_one(t, return_scenario=main, timing_scenario=sid)
            rows.append([labels_t[sid]] + [r[k] for k in ['closing_net_aum_usd', 'cumulative_external_redemptions_usd', 'cumulative_external_fees_usd', 'cumulative_manager_cash_usd']])
        return rows

    add('04_selected_timing_outcomes', '6.2', 'Equal gross subscriptions, selected timing cases',
        [('Timing case', 'text'), ('Total fund assets, year 10 (USD m)', 'million2'), ('Cumulative external redemptions (USD m)', 'million2'),
         ('Ten-year external fees (USD)', 'usd0'), ('Ten-year manager cash (USD)', 'usd0')],
        timing_rows(selection['selected_timing_cases']), ['timing_headline.csv'], evidence={'return_scenario': main})
    return_rows = []
    for sid in selection['selected_timing_cases']:
        r = select_one(investor['external_investor_returns'], return_path=selection['investor_return_scenario'], timing=sid)
        return_rows.append([labels_t[sid], r['twr_annual_pct'], r['aggregate_external_mwr_annual_pct']])
    add('05_investor_returns', '6.3', 'Unit and aggregate external investor returns',
        [('Timing case', 'text'), ('Annualised unit TWR', 'return_pct2'), ('Annualised aggregate external MWR', 'return_pct2')],
        return_rows, ['return_diagnostics.json'], evidence={'return_scenario': selection['investor_return_scenario']},
        note='Equal monthly periods; aggregate external MWR is not an individual investor return or a dated XIRR.')

    ranges = []
    for item in selection['loss_range_cases']:
        matches = [r for r in loss['cases'] if r['layer'] == item['layer'] and r['flow'] == item['flow']
            and r['return_scenario'] == selection['loss_return_scenario'] and r['mode'] == 'same_net_annual_return']
        if sorted(r['shock_month'] for r in matches) != list(range(1, 13)):
            raise ValueError('loss-range table requires all twelve matched-net placements')
        values = [r['total_aum'] for r in matches]
        label = (labels_a if item['layer'] == 'acquisition' else labels_t)[item['flow']]
        ranges.append([label, min(values), max(values), max(values) - min(values)])
    add('06_loss_placement_ranges', '7', 'Within-year loss-placement ranges',
        [('Loss-placement control', 'text'), ('Minimum ending total assets (USD)', 'usd2'), ('Maximum ending total assets (USD)', 'usd2'), ('Range (USD)', 'usd2')],
        ranges, ['loss_controls.json'], evidence={'return_scenario': selection['loss_return_scenario'], 'mode': 'same_net_annual_return'},
        note='Range is calculated from unrounded endpoints; matching net annual unit performance preserves owner terminal equity.')

    fee_rows, treasury_rows = [], []
    for fee in business['fee_sensitivity']:
        r = select_one(tables['fee_ticket_receipt_sensitivity.csv'], annual_fee=fee, ticket_usd=business['ticket_usd'], manager_receipt_fraction=selection['fee_manager_receipt_fraction'])
        fee_rows.append([fee] + [r[k] for k in ['owner_equity_year10_usd', 'external_fee_year10_usd', 'manager_net_year10_usd', 'cumulative_manager_cash_usd']])
        external = select_one(funding['fee_cases_with_peak_funding'], annual_fee=fee)
        internal = select_one(treasury['fee_cases'], annual_fee_bps=fee * 10000)
        treasury_rows.append([fee, external['cumulative_manager_cash_usd'], external['peak_funding_gap'], internal['including_owner_fee_cash'], internal['including_owner_fee_peak_funding']])
    if selection['fee_manager_receipt_fraction'] != 1:
        raise ValueError('current paired treasury presentation requires full external fee receipt')
    add('07_fee_economics', '8', 'Fee economics',
        [('Annual fee', 'pct2'), ('Owner equity, year 10 (USD m)', 'million2'), ('External fee, year 10 (USD)', 'usd0'), ('Manager result, year 10 (USD)', 'usd0'), ('Ten-year manager cash (USD)', 'usd0')],
        fee_rows, ['fee_ticket_receipt_sensitivity.csv'], evidence={'ticket_usd': business['ticket_usd'], 'manager_receipt_fraction': selection['fee_manager_receipt_fraction'],
            'return_scenario': main, 'flow_scenario': business['sensitivity_flow_scenario']})
    add('08_treasury_definitions', '8', 'Closing cash versus peak funding',
        [('Annual fee', 'pct2'), ('Closing cash, external fees only (USD)', 'usd0'), ('Peak deficit, external fees only (USD)', 'usd0'),
         ('Closing cash, including owner fees (USD)', 'usd0'), ('Peak deficit, including owner fees (USD)', 'usd0')],
        treasury_rows, ['treasury_controls.json', 'funding_sensitivity.json'], note=treasury['conditions'])

    def path_label(rid):
        values = business['annual_returns'][rid]
        if len(set(values)) == 1:
            return 'Flat' if values[0] == 0 else pct_general(values[0])
        return {'early_loss': 'Early loss', 'late_loss': 'Later loss'}.get(rid, rid)

    path_columns = [(path_label(rid), 'million2') for rid in paths]
    add('09_acquisition_return_matrix', 'Appendix A', 'All acquisition return paths',
        [('Flow case', 'text')] + path_columns,
        [[labels_a[sid]] + [select_one(a, return_scenario=rid, flow_scenario=sid)['closing_aum_usd'] for rid in paths] for sid in acquisition_ids],
        ['acquisition_headline.csv'], evidence={'return_scenarios': paths}, note='Ending fund assets, not cumulative investor wealth.')
    add('10_timing_schedules', 'C.1', 'Timing schedule definitions', [('Schedule', 'text'), ('Definition', 'text')],
        [[labels_t[sid], schedule_definition(timing['monthly_schedules_usd'][sid])] for sid in timing_ids],
        ['inflow_timing.json'], evidence=timing['monthly_schedules_usd'], note='Rounded amounts describe display only; calculation uses the exact monthly schedule.')
    add('11_all_timing_outcomes', 'C.2', 'All timing cases under the selected return path',
        [('Timing case', 'text'), ('Total fund assets, year 10 (USD m)', 'million2'), ('Cumulative external redemptions (USD m)', 'million2'),
         ('Cumulative external fees (USD)', 'usd0'), ('Ten-year manager cash (USD)', 'usd0')],
        timing_rows(timing_ids), ['timing_headline.csv'], evidence={'return_scenario': main})
    add('12_timing_return_matrix', 'C.5', 'All timing return paths', [('Timing case', 'text')] + path_columns,
        [[labels_t[sid]] + [select_one(t, return_scenario=rid, timing_scenario=sid)['closing_net_aum_usd'] for rid in paths] for sid in timing_ids],
        ['timing_headline.csv'], evidence={'return_scenarios': paths}, note='Ending fund assets, not cumulative investor wealth.')
    return result


def markdown_table(spec):
    columns = spec['columns']
    def line(values):
        return '| ' + ' | '.join(str(x).replace('|', '\\|').replace('\n', ' ') for x in values) + ' |'
    lines = [line(c['heading'] for c in columns),
             line('---' if c['format'] in {'text', 'clients'} else '---:' for c in columns)]
    for row in spec['rows']:
        if len(row) != len(columns):
            raise ValueError('report row does not match its columns')
        lines.append(line(format_value(v, c['format']) for v, c in zip(row, columns)))
    return '\n'.join(lines)


def write_tables(specs, output, files, *, run_manifest=None):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    book = ['# Capital-inflow study: generated table fragments', '',
        'Local working output. These twelve tables reproduce the selected report presentation; this is not the full report or a publication.', '',
        'After economic assumptions change, recalculate baseline tables, investor returns and controls together before regenerating these fragments. Prose and interpretation need editorial review.', '']
    for spec in specs:
        fragment = '\n'.join([f"## {spec['section']} · {spec['title']}", '', markdown_table(spec), '',
            'Sources: ' + ', '.join(f'`{name}`' for name in spec['sources']) + '.', '', spec['note'], ''])
        (output / (spec['id'] + '.md')).write_text(fragment)
        book.append(fragment)
    (output / 'report_tables.md').write_text('\n'.join(book))
    (output / 'report_tables.json').write_text(json.dumps(specs, indent=2, ensure_ascii=False) + '\n')
    (output / 'input_manifest.json').write_text(json.dumps({
        'inputs': {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in files.items()},
        'run_manifest': run_manifest,
        'scope': ('All producers belong to the enclosing unified run and its configuration snapshots.' if run_manifest
                  else 'Input hashes record the selected bundle; they do not independently establish that all producers used identical configuration versions.'),
    }, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ['acquisition-config', 'timing-config', 'presentation-config', 'tables', 'returns', 'controls', 'output']:
        parser.add_argument('--' + flag, type=Path, required=True)
    args = parser.parse_args()
    files = {'inflow_acquisition.json': args.acquisition_config, 'inflow_timing.json': args.timing_config,
        'inflow_presentation.json': args.presentation_config,
        'return_diagnostics.json': args.returns / 'return_diagnostics.json',
        'loss_controls.json': args.controls / 'loss_controls.json',
        'treasury_controls.json': args.controls / 'treasury_controls.json',
        'funding_sensitivity.json': args.controls / 'funding_sensitivity.json'}
    csv_names = ['acquisition_headline.csv', 'timing_headline.csv', 'fee_ticket_receipt_sensitivity.csv']
    files.update({name: args.tables / name for name in csv_names})
    payload = {name: json.loads(path.read_text()) for name, path in files.items() if name.endswith('.json')}
    tables = {name: read_table(files[name]) for name in csv_names}
    specs = report_tables(payload['inflow_acquisition.json'], payload['inflow_timing.json'], payload['inflow_presentation.json'],
        tables, payload['return_diagnostics.json'], payload['loss_controls.json'], payload['treasury_controls.json'], payload['funding_sensitivity.json'])
    write_tables(specs, args.output, files)
    print(f'Created {len(specs)} report tables, full-precision records and input hashes.')


if __name__ == '__main__':
    main()
