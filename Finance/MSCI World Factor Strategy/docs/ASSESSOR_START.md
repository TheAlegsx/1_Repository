# Start an assessment reconstruction

This wrapper uses the existing reviewed calculation workflow. It adds automatic input location, preflight checks, a new output folder and a readable outcome summary. It changes no financial rule or reference value.

## Package layout

```text
Assessment/
├── Code/                 Frozen export of this GitHub project
│   ├── tools/run_assessment.py
│   ├── src/, config/, reports/, docs/, ...
│   └── .venv/            Created locally after extraction; never distributed
└── Inputs/               Eligible private originals supplied by the authors
    ├── PACKAGE_INFO.json
    ├── ORIGINAL_DATA_REQUIREMENTS.json
    └── originals/        Six package-relative input roots, 25 unchanged files
```

The authors assemble the input companion to match the public [original-file inventory](ORIGINAL_DATA_REQUIREMENTS_2026-10-06.json). Its `PACKAGE_INFO.json` specifies the six relative roots, the 25-file count and pins for the public inventory, recipe, reference checks, full dependency lock and common reconstruction module. The companion inventory must equal the public inventory. This is a technical format, not a grant of third-party data rights. Inputs stay outside the downloaded repository or `Code/` folder.

## Start

Complete [installation](../SETUP.md) once in `Code/`. From `Code/`:

```sh
.venv/bin/python tools/run_assessment.py --check-only
.venv/bin/python tools/run_assessment.py
```

The first command checks the original files, source pins, installed lock, linked Python/native runtime and requested PDF fonts without writing files or calculating. The second command performs the same checks, prepares an ignored local mapping, executes all fourteen calculation jobs and checks all 598 reference CSV hashes and report evidence. It then prints the location of `ASSESSMENT_SUMMARY.md`. Open it to reach the regenerated manuscripts, PDFs, detailed evidence and logs.

Each run receives a new name below `outputs/`. Existing outputs are refused and never replaced. A preparation folder below ignored `local/` holds the mapping/preflight and a writable plotting cache. No manual editing of data paths is needed in the packaged layout. A failed calculation retains its logs and does not receive a success summary. Numerical success does not replace PDF visual review.

For the existing separately supplied original-data companion, choose its folder explicitly:

```sh
.venv/bin/python tools/run_assessment.py --data /path/to/MSCI_World_Factor_Strategy_Private_Data
```

Quote paths that contain spaces. Optional arguments:

| Argument | Purpose |
| --- | --- |
| `--check-only` | Verify inputs/environment/fonts without writes or calculations |
| `--output outputs/my-new-run` | Use a named new output directory |
| `--font-directory /path/to/licensed/fonts` | Supply the four Times New Roman fonts required by the renderer |
| `--no-pdf` | Run all calculations and generate Markdown reports without PDF rendering |

## Scope

The complete installation/calculation route has been demonstrated on macOS ARM64. This entrypoint uses the project's POSIX filesystem protections; it does not establish Windows support. Linux installation and recipient-specific setup remain unverified. The wrapper performs no installation, network download or upload and does not run a synthetic replacement for the research inputs. The native runtime, environment and licensed font binaries are not bundled.

The authors must establish the applicable private data-provision basis before delivering a complete assessment package. Video and required slide material are assembled separately. A locally tested technical candidate is not a final submission.

[Full calculation workflow](../REPRODUCE.md) · [Security controls](SECURITY.md)
