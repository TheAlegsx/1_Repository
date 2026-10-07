# Local research security controls

The reviewed workflow is a local CLI/library, not a remotely accessible application. Public source, methods and reports are intended for sharing; original provider files, installed environments, runtime caches and generated evidence remain local.

## Corrected installation

Use [the installation procedure](../SETUP.md). It checks the actual interpreter/linked OpenSSL/Expat versions, bootstraps the corrected installer from a verified wheel, and installs the complete 31-distribution hash lock. The complete reconstruction rejects missing or different locked versions before original-data processing. Hashes establish artifact equality, not a guarantee that upstream software is trustworthy or free of unknown defects.

The demonstrated runtime is Python 3.12.15 with OpenSSL 3.5.9 and Expat 2.9.0 on macOS ARM64. The pinned cryptography 50.0.2 wheel separately bundles OpenSSL 4.0.3, which the common workflow checks explicitly. The package restricts the interpreter to the reviewed Python 3.12 series. Native source/build provenance is [pinned separately](../config/security_runtime_sources_2026-10-06.json). Build tools create only a new dedicated project cache; they do not replace system/Codex interpreters. Runtime installation is explicitly invoked and uses verified sources. Research calculation modules make no provider-data network request.

## Filesystem boundaries

Output directories must be owned by the invoking user and not writable by other users. Mutable JSON manifests use randomly named exclusive temporary files and directory-descriptor atomic replacement. Snapshot writers reject links/non-regular files, preflight every existing payload, and create missing files exclusively without following links. Existing differing snapshots are refused. The common reconstruction also refuses existing output directories and resolved paths outside the project.

These controls address the reproduced temporary-file and dangling-output-link failures. They are not a sandbox for a program/user who already controls the source code or the same user account. Keep local output directories private and share an explicitly reviewed package.

## Input budgets

Every one of the 25 frozen original inputs is checked against the public metadata inventory before a common reconstruction starts. The existing job-specific source/date/currency checks remain in place. Changed or oversized inputs stop processing; data are not truncated to fit a limit.

| Boundary | Maximum / rule |
| --- | --- |
| Original/canonical source file | 64 MiB, regular file |
| Input-root configuration | 1 MiB |
| XML document/member | 16 MiB |
| XML tree | 500,000 nodes, depth 128 |
| Sparse worksheet columns | 16,384 |
| XLSX archive | 4,096 distinct members; 64 MiB total expanded |
| Individual XLSX member | 16 MiB; compression ratio at most 200 |
| Archive methods | Stored or DEFLATE only; no encryption, path traversal or archive symlinks |
| XML declarations | DTD/entity declarations refused, including alternate Unicode encodings |

The frozen originals were inspected: the largest is about 8.2 MB; the largest workbook member is below 1 MB and the largest workbook compression ratio below 8.2. These budgets provide headroom without changing observations or research parameters. The calculation subprocess also has its existing 600-second timeout. Budgets bound selected inputs; they do not provide a general operating-system memory sandbox.

The independent comparison keeps separate financial/accounting algorithms, source-column declarations and currency/calendar checks. It shares only generic runtime/input-budget utilities; a test restricts that utility to standard-library imports and prevents importing production model/readers/metrics into the independent numeric modules.

## Publication and limitations

Before publishing, check the exact selected index and Git history for credentials/private content. Ignore rules cannot remove files already tracked. Generated PDFs contain intentional clickable publisher/companion links; JavaScript, automatic launches and embedded provider files are not required. Public content can be copied permanently.

Account 2FA/sessions, OS security and a complete third-party/native-code forensic review are separate from these project controls. The recorded dependency/advisory checks apply to their execution date; future advisories require renewed review. No security certificate, institution approval or legal redistribution clearance is implied.
