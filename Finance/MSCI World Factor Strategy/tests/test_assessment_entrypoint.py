"""Recipient relocation and refusal cases for the assessment start wrapper."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil

import pytest

TOOL = Path(__file__).resolve().parents[1] / 'tools/run_assessment.py'
spec = importlib.util.spec_from_file_location('assessment_entrypoint', TOOL)
assessment = importlib.util.module_from_spec(spec)
spec.loader.exec_module(assessment)


def packet_fixture(tmp_path):
    project = tmp_path / 'Assessment/Code'
    packet = tmp_path / 'Assessment/Inputs'
    project.mkdir(parents=True)
    packet.mkdir(parents=True)
    roots = {name: 'originals/' + name for name in sorted(assessment.ROOT_NAMES)}
    entries = []
    names = list(roots)
    for index in range(25):
        root = names[index % len(names)]
        relative = f'input-{index}.dat'
        path = packet / roots[root] / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f'original-{index}'.encode())
        entries.append(dict(input_root=root, relative_path=relative,
                            sha256=assessment.digest(path)))
    inventory = project / assessment.INVENTORY
    inventory.parent.mkdir(parents=True)
    inventory.write_text(json.dumps({'inputs': entries}))
    (packet / 'ORIGINAL_DATA_REQUIREMENTS.json').write_bytes(inventory.read_bytes())
    pins = {}
    for relative in sorted(assessment.PIN_FILES):
        path = project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if path != inventory:
            path.write_text('declared public source\n')
        pins[relative] = assessment.digest(path)
    info = dict(public_project_pins=pins, inventory_sha256=assessment.digest(inventory),
                input_roots=roots, original_file_count=25)
    (packet / 'PACKAGE_INFO.json').write_text(json.dumps(info))
    return project, packet, entries, info


def test_relocated_package_locates_all_inputs_without_writing(tmp_path):
    project, packet, entries, info = packet_fixture(tmp_path)
    moved = tmp_path / 'another folder'
    shutil.move(str(project.parent), moved)
    roots = assessment.verify_packet(moved / 'Code', moved / 'Inputs')
    assert len(roots) == 6
    assert all(Path(value).is_relative_to(moved / 'Inputs') for value in roots.values())
    assert not (moved / 'Code/local').exists()


@pytest.mark.parametrize('alteration', ['missing', 'changed', 'linked-file', 'linked-root'])
def test_invalid_input_stops_before_any_project_write(tmp_path, alteration):
    project, packet, entries, info = packet_fixture(tmp_path)
    entry = entries[0]
    root = packet / info['input_roots'][entry['input_root']]
    path = root / entry['relative_path']
    if alteration == 'missing':
        path.unlink()
    elif alteration == 'changed':
        path.write_bytes(b'changed')
    elif alteration == 'linked-file':
        outside = tmp_path / 'original-copy'
        outside.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(outside)
    else:
        outside = tmp_path / 'original-root'
        shutil.move(root, outside)
        root.symlink_to(outside, target_is_directory=True)
    with pytest.raises((ValueError, OSError)):
        assessment.verify_packet(project, packet)
    assert not (project / 'local').exists() and not (project / 'outputs').exists()


def test_packet_cannot_replace_public_inventory_or_point_at_unlisted_source(tmp_path):
    project, packet, entries, info = packet_fixture(tmp_path)
    (packet / 'ORIGINAL_DATA_REQUIREMENTS.json').write_text('{}')
    with pytest.raises(ValueError, match='inventory'):
        assessment.verify_packet(project, packet)
    info['public_project_pins']['../private'] = '0' * 64
    (packet / 'PACKAGE_INFO.json').write_text(json.dumps(info))
    with pytest.raises(ValueError, match='five declared'):
        assessment.verify_packet(project, packet)


def test_private_data_inside_repository_is_rejected(tmp_path):
    project, packet, entries, info = packet_fixture(tmp_path)
    (project.parent / '.git').mkdir()
    with pytest.raises(ValueError, match='outside the GitHub'):
        assessment.verify_packet(project, packet)


@pytest.mark.parametrize('relative', ['../outside', '/outside', 'outputs/../elsewhere',
                                      'local/results', 'outputs', 'outputs/linked/result'])
def test_output_escape_and_link_paths_do_not_touch_victim(tmp_path, relative):
    project = tmp_path / 'Code'
    project.mkdir()
    (project / 'outputs').mkdir()
    victim = tmp_path / 'victim'
    victim.mkdir()
    (victim / 'keep').write_bytes(b'original')
    (project / 'outputs/linked').symlink_to(victim, target_is_directory=True)
    with pytest.raises(ValueError):
        assessment.output_path(project, relative)
    assert (victim / 'keep').read_bytes() == b'original'
    assert not (victim / 'result').exists()


def test_existing_output_and_shared_parent_are_preserved(tmp_path):
    project = tmp_path / 'Code'
    existing = project / 'outputs/existing'
    existing.mkdir(parents=True)
    (existing / 'keep').write_bytes(b'original')
    with pytest.raises(FileExistsError):
        assessment.output_path(project, 'outputs/existing')
    assert (existing / 'keep').read_bytes() == b'original'
    shared = project / 'outputs/shared'
    shared.mkdir()
    shared.chmod(0o777)
    try:
        with pytest.raises(PermissionError):
            assessment.output_path(project, 'outputs/shared/new')
    finally:
        shared.chmod(0o700)


def test_fifo_cannot_block_inventory_hashing(tmp_path):
    import os
    fifo = tmp_path / 'metadata'
    os.mkfifo(fifo)
    with pytest.raises(ValueError, match='regular file'):
        assessment.digest(fifo)
