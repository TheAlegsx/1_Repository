# Configuration map

| Definition | Location |
| --- | --- |
| Current portfolio, costs, financing, calendar and tolerances | [absolute baseline](backtest_absolute_decoupled_2026-10-05.json) |
| Original/comparison policy settings | [retained baseline](backtest_baseline.json) and historical funding/bridge files |
| Hypothetical fundraising, returns, timing and controls | `inflow_acquisition.json`, `inflow_timing.json`, `inflow_returns.json`, `inflow_controls.json` |
| Actual-date historical fund execution | [execution v2](historical_inflows_execution_v2_2026-10-05.json) and associated calendar/diagnostic definitions |
| Full reconstruction order and accepted fingerprints | [recipe](reproduction_recipe_2026-10-06.json) and [reference checksums](reproduction_reference_2026-10-06.json) |
| Concise report selections | [reader selection](research_reader_selection_2026-10-06.json) |

The dated extension files define financing, allocation, fresh-entry/rolling, margin/gap, artificial-regime, product/correlation, holdings, custody and independent-check branches. The common recipe selects the required set. Original configurations are retained; updating a study means creating/reviewing a new configuration and interpretation rather than deleting comparisons.

[Methods](../docs/METHODS.md) · [Reconstruction](../REPRODUCE.md)
