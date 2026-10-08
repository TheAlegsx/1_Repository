# MSCI World Factor Strategy

**Portfolio backtest · Research report · 8 October 2026**  
USD results · 3 October 2014–28 August 2026  
AI-assisted analysis and writing; tools, scope and responsibility are disclosed in the final section.

## Abstract

This study evaluates a shared MSCI World portfolio with Core, Momentum, Quality and Value weights of 60/15/10/15 and a 1.25x leverage target. Over 3 October 2014-28 August 2026, its CAGR is **{{claim:levered_cagr}}**, compared with **12.82%** for the MSCI World/Core investment at the same target leverage. Both include modelled trading and financing costs; the portfolio result excludes the added fund fee and outside-fund business costs. Borrowing raises return and risk relative to the unlevered portfolio. The estimated alpha against unlevered Core is -0.08% annually, with an interval including zero. The concept offers shared factor and leverage access; the historical evidence supports neither reliable future outperformance nor a proven commercial advantage.

## 1. Research Question

How does a shared portfolio anchored in the MSCI World, with momentum, quality and value sleeves, compare with a broad-market investment in growth, risk and cost? Does borrowing add return after investment costs, and what additional risks accompany it?

The intended value is a rules-based factor/leverage alternative for investors for whom direct borrowing is unavailable or relatively expensive. Its usefulness need not depend on persistent benchmark outperformance. Actual borrowing access and terms must still be established.

The main strategy uses 1.25x target leverage. Unlevered results provide a control for the contribution and risk of borrowing. A favourable joint historical comparison requires higher CAGR, no higher volatility and no deeper maximum drawdown. This criterion is distinct from statistical alpha or a reliable forecast of future outperformance.

## 2. Portfolio Design and Benchmark

### 2.1 Allocation and trading rules

