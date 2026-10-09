# Capital Inflows and Fund Economics

**Research report · 9 October 2026**  
USD {{claim:owner_capital_m}} million of initial owner capital · Historical and hypothetical fund experiments  
AI-assisted analysis and writing; tools, scope and responsibility are disclosed in the final section.

## Abstract

This study separates a shared investment for seven founders from a business serving external clients. A historical simulation executes the same factor portfolio and 1.25x leverage rules with assumed subscriptions, redemptions and a 5 bp annual fund fee over 3 October 2014-3 October 2024. Its steady-acquisition unit return is **{{historical:absolute_coupled_twr}} annually**. Fee financing also changes portfolio signals and historical performance without outside clients. In that scenario, full receipt of external fees generates approximately **USD 47,000** against **USD 455,000** of modelled business costs. Raising assets therefore does not fund the assumed operation or automatically improve founder wealth. Separate flat, fixed-growth and loss scenarios explore adjustable assumptions. Better borrowing terms from greater scale remain a hypothesis, not a mechanism in these calculations.

## 1. Research Question and Economic Framework

How much externally owned capital can specified client-acquisition schedules generate, and would external fee receipts cover the assumed business costs? How do returns, redemptions and subscription timing change that answer?

The concept begins with seven founders contributing USD one million each. Initial owner capital is modelled as an aggregate cohort, not seven individual cash-flow ledgers. The portfolio could serve their shared investment purpose without outside subscriptions; operating a fund business for external clients is a separate question.

Four quantities must remain separate. **Owner invested equity** is the owner's fund holding. **External invested equity** belongs to subscribing clients. **Total net fund assets** combine the two invested cohorts. **Manager cash** is held outside the fund and reflects fee receipts less the stated business costs. Assets raised from clients do not become owner wealth, and investment performance does not establish manager profitability.

Additional capital might improve access to financing or negotiated borrowing terms. This is an economic hypothesis: the backtest funding sensitivities vary assumed margins, but do not demonstrate an assets-to-pricing relationship. The historical inflow replay retains the same financing specification as the backtest; subscriptions do not automatically earn a lower margin.

Subscriptions buy units; redemptions return cash to investors. Closing external equity excludes cash already redeemed. Ending fund assets alone therefore cannot rank investor outcomes. Owner fees transferred to an owner-associated manager are internal transfers within the assumed owner group; they are not new externally earned revenue.

{{figure:accounts}}

