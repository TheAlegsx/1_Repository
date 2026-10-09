# Frozen paired robustness results — 9 October 2026

Paired study extends the research baseline `b0864758c7f33c7001e3a09afb3d1a647f66c534`. The report links pin the calculation code to its exact GitHub snapshot. The primary investment specification, original engine files and existing 14 numerical job references remain unchanged.

## What the evidence says

The original factor and Core accounts reproduce exactly: both ending equities, all 2,929 wealth observations, transaction/financing totals and post-entry events. The rounded display-return CSV initially differed by less than USD 0.001 at the endpoint. Recomputing its returns from the frozen NAV levels reproduces the original in-memory calculation exactly, without changing inputs or tolerances.

All 14 available OAT cases retain a positive terminal CAGR gap (0.168 to 0.475 percentage points per year). Every case is negative at the 2023 and 2024 endpoints. At the end of 2025, five are positive and nine negative. The result remains strongly endpoint-dependent.

The paired conditional stationary bootstrap intervals both include zero: mean block 20, -0.728 to +1.636 pp; mean block 60, -0.662 to +1.743 pp. Under this specified resampling model, the realised advantage is not statistically separated from zero. These intervals condition on existing strategy returns; they do not regenerate threshold decisions or correct specification selection.

Tracking error is 1.971% annualised and the descriptive information ratio is 0.160. Parameter ranges are specification sensitivity, not sampling probabilities. No variant was selected as a new primary strategy.

## Endpoint summaries

| end | available_pairs | baseline_gap_pp | median_gap_pp | minimum_gap_pp | maximum_gap_pp | positive_pairs | negative_pairs | zero_pairs |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2023-12-29 | 14 | -0.140134 | -0.142695 | -0.336296 | -0.063467 | 0 | 14 | 0 |
| 2024-12-31 | 14 | -0.240088 | -0.241920 | -0.471836 | -0.180684 | 0 | 14 | 0 |
| 2025-12-31 | 14 | -0.006564 | -0.007583 | -0.291845 | 0.048939 | 5 | 9 | 0 |
| 2026-08-28 | 14 | 0.418960 | 0.422758 | 0.167677 | 0.474544 | 14 | 0 | 0 |

## Conditional bootstrap

| block_length | replications | seed | observed_gap_pp | median_gap_pp | mean_gap_pp | ci_low_pp | ci_high_pp | standard_deviation_pp | ci_includes_zero |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 20 | 5000 | 2026100920 | 0.418960 | 0.432714 | 0.437719 | -0.728453 | 1.636438 | 0.604775 | True |
| 60 | 5000 | 2026100960 | 0.418960 | 0.394897 | 0.425771 | -0.662195 | 1.743283 | 0.605321 | True |

## Every available pair

The matrix reports all available variants and four endpoints. Counts exclude the opening investment. Five earlier starts lack admitted input data and remain unavailable; no earlier dates or synthetic returns were invented. Changes are one at a time, not a factorial grid. Core has no factor sleeve rule.

