"""Assemble concise reader reports from a verified complete research package.

This is an editorial postprocessor. Financial engines and complete-report
contracts are unchanged. A reviewed disposition map accounts for every original
table family, prose claim and figure, including material retained outside PDFs.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import uuid

from .inflow_workflow import verify_run, sha256
from .inflow_report_tables import format_value

TOKEN = re.compile(r'\{\{(table|claim|historical|figure|sources|disclosure):(\w+)\}\}')


def copy_bytes(source, destination):
    # Copy contents only; no source filesystem metadata or extended attributes.
    Path(destination).write_bytes(Path(source).read_bytes())


def write_json(path, value):
    # All destinations are new and the completed manifest is written last.
    # Avoid filesystem metadata replacement operations on protected macOS files.
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write('\n')


def inventory(directory):
    return {str(p.relative_to(directory)): sha256(p)
            for p in sorted(directory.rglob('*')) if p.is_file()}


def load_evidence(source):
    def read(path):
        return json.loads((source / path).read_text())
    backtest = read('backtest/report/tables.json')
    hypothetical = read('inflow/report_tables/report_tables.json')
    inflow = {}
    for spec in hypothetical:
        inflow[spec['id']] = dict(
            headers=[c['heading'] for c in spec['columns']],
            rows=[[dict(value=value, display=format_value(value, column['format']),
                        source_row=i, source_column=j)
                   for j, (value, column) in enumerate(zip(row, spec['columns']))]
                  for i, row in enumerate(spec['rows'])],
            sources=spec['sources'], evidence=spec['evidence'])
    inflow.update(read('inflow/report/historical_tables.json'))
    return dict(backtest=backtest, inflow=inflow), {
        'backtest': {'claim': read('backtest/report/claims.json')['claims']},
        'inflow': {'claim': read('inflow/report/claims.json')['claims'],
                   'historical': read('inflow/report/historical_claims.json')['claims']}}


def select_table(spec, selection):
    rows = selection['rows'] if selection['rows'] is not None else list(range(len(spec['rows'])))
    columns = (selection['columns'] if selection['columns'] is not None
               else list(range(len(spec['headers']))))
    if len(rows) != len(set(rows)) or len(columns) != len(set(columns)):
        raise ValueError('duplicate table selections')
    result = copy.deepcopy(spec)
    result['headers'] = [spec['headers'][j] for j in columns]
    result['rows'] = [[copy.deepcopy(spec['rows'][i][j]) for j in columns] for i in rows]
    result['selected_source_rows'] = rows
    result['selected_source_columns'] = columns
    # Keep value/display/origin objects intact, even when the PDF omits columns.
    return result


def table_markdown(spec):
    def line(values):
        return '| ' + ' | '.join(str(x).replace('|', '\\|').replace('\n', ' ') for x in values) + ' |'
    return '\n'.join([line(spec['headers']), line(['---'] * len(spec['headers']))]
                     + [line(c['display'] for c in row) for row in spec['rows']])


def source_excerpt(source, names):
    # Reader citations describe actual use. The unchanged sealed register retains
    # original retrieval dates/qualifications; never infer them from this excerpt.
    original = (source / 'backtest/report/source_register.md').read_text()
    rows = {}
    for line in original.splitlines():
        if not line.startswith('|'):
            continue
        first = line.strip('| ').split('|')[0].strip()
        key = re.sub(r'^\[([^]]+)\]\([^)]+\)$', r'\1', first)
        rows[key] = [part.strip() for part in line.strip('| ').split('|')]
    missing = set(names) - rows.keys()
    if missing:
        raise ValueError(f'missing source/register entries: {sorted(missing)}')
    labels = dict(core='Core MSCI World NAV', momentum='Momentum NAV', quality='Quality NAV',
        value='Value NAV', indicative_sofr='Indicative reference rate', official_sofr='Official SOFR',
        dimensional='Dimensional NAV hardcopy', amundi_2x='Amundi daily 2x NAV',
        commission_tariff='Commission tariff', stamp_duty='Investor-side stamp duty',
        commission_fx='Commission FX conversion', dimensional_kid='Dimensional key information document',
        sofr_explanation='Reference-rate methodology', risk_measures='Risk-measure definitions',
        swissquote_collateral_agreement='Collateralised loan terms', swissquote_lombard='Lombard loan overview',
        inflow_terminology='Fund fee and expense terminology',
        core_published_annual_performance='Published Core annual returns',
        momentum_published_annual_performance='Published Momentum annual returns',
        quality_published_annual_performance='Published Quality annual returns',
        value_published_annual_performance='Published Value annual returns')
    uses = dict(core='Core accumulating USD NAV; investment returns',
        momentum='Momentum accumulating USD NAV; investment returns',
        quality='Quality accumulating USD NAV; investment returns',
        value='Value accumulating USD NAV; investment returns',
        indicative_sofr='Early indicative financing reference series',
        official_sofr='Later official financing reference series',
        dimensional='USD fund NAV; secondary fund comparison',
        amundi_2x='USD ETF NAV; short-window daily 2x product comparison',
        commission_tariff='Current CHF commission schedule for the investment cost model',
        stamp_duty='Basis for the modelled 0.15% investor-side duty',
        commission_fx='31 August 2026 reference cross-rate; CHF commission conversion only',
        dimensional_kid='USD share-class identity and permitted investment universe; 17 July 2025 KID',
        sofr_explanation='Interpretation of the early reference-rate proxy',
        risk_measures='Background on risk-adjusted performance; calculation conventions stated in Method',
        swissquote_collateral_agreement='Contractual context for hypothetical credit and liquidation risks',
        swissquote_lombard='Product context for borrowing; not an account-specific rate quote',
        inflow_terminology='Background on fund fees and expenses; business assumptions are author-defined')
    identities = ('Fund identities: Core IE00B4L5Y983; Momentum IE00BP3QZ825; '
                  'Quality IE00BP3QZ601; Value IE00BP3QZB59.')
    if 'dimensional' in names:
        identities += ' Dimensional IE00B2PC0153; Amundi FR0014010HV4.'
    header = '| Source | Publisher | Use in this report |\n| --- | --- | --- |\n'
    data_ids = {'core', 'momentum', 'quality', 'value', 'indicative_sofr',
                'official_sofr', 'dimensional', 'amundi_2x'}
    performance_ids = [f'{key}_published_annual_performance'
                       for key in ['core', 'momentum', 'quality', 'value']]

    def citation(name):
        cell = rows[name][0]
        return (re.sub(r'\[([^]]+)\]', lambda m: '[' + labels[name] + ']', cell, count=1)
                if '[' in cell else labels[name])

    def row(name):
        return '| ' + ' | '.join([citation(name), rows[name][1], uses[name]]) + ' |'

    data = [row(name) for name in names if name in data_ids]
    references = [row(name) for name in names
                  if name not in data_ids and name not in performance_ids]
    selected_performance = [name for name in performance_ids if name in names]
    if selected_performance:
        references.append('| ' + '; '.join(citation(name) for name in selected_performance)
                          + ' | BlackRock / iShares | Rounded calendar-year returns; secondary validation of NAV calculations |')
    if 'amundi_2x' in names:
        references.append('| [Amundi key information document, 28 April 2026]'
            '(https://www.amundietf.lu/pdfDocuments/kid-priips/FR0014010HV4/ENG/LUX/20260428)'
            ' | Amundi | Daily-reset 2x mechanism and embedded product/financing costs; not a NAV download source |')
    intro = (identities + '\n\n**Market data and financing series**\n\n'
             'NAV observations and reference rates enter the calculations. '
             'Their sample dates are specified in the analysis. Provider links '
             'identify the funds and series; the supplied local files are the calculation inputs.\n\n')
    note = ('\n\n**Cost, product and methodology references**\n\n'
            'These sources support the stated assumptions, product descriptions and checks. '
            'They are distinguished from time-series inputs.\n\n')
    end = ('\n\nOriginal files and download records are retained with the reproducibility '
           'materials. Fund-business assumptions about client acquisition, redemptions, '
           'fees and budgets are author-defined scenarios rather than observed fundraising data.'
           if 'inflow_terminology' in names else
           '\n\nOriginal files and download records are retained with the reproducibility materials.')
    return intro + header + '\n'.join(data) + note + header + '\n'.join(references) + end


def assemble(project_root, source, output, selection_path, review_path=None):
    project_root, source, output = map(lambda p: Path(p).resolve(), (project_root, source, output))
    if output.exists():
        raise FileExistsError('choose a new reader-report destination')
    for directory in [source, source / 'backtest', source / 'inflow']:
        verify_run(directory)
    before = inventory(source)
    selection_path = Path(selection_path).resolve()
    selection = json.loads(selection_path.read_text())
    resources = Path(__file__).parent / 'templates'
    review_path = (resources / 'research_reader_review_2026-10-06.json'
                   if review_path is None else Path(review_path).resolve())
    review = json.loads(review_path.read_text())
    supplement_path = resources / 'research_ai_supplement_2026-10-06.md'
    ai_record_path = project_root / 'docs/AI_USE_RECORD_2026-10-06.md'
    if (review.get('ai_supplement_sha256') != sha256(supplement_path)
            or review.get('ai_record_sha256') != sha256(ai_record_path)):
        raise ValueError('AI disclosure or record requires renewed review')
    source_manifest = json.loads((source / 'run_manifest.json').read_text())
    if (selection['source_run_id'] != source_manifest['run_id']
            or review['source_run_id'] != selection['source_run_id']
            or review['selection_sha256'] != sha256(selection_path)):
        raise ValueError('source or reader selection requires renewed review')
    tables, claims = load_evidence(source)
    original_report = (source / 'backtest/report/BACKTEST_REPORT_2026-10-06.md').read_text()
    disclosure = original_report.split('**AI assistance and responsibility**\n\n', 1)[1].split('\n\n', 1)[0]
    if not disclosure.startswith('This portfolio-backtest and capital-inflow research package'):
        raise ValueError('expected full author disclosure missing')
    output.mkdir(parents=True)
    for directory in ['report', 'evidence', 'config', 'figures']:
        (output / directory).mkdir()
    copy_bytes(selection_path, output / 'config/reader_selection.json')
    copy_bytes(review_path, output / 'config/reader_review.json')
    copy_bytes(supplement_path, output / 'config' / supplement_path.name)
    copy_bytes(ai_record_path, output / 'evidence/ai_use_record.md')
    results = {}
    for name, plan in selection['reports'].items():
        template_path = project_root / plan['template']
        if sha256(template_path) != review['templates_sha256'][name]:
            raise ValueError(f'{name} reader interpretation requires renewed review')
        template = template_path.read_text()
        copy_bytes(template_path, output / 'config' / template_path.name)
        if set(plan['table_family_disposition']) != set(tables[name]):
            raise ValueError('incomplete source-table disposition')
        for namespace, items in claims[name].items():
            if set(plan['claim_disposition'][namespace]) != set(items):
                raise ValueError('incomplete source-claim disposition')
            actual = set(re.findall(r'\{\{' + namespace + r':(\w+)\}\}', template))
            declared = {k for k, v in plan['claim_disposition'][namespace].items() if v == 'displayed'}
            if actual != declared:
                raise ValueError('claim selection differs from reviewed disposition')
        selected = {key: select_table(tables[name][value['source']], value)
                    for key, value in plan['tables'].items()}
        for key, spec in selected.items():
            spec['source_table'] = plan['tables'][key]['source']
        figure_records = {}
        for key, relative in plan['figures'].items():
            src = source / relative
            if not src.is_file() or before.get(relative) != sha256(src):
                raise ValueError('selected figure missing or changed')
            dest = output / 'figures' / f'{name}_{key}.png'
            copy_bytes(src, dest)
            figure_records[key] = dict(source=relative, sha256=sha256(src), artifact=str(dest.relative_to(output)))
        used = {namespace: [] for namespace in ['table', 'claim', 'historical', 'figure', 'sources', 'disclosure']}

        def substitute(match):
            namespace, key = match.groups()
            used[namespace].append(key)
            if namespace == 'table':
                return table_markdown(selected[key])
            if namespace in ['claim', 'historical']:
                return claims[name][namespace][key]['display']
            if namespace == 'figure':
                return f'![{name.capitalize()} {key.replace("_", " ")}](../{figure_records[key]["artifact"]})'
            if namespace == 'sources':
                if key != name:
                    raise ValueError('wrong source excerpt')
                return source_excerpt(source, plan['source_ids'])
            if key != 'author':
                raise ValueError('unknown disclosure')
            return disclosure + '\n\n' + supplement_path.read_text().strip()

        text = TOKEN.sub(substitute, template)
        if '{{' in text or '}}' in text:
            raise ValueError('unresolved reader token')
        if set(used['table']) != set(selected) or len(used['table']) != len(selected):
            raise ValueError('every selected table must appear once')
        if (set(used['figure']) != set(plan['figures'])
                or len(used['figure']) != len(plan['figures'])
                or used['disclosure'] != ['author']):
            raise ValueError('figure/disclosure selection mismatch')
        sections = re.split(r'^## ', text, flags=re.MULTILINE)
        if (not sections[-1].startswith('AI Assistance and Responsibility\n')
                or text.count(disclosure) != 1 or disclosure in '\n'.join(sections[:-1])):
            raise ValueError('AI disclosure must occur only in the final section')
        report_path = output / 'report' / plan['output']
        report_path.write_text(text)
        displayed_claims = {ns: {k: claims[name][ns][k] for k in sorted(set(used[ns]))}
                            for ns in claims[name]}
        write_json(output / 'evidence' / f'{name}_bindings.json', dict(
            tables=selected, claims=displayed_claims, claim_occurrences=used,
            figures=figure_records, source_entries=plan['source_ids'],
            source_package=str(source.relative_to(project_root)),
            source_run_id=source_manifest['run_id'],
            source_payload_sha256=before,
            manual_context=review['manual_numeric_context']))
        results[name] = dict(file=str(report_path.relative_to(output)), version=plan['version'],
                             tables=len(selected), figures=len(figure_records),
                             unique_claims=sum(len(x) for x in displayed_claims.values()),
                             original_families=len(tables[name]), final_only_ai_disclosure=True)
    # Both companion manuscripts exist before cross-link checking.
    for record in results.values():
        path = output / record['file']
        for target in re.findall(r'!?\[[^]]*\]\(([^)]+)\)', path.read_text()):
            if target.startswith(('http://', 'https://')):
                continue
            resolved = (path.parent / target).resolve()
            if not resolved.is_relative_to(output) or not resolved.is_file():
                raise ValueError('reader link missing or escaping output')
    if inventory(source) != before:
        raise RuntimeError('sealed complete source package changed')
    write_json(output / 'evidence/assembly_checks.json', dict(status='complete', reports=results,
        source_files_unchanged=len(before), source_seals_verified=True,
        selection_coverage='All 52 complete-report table families, original claims and figures accounted for.',
        scope='Verified source cells/displays/claims copied through explicit selections. No financial recomputation, expert review or fresh dependency installation.'))
    (output / 'README.md').write_text(
        '# Research reader reports\n\n'
        '[Portfolio backtest](report/BACKTEST_RESEARCH_2026-10-07.md) · '
        '[Capital inflows](report/CAPITAL_INFLOWS_RESEARCH_2026-10-07.md)\n\n'
        f'Editorial versions {results["backtest"]["version"]}/{results["inflow"]["version"]} assembled from verified complete research evidence. '
        'Financial assumptions and calculations are unchanged. Full omitted material '
        'remains in the separately retained source package; raw data stay local. '
        'Human reading, fresh installation and publication remain subsequent steps.\n')
    artifacts = inventory(output)
    code_path = Path(__file__)
    manifest = dict(schema_version=1, run_id=str(uuid.uuid4()), status='complete',
        figures_included=True, configuration_snapshots={}, artifacts=artifacts,
        source_run_id=source_manifest['run_id'], source_manifest_sha256=sha256(source / 'run_manifest.json'),
        code={code_path.name: sha256(code_path)}, reports=results,
        scope='Local curated reader assembly; financial engines and original outputs unchanged.')
    write_json(output / 'run_manifest.json', manifest)
    verify_run(output)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root', type=Path, default=Path.cwd())
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--selection', type=Path, default=Path('config/research_reader_selection_2026-10-06.json'))
    parser.add_argument('--review', type=Path, help='separately reviewed source binding; all existing checks remain required')
    args = parser.parse_args()
    result = assemble(args.project_root, args.source, args.output, args.selection, args.review)
    print(json.dumps(dict(run_id=result['run_id'], reports=result['reports']), indent=2))


if __name__ == '__main__':
    main()
