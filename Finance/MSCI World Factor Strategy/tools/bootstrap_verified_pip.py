"""Install only the reviewed pip wheel into an explicit isolated interpreter.

The corrected installer is loaded from the hash-verified wheel itself. No old
pip/get-pip installer or unreviewed download script is executed.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def bootstrap(python, destination):
    # Preserve the venv invocation path; resolving its executable symlink would
    # silently select the base interpreter and install into the wrong environment.
    python = Path(python).absolute()
    destination = Path(destination).resolve()
    environment = python.parent.parent
    configuration = environment / 'pyvenv.cfg'
    if (not python.is_file() or not environment.resolve().is_relative_to(ROOT)
            or not configuration.is_file() or 'include-system-site-packages = false' not in configuration.read_text()
            or not destination.is_relative_to(ROOT) or destination.exists()):
        raise ValueError('Use an existing explicit interpreter and a new download directory inside this project')
    metadata = json.loads((ROOT / 'config/security_runtime_sources_2026-10-06.json').read_text())['pip_bootstrap']
    destination.mkdir(parents=True, mode=0o700)
    wheel = destination / metadata['filename']
    digest = hashlib.sha256()
    with urllib.request.urlopen(metadata['url'], timeout=30) as source, wheel.open('xb') as output:
        while block := source.read(1024 * 1024):
            digest.update(block)
            output.write(block)
    if digest.hexdigest() != metadata['sha256'] or wheel.stat().st_size != metadata['bytes']:
        raise ValueError('Reviewed installer artifact checksum/size mismatch')
    invocation = ('import runpy,sys; wheel=sys.argv.pop(1); sys.path.insert(0,wheel); '
                  'sys.argv[0]="pip"; runpy.run_module("pip",run_name="__main__")')
    subprocess.run([str(python), '-B', '-c', invocation, str(wheel), 'install',
                    '--no-index', '--no-deps', '--upgrade', str(wheel)], check=True, timeout=120)
    subprocess.run([str(python), '-m', 'pip', '--version'], check=True, timeout=30)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--python', type=Path, required=True)
    parser.add_argument('--download-directory', type=Path, required=True)
    args = parser.parse_args()
    bootstrap(args.python, args.download_directory)
