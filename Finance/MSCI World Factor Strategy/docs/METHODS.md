# Methods and scope

The main study asks whether an implementable MSCI World factor allocation improves historical growth/risk outcomes relative to a broad-market investment after financing and trading costs. The backtest and fund-economics study answer different questions.

## Portfolio and accounting

The authoritative baseline is[the absolute-band configuration](../config/backtest_absolute_decoupled_2026-10-05.json): Core/Momentum/Quality/Value 60/15/10/15, USD7million committed equity,1.25x target exposure, absolute±5-percentage-point sleeve bands and separate±0.10 leverage adjustment band. A sleeve-only intervention restores target weights; leverage-only intervention rescales the existing mixture. A joint signal resets both. The capped-relative policy remains a comparison.

The common investment window is 3 October 2014–28August 2026:2,929 levels and 2,928 intervals. Missing investment NAVs are not forward-filled. Accumulating NAVs embed fund expenses/reinvestment. Trading costs reduce equity; ACT/360 funding accrues on debt at the historical reference rate plus a 3-percentage-point margin. Opening costs enter committed-capital returns. Current commissions, duty, spread and the fixed CHF-cost conversion are explicit assumptions, not historical broker invoices. Measurement details and cost values appear in the backtest report.

MSCI World supplies the common developed-market setting and reference for the factor sleeves. The Core ETF implements that market benchmark; unlevered and matched 1.25x cases retain distinct meanings. Dimensional is an external fund comparison. The short 2x Amundi case uses actual daily 2x NAV with embedded product economics; factor 2x includes its own trading/funding costs. The two leverage mechanisms and investor-cost conventions differ.

## Capital inflows and fund economics

The historical branch executes the same selected investment strategy with hypothetical investor flows, units, redemptions and an added fund fee over 3 October 2014–3 October 2024,120 project months. Flows/costs/debt can alter the realised path. A separate overlay applies cohort accounting to the no-flow path and does not substitute for the coupled simulation. The main full-period CAGR is not inserted as a constant historical return.

The hypothetical branch uses separately adjustable flat,6% growth, early-loss and later-loss paths. These imposed returns and demand/budget assumptions are not observed fundraising or forecasts. Owner invested equity, external invested equity, consolidated fund assets and manager cash are separate accounts. Internal owner-fee transfers do not create new external wealth. No-investor MWR remains unavailable; historical dated returns and equal-month hypothetical return calculations use different conventions.

## Interpretation

Historical choices and alternative rules were examined retrospectively. Reported alpha intervals include zero; overlapping horizons and constructed controls are not independent samples. Matching accounting implementations reduces implementation-error risk under shared inputs; it does not establish future superiority, executable prices, bank-specific credit terms or business viability. Historical holdings are sparse dated snapshots, not continuous attribution panels.

[Backtest](../reports/MSCI_World_Factor_Strategy_Backtest.pdf) · [Fund economics](../reports/Capital_Inflows_Fund_Economics.pdf) · [AI attribution](AI_USE.md)