| case_id | start | end | factor_cagr | core_cagr | cagr_gap_pp | factor_post_entry_events | core_post_entry_events |
| --- | --- | --- | --- | --- | --- | --- | --- |
| baseline | 2014-10-03 | 2023-12-29 | 0.098842 | 0.100243 | -0.140134 | 2 | 1 |
| baseline | 2014-10-03 | 2024-12-31 | 0.108302 | 0.110703 | -0.240088 | 2 | 1 |
| baseline | 2014-10-03 | 2025-12-31 | 0.121838 | 0.121904 | -0.006564 | 2 | 1 |
| baseline | 2014-10-03 | 2026-08-28 | 0.132436 | 0.128247 | 0.418960 | 2 | 1 |
| start_+1 | 2014-10-06 | 2023-12-29 | 0.098934 | 0.099986 | -0.105216 | 2 | 1 |
| start_+1 | 2014-10-06 | 2024-12-31 | 0.108322 | 0.110478 | -0.215597 | 2 | 1 |
| start_+1 | 2014-10-06 | 2025-12-31 | 0.121916 | 0.121705 | 0.021150 | 2 | 1 |
| start_+1 | 2014-10-06 | 2026-08-28 | 0.132573 | 0.128062 | 0.451105 | 2 | 1 |
| start_+2 | 2014-10-07 | 2023-12-29 | 0.100680 | 0.101742 | -0.106164 | 2 | 1 |
| start_+2 | 2014-10-07 | 2024-12-31 | 0.109887 | 0.112033 | -0.214625 | 2 | 1 |
| start_+2 | 2014-10-07 | 2025-12-31 | 0.123328 | 0.123090 | 0.023814 | 2 | 1 |
| start_+2 | 2014-10-07 | 2026-08-28 | 0.133898 | 0.129352 | 0.454599 | 2 | 1 |
| start_+3 | 2014-10-08 | 2023-12-29 | 0.099524 | 0.100528 | -0.100374 | 2 | 1 |
| start_+3 | 2014-10-08 | 2024-12-31 | 0.108863 | 0.110976 | -0.211302 | 2 | 1 |
| start_+3 | 2014-10-08 | 2025-12-31 | 0.122422 | 0.122169 | 0.025325 | 2 | 1 |
| start_+3 | 2014-10-08 | 2026-08-28 | 0.133060 | 0.128506 | 0.455454 | 2 | 1 |
| start_+4 | 2014-10-09 | 2023-12-29 | 0.101509 | 0.102439 | -0.092945 | 2 | 1 |
| start_+4 | 2014-10-09 | 2024-12-31 | 0.110645 | 0.112676 | -0.203077 | 2 | 1 |
| start_+4 | 2014-10-09 | 2025-12-31 | 0.124034 | 0.123691 | 0.034334 | 2 | 1 |
| start_+4 | 2014-10-09 | 2026-08-28 | 0.134576 | 0.129928 | 0.464835 | 2 | 1 |
| start_+5 | 2014-10-10 | 2023-12-29 | 0.104142 | 0.104777 | -0.063467 | 2 | 1 |
| start_+5 | 2014-10-10 | 2024-12-31 | 0.112970 | 0.114777 | -0.180684 | 2 | 1 |
| start_+5 | 2014-10-10 | 2025-12-31 | 0.126085 | 0.125595 | 0.048939 | 2 | 1 |
| start_+5 | 2014-10-10 | 2026-08-28 | 0.136466 | 0.131721 | 0.474544 | 2 | 1 |
| margin_bps_250 | 2014-10-03 | 2023-12-29 | 0.100313 | 0.101576 | -0.126248 | 2 | 1 |
| margin_bps_250 | 2014-10-03 | 2024-12-31 | 0.109632 | 0.111925 | -0.229354 | 2 | 1 |
| margin_bps_250 | 2014-10-03 | 2025-12-31 | 0.122964 | 0.122988 | -0.002476 | 2 | 1 |
| margin_bps_250 | 2014-10-03 | 2026-08-28 | 0.133411 | 0.129245 | 0.416631 | 2 | 1 |
| margin_bps_350 | 2014-10-03 | 2023-12-29 | 0.095248 | 0.096776 | -0.152765 | 3 | 2 |
| margin_bps_350 | 2014-10-03 | 2024-12-31 | 0.104406 | 0.106879 | -0.247217 | 3 | 2 |
| margin_bps_350 | 2014-10-03 | 2025-12-31 | 0.117466 | 0.117707 | -0.024159 | 3 | 2 |
| margin_bps_350 | 2014-10-03 | 2026-08-28 | 0.128470 | 0.124155 | 0.431492 | 4 | 3 |
| fund_fee_bps_2.5 | 2014-10-03 | 2023-12-29 | 0.098624 | 0.100076 | -0.145255 | 2 | 1 |
| fund_fee_bps_2.5 | 2014-10-03 | 2024-12-31 | 0.108086 | 0.110523 | -0.243753 | 2 | 1 |
| fund_fee_bps_2.5 | 2014-10-03 | 2025-12-31 | 0.121631 | 0.121717 | -0.008601 | 2 | 1 |
| fund_fee_bps_2.5 | 2014-10-03 | 2026-08-28 | 0.132237 | 0.128057 | 0.418018 | 2 | 1 |
| fund_fee_bps_5 | 2014-10-03 | 2023-12-29 | 0.096429 | 0.099792 | -0.336296 | 3 | 1 |
| fund_fee_bps_5 | 2014-10-03 | 2024-12-31 | 0.105544 | 0.110262 | -0.471836 | 3 | 1 |
| fund_fee_bps_5 | 2014-10-03 | 2025-12-31 | 0.118564 | 0.121482 | -0.291845 | 3 | 1 |
| fund_fee_bps_5 | 2014-10-03 | 2026-08-28 | 0.129515 | 0.127838 | 0.167677 | 4 | 1 |
| leverage_band_0.09 | 2014-10-03 | 2023-12-29 | 0.099485 | 0.100972 | -0.148670 | 2 | 1 |
| leverage_band_0.09 | 2014-10-03 | 2024-12-31 | 0.108748 | 0.111190 | -0.244132 | 2 | 1 |
| leverage_band_0.09 | 2014-10-03 | 2025-12-31 | 0.122062 | 0.122163 | -0.010101 | 2 | 1 |
| leverage_band_0.09 | 2014-10-03 | 2026-08-28 | 0.132517 | 0.128385 | 0.413260 | 2 | 1 |
| leverage_band_0.11 | 2014-10-03 | 2023-12-29 | 0.095618 | 0.097176 | -0.155826 | 3 | 2 |
| leverage_band_0.11 | 2014-10-03 | 2024-12-31 | 0.104830 | 0.107328 | -0.249805 | 3 | 2 |
| leverage_band_0.11 | 2014-10-03 | 2025-12-31 | 0.117904 | 0.118173 | -0.026918 | 3 | 2 |
| leverage_band_0.11 | 2014-10-03 | 2026-08-28 | 0.128560 | 0.124295 | 0.426556 | 4 | 3 |
| sleeve_band_0.045 | 2014-10-03 | 2023-12-29 | 0.098692 | 0.100243 | -0.155113 | 2 | 1 |
| sleeve_band_0.045 | 2014-10-03 | 2024-12-31 | 0.108229 | 0.110703 | -0.247367 | 2 | 1 |
| sleeve_band_0.045 | 2014-10-03 | 2025-12-31 | 0.121668 | 0.121904 | -0.023526 | 2 | 1 |
| sleeve_band_0.045 | 2014-10-03 | 2026-08-28 | 0.132148 | 0.128247 | 0.390131 | 2 | 1 |
| sleeve_band_0.055 | 2014-10-03 | 2023-12-29 | 0.097220 | 0.100243 | -0.302313 | 1 | 1 |
| sleeve_band_0.055 | 2014-10-03 | 2024-12-31 | 0.108119 | 0.110703 | -0.258384 | 1 | 1 |
| sleeve_band_0.055 | 2014-10-03 | 2025-12-31 | 0.120784 | 0.121904 | -0.111999 | 1 | 1 |
| sleeve_band_0.055 | 2014-10-03 | 2026-08-28 | 0.130502 | 0.128247 | 0.225511 | 1 | 1 |

