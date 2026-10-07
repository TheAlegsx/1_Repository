# Installation

The corrected reconstruction targets Python 3.12.15+ in the 3.12 series, patched OpenSSL (3.5.9+ in the tested branch) and Expat 2.9.0+. The workflow checks the actual linked versions and all locked distributions before reading originals. The demonstrated platform is macOS ARM64; other platforms have not been verified. Previous successful environments remain historical evidence.

## Prepare the reviewed interpreter

If you already have an interpreter that passes the runtime check below, use it. Otherwise, on macOS ARM64 with Apple Command Line Tools and a trusted bootstrap Python/CA bundle, run:

```sh
python3 tools/build_reviewed_runtime.py
```

This compiles pinned, hash-verified Python/OpenSSL/Expat sources into a **new dedicated project cache** at `~/.cache/msci-world-factor-strategy/runtime-20261006`. It does not replace system Python, Codex or another project. Native build paths cannot contain whitespace; the dedicated cache keeps them separate from human-readable repository folder names. Existing destinations are refused. Use `--output` for another new directory under that project cache. Logs and source archives remain there, outside Git. The script retains TLS verification and never executes a downloaded installer script.

## Create the isolated environment

From this project root, using that reviewed interpreter:

```sh
~/.cache/msci-world-factor-strategy/runtime-20261006/python/bin/python3.12 src/factor_portfolio/security_io.py --check-runtime
~/.cache/msci-world-factor-strategy/runtime-20261006/python/bin/python3.12 -m venv --without-pip .venv
python3 tools/bootstrap_verified_pip.py --python .venv/bin/python --download-directory local/installer-bootstrap
.venv/bin/python -m pip install --require-hashes --only-binary=:all: -r requirements-security-lock.txt
.venv/bin/python -m pip install --no-deps --no-build-isolation -e .
.venv/bin/python -m pip check
.venv/bin/python examples/synthetic_demo.py
.venv/bin/python -m pytest -p no:cacheprovider
```

The installer bootstrap loads only the reviewed `pip 26.2.1` wheel after checking its exact hash and size. It targets an explicit project venv and does not call an older `ensurepip` or `get-pip` installer. The complete 31-distribution lock includes numerical, plotting, reader/layout, renderer and test packages and is hash-enforced for the demonstrated CPython 3.12/macOS ARM64 wheels. Earlier partial locks are retained as historical configuration references; use the complete security lock for reconstruction.

PDF generation needs locally licensed Times New Roman regular/bold/italic/bold-italic fonts. On the verified Mac they are under `/System/Library/Fonts/Supplemental`. Use `--font-directory` for another licensed directory, or `--no-pdf` to generate complete evidence and Markdown reports without rendering fonts. Font binaries are not distributed.

[Security controls and limits](docs/SECURITY.md) · [Original-data requirements](data/README.md) · [Complete reconstruction](REPRODUCE.md)
