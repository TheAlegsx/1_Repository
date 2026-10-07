"""Render report figures from calculated CSV tables, with explicit plot data."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

ACQUISITION_LABELS = {
    'no_flows': 'No external flows', 'limited': 'Limited demand',
    'steady': 'Steady acquisition', 'strong': 'Strong acquisition',
    'sales_stop': 'Sales stop / runoff',
}
TIMING_LABELS = {
    'no_flows': 'No external flows', 'constant_monthly': 'Constant monthly',
    'rising_monthly': 'Rising monthly', 'even_steps': 'Evenly spaced steps',
    'early_steps': 'Early steps', 'late_steps': 'Late steps',
}
COLORS = ['#666666', '#254A78', '#267B82', '#805080', '#95562B', '#748E38']


def read_table(path):
    with Path(path).open() as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        for key, value in row.items():
            try:
                row[key] = float(value)
            except ValueError:
                pass
    return rows


def plot_specs(tables, business, timing):
    """Return plot definitions and exact values; no renderer or private reads."""
    specs = []
    paths = business['annual_returns']
    growth = paths['growth']
    growth_title = (f'{growth[0]:.0%} path' if len(set(growth)) == 1
                    else 'configured growth path')
    years = len(growth)
    capital = business['initial_owner_capital_usd'] / 1e6

    def lines(name, title, source, rid, scenario_key, labels, field,
              scale, ylabel, start, *, step=False, exclude=()):
        series = []
        for index, (sid, label) in enumerate(labels.items()):
            if sid in exclude:
                continue
            rows = [r for r in tables[source] if r['return_scenario'] == rid and r[scenario_key] == sid]
            if [r['month'] for r in rows] != list(range(1, years * 12 + 1)):
                raise ValueError(f'incomplete or unordered plot series: {name}/{sid}')
            series.append(dict(scenario=sid, label=label, color=COLORS[index],
                x=[0] + [r['month'] / 12 for r in rows],
                y=[start] + [r[field] / scale for r in rows],
                dashed=sid == 'no_flows' and source == 'timing_monthly.csv'))
        specs.append(dict(name=name, title=title, kind='step' if step else 'line',
            source=source, field=field, return_scenario=rid, scale=scale,
            ylabel=ylabel, xlabel='Scenario year', series=series, years=years,
            zero_floor='cash' not in field))

    lines('acquisition/01_aum', f'External acquisition under the {growth_title}',
        'acquisition_monthly.csv', 'growth', 'flow_scenario', ACQUISITION_LABELS,
        'closing_aum_usd', 1e6, 'Total fund assets (USD million)', capital)
    lines('acquisition/02_aum', 'Later loss with reduced subscriptions and higher redemptions',
        'acquisition_monthly.csv', 'late_loss', 'flow_scenario', ACQUISITION_LABELS,
        'closing_aum_usd', 1e6, 'Total fund assets (USD million)', capital)
    lines('acquisition/03_manager_cash', 'Manager cash after illustrative startup and operating costs',
        'acquisition_monthly.csv', 'growth', 'flow_scenario', ACQUISITION_LABELS,
        'cumulative_manager_cash_usd', 1000, 'Cumulative cash (USD thousand)', 0,
        exclude=('sales_stop',))
    fees = [r for r in tables['fee_ticket_receipt_sensitivity.csv']
            if r['ticket_usd'] == business['ticket_usd'] and r['manager_receipt_fraction'] == 1]
    if len(fees) != len(business['fee_sensitivity']):
        raise ValueError('fee figure requires baseline ticket and full receipt in the sensitivity grid')
    specs.append(dict(name='acquisition/04_fee_sensitivity',
        title=f'Steady acquisition: fee sensitivity, {growth_title}', kind='bar',
        source='fee_ticket_receipt_sensitivity.csv', field='manager_net_year10_usd',
        return_scenario='growth', scale=1000,
        ylabel='Year 10 manager result (USD thousand)',
        xlabel='Annual investor fee (not an approved change)',
        categories=[f"{r['annual_fee'] * 100:.2f}%" for r in fees],
        series=[dict(scenario='steady', label='Steady acquisition', color=COLORS[1],
                     x=[r['annual_fee'] for r in fees], y=[r['manager_net_year10_usd'] / 1000 for r in fees])],
        years=years, zero_floor=False))
    total = timing['total_gross_subscriptions_per_timing_case_usd'] / 1e6
    lines('timing/01_subscription_timing', f'Same USD {total:g}m gross subscriptions, different timing',
        'timing_monthly.csv', 'growth', 'timing_scenario', TIMING_LABELS,
        'cumulative_gross_subscriptions_usd', 1e6, 'Gross subscriptions (USD million)', 0,
        step=True, exclude=('no_flows',))
    lines('timing/02_assets_growth', f'Assets reflect returns, timing and redemptions: {growth_title}',
        'timing_monthly.csv', 'growth', 'timing_scenario', TIMING_LABELS,
        'closing_net_aum_usd', 1e6, 'Total fund assets (USD million)', capital)
    lines('timing/03_assets_loss', 'Matched subscription schedules with the year 4 loss',
        'timing_monthly.csv', 'late_loss', 'timing_scenario', TIMING_LABELS,
        'closing_net_aum_usd', 1e6, 'Total fund assets (USD million)', capital)
    lines('timing/04_manager_cash', 'Timing of external fees and illustrative business costs',
        'timing_monthly.csv', 'growth', 'timing_scenario', TIMING_LABELS,
        'cumulative_manager_cash_usd', 1000, 'Cumulative manager cash (USD thousand)', 0)
    return specs


def plot_data(specs):
    return [dict(figure=spec['name'], scenario=s['scenario'],
                 return_scenario=spec['return_scenario'], x=x, value=y,
                 unit=spec['ylabel'], source_table=spec['source'], source_field=spec['field'])
            for spec in specs for s in spec['series'] for x, y in zip(s['x'], s['y'])]


def render(specs, output):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.ticker import MaxNLocator

    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    with plt.rc_context({'font.family': 'DejaVu Sans', 'font.size': 11,
                         'axes.spines.top': False, 'axes.spines.right': False}):
        for spec in specs:
            fig, ax = plt.subplots(figsize=(9, 5.5), layout='constrained')
            for s in spec['series']:
                if spec['kind'] == 'bar':
                    ax.bar(spec['categories'], s['y'], color=s['color'])
                elif spec['kind'] == 'step':
                    ax.step(s['x'], s['y'], where='post', label=s['label'], color=s['color'])
                else:
                    ax.plot(s['x'], s['y'], label=s['label'], color=s['color'],
                            linestyle='--' if s['dashed'] else '-')
            ax.set(title=spec['title'], xlabel=spec['xlabel'], ylabel=spec['ylabel'])
            ax.grid(axis='y', alpha=.2)
            ax.set_axisbelow(True)
            if spec['kind'] != 'bar':
                ax.set_xlim(0, spec['years'])
                ax.xaxis.set_major_locator(MaxNLocator(integer=True))
                ax.legend(frameon=False, fontsize=9, loc='best')
            if spec['zero_floor']:
                ax.set_ylim(bottom=0)
            else:
                ax.axhline(0, color='gray', linewidth=.8)
            target = output / spec['name']
            target.parent.mkdir(parents=True, exist_ok=True)
            fig.savefig(target.with_suffix('.png'), dpi=180)
            fig.savefig(target.with_suffix('.svg'), metadata={'Date': None})
            plt.close(fig)
    rows = plot_data(specs)
    with (output / 'figure_data.csv').open('x', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)
    (output / 'plot_definitions.json').write_text(json.dumps(specs, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tables', type=Path, required=True)
    parser.add_argument('--acquisition-config', type=Path, required=True)
    parser.add_argument('--timing-config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    tables = {name: read_table(args.tables / name) for name in
              ['acquisition_monthly.csv', 'timing_monthly.csv', 'fee_ticket_receipt_sensitivity.csv']}
    specs = plot_specs(tables, json.loads(args.acquisition_config.read_text()),
                       json.loads(args.timing_config.read_text()))
    render(specs, args.output)
    print(f'Created {len(specs)} figures as PNG and SVG, plus exact plot data.')


if __name__ == '__main__':
    main()
