"""One configured run of the inflow numerical and presentation components."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import importlib.util
import json
import math
import os
from pathlib import Path
import platform
import uuid

from .security_io import atomic_json

from .inflow_controls import loss_controls
from .inflow_figures import plot_specs, render
from .inflow_report_tables import report_tables, write_tables
from .inflow_report import load_template, validate_template, write_report
from .inflow_results import build_results
from .inflow_returns import return_diagnostics, write_results
from .inflow_scenarios import acquisition, timing
from .inflow_treasury import sensitivity_controls, treasury_controls

CONFIG_NAMES = ['inflow_acquisition.json', 'inflow_timing.json', 'inflow_returns.json',
                'inflow_controls.json', 'inflow_presentation.json']


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    atomic_json(path, value)


def source_hashes():
    package = Path(__file__).parent
    sources = (list(package.glob('*.py')) + list((package / 'templates').glob('*.md'))
               + list((package / 'templates').glob('*.json')))
    return {f'factor_portfolio/{p.relative_to(package)}': sha256(p)
            for p in sorted(sources) if p.is_file()}


def write_csv(path, rows):
    if not rows:
        raise ValueError('cannot write an empty calculation table')
    with Path(path).open('x', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)


def validate_shared_settings(configs):
    business, timing_config, returns, controls, selection = (configs[n] for n in CONFIG_NAMES)
    if (timing_config['annual_returns'] != business['annual_returns']
        or timing_config['annual_fee'] != business['annual_fee']
        or timing_config['owner_capital_usd'] != business['initial_owner_capital_usd']):
        raise ValueError('timing and acquisition assumptions disagree')
    if returns['initial_unit_nav'] != 100 or returns['months_per_year'] != 12:
        raise ValueError('return diagnostics must use model initial NAV 100 and twelve months per year')
    tolerance = controls['comparison_tolerance_usd']
    if not math.isfinite(tolerance) or tolerance <= 0:
        raise ValueError('control comparison tolerance must be positive and finite')
    if selection['main_return_scenario'] != business['sensitivity_return_scenario']:
        raise ValueError('presentation and sensitivity return scenarios disagree')


def verify_run(output):
    """Check retained snapshot/artifact hashes; no market or model-validity claim."""
    output = Path(output).resolve()
    manifest = json.loads((output / 'run_manifest.json').read_text())
    if manifest['status'] != 'complete':
        raise ValueError('run is not complete')
    expected = {**manifest['configuration_snapshots'], **manifest['artifacts']}
    if not expected:
        raise ValueError('run contains no recorded artifacts')
    for name, digest in expected.items():
        path = (output / name).resolve()
        if not path.is_relative_to(output) or not path.is_file() or sha256(path) != digest:
            raise ValueError(f'run artifact missing or changed: {name}')
    return dict(run_id=manifest['run_id'], verified_files=len(expected), figures_included=manifest['figures_included'])


def run_study(config_dir, output, *, figures=True, report=True):
    config_dir, output = Path(config_dir), Path(output)
    if output.exists():
        raise FileExistsError('choose a new output directory; existing runs are never overwritten')
    # Load each source once. All later producers use these objects or their snapshots.
    originals = {name: (config_dir / name).read_bytes() for name in CONFIG_NAMES}
    configs = {name: json.loads(raw) for name, raw in originals.items()}
    validate_shared_settings(configs)
    resources = load_template() if report else None
    if report:
        validate_template(configs, resources)
    if figures and importlib.util.find_spec('matplotlib') is None:
        raise RuntimeError('install requirements-plots-lock.txt or explicitly use --no-figures')
    output.mkdir(parents=True, exist_ok=False)
    (output / 'config').mkdir()
    for name, raw in originals.items():
        (output / 'config' / name).write_bytes(raw)
    code = source_hashes()
    manifest = dict(schema_version=1, run_id=str(uuid.uuid4()), status='running',
        started_at_utc=datetime.now(timezone.utc).isoformat(), figures_included=figures, full_report_included=report,
        scope=('Inflow numerical components, optional figures and twelve table fragments; '
               + ('includes reviewed-baseline report assembly. ' if report else 'complete report explicitly excluded. ')
               + 'Historical investment reconstruction remains separate.'),
        configuration_snapshots={f'config/{name}': hashlib.sha256(raw).hexdigest() for name, raw in originals.items()},
        code=code, code_snapshot_sha256=hashlib.sha256(json.dumps(code, sort_keys=True).encode()).hexdigest(),
        environment=dict(python=platform.python_version(), system=platform.system(), machine=platform.machine(),
            distributions={d.metadata['Name']: d.version for d in sorted(importlib.metadata.distributions(), key=lambda d: d.metadata['Name'].lower())}),
        stages=[], artifacts={})
    write_json(output / 'run_manifest.json', manifest)

    def stage(name, inputs, paths):
        manifest['stages'].append(dict(id=name, inputs=inputs, outputs=paths))
        write_json(output / 'run_manifest.json', manifest)

    business, timing_config, return_settings, control_settings, selection = (configs[n] for n in CONFIG_NAMES)
    try:
        acquisition_rows = [row for rid in business['annual_returns']
            for sid in business['annual_new_client_equivalents'] for row in acquisition(business, rid, sid)]
        timing_rows = [row for rid in business['annual_returns']
            for sid in timing_config['monthly_schedules_usd'] for row in timing(business, timing_config, rid, sid)]
        tables = build_results(business, timing_config, acquisition_rows, timing_rows)
        (output / 'tables').mkdir()
        for name, rows in tables.items():
            write_csv(output / 'tables' / name, rows)
        stage('tables', ['config/inflow_acquisition.json', 'config/inflow_timing.json'], [f'tables/{name}' for name in tables])

        investor = return_diagnostics(timing_rows, return_settings)
        write_results(investor, output / 'returns')
        stage('returns', ['tables/timing_monthly.csv', 'config/inflow_returns.json'],
            ['returns/return_diagnostics.json', 'returns/external_investor_returns.csv'])

        loss = loss_controls(business, timing_config, {'acquisition': acquisition_rows, 'timing': timing_rows}, control_settings)
        treasury = treasury_controls(business, control_settings, loss['summary']['break_even_fees'])
        funding = sensitivity_controls(business, control_settings, output / 'tables')
        (output / 'controls').mkdir()
        control_payloads = {'loss_controls.json': loss, 'treasury_controls.json': treasury,
                            'funding_sensitivity.json': funding, 'control_settings.json': control_settings}
        for name, payload in control_payloads.items():
            write_json(output / 'controls' / name, payload)
        stage('controls', ['config/inflow_acquisition.json', 'config/inflow_timing.json', 'config/inflow_controls.json',
            'tables/acquisition_monthly.csv', 'tables/timing_monthly.csv',
            'tables/fee_ticket_receipt_sensitivity.csv', 'tables/business_cost_sensitivity.csv'],
            [f'controls/{name}' for name in control_payloads])

        if figures:
            specs = plot_specs(tables, business, timing_config)
            previous_cache = os.environ.get('MPLCONFIGDIR')
            os.environ['MPLCONFIGDIR'] = str((output / '_cache' / 'matplotlib').resolve())
            try:
                render(specs, output / 'figures')
            finally:
                if previous_cache is None:
                    os.environ.pop('MPLCONFIGDIR', None)
                else:
                    os.environ['MPLCONFIGDIR'] = previous_cache
            stage('figures', ['config/inflow_acquisition.json', 'config/inflow_timing.json',
                'tables/acquisition_monthly.csv', 'tables/timing_monthly.csv', 'tables/fee_ticket_receipt_sensitivity.csv'],
                [str(p.relative_to(output)) for p in sorted((output / 'figures').rglob('*')) if p.is_file()])

        report_specs = report_tables(business, timing_config, selection, tables, investor, loss, treasury, funding)
        report_files = {name: output / 'config' / name for name in ['inflow_acquisition.json', 'inflow_timing.json', 'inflow_presentation.json']}
        report_files.update({name: output / 'tables' / name for name in ['acquisition_headline.csv', 'timing_headline.csv', 'fee_ticket_receipt_sensitivity.csv']})
        report_files.update({'return_diagnostics.json': output / 'returns' / 'return_diagnostics.json',
            'loss_controls.json': output / 'controls' / 'loss_controls.json',
            'treasury_controls.json': output / 'controls' / 'treasury_controls.json',
            'funding_sensitivity.json': output / 'controls' / 'funding_sensitivity.json'})
        write_tables(report_specs, output / 'report_tables', report_files, run_manifest='../run_manifest.json')
        stage('report_tables', [str(p.relative_to(output)) for p in report_files.values()],
            [str(p.relative_to(output)) for p in sorted((output / 'report_tables').iterdir()) if p.is_file()])

        if report:
            assembly = write_report(configs, tables, investor, loss, treasury, report_specs,
                resources, output, figures=figures)
            stage('report', ['report/template.md', 'report/template_review.json']
                + [str(p.relative_to(output)) for p in report_files.values()]
                + ['tables/timing_monthly.csv', 'tables/acquisition_monthly.csv', 'tables/business_cost_sensitivity.csv']
                + (['figures/plot_definitions.json', 'figures/figure_data.csv'] if figures else []),
                [str(p.relative_to(output)) for p in sorted((output / 'report').iterdir()) if p.is_file()])

        (output / 'README.md').write_text(
            '# Capital-inflow calculation run\n\n'
            'This run uses one captured set of assumptions. All numerical artifacts were generated afresh.\n\n'
            + ('- [Complete inflow discussion report](report/report.md)\n' if report else '- Complete report explicitly excluded; interpretations need editorial review.\n')
            + '- [Displayed report tables](report_tables/report_tables.md)\n'
            '- [Configuration snapshots](config/)\n'
            '- [Calculation tables](tables/)\n'
            '- [Investor returns](returns/return_diagnostics.json)\n'
            '- [Loss-placement and treasury controls](controls/)\n'
            + ('- [Figures and plot data](figures/)\n' if figures else '- Figures explicitly excluded from this run.\n')
            + '- [Run manifest](run_manifest.json)\n\n'
            'This is a hypothetical inflow experiment. Report interpretations are manually authored for reviewed assumptions; historical investment reconstruction remains outside this run.\n', encoding='utf-8')
        if source_hashes() != code:
            raise RuntimeError('package source changed during calculation; repeat in a stable working copy')
        manifest['artifacts'] = {str(p.relative_to(output)): sha256(p) for p in sorted(output.rglob('*'))
            if p.is_file() and p.name != 'run_manifest.json' and p.relative_to(output).parts[0] not in {'config', '_cache'}}
        manifest['counts'] = dict(csv_tables=len(tables), table_rows=sum(len(rows) for rows in tables.values()),
            acquisition_months=len(acquisition_rows), timing_months=len(timing_rows),
            investor_return_cases=len(investor['external_investor_returns']),
            loss_controls=loss['summary']['loss_sensitivity_cases'], report_tables=len(report_specs), figures=8 if figures else 0,
            full_reports=1 if manifest['full_report_included'] else 0,
            text_claims=assembly['text_claims'] if manifest['full_report_included'] else 0)
        manifest['status'] = 'complete'
        manifest['finished_at_utc'] = datetime.now(timezone.utc).isoformat()
        write_json(output / 'run_manifest.json', manifest)
        verify_run(output)
    except Exception as error:
        manifest['status'] = 'failed'
        manifest['failure'] = dict(type=type(error).__name__, message=str(error))
        manifest['finished_at_utc'] = datetime.now(timezone.utc).isoformat()
        write_json(output / 'run_manifest.json', manifest)
        raise
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config-dir', type=Path, default=Path('config'))
    parser.add_argument('--output', type=Path)
    parser.add_argument('--no-figures', action='store_true')
    parser.add_argument('--no-report', action='store_true', help='numerical experiments without reviewed report prose')
    parser.add_argument('--verify-run', type=Path)
    args = parser.parse_args()
    if args.verify_run:
        if args.output or args.no_figures or args.no_report:
            parser.error('--verify-run cannot be combined with output or scope-exclusion flags')
        print(json.dumps(verify_run(args.verify_run), indent=2))
    else:
        if args.output is None:
            parser.error('--output is required for a new calculation run')
        result = run_study(args.config_dir, args.output, figures=not args.no_figures, report=not args.no_report)
        print(json.dumps(dict(status=result['status'], run_id=result['run_id'], counts=result['counts']), indent=2))


if __name__ == '__main__':
    main()
