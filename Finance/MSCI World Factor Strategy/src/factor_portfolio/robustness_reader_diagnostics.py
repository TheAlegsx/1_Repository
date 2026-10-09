"""Reader cells derived from the sealed, frozen paired study."""
from pathlib import Path
import hashlib
import json
import pandas as pd
from .inflow_workflow import verify_run


def summaries(source):
    source = Path(source)
    verify_run(source)
    names = ['endpoint_summary.csv', 'paired_matrix.csv', 'bootstrap_summary.csv',
             'measurement_definitions.json', 'study_checks.json', 'config/PROTOCOL.json']
    checks = json.loads((source / 'study_checks.json').read_text())
    if (checks['status'] != 'passed' or checks['paired_endpoint_results'] != 56
            or checks['bootstrap_draws'] != 10000):
        raise ValueError('complete frozen paired study required')
    endpoints = pd.read_csv(source / names[0], float_precision='round_trip')
    pairs = pd.read_csv(source / names[1], float_precision='round_trip')
    boot = pd.read_csv(source / names[2], float_precision='round_trip')
    definitions = json.loads((source / names[3]).read_text())

    def cell(value, display, artifact, row, field):
        return dict(value=value, display=display, origins=[dict(
            artifact='robustness/' + artifact, row=row, field=field)])

    rows=[]
    for i, row in endpoints.iterrows():
        rows.append([cell(row.end, row.end, names[0], int(i), 'end')] +
            [cell(float(row[k]), f'{row[k]:+.2f}', names[0], int(i), k)
             for k in ['baseline_gap_pp', 'median_gap_pp', 'minimum_gap_pp', 'maximum_gap_pp']] +
            [cell(int(row.positive_pairs), f'{int(row.positive_pairs)}/14', names[0], int(i), 'positive_pairs')])
    intervals=[]
    for i, row in boot.iterrows():
        intervals.append([cell(int(row.block_length), str(int(row.block_length)), names[2], int(i), 'block_length'),
            cell(int(row.replications), f'{int(row.replications):,}', names[2], int(i), 'replications')] +
            [cell(float(row[k]), f'{row[k]:+.2f}', names[2], int(i), k)
             for k in ['observed_gap_pp', 'ci_low_pp', 'ci_high_pp']])
    fee_rows=[]
    # Identify by fee and dimension, rather than rely on friendly case labels.
    selected = pairs[(pairs.end == '2026-08-28') & pairs.dimension.isin(['baseline', 'fund_fee_bps'])].sort_values('fund_fee_bps')
    if len(selected)!=3:
        raise ValueError('all three matched fee cases required')
    for i,row in selected.iterrows():
        fee_rows.append([cell(float(row.fund_fee_bps), f'{row.fund_fee_bps:g} bp', names[1], int(i), 'fund_fee_bps')] +
            [cell(float(row[k]), f'{row[k]*100:.2f}%', names[1], int(i), k) for k in ['factor_cagr', 'core_cagr']] +
            [cell(float(row.cagr_gap_pp), f'{row.cagr_gap_pp:+.2f}', names[1], int(i), 'cagr_gap_pp'),
             cell(int(row.factor_post_entry_events), str(int(row.factor_post_entry_events)), names[1], int(i), 'factor_post_entry_events'),
             cell(int(row.core_post_entry_events), str(int(row.core_post_entry_events)), names[1], int(i), 'core_post_entry_events')])
    return dict(
        paired_sensitivity=dict(kind='table', headers=['Endpoint', 'Baseline', 'Median', 'Minimum', 'Maximum', 'Positive'], rows=rows),
        bootstrap_intervals=dict(kind='table', headers=['Mean block', 'Draws', 'Observed gap (pp)', '95% low (pp)', '95% high (pp)'], rows=intervals),
        paired_fee_sensitivity=dict(kind='table', headers=['Fund fee', 'Factor CAGR', 'Core CAGR', 'Gap (pp)', 'Factor trades', 'Core trades'], rows=fee_rows),
        tracking_error=dict(kind='claim', **cell(definitions['tracking_error_annual'], f"{definitions['tracking_error_annual']*100:.2f}%", names[3], None, 'tracking_error_annual')),
        information_ratio=dict(kind='claim', **cell(definitions['information_ratio'], f"{definitions['information_ratio']:.3f}", names[3], None, 'information_ratio')),
        source_files_sha256={name:hashlib.sha256((source/name).read_bytes()).hexdigest() for name in names})
