# Assessment entrypoint verification

Verified on 7 October 2026. The [start guide](ASSESSOR_START.md) documents the new `tools/run_assessment.py` wrapper. It calls the existing calculation workflow without changing financial code, configurations, original-data requirements, reference values or either published report.

## Tested source and layout

The candidate used an export of actual GitHub snapshot `57e77db732e4d73c41c4e34fa96b37cde47bf3a9`, with the new wrapper, its tests, start guide and reproduction-guide insertion. The package had a `Code/` directory and sibling `Inputs/`; no author-specific data paths were supplied. All 25 unchanged original files were located through the relative companion metadata and checked against the public inventory.

The previously prepared isolated, reviewed macOS ARM64 environment was reused: Python 3.12.15, linked OpenSSL 3.5.9, Expat 2.9.0 and all 31 locked distributions. This was an entrypoint integration test, not another new native build or a Windows/Linux installation test.

## Results

| Check | Outcome |
| --- | --- |
| Focused wrapper, reconstruction-guard and security tests | 44 passed, including 15 new wrapper refusal/relocation cases |
| Actual 25-input preflight | Passed; check-only left source/preparation files unchanged and created no requested output |
| Packet relocation, changed/missing files, linked roots/files, altered inventory, private-data repository boundary | Tested; invalid cases rejected before writing local paths or results |
| Output traversal, symbolic-link destinations, shared writable parents and existing outputs | Tested; rejected, with existing/victim files preserved |
| FIFO metadata hashing | Rejected without blocking |
| Full wrapper reconstruction | All fourteen jobs and 598 reviewed CSV checks passed |
| Report evidence binding | Complete evidence, reader manuscripts and selected figures matched unchanged reviewed references |
| Generated PDFs | All 23 pages matched public text, rendered pixels at 110 dpi and link targets; relative companion links resolved |
| PDF active content | No attached files, document/page automatic actions or unsupported link actions found |
| Readable result | `ASSESSMENT_SUMMARY.md` generated with navigation to reports, evidence, checks and logs |

The successful integration run has reader ID `40c9ec6d-7289-4a3d-bfea-5465ef70ce97`. The reviewed reconstruction reference remains `9e1dc7cf6f956e4175480bc0eb875ae732d59e0fe78a6c8cd83e5fb3dda5c1e8`.

PDF binary hashes changed with render metadata. Unchanged content was checked directly; expected PDF bytes or scientific references were not adjusted to make the test pass. The existing reader's separate visual-review marker remains conservative, and the equality check supplements the earlier inspection of the published layout.

## Remaining scope

This closes the local technical start-workflow block for the documented Mac environment. The final frozen delivery archive still needs an extraction/start check, actual required video/slides, the recipient's supported setup and an established private data-provision basis. No complete final submission or provider-rights clearance is claimed. Original inputs, private test outputs and internal author notes are excluded from GitHub.

[Reconstruction](../REPRODUCE.md) · [Original-data inventory](ORIGINAL_DATA_REQUIREMENTS_2026-10-06.json)
