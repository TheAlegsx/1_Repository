# MSCI World Factor Strategy

GitHub reconstruction verified: code downloaded from the published revision and installed in a new isolated environment reproduced all14 calculation branches and598 reference CSV hashes.469 tests and nine subtests pass; both manuscripts match and all22 regenerated PDF pages match the downloaded public reading copies pixel-for-pixel. [Verification](docs/VERIFICATION.md) · [Security controls](docs/SECURITY.md). Original provider data and private working records remain local.

Research on a leveraged global equity factor portfolio and the economics of a potential fund. The project brings together two connected studies: historical investment performance and hypothetical capital inflows, ownership, fees and operating costs.

**Status:** research in development; a published research contribution with verified reconstruction. Assumptions can be revised through separately reviewed configurations. The latest reading reports are dated 7 October 2026.

| Read | Scope |
| --- | --- |
| [Portfolio backtest, version 14](reports/MSCI_World_Factor_Strategy_Backtest_V14_2026-10-07.pdf) | Investment returns, costs, leverage, benchmarks and robustness |
| [Capital inflows and fund economics, version 10](reports/Capital_Inflows_Fund_Economics_V10_2026-10-07.pdf) | Historical fund replay and separate hypothetical fundraising/business scenarios |

## Main design

The portfolio allocates 60% to Core MSCI World, 15% to Momentum, 10% to Quality and 15% to Value. Each sleeve has an absolute band of ±5 percentage points. Leverage is controlled separately at 1.25x with a ±0.10 adjustment band. Initial committed equity is USD 7 million.

Over 3 October 2014–28 August 2026, historical net CAGR is 13.24% for the main 1.25x strategy and 11.87% without borrowing. The retained capped-relative 1.25x comparison returns 12.92%. These are historical model outcomes with current assumed costs, not forecasts. The market benchmark is the MSCI World Core ETF, with a matched 1.25x financing control. Dimensional is a secondary comparison; the short Amundi comparison contrasts the factor portfolio at 2x with the actual daily 2x ETF, without charging product financing twice.

The historical inflow simulation uses the actual return sequence and fee/flow/debt feedback over 3 October 2014–3 October 2024. Its ten-year calendar matches the fund-economics horizon. Flat, 6% growth and imposed-loss scenarios remain separate adjustable experiments.

## Explore and reproduce

- [Report to calculation map](docs/REPORT_CALCULATION_MAP.md) — tables, figures, prose claims and their code/evidence origins
- [Methods and limitations](docs/METHODS.md)
- [Data sources and original-file requirements](data/README.md)
- [Installation](SETUP.md) and [complete reconstruction](REPRODUCE.md)
- [Configurations](config/README.md), [code map](src/README.md) and [validation](tests/README.md)
- [Verification scope](docs/VERIFICATION.md) and [AI assistance](docs/AI_USE.md)
- [Artificial demonstration](examples/README.md)

Original provider observations stay local. The repository supplies code, configuration, report templates, tests and reference checksums; research reconstruction requires separately obtained matching originals. Public checksum records are not copies of the underlying datasets.

The code is covered by the [MIT licence](LICENSE). It does not grant rights to third-party data or documents. Extensive OpenAI Codex assistance is disclosed in both reports and the linked evidence record. Human responsibility and the limits of the checks remain explicit.

[Finance projects](../README.md) · [All projects](../../README.md)