## Calculation and reproduction

- [Calculation module](../src/factor_portfolio/paired_robustness.py): `run_account`, `outcome`, `bootstrap`, `stationary_draws`, `run`.
- [Reader cells](../src/factor_portfolio/robustness_reader_diagnostics.py): original values, displayed rounding, source hashes and row selectors.
- [Frozen protocol](ROBUSTNESS_PROTOCOL_2026-10-09.md) and [machine protocol](../config/paired_robustness_protocol_2026-10-09.json).
- [Exact study reference](../config/paired_robustness_reference_2026-10-09.json) pins every generated account/event/fee calendar, summary and bootstrap draw.
- [Common reconstruction](../REPRODUCE.md) now executes the separately sealed study after the 14 original producers and before revised reader binding.

In the private reconstruction package, `Calculations/Robustness/` supplies the complete sealed study. The code recalculates it from originals; saved study results are not required as inputs. The PDF calculation links open [the exact paired-study code](https://github.com/TheAlegsx/1_Repository/blob/1d3dcd6fa63024174a5854d37292f08002c3d67d/Finance/MSCI%20World%20Factor%20Strategy/src/factor_portfolio/paired_robustness.py#L167). The same file is included locally under `Code/src/factor_portfolio/paired_robustness.py`. Older links retain their fixed calculation snapshots.

## Scope and limitations

The protocol was frozen after prior results and fee feedback were known, before the new matrix and bootstrap. It is not pristine preregistration or a holdout. Monthly no-client sensitivity fees include the frozen terminal stub convention. The original 120-month historical inflow experiment and fee-free baseline are unchanged. The second-NAV timing experiment was not run and is excluded from all counts and intervals. No new attribution, factor regression, dataset extension or optimisation was added.
