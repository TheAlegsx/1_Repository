"""One assumption snapshot, no overwritten runs, and explicit failure state."""
import csv
import json
from pathlib import Path
import shutil

import pytest

from factor_portfolio import inflow_workflow as workflow

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def config_dir(tmp_path):
    destination = tmp_path / 'config'
    destination.mkdir()
    for name in workflow.CONFIG_NAMES:
        shutil.copyfile(ROOT / 'config' / name, destination / name)
    return destination


def test_configuration_changes_during_run_do_not_mix_assumptions(config_dir, tmp_path, monkeypatch):
    source = config_dir / 'inflow_acquisition.json'
    original = source.read_bytes()
    real_builder = workflow.build_results

    def changed_source(*args):
        edited = json.loads(source.read_text())
        edited['initial_owner_capital_usd'] = 999
        source.write_text(json.dumps(edited))
        return real_builder(*args)

    monkeypatch.setattr(workflow, 'build_results', changed_source)
    output = tmp_path / 'run'
    manifest = workflow.run_study(config_dir, output, figures=False)
    assert manifest['status'] == 'complete'
    assert (output / 'config/inflow_acquisition.json').read_bytes() == original
    with (output / 'tables/acquisition_monthly.csv').open() as f:
        acquisition = next(csv.DictReader(f))
    with (output / 'tables/timing_monthly.csv').open() as f:
        timing = next(csv.DictReader(f))
    capital = json.loads(original)['initial_owner_capital_usd']
    assert float(acquisition['owner_equity_usd']) / float(acquisition['unit_nav']) == pytest.approx(capital / 100)
    assert float(timing['start_cohort_equity_usd']) / float(timing['nav_per_unit']) == pytest.approx(capital / 100)
    assert workflow.verify_run(output)['verified_files'] == 41
    assert manifest['figures_included'] is False
    assert manifest['counts']['figures'] == 0
    assert json.loads((output / 'report_tables/input_manifest.json').read_text())['run_manifest'] == '../run_manifest.json'


def test_completed_runs_cannot_be_overwritten_and_artifact_changes_are_detected(config_dir, tmp_path):
    output = tmp_path / 'run'
    workflow.run_study(config_dir, output, figures=False)
    original = (output / 'run_manifest.json').read_bytes()
    with pytest.raises(FileExistsError, match='never overwritten'):
        workflow.run_study(config_dir, output, figures=False)
    assert (output / 'run_manifest.json').read_bytes() == original
    (output / 'tables/timing_headline.csv').write_text('changed data')
    with pytest.raises(ValueError, match='missing or changed'):
        workflow.verify_run(output)


def test_failed_calculation_is_not_accepted_as_a_complete_run(config_dir, tmp_path, monkeypatch):
    def failure(*args):
        raise RuntimeError('injected return calculation failure')
    monkeypatch.setattr(workflow, 'return_diagnostics', failure)
    output = tmp_path / 'failed'
    with pytest.raises(RuntimeError, match='injected'):
        workflow.run_study(config_dir, output, figures=False)
    manifest = json.loads((output / 'run_manifest.json').read_text())
    assert manifest['status'] == 'failed'
    assert [s['id'] for s in manifest['stages']] == ['tables']
    with pytest.raises(ValueError, match='not complete'):
        workflow.verify_run(output)


def test_return_diagnostics_cannot_silently_use_a_different_nav_basis(config_dir, tmp_path):
    path = config_dir / 'inflow_returns.json'
    settings = json.loads(path.read_text())
    settings['initial_unit_nav'] = 1000
    path.write_text(json.dumps(settings))
    output = tmp_path / 'invalid'
    with pytest.raises(ValueError, match='initial NAV 100'):
        workflow.run_study(config_dir, output, figures=False)
    assert not output.exists()
