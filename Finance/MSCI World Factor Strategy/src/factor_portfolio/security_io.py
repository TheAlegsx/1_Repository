"""Bounded local inputs and link-safe writes for the reviewed research workflow.

These controls preserve payload bytes. They are not a sandbox for arbitrary code.
"""
from __future__ import annotations

import argparse
import codecs
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path, PurePosixPath
import pyexpat
import re
import secrets
import ssl
import stat
import sys
from xml.etree import ElementTree as ET
from zipfile import ZipFile, ZIP_STORED, ZIP_DEFLATED

MAX_SOURCE_BYTES = 64 * 1024 * 1024
MAX_XML_BYTES = 16 * 1024 * 1024
MAX_XML_NODES = 500_000
MAX_XML_DEPTH = 128
MAX_SHEET_COLUMNS = 16_384
MAX_ZIP_ENTRIES = 4096
MAX_ZIP_EXPANDED_BYTES = 64 * 1024 * 1024
MAX_ZIP_MEMBER_BYTES = 16 * 1024 * 1024
MAX_ZIP_RATIO = 200


def require_runtime():
    """Fail before source parsing when the declared patched runtime is absent."""
    python = tuple(sys.version_info[:3])
    # OPENSSL_VERSION_INFO retains the older five-field layout: on OpenSSL 3
    # the third field may be zero and the semantic patch is in the fourth.
    parsed = re.match(r'^OpenSSL (\d+)\.(\d+)\.(\d+)\b', ssl.OPENSSL_VERSION)
    if parsed is None:
        raise RuntimeError('Use a reviewed OpenSSL runtime, not an unverified alternative SSL library.')
    openssl = tuple(map(int, parsed.groups()))
    expat = tuple(map(int, pyexpat.EXPAT_VERSION.removeprefix('expat_').split('.')))
    ssl_floors = {(3, 5): 9, (3, 6): 5, (4, 0): 3}
    if python[:2] != (3, 12) or python < (3, 12, 15):
        raise RuntimeError('Use the reviewed Python 3.12.15+ runtime (Python 3.12 series).')
    if openssl[:2] not in ssl_floors or openssl[2] < ssl_floors[openssl[:2]]:
        raise RuntimeError('Use patched OpenSSL: 3.5.9+, 3.6.5+ or 4.0.3+ in the declared branch.')
    if expat < (2, 9, 0) or expat[0] != 2:
        raise RuntimeError('Use a reviewed runtime linked to Expat 2.9.0+ (2.x).')
    return {'python': '.'.join(map(str, python)), 'openssl': ssl.OPENSSL_VERSION,
            'expat': pyexpat.EXPAT_VERSION}


def require_installation(project):
    """The complete reconstruction uses only the reviewed locked environment."""
    checked = {}
    for line in (Path(project) / 'requirements-security-lock.txt').read_text().splitlines():
        if not line or line.startswith('#'):
            continue
        pin = line.split(' --hash=', 1)[0]
        name, expected = pin.split('==', 1)
        try:
            actual = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            raise RuntimeError('Install the complete reviewed security lock: missing ' + name) from None
        if actual != expected:
            raise RuntimeError('Installed package differs from the reviewed lock: ' + name)
        checked[name] = actual
    return checked


def bounded_input(path, limit=MAX_SOURCE_BYTES):
    path = Path(path)
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
        raise ValueError('Input is not a bounded regular file: ' + path.name)
    return path


def read_bounded_bytes(path, limit=MAX_XML_BYTES):
    path = bounded_input(path, limit)
    with path.open('rb') as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError('Input grew beyond the declared byte budget: ' + path.name)
    return data


def parse_bounded_xml(data):
    require_runtime()
    if len(data) > MAX_XML_BYTES:
        raise ValueError('XML exceeds the declared byte budget')
    if data.startswith((codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)):
        encoding = 'utf-32'
    elif data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        encoding = 'utf-16'
    elif data.startswith(b'<\x00\x00\x00'):
        encoding = 'utf-32-le'
    elif data.startswith(b'\x00\x00\x00<'):
        encoding = 'utf-32-be'
    elif data.startswith(b'<\x00'):
        encoding = 'utf-16-le'
    elif data.startswith(b'\x00<'):
        encoding = 'utf-16-be'
    else:
        encoding = 'utf-8-sig'
    text = data.decode(encoding)
    if '\x00' in text:
        raise ValueError('NUL characters are not accepted XML input')
    if re.search(r'<!\s*(?:DOCTYPE|ENTITY)\b', text, re.IGNORECASE):
        raise ValueError('DTD and entity declarations are not accepted research inputs')
    parser = ET.XMLPullParser(events=('start', 'end'))
    root = None
    nodes = 0
    depth = 0
    for offset in range(0, len(data), 64 * 1024):
        parser.feed(data[offset:offset + 64 * 1024])
        for event, element in parser.read_events():
            if event == 'start':
                nodes += 1
                depth += 1
                if root is None:
                    root = element
                if nodes > MAX_XML_NODES:
                    raise ValueError('XML exceeds the declared node budget')
                if depth > MAX_XML_DEPTH:
                    raise ValueError('XML exceeds the declared depth budget')
            else:
                depth -= 1
    parser.close()
    if root is None:
        raise ValueError('XML input is empty')
    return root


