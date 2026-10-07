"""A report must bind new numerical evidence to reviewed prose and portable files."""
import copy
import json
from pathlib import Path
import shutil

import pytest

from factor_portfolio import inflow_report as report
from factor_portfolio import inflow_workflow as workflow
from factor_portfolio.inflow_figures import read_table

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def assembled(tmp_path_factory):
    output = tmp_path_factory.mktemp('report') / 'run'
    manifest = workflow.run_study(ROOT / 'config', output, figures=False)
    return output, manifest


def test_report_rebuilds_text_tables_and_sources_without_missing_local_links(assembled):
    output, manifest = assembled
    text = (output / 'report/report.md').read_text()
    checks = json.loads((output / 'report/assembly_checks.json').read_text())
    claims = json.loads((output / 'report/claims.json').read_text())['claims']
    assert '{{' not in text
    assert 'results/' not in text
    assert 'USD 42,233 cumulative external fees' in text
    assert 'USD 836,556.50' in text
    assert 'USD 136,920 peak deficit in month 70' in text
    assert '| Early steps | -1.85% | -2.99% |' in text
    assert len(checks['links']) == len(report.validate_links(text, output / 'report', output))
    assert checks['tables'] == 12
    assert checks['figures'] == 0
    assert 'Figures are explicitly excluded' in text
    assert manifest['full_report_included'] is True
    assert manifest['counts']['text_claims'] == len(claims)
    assert manifest['counts']['full_reports'] == 1
    assert manifest['stages'][-1]['id'] == 'report'
    for name in ['inflow_report.md', 'inflow_report_review.json']:
        assert 'factor_portfolio/templates/' + name in manifest['code']
    assert 'USD 7 million' in text
    assert 'newly approved group version' in text


def test_text_claims_come_from_current_results_and_round_residuals_upwards(assembled):
    output, _ = assembled
    configs = {n: json.loads((output / 'config' / n).read_text()) for n in workflow.CONFIG_NAMES}
    tables = {p.name: read_table(p) for p in (output / 'tables').glob('*.csv')}
    investor = json.loads((output / 'returns/return_diagnostics.json').read_text())
    loss = json.loads((output / 'controls/loss_controls.json').read_text())
    treasury = json.loads((output / 'controls/treasury_controls.json').read_text())
    review = json.loads((output / 'report/template_review.json').read_text())
    reordered = json.loads(json.dumps(configs, sort_keys=True))
    ordered_claims = report.prose_claims(configs, tables, investor, loss, treasury, review)
    reordered_claims = report.prose_claims(reordered, tables, investor, loss, treasury, review)
    assert reordered_claims['no_flow_equities'] == ordered_claims['no_flow_equities']
    changed = copy.deepcopy(tables)
    row = next(r for r in changed['acquisition_headline.csv'] if r['return_scenario'] == 'growth' and r['flow_scenario'] == 'steady')
    row['external_fees_10y_usd'] = 12345.6
    loss['summary']['same_net_owner_max_error_usd'] = 4.1e-9
    claims = report.prose_claims(configs, changed, investor, loss, treasury, review)
    assert claims['steady_fees']['value'] == 12345.6
    assert claims['steady_fees']['display'] == 'USD 12,346 cumulative external fees'
    assert claims['steady_fees']['sources'][0]['selector'] == dict(return_scenario='growth', flow_scenario='steady')
    assert claims['owner_control_residual']['display'] == 'USD 0.000000005'


def test_changed_assumptions_require_text_review_but_numerical_experiments_remain_available(tmp_path):
    configs = tmp_path / 'config'
    configs.mkdir()
    for n in workflow.CONFIG_NAMES:
        shutil.copyfile(ROOT / 'config' / n, configs / n)
    path = configs / 'inflow_acquisition.json'
    b = json.loads(path.read_text())
    b['annual_fixed_manager_cost_usd'] = 26000
    path.write_text(json.dumps(b))
    destination = tmp_path / 'unreviewed'
    with pytest.raises(ValueError, match='editorial review'):
        workflow.run_study(configs, destination, figures=False)
    assert not destination.exists()
    output = tmp_path / 'numerical'
    manifest = workflow.run_study(configs, output, figures=False, report=False)
    assert manifest['full_report_included'] is False
    assert manifest['counts']['full_reports'] == 0
    assert not (output / 'report').exists()
    assert workflow.verify_run(output)['verified_files'] == 36
    assert 'report' not in [stage['id'] for stage in manifest['stages']]


def test_cosmetic_json_changes_do_not_invalidate_interpretation_review():
    resources = report.load_template()
    configs = {n: json.loads((ROOT / 'config' / n).read_text()) for n in workflow.CONFIG_NAMES}
    configs = json.loads(json.dumps(configs, sort_keys=True, indent=4))
    report.validate_template(configs, resources)
    resources['inflow_report.md'] += b'\nA different interpretation.\n'
    with pytest.raises(ValueError, match='report text changed'):
        report.validate_template(configs, resources)


def test_missing_and_escaping_report_links_fail_instead_of_linking_old_workspace(tmp_path):
    root = tmp_path / 'run'
    destination = root / 'report'
    destination.mkdir(parents=True)
    with pytest.raises(ValueError, match='missing or outside'):
        report.validate_links('[evidence](../absent.csv)', destination, root)
    secret = tmp_path / 'outside.md'
    secret.write_text('outside this run')
    with pytest.raises(ValueError, match='missing or outside'):
        report.validate_links('[evidence](../../outside.md)', destination, root)
    with pytest.raises(ValueError, match='unsupported'):
        report.validate_links('[evidence](file:///tmp/source.md)', destination, root)
