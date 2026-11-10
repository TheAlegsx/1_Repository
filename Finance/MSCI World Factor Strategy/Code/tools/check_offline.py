"""Verify the documented macOS offline profile before running the backtest."""

import errno
from pathlib import Path
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory


def connect(port):
    return socket.create_connection(('127.0.0.1', port), timeout=2)


def check_denials(home, control_file, port):
    def tcp_probe():
        with connect(port):
            pass

    for label, probe in (
        ('personal folder', lambda: list(home.iterdir())),
        ('file outside the review directory', control_file.read_bytes),
        ('TCP connection to the live listener', tcp_probe),
    ):
        try:
            probe()
        except OSError as exc:
            if exc.errno not in (errno.EPERM, errno.EACCES):
                raise
            print(f'{label}: access denied', flush=True)
        else:
            raise SystemExit(f'{label}: access unexpectedly allowed')

    Path(__file__).read_bytes()
    print('file inside the review directory: read allowed', flush=True)


def check_profile(review_root, home):
    package = Path(__file__).resolve().parents[2]
    offline_home = review_root / 'offline-home'
    with TemporaryDirectory(prefix='msci-offline-control.', dir='/private/tmp') as directory:
        control_file = Path(directory) / 'probe.txt'
        control_file.write_bytes(b'offline control\n')
        if control_file.read_bytes() != b'offline control\n':
            raise RuntimeError('Could not read the control file outside the review directory')
        print('file outside the review directory: positive control passed', flush=True)

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen(1)
            listener.settimeout(2)
            port = listener.getsockname()[1]
            with connect(port), listener.accept()[0]:
                print('local TCP listener: positive control passed', flush=True)

            subprocess.run(
                ['/usr/bin/sandbox-exec', '-D', f'REVIEW_ROOT={review_root}',
                 '-f', str(package / 'Code/tools/offline.sb'), sys.executable,
                 '-B', __file__, '--inside', str(home), str(control_file), str(port)],
                cwd=package,
                env={'HOME': str(offline_home), 'TMPDIR': str(offline_home),
                     'PATH': '/usr/bin:/bin', 'PYTHONPATH': str(package / 'Code/src')},
                check=True,
            )


if __name__ == '__main__':
    if sys.argv[1] == '--inside':
        check_denials(Path(sys.argv[2]), Path(sys.argv[3]), int(sys.argv[4]))
    else:
        check_profile(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve())
