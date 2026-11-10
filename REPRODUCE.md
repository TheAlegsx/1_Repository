# Reproduce the portfolio backtest

## Reproduce

The package was tested on macOS ARM64. Use macOS 14 or later for the pinned NumPy wheel, Apple Command Line Tools with Clang and make, Perl, a bootstrap Python 3.9 or later, and a trusted CA bundle. PDF generation requires Times New Roman and Arial in `/System/Library/Fonts/Supplemental`.

### Set up the runtime and dependencies

Enter the checkout directory and set the review root to its physical path. The data paths and input SHA-256 digests are in [the results record](Evidence/results.json). Put authorized copies and the matching source manifests under `Inputs/market_data/`.

```sh
REVIEW_ROOT="$(pwd -P)"
```

Verify the public files and build the runtime. The [build helper](Code/tools/build_reviewed_runtime.py) verifies the source downloads against the [runtime manifest](Code/config/security_runtime_sources_2026-10-06.json) before compiling Python 3.12.15, OpenSSL 3.5.9 and Expat 2.9.0. These steps require internet access.

```sh
shasum -a 256 -c CHECKSUMS.sha256
BUILD_HOME="$REVIEW_ROOT/runtime-home"
mkdir "$BUILD_HOME"
BUILD_DIR="$BUILD_HOME/.cache/msci-world-factor-strategy/runtime"
HOME="$BUILD_HOME" SSL_CERT_FILE=/etc/ssl/cert.pem \
  /usr/bin/python3 -B Code/tools/build_reviewed_runtime.py --output "$BUILD_DIR"
RUNTIME="$BUILD_DIR/python/bin/python3.12"
"$RUNTIME" -m venv .venv
.venv/bin/python -m pip install -r Code/requirements.txt
.venv/bin/python -m pip check
```

The requirements file pins the wheel versions and SHA-256 hashes for the documented platform. Keep the runtime directory while using `.venv`. If Python is installed elsewhere, substitute its absolute path for `/usr/bin/python3` in the build command.

### Run offline and compare

The [macOS profile](Code/tools/offline.sb) blocks networking, personal folders under `/Users`, mounted volumes and other temporary directories. It allows the runtime to read system libraries and fonts and restricts writes to the review directory. The [offline check](Code/tools/check_offline.py) first confirms that a local TCP listener and a temporary control file outside the review directory are accessible. It then requires the profile to block both accesses and a listing of your home directory, while a read inside the package still succeeds. The calculation and comparisons run only after the check passes.

```sh
mkdir "$REVIEW_ROOT/offline-home"
offline() {
  /usr/bin/env -i HOME="$REVIEW_ROOT/offline-home" TMPDIR="$REVIEW_ROOT/offline-home" \
    PATH=/usr/bin:/bin PYTHONPATH="$PWD/Code/src" \
    /usr/bin/sandbox-exec -D "REVIEW_ROOT=$REVIEW_ROOT" -f Code/tools/offline.sb \
    .venv/bin/python -B "$@"
}

.venv/bin/python -B Code/tools/check_offline.py "$REVIEW_ROOT" "$HOME" &&
  offline Code/reproduce.py "$PWD" "$PWD/rebuilt" &&
  cmp Evidence/results.json rebuilt/Evidence/results.json &&
  cmp Evidence/paired_cases.csv rebuilt/Evidence/paired_cases.csv &&
  cmp MSCI_World_Factor_Strategy_Backtest.pdf rebuilt/MSCI_World_Factor_Strategy_Backtest.pdf
```

The run reads the local market data and writes to a new `rebuilt/` directory. The comparison commands are silent when the files match byte for byte. The PDF uses fixed build metadata. For a byte comparison, use the pinned dependencies and the documented system fonts.