**Table 1. Target allocation** · [Target weights: backtest configuration](https://github.com/TheAlegsx/1_Repository/blob/cd861934faf1aaeca43ae57bde0d01ec68ee6a25/Finance/MSCI%20World%20Factor%20Strategy/config/backtest_absolute_decoupled_2026-10-05.json)

{{table:allocation}}

The Core provides broad developed-market equity exposure; the factor sleeves apply different selection and weighting characteristics within the MSCI World framework. They remain equity investments and can decline together. The 60% Core keeps broad-market exposure central, while the remaining 40% diversifies the proposed factor tilts. The 1.25x target adds moderate borrowing rather than adopting a daily 2x product. These are design choices, not estimates of optimal future weights.

Weights are measured against gross invested assets. Each sleeve may drift by five percentage points above or below its target: Core 55–65%, Momentum 10–20%, Quality 5–15% and Value 10–20%. Equality at a boundary does not trigger trading. A strict breach signals a full sleeve reset at the next common NAV observation. A sleeve-only reset preserves debt; a leverage-only adjustment scales the existing mixture proportionally. A simultaneous signal resets both.

Leverage is managed separately at 1.25x with a ±0.10 band. This is an adjustment rule, not a hard cap on realised leverage. An account begins with USD {{claim:capital}} million of committed equity, corresponding to USD {{claim:gross}} million of gross exposure and USD {{claim:debt}} million of debt before opening charges. [Portfolio and cost settings: backtest configuration](https://github.com/TheAlegsx/1_Repository/blob/cd861934faf1aaeca43ae57bde0d01ec68ee6a25/Finance/MSCI%20World%20Factor%20Strategy/config/backtest_absolute_decoupled_2026-10-05.json).

The proposed opening equity represents seven founders contributing USD one million each. The backtest treats their investment as one aggregate account; it does not model separate founder transactions.

Five-percentage-point bands were the author's initial band-width proposal. Tighter alternatives were explored before returning to that width for simplicity and greater permitted factor drift. This chronology does not make the final specification independent of the historical evidence. The separated leverage mechanism must also be distinguished from coupled resets in some exploratory controls. A capped-relative rule, using the smaller of five percentage points and twenty percent of each sleeve target, is retained as a sensitivity in Appendix A.

### 2.2 Why MSCI World is the benchmark

The MSCI World is the primary market benchmark because it supplies the common developed-market framework for the Core and factor sleeves. A broad-market investment is the natural alternative against which to evaluate the combined allocation and management rules. The 60% Core allocation reinforces this connection; the common framework is the principal justification.

The backtest implements this benchmark through the **iShares Core MSCI World UCITS ETF**, an investable proxy whose NAV includes embedded fund expenses. It is not the bare index return. Results compare both unlevered investments and investments at the same 1.25x target. Equal target exposure does not establish equal realised leverage, beta, costs or investment universes.

Dimensional is a secondary systematic-investment alternative. Amundi is a short-period real leveraged-product comparison. Neither replaces the MSCI World/Core benchmark.

## 3. Data and Method

### 3.1 Inputs and common calendar

**Table 2. Main analytical inputs** · [NAV and funding inputs: backtest_sources.json](https://github.com/TheAlegsx/1_Repository/blob/cd861934faf1aaeca43ae57bde0d01ec68ee6a25/Finance/MSCI%20World%20Factor%20Strategy/config/backtest_sources.json)

| Source | Period | Use |
| --- | --- | --- |
| BlackRock/iShares accumulating ETF NAV exports | Common sample: 3 October 2014–28 August 2026 | Core, Momentum, Quality and Value investment returns |
| Author-supplied Bloomberg Dimensional NAV hardcopy | Same common sample | Secondary systematic-fund comparison |
| New York Fed indicative reference series and official SOFR | Relevant financing dates | Reference rate for borrowed exposure |
| Saved Amundi NAV workbook | Separate overlap: 30 September 2025–31 August 2026 | Real daily 2x product comparison |

The main common calendar contains **{{claim:levels}} levels and {{claim:intervals}} adjacent return intervals**. Investment levels are intersected before calculating returns; missing investment NAVs are not filled. The short Amundi experiment uses its own overlap and extends to August month-end. Reference rates are carried across nonpublication calendar days. The early indicative series is distinct from later official SOFR; both are financing proxies rather than the actual account's borrowing rate. [Common NAV calendar: backtest_workflow.prepare_inputs](https://github.com/TheAlegsx/1_Repository/blob/cd861934faf1aaeca43ae57bde0d01ec68ee6a25/Finance/MSCI%20World%20Factor%20Strategy/src/factor_portfolio/backtest_workflow.py#L119).

Accumulating NAVs include embedded fund expenses and reinvestment treatment. Deducting TER again would double-count that layer. NAV is not an executable bid or ask. Investor trading costs are therefore specified separately. Published rounded issuer returns provide a secondary check for {{claim:issuer_count}} calendar-year observations; the largest central-value difference is {{claim:issuer_max_gap}} and remains compatible with the retained rounding assumptions. This is not a second complete daily-price feed. [Issuer return check: backtest_issuer_returns.run_issuer_returns](https://github.com/TheAlegsx/1_Repository/blob/cd861934faf1aaeca43ae57bde0d01ec68ee6a25/Finance/MSCI%20World%20Factor%20Strategy/src/factor_portfolio/backtest_issuer_returns.py#L64).

The Dimensional comparison uses the Global Core Equity Fund, USD Accumulation Shares (ISIN IE00B2PC0153), with NAV observations from the supplied Bloomberg workbook. Its investment mandate differs from MSCI World and allows some emerging-market investments. That permission does not establish the fund's actual emerging-market allocation throughout the sample. Fund identities and sources are listed after the conclusion.

### 3.2 Accounting and costs

Gross invested assets minus debt equals investor equity. At an observation, positions are marked and financing is accrued; prior signals are executed before new signals are evaluated. Trading charges reduce equity. No subscriptions or withdrawals enter the investment backtest. [Trading, debt and fees: historical.simulate](https://github.com/TheAlegsx/1_Repository/blob/cd861934faf1aaeca43ae57bde0d01ec68ee6a25/Finance/MSCI%20World%20Factor%20Strategy/src/factor_portfolio/historical.py#L21).

**Table 3. Investment cost and measurement assumptions** · [Trading and borrowing costs: backtest configuration](https://github.com/TheAlegsx/1_Repository/blob/cd861934faf1aaeca43ae57bde0d01ec68ee6a25/Finance/MSCI%20World%20Factor%20Strategy/config/backtest_absolute_decoupled_2026-10-05.json)

{{table:costs}}

The borrowing charge is the reference rate **plus 3 percentage points (300 bp)**. Each traded leg also incurs a stepped broker commission, ranging from CHF 3 to CHF 190 according to the configured trade-notional brackets. The commission is converted into USD at the fixed rate below; the USD 0.85 platform charge is additional. [Broker commission: config.SwissquoteStandardFeeSchedule](https://github.com/TheAlegsx/1_Repository/blob/cd861934faf1aaeca43ae57bde0d01ec68ee6a25/Finance/MSCI%20World%20Factor%20Strategy/src/factor_portfolio/config.py#L66) specifies the exact brackets used in this current-cost scenario.

Funding accrues from the previous observation inclusive to the current observation exclusive, on ACT/360, and is capitalised at NAV dates. Current-cost scenarios apply the stated tariff and commission conversion throughout history rather than reconstructing historical invoices. Fund administration charges, custody sensitivities, investor taxes and manager business budgets are outside the baseline investment account. [Trading, debt and fees: historical.simulate](https://github.com/TheAlegsx/1_Repository/blob/cd861934faf1aaeca43ae57bde0d01ec68ee6a25/Finance/MSCI%20World%20Factor%20Strategy/src/factor_portfolio/historical.py#L21).

The fixed commission conversion is **1 CHF = USD 1.2368**, derived from the recorded ECB reference rates for **31 August 2026**: 1.1596 USD per EUR divided by 0.9376 CHF per EUR. Only the CHF-denominated broker commission is converted; investment returns and debt already use USD. Full precision is retained in the calculation. This endpoint reference rate is a modelling assumption, not a historical series of broker execution rates. [Portfolio and cost settings: backtest configuration](https://github.com/TheAlegsx/1_Repository/blob/cd861934faf1aaeca43ae57bde0d01ec68ee6a25/Finance/MSCI%20World%20Factor%20Strategy/config/backtest_absolute_decoupled_2026-10-05.json).

CAGR uses committed opening capital and elapsed calendar years. Opening trading charges are included once and folded into the first investor-return interval. Drawdown uses a high-water mark no lower than committed opening capital. Volatility uses 252-observation annualisation. Jensen alpha is an annualised excess-return regression intercept against unlevered Core, not the CAGR difference; exploratory intervals use five-lag HAC errors. [Return and risk metrics: historical.metrics](https://github.com/TheAlegsx/1_Repository/blob/cd861934faf1aaeca43ae57bde0d01ec68ee6a25/Finance/MSCI%20World%20Factor%20Strategy/src/factor_portfolio/historical.py#L121).

Separate implementations check account identities and selected daily, event and outcome results under shared inputs and conventions. These checks address implementation errors; they do not establish market-price executability, commercial feasibility or expert peer review.

## 4. Historical Results

### 4.1 Central MSCI World comparison

**Table 4. Unlevered control over the main sample** · [CAGR, volatility and drawdown: historical.metrics](https://github.com/TheAlegsx/1_Repository/blob/cd861934faf1aaeca43ae57bde0d01ec68ee6a25/Finance/MSCI%20World%20Factor%20Strategy/src/factor_portfolio/historical.py#L121)

{{table:unlevered}}

**Table 5. Main portfolio and Core at a 1.25x target** · [CAGR, volatility and drawdown: historical.metrics](https://github.com/TheAlegsx/1_Repository/blob/cd861934faf1aaeca43ae57bde0d01ec68ee6a25/Finance/MSCI%20World%20Factor%20Strategy/src/factor_portfolio/historical.py#L121)

{{table:main}}

These account returns include embedded product expenses, investor trading charges and financing. They exclude the additional fund fee and outside-fund operating budget analysed in the companion study. The main strategy meets the stated joint growth/risk criterion against Core over the full sample. Its CAGR advantage is {{claim:unlevered_gap_core}} without borrowing and {{claim:levered_gap_core}} at matched target leverage. These are historical account comparisons, not a causal estimate of the return from each factor. [Return and risk metrics: historical.metrics](https://github.com/TheAlegsx/1_Repository/blob/cd861934faf1aaeca43ae57bde0d01ec68ee6a25/Finance/MSCI%20World%20Factor%20Strategy/src/factor_portfolio/historical.py#L121).

Borrowing increases portfolio CAGR from {{claim:unlevered_cagr}} to {{claim:levered_cagr}}, but also raises volatility from {{claim:unlevered_annualised_volatility}} to {{claim:levered_annualised_volatility}} and deepens maximum drawdown from {{claim:unlevered_maximum_drawdown}} to {{claim:levered_maximum_drawdown}}. The additional growth comes with additional total risk. [Return and risk metrics: historical.metrics](https://github.com/TheAlegsx/1_Repository/blob/cd861934faf1aaeca43ae57bde0d01ec68ee6a25/Finance/MSCI%20World%20Factor%20Strategy/src/factor_portfolio/historical.py#L121).

**Table 6. Main strategy and the unlevered retail alternative** · [Existing return and risk measures: reader_diagnostics.summaries](https://github.com/TheAlegsx/1_Repository/blob/24979b0b422c1f016a4b3a51e84420b3d701b5f7/Finance/MSCI%20World%20Factor%20Strategy/src/factor_portfolio/reader_diagnostics.py#L8)

{{detail:retail}}

For an investor without convenient borrowing access, unlevered Core is a relevant practical alternative. The main portfolio delivered higher historical CAGR, with higher volatility and a slightly lower Sharpe ratio, before the added fund fee. Its value proposition is access to a chosen factor/leverage exposure; these figures do not establish better risk-adjusted performance than a simple Core holding. The matched-target comparison remains necessary to distinguish this question from the effects of borrowing.

**Table 7. End-date sensitivity of the continuing investment paths** · [Relative wealth: reader_diagnostics.summaries](https://github.com/TheAlegsx/1_Repository/blob/24979b0b422c1f016a4b3a51e84420b3d701b5f7/Finance/MSCI%20World%20Factor%20Strategy/src/factor_portfolio/reader_diagnostics.py#L8)

{{detail:endpoints}}

Relative wealth is 100 x (portfolio equity / Core equity - 1), with both paths at a 1.25x target and unchanged opening capital. These are checkpoints of the continuing accounts, not independently restarted backtests or annual return gaps. The portfolio recovered most of its 2024 shortfall during 2025 and was nearly level with Core at the end of 2025. Its positive terminal wealth advantage emerged in the observed 2026 segment. The headline result is therefore sensitive to the chosen endpoint and does not demonstrate a persistent advantage throughout the sample.

After the opening investment, the main path contains only **two rule-triggered interventions**: a sleeve reset on **3 September 2020** and a leverage adjustment on **9 April 2021**. The count includes leverage adjustments. Most of this historical path therefore consists of held positions with permitted weight and leverage drift. The thresholds still govern when trading is avoided, and few interventions do not remove retrospective selection risk. The event ledger records both actions.

{{figure:equity}}

*Figure 1. Main portfolio and Core at the same 1.25x target, after modelled trading and financing. The lower panel shows their relative ending wealth at each date: 100 x (portfolio equity / Core equity - 1). This is not an annual return or regression alpha. The capped-relative comparison remains in Appendix A.* [Reader charts from recorded evidence: reader_figures.render](https://github.com/TheAlegsx/1_Repository/blob/24979b0b422c1f016a4b3a51e84420b3d701b5f7/Finance/MSCI%20World%20Factor%20Strategy/src/factor_portfolio/reader_figures.py#L15)

{{figure:drawdown}}

*Figure 2. Main portfolio and Core drawdowns from their committed-capital high-water marks. Opening charges are included; intraday lender exposure is outside this observation calendar.* [Reader charts from recorded evidence: reader_figures.render](https://github.com/TheAlegsx/1_Repository/blob/24979b0b422c1f016a4b3a51e84420b3d701b5f7/Finance/MSCI%20World%20Factor%20Strategy/src/factor_portfolio/reader_figures.py#L15)

**Table 8. Realised leverage on the common NAV calendar** · [Leverage summaries: reader_diagnostics.summaries](https://github.com/TheAlegsx/1_Repository/blob/24979b0b422c1f016a4b3a51e84420b3d701b5f7/Finance/MSCI%20World%20Factor%20Strategy/src/factor_portfolio/reader_diagnostics.py#L8)

{{detail:leverage}}

The observation mean is close to the target and to the Core comparator's **{{detail:core_mean}}**. Leverage varies because market moves change equity and financing accrues into debt. The 1.25x label is an actively monitored target rather than a constant daily exposure or only an opening value. Similar average leverage does not imply equal daily exposure, beta or risk. The observed maximum is a common-NAV measure, not an intraday maximum or a verified distance to a lender's margin-call threshold.

{{figure:leverage}}

*Figure 3. Observed portfolio leverage, target and adjustment band. Strict breaches are executed at the next common NAV; the band is not a hard realised-exposure cap. The average uses the same observation-based definition as the reported investment metrics.* [Recorded leverage plot: reader_figures.render](https://github.com/TheAlegsx/1_Repository/blob/24979b0b422c1f016a4b3a51e84420b3d701b5f7/Finance/MSCI%20World%20Factor%20Strategy/src/factor_portfolio/reader_figures.py#L15)

### 4.2 Brief comparison with Dimensional

**Table 9. Main strategy and Dimensional at the 1.25x target** · [CAGR, volatility and drawdown: historical.metrics](https://github.com/TheAlegsx/1_Repository/blob/cd861934faf1aaeca43ae57bde0d01ec68ee6a25/Finance/MSCI%20World%20Factor%20Strategy/src/factor_portfolio/historical.py#L121)

{{table:dimensional}}

The main portfolio's CAGR advantage over Dimensional is {{claim:levered_gap_dimensional}}, with lower observed volatility and a shallower maximum drawdown. Dimensional is an existing systematic fund alternative with different universe and implementation characteristics. Equal target borrowing does not remove those differences. The comparator control excluding external transaction charges also remains below the primary over the full sample; embedded product costs remain in that control. This comparison therefore does not isolate a pure factor premium. [Return and risk metrics: historical.metrics](https://github.com/TheAlegsx/1_Repository/blob/cd861934faf1aaeca43ae57bde0d01ec68ee6a25/Finance/MSCI%20World%20Factor%20Strategy/src/factor_portfolio/historical.py#L121).

### 4.3 Portfolio at 2x versus the Amundi daily 2x ETF

**Table 10. Factor portfolio at 2x and Amundi daily 2x: 30 September 2025–31 August 2026** · [Product comparison: backtest_products.product_comparison](https://github.com/TheAlegsx/1_Repository/blob/cd861934faf1aaeca43ae57bde0d01ec68ee6a25/Finance/MSCI%20World%20Factor%20Strategy/src/factor_portfolio/backtest_products.py#L55)

{{table:amundi}}

For this product comparison, the factor portfolio uses a **2x leverage target** with the same allocation and absolute sleeve bands. Its debt is adjusted through the separate leverage band. It is compared with the **Amundi daily 2x ETF** over their common short window. The table reports cumulative returns. The factor portfolio earns the higher return, accompanied by higher volatility and a deeper maximum drawdown. The main strategy and its MSCI World/Core benchmark comparison continue to use **1.25x**.

The factor portfolio includes modelled ongoing trading and borrowing costs. The Amundi return is taken directly from its USD NAV, which incorporates the product's expenses and leveraged financing economics. **The portfolio's borrowing charges are therefore not applied to Amundi.** The Amundi series excludes additional investor purchase/exit brokerage, taxes and listing spreads. Both paths are normalised to the first common post-entry observation; this removes the modelled portfolio's opening expenses.

Amundi resets exposure daily, while the factor portfolio manages leverage within a band. These mechanics produce different exposure paths despite the same nominal 2x label. The evidence is limited to the observed product overlap and does not establish long-period or future superiority. The 2x experiment remains an additional comparison; it leaves the main investment and capital-inflow specifications unchanged.

## 5. Robustness and Implementation Risk

The growth ranking is not stable across all dates. In independently restarted early and later periods, Core exceeds the main portfolio's CAGR in the early segment, while the main portfolio leads in the later segment. Appendix B retains this counter-evidence and the alpha estimates. Overlapping rolling windows and alternative entry dates do not provide independent probabilities of future success.

The main portfolio's exploratory alpha intervals include zero at both exposure levels. The slightly negative leveraged alpha and the positive matched-target CAGR gap answer different questions. Alpha is a beta-adjusted excess-return intercept against **unlevered Core**; the CAGR gap compares compounded account growth with Core at the **same 1.25x target**. No separate significance test of that CAGR gap is reported. Historical testing, changes in period rankings and a market-exposed set of equity sleeves prevent a claim of established future superiority. The later restart is retrospective rather than a pristine holdout.

Financing and custody costs can change signals, holdings and later trades. Consequently, small changes in charges need not produce monotone ending values. Appendix B reruns the whole strategy at each financing margin, including newly triggered trades. At 0 bp the path has five post-entry interventions, compared with two at 300 bp, including additional leverage adjustments around the 2020 decline. The 13.64% versus 13.24% CAGR comparison therefore includes changed exposure paths as well as direct interest expense. Zero markup still incurs the reference rate. A constant-debt estimate of financing drag cannot reproduce this comparison, and the table does not identify a universally safe borrowing margin. Higher ending wealth in an isolated fee scenario is not evidence that paying higher fees is beneficial.

A larger pool of capital, including possible external subscriptions, might support negotiation of better financing terms. The funding sensitivity measures alternative assumed borrowing margins; it does not establish a relationship between assets and lender pricing. The baseline margin remains fixed, and the companion inflow model does not automatically reduce it as assets grow.

Hypothetical instantaneous losses at maintenance boundaries include both sale-funded cures and insolvency before a cure is possible. These are imposed account states with liquidation friction, not actual historical lender accounts. Positive equity and successful modelled sales do not establish that a lender permits the cure or executes at that NAV.

Actual collateral eligibility, account category, rate fixing, settlement, liquidation timing and complete charges remain unconfirmed. The public banking material supports scenario definitions rather than an individual credit offer. Sparse holdings snapshots cannot explain the entire historical return difference or supply a full historical sector panel.

## 6. Conclusion

Under the stated conventions, the 60/15/10/15 portfolio with absolute ±5-percentage-point bands and separate leverage management has a favourable full-sample growth/risk comparison with MSCI World/Core. The simpler common band consciously permits factor drift. Borrowing adds historical growth and materially increases total risk.

Shared access to the factor/leverage implementation is the central investment rationale; the favourable historical comparison is supporting evidence. Any financing advantage from pooling capital remains conditional on applicable lending terms.

The evidence supports further investigation of a fixed specification rather than a forecast of superior returns. Prospective evaluation and verified lending and execution terms are separate requirements from reproducing the historical accounts. The [capital-inflow companion report](CAPITAL_INFLOWS_RESEARCH_2026-10-07.md) applies the portfolio to a shorter historical fund experiment with hypothetical fees, flows and business costs. Its separate flat, fixed-growth and imposed-loss controls are not projections of the full-period backtest CAGR.

## Sources and Data

{{sources:backtest}}

## Appendix A. Band Sensitivity

**Table A1. Absolute/separate and capped-relative policies** · [Policy accounts: backtest_workflow.policy_comparison](https://github.com/TheAlegsx/1_Repository/blob/cd861934faf1aaeca43ae57bde0d01ec68ee6a25/Finance/MSCI%20World%20Factor%20Strategy/src/factor_portfolio/backtest_workflow.py#L161)

{{table:policy}}

The capped-relative rule has narrower factor bands, particularly for Quality. Broader bands do not guarantee lower overall risk or fewer trades on every path. Allocation grids and legacy coupled-absolute search maxima are retrospective sensitivity evidence and do not define the separated primary or an optimal future allocation.

## Appendix B. Statistical and Period Checks

**Table B1. Main portfolio alpha against unlevered Core** · [Alpha and HAC intervals: historical.metrics](https://github.com/TheAlegsx/1_Repository/blob/cd861934faf1aaeca43ae57bde0d01ec68ee6a25/Finance/MSCI%20World%20Factor%20Strategy/src/factor_portfolio/historical.py#L121)

{{table:alpha}}

Intervals are exploratory nominal-252 annualised regression-intercept intervals with five-lag HAC errors. They are not adjusted for specification selection or multiple testing. The leveraged regression remains against unlevered Core, so its intercept must not be confused with the matched-target CAGR gap.

**Table B2. Independently restarted retrospective periods at 1.25x** · [Policy accounts: backtest_workflow.policy_comparison](https://github.com/TheAlegsx/1_Repository/blob/cd861934faf1aaeca43ae57bde0d01ec68ee6a25/Finance/MSCI%20World%20Factor%20Strategy/src/factor_portfolio/backtest_workflow.py#L161)

{{table:periods}}

The early period is 3 October 2014–31 December 2021; the later period starts on the first common 2022 observation, 4 January, and ends on 28 August 2026. Each account restarts capital and opening charges. These splits preserve counter-evidence rather than provide an untouched holdout.

**Table B3. Financing-markup sensitivity above the reference rate** · [Borrowing scenarios: backtest_funding.funding_comparison](https://github.com/TheAlegsx/1_Repository/blob/cd861934faf1aaeca43ae57bde0d01ec68ee6a25/Finance/MSCI%20World%20Factor%20Strategy/src/factor_portfolio/backtest_funding.py#L77)

{{table:funding}}

The later result is a restarted account, not a continuation of the full-history balance. Policy discontinuities prevent interpreting a finite scan as a continuous or globally complete break-even search.

## Reproducibility Materials

The blue links open the responsible function or configuration on GitHub. [The calculation map](https://github.com/TheAlegsx/1_Repository/blob/main/Finance/MSCI%20World%20Factor%20Strategy/docs/REPORT_CALCULATION_MAP.md) identifies exact rows, fields and generated evidence paths. Code links use fixed snapshots. The prepared code and separately supplied original data reconstruct the accounts; full analyses and source-cell bindings remain in the accompanying calculation materials. Provider originals stay local.

## AI Assistance and Responsibility

{{disclosure:author}}

This declaration concerns Alex's research contribution. It does not attribute unverified AI use to other group members or future video narration.
