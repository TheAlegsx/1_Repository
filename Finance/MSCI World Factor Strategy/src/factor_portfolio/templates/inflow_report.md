# Capital Inflows, Investor Outcomes and Fund Economics

**Reconstructed working copy of academic discussion draft, version 4 · 3 October 2026**  
USD {{claim:owner_capital_m}} million of owner capital; ten scenario years; historical investment research remains separate.

This working copy rebuilds the version-4 numerical content with a new calculation workflow. Text and interpretations are retained or adapted manually from that draft and reviewed against the configuration snapshots recorded for this template. It is not a newly approved group version or a public release. See the [run manifest](../run_manifest.json), [text claim sources](claims.json) and [retained template review](template_review.json).

## 1. Research Question

How much external capital could specified client-acquisition schedules generate, and would external fee receipts cover explicitly modelled business costs? How do weaker returns, redemptions, ticket sizes, fee terms and the timing of equal gross subscriptions change that answer without confusing external investor capital with owner wealth?

The version-4 source report combined a revised acquisition study and a matched-volume timing experiment. Their reconstructed calculations are included in this run. Earlier drafts remain historical references outside this generated bundle. The schedules are discussion inputs, not better-supported forecasts. The historical investment backtest is a separate study; its reconstruction remains pending and its return is not used as a business forecast.

## 2. What the Challenge Changed

The former good-sales schedule assumed USD 55 million of gross subscriptions without an acquisition mechanism. Its surge assumed USD 1.092 billion. Those remain conditional scale illustrations in the previous report and are excluded from this revision's core comparisons.

This study instead states client equivalents and ticket sizes, delays first-year subscriptions until {{claim:launch_first_month}}, raises ordinary annual redemptions from 5% to {{claim:ordinary_attrition_pct}}, and reduces subscriptions during imposed negative-return years. It replaces a cost-free sales narrative with acquisition, servicing, startup and inflating fixed costs. None of these new values is empirically calibrated; lower inflows or higher costs are not automatically more accurate.

The proposed annual fee remains **{{claim:baseline_fee}}**. The term means an investor charge in this simulation, not a verified total expense ratio, a bank quote or necessarily the amount retained by the manager. Fee sensitivity does not approve a new fee.

## 3. Assumptions, Provenance and Challenges

### 3.1 External client acquisition

The central ticket is {{claim:ticket_usd}}. Client equivalents allow fractional monthly modelling and do not describe signed clients. Counts below are new gross subscriptions; repeat subscriptions can also make up the equivalents. The {{claim:launch_delay}} concentrates first-year subscriptions into {{claim:launch_months}}. Existing clients can redeem independently.

{{table:01_acquisition_assumptions}}

Tickets of {{claim:alternative_tickets}} are tested separately. Counts, tickets and launch timing are researcher-proposed inputs with no sales funnel or client evidence. Strong acquisition requires {{claim:strong_final_clients}} in year 10; it is an ambitious schedule, not a probability-weighted outcome. We need contacts, conversion rates, capacity and actual ticket estimates before calling any schedule a business plan.

### 3.2 Redemptions and return paths

Ordinary cases assume {{claim:ordinary_attrition}} external-unit attrition; the sales-stop case assumes {{claim:runoff_attrition}}. In an imposed negative-return year, subscriptions are {{claim:stress_subscription_fraction}} and annual external-unit attrition rises to {{claim:stress_attrition}}. Each annual redemption fraction becomes a constant equivalent monthly fraction. It describes units of existing investors, not {{claim:stress_attrition}} of a year's total inflows. New subscriptions can redeem from the following month.

This is a transparent **concurrent stress assumption**, not a predictive rule that knows future annual returns. It does not capture lagged disappointment, liquidity gates or clustered redemptions. The original independent-flow structure remains available as a control in the calculations.

Four uncalibrated annual investment paths are retained or added: {{claim:return_paths_emphasised}}. The later loss tests an established external cohort rather than only a largely owner-funded launch. These are nominal returns assumed after underlying investing costs but before the proposed fund fee. There is no debt or actual strategy replay. No return path is an expected return or a worst-case bound.

