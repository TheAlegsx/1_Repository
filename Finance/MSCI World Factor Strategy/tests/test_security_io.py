"""Regression checks for the audit's concrete filesystem and parser failures."""
import json
from pathlib import Path
from types import SimpleNamespace
import zipfile

import pandas as pd
import pytest

from factor_portfolio.security_io import (atomic_json, write_immutable_payloads,
    validate_xlsx, parse_bounded_xml, require_runtime, MAX_XML_BYTES, MAX_SHEET_COLUMNS)
from factor_portfolio.data import write_canonical_dataset, _row_values
from factor_portfolio.market_data import write_market_dataset
from factor_portfolio.rates import write_funding_dataset
from xml.etree import ElementTree as ET


def test_atomic_json_does_not_follow_the_old_predictable_temporary_link(tmp_path):
    output = tmp_path / 'output'; output.mkdir()
    victim = tmp_path / 'victim'; victim.write_bytes(b'keep original')
    (output / 'manifest.json.tmp').symlink_to(victim)
    atomic_json(output / 'manifest.json', {'status': 'complete'})
    assert victim.read_bytes() == b'keep original'
    assert json.loads((output / 'manifest.json').read_text()) == {'status': 'complete'}


@pytest.mark.parametrize('existing', [True, False])
def test_atomic_json_rejects_linked_destination(tmp_path, existing):
    output = tmp_path / 'output'; output.mkdir()
    victim = tmp_path / 'victim'
    if existing: victim.write_bytes(b'keep original')
    (output / 'manifest.json').symlink_to(victim)
    with pytest.raises(FileExistsError): atomic_json(output / 'manifest.json', {'changed': True})
    assert victim.read_bytes() == b'keep original' if existing else not victim.exists()


def test_atomic_json_refuses_shared_writable_parent(tmp_path):
    output = tmp_path / 'shared'; output.mkdir(); output.chmod(0o777)
    try:
        with pytest.raises(PermissionError): atomic_json(output / 'manifest.json', {})
        assert not (output / 'manifest.json').exists()
    finally: output.chmod(0o700)


def test_atomic_json_replacement_retains_exact_serialization_and_leaves_no_temporary_files(tmp_path):
    path = tmp_path / 'state.json'
    atomic_json(path, {'value': 1})
    atomic_json(path, {'value': 2, 'unicode': 'ä'})
    assert path.read_bytes() == (json.dumps({'value': 2, 'unicode': 'ä'}, indent=2,
                                           ensure_ascii=False, allow_nan=False) + '\n').encode()
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize('writer,filename', [
    ('canonical', 'daily_nav_usd.csv'), ('market', 'listing_quotes_usd.csv'),
    ('funding', 'reference_rate_observations_usd.csv')])
def test_all_raw_snapshot_writers_refuse_dangling_output_links(tmp_path, writer, filename):
    output = tmp_path / 'output'; output.mkdir()
    victim = tmp_path / 'outside.csv'
    (output / filename).symlink_to(victim)
    frame = pd.DataFrame({'value': [1.]}, index=pd.to_datetime(['2030-01-02']))
    if writer == 'canonical':
        dataset = SimpleNamespace(nav_usd=frame, returns_usd=frame, manifest={})
        call = lambda: write_canonical_dataset(dataset, output)
    elif writer == 'market':
        dataset = SimpleNamespace(listing_quotes=frame, spread_calibration=frame,
                                  mxwoldnu_index=frame, amundi_nav=frame, benchmark_overlap=frame, manifest={})
        call = lambda: write_market_dataset(dataset, output)
    else:
        dataset = SimpleNamespace(reference_observations=frame, daily_borrow_rates=frame, manifest={})
        call = lambda: write_funding_dataset(dataset, output)
    with pytest.raises(FileExistsError): call()
    assert not victim.exists()
    assert [p.name for p in output.iterdir()] == [filename]


def test_snapshot_preflight_preserves_every_file_when_one_differs(tmp_path):
    first, second = tmp_path / 'first', tmp_path / 'second'
    first.write_bytes(b'old')
    with pytest.raises(FileExistsError):
        write_immutable_payloads({first: b'changed', second: b'new'}, 'fixture')
    assert first.read_bytes() == b'old' and not second.exists()


def test_sparse_column_input_cannot_allocate_an_unbounded_list():
    row = ET.fromstring('<Row xmlns="urn:schemas-microsoft-com:office:spreadsheet" '
                        'xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">'
                        '<Cell ss:Index="999999999999"><Data>1</Data></Cell></Row>')
    with pytest.raises(ValueError, match='bounds'): _row_values(row)


def test_xml_declarations_and_oversize_are_refused():
    with pytest.raises(ValueError, match='DTD'): parse_bounded_xml(b'<!DOCTYPE root><root/>')
    with pytest.raises(ValueError, match='byte budget'): parse_bounded_xml(b'x' * (MAX_XML_BYTES + 1))
    assert parse_bounded_xml(b'<root><value>unchanged</value></root>').find('value').text == 'unchanged'


@pytest.mark.parametrize('encoding', ['utf-16-le', 'utf-16-be', 'utf-32-le', 'utf-32-be'])
def test_entity_rejection_cannot_be_bypassed_by_encoding_without_a_bom(encoding):
    with pytest.raises(ValueError, match='DTD'):
        parse_bounded_xml('<!DOCTYPE root><root/>'.encode(encoding))


def test_excessive_xml_depth_is_rejected_before_accepting_the_tree():
    with pytest.raises(ValueError, match='depth budget'):
        parse_bounded_xml(b'<r>' * 129 + b'</r>' * 129)


@pytest.mark.parametrize('kind', ['ratio', 'traversal', 'duplicate', 'bzip2'])
def test_malformed_or_excessively_compressed_workbooks_are_refused(tmp_path, kind):
    path = tmp_path / 'fixture.xlsx'
    compression = zipfile.ZIP_BZIP2 if kind == 'bzip2' else zipfile.ZIP_DEFLATED
    with zipfile.ZipFile(path, 'w', compression=compression) as archive:
        name = '../escape.xml' if kind == 'traversal' else 'xl/sharedStrings.xml'
        archive.writestr(name, b'A' * 1048576 if kind == 'ratio' else b'<root/>')
        if kind == 'duplicate': archive.writestr(name, b'<root/>')
    with pytest.raises(ValueError): validate_xlsx(path)


def test_supported_runtime_is_actually_patched():
    checked = require_runtime()
    assert checked['python'].startswith('3.12.')
    assert tuple(map(int, checked['expat'].removeprefix('expat_').split('.'))) >= (2, 9, 0)


@pytest.mark.parametrize('component', ['python', 'openssl', 'expat'])
def test_runtime_guard_rejects_the_previously_demonstrated_vulnerable_versions(monkeypatch, component):
    import factor_portfolio.security_io as security
    if component == 'python': monkeypatch.setattr(security.sys, 'version_info', (3, 12, 14))
    elif component == 'openssl': monkeypatch.setattr(security.ssl, 'OPENSSL_VERSION', 'OpenSSL 3.5.8 25 Aug 2026')
    else: monkeypatch.setattr(security.pyexpat, 'EXPAT_VERSION', 'expat_2.8.3')
    with pytest.raises(RuntimeError): require_runtime()
