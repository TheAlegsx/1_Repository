# Backtesting an MSCI World–Anchored Factor Portfolio

**Academic discussion draft · Version 9 · 6 October 2026**  
Historical strategy research in USD · Main comparison: 3 October 2014–28 August 2026

The primary design combines Core, Momentum, Quality and Value with absolute ±5-percentage-point sleeve bands and separate leverage control. The previous capped-relative rule remains a comparison. This working report preserves the original research files and makes the revised selection explicit.

**AI assistance and responsibility**

{{disclosure:author}}

This disclosure concerns Alex's research contribution. It does not attribute unverified AI use to other group members or future video narration. The [source and download register](source_register.md) retains the actual providers and evidence qualifications.

## 1. Research Question

Can an MSCI World–anchored factor allocation improve historical outcomes relative to a broad-market investment and an existing systematic fund? Does borrowed exposure add return after explicit costs, and what additional risks and implementation conditions accompany it?

The analysis first compares unlevered investments and then equal target exposure. A favourable historical joint result requires higher CAGR, no higher volatility and no deeper maximum drawdown. This criterion differs from positive statistical alpha, reliable time stability, future performance and practical investability.

The primary has full-period CAGR **{{claim:unlevered_cagr}} without borrowing** and **{{claim:levered_cagr}} at borrowed target exposure**. These retrospective outcomes are assessed with their risk and counter-evidence rather than treated as a return forecast.

## 2. Economic Design and Benchmarks

### 2.1 Allocation and motivation

The concept combines a broad developed-market anchor with systematic momentum, quality and value selection. The intended factor sleeves offer different selection characteristics, while the larger Core allocation keeps a substantial market exposure. All sleeves remain equities and can lose value together.

{{table:backtest_01}}

The weights express the proposed design; they are not a fitted estimate of optimal future weights. Alternative allocations are retained in Appendix A. No historical grid winner automatically replaces this allocation.

The absolute band was selected after historical alternatives were examined, for a simpler common rule and consciously greater room for the factor weights to drift. That choice is ex post. The relative breadth of the quality sleeve's band is larger than before; greater permitted drift is a design trade-off, not a newly established risk reduction.

### 2.2 Comparison investments

{{table:backtest_02}}

Equal target exposure does not mean identical realised leverage, beta, expenses or investment universes. Core is an investable ETF proxy rather than the index itself. The Dimensional share-class mapping is author-confirmed; its permitted broader universe is not evidence of its actual historical emerging-market exposure. The short daily-reset leveraged-product comparison cannot replace the long main history.

## 3. Data and Validation

### 3.1 Observations and alignment

{{table:backtest_03}}

The main common calendar contains **{{claim:levels}} NAV levels and {{claim:intervals}} adjacent return intervals**. Levels are intersected before returns are calculated; missing investment NAVs are not filled. Independently restarted periods include their own opening transaction expenses once. The initial return row is zero for portfolio accounting, while investor-return statistics retain the opening charge.

Accumulating fund NAVs already include their embedded expenses and reinvestment treatment. A second TER deduction would double-count a cost layer. NAV is not an executable price; the model separately specifies investor trading charges.

ETF imports retain the research serialization precision. Reference-rate observations are converted to annual decimals and carried over nonpublication calendar days. The early indicative reference series remains distinct from later official SOFR. It is a financing proxy, not the portfolio's actual lender contract.

### 3.2 Checks and their limits

The separate issuer comparison checks **{{claim:issuer_count}} calendar-year returns** against published rounded performance. All selected observations are compatible with the retained rounding assumptions; the largest central-value difference is **{{claim:issuer_max_gap}}**. This does not establish exact high-precision equality or supply another complete daily NAV feed. [Issuer comparison](../evidence/issuer.csv)

