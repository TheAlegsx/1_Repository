"""Reconstruct the research and bind unchanged reports after exact reference checks.

Reference files contain hashes, not market observations or saved result tables.
Each invocation requires a new output directory and preserves source files.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import sys

from .inflow_workflow import sha256, verify_run
from .research_reader_reports import assemble, load_evidence, write_json
from .report_contract import contained, run_contract
from .backtest_report import run_backtest_report
from .coordinated_inflow_report import run_coordinated
from .security_io import require_runtime, require_installation, verify_original_inventory, read_bounded_bytes


ROOT_NAMES = {'raw_root', 'annual_raw_root', 'factor_annual_raw_root',
              'dimensional_annual_raw_root', 'collateral_raw_root', 'custody_raw_root'}


def evidence_fingerprint(source):
    tables, claims = load_evidence(Path(source))
    payload = json.dumps(dict(tables=tables, claims=claims), sort_keys=True,
                         separators=(',', ':'), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def verify_reference_run(directory, reference):
    verify_run(directory)
    manifest = json.loads((Path(directory) / 'run_manifest.json').read_text())
    if manifest['configuration_snapshots'] != reference['configuration_snapshots']:
        raise ValueError('reference configuration snapshots differ')
    actual = {path: digest for path, digest in manifest['artifacts'].items() if path.endswith('.csv')}
    if actual != reference['csv_artifacts']:
        raise ValueError('reconstructed CSV hashes or inventory differ from the reviewed reference')
    return len(actual)


def check_complete_source(source, reference):
    for directory in [Path(source), Path(source) / 'backtest', Path(source) / 'inflow']:
        verify_run(directory)
    if evidence_fingerprint(source) != reference['complete_evidence_fingerprint']:
        raise ValueError('complete table/claim evidence differs; reader binding cannot be renewed')
    for relative, expected in reference['complete_payloads'].items():
        if sha256(contained(source, relative)) != expected:
            raise ValueError('reviewed manuscript/figure payload differs: ' + relative)


def check_robustness(project, source):
    verify_run(source)
    reference = json.loads((project / 'config/paired_robustness_reference_2026-10-09.json').read_text())
    manifest = json.loads((Path(source) / 'run_manifest.json').read_text())
    if (reference['protocol_sha256'] != sha256(project / 'config/paired_robustness_protocol_2026-10-09.json')
            or manifest['configuration_snapshots'] != reference['configuration_snapshots']
            or manifest['artifacts'] != reference['artifacts_sha256']):
        raise ValueError('frozen paired study results differ from the reviewed reference')
    return len(manifest['artifacts'])


def bind_readers(project, source, destination, reference, binding_directory, robustness_source=None):
    # Never infer equivalence from a run ID or silently refresh an unchecked hash.
    check_complete_source(source, reference)
    settings = json.loads((project / 'config/research_reader_selection_2026-10-06.json').read_text())
    review = json.loads((project / 'src/factor_portfolio/templates/research_reader_review_2026-10-06.json').read_text())
    if (sha256(project / 'config/research_reader_selection_2026-10-06.json') != reference['reader_selection_sha256']
            or sha256(project / 'src/factor_portfolio/templates/research_reader_review_2026-10-06.json') != reference['reader_review_sha256']):
        raise ValueError('published selection/review differs from the reviewed reference')
    if review['ai_record_sha256'] != sha256(project / 'docs/AI_USE_RECORD_2026-10-06.md'):
        raise ValueError('AI evidence differs from the reviewed publication record')
    settings = copy.deepcopy(settings)
    settings['source_run_id'] = json.loads((source / 'run_manifest.json').read_text())['run_id']
    binding_directory.mkdir()
    selection_path = binding_directory / 'reader_selection.json'
    write_json(selection_path, settings)
    renewed = copy.deepcopy(review)
    renewed['source_run_id'] = settings['source_run_id']
    renewed['selection_sha256'] = sha256(selection_path)
    renewed['reconstruction_binding'] = dict(
        scope='Run identity renewed only after exact reviewed configuration/CSV and complete table/claim/text/figure checks.',
        complete_evidence_fingerprint=reference['complete_evidence_fingerprint'])
    review_path = binding_directory / 'reader_review.json'
    write_json(review_path, renewed)
    result = assemble(project, source, destination, selection_path, review_path, robustness_source)
    for relative, expected in reference['reader_payloads'].items():
        if sha256(contained(destination, relative)) != expected:
            raise ValueError('regenerated reader manuscript/figure differs: ' + relative)
    return result


def run(project, input_roots, output, font_directory, include_pdf=True):
    project = Path(project).resolve()
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError('choose a new reconstruction output directory')
    if not output.is_relative_to(project) or output == project:
        raise ValueError('reconstruction output must be a new directory inside the project')
    require_runtime()
    require_installation(project)
    from cryptography.hazmat.bindings.openssl.binding import Binding
    crypto = Binding()
    crypto_version = crypto.ffi.string(crypto.lib.OpenSSL_version(0)).decode('ascii')
    version = re.match(r'^OpenSSL (\d+)\.(\d+)\.(\d+)\b', crypto_version)
    if version is None or tuple(map(int, version.groups())) != (4, 0, 3):
        raise RuntimeError('The reviewed cryptography wheel must bundle patched OpenSSL 4.0.3')
    roots = json.loads(read_bounded_bytes(input_roots, 1024 * 1024))
    if set(roots) != ROOT_NAMES or any(not Path(value).is_dir() for value in roots.values()):
        raise ValueError('supply all six existing local original-data directories')
    roots = {name: str(Path(value).resolve()) for name, value in roots.items()}
    verify_original_inventory(project, roots)
    recipe_path = project / 'config/reproduction_recipe_2026-10-06.json'
    recipe = json.loads(recipe_path.read_text())
    reference_path = project / 'config/reproduction_reference_2026-10-06.json'
    reference = json.loads(reference_path.read_text())
    if sha256(recipe_path) != reference['recipe_sha256']:
        raise ValueError('calculation recipe requires renewed review')
    jobs = recipe['jobs']
    if len(jobs) != 14 or {job['id'] for job in jobs} != set(reference['jobs']):
        raise ValueError('all fourteen unique reviewed evidence jobs are required')
    targets = {job['output']: output / job['id'] for job in jobs}
    output.mkdir(parents=True)
    (output / 'logs').mkdir()
    env = os.environ.copy()
    env.pop('PYTHONHOME', None)
    env.update(PYTHONPATH=str(project / 'src'), PYTHONNOUSERSITE='1',
               PYTHONDONTWRITEBYTECODE='1', MPLCONFIGDIR=str(output / '_cache/matplotlib'))
    completed, csv_count = [], 0
    for job in jobs:
        if any(dependency not in completed for dependency in job['depends_on']):
            raise ValueError('recipe dependency order differs')
        arguments = [str(targets[value].relative_to(project)) if value in targets
                     else value.format(**roots) for value in job['arguments']]
        print('Calculating ' + job['id'], flush=True)
        with (output / 'logs' / (job['id'] + '.log')).open('xb') as log:
            subprocess.run([sys.executable, '-m', job['module'], *arguments],
                           cwd=project, env=env, stdout=log, stderr=subprocess.STDOUT,
                           timeout=600, check=True)
        csv_count += verify_reference_run(targets[job['output']], reference['jobs'][job['id']])
        completed.append(job['id'])
    contract = json.loads((project / 'config/coordinated_reports_2026-10-06.json').read_text())
    contract['runs'] = {name: str(targets[relative].relative_to(project))
                        for name, relative in contract['runs'].items()}
    (output / 'configuration').mkdir()
    contract_path = output / 'configuration/coordinated_reports.json'
    write_json(contract_path, contract)
    from .paired_robustness import run as run_robustness
    print('Calculating frozen paired robustness study', flush=True)
    run_robustness(project, output / 'core', output / 'robustness')
    robustness_count = check_robustness(project, output / 'robustness')
    print('Assembling verified reports', flush=True)
    run_contract(project, contract_path, output / 'report_contract')
    run_backtest_report(project, output / 'report_contract', output / 'backtest_report')
    run_coordinated(project, output / 'report_contract', output / 'backtest_report', output / 'complete_reports')
    reader = bind_readers(project, output / 'complete_reports', output / 'readers',
                          reference, output / 'reader_binding', output / 'robustness')
    if include_pdf:
        from .research_reader_pdf import render_readers
        render_readers(output / 'readers', output / 'pdf', font_directory)
    result = dict(status='complete', evidence_jobs=completed, exact_reference_csv_files=csv_count,
                  robustness_paired_results=56, robustness_bootstrap_draws=10000,
                  exact_robustness_artifacts=robustness_count,
                  reference_sha256=sha256(reference_path), reader_run_id=reader['run_id'],
                  pdf_generated=include_pdf, pdf_visual_review='pending' if include_pdf else 'not generated',
                  source_files_modified=False, scope='Matching-original-data reconstruction against reviewed references; no forecast or expert approval.')
    write_json(output / 'reconstruction_checks.json', result)
    print(json.dumps(result, indent=2), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root', type=Path, default=Path.cwd())
    parser.add_argument('--input-roots', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--font-directory', type=Path, default=Path('/System/Library/Fonts/Supplemental'))
    parser.add_argument('--no-pdf', action='store_true', help='generate complete evidence and Markdown readers without PDF fonts')
    args = parser.parse_args()
    run(args.project_root, args.input_roots, args.output, args.font_directory, not args.no_pdf)


if __name__ == '__main__':
    main()
