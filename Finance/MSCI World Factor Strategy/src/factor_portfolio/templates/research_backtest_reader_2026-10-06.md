# MSCI World Factor Strategy

**Portfolio backtest · Research report · 7 October 2026**  
USD results · 3 October 2014–28 August 2026

## Abstract

This study evaluates a developed-market equity portfolio with Core, Momentum, Quality and Value weights of 60/15/10/15. Absolute ±5-percentage-point sleeve bands are combined with separate leverage management at a target of 1.25x. Over the common historical sample, CAGR is **{{claim:unlevered_cagr}} without borrowing** and **{{claim:levered_cagr}} at the borrowed target**, after modelled investment trading and financing costs. The borrowed portfolio has a {{claim:levered_gap_core}} CAGR advantage over the MSCI World/Core comparator at the same target exposure, with slightly lower observed volatility and drawdown. These favourable full-period comparisons coexist with changing period rankings and alpha intervals that include zero. Historical specification testing and unverified real lending conditions limit prospective conclusions. [Return and risk metrics: historical.metrics](https://github.com/TheAlegsx/1_Repository/blob/cd861934faf1aaeca43ae57bde0d01ec68ee6a25/Finance/MSCI%20World%20Factor%20Strategy/src/factor_portfolio/historical.py#L121).

## 1. Research Question

Can a portfolio anchored in the MSCI World, with momentum, quality and value sleeves, improve historical growth and risk outcomes relative to a broad-market investment? Does borrowing add return after investment costs, and what additional risks accompany it?

The main strategy uses 1.25x target leverage. Unlevered results provide a control for the contribution and risk of borrowing. A favourable joint historical comparison requires higher CAGR, no higher volatility and no deeper maximum drawdown. This criterion is distinct from statistical alpha or a reliable forecast of future outperformance.

## 2. Portfolio Design and Benchmark

### 2.1 Allocation and trading rules

**Table 1. Target allocation** · [Target weights: backtest configuration](https://github.com/TheAlegsx/1_Repository/blob/cd861934faf1aaeca43ae57bde0d01ec68ee6a25/Finance/MSCI%20World%20Factor%20Strategy/config/backtest_absolute_decoupled_2026-10-05.json)

{{table:allocation}}

The Core provides broad developed-market equity exposure; the factor sleeves apply different selection and weighting characteristics within the MSCI World framework. They remain equity investments and can decline together. The weights express the proposed investment design rather than a fitted estimate of optimal future weights.

Weights are measured against gross invested assets. Each sleeve may drift by five percentage points above or below its target: Core 55–65%, Momentum 10–20%, Quality 5–15% and Value 10–20%. Equality at a boundary does not trigger trading. A strict breach signals a full sleeve reset at the next common NAV observation. A sleeve-only reset preserves debt; a leverage-only adjustment scales the existing mixture proportionally. A simultaneous signal resets both.

Leverage is managed separately at 1.25x with a ±0.10 band. This is an adjustment rule, not a hard cap on realised leverage. An account begins with USD {{claim:capital}} million of committed equity, corresponding to USD {{claim:gross}} million of gross exposure and USD {{claim:debt}} million of debt before opening charges. [Portfolio and cost settings: backtest configuration](https://github.com/TheAlegsx/1_Repository/blob/cd861934faf1aaeca43ae57bde0d01ec68ee6a25/Finance/MSCI%20World%20Factor%20Strategy/config/backtest_absolute_decoupled_2026-10-05.json).

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

**AI-assisted methodology and writing:** OpenAI Codex (OpenAI, n.d.) assisted development of the analytical code and all narrative sections, tables and figures. The final AI Assistance and Responsibility section identifies the affected material, tools, author decisions, checks and retained prompt evidence.

Gross invested assets minus debt equals investor equity. At an observation, positions are marked and financing is accrued; prior signals are executed before new signals are evaluated. Trading charges reduce equity. No subscriptions or withdrawals enter the investment backtest. [Trading, debt and fees: historical.simulate](https://github.com/TheAlegsx/1_Repository/blob/cd861934faf1aaeca43ae57bde0d01ec68ee6a25/Finance/MSCI%20World%20Factor%20Strategy/src/factor_portfolio/historical.py#L21).

**Table 3. Investment cost and measurement assumptions** · [Trading and borrowing costs: backtest configuration](https://github.com/TheAlegsx/1_Repository/blob/cd861934faf1aaeca43ae57bde0d01ec68ee6a25/Finance/MSCI%20World%20Factor%20Strategy/config/backtest_absolute_decoupled_2026-10-05.json)

{{table:costs}}

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

The main strategy meets the stated joint growth/risk criterion against Core over the full sample. Its CAGR advantage is {{claim:unlevered_gap_core}} without borrowing and {{claim:levered_gap_core}} at matched target leverage. These are historical account comparisons, not a causal estimate of the return from each factor. [Return and risk metrics: historical.metrics](https://github.com/TheAlegsx/1_Repository/blob/cd861934faf1aaeca43ae57bde0d01ec68ee6a25/Finance/MSCI%20World%20Factor%20Strategy/src/factor_portfolio/historical.py#L121).

Borrowing increases portfolio CAGR from {{claim:unlevered_cagr}} to {{claim:levered_cagr}}, but also raises volatility from {{claim:unlevered_annualised_volatility}} to {{claim:levered_annualised_volatility}} and deepens maximum drawdown from {{claim:unlevered_maximum_drawdown}} to {{claim:levered_maximum_drawdown}}. The additional growth comes with additional total risk. [Return and risk metrics: historical.metrics](https://github.com/TheAlegsx/1_Repository/blob/cd861934faf1aaeca43ae57bde0d01ec68ee6a25/Finance/MSCI%20World%20Factor%20Strategy/src/factor_portfolio/historical.py#L121).

{{figure:equity}}

*Figure 1. Investor equity at matched 1.25x target exposure, after modelled trading and financing. The capped-relative sensitivity is shown alongside the main strategy. There are no subscriptions or manager-fee receipts in these paths.* [Equity and drawdown plots: backtest_report.plot_history](https://github.com/TheAlegsx/1_Repository/blob/cd861934faf1aaeca43ae57bde0d01ec68ee6a25/Finance/MSCI%20World%20Factor%20Strategy/src/factor_portfolio/backtest_report.py#L278)

{{figure:drawdown}}

*Figure 2. Drawdown from the committed-capital high-water mark on the common observation calendar. The paths include opening charges but do not capture intraday lender exposure.* [Equity and drawdown plots: backtest_report.plot_history](https://github.com/TheAlegsx/1_Repository/blob/cd861934faf1aaeca43ae57bde0d01ec68ee6a25/Finance/MSCI%20World%20Factor%20Strategy/src/factor_portfolio/backtest_report.py#L278)

### 4.2 Brief comparison with Dimensional

**Table 6. Main strategy and Dimensional at the 1.25x target** · [CAGR, volatility and drawdown: historical.metrics](https://github.com/TheAlegsx/1_Repository/blob/cd861934faf1aaeca43ae57bde0d01ec68ee6a25/Finance/MSCI%20World%20Factor%20Strategy/src/factor_portfolio/historical.py#L121)

{{table:dimensional}}

The main portfolio's CAGR advantage over Dimensional is {{claim:levered_gap_dimensional}}, with lower observed volatility and a shallower maximum drawdown. Dimensional is an existing systematic fund alternative with different universe and implementation characteristics. Equal target borrowing does not remove those differences. The comparator control excluding external transaction charges also remains below the primary over the full sample; embedded product costs remain in that control. This comparison therefore does not isolate a pure factor premium. [Return and risk metrics: historical.metrics](https://github.com/TheAlegsx/1_Repository/blob/cd861934faf1aaeca43ae57bde0d01ec68ee6a25/Finance/MSCI%20World%20Factor%20Strategy/src/factor_portfolio/historical.py#L121).

### 4.3 Portfolio at 2x versus the Amundi daily 2x ETF

**Table 7. Factor portfolio at 2x and Amundi daily 2x: 30 September 2025–31 August 2026** · [Product comparison: backtest_products.product_comparison](https://github.com/TheAlegsx/1_Repository/blob/cd861934faf1aaeca43ae57bde0d01ec68ee6a25/Finance/MSCI%20World%20Factor%20Strategy/src/factor_portfolio/backtest_products.py#L55)

{{table:amundi}}

For this product comparison, the factor portfolio uses a **2x leverage target** with the same allocation and absolute sleeve bands. Its debt is adjusted through the separate leverage band. It is compared with the **Amundi daily 2x ETF** over their common short window. The table reports cumulative returns. The factor portfolio earns the higher return, accompanied by higher volatility and a deeper maximum drawdown. The main strategy and its MSCI World/Core benchmark comparison continue to use **1.25x**.

The factor portfolio includes modelled ongoing trading and borrowing costs. The Amundi return is taken directly from its USD NAV, which incorporates the product's expenses and leveraged financing economics. **The portfolio's borrowing charges are therefore not applied to Amundi.** The Amundi series excludes additional investor purchase/exit brokerage, taxes and listing spreads. Both paths are normalised to the first common post-entry observation; this removes the modelled portfolio's opening expenses.

Amundi resets exposure daily, while the factor portfolio manages leverage within a band. These mechanics produce different exposure paths despite the same nominal 2x label. The evidence is limited to the observed product overlap and does not establish long-period or future superiority. The 2x experiment remains an additional comparison; it leaves the main investment and capital-inflow specifications unchanged.

## 5. Robustness and Implementation Risk

The growth ranking is not stable across all dates. In independently restarted early and later periods, Core exceeds the main portfolio's CAGR in the early segment, while the main portfolio leads in the later segment. Appendix B retains this counter-evidence and the alpha estimates. Overlapping rolling windows and alternative entry dates do not provide independent probabilities of future success.

The main portfolio's exploratory alpha intervals include zero at both exposure levels. The leveraged estimate is not convincingly positive. Historical testing, changes in period rankings and a market-exposed set of equity sleeves prevent a claim of established future superiority. The later restart is retrospective rather than a pristine holdout.

Financing and custody costs can change signals, holdings and later trades. Consequently, small changes in charges need not produce monotone ending values. The financing sensitivity in Appendix B is descriptive; it does not identify a universally safe borrowing margin. Higher ending wealth in an isolated fee scenario is not evidence that paying higher fees is beneficial.

Hypothetical instantaneous losses at maintenance boundaries include both sale-funded cures and insolvency before a cure is possible. These are imposed account states with liquidation friction, not actual historical lender accounts. Positive equity and successful modelled sales do not establish that a lender permits the cure or executes at that NAV.

Actual collateral eligibility, account category, rate fixing, settlement, liquidation timing and complete charges remain unconfirmed. The public banking material supports scenario definitions rather than an individual credit offer. Sparse holdings snapshots cannot explain the entire historical return difference or supply a full historical sector panel.

## 6. Conclusion

Under the stated conventions, the 60/15/10/15 portfolio with absolute ±5-percentage-point bands and separate leverage management has a favourable full-sample growth/risk comparison with MSCI World/Core. The simpler common band consciously permits factor drift. Borrowing adds historical growth and materially increases total risk.

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

Blue highlighted links name the source function or configuration and the quantity it calculates or specifies. Click a function link to open the corresponding code line on GitHub. Code links identify a fixed source snapshot; [the report-to-calculation map](https://github.com/TheAlegsx/1_Repository/blob/main/Finance/MSCI%20World%20Factor%20Strategy/docs/REPORT_CALCULATION_MAP.md) provides the selected rows, fields and generated evidence paths. Original provider observations remain local.

The prepared code and separately supplied original data reconstruct the investment accounts. Full allocation, policy, rolling-entry, correlation, cost, artificial-regime, gap-cure, holdings and product-control results remain in the accompanying calculation materials. Their inclusion in the research archive does not make raw provider data public. The reader-selection record identifies the evidence behind each displayed table and claim.

## AI Assistance and Responsibility

{{disclosure:author}}

This declaration concerns Alex's research contribution. It does not attribute unverified AI use to other group members or future video narration.
