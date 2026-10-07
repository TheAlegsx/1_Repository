"""Assemble the reviewed inflow discussion text from this run's numerical evidence."""
from __future__ import annotations

import hashlib
from importlib.resources import files
import json
import math
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

from .inflow_report_tables import markdown_table, select_one

TOKEN = re.compile(r'\{\{(claim|table|figure):([^{}]+)\}\}')
LINK = re.compile(r'!?\[[^\]]*\]\(([^\s)]+)\)')


def configuration_digest(config):
    return hashlib.sha256(json.dumps(config, sort_keys=True, separators=(',', ':'),
        ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def load_template():
    root = files('factor_portfolio').joinpath('templates')
    return {name: root.joinpath(name).read_bytes() for name in
        ['inflow_report.md', 'inflow_report_review.json']}


def validate_template(configs, resources):
    review = json.loads(resources['inflow_report_review.json'])
    if review['schema_version'] != 1:
        raise ValueError('unsupported report template review schema')
    if hashlib.sha256(resources['inflow_report.md']).hexdigest() != review['reviewed_template_sha256']:
        raise ValueError('report text changed; review the template and update its review metadata')
    expected = review['reviewed_configuration_sha256']
    if set(configs) != set(expected) or any(configuration_digest(configs[n]) != expected[n] for n in configs):
        raise ValueError('report interpretations require editorial review for changed assumptions; '
            'use --no-report for numerical experiments, then review the template and its metadata')
    return review


def prose_claims(configs, tables, investor, loss, treasury, review):
    """Retain raw values, formatting and selectable sources for each numerical span."""
    b, t = configs['inflow_acquisition.json'], configs['inflow_timing.json']
    selection = configs['inflow_presentation.json']
    controls = configs['inflow_controls.json']
    claims = {}
    pct = lambda x: f'{x * 100:g}%'
    bps = lambda x: f'{x * 10000:g}bp'
    money = lambda x: f'USD {x:,.0f}'
    million = lambda x: f'USD {x / 1e6:g} million'

    def source(artifact, field, **selector):
        return dict(artifact=artifact, field=field, selector=selector)

    def add(key, value, display, origins, expression=None):
        claims[key] = dict(value=value, display=display, sources=origins, expression=expression)

    def config(key, field, display, *, name='inflow_acquisition.json'):
        value = configs[name][field]
        add(key, value, display(value), [source('../config/' + name, field)])

    config('owner_capital_m', 'initial_owner_capital_usd', lambda x: f'{x / 1e6:g}')
    config('capital_usd_m', 'initial_owner_capital_usd', million)
    config('owners_capital', 'initial_owner_capital_usd', lambda x: "owners' " + million(x))
    config('ticket_usd', 'ticket_usd', money)
    config('baseline_fee', 'annual_fee', lambda x: f'{x * 100:.2f}% ({x * 10000:g} basis points)')
    for key, formatter in [('fee_bps', lambda x: bps(x) + ' fee'),
                           ('baseline_fee_bps', lambda x: bps(x) + ' investor fees'),
                           ('full_fee_bps', lambda x: 'full ' + bps(x) + ' receipt'),
                           ('investor_fee_short', lambda x: 'fees of ' + bps(x)),
                           ('short_fee', lambda x: 'A ' + bps(x) + ' fee'),
                           ('annual_fee_pct', lambda x: f'{x * 100:.2f}% annually'),
                           ('baseline_bps', bps)]:
        config(key, 'annual_fee', formatter)
    config('ordinary_attrition', 'normal_annual_redemption', lambda x: pct(x) + ' annual')
    config('ordinary_attrition_pct', 'normal_annual_redemption', pct)
    config('runoff_attrition', 'sales_stop_annual_redemption', pct)
    config('stress_attrition', 'bad_year_annual_redemption', pct)
    config('stress_subscription_fraction', 'bad_year_subscription_multiplier',
        lambda x: 'halved' if x == .5 else f'multiplied by {x:g}')
    config('timing_attrition', 'annual_external_unit_redemption', pct, name='inflow_timing.json')
    config('timing_attrition_annual', 'annual_external_unit_redemption', lambda x: pct(x) + ' annually', name='inflow_timing.json')
    config('timing_attrition_year', 'annual_external_unit_redemption', lambda x: pct(x) + ' annual', name='inflow_timing.json')
    active = b['first_year_subscription_months']
    origin = [source('../config/inflow_acquisition.json', 'first_year_subscription_months')]
    add('launch_months', active, f'months {min(active)}–{max(active)}', origin)
    add('launch_first_month', min(active), f'month {min(active)}', origin, 'minimum subscription month')
    delay = min(active) - 1
    add('launch_delay', delay, ('six' if delay == 6 else str(delay)) + '-month delay', origin, 'first month minus one')
    add('prelaunch_months', delay, f'months 1–{delay}', origin, 'months before first subscription')
    clients = b['annual_new_client_equivalents']['strong'][-1]
    add('strong_final_clients', clients, f'{clients:g} new client equivalents',
        [source('../config/inflow_acquisition.json', 'annual_new_client_equivalents.strong[9]')])
    alternative = [x for x in b['ticket_sensitivity_usd'] if x != b['ticket_usd']]
    add('alternative_tickets', alternative, ' and '.join(money(x) for x in alternative),
        [source('../config/inflow_acquisition.json', 'ticket_sensitivity_usd'), source('../config/inflow_acquisition.json', 'ticket_usd')])
    annual = b['annual_returns']
    main = selection['main_return_scenario']
    growth = annual[main][0]
    origins = [source('../config/inflow_acquisition.json', 'annual_returns')]
    later = f'{pct(annual["late_loss"][0])} in years 1–3, {pct(annual["late_loss"][3]).replace("-", "−")} in year 4, then {pct(annual["late_loss"][4])}'
    paths = f'{pct(annual["flat"][0])} throughout; {pct(growth)} throughout; {pct(annual["early_loss"][0]).replace("-", "−")} in year 1 then {pct(annual["early_loss"][1])}; and '
    add('later_return_path', annual['late_loss'], later, origins)
    add('return_paths_emphasised', annual, paths + '**' + later + '**', origins)
    add('return_paths', annual, paths + later.replace('year 4, then', 'year 4 then'), origins)
    add('growth_pct', growth, pct(growth), origins)
    add('main_return_path', growth, f'same {pct(growth)} path', origins)
    add('main_illustration', growth, f'concise {pct(growth)} illustration', origins)
    shock = annual['late_loss'][3]
    add('loss_annual_pct', shock, pct(shock).replace('-', '−'), origins)
    monthly = (1 + shock) ** (1 / 12) - 1
    add('smooth_loss_monthly', monthly, ('approximately ' + f'{monthly * 100:.4f}%').replace('-', '−'), origins, '(1 + annual loss)^(1/12) - 1')
    years, periods = len(annual[main]), configs['inflow_returns.json']['months_per_year']
    add('months', years * periods, f'{years * periods} months', origins + [source('../config/inflow_returns.json', 'months_per_year')], 'years times months per year')
    add('months_per_year_words', periods, 'twelve' if periods == 12 else str(periods), [source('../config/inflow_returns.json', 'months_per_year')])
    for layer in ['acquisition', 'timing']:
        rows = tables[f'{layer}_monthly.csv']
        add(layer + '_rows', len(rows), f'{len(rows):,}', [source(f'../tables/{layer}_monthly.csv', 'row count')])
        key = 'flow_scenario' if layer == 'acquisition' else 'timing_scenario'
        count = len({(r['return_scenario'], r[key]) for r in rows})
        add(layer + '_cases', count, str(count), [source(f'../tables/{layer}_monthly.csv', 'distinct scenario pairs')])
    add('baseline_cases', loss['summary']['baseline_cases'], str(loss['summary']['baseline_cases']), [source('../controls/loss_controls.json', 'summary.baseline_cases')])
    a = tables['acquisition_headline.csv']
    # Named paths preserve the sentence's meaning even if JSON object keys reorder.
    no_flow = [select_one(a, return_scenario=rid, flow_scenario='no_flows')['owner_equity_usd']
               for rid in ['flat', 'growth', 'early_loss', 'late_loss']]
    description = (f'USD {no_flow[0] / 1e6:.2f} million under {pct(annual["flat"][0])}, '
        f'USD {no_flow[1] / 1e6:.2f} million under {pct(growth)}, '
        f'USD {no_flow[2] / 1e6:.2f} million under the early loss, and USD {no_flow[3] / 1e6:.2f} million under the later loss')
    add('no_flow_equities', no_flow, description, [source('../tables/acquisition_headline.csv', 'owner_equity_usd', flow_scenario='no_flows')])
    row = select_one(a, return_scenario=main, flow_scenario='steady')
    origin = [source('../tables/acquisition_headline.csv', 'gross_subscriptions_10y_usd', return_scenario=main, flow_scenario='steady')]
    add('steady_gross', row['gross_subscriptions_10y_usd'], f'USD {row["gross_subscriptions_10y_usd"] / 1e6:.2f} million gross subscriptions', origin)
    add('steady_fees', row['external_fees_10y_usd'], money(row['external_fees_10y_usd']) + ' cumulative external fees', [source('../tables/acquisition_headline.csv', 'external_fees_10y_usd', return_scenario=main, flow_scenario='steady')])
    for sid in ['steady', 'strong']:
        value = select_one(a, return_scenario=main, flow_scenario=sid)['peak_business_funding_gap_usd']
        add(sid + '_peak', value, money(value), [source('../tables/acquisition_headline.csv', 'peak_business_funding_gap_usd', return_scenario=main, flow_scenario=sid)])
    owner = row['owner_equity_usd']
    add('owner_growth_equity', owner, f'USD {owner / 1e6:.2f} million', [source('../tables/acquisition_headline.csv', 'owner_equity_usd', return_scenario=main, flow_scenario='steady')])
    config('timing_gross', 'total_gross_subscriptions_per_timing_case_usd', million, name='inflow_timing.json')
    tranches = [x for x in t['monthly_schedules_usd']['even_steps'] if x]
    if len(set(tranches)) != 1:
        raise ValueError('reviewed text requires equal timing tranches')
    add('timing_tranche', tranches[0], million(tranches[0]), [source('../config/inflow_timing.json', 'monthly_schedules_usd.even_steps')])
    returns = [r for r in investor['external_investor_returns'] if r['return_path'] == main]
    if not returns or any(abs(r['aggregate_external_mwr_annual_pct'] - r['twr_annual_pct']) > 1e-8 for r in returns):
        raise ValueError('constant-growth TWR/MWR interpretation no longer agrees with evidence')
    value = returns[0]['twr_annual_pct']
    add('growth_unit_return', value, f'{value:.4f}%', [source('../returns/return_diagnostics.json', 'external_investor_returns.twr_annual_pct', return_path=main)])
    count = len(investor['external_investor_returns'])
    add('investor_return_count', count, ('twenty' if count == 20 else str(count)) + ' non-zero-flow', [source('../returns/return_diagnostics.json', 'external_investor_returns count')])
    loss_rows = [r for r in loss['cases'] if r['layer'] == 'timing' and r['flow'] == 'early_steps' and r['return_scenario'] == selection['loss_return_scenario'] and r['mode'] == 'same_net_annual_return']
    if len(loss_rows) != 12:
        raise ValueError('reviewed text requires twelve early-tranche loss placements')
    value = max(r['total_aum'] for r in loss_rows) - min(r['total_aum'] for r in loss_rows)
    add('early_loss_range', value, f'USD {value:,.2f}', [source('../controls/loss_controls.json', 'cases.total_aum', layer='timing', flow='early_steps', return_scenario=selection['loss_return_scenario'], mode='same_net_annual_return')], 'maximum minus minimum')
    value = loss['summary']['same_net_owner_max_error_usd']
    # Round the upper bound upwards: a residual disclosure must not understate it.
    bound = math.ceil(value * 1e9) / 1e9
    add('owner_control_residual', value, f'USD {bound:.9f}', [source('../controls/loss_controls.json', 'summary.same_net_owner_max_error_usd')], 'upper bound rounded upward to 1e-9 USD')
    value = loss['summary']['loss_sensitivity_cases']
    add('loss_control_count', value, f'{value} controls', [source('../controls/loss_controls.json', 'summary.loss_sensitivity_cases')])
    illustrative = loss['summary']['illustrative_fee_result']
    for key, field, suffix, sign in [('illustrative_closing_deficit', 'manager_cash', ' closing deficit', -1), ('illustrative_peak', 'peak_funding', ' peak deficit', 1), ('illustrative_peak_month', 'peak_month', '', 1)]:
        value = illustrative[field]
        add(key, value, (f'month {value}' if field == 'peak_month' else money(sign * value) + suffix), [source('../controls/loss_controls.json', 'summary.illustrative_fee_result.' + field)])
    fee = controls['illustrative_fee']
    origin = [source('../config/inflow_controls.json', 'illustrative_fee')]
    add('illustrative_fee_bps', fee, 'At ' + bps(fee), origin)
    add('illustrative_bps', fee, bps(fee), origin)
    row = select_one(treasury['fee_cases'], annual_fee_bps=fee * 10000)
    for key, field in [('illustrative_owner_fees', 'cumulative_owner_fees'), ('illustrative_total_cash', 'including_owner_fee_cash'), ('illustrative_owner_peak', 'including_owner_fee_peak_funding')]:
        add(key, row[field], money(row[field]), [source('../controls/treasury_controls.json', 'fee_cases.' + field, annual_fee_bps=fee * 10000)])
    add('owner_receipt', 1.0, '100% of fees', [source('../controls/treasury_controls.json', 'conditions')])
    for key, formatter in [('servicing_bps', lambda x: bps(x) + ' servicing costs'), ('servicing_variable_bps', lambda x: bps(x) + ' variable servicing cost'), ('servicing_cost_pct', lambda x: f'{x * 100:.2f}% of opening external assets')]:
        config(key, 'annual_servicing_cost_fraction_of_opening_external_assets', formatter)
    receipts = [x for x in b['manager_fee_receipt_fractions'] if x != 1]
    if len(receipts) != 1:
        raise ValueError('reviewed partial-receipt illustration requires one alternative')
    add('half_receipt', receipts[0], pct(receipts[0]) + ' receipt', [source('../config/inflow_acquisition.json', 'manager_fee_receipt_fractions')])
    fee, servicing = b['annual_fee'], b['annual_servicing_cost_fraction_of_opening_external_assets']
    origin = [source('../config/inflow_acquisition.json', 'annual_fee'), source('../config/inflow_acquisition.json', 'annual_servicing_cost_fraction_of_opening_external_assets')]
    add('net_margin_bps', fee - servicing, bps(fee - servicing), origin, 'full investor fee minus annual servicing rate')
    add('partial_margin_bps', fee * receipts[0] - servicing, bps(fee * receipts[0] - servicing), origin + [source('../config/inflow_acquisition.json', 'manager_fee_receipt_fractions')], 'partial investor fee receipt minus servicing rate')
    static = review['static_fixed_cost_example_usd']
    origin_static = [source('template_review.json', 'static_fixed_cost_example_usd')]
    add('static_cost', static, money(static) + ' cost', origin_static)
    add('static_aum_no_variable', static / fee, million(static / fee), origin_static + origin, 'illustrative static cost divided by fee; no variable costs')
    add('static_aum_with_variable', static / (fee - servicing), f'USD {static / (fee - servicing) / 1e6:.1f} million', origin_static + origin, 'illustrative static cost divided by fee minus servicing rate')
    for key, name, label in [('fee_case_count', 'fee_ticket_receipt_sensitivity.csv', 'fee/ticket/receipt table'), ('cost_case_count', 'business_cost_sensitivity.csv', 'business-cost sensitivity')]:
        value = len(tables[name])
        add(key, value, f'{value}-case {label}', [source('../tables/' + name, 'row count')])
    grid = b['business_cost_sensitivity']
    add('fixed_cost_grid', grid['first_year_fixed_cost_usd'], 'USD ' + ' / '.join(f'{x:,.0f}' for x in grid['first_year_fixed_cost_usd']), [source('../config/inflow_acquisition.json', 'business_cost_sensitivity.first_year_fixed_cost_usd')])
    add('acquisition_grid', grid['acquisition_fraction'], ' / '.join('0%' if x == 0 else f'{x * 100:.2f}%' for x in grid['acquisition_fraction']), [source('../config/inflow_acquisition.json', 'business_cost_sensitivity.acquisition_fraction')])
    add('servicing_grid', grid['servicing_fraction'], ' / '.join('0' if x == 0 else bps(x) for x in grid['servicing_fraction']), [source('../config/inflow_acquisition.json', 'business_cost_sensitivity.servicing_fraction')])
    rate = b['acquisition_cost_fraction_of_gross_subscriptions']
    origin = [source('../config/inflow_acquisition.json', 'acquisition_cost_fraction_of_gross_subscriptions')]
    add('acquisition_bps', rate, bps(rate) + ' of each subscription', origin)
    add('acquisition_cost_bps', rate, bps(rate), origin)
    add('acquisition_cost_pct', rate, f'{rate * 100:.2f}% of gross subscriptions', origin)
    payback = rate / fee
    add('acquisition_payback', payback, ('ten' if payback == 10 else f'{payback:g}') + ' years of gross fees', origin + [source('../config/inflow_acquisition.json', 'annual_fee')], 'acquisition fraction divided by annual fee; static assets and no other costs')
    config('setup_cost', 'setup_cost_usd', lambda x: 'Setup is ' + money(x))
    fixed, inflation = b['annual_fixed_manager_cost_usd'], b['fixed_cost_inflation']
    add('fixed_cost', [fixed, inflation], f'annual fixed costs start at {money(fixed)} and rise {pct(inflation)}', [source('../config/inflow_acquisition.json', 'annual_fixed_manager_cost_usd'), source('../config/inflow_acquisition.json', 'fixed_cost_inflation')])
    matched = [r for r in tables['timing_headline.csv'] if r['return_scenario'] == main and r['timing_scenario'] != 'no_flows']
    spending = [r['cumulative_gross_subscriptions_usd'] * rate for r in matched]
    if not spending or any(abs(x - spending[0]) > 1e-6 for x in spending):
        raise ValueError('matched timing acquisition-spending interpretation no longer agrees')
    add('timing_acquisition_cost', spending[0], money(spending[0]), [source('../tables/timing_headline.csv', 'cumulative_gross_subscriptions_usd', return_scenario=main)] + origin, 'equal cumulative subscriptions times acquisition fraction')
    return claims


def validate_links(text, report_dir, run_root):
    records = []
    for target in LINK.findall(text):
        parsed = urlsplit(target)
        if parsed.scheme in {'http', 'https'}:
            records.append(dict(target=target, kind='external citation retained; not fetched by calculation'))
            continue
        if parsed.scheme or parsed.netloc or not parsed.path:
            raise ValueError(f'unsupported report link: {target}')
        path = (report_dir / unquote(parsed.path)).resolve()
        if not path.is_relative_to(run_root.resolve()) or not path.is_file():
            raise ValueError(f'report link missing or outside this run: {target}')
        records.append(dict(target=target, kind='local', artifact=str(path.relative_to(run_root.resolve()))))
    return records


def write_report(configs, tables, investor, loss, treasury, specs, resources, run_root, *, figures):
    review = validate_template(configs, resources)
    claims = prose_claims(configs, tables, investor, loss, treasury, review)
    template = resources['inflow_report.md'].decode('utf-8')
    by_id = {s['id']: s for s in specs}
    if len(by_id) != len(specs):
        raise ValueError('duplicate report table identity')
    used = {'claim': [], 'table': [], 'figure': []}

    def substitute(match):
        kind, name = match.groups()
        used[kind].append(name)
        if kind == 'claim':
            return claims[name]['display']
        if kind == 'table':
            return markdown_table(by_id[name])
        fig = review['figures'][name]
        return (f'![{fig["alt"]}]({fig["path"]})' if figures else
            f'*{fig["alt"]}: figure explicitly omitted from this run.*')

    text = TOKEN.sub(substitute, template)
    if '{{' in text or '}}' in text:
        raise ValueError('unresolved report template token')
    if used['table'] != list(by_id) or set(used['figure']) != set(review['figures']):
        raise ValueError('report must include each table and expected figure')
    if not figures:
        text = text.replace('[figure data](../figures/figure_data.csv)', 'figure data (explicitly omitted)')
        text = text.replace('This working copy rebuilds', '**Figures are explicitly excluded from this run; captions describe the reviewed full-figure baseline.**\n\nThis working copy rebuilds', 1)
    output = Path(run_root) / 'report'
    output.mkdir(exist_ok=False)
    (output / 'template.md').write_bytes(resources['inflow_report.md'])
    (output / 'template_review.json').write_bytes(resources['inflow_report_review.json'])
    payload = dict(schema_version=1, claims={k: dict(claims[k], occurrences=used['claim'].count(k)) for k in sorted(set(used['claim']))},
        manual_numeric_context=review['manual_numeric_context'],
        interpretation_scope=review['scope'], report_tables='../report_tables/report_tables.json')
    (output / 'claims.json').write_text(json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + '\n', encoding='utf-8')
    links = validate_links(text, output, Path(run_root))
    for item in payload['claims'].values():
        for origin in item['sources']:
            validate_links('[source](' + origin['artifact'] + ')', output, Path(run_root))
    (output / 'report.md').write_text(text, encoding='utf-8')
    verification = dict(report='report.md', run_manifest='../run_manifest.json',
        text_claims=len(payload['claims']), text_claim_occurrences=len(used['claim']),
        tables=len(used['table']), figures=len(used['figure']) if figures else 0,
        local_links=sum(r['kind'] == 'local' for r in links), links=links,
        scope='Assembly and source/link checks for the reviewed baseline; prose and conclusions are manually authored. Historical investment reproduction and publication are separate.')
    (output / 'assembly_checks.json').write_text(json.dumps(verification, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    return verification
