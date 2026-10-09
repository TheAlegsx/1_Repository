# Reconstruct both research reports

Run from this project root after[installation](SETUP.md). The command reconstructs every required calculation from separately supplied original files. It requires no saved result folders, original working-project code or network data feed.

## Assessment package shortcut

For an author-prepared private package with `Code/` and sibling `Inputs/`, use [the assessment start guide](docs/ASSESSOR_START.md). After installation, `python tools/run_assessment.py` automatically verifies and locates the originals, invokes this same workflow and writes an outcome summary. The manual local-input route remains available below.

## Supply the originals locally

Match the filenames and SHA-256 pins in[the original-data inventory](docs/ORIGINAL_DATA_REQUIREMENTS_2026-10-06.json). Create `local/input_roots.json` yourself; it is ignored by Git. Values should be absolute paths to your local folders:

```json
{
  "raw_root": "/absolute/path/to/market-and-rate-files",
  "annual_raw_root": "/absolute/path/to/core-annual-pdfs",
  "factor_annual_raw_root": "/absolute/path/to/factor-annual-pdfs",
  "dimensional_annual_raw_root": "/absolute/path/to/dimensional-pdfs",
  "collateral_raw_root": "/absolute/path/to/collateral-evidence",
  "custody_raw_root": "/absolute/path/to/custody-evidence"
}
```

Several roots may point to the same folder if it contains the specified files. Keep originals outside the tracked tree. Do not upload them merely to run this code.

## Run the common workflow

```sh
.venv/bin/python -m factor_portfolio.publication_reproduce   --input-roots local/input_roots.json   --output outputs/my-reconstruction
```

Choose a new output directory for every attempt. An existing directory is rejected. To omit only PDF generation, append `--no-pdf`; the complete calculations and Markdown reports still run. For another font location append `--font-directory /absolute/path/to/fonts`.

The workflow executes fourteen evidence producers: main accounts; extended financing/entry/rolling/margin/artificial/product/correlation/holdings analyses; endpoint, allocation and comparator controls; custody/collateral; hindsight; issuer validation; independent accounting; joint costs; funding/gap diagnostics; hypothetical inflows; historical investor/manager diagnostics; and historical interpretation. The[recipe](config/reproduction_recipe_2026-10-06.json) records their configurations and dependencies.

## Checks and outputs

Every job verifies its seals, exact captured configurations and the full expected CSV inventory against[reviewed reference checksums](config/reproduction_reference_2026-10-06.json). The complete table/claim evidence, manuscripts and selected figure data/bitmaps are then checked. The separate frozen paired robustness study then regenerates 56 matched endpoint comparisons and 10,000 conditional bootstrap draws, checking all its artifacts against its own exact reference. Only after equality is established does the workflow create new reader-selection/review sidecars with the actual new run identity. Published source files remain unchanged. A missing, changed or non-equivalent result stops the workflow; it does not silently change parameters or disable report guards.

Look inside your output directory:

| Location | Result |
| --- | --- |
| `logs/` and fourteen named job folders | Calculation logs, data-derived outputs and manifests |
| `robustness/` | Frozen 56-pair matrix, 112 accounts/events, 10,000 bootstrap draws and exact checks |
| `complete_reports/` | Full 52-family research evidence and linked complete reports |
| `reader_binding/` | Checked sidecars for this actual run |
| `readers/report/` | Concise backtest and inflow Markdown reports |
| `pdf/` | Both PDFs and their AI-use evidence record, when enabled |
| `reconstruction_checks.json` | Run outcome and checksum comparison scope |

PDF metadata may change between renders. Manuscripts, table cells and figure data must match; compare extracted text and rendered pages rather than expecting identical PDF bytes. PDF visual review is recorded separately from successful numerical reconstruction.

This is reconstruction of the recorded research with matching inputs, not an experiment with different datasets or assumptions. For exploratory changes, use the component configurations and numerical modes, then renew interpretation/reference evidence after review. Do not update checksums merely to accept an unexplained difference.

The[verification record](docs/VERIFICATION.md) distinguishes the local clean-install test from the later experiment using an actually published GitHub revision.

The frozen paired study and its scope are documented in [the result record](docs/PAIRED_ROBUSTNESS_RESULTS_2026-10-09.md). Its exact study reference remains separate from the preserved original numerical references.