Investment returns are also converted geometrically: each annual assumption becomes the constant monthly rate `(1 + annual return)^(1/12) − 1`. Thus {{claim:loss_annual_pct}} is spread as {{claim:smooth_loss_monthly}} each month, rather than placed in a single loss month. The monthly fee is deducted separately from opening assets. This smooth within-year path is a modelling assumption; the loss-placement control in Section 7 tests its consequences.

### 3.3 Business costs and receipt of fees

{{table:02_business_assumptions}}

Costs are paid outside the fund by the modelled manager. Thus they reduce manager cash, not unit NAV. If the fund must pay any of these costs additionally, investor returns require a separate recalculation; the present net-return assumption must not be used to hide them. Categories are illustrative and may overlap real bundled provider invoices; quote mapping is needed before adding actual amounts. Taxes, remuneration beyond the stated budget, unexpected legal costs and financing of negative manager cash are excluded. Cumulative funding gaps are additional capital needs, not automatically paid from the {{claim:owners_capital}} invested in the fund.

The basic distinction between management fees and other operating expenses is supported by [Investor.gov's fee guidance](https://www.investor.gov/introduction-investing/general-resources/news-alerts/alerts-bulletins/investor-bulletins/mutual-fund-and-etf-fees-and-expenses-investor-bulletin). That US investor-education source is used for terminology only; it does not validate our numbers or determine a Swiss fund structure. All numerical inputs and provenance are in [captured acquisition assumptions](../config/inflow_acquisition.json).

## 4. Accounting and Validation

Each month applies the investment return and fee to opening assets, then redeems existing external units and issues new units. End-month subscriptions earn returns and pay fees starting next month. Owner units remain fixed; no personal withdrawals are included.

`Closing assets = opening assets + investment P/L − investor fee + subscriptions − redemptions`

`Manager cash = manager receipt fraction × external-cohort fee − fixed costs − acquisition costs − servicing costs − setup costs`

The reported manager-cash measure is external-client economics: owner fees are internal transfers within the assumed owner group and are excluded from incremental external business receipts. Actual manager treasury can additionally receive these internal fees, depending on the contract and settlement. Section 8 reconciles both definitions without counting an internal transfer as external profit. Owner invested equity is not consolidated wealth including outside cash. Fund performance and manager profitability are distinct measures.

The acquisition grid comprises {{claim:acquisition_cases}} return/flow cases and {{claim:acquisition_rows}} monthly observations. An independent cash-asset recurrence and cohort accumulation check closing assets, fees and the invariant owner cohort against newly generated monthly accounts. [Independent controls](../controls/loss_controls.json) record the scope and residuals. The separate timing layer contains {{claim:timing_cases}} cases and {{claim:timing_rows}} monthly observations; it retains equal gross totals and cohort accounts. These are two experimental grids with overlapping no-flow controls, not {{claim:baseline_cases}} unique economic scenarios. The original version-3 consolidation changed presentation only; the version-4 source report added audit-derived disclosures and diagnostic tables. This working copy rebuilds the numerical content rather than relying on those historical verification files. Accounting checks do not establish economic plausibility.

## 5. No-Flow Reference First

With the unchanged {{claim:fee_bps}} and no external flows, owner capital at year 10 is {{claim:no_flow_equities}}.

The original no-flow investor baseline is preserved. A zero-client commercial operation under this revision still incurs costs, however. This business counterfactual should not be mistaken for the cost of a personal portfolio: a private own-wealth investment without a fund business may avoid the assumed setup and sales infrastructure.

## 6. Inflow Outcomes and Subscription Timing

### 6.1 Client-acquisition scenarios

The table isolates acquisition under the {{claim:main_return_path}} and {{claim:fee_bps}}. Scheduled subscriptions are not guaranteed realised amounts; bad-year cuts affect the loss cases in Appendix A.

{{table:03_acquisition_outcomes}}

{{figure:figure_1}}

*Figure 1. Total fund assets, including owner capital; all cases share the same unit return. The added assets belong to external investors. Axes retain the full paths.*

Steady acquisition generates {{claim:steady_gross}} over ten years and {{claim:steady_fees}}. Its peak cumulative business funding gap is {{claim:steady_peak}}. Under strong acquisition the gap is {{claim:strong_peak}}. Scale alone does not eliminate costs or funding needs.

### 6.2 Equal gross subscriptions, different timing

A separate controlled experiment distributes the same {{claim:timing_gross}} of gross subscriptions in five ways: constant monthly payments, linearly increasing monthly payments, evenly spaced {{claim:timing_tranche}} tranches, early tranches and late tranches. No case subscribes before {{claim:launch_first_month}}. This isolates timing rather than changing the total amount raised.

{{figure:figure_2}}

*Figure 2. Cumulative gross subscriptions. All five flow cases end at {{claim:timing_gross}}; the no-flow reference is separate. Constant monthly inflows give linear cumulative subscriptions, while rising monthly inflows give accelerating cumulative subscriptions.*

For a {{claim:main_illustration}}:

{{table:04_selected_timing_outcomes}}

Earlier cohorts pay fees for longer and are exposed to more redemption attrition. With {{claim:timing_attrition_year}} unit attrition and {{claim:growth_pct}} investment growth, later subscriptions leave more assets inside the fund at year 10, but produce fewer cumulative fees. Redeemed capital is paid to external investors; it is not automatically destroyed wealth. Ending AUM alone cannot rank investor performance. Owner invested equity remains {{claim:owner_growth_equity}} in each case.

**Different experimental controls:** This timing layer holds subscriptions fixed and external-unit redemptions at {{claim:timing_attrition_annual}} under all four return paths. It does not apply the {{claim:stress_subscription_fraction}}-subscription / {{claim:stress_attrition}}-redemption feedback used in the acquisition stress cases. Both analyses are retained; their loss results answer different questions. Appendix C gives every schedule, all timing outcomes, the remaining figures and their calculation trail.

### 6.3 Fund unit return and external investor return

For the fixed-subscription timing experiment's later-loss path ({{claim:later_return_path}}), the annualised fund unit time-weighted return (TWR), net of the {{claim:fee_bps}}, is identical across schedules. The aggregate external investors' money-weighted return (MWR) differs because their cash arrives at different times.

{{table:05_investor_returns}}

MWR treats subscriptions as investor outflows, redemptions as inflows and closing external equity as a terminal inflow. It solves the equal-month cash-flow IRR and compounds it over {{claim:months_per_year_words}} months; it is an aggregate cohort measure, not each client's individual return, manager profit or owner wealth. These are scenario months, not dated transaction XIRRs. Late subscriptions largely avoid the stipulated loss; the result does not imply investors can anticipate losses. Under the constant {{claim:growth_pct}} path both measures are {{claim:growth_unit_return}} annually after the fee. [Return calculations and cash-flow residual checks](../returns/return_diagnostics.json) retain all {{claim:investor_return_count}} timing controls.

## 7. Losses, Retention and Sequence

{{figure:figure_3}}

*Figure 3. Year 4 losses coincide with {{claim:stress_subscription_fraction}} subscriptions and {{claim:stress_attrition}} external-unit attrition. Owner capital stays separate. This combines market and sales stress rather than assuming business conditions are unaffected.*

The later loss places more external capital at risk than the launch loss. Earlier good performance does not protect the fund from redemptions, and subsequent flat returns do not insert a recovery. Different cumulative AUM outcomes need not imply different unit performance across sales cases. Stress rules are hypotheses; no probability is assigned.

A separate within-year control concentrates the year-4 loss in each of its {{claim:months_per_year_words}} months while preserving exactly the same annual return after the fund fee. With monthly fee `f` and smooth monthly return `r`, the matched annual multiplier is `G = (1 + r − f)^12`; the single-month gross shock is `G / (1 − f)^11 − 1 + f`, with zero gross investment returns in the other eleven months. This avoids attributing a fee-compounding difference to cash-flow timing. Subscription amounts and redemption assumptions remain fixed within each control; the acquisition layer retains its concurrent year-4 stress rules, while the timing layer retains its fixed flows and {{claim:timing_attrition}} unit attrition.

{{table:06_loss_placement_ranges}}

The early-tranche range is {{claim:early_loss_range}} despite unchanged annual net unit performance; owner closing equity reconciles to within {{claim:owner_control_residual}}. Smooth annual-to-monthly returns therefore suppress a material source of timing sensitivity. These {{claim:months_per_year_words}} placements per case are deterministic controls, not probabilities or bounds on real markets. [Independent loss-placement evidence](../controls/loss_controls.json) contains {{claim:loss_control_count}} across both layers and both annual matching conventions.

## 8. Fee Economics, Funding and Sensitivities

{{figure:figure_4}}

*Figure 4. Manager cash under {{claim:growth_pct}}, {{claim:baseline_bps}} and the stated business costs. Negative balances indicate cumulative external funding needed before tax and financing. They do not reduce plotted fund assets automatically.*

Steady acquisition with {{claim:ticket_usd}} tickets and full receipt of the investor fee gives:

{{table:07_fee_economics}}

The preceding table uses external-client fee receipts only. Closing cumulative cash is not necessarily the peak funding requirement: at {{claim:illustrative_bps}}, the {{claim:illustrative_closing_deficit}} follows a {{claim:illustrative_peak}} in {{claim:illustrative_peak_month}}. Required working capital must cover the path, rather than only year 10.

{{table:08_treasury_definitions}}

The owner-fee columns are a conditional treasury illustration: {{claim:owner_receipt}} deducted from owner NAV are available to the manager at each monthly accrual, with no distribution back to owners, tax or settlement delay. {{claim:illustrative_fee_bps}} this includes {{claim:illustrative_owner_fees}} of cumulative internal owner fees and closes at {{claim:illustrative_total_cash}}, but still needs {{claim:illustrative_owner_peak}} in peak funding. These transfers are already deducted from invested owner equity; adding them again as external revenue or counting both transferred and invested cash twice would overstate consolidated owner wealth. Neither definition establishes actual bank-account funding without confirmed receipt terms. Peak deficits are measured at month end; intramonth needs are outside the model. [Treasury reconciliation](../controls/treasury_controls.json) and [external-only peak funding](../controls/funding_sensitivity.json) retain the exact values.

{{figure:figure_5}}

*Figure 5. Fee changes affect both investor NAV and the manager result. Identical client counts across fee levels are a simplifying assumption, not evidence that clients accept higher fees.*

At {{claim:baseline_fee_bps}} and {{claim:servicing_bps}}, full manager receipt leaves {{claim:net_margin_bps}} of external assets to cover fixed and acquisition costs. With only {{claim:half_receipt}}, that falls to {{claim:partial_margin_bps}}. A static {{claim:static_cost}} would require {{claim:static_aum_no_variable}} of external assets if no variable costs applied; it would require approximately {{claim:static_aum_with_variable}} with a {{claim:servicing_variable_bps}} and {{claim:full_fee_bps}}. Acquisition spending adds another hurdle. These are static arithmetic illustrations, not simulated break-even estimates or actual quotes.

The [{{claim:fee_case_count}}](../tables/fee_ticket_receipt_sensitivity.csv) retains the full sensitivity grid. Higher fees reduce invested wealth and may change client demand, which this grid does not model. An annual positive result is distinct from cumulative recovery of startup and earlier operating losses.

The [{{claim:cost_case_count}}](../tables/business_cost_sensitivity.csv) independently varies first-year fixed costs ({{claim:fixed_cost_grid}}), acquisition spending ({{claim:acquisition_grid}} of subscriptions) and servicing ({{claim:servicing_grid}} of external assets). It retains the {{claim:fee_bps}}, {{claim:ticket_usd}} tickets, steady acquisition and {{claim:growth_pct}} path. This isolates cost uncertainty from fee changes; all budgets remain hypothetical.

In the central case, acquisition costs {{claim:acquisition_bps}}, versus annual investor {{claim:investor_fee_short}}. A simple constant-asset calculation would require {{claim:acquisition_payback}} just to repay acquisition, before redemptions, servicing, overhead or discounting. This is why strong acquisition can worsen the ten-year cash gap. That result challenges the cost/fee combination; it does not establish that acquisition must cost {{claim:acquisition_cost_bps}} or that more clients are inherently undesirable.

## 9. Interpretation and Remaining Inputs

This revision gives the colleague discussion concrete assumptions to replace: new clients per year, ticket sizes, time to first subscriptions, redemption behaviour, who retains fees, invoice-level setup/annual costs and the source of working capital. None is resolved by the historical backtest. The fee should be discussed together with an explicit cost payer and cost structure, rather than treated as a standalone revenue rate.

No scenario proves retirement sufficiency. Withdrawals, inflation, tax, changing real returns and personal risk capacity would require a separate owner-wealth study. No market-impact, collateral or margin-call simulation is added here. The historical strategy and its financing remain in the separate backtest.

## 10. Conclusion

Specified client acquisition can increase externally owned fund assets while leaving owner unit performance unchanged under fixed return assumptions. At the retained {{claim:fee_bps}}, business viability becomes more demanding once acquisition, servicing and startup costs are explicitly included. Strong fundraising cannot be interpreted as owner investment profit.

Equal gross fundraising also produces different results when payments arrive at different times. Early subscriptions generate more fee-paying time and redemptions; late subscriptions can leave higher ending AUM while providing less funding for earlier business costs. Under the stipulated model, timing does not change the unit return or owner equity within a return path, and it does not resolve the {{claim:baseline_bps}} cost shortfall.

The revision does not replace unverified optimism with a validated forecast. It supplies a more explicit, challengeable experiment: counts and tickets determine subscriptions; losses can damage retention; costs rise with fundraising and assets; manager fee receipts may differ from the investor charge. The next step is documented sales and provider inputs, followed by a new recalculation. The original no-flow and inflow studies remain available for comparison.

## Appendix A. All Twenty Acquisition Scenario Outcomes

Ending total fund assets, USD millions. Columns: flat; {{claim:growth_pct}}; early loss; later loss. Manager results and each annual schedule are retained in CSV.

{{table:09_acquisition_return_matrix}}

[Monthly accounting](../tables/acquisition_monthly.csv), [annual results](../tables/acquisition_annual.csv), [ownership, fees and funding gaps](../tables/acquisition_headline.csv).

## Appendix B. Reproduction and Prior Version

The current calculation trail consists of [captured assumptions](../config/inflow_acquisition.json), [timing schedules](../config/inflow_timing.json), [return settings](../config/inflow_returns.json), [control settings](../config/inflow_controls.json), [presentation selections](../config/inflow_presentation.json) and the [run manifest](../run_manifest.json). The manifest records package source hashes, environment and stage dependencies. Tables, figures and text claims are regenerated from this run; original result folders are not calculation inputs.

The report template is manually authored from the academic discussion draft, version 4, dated 3 October 2026. Historical version 1 retained 15 scenarios; the original version-3 editorial merge and version-4 revision records remain in the research archive outside this bundle. Historical version numbers and earlier assumptions are context, not recomputed outputs. No archival draft, historical verification file or separate investment report is included here.

The template review binds interpretations and captions to the reviewed configuration set. If assumptions change, run numerical components with `--no-report`, then review and update the template and its review metadata before producing another complete report. A generated report does not automatically validate its interpretation or commercial feasibility.

## Appendix C. Full Linear and Stepwise Timing Experiment

### C.1 Schedule definitions and controlled assumptions

Each flow case has the same total gross subscriptions over {{claim:months}} and no subscriptions in {{claim:prelaunch_months}}. The {{claim:timing_gross}} matches the previous steady-acquisition case's scheduled total, but these schedules redistribute it across time. The comparison does not match net flows or ending assets, because redemptions and investment returns vary with the time invested.

{{table:10_timing_schedules}}

Rounded schedule amounts above are for display; the [exact monthly schedule](../tables/subscription_schedule.csv) is used in calculations. A step of {{claim:timing_tranche}} is a stylised tranche and may represent one or several investors. The study assumes it arrives; it does not establish sales feasibility.

Owner capital is {{claim:capital_usd_m}}; the investor fee remains {{claim:annual_fee_pct}}. External units redeem at an equivalent {{claim:timing_attrition_year}} fraction in every return path. Fee timing, returns, setup, acquisition, servicing and fixed manager costs follow Section 3.3. New subscriptions are invested at month-end and first earn returns and pay fees the following month. Manager costs are paid outside the fund.

**Controlled distinction:** Subscription schedules and {{claim:timing_attrition}} attrition are held fixed even in loss years, to isolate timing. The acquisition analysis in Sections 3.2 and 7 retains its separate {{claim:stress_subscription_fraction}}-subscription / {{claim:stress_attrition}}-redemption stress. These results therefore do not replace that joint market-and-demand stress.

The four imposed annual paths are {{claim:return_paths}}. They are not forecasts or historical strategy returns.

### C.2 All timing cases under {{claim:growth_pct}}

{{table:11_all_timing_outcomes}}

{{figure:figure_6}}

*Figure 6. Owner plus external equity still invested. The asset level excludes cash already returned through redemptions. Different ending assets are not evidence of different return per unit.*

Earlier subscriptions have more time exposed to both investment returns and redemption attrition. Here, {{claim:timing_attrition_year}} unit attrition exceeds the {{claim:growth_pct}} gross investment growth assumption, so earlier external cohorts can leave less capital inside the fund at year 10. They also generate fees for longer. A larger ending AUM in a late-arrival case does not establish superior investor performance.

Redemptions are payments of investor capital and investment gains or losses, not business expenses or automatically destroyed wealth. The accounting retains cumulative redeemed amounts and investment P/L. Aggregate wealth of different external cohorts cannot be compared fairly using ending AUM alone or by treating every client as invested from month 1.

### C.3 Timing and loss exposure

{{figure:figure_7}}

*Figure 7. Early external cohorts face the year 4 loss; the late-step cohort enters afterwards. All schedules are imposed in advance, with no claim that a manager or client can anticipate the loss.*

This is a sequence illustration. Timing after a known simulated loss can look favourable retrospectively, but is not an implementable market-timing rule. Redemptions remain fixed at {{claim:timing_attrition}} in this controlled experiment; the combined demand stress remains in Section 7.

### C.4 Timing and business cash

{{figure:figure_8}}

*Figure 8. Cumulative external fees less manager costs under {{claim:growth_pct}}. {{claim:setup_cost}}; {{claim:fixed_cost}}; acquisition spending is {{claim:acquisition_cost_pct}}; servicing is {{claim:servicing_cost_pct}}. Full external-fee receipt is assumed. These remain hypothetical costs.*

All matched cases have the same cumulative acquisition spending of {{claim:timing_acquisition_cost}}, but incur it at different times. Fixed and setup costs are the same; servicing and fee receipts change with capital residence time. Early tranches can create sharp acquisition-cost funding needs; late tranches leave fewer years of fee receipts. The [headline results](../tables/timing_headline.csv) retain the peak cumulative funding gap as well as final cash.

{{claim:short_fee}} is still not demonstrated to fund the modelled business. Timing alone is not a solution to an unfavourable cost/fee structure. Funding negative manager cash is separate from the {{claim:capital_usd_m}} invested in the owner cohort; no automatic withdrawal from that cohort is modelled.

### C.5 All four return-path comparisons

Ending total fund assets, USD million; not cumulative investor wealth.

{{table:12_timing_return_matrix}}

### C.6 Timing calculation trail

[Assumptions](../config/inflow_timing.json), [monthly schedule](../tables/subscription_schedule.csv), [monthly accounts](../tables/timing_monthly.csv), [annual results](../tables/timing_annual.csv), [headline results](../tables/timing_headline.csv), [figure data](../figures/figure_data.csv), [independent controls](../controls/loss_controls.json), [table sources](../report_tables/report_tables.json) and [run manifest](../run_manifest.json).

The timing grid retains {{claim:timing_cases}} cases and {{claim:timing_rows}} monthly observations. Unit-based accounting calculates investor accounts; an independent cash-asset recurrence and cohort accumulation check assets, and manager costs follow the explicit assumptions. Previous drafts and PDFs are historical references outside this bundle. This command produces a local Markdown report; no PDF or public upload is performed.
