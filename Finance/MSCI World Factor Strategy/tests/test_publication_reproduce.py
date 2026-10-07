"""A new run identity is accepted only after reviewed financial evidence checks."""
import hashlib
import json
from pathlib import Path

import pytest

from factor_portfolio.publication_reproduce import verify_reference_run, bind_readers, run


def sealed_fixture(directory, value='1'):
    directory.mkdir()
    data=directory/'result.csv';data.write_text('value\n'+value+'\n')
    digest=hashlib.sha256(data.read_bytes()).hexdigest()
    manifest=dict(status='complete',run_id='new_identity',figures_included=False,
                  configuration_snapshots={},artifacts={'result.csv':digest})
    (directory/'run_manifest.json').write_text(json.dumps(manifest))
    return dict(configuration_snapshots={},csv_artifacts={'result.csv':digest})


def test_new_run_identity_does_not_replace_reference_result_checks(tmp_path):
    reference=sealed_fixture(tmp_path/'first')
    sealed_fixture(tmp_path/'second')
    assert verify_reference_run(tmp_path/'second',reference)==1
    sealed_fixture(tmp_path/'changed','2')
    with pytest.raises(ValueError,match='CSV hashes'):
        verify_reference_run(tmp_path/'changed',reference)


def test_missing_unrecorded_and_modified_artifacts_fail(tmp_path):
    reference=sealed_fixture(tmp_path/'run')
    (tmp_path/'run/result.csv').write_text('value\n2\n')
    with pytest.raises(ValueError,match='artifact missing or changed'):
        verify_reference_run(tmp_path/'run',reference)


def test_changed_reference_configuration_is_rejected(tmp_path):
    reference=sealed_fixture(tmp_path/'run')
    reference['configuration_snapshots']={'config/settings.json':'unreviewed'}
    with pytest.raises(ValueError,match='configuration snapshots'):
        verify_reference_run(tmp_path/'run',reference)


def test_non_equivalent_complete_source_cannot_write_reader_binding(tmp_path,monkeypatch):
    def reject(source,reference):
        raise ValueError('complete table/claim evidence differs')
    monkeypatch.setattr('factor_portfolio.publication_reproduce.check_complete_source',reject)
    with pytest.raises(ValueError,match='evidence differs'):
        bind_readers(tmp_path,tmp_path/'source',tmp_path/'readers',{},tmp_path/'binding')
    assert not (tmp_path/'binding').exists() and not (tmp_path/'readers').exists()


def test_existing_outputs_and_outside_project_paths_are_preserved(tmp_path):
    project=tmp_path/'project';project.mkdir()
    existing=project/'existing';existing.mkdir();(existing/'retain').write_text('original')
    with pytest.raises(FileExistsError):run(project,tmp_path/'missing',existing,tmp_path/'fonts')
    assert (existing/'retain').read_text()=='original'
    with pytest.raises(ValueError,match='inside the project'):
        run(project,tmp_path/'missing',tmp_path/'outside',tmp_path/'fonts')
    assert not (tmp_path/'outside').exists()
