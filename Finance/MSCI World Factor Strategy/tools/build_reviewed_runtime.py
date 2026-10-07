"""Build the pinned runtime only inside a new dedicated project cache directory.

Verified source archives are extracted manually with contained paths. Compiler
commands are argument lists, and every installation prefix stays in that directory.
Only the demonstrated macOS ARM64 recipe is supported here.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import ssl
import subprocess
import tarfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
CACHE = Path.home() / '.cache/msci-world-factor-strategy'


def extract(archive, directory):
    with tarfile.open(archive, 'r:*') as source:
        members = source.getmembers()
        if len(members) > 30_000 or sum(m.size for m in members) > 1024 ** 3:
            raise ValueError('Runtime source archive exceeds the reviewed budget')
        for member in members:
            name = Path(member.name)
            target = directory / name
            if name.is_absolute() or '..' in name.parts or not target.resolve().is_relative_to(directory):
                raise ValueError('Runtime source archive path escapes destination')
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.extractfile(member) as inp, target.open('xb') as output:
                    shutil.copyfileobj(inp, output)
                target.chmod(member.mode & 0o755)
            elif not (member.issym() or member.islnk()):
                raise ValueError('Unsupported source archive entry')
        # Links are created last so extraction cannot write through an archive link.
        for member in members:
            if member.issym() or member.islnk():
                target = directory / member.name
                link = Path(member.linkname)
                resolved = (target.parent / link if member.issym() else directory / link).resolve()
                if link.is_absolute() or not resolved.is_relative_to(directory) or not resolved.exists():
                    raise ValueError('Runtime archive link escapes destination')
                if member.issym(): target.symlink_to(member.linkname)
                else: os.link(resolved, target)


def build(output, archive_cache=None):
    output = Path(output).resolve()
    if (platform.system(), platform.machine()) != ('Darwin', 'arm64'):
        raise RuntimeError('This source recipe has only been verified on macOS ARM64')
    if (output.exists() or not output.is_relative_to(CACHE.resolve())
            or output == CACHE.resolve() or any(c.isspace() for c in str(output))):
        raise ValueError('Choose a new whitespace-free runtime directory under the dedicated project cache')
    metadata = json.loads((ROOT / 'config/security_runtime_sources_2026-10-06.json').read_text())
    output.mkdir(parents=True, mode=0o700)
    sources, logs = output / 'sources', output / 'logs'
    sources.mkdir(); logs.mkdir()
    for artifact in metadata['sources']:
        archive = sources / artifact['name']
        digest = hashlib.sha256()
        cached = Path(archive_cache) / artifact['name'] if archive_cache else None
        inp = cached.open('rb') if cached and cached.is_file() else urllib.request.urlopen(artifact['url'], timeout=30)
        with inp, archive.open('xb') as dest:
            while block := inp.read(1024 * 1024): digest.update(block); dest.write(block)
        if digest.hexdigest() != artifact['sha256']:
            raise ValueError('Runtime source checksum mismatch: ' + artifact['name'])
        extract(archive, sources)
    deps, prefix = output / 'deps', output / 'python'
    environment = os.environ.copy()
    environment.update(CC='clang', CXX='clang++', lt_cv_sys_max_cmd_len='32768')
    completed = []
    def execute(name, command, cwd, env=environment):
        print('Building ' + name, flush=True)
        started = time.monotonic()
        with (logs / (name + '.log')).open('xb') as log:
            subprocess.run(command, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT,
                           timeout=1800, check=True)
        completed.append({'step': name, 'seconds': round(time.monotonic() - started, 2)})
    expat = sources / 'expat-2.9.0'
    execute('expat-configure', ['./configure', '--prefix=' + str(deps), '--without-docbook',
            '--without-tests', '--without-examples', '--enable-shared'], expat)
    execute('expat-compile', ['make', '-j4'], expat)
    execute('expat-install', ['make', 'install'], expat)
    openssl = sources / 'openssl-3.5.9'
    execute('openssl-configure', ['./Configure', 'darwin64-arm64-cc', '--prefix=' + str(deps),
            '--openssldir=' + str(deps / 'ssl'), 'no-tests', 'shared'], openssl)
    execute('openssl-compile', ['make', '-j4'], openssl)
    execute('openssl-install', ['make', 'install_sw'], openssl)
    certificates = ssl.get_default_verify_paths().cafile
    if not certificates or not Path(certificates).is_file():
        raise RuntimeError('Supply a trusted CA bundle to the bootstrap interpreter; TLS verification is not disabled')
    (deps / 'ssl').mkdir(exist_ok=True)
    shutil.copyfile(certificates, deps / 'ssl/cert.pem')
    pyenv = environment.copy()
    # New Apple SDK headers advertise functions absent on older macOS releases.
    # Use the normal portable fallbacks rather than creating weak null calls.
    pyenv.update(ac_cv_func_pipe2='no', ac_cv_func_dup3='no', MACOSX_DEPLOYMENT_TARGET='11.0',
        CFLAGS='-O2 -mmacosx-version-min=11.0 -Werror=unguarded-availability-new',
        CPPFLAGS='-I' + str(deps / 'include') + ' -mmacosx-version-min=11.0',
        LDFLAGS='-L' + str(deps / 'lib') + ' -Wl,-rpath,' + str(deps / 'lib') + ' -mmacosx-version-min=11.0',
        PKG_CONFIG_PATH=str(deps / 'lib/pkgconfig'), EXPAT_CFLAGS='-I' + str(deps / 'include'),
        EXPAT_LIBS='-L' + str(deps / 'lib') + ' -lexpat')
    python = sources / 'Python-3.12.15'
    execute('python-configure', ['./configure', '--prefix=' + str(prefix),
            '--with-openssl=' + str(deps), '--with-openssl-rpath=auto',
            '--with-system-expat', '--with-ensurepip=no'], python, pyenv)
    execute('python-compile', ['make', '-j4'], python, pyenv)
    execute('python-install', ['make', 'install'], python, pyenv)
    interpreter = prefix / 'bin/python3.12'
    subprocess.run([str(interpreter), '-B', str(ROOT / 'src/factor_portfolio/security_io.py'),
                    '--check-runtime'], check=True, timeout=30)
    subprocess.run([str(interpreter), '-c',
        'import sys,subprocess;subprocess.run([sys.executable,"-c","print(123)"],capture_output=True,check=True)'],
        check=True, timeout=30)
    (output / 'build_checks.json').write_text(json.dumps({'sources': metadata['sources'],
        'completed': completed, 'runtime_version_guard': 'passed', 'subprocess_smoke_test': 'passed',
        'global_installation': False}, indent=2) + '\n')
    print('Reviewed interpreter: ' + str(interpreter))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=CACHE / 'runtime-20261006')
    parser.add_argument('--archive-cache', type=Path, help='Optional existing source archives; every hash is still checked')
    args = parser.parse_args()
    build(args.output, args.archive_cache)