The annual-report reconstruction covers **{{claim:annual_snapshots}} snapshots and {{claim:holding_lines}} security-line observations**. ETF equity totals reconcile to their recorded schedules; the Dimensional sums preserve differences consistent with rounding of individual values. Different dates, country conventions, security lines and issuer consolidation remain qualified. [Historical holdings](#appendix-i)

Separate account code checks **{{claim:independent_retained}} retained and {{claim:independent_additional}} additional labels**, with **{{claim:independent_comparisons}} eight-outcome comparisons**. Raw-source readers, declared risk/rolling checks and daily/event comparisons have separate recorded scopes. Parameter labels, overlapping horizons and constructed controls are not independent observations. These checks reduce implementation-error risk under shared inputs and conventions; they do not establish executable prices, expert approval or future superiority. [Audit coverage](../evidence/independent.json)

## 4. Method and Assumptions

### 4.1 Portfolio mechanics

Each independently started account commits **USD {{claim:capital}} million**. Gross invested assets minus debt equals equity. Existing positions are marked, funding is accrued and prior signals are executed before new signals are evaluated. Trading charges reduce equity; no external capital is injected into the main backtest.

Weights are measured against gross invested assets. A strict sleeve-band breach signals a full sleeve reset on the next common NAV. A sleeve-only reset preserves debt; it does not force a leverage reset. A leverage-only adjustment scales the current mixture proportionally. A simultaneous signal resets both. The comparison policy uses the smaller of five percentage points and twenty percent of each target; it is separately labelled throughout.

At the borrowed target, opening capital corresponds to **USD {{claim:gross}} million gross exposure and USD {{claim:debt}} million debt before charges**. Target leverage is 1.25x with a ±0.10 adjustment band. This is a trading rule, not a hard cap on realised exposure or a lender-approved borrowing limit. ETF constituent changes are separate from portfolio sleeve trades.

### 4.2 Economic assumptions

{{table:backtest_04}}

Commission, platform fee, investor-side duty and ordinary one-way spread remain separate. Current-cost scenarios apply one tariff and commission conversion across history; they do not reconstruct historical invoices. Funding accrues over the previous observation inclusive to the current observation exclusive, ACT/360, and is capitalised at NAV dates. Administration fees, subscriptions, withdrawals, investor capital-gains taxes and manager business costs are outside the main investment model.

### 4.3 Measurement and selection

CAGR uses committed opening capital and elapsed calendar years. Investor risk returns fold the opening cost into the first observed interval. Drawdown uses a high-water mark no lower than committed opening capital. Volatility uses nominal 252-observation scaling. Alpha is an annualised excess-return regression intercept against unlevered Core, not a CAGR gap; exploratory intervals use five-lag HAC errors. Appendix C explains the distinctions.

The specification was chosen after historical outcomes had been inspected. The later period is a retrospective period check, even where source filenames call it “confirmation”. It is not a pristine holdout. Overlapping windows, hindsight maximisation and synthetic regimes cannot produce independent future probabilities.

## 5. Unlevered Results

{{table:backtest_05}}

The absolute primary meets the stated joint growth/risk criterion against both comparators over the complete sample. Its CAGR gaps are **{{claim:unlevered_gap_core}} versus Core** and **{{claim:unlevered_gap_dimensional}} versus Dimensional**. Capped-relative results remain visible rather than being silently replaced.

The external-cost control for Dimensional removes investor transaction charges while retaining embedded NAV expenses and the remaining conventions. Its result remains below the primary over this sample; this does not isolate a causal factor premium or eliminate other product/universe differences. [Control table](#appendix-f)

## 6. Borrowed Results and Implementation Risks

### 6.1 Matched target exposure

{{table:backtest_06}}

At equal target exposure, the absolute primary again meets the full-period joint criterion. Its CAGR gaps are **{{claim:levered_gap_core}} versus borrowed Core** and **{{claim:levered_gap_dimensional}} versus borrowed Dimensional**. These are historical differences with disclosed realised-exposure and product-cost qualifications.

For the primary, borrowing changes CAGR from {{claim:unlevered_cagr}} to {{claim:levered_cagr}}, volatility from {{claim:unlevered_annualised_volatility}} to {{claim:levered_annualised_volatility}}, and maximum drawdown from {{claim:unlevered_maximum_drawdown}} to {{claim:levered_maximum_drawdown}}. Additional growth comes with additional total risk; it is not evidence of factor alpha.

{{figure:equity}}

*Investor equity after modelled investment trading and financing, on the main common calendar. This chart contains no subscriptions, administration-fee revenue or custody additions. The committed opening capital is preserved as the measurement base.*

{{figure:drawdown}}

*Observed drawdown at matched target exposure. The high-water mark includes committed initial capital, so opening charges remain included. Modelled NAV observations do not describe intraday lender exposure.*

### 6.2 Funding, costs and margin

Financing markup changes affect equity, trading signals and holdings, making performance locally non-monotone. The scan distinguishes small-residual equality from policy discontinuities; it does not establish one universally safe credit margin. Custody charges similarly change trading sequences, and an occasional higher ending value after added fees must not be marketed as a benefit of paying more.

The hypothetical boundary gap cases yield **{{claim:cures}} cures at the assumed NAV and {{claim:insolvent}} states already insolvent before cure**. Ordinary charges and extra liquidation friction are paid from proportional sales, with no cash injection. These cases are hypothetical maintenance-boundary states, not reconstructions of actual historical lender accounts or a promise that the lender permits that cure.

Actual account category, collateral eligibility, rate fixing, day count, debit/settlement conventions, liquidation timing and complete charges remain unconfirmed. Public dated banking evidence informs scenarios; it is not an individual credit offer.

## 7. Stability and Counter-Evidence

### 7.1 Continuing endpoints

{{table:backtest_07}}

Each endpoint continues from the same initial investment, with no capital restart. The endpoint/date comparison is distinct from the independently restarted early/later periods and entry tests. A final favourable growth ordering cannot establish stable performance at every earlier date.

### 7.2 Alpha, windows and risk

The primary's full-sample exploratory alpha intervals contain zero at both target exposures. The leveraged estimate is not convincingly positive. The rolling and restarted-entry tables preserve unfavourable comparisons and changing rankings. Counts of higher-CAGR windows describe overlapping retrospective intervals, not a probability of future outperformance.

The equity sleeves remain strongly exposed to shared markets. Return correlation differs from security overlap, and sparse holdings snapshots cannot explain the full historical return gap. Synthetic stresses challenge mechanics under imposed inputs rather than validate a future crash scenario.

## 8. Interpretation and Next Research

The revised simple rule produces favourable full-sample investor growth/risk comparisons under the unchanged research conventions. It gives the factor sleeves more permitted drift and retains leverage management separately. The earlier capped-relative rule remains a useful comparator; neither implementation is presented as a uniquely optimal prospective strategy.

Borrowing adds return and risk. Retrospective selection, time instability, uncertain alpha, costs, product differences and unresolved real-world execution/lending conditions remain central. Prospective evaluation of a fixed specification and concrete account evidence would address different questions from reproducing this historical calculation.

The capital-inflow/business model is a separate layer. Its historical branch uses the same portfolio inputs and policy but a shorter ten-project-year horizon and fee/flow feedback. Its flat, fixed-growth and imposed-loss controls remain hypothetical; main backtest CAGR must not be inserted as a constant return. Appendix L explains the connection. The coordinated companion report is the next assembly step.

---

## Appendices

The appendices retain the calculation families and qualifications behind the main conclusions. Table shapes may differ from the earlier report because primary and comparison rows are now explicit. Detailed evidence files are local research material; inclusion here does not make them public-release content.

{{table:backtest_08}}

<a id="appendix-a"></a>
### Appendix A. Allocations and Hindsight

{{table:backtest_09}}

The same eight design alternatives are shown under both current and retained rules. They are sensitivity cases, not weights selected to maximise the final report's return. Early/later outcomes remain in the full evidence file.

{{table:backtest_10}}

The bounded grid uses **legacy coupled absolute semantics**, not the new separated primary. Its display representatives and exact ties remain recorded. These ex-post maxima are neither global nor prospective optima and do not replace the agreed allocation.

<a id="appendix-b"></a>
### Appendix B. Policy Mechanics and Drift

{{table:backtest_11}}

All targets and bands concern gross invested assets. Equality at a boundary does not itself trigger a trade. The strict breach convention and next-observation execution remain unchanged. Separate debt-preserving sleeve and mixture-preserving leverage adjustments are different from legacy coupled absolute resets.

{{table:backtest_12}}

The policy comparison includes sleeve resets, calendar resets, no-sleeve trading and passive debt. “No sleeve resets” can still trade for leverage management; passive debt is a separate borrowed control. Costs, event counts and mean absolute sleeve drift remain visible. Broader bands do not guarantee lower overall risk or fewer events in every future path.

<a id="appendix-c"></a>
### Appendix C. Risk Measures and Alpha

{{table:backtest_13}}

Beta and Jensen alpha use common-calendar excess returns against unlevered Core. Annual alpha is the nominal-252 arithmetic intercept; the HAC interval is exploratory and unadjusted for selection or multiple testing. Treynor scales mean excess return by positive beta; Sortino uses the reference hurdle and all intervals in its downside-deviation denominator; Calmar divides CAGR by absolute maximum drawdown. None establishes multi-factor causal skill. [Definitions and source context](source_register.md)

<a id="appendix-d"></a>
### Appendix D. Periods, Rolling Windows and Entries

{{table:backtest_14}}

The early period ends in 2021; the later restart begins on the first common 2022 observation. Each has fresh opening charges and committed capital. These are retrospective splits.

{{table:backtest_15}}

Monthly continuing windows have no repeated entry charge; their wealth bases and observed dates differ from a fresh restart. Overlap prevents interpreting the shares as independent estimates of future success.

{{table:backtest_16}}

Fresh entries map requested dates to the first common available NAV. Every account restarts costs and capital; the later start naturally shortens the available endpoint window. Underwater durations and terminal censoring remain in the complete evidence rather than being assigned an unobserved recovery.

<a id="appendix-e"></a>
### Appendix E. Return Correlations

{{table:backtest_17}}

The long panel uses adjacent returns on the main common calendar. It is descriptive, not a full factor model or holdings-overlap measure.

{{table:backtest_18}}

The short Amundi panel ends at the main backtest's last common date; the product-performance table separately extends to its declared August-end overlap. Daily/monthly and conditional panels, rank correlations and rolling correlations have distinct scopes in the selected component run. No covariance or correlation is a guarantee of crisis diversification.

<a id="appendix-f"></a>
### Appendix F. Financing and Cost Sensitivities

{{table:backtest_19}}

Only comparator external transaction charges are removed. Embedded fund expenses and financing remain; this is not a no-cost reconstruction of the product.

{{table:backtest_20}}

The sequence changes allocation, exposure, reference financing and markup; the two zero-trading controls are separately labelled. Changes combine later accounting and intervention effects rather than an additive causal attribution.

{{table:backtest_21}}

Markup is above the observed reference, not the total borrowing rate. The factor rows use the absolute primary; their declared later-period restart differs from continuing full-history paths.

{{table:financing_crossings}}

The finite scan uses ten-bp steps and 25 local refinements, comparing each borrowed factor rule with its own unlevered counterpart. A fractional CAGR residual below 1e−6 receives the approximate-zero label; the remaining bracketed sign changes are labelled policy discontinuities. Labels classify the residual, not mathematical continuity or global completeness. A narrow unsampled crossing or tangency can be missed; jumps caused by interventions are not exact return-equality points. [Captured scan settings](../evidence/funding_gap_settings.json)

{{table:backtest_22}}

Current custody interpretations are separate from the baseline. Full-value versus excess-only private treatment and the legal-entity scenario retain their qualifications. Fees can change signals, so the net path effect need not be monotone.

{{table:joint_cost}}

Selected margin/spread cells compare each factor rule against matched Core with a strict higher-growth/no-higher-volatility/no-deeper-drawdown criterion. Their grid-wide outcomes are retrospective observations, not probabilities or a proof over all costs.

<a id="appendix-g"></a>
### Appendix G. Price-Gap Cures and Implementation

{{table:gap_cures}}

Each state starts at a hypothetical maintenance boundary. Debt remains after an instantaneous uniform price loss; post-gap equity must be positive before attempting sale-funded fees and debt repayment. Liquidation uses ordinary leg charges plus 100bp extra friction on the sale notional, aiming for 1.25x exposure after costs. Unavailable cure fields in insolvent states remain unavailable, not zeros. The assumed pro-rata cure geometry is shared across the two rules; it does not reconstruct their separate historical margin-call paths. [Captured cure settings](../evidence/funding_gap_settings.json)

Other maintenance and changing-collateral diagnostics are distinct from these fee-aware gap cases. No next-common-NAV assumption should be presented as a contractual cure window, actual bank permission or a loss bound. The dated source register preserves public evidence and the unconfirmed account scope.

<a id="appendix-h"></a>
### Appendix H. Artificial Market Regimes

{{table:backtest_23}}

These selected primary controls use prescribed artificial paths and one stated total-funding scenario. The complete reconstructed catalogue also retains alternative controls and funding settings. They are mechanical experiments, not generated historical provider observations, fitted premia, probabilities or worst-case bounds. The preliminary earlier catalogue stays an archive; no fresh reconstruction of its figures is claimed.

<a id="appendix-i"></a>
### Appendix I. Holdings and Historical Exposures

{{table:backtest_24}}

The table combines Core June, factor May and Dimensional November schedules. Units in the residual column are USD thousands. Individual rounded Dimensional security values explain retained aggregate differences; no balancing security is invented. Top-ten measures concern security lines rather than consolidated issuers. The subfund portfolio does not replace the user-confirmed USD NAV share class.

The later issuer snapshot is descriptive evidence after the backtest cutoff, not a synchronous historical attribution panel. Detailed country/name-overlap and second-reader records remain in the component run. Country assignment, security identity and unrounded valuations are outside the independent numeric PDF-page comparison. A complete daily historical security/sector exposure series is unavailable.

<a id="appendix-j"></a>
### Appendix J. Leveraged-Product Overlap

{{table:backtest_25}}

This table reports **cumulative return**, not main-period CAGR. It uses the genuine short common overlap from September 2025 through August 2026. Values are normalized to the first common post-entry observation; this removes modeled portfolio entry expenses, and no product/index investor brokerage or exit cost is invented. Daily-reset products and band-managed debt accounts differ economically, including at the same nominal target. The Amundi original download URL/date remain unknown.

<a id="appendix-k"></a>
### Appendix K. Identities, Assumptions and Evidence

{{table:backtest_26}}

The Dimensional ISIN is the author-confirmed mapping and is not embedded in the supplied Bloomberg workbook. Raw-provider integrity and instrument interpretation are different checks.

{{table:backtest_27}}

{{table:backtest_28}}

{{table:backtest_29}}

Numerical result-table cells retain source rows/fields or declared expressions in [table provenance](tables.json). Numerical prose and its occurrences are in [claim provenance](claims.json). The configuration, design, source-description and navigation tables contain separately declared manual context and use the captured baseline; this does not imply that every narrative sentence has independent expert approval. [Assembly and link checks](assembly_checks.json)

The [source/download register](source_register.md) and [captured detailed registry](../config/SOURCE_DOWNLOAD_REGISTER_2026-10-06.json) distinguish provider downloads, date evidence and missing provenance. File hashes authenticate snapshots, not infallible provider valuation or rights to republish datasets. Raw and detailed provider-derived evidence stays local until an explicit public-content selection.

This package assembles accepted calculations without rerunning their financial models. Component reproduction, installation and the final release remain separately testable tasks. No full reconstruction from an actual public release is claimed here.

<a id="appendix-l"></a>
### Appendix L. Assignment Scope and Capital-Inflows Connection

{{table:backtest_30}}

The report supplies research inputs for the team; narration, marketing, lecture connections and submission production remain separate. Main investment returns contain no external subscriptions or manager fee revenue.

{{table:historical_link}}

The historical business branch covers ten project years through October 2024, using the same accepted investment rule and market inputs. Coupled fees and hypothetical flows change trading, debt, financing and later signals. The overlay diagnostic applies the no-flow path without that feedback. Both differ from full-period strategy CAGR and from the preserved flat/fixed-growth/loss scenarios.

Use executed historical v2: actual flow-trading charges are posted to debt at borrowed exposure, and resulting leverage drift feeds the next original signal. It does not assert exact post-cost leverage preservation at fee discontinuities. Owner investment wealth, external equity and manager cash are different quantities; owner fees are conditional internal transfers and budgets remain outside the fund.

The coordinated capital-inflow report remains to be assembled with these distinctions and the same source/AI disclosure. This local version does not replace the original group package or publish research files.
