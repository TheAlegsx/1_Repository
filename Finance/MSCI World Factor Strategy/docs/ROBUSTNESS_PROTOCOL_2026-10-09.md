---
status: active
doc_type: PLAN
frozen_on: 2026-10-09
---

# Paired robustness and bootstrap protocol

This protocol defines the bounded follow-up accepted by Alex on 9 October 2026. It is frozen before the new perturbation and bootstrap results. The study was designed after inspecting the historical research, so it is not a pristine preregistration or holdout. The current reports and private ZIP remain tied to public commit `b0864758c7f33c7001e3a09afb3d1a647f66c534`.

## Questions and fixed baseline

Does the factor–Core CAGR gap remain similar under small specified changes? Separately, how uncertain is the realised baseline return comparison under a defined time-series resampling model? Neither experiment selects new optimal weights or replaces the primary strategy.

Keep 60/15/10/15, USD 7 million, 1.25x target leverage, absolute 5 pp sleeve bands, separate 0.10 leverage band, 300 bp financing markup and next-common-NAV execution as the baseline. Trading/financing definitions and the original shared calendar remain unchanged. The Core control holds one sleeve at the same target leverage.

## First matrix

Change one setting at a time. Compare factor and Core under the same change.

| Dimension | Predefined alternatives |
| --- | --- |
| Start date | Minus and plus 1–5 common NAV observations; earlier cases explicitly unavailable |
| Markup above the reference rate |250 / 300 / 350 bp |
| Added annual fund fee |0 / 2.5 / 5 bp, applied to both portfolios |
| Leverage adjustment band |0.09 / 0.10 / 0.11 |
| Absolute sleeve band |4.5 / 5 / 5.5 percentage points; not applicable to single-sleeve Core |

The admitted data begin 3 October 2014. Later starts are 6, 7, 8, 9 and 10 October 2014. Do not invent earlier levels or substitute another calendar. There are 19 requested variants: 14 available and 5 unavailable. Report all requested cases. Four actual endpoints are 29 December 2023, 31 December 2024, 31 December 2025 and 28 August 2026: 56 available pairs and 112 account-endpoint outcomes. Earlier endpoints are continuing-account checkpoints, not separately selected optimisations.

For every pair record CAGR and its signed gap, intervention counts, wealth, trading/funding/fund-fee costs and observed leverage. Summarise baseline, median and range by endpoint and perturbation family. A parameter span is not a confidence interval; a positive-case fraction is not a success probability. Core can be reused where sleeve-band changes do not affect it.

## Fee timing and secondary execution check

Use the existing anniversary-month fee payment rule, charged on previous event closing net equity and funded through debt. For a cutoff between regular events, apply a terminal-only accrued fee at annual rate times elapsed calendar days/365.2425 times the previous event closing equity. Do not duplicate a regular payment. This explicit stub convention extends only this robustness study; it changes neither the original 120-month inflow account nor the zero-fee primary strategy.

Second-NAV execution is a separate timing experiment. It enters only after its implementation is independently regression-checked against unchanged default next-NAV behavior. It is excluded from the first matrix and its statistics.

## Separate conditional bootstrap

Use the full-period baseline factor 1.25 / Core 1.25 realised return pair. Apply paired stationary circular-block resampling with expected block lengths 20 and 60 common-NAV intervals, 5,000 replicates each and fixed seeds recorded in `PROTOCOL.json`. Do not choose a block length after seeing its interval.

Hold the original opening-cost factor fixed once. Resample only adjacent post-entry net equity returns, using the same indices for both investments. Compute each calendar-year CAGR and their difference with the original elapsed-year denominator. Report both 95 percent percentile intervals and the resampling medians. Verify that original-order returns recover the published baseline before resampling.

This estimates uncertainty conditional on the realised return streams and resampling assumptions. It does not rerun holdings, financing or threshold decisions under alternative market paths, remove historical specification selection or prove future outperformance. Tracking error and information ratio are descriptive companions, not significance tests.

[Time-series block methods](https://arch.readthedocs.io/en/latest/bootstrap/timeseries-bootstraps.html) · [Paired resampling and confidence intervals](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.bootstrap.html)

## Source, recovery and delivery

`PROTOCOL.json` pins the authoritative baseline configurations, financial code, reference inventory and admitted input snapshots. Execute from the current checkout under `2_GitHub Connection/1_Repository/Finance/MSCI World Factor Strategy`, not the older private preparation code. Keep new study outputs separate and protect the original reports, references, raw data and sealed results.

Before interpreting results, preserve this protocol's hashes and copy it unchanged into the public study config/documentation. A material protocol change requires a new dated amendment that explains its effect; do not silently tune variants or tolerances. Only after appropriate checks should the reports, calculation map, GitHub source and private ZIP be updated together. Original inputs remain local/private.

**Current outcome:** protocol frozen; no new perturbation or bootstrap results generated. Next action: implement and verify the paired matrix, beginning with exact reproduction of the baseline.
