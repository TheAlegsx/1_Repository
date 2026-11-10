# Market data provenance

The eight market data inputs are included under `Inputs/market_data`. The SHA-256 digests of the four packaged iShares copies can be checked against the iShares source manifest. The packaging record reports that one unused metadata row was cleared in each copy and that the historical NAV worksheets were preserved byte for byte. The manifest records the original issuer-export digests separately. Verifying those digests and the worksheet identity requires the original exports, which are outside this package. [results.json](results.json) records the filenames and digests of the inputs used to reproduce the results under `inputs_relative_to_market_data_sha256`.

## References

Amundi Asset Management. (2026a). *NAV history: Amundi MSCI World (2x) Leveraged UCITS ETF Acc* (FR0014010HV4, September 25, 2026 update) [Data set]. Workbook retained with the private assessment package.

Amundi Asset Management. (2026b, April 28). *Amundi MSCI World (2x) Leveraged UCITS ETF Acc* (FR0014010HV4) [Key information document]. [Amundi PDF](https://www.amundietf.lu/pdfDocuments/kid-priips/FR0014010HV4/ENG/LUX/20260428)

BlackRock. (2026a). *iShares Core MSCI World UCITS ETF: Historical NAVs* (IE00B4L5Y983, September 2026 snapshot) [Data set]. iShares. [https://www.ishares.com/uk/individual/en/products/251882/ishares-msci-world-ucits-etf-acc-fund](https://www.ishares.com/uk/individual/en/products/251882/ishares-msci-world-ucits-etf-acc-fund)

BlackRock. (2026b). *iShares Edge MSCI World Momentum Factor UCITS ETF: Historical NAVs* (IE00BP3QZ825, September 2026 snapshot) [Data set]. iShares. [https://www.ishares.com/uk/individual/en/products/270051/ishares-msci-world-momentum-factor-ucits-etf](https://www.ishares.com/uk/individual/en/products/270051/ishares-msci-world-momentum-factor-ucits-etf)

BlackRock. (2026c). *iShares Edge MSCI World Quality Factor UCITS ETF: Historical NAVs* (IE00BP3QZ601, September 2026 snapshot) [Data set]. iShares. [https://www.ishares.com/uk/individual/en/products/270054/ishares-msci-world-quality-factor-ucits-etf](https://www.ishares.com/uk/individual/en/products/270054/ishares-msci-world-quality-factor-ucits-etf)

BlackRock. (2026d). *iShares Edge MSCI World Value Factor UCITS ETF: Historical NAVs* (IE00BP3QZB59, September 2026 snapshot) [Data set]. iShares. [https://www.ishares.com/uk/individual/en/products/270048/ishares-msci-world-value-factor-ucits-etf](https://www.ishares.com/uk/individual/en/products/270048/ishares-msci-world-value-factor-ucits-etf)

Eidgenössische Steuerverwaltung. (2025, August 28). *Umsatzabgabe kurz erklärt* [Turnover tax explained]. [https://www.estv.admin.ch/de/umsatzabgabe-kurz-erklaert](https://www.estv.admin.ch/de/umsatzabgabe-kurz-erklaert)

European Commission. (2026, September 1). *Euro exchange rates – 31 August 2026* (C/2026/4112). Official Journal of the European Union. [English PDF, Publications Office of the European Union](https://op.europa.eu/o/opportal-service/download-handler?identifier=1086c7a2-a59e-11f1-b25c-01aa75ed71a1&format=pdfa2a&language=en&productionSystem=cellar&part=)

Federal Reserve Bank of New York. (n.d.). *Additional information about reference rates administered by the New York Fed*. [https://www.newyorkfed.org/markets/reference-rates/additional-information-about-reference-rates](https://www.newyorkfed.org/markets/reference-rates/additional-information-about-reference-rates)

Federal Reserve Bank of New York. (2018). *Volume-weighted median overnight Treasury repo rates* (Indicative SOFR, August 22, 2014 to March 29, 2018) [Data set]. [https://www.newyorkfed.org/medialibrary/media/markets/Data%20Release.xlsx](https://www.newyorkfed.org/medialibrary/media/markets/Data%20Release.xlsx)

Federal Reserve Bank of New York. (2026a). *30-day average SOFR* (September 25, 2026 observation) [Data set]. FRED, Federal Reserve Bank of St. Louis. [Historical data table](https://fred.stlouisfed.org/data/SOFR30DAYAVG)

Federal Reserve Bank of New York. (2026b). *Secured Overnight Financing Rate data* (April 2, 2018 to August 31, 2026, September 2026 snapshot) [Data set]. [https://markets.newyorkfed.org/api/rates/secured/sofr/search.json?startDate=2018-04-02&endDate=2026-08-31&type=rate](https://markets.newyorkfed.org/api/rates/secured/sofr/search.json?startDate=2018-04-02&endDate=2026-08-31&type=rate)

Morningstar. (n.d.). *Dimensional Global Core Equity Fund USD Accumulation: Daily USD NAV* (IE00B2PC0153, series 42858) [Data set]. Finanzfluss. Retrieved November 10, 2026, from [https://hippoverse.finanzfluss.de/api/v1/funds/IE00B2PC0153/prices?startDate=2014-10-03&endDate=2026-08-28&includeNav=true](https://hippoverse.finanzfluss.de/api/v1/funds/IE00B2PC0153/prices?startDate=2014-10-03&endDate=2026-08-28&includeNav=true)

Politis, D. N., & Romano, J. P. (1994). The stationary bootstrap. *Journal of the American Statistical Association, 89*(428), 1303–1313. [https://doi.org/10.1080/01621459.1994.10476870](https://doi.org/10.1080/01621459.1994.10476870)

Swissquote Bank Ltd. (n.d.). *Handelsgebühren für Aktien* [Stock trading fees]. Retrieved November 10, 2026, from [https://www.swissquote.com/de-ch/private/trade/pricing/commissions/stocks](https://www.swissquote.com/de-ch/private/trade/pricing/commissions/stocks)

## Snapshot and file notes

- **BlackRock (2026a, 2026b, 2026c, 2026d).** The capture date for all four iShares exports is September 27, 2026. The iShares manifest records the original export-page URLs. The references link to the issuer pages for the matching share classes.
- **Federal Reserve Bank of New York (2018, 2026b).** Both files were captured on September 28, 2026. The indicative workbook uses the “Secured Overnight Financing Rate” column in “VWM Rates” in basis points. The official API response uses the `percentRate` field in percent per annum.
- **Amundi Asset Management (2026a).** The archived workbook identifies the September 25, 2026 update. It contains the “Official NAV” column in the “Nav History” sheet. The workbook retained with the private assessment package is the exact calculation input. The original workbook download URL and retrieval date are unverified.

## Investment cost assumptions

- **Observed reference rates.** The New York Fed series supplies indicative rates and daily SOFR. ACT/360 accrual follows the convention described in the New York Fed methodology for the SOFR Averages and Index.
- **Financing markup.** The project brief records a 6.65% USD borrowing rate from a private Swissquote account snapshot dated September 26, 2026. The 30-day SOFR average was 3.705% on September 25, 2026. The difference of 294.5 bp was rounded to a fixed 300 bp markup over the historical reference rate. The account category and historical broker rates remain unverified. The 30-day observation serves as a calibration reference.
- **One-way spread.** The model assumes a fixed 5 bp charge per purchase or sale throughout the sample. The baseline configuration records the markup and spread.
- **Broker charges.** Section 1.1 of the Swissquote tariff supplies the 0.85 fee in the transaction currency and the stepped CHF commission schedule used for USD trades. The calculation applies that schedule throughout the sample.
- **Transfer duty.** The tax authority publishes 3.0‰ total for foreign securities and describes the half-duty per applicable party. The simulation models one investor-side half of 1.5‰ (0.15%).
- **Fixed conversion.** The European Commission publication gives the ECB rates for 31 August 2026. Dividing 1.1596 USD per EUR by 0.9376 CHF per EUR gives 1.2367747440 USD per CHF. The model applies this fixed rate to CHF commissions.

## Dimensional NAVs

Finanzfluss identifies Morningstar as the provider of the fund's NAV data. The response identifies price series `42858`. It returned 2,931 rows. Filtering to October 3, 2014–August 28, 2026 retained 2,929 USD NAV observations, all on dates common to the iShares series. The response SHA-256 was `26ce9209a97e69a2578581652e8044bedf3c7dc091c6f38decdcb6fbd0bdd5fe`. [Fund page and data attribution](https://www.finanzfluss.de/informer/fonds/ie00b2pc0153/)

The 1.25× comparison on the matched NAV dates produced an annualised return of **11.31744726%** for Dimensional and **13.24364961%** for the factor portfolio.

## Supplementary video calculations

The unlevered Quality comparison uses the same issuer NAVs, calendar and transaction-cost assumptions as the portfolio backtest. It compares the original 60/15/10/15 allocation with 60/10/20/10 under both the earlier capped-relative rule and the final absolute-band rule. The exact weights and results are in `video_supplement.quality_weight_test` in [results.json](results.json).

The ten-year fund-assets calculation uses the packaged monthly unit-accounting model. The [scenario configuration](../Code/config/steady_acquisition_video.json) records the steady-acquisition inputs and the 0.30% annual fund fee. The [calculation module](../Code/src/factor_portfolio/inflows.py) specifies the monthly accounting and the package runner reproduces the result.