*Figure 1. Two investor groups hold units in the same fund. Subscriptions and redemptions change investor holdings; fund fees leave the fund for the separate manager account. Operating costs are paid from manager cash. Owner-fee receipts are internal transfers when the manager belongs to the same owner group. Arrows describe the model, not a licensed or established legal structure.* [Account schematic: reader_figures.render](https://github.com/TheAlegsx/1_Repository/blob/24979b0b422c1f016a4b3a51e84420b3d701b5f7/Finance/MSCI%20World%20Factor%20Strategy/src/factor_portfolio/reader_figures.py#L15)

## 2. Assumptions and Accounting

### 2.1 Client acquisition and retention

The central ticket is {{claim:ticket_usd}}. Client equivalents may be fractional for monthly modelling and may include repeat subscriptions. They are proposed inputs, not signed clients or evidence of a sales funnel. First-year subscriptions begin in {{claim:launch_first_month}} and are distributed over {{claim:launch_months}}. [Client, fee and cost settings: inflow_acquisition.json](https://github.com/TheAlegsx/1_Repository/blob/cd861934faf1aaeca43ae57bde0d01ec68ee6a25/Finance/MSCI%20World%20Factor%20Strategy/config/inflow_acquisition.json).

**Table 1. Acquisition schedules before loss-year cuts** · [Client schedules: inflow_acquisition.json](https://github.com/TheAlegsx/1_Repository/blob/cd861934faf1aaeca43ae57bde0d01ec68ee6a25/Finance/MSCI%20World%20Factor%20Strategy/config/inflow_acquisition.json)

{{table:acquisition}}

Ordinary cases use {{claim:ordinary_attrition}} external-unit attrition; sales-stop/runoff uses {{claim:runoff_attrition}}. Each annual fraction becomes a constant equivalent monthly fraction. This is a fraction of existing external units, not the same fraction of annual subscriptions. Newly subscribed units can redeem from the following month. [Client, fee and cost settings: inflow_acquisition.json](https://github.com/TheAlegsx/1_Repository/blob/cd861934faf1aaeca43ae57bde0d01ec68ee6a25/Finance/MSCI%20World%20Factor%20Strategy/config/inflow_acquisition.json).

The schedules, ticket sizes and retention assumptions are not empirically calibrated. The strong schedule requires {{claim:strong_final_clients}} in the final year. Contacts, conversion rates, servicing capacity, client tickets and redemption evidence are needed before adopting a commercial plan. [Client, fee and cost settings: inflow_acquisition.json](https://github.com/TheAlegsx/1_Repository/blob/cd861934faf1aaeca43ae57bde0d01ec68ee6a25/Finance/MSCI%20World%20Factor%20Strategy/config/inflow_acquisition.json).

### 2.2 Fees and costs

**Table 2. Central business assumptions and sensitivities** · [Business costs and fees: inflow_acquisition.json](https://github.com/TheAlegsx/1_Repository/blob/cd861934faf1aaeca43ae57bde0d01ec68ee6a25/Finance/MSCI%20World%20Factor%20Strategy/config/inflow_acquisition.json)

{{table:business}}

The investor fee is a charge in the simulation, not a verified total expense ratio or necessarily the amount retained by the manager. Embedded investment-product costs, portfolio trading and financing, the added fund fee and outside-fund business costs are separate layers.

Business costs are paid outside the fund. They reduce manager cash rather than unit NAV. If any of these costs are instead charged to the fund, investor accounts require recalculation. The budget is illustrative, may overlap bundled provider invoices and includes no full-time salary provision. Taxes, unexpected legal costs and borrowing interest on manager deficits are excluded. A funding gap is an additional working-capital requirement, not an automatic withdrawal from the owner's invested capital.

### 2.3 Three ways of examining investment returns

| Calculation | Period and costs | Question answered |
| --- | --- | --- |
| Historical portfolio with flows (coupled simulation) | 3 Oct 2014-3 Oct 2024; observed investment path, trading, financing and added fund fee; business costs stay outside NAV | How do flows and fees interact with the actual strategy? |
| Return-path comparison (overlay) | Same historical horizon and added fund fee; the no-flow investment path already includes its trading and financing, but there is no feedback from client trades into holdings or debt | How different is the result if portfolio flow feedback is omitted? |
| Hypothetical return scenarios | Ten project years; imposed returns after underlying investment costs, before the added fund fee; business costs stay outside NAV | How do assumed returns, acquisition and timing change the accounts? |

**Historical branch:** actual market observations drive the same 60/15/10/15 portfolio, absolute ±5-percentage-point bands, separate 1.25x leverage with ±0.10 adjustments, and investment costs and financing used by the companion backtest. Its horizon is **3 October 2014–3 October 2024**, comprising {{historical:months}} project months. Fees, client schedules, redemptions and budgets are hypothetical. Acquisition plans and attrition are fixed; they do not adopt the annual-loss demand rule below. [Fund return comparison: historical_inflow_interpretation.compare_accounts](https://github.com/TheAlegsx/1_Repository/blob/cd861934faf1aaeca43ae57bde0d01ec68ee6a25/Finance/MSCI%20World%20Factor%20Strategy/src/factor_portfolio/historical_inflow_interpretation.py#L20).

**Hypothetical controls:** {{claim:return_paths}}. These are nominal returns after underlying investment costs but before the added fund fee, with no actual leveraged-portfolio replay. Annual returns become constant monthly returns through `(1 + annual return)^(1/12) - 1`; the monthly fee is deducted separately from opening assets. Losses are therefore smoothed within their year unless the loss-placement control is used. [Client, fee and cost settings: inflow_acquisition.json](https://github.com/TheAlegsx/1_Repository/blob/cd861934faf1aaeca43ae57bde0d01ec68ee6a25/Finance/MSCI%20World%20Factor%20Strategy/config/inflow_acquisition.json).

In hypothetical acquisition loss years, subscriptions are {{claim:stress_subscription_fraction}} and annual external-unit attrition rises to {{claim:stress_attrition}}. This is an imposed concurrent market-and-demand stress rather than a predictive rule. The separate timing experiment holds gross schedules and {{claim:timing_attrition_annual}} attrition fixed even in loss years, so it answers a different question. None of these return paths or demand rules is a forecast or worst-case bound. [Client, fee and cost settings: inflow_acquisition.json](https://github.com/TheAlegsx/1_Repository/blob/cd861934faf1aaeca43ae57bde0d01ec68ee6a25/Finance/MSCI%20World%20Factor%20Strategy/config/inflow_acquisition.json) · [Subscription schedules: inflow_timing.json](https://github.com/TheAlegsx/1_Repository/blob/cd861934faf1aaeca43ae57bde0d01ec68ee6a25/Finance/MSCI%20World%20Factor%20Strategy/config/inflow_timing.json).

### 2.4 Accounting sequence

In the hypothetical controls, each month applies the investment return and fee to opening assets, then redeems existing external units and issues new units. End-month subscriptions first earn returns and pay fees next month. Owner units stay fixed, with no personal withdrawals. [Monthly unit accounts: inflows.simulate](https://github.com/TheAlegsx/1_Repository/blob/cd861934faf1aaeca43ae57bde0d01ec68ee6a25/Finance/MSCI%20World%20Factor%20Strategy/src/factor_portfolio/inflows.py#L12).

`Closing assets = opening assets + investment P/L - investor fee + subscriptions - redemptions`

`External-business cash = external fee receipts - fixed costs - acquisition costs - servicing costs - setup costs`

The historical execution additionally marks portfolio prices, accrues financing and executes prior investment signals. It charges the fund fee on previous-event net fund equity and adjusts positions for cash flow before forming the next signal. Flow trades preserve the current mixture and use pre-cost exposure rather than resetting target weights. At borrowed exposure, flow-trading expenses are posted to debt; post-cost leverage can drift and change subsequent funding and signals. Exact post-cost leverage preservation is not assumed at commission discontinuities. [Fund units and flows: coupled_inflow_accounting.simulate_coupled](https://github.com/TheAlegsx/1_Repository/blob/cd861934faf1aaeca43ae57bde0d01ec68ee6a25/Finance/MSCI%20World%20Factor%20Strategy/src/factor_portfolio/coupled_inflow_accounting.py#L48).

## 3. No-External-Investor Reference

At the {{claim:fee_bps}} and without external subscriptions, hypothetical owner equity after ten years is {{claim:no_flow_equities}}. Under a fixed return path, external subscriptions do not change owner unit performance. This invariance is not imposed on the historical coupled portfolio, where fees and flow trades can alter later investment accounts. [Client, fee and cost settings: inflow_acquisition.json](https://github.com/TheAlegsx/1_Repository/blob/cd861934faf1aaeca43ae57bde0d01ec68ee6a25/Finance/MSCI%20World%20Factor%20Strategy/config/inflow_acquisition.json) · [Acquisition accounts: inflow_scenarios.acquisition](https://github.com/TheAlegsx/1_Repository/blob/cd861934faf1aaeca43ae57bde0d01ec68ee6a25/Finance/MSCI%20World%20Factor%20Strategy/src/factor_portfolio/inflow_scenarios.py#L14).

A commercial operation with zero external clients still incurs the assumed business costs. The founders could instead pursue a shared investment arrangement, but its applicable costs and governance would need a separate assessment. The no-external-investor cases here retain the stated business budgets; they are not a newly calculated lean founders-only arrangement. Appendix B includes the historical no-flow/no-added-fund-fee control; ordinary investment trading and financing costs remain in it.

## 4. Historical Portfolio and Fund Results

### 4.1 Fund fees and client-plan feedback

The historical results use the ±5-percentage-point portfolio and separate leverage management. They are not calculated by inserting the full-period backtest CAGR as a constant monthly return. The full investment backtest continues to August 2026, whereas the business experiment ends in October 2024. Horizon, the added fund fee and flow feedback make the headline return measures different.

The **return-path comparison (overlay)** applies the no-flow portfolio's dated return path to cohorts without executing subscriptions, redemptions or fee financing through the holdings and debt account. Its unit return is invariant across plans at a fixed fee schedule. The simulated fund unit return can vary because client transactions and fee financing change subsequent portfolio holdings and debt.

**Table 3. Steady acquisition: coupled execution and overlay** · [Fund return comparison: historical_inflow_interpretation.compare_accounts](https://github.com/TheAlegsx/1_Repository/blob/cd861934faf1aaeca43ae57bde0d01ec68ee6a25/Finance/MSCI%20World%20Factor%20Strategy/src/factor_portfolio/historical_inflow_interpretation.py#L20)

{{table:historical_returns}}

For the main strategy, the steady-acquisition fund unit return differs from the overlay by {{historical:absolute_gap}}. This is the combined effect of fee/debt/signal feedback and the client plan. It is not an isolated customer-flow effect. Direct flow-trading charges are {{historical:absolute_flow_cost}}; Table 4 shows that a substantial return difference already exists without customers. The capped-relative comparison is retained in Appendix B. [Fund return comparison: historical_inflow_interpretation.compare_accounts](https://github.com/TheAlegsx/1_Repository/blob/cd861934faf1aaeca43ae57bde0d01ec68ee6a25/Finance/MSCI%20World%20Factor%20Strategy/src/factor_portfolio/historical_inflow_interpretation.py#L20).

**Table 4. Separating fund-fee feedback from the client plan** · [Fee and account bridge: inflow_fee_diagnostics.summaries](https://github.com/TheAlegsx/1_Repository/blob/1c63b98051771cbcfbf043c1ab62e0d7cec3ed5f/Finance/MSCI%20World%20Factor%20Strategy/src/factor_portfolio/inflow_fee_diagnostics.py#L9)

{{detail:fee_chain}}

All four comparisons use the same USD 7 million opening owner capital and 3 October 2014-3 October 2024 window. The executed accounts retain the same weights, absolute sleeve bands, leverage target, financing and trading rules. Returns use unrounded values and elapsed calendar years; owner units remain fixed. Manager cash and outside-fund business costs are excluded from these invested-equity amounts.

Without external customers, the executed fee-paying account falls below the overlay by **{{detail:no_client_gap}} per year**. Adding the steady client plan changes annual unit return by another **{{detail:additional_plan_gap}}**. The no-client comparison accounts for **{{detail:no_client_gap_share}}** of the total coupled-minus-overlay return gap. This chained arithmetic comparison separates existing account outcomes; it is not an order-independent causal attribution of all interacting mechanisms.

**Table 5. Accounting for the fee-paying no-client wealth shortfall, USD** · [Fee and account bridge: inflow_fee_diagnostics.summaries](https://github.com/TheAlegsx/1_Repository/blob/1c63b98051771cbcfbf043c1ab62e0d7cec3ed5f/Finance/MSCI%20World%20Factor%20Strategy/src/factor_portfolio/inflow_fee_diagnostics.py#L9)

{{detail:wealth_bridge}}

This signed identity explains the ending-equity difference between the fee-paying no-client account and the no-added-fee investment control. The investment-price P/L difference reflects the positions actually held on their different paths. Lower financing costs partly offset that lost investment P/L. The fee charge, financing difference and transaction costs are separate ledger components; they must not be counted again inside the price P/L component.

**Table 6. Existing intervention records with and without the fund fee** · [Fee and account bridge: inflow_fee_diagnostics.summaries](https://github.com/TheAlegsx/1_Repository/blob/1c63b98051771cbcfbf043c1ab62e0d7cec3ed5f/Finance/MSCI%20World%20Factor%20Strategy/src/factor_portfolio/inflow_fee_diagnostics.py#L9)

{{detail:fee_events}}

In the borrowed fund, the added fee is posted to debt. It reduces net equity and can change the next portfolio signal even without subscriptions or redemptions. On 30 September 2022, leverage is **{{detail:threshold_fee}}** with the fee, versus **{{detail:threshold_control}}** without it. Only the fee-paying case breaches the 1.35x upper adjustment boundary and executes the signalled reduction on 3 October 2022. The earlier leverage increase also occurs on a different date. These deterministic threshold responses explain why a small fee can have a larger historical effect than a fixed-return deduction. The example establishes sensitivity in this ten-year fund window, not a probability of future loss or a measured fee effect on the longer full-sample backtest.

{{figure:historical_nav}}

*Figure 2. Historical fund unit performance under steady acquisition and the return-path comparison. The lower panel shows 100 x (coupled unit NAV / overlay unit NAV - 1), showing combined fee/signal and client-plan feedback. This relative wealth difference is not the annualised return gap or an isolated customer-flow effect. Both paths include the added fee; investment observations are historical, while client schedules are assumed.* [Reader charts from recorded evidence: reader_figures.render](https://github.com/TheAlegsx/1_Repository/blob/24979b0b422c1f016a4b3a51e84420b3d701b5f7/Finance/MSCI%20World%20Factor%20Strategy/src/factor_portfolio/reader_figures.py#L15)

### 4.2 Ownership and cash already returned to investors

**Table 7. Main strategy: historical acquisition outcomes, USD million** · [Fund units and flows: coupled_inflow_accounting.simulate_coupled](https://github.com/TheAlegsx/1_Repository/blob/cd861934faf1aaeca43ae57bde0d01ec68ee6a25/Finance/MSCI%20World%20Factor%20Strategy/src/factor_portfolio/coupled_inflow_accounting.py#L48)

{{table:ownership}}

The founder investment closes at **USD 19.60 million without external flows**, versus **USD 19.41 million with steady acquisition**. Under the unchanged financing terms, larger fund assets therefore do not automatically improve the founders' invested equity. These values exclude the separate manager account. The large asset totals include client-owned capital. Owner invested equity excludes outside manager cash and personal withdrawals. Redemptions are cash returned to investors and are excluded from closing external equity; they are not automatically destroyed wealth.

Fund-unit TWR measures the compounded unit performance. Aggregate external MWR also accounts for when clients subscribe and redeem. Subscriptions are negative investor cash flows; redemptions and terminal external equity are positive. Historical MWR uses the actual transaction dates; Appendix B records its annualisation and root-search conventions. The external-investor window begins at the first subscription and differs from the full fund window. No-investor MWR is unavailable, never zero. [Dated investor return: historical_inflow_diagnostics.dated_mwr](https://github.com/TheAlegsx/1_Repository/blob/cd861934faf1aaeca43ae57bde0d01ec68ee6a25/Finance/MSCI%20World%20Factor%20Strategy/src/factor_portfolio/historical_inflow_diagnostics.py#L29).

### 4.3 Manager cash and working capital

**Table 8. Main strategy, steady acquisition: historical manager accounts, USD** · [Manager cash: historical_inflow_diagnostics.manager_accounts](https://github.com/TheAlegsx/1_Repository/blob/cd861934faf1aaeca43ae57bde0d01ec68ee6a25/Finance/MSCI%20World%20Factor%20Strategy/src/factor_portfolio/historical_inflow_diagnostics.py#L94)

{{table:manager}}

At full fee receipt, external receipts are {{historical:absolute_external_receipts}} against {{historical:absolute_manager_costs}} of business costs. Peak external-business funding need is {{historical:absolute_peak_gap}}. Including conditional owner-fee receipts changes manager treasury but does not create external profit; these fees are already deducted from owner invested equity. [Manager cash: historical_inflow_diagnostics.manager_accounts](https://github.com/TheAlegsx/1_Repository/blob/cd861934faf1aaeca43ae57bde0d01ec68ee6a25/Finance/MSCI%20World%20Factor%20Strategy/src/factor_portfolio/historical_inflow_diagnostics.py#L94).

{{figure:manager_cash}}

*Figure 3. Historical steady-acquisition scenario at the 5 bp investor fee and full manager receipt: external fee receipts versus modelled outside-fund business costs over ten years. Their difference is an approximately USD 408,000 funding deficit. Owner-fee transfers are excluded from the external revenue bar.* [Fee and cost chart: reader_figures.render](https://github.com/TheAlegsx/1_Repository/blob/24979b0b422c1f016a4b3a51e84420b3d701b5f7/Finance/MSCI%20World%20Factor%20Strategy/src/factor_portfolio/reader_figures.py#L15)

Across the retained historical grid, {{historical:negative_manager_cases}} of {{historical:manager_cases}} manager labels have negative terminal external-business cash. The labels include repeated no-flow economics and controls, so this is not a count of independent observations or a probability of failure. The result challenges the assumed fee-and-cost combination, not every possible fund business. [Manager cash: historical_inflow_diagnostics.manager_accounts](https://github.com/TheAlegsx/1_Repository/blob/cd861934faf1aaeca43ae57bde0d01ec68ee6a25/Finance/MSCI%20World%20Factor%20Strategy/src/factor_portfolio/historical_inflow_diagnostics.py#L94).

Historical conditional treasury applies the same receipt fraction to owner and external fees, assuming monthly availability. The hypothetical treasury sensitivity in Appendix A has its own full owner-fee receipt convention. Neither establishes actual bank-account funding without settlement and contract terms. Peak gaps are measured at month-end; intramonth needs are excluded.

## 5. Hypothetical Scenarios and Sensitivities

### 5.1 Raising assets does not establish profitable operations

**Table 9. Acquisition under the hypothetical {{claim:growth_pct}} path** · [Acquisition accounts: inflow_scenarios.acquisition](https://github.com/TheAlegsx/1_Repository/blob/cd861934faf1aaeca43ae57bde0d01ec68ee6a25/Finance/MSCI%20World%20Factor%20Strategy/src/factor_portfolio/inflow_scenarios.py#L14)

{{table:hypothetical_outcomes}}

Steady acquisition generates {{claim:steady_gross}} and {{claim:steady_fees}} over ten years. Its peak business funding gap is {{claim:steady_peak}}; the strong schedule's gap is {{claim:strong_peak}}. Acquisition spending occurs on subscriptions, while a low annual fee is earned over the time capital remains invested. More clients can therefore increase working-capital needs under this cost structure. [Acquisition accounts: inflow_scenarios.acquisition](https://github.com/TheAlegsx/1_Repository/blob/cd861934faf1aaeca43ae57bde0d01ec68ee6a25/Finance/MSCI%20World%20Factor%20Strategy/src/factor_portfolio/inflow_scenarios.py#L14).

A simple illustration explains the pressure: a USD 250,000 subscription incurs **USD 1,250** at the assumed 0.5% acquisition charge, while the 5 bp annual fee yields only **USD 125 per year** on a constant USD 250,000 balance, before servicing and fixed costs. The simulation additionally incorporates changing balances, redemptions and receipt terms; this illustration is not a payback forecast.

### 5.2 The fee rate and the amount actually received

**Table 10. Steady acquisition: fee sensitivity under {{claim:growth_pct}}** · [Fee scenarios: inflow_results.sensitivity_tables](https://github.com/TheAlegsx/1_Repository/blob/cd861934faf1aaeca43ae57bde0d01ec68ee6a25/Finance/MSCI%20World%20Factor%20Strategy/src/factor_portfolio/inflow_results.py#L55)

{{table:fees}}

Higher fees reduce owner invested wealth. They also improve manager receipts if client counts, redemptions and receipt terms stay fixed; that fixed-demand assumption is not evidence that clients accept the higher charge. A positive final-year manager result does not imply recovery of startup and earlier losses.

At {{claim:illustrative_bps}}, the {{claim:illustrative_closing_deficit}} follows a {{claim:illustrative_peak}} in {{claim:illustrative_peak_month}}. Working capital must cover the lowest balance on the path rather than only the final year. The conditional owner-transfer comparison is shown in Appendix A. [Sensitivity settings: inflow_controls.json](https://github.com/TheAlegsx/1_Repository/blob/cd861934faf1aaeca43ae57bde0d01ec68ee6a25/Finance/MSCI%20World%20Factor%20Strategy/config/inflow_controls.json) · [Loss timing: inflow_controls.loss_controls](https://github.com/TheAlegsx/1_Repository/blob/cd861934faf1aaeca43ae57bde0d01ec68ee6a25/Finance/MSCI%20World%20Factor%20Strategy/src/factor_portfolio/inflow_controls.py#L99).

At the baseline fee and servicing assumptions, full receipt leaves {{claim:net_margin_bps}} of external assets for fixed and acquisition costs; {{claim:half_receipt}} leaves {{claim:partial_margin_bps}}. The full sensitivity materials also vary tickets, receipt fractions and fixed/acquisition/servicing budgets. These adjustable inputs are not provider quotes or approved fee terms. [Net fee arithmetic: inflow_report.prose_claims](https://github.com/TheAlegsx/1_Repository/blob/cd861934faf1aaeca43ae57bde0d01ec68ee6a25/Finance/MSCI%20World%20Factor%20Strategy/src/factor_portfolio/inflow_report.py#L42) · [Client, fee and cost settings: inflow_acquisition.json](https://github.com/TheAlegsx/1_Repository/blob/cd861934faf1aaeca43ae57bde0d01ec68ee6a25/Finance/MSCI%20World%20Factor%20Strategy/config/inflow_acquisition.json).

### 5.3 Equal gross subscriptions at different times

A controlled experiment distributes {{claim:timing_gross}} of gross subscriptions across five schedules: constant monthly, linearly increasing monthly, even tranches, early tranches and late tranches. Subscriptions begin no earlier than {{claim:launch_first_month}}. This matches gross fundraising rather than net flows or closing assets. [Subscription schedules: inflow_timing.json](https://github.com/TheAlegsx/1_Repository/blob/cd861934faf1aaeca43ae57bde0d01ec68ee6a25/Finance/MSCI%20World%20Factor%20Strategy/config/inflow_timing.json) · [Client, fee and cost settings: inflow_acquisition.json](https://github.com/TheAlegsx/1_Repository/blob/cd861934faf1aaeca43ae57bde0d01ec68ee6a25/Finance/MSCI%20World%20Factor%20Strategy/config/inflow_acquisition.json).

**Table 11. Selected timing cases under {{claim:growth_pct}}** · [Subscription timing: inflow_scenarios.timing](https://github.com/TheAlegsx/1_Repository/blob/cd861934faf1aaeca43ae57bde0d01ec68ee6a25/Finance/MSCI%20World%20Factor%20Strategy/src/factor_portfolio/inflow_scenarios.py#L80)

{{table:timing}}

Earlier cohorts pay fees for longer and face more redemption attrition. Later subscriptions can leave more assets in the fund at the endpoint while providing less earlier fee income. Cash already redeemed remains an investor outcome, so higher closing AUM does not by itself establish higher investor wealth. Owner invested equity is {{claim:owner_growth_equity}} in all these fixed-return cases. [Acquisition accounts: inflow_scenarios.acquisition](https://github.com/TheAlegsx/1_Repository/blob/cd861934faf1aaeca43ae57bde0d01ec68ee6a25/Finance/MSCI%20World%20Factor%20Strategy/src/factor_portfolio/inflow_scenarios.py#L14).

For the later-loss path, {{claim:later_return_path}}, unit TWR is identical across timing schedules while external MWR differs. Appendix B shows representative return measures. Late subscriptions avoid much of the stipulated loss, but clients cannot infer future loss dates from this retrospective illustration. [Client, fee and cost settings: inflow_acquisition.json](https://github.com/TheAlegsx/1_Repository/blob/cd861934faf1aaeca43ae57bde0d01ec68ee6a25/Finance/MSCI%20World%20Factor%20Strategy/config/inflow_acquisition.json).

Moving the same net annual loss into different individual months changes the subscription cohorts exposed to it. The early-tranche terminal-asset range is {{claim:early_loss_range}} despite unchanged annual net unit performance. Appendix B retains selected ranges. Smoothing losses across a year therefore suppresses a material timing sensitivity; these deterministic placements are not probabilities or worst-case limits. [Loss timing: inflow_controls.loss_controls](https://github.com/TheAlegsx/1_Repository/blob/cd861934faf1aaeca43ae57bde0d01ec68ee6a25/Finance/MSCI%20World%20Factor%20Strategy/src/factor_portfolio/inflow_controls.py#L99).

## 6. Discussion and Conclusion

The study separates investment outcomes from fundraising and business economics. A large part of the coupled-minus-overlay investment-return gap already arises without external customers: fee financing changes portfolio signals and holdings. Customer acquisition adds further interactions. The historical fee effect therefore cannot be represented solely by subtracting the quoted annual fee from an unchanged investment path. The historical branch executes the actual strategy with assumed investor flows and an added fund fee; the hypothetical branches isolate adjustable return, demand and timing assumptions. Their horizons and accounting should remain distinct.

External subscriptions can enlarge fund assets without becoming owner wealth. At the assumed low fee and the stated costs, the retained historical manager accounts require additional working capital. Strong fundraising alone does not resolve that shortfall. Fee retention, acquisition spending and servicing costs must be discussed together.

These commercial results do not by themselves reject the founders' shared investment purpose. External capital could expand that arrangement and might improve financing terms, but neither benefit is established by larger asset totals alone. Investment usefulness, conditional financing economies and manager profitability should therefore be assessed separately.

The next substantive inputs are evidenced client counts, tickets, redemption behaviour, fee-sharing contracts, provider invoices and the source of manager working capital. These would support a recalculation of an explicit business design. Historical investment performance cannot supply missing commercial evidence or executable credit terms. Personal withdrawals, tax, inflation and retirement sufficiency require a separate owner-wealth analysis.

The [companion portfolio backtest](BACKTEST_RESEARCH_2026-10-07.md) presents investment performance, the MSCI World benchmark and brief Dimensional and Amundi comparisons. It contains no investor subscriptions or outside-fund manager revenue.

## Sources and Data

{{sources:inflow}}

## Reproducibility Materials

The blue links open the responsible function or configuration on GitHub. [The calculation map](https://github.com/TheAlegsx/1_Repository/blob/main/Finance/MSCI%20World%20Factor%20Strategy/docs/REPORT_CALCULATION_MAP.md) identifies exact rows, fields and generated evidence paths. Code links use fixed snapshots. The prepared code and separately supplied original investment data reconstruct both historical and hypothetical accounts. Complete monthly ledgers, return-search records, additional sensitivities and source-cell bindings remain in the accompanying calculation materials. Provider originals stay local.

## Appendix A. Hypothetical Scenario Overview

**Table A1. Closing total fund assets under all twenty acquisition combinations, USD million** · [Acquisition accounts: inflow_scenarios.acquisition](https://github.com/TheAlegsx/1_Repository/blob/cd861934faf1aaeca43ae57bde0d01ec68ee6a25/Finance/MSCI%20World%20Factor%20Strategy/src/factor_portfolio/inflow_scenarios.py#L14)

{{table:scenario_matrix}}

Columns distinguish Flat 0%, Fixed 6%, early loss and later loss. Acquisition loss cases include halved subscriptions and higher attrition. These totals include owner capital and external equity; they are not consolidated investor wealth or probabilities.

**Table A2. External-business funding and conditional owner-fee receipts, USD** · [Funding gaps: inflow_treasury.treasury_controls](https://github.com/TheAlegsx/1_Repository/blob/cd861934faf1aaeca43ae57bde0d01ec68ee6a25/Finance/MSCI%20World%20Factor%20Strategy/src/factor_portfolio/inflow_treasury.py#L43)

{{table:treasury}}

The hypothetical illustration assumes 100% internal owner-fee receipt at monthly accrual, no redistribution to owners, tax or settlement delay. These internal transfers are already deducted from invested owner equity and must not be counted twice as consolidated wealth.

## Appendix B. Return and Timing Controls

**Table B1. Aggregate external investor returns under the hypothetical later loss** · [Investor returns: inflow_returns.external_investor_returns](https://github.com/TheAlegsx/1_Repository/blob/cd861934faf1aaeca43ae57bde0d01ec68ee6a25/Finance/MSCI%20World%20Factor%20Strategy/src/factor_portfolio/inflow_returns.py#L65)

{{table:investor_returns}}

Hypothetical MWR solves equal-month cash-flow IRR and annualises over twelve months. It is not dated transaction XIRR or an individual client's return. Timing schedules and 10% annual unit attrition stay fixed in these loss cases, unlike the acquisition demand stress. [Cash-flow IRR: inflow_returns.money_weighted_return](https://github.com/TheAlegsx/1_Repository/blob/cd861934faf1aaeca43ae57bde0d01ec68ee6a25/Finance/MSCI%20World%20Factor%20Strategy/src/factor_portfolio/inflow_returns.py#L14).

**Table B2. Within-year loss placement with matched annual net unit performance** · [Loss timing: inflow_controls.loss_controls](https://github.com/TheAlegsx/1_Repository/blob/cd861934faf1aaeca43ae57bde0d01ec68ee6a25/Finance/MSCI%20World%20Factor%20Strategy/src/factor_portfolio/inflow_controls.py#L99)

{{table:loss_ranges}}

The loss is concentrated into each possible month while preserving the same net annual unit multiplier. With monthly fee `f` and smooth return `r`, the matched multiplier is `G = (1 + r - f)^12`; the single gross shock is `G / (1 - f)^11 - 1 + f`. Subscriptions and each layer's redemption convention remain fixed within the control. Ranges use unrounded endpoints and do not bound actual markets. [Loss timing: inflow_controls.loss_controls](https://github.com/TheAlegsx/1_Repository/blob/cd861934faf1aaeca43ae57bde0d01ec68ee6a25/Finance/MSCI%20World%20Factor%20Strategy/src/factor_portfolio/inflow_controls.py#L99).

**Table B3. Historical no-flow/no-added-fund-fee controls** · [Historical controls: historical_inflow_replay.calculate_replays](https://github.com/TheAlegsx/1_Repository/blob/cd861934faf1aaeca43ae57bde0d01ec68ee6a25/Finance/MSCI%20World%20Factor%20Strategy/src/factor_portfolio/historical_inflow_replay.py#L22)

{{table:historical_controls}}

The controls retain ordinary investment entry, trading and financing costs. They reconcile to the investment paths over the shorter business horizon. No external cohort is invested, so external MWR is unavailable.

**Table B4. Steady acquisition: retained capped-relative comparison** · [Existing comparison cells: historical_inflow_interpretation.compare_accounts](https://github.com/TheAlegsx/1_Repository/blob/cd861934faf1aaeca43ae57bde0d01ec68ee6a25/Finance/MSCI%20World%20Factor%20Strategy/src/factor_portfolio/historical_inflow_interpretation.py#L20)

{{table:historical_relative}}

Historical MWR annualises actual dated cash flows using elapsed days divided by 365.2425. One root found by a finite scan does not establish global uniqueness or detection of every tangency. These implementation qualifications differ from the equal-month IRR convention used by hypothetical controls.

## AI Assistance and Responsibility

{{disclosure:author}}

This declaration concerns Alex's research contribution. It does not attribute unverified AI use to other group members or future video narration.
