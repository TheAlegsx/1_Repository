# Code map

| Task | Python module |
| --- | --- |
| Complete guarded reconstruction | `factor_portfolio.publication_reproduce` |
| Real-data portfolio accounts and baseline/extension calculations | `historical.simulate`, `historical.metrics`, `backtest_workflow` and `backtest_*` |
| Artificial example and accounting library API | `engine.run_backtest` |
| Hypothetical fund accounts and diagnostics | `inflow_workflow` and `inflow_*` |
| Coupled historical accounts, dated returns and manager cash | `historical_inflow_*` and `coupled_inflow_accounting` |
| Complete report evidence and assembly | `report_contract`, `backtest_report`, `coordinated_inflow_report` |
| Concise readers and PDF presentation | `research_reader_reports`, `research_reader_pdf` |

Templates/review metadata under `factor_portfolio/templates/` keep interpretation and selections explicit. Financial calculation and report assembly are separate stages. The common command checks reviewed results before assigning a new reader run identity, with sidecars written to the new output directory rather than the published source tree.

[Report to calculation map](../docs/REPORT_CALCULATION_MAP.md) · [Run instructions](../REPRODUCE.md) · [Validation](../tests/README.md)
