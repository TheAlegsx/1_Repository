"""Reader charts from sealed report evidence; no portfolio calculations."""
from pathlib import Path
import hashlib
import json

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd

PRIMARY = '#1e4d78'
COMPARATOR = '#555555'


def render(kind, source, output):
    """Render a deterministic presentation and retain its plotted values."""
    source, output = Path(source), Path(output)
    plt.rcParams.update({'font.family': 'DejaVu Serif', 'font.size': 10,
                         'axes.spines.top': False, 'axes.spines.right': False})
    records = []
    if kind.startswith('backtest_') or kind == 'inflow_nav':
        frame = pd.read_csv(source)
        figure = 'historical_nav' if kind == 'inflow_nav' else kind.removeprefix('backtest_')
        data = frame[frame.figure.eq(figure)].pivot(index='date', columns='series', values='value')
        data.index = pd.to_datetime(data.index)
        if kind == 'inflow_nav':
            primary, comparator = 'coupled steady', 'overlay steady'
            labels = ['Fund with flows', 'Return-path comparison']
            ylabel = 'Unit NAV'
        else:
            primary, comparator = 'full_factor_absolute_decoupled_1.25', 'full_core_1.25'
            labels = ['Factor portfolio', 'MSCI World Core']
            ylabel = 'Drawdown (%)' if figure == 'drawdown' else 'Investor equity (USD million)'
        pair = data[[primary, comparator]].copy()
        if pair.isna().any().any():
            raise ValueError('reader figure requires matched complete observations')
        has_difference = figure != 'drawdown'
        if has_difference:
            fig, (ax, lower) = plt.subplots(2, 1, figsize=(8.2, 5.0), sharex=True,
                                            gridspec_kw={'height_ratios': [2, 1]})
        else:
            fig, ax = plt.subplots(figsize=(8.2, 3.4))
        for column, label, color in zip(pair, labels, [PRIMARY, COMPARATOR]):
            # Sealed drawdown figure values are already percentages.
            ax.plot(pair.index, pair[column], label=label, color=color, linewidth=1.4)
            records += [{'date': str(date.date()), 'series': label, 'value': float(value)}
                        for date, value in pair[column].items()]
        ax.set_ylabel(ylabel)
        ax.legend(frameon=False, loc='upper left')
        ax.grid(axis='y', color='#e4e4e4', linewidth=.5)
        if has_difference:
            relative = (pair[primary] / pair[comparator] - 1) * 100
            lower.plot(relative.index, relative, color=PRIMARY, linewidth=1.3)
            lower.axhline(0, color=COMPARATOR, linewidth=.7)
            lower.set_ylabel('Relative wealth (%)')
            lower.grid(axis='y', color='#e4e4e4', linewidth=.5)
            records += [{'date': str(date.date()), 'series': 'relative wealth percent', 'value': float(value)}
                        for date, value in relative.items()]
        fig.tight_layout(pad=1.0)
    elif kind == 'manager_cash':
        tables = json.loads(source.read_text())
        row = tables['historical_manager']['rows'][0]
        values = [float(row[i]['value']) / 1000 for i in [2, 3]]
        fig, ax = plt.subplots(figsize=(8.2, 2.9))
        bars = ax.barh(['External fee receipts', 'Business costs'], values,
                       color=[PRIMARY, COMPARATOR], height=.5)
        ax.invert_yaxis(); ax.set_xlabel('USD thousand over ten years')
        ax.set_xlim(0, max(values) * 1.17)
        for bar, value in zip(bars, values):
            ax.text(value + 5, bar.get_y() + bar.get_height()/2, f'{value:,.0f}', va='center')
        ax.spines['left'].set_visible(False); ax.tick_params(axis='y', length=0)
        fig.tight_layout(pad=1.0)
        records = [{'series': label, 'value_usd': float(row[i]['value'])}
                   for label, i in [('external receipts', 2), ('business costs', 3)]]
    elif kind == 'accounts':
        fig, ax = plt.subplots(figsize=(8.2, 3.35)); ax.set_xlim(0, 10); ax.set_ylim(0, 4); ax.axis('off')
        boxes = [(1.5, 3.2, 'Founders\nFund units'), (1.5, .8, 'External clients\nFund units'),
                 (5, 2, 'Same investment fund\nAssets minus debt = equity'),
                 (8.5, 2, 'Separate manager cash\nFee receipts less costs')]
        for x, y, label in boxes:
            ax.text(x, y, label, ha='center', va='center', fontsize=10,
                    bbox={'boxstyle': 'round,pad=.65', 'facecolor': '#f3f5f7', 'edgecolor': '#999999'})
        for start, end, text, tx, ty in [((2.7, 3.1), (3.5, 2.4), 'Investment / units', 3.45, 3.35),
                ((2.7, .9), (3.5, 1.6), 'Subscriptions / redemptions', 3.35, .4),
                ((6.5, 2), (7.15, 2), 'Fund fees', 6.85, 2.75)]:
            ax.annotate('', xy=end, xytext=start, arrowprops={'arrowstyle': '<->' if tx < 4 else '->', 'color': PRIMARY})
            ax.text(tx, ty, text, ha='center', fontsize=9)
        ax.annotate('', xy=(8.5, .7), xytext=(8.5, 1.4), arrowprops={'arrowstyle': '->', 'color': COMPARATOR})
        ax.text(8.5, .35, 'Operating costs', ha='center', fontsize=9)
        fig.tight_layout(pad=.5)
        records = [{'kind': 'accounting schematic', 'basis': 'Report accounting definitions; no numerical simulation'}]
    else:
        raise ValueError('unknown reader figure transformation')
    fig.savefig(output, dpi=170, metadata={'Software': 'MSCI World Factor Strategy reader charts'})
    plt.close(fig)
    values = output.with_suffix('.json')
    values.write_text(json.dumps({'render': kind, 'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                                  'records': records}, indent=2, allow_nan=False) + '\n')
    return values
