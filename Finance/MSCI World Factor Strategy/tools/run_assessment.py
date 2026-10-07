"""Start the existing reconstruction from an extracted private assessment package.

No installer, download, upload or financial implementation is added here.
Complete SETUP.md first. Private data must remain outside the GitHub tree.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys
import uuid

ROOT_NAMES = {'raw_root', 'annual_raw_root', 'factor_annual_raw_root',
              'dimensional_annual_raw_root', 'collateral_raw_root', 'custody_raw_root'}
INVENTORY = 'docs/ORIGINAL_DATA_REQUIREMENTS_2026-10-06.json'
PIN_FILES = {INVENTORY, 'config/reproduction_recipe_2026-10-06.json',
             'config/reproduction_reference_2026-10-06.json',
             'requirements-security-lock.txt', 'src/factor_portfolio/publication_reproduce.py'}
FONT_FILES = ('Times New Roman.ttf', 'Times New Roman Bold.ttf',
              'Times New Roman Italic.ttf', 'Times New Roman Bold Italic.ttf')


def digest(path):
    result = hashlib.sha256()
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as stream:
        metadata = os.fstat(stream.fileno())
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > 64 * 1024 * 1024:
            raise ValueError('Hash input must be a bounded regular file: ' + path.name)
        total = 0
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            total += len(block)
            if total > 64 * 1024 * 1024:
                raise ValueError('Hash input grew beyond its byte limit: ' + path.name)
            result.update(block)
    return result.hexdigest()


def plain_under(root, relative):
    """Accept package-relative paths only; do not follow links below the root."""
    name = PurePosixPath(relative)
    if (not relative or name.is_absolute() or '..' in name.parts
            or '\\' in relative or ':' in relative or str(name) == '.'):
        raise ValueError('Use a non-empty relative path without traversal: ' + relative)
    path = root
    for part in name.parts:
        path = path / part
        if path.is_symlink():
            raise ValueError('Symbolic links are not accepted in package paths: ' + relative)
    return path


def read_json(path):
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > 1024 * 1024:
        raise ValueError('Package metadata must be a bounded regular file: ' + path.name)
    with path.open('rb') as stream:
        data = stream.read(1024 * 1024 + 1)
    if len(data) > 1024 * 1024:
        raise ValueError('Package metadata exceeds its byte limit')
    return json.loads(data)


def verify_packet(project, data):
    project, data = Path(project).resolve(), Path(data).absolute()
    if data.is_symlink() or not data.is_dir():
        raise ValueError('Supply a plain private input folder')
    data = data.resolve()
    repository = project.parent.parent if project.parent.name == 'Finance' else project
    git_roots = [parent for parent in [project, *project.parents] if (parent / '.git').exists()]
    if any(data.is_relative_to(root) for root in [repository, *git_roots]):
        raise ValueError('Keep private inputs outside the GitHub repository')
    info = read_json(plain_under(data, 'PACKAGE_INFO.json'))
    if set(info['public_project_pins']) != PIN_FILES:
        raise ValueError('The packet must pin the five declared public reconstruction files')
    for relative, expected in info['public_project_pins'].items():
        path = plain_under(project, relative)
        if not path.is_file() or digest(path) != expected:
            raise ValueError('Public source differs from the data packet pin: ' + relative)
    canonical = plain_under(project, INVENTORY)
    copied = plain_under(data, 'ORIGINAL_DATA_REQUIREMENTS.json')
    if digest(canonical) != info['inventory_sha256'] or digest(copied) != digest(canonical):
        raise ValueError('Packet inventory must match the public original-data inventory')
    inventory = read_json(canonical)
    if set(info['input_roots']) != ROOT_NAMES or info['original_file_count'] != 25:
        raise ValueError('All six declared roots and 25 originals are required')
    entries = inventory['inputs']
    identities = {(entry['input_root'], entry['relative_path']) for entry in entries}
    if len(entries) != 25 or len(identities) != 25:
        raise ValueError('The public inventory must contain 25 distinct originals')
    roots = {}
    for name, relative in info['input_roots'].items():
        folder = plain_under(data, relative)
        if not folder.is_dir():
            raise ValueError('Original-data root is missing: ' + name)
        roots[name] = str(folder)
    for entry in entries:
        path = plain_under(Path(roots[entry['input_root']]), entry['relative_path'])
        metadata = path.stat()
        if (not stat.S_ISREG(metadata.st_mode) or metadata.st_size > 64 * 1024 * 1024
                or digest(path) != entry['sha256']):
            raise ValueError('Original file changed or is not a bounded regular file: ' + entry['relative_path'])
    return roots


def output_path(project, relative):
    path = plain_under(project, relative)
    if not path.is_relative_to(project / 'outputs') or path == project / 'outputs':
        raise ValueError('Choose a new reconstruction directory below outputs/')
    if path.exists():
        raise FileExistsError('Existing reconstruction output preserved; choose a new name')
    for parent in path.parents:
        if parent == project:
            break
        if parent.exists():
            metadata = parent.stat()
            if (not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.getuid()
                    or metadata.st_mode & 0o022):
                raise PermissionError('Output parents must be private user-owned directories')
    return path


def start(project, data, output=None, font_directory=None, include_pdf=True, check_only=False):
    project = Path(project).resolve()
    if os.name != 'posix':
        raise RuntimeError('This entrypoint requires the documented POSIX environment; Windows is unverified')
    roots = verify_packet(project, data)
    run_name = 'assessment-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8]
    destination = output_path(project, output or 'outputs/' + run_name)
    fonts = Path(font_directory or '/System/Library/Fonts/Supplemental')
    if include_pdf and any(not (fonts / name).is_file() for name in FONT_FILES):
        raise FileNotFoundError('Supply all four licensed Times New Roman fonts, or use --no-pdf')
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(project / 'src'))
    from factor_portfolio.security_io import require_runtime, require_installation, write_immutable_payloads
    runtime = require_runtime()
    packages = require_installation(project)
    preflight = dict(status='preflight passed', original_files=25, locked_distributions=len(packages),
                     runtime=runtime, pdf_requested=include_pdf, financial_parameters_changed=False,
                     scope='Technical input/environment checks; no provider-rights or commercial approval.')
    if check_only:
        print(json.dumps(preflight, indent=2), flush=True)
        return preflight
    preparation = plain_under(project, 'local/' + run_name)
    local = preparation.parent
    if local.exists():
        metadata = local.stat()
        if not local.is_dir() or metadata.st_uid != os.getuid() or metadata.st_mode & 0o022:
            raise PermissionError('local/ must be a plain private user-owned directory')
    else:
        local.mkdir(mode=0o700)
    preparation.mkdir(mode=0o700)
    mapping = preparation / 'input_roots.json'
    write_immutable_payloads({mapping: (json.dumps(roots, indent=2) + '\n').encode(),
                              preparation / 'preflight.json': (json.dumps(preflight, indent=2) + '\n').encode()},
                             'assessment preparation')
    # Set this before importing plotting/report code, including in the parent process.
    os.environ['MPLCONFIGDIR'] = str(preparation / 'matplotlib')
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    from factor_portfolio.publication_reproduce import run
    result = run(project, mapping, destination, fonts, include_pdf)
    summary = ('# Reconstruction outcome\n\n'
               'Status: complete. All 25 originals passed input checks. '
               f"All {len(result['evidence_jobs'])} calculation jobs and {result['exact_reference_csv_files']} "
               'reviewed CSV checks passed. Report manuscript and figure checks passed.\n\n'
               '- [Numerical reconstruction checks](reconstruction_checks.json)\n'
               '- [Regenerated report manuscripts](readers/report/)\n'
               '- [Complete report evidence](complete_reports/)\n'
               '- [Job logs](logs/)\n' +
               ('- [Regenerated PDFs](pdf/)\n' if include_pdf else '') +
               '\nPDF visual review remains separate from numerical verification. '
               'This outcome does not certify data-provision rights, investment performance or commercial viability.\n')
    write_immutable_payloads({destination / 'ASSESSMENT_SUMMARY.md': summary.encode('utf-8')},
                             'assessment summary')
    print('Open: ' + str(destination / 'ASSESSMENT_SUMMARY.md'), flush=True)
    return result


def main():
    project = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=project.parent / 'Inputs')
    parser.add_argument('--output', help='New relative folder below outputs/; a unique name is generated by default')
    parser.add_argument('--font-directory', type=Path)
    parser.add_argument('--no-pdf', action='store_true')
    parser.add_argument('--check-only', action='store_true', help='Verify inputs and environment without writing or calculating')
    options = parser.parse_args()
    try:
        start(project, options.data, options.output, options.font_directory,
              not options.no_pdf, options.check_only)
    except (ValueError, OSError, KeyError, TypeError, RuntimeError, subprocess.CalledProcessError) as error:
        print('Stopped: ' + str(error), file=sys.stderr)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