def validate_xlsx(path):
    require_runtime()
    path = bounded_input(path)
    with ZipFile(path) as archive:
        entries = archive.infolist()
        if len(entries) > MAX_ZIP_ENTRIES or len({e.filename for e in entries}) != len(entries):
            raise ValueError('XLSX entry count or duplicate member name is invalid')
        if sum(e.file_size for e in entries) > MAX_ZIP_EXPANDED_BYTES:
            raise ValueError('XLSX exceeds the declared expanded byte budget')
        for entry in entries:
            name = PurePosixPath(entry.filename)
            if (name.is_absolute() or '..' in name.parts or '\\' in entry.filename
                    or stat.S_ISLNK(entry.external_attr >> 16) or entry.flag_bits & 1):
                raise ValueError('Unsafe XLSX archive member')
            if (entry.file_size > MAX_ZIP_MEMBER_BYTES
                    or entry.file_size > MAX_ZIP_RATIO * max(entry.compress_size, 1)
                    or entry.compress_type not in {ZIP_STORED, ZIP_DEFLATED}):
                raise ValueError('XLSX member exceeds the declared size/compression budget')
    return path


def read_xml_member(archive, name):
    with archive.open(name) as stream:
        data = stream.read(MAX_XML_BYTES + 1)
    return parse_bounded_xml(data)


def _parent_descriptor(path):
    path = Path(path)
    if os.name != 'posix' or path.parent.is_symlink():
        raise FileExistsError('Link-safe writes require a plain POSIX output directory')
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    info = os.fstat(descriptor)
    if info.st_uid != os.getuid() or info.st_mode & 0o022:
        os.close(descriptor)
        raise PermissionError('Output directory must be owned by this user and not writable by other users')
    return descriptor


def _leaf_info(descriptor, name):
    try:
        info = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode):
        raise FileExistsError('Output file is a link or non-regular file: ' + name)
    return info


def _read_at(descriptor, name):
    stream = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
    try:
        if not stat.S_ISREG(os.fstat(stream).st_mode):
            raise FileExistsError('Output snapshot is not a regular file: ' + name)
        with os.fdopen(stream, 'rb', closefd=False) as handle:
            return handle.read()
    finally:
        os.close(stream)


def write_immutable_payloads(payloads, label):
    parents = {Path(p).parent for p in payloads}
    if len(parents) != 1 or len({Path(p).name for p in payloads}) != len(payloads):
        raise ValueError('Immutable payloads must have distinct names in one directory')
    descriptor = _parent_descriptor(next(iter(payloads)))
    try:
        present = {}
        for path, data in payloads.items():
            name = Path(path).name
            present[name] = _leaf_info(descriptor, name) is not None
            if present[name] and _read_at(descriptor, name) != data:
                raise FileExistsError(f'immutable {label} file differs: {path}; use a new output directory')
        for path, data in payloads.items():
            name = Path(path).name
            if not present[name]:
                stream = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                 0o600, dir_fd=descriptor)
                with os.fdopen(stream, 'wb') as handle:
                    handle.write(data)
    finally:
        os.close(descriptor)


def atomic_json(path, value):
    path = Path(path)
    data = (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8')
    descriptor = _parent_descriptor(path)
    temporary = '.' + path.name + '.' + secrets.token_hex(16) + '.tmp'
    created = False
    try:
        _leaf_info(descriptor, path.name)
        stream = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=descriptor)
        created = True
        with os.fdopen(stream, 'wb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path.name, src_dir_fd=descriptor, dst_dir_fd=descriptor)
        created = False
    finally:
        if created:
            os.unlink(temporary, dir_fd=descriptor)
        os.close(descriptor)


def verify_original_inventory(project, roots):
    inventory = json.loads((Path(project) / 'docs/ORIGINAL_DATA_REQUIREMENTS_2026-10-06.json').read_text())
    for entry in inventory['inputs']:
        root = Path(roots[entry['input_root']]).resolve()
        path = (root / entry['relative_path']).resolve()
        if not path.is_relative_to(root):
            raise ValueError('Original input escapes its declared root')
        bounded_input(path)
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
        if digest.hexdigest() != entry['sha256']:
            raise ValueError('Original input checksum mismatch: ' + path.name)
    return len(inventory['inputs'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-runtime', action='store_true', required=True)
    parser.parse_args()
    print(json.dumps(require_runtime(), indent=2))
