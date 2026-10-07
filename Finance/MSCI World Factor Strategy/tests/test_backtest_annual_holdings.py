"""Annual PDF admission, direct extraction and published-total reconciliation."""
import copy
import json
from pathlib import Path

import pytest
pytest.importorskip('pypdf')
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

from factor_portfolio import backtest_annual_holdings as annual

ROOT = Path(__file__).resolve().parents[1]
TEXT = '''iShares Core MSCI World UCITS ETF
SCHEDULE OF INVESTMENTS
As at 30 June 2023
Equities (30 June 2022: 100.00%)
United States (30 June 2022: 90.00%)
USD 1,200 Listed Class A 60 60.00
USD 20 Listed
Class B 30 30.00
USD 1 Zero-valued Right-name Equity 0 -
Total United States 90 90.00
Switzerland (30 June 2022: 10.00%)
CHF 10 Swiss Company 10 10.00
Total Switzerland 10 10.00
Total Equities 100 100.00
Net asset value attributable to redeemable
shareholders at the end of the financial year 100 100.00
'''


def write_pdf(path, text):
    writer = PdfWriter();page = writer.add_blank_page(width=600, height=900)
    font = DictionaryObject({NameObject('/Type'):NameObject('/Font'), NameObject('/Subtype'):NameObject('/Type1'), NameObject('/BaseFont'):NameObject('/Helvetica')})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
    commands = ['BT /F1 10 Tf 40 850 Td']
    for line in text.splitlines():
        line = line.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
        commands.append('('+line+') Tj 0 -15 Td')
    commands.append('ET');stream = DecodedStreamObject();stream.set_data('\n'.join(commands).encode('ascii'))
    page[NameObject('/Contents')] = writer._add_object(stream)
    with path.open('wb') as handle:writer.write(handle)


@pytest.fixture
def pdf_study(tmp_path):
    baseline = json.loads((ROOT/'config/backtest_absolute_decoupled_2026-10-05.json').read_text())
    settings = json.loads((ROOT/'config/backtest_annual_core_2026-10-05.json').read_text())
    settings['reports'] = settings['reports'][:1]
    report = settings['reports'][0];report.update(pages_1based=[1], expected_holdings=4, expected_country_groups=2)
    raw = tmp_path/'raw';raw.mkdir();path = raw/report['path'];write_pdf(path, TEXT);report['sha256'] = annual.sha256(path)
    return raw, settings, baseline, path


def test_line_grammar_retains_multiline_names_shares_currency_and_nav_denominator(pdf_study):
    _, settings, _, _ = pdf_study
    h, c, s = annual.parse_core_schedule([(1,TEXT)], settings['reports'][0])
    assert len(h) == 4 and h[1]['name'] == 'Listed Class B'
    assert h[0]['shares_reported'] == '1,200' and h[0]['shares_units'] == 'units'
    assert h[-1]['currency'] == 'CHF' and h[-1]['reconstructed_weight'] == pytest.approx(.1)
    assert h[2]['reported_weight_pct'] == 0 and h[2]['fair_value_000_usd'] == 0
    assert s['difference_000_usd'] == 0 and s['top10_security_line_weight'] == pytest.approx(1.)
    assert sum(row['reconstructed_weight'] for row in c) == pytest.approx(1.)


def test_partial_equity_coverage_uses_fund_nav_not_equity_sum(pdf_study):
    _, settings, _, _ = pdf_study
    text = TEXT.replace('90 90.00','90 45.00').replace('10 10.00\nTotal Switzerland','10 5.00\nTotal Switzerland')
    text = text.replace('Total Switzerland 10 10.00','Total Switzerland 10 5.00').replace('financial year 100 100.00','financial year 200 100.00')
    h, _, s = annual.parse_core_schedule([(1,text)], settings['reports'][0])
    assert s['equity_weight'] == pytest.approx(.5)
    assert h[0]['reconstructed_weight'] == pytest.approx(.3)
    assert s['top10_security_line_weight'] == pytest.approx(.5)


def test_missing_nav_totals_country_values_and_unparsed_lines_fail(pdf_study):
    _, settings, _, _ = pdf_study;r = settings['reports'][0]
    with pytest.raises(ValueError, match='positive USD'):annual.parse_core_schedule([(1,TEXT.replace('financial year 100 100.00','financial year 0 100.00'))], r)
    with pytest.raises(ValueError, match='equity values'):annual.parse_core_schedule([(1,TEXT.replace('Total Equities 100','Total Equities 101'))], r)
    with pytest.raises(ValueError, match='country values'):annual.parse_core_schedule([(1,TEXT.replace('Total United States 90','Total United States 89'))], r)
    with pytest.raises(ValueError, match='unparsed'):annual.parse_core_schedule([(1,TEXT.replace('USD 1,200 Listed Class A 60 60.00','USD 1,200 Unparsed security'))], r)


def test_pdf_admission_rejects_substitution_and_root_escape(pdf_study, tmp_path):
    raw, settings, _, path = pdf_study
    annual.admit_sources(raw, settings)
    changed = copy.deepcopy(settings);changed['reports'][0]['path'] = '../outside.pdf'
    with pytest.raises(ValueError, match='outside'):annual.admit_sources(raw, changed)
    path.write_text('%PDF- replaced source')
    with pytest.raises(ValueError, match='checksum'):annual.admit_sources(raw, settings)


def test_direct_pdf_extraction_records_pages_and_ignores_cached_text(pdf_study, tmp_path):
    raw, settings, baseline, _ = pdf_study
    annual.validate_settings(settings, baseline)
    (raw/'ishares_iii_annual_2023_page_1.txt').write_text('incorrect cached extraction')
    output = tmp_path/'output';result = annual.build_annual_core_study(raw, settings, output)
    assert len(result['frames']['historical_equity_holdings.csv']) == 4
    concentration = result['frames']['historical_concentration_summary.csv'].iloc[0]
    assert concentration.us_equity_weight_of_nav == pytest.approx(.9)
    assert result['definitions']['parser']['version'] == '6.19.0'
    page = result['definitions']['extracted_pages'][0]
    extracted = output/'annual_core/extracted_pages/ishares_iii_annual_2023_page_1.txt'
    assert annual.sha256(extracted) == page['text_sha256']
    assert 'incorrect cached' not in extracted.read_text()


def test_pdf_page_identity_and_schedule_range_are_validated(pdf_study, tmp_path):
    raw, settings, baseline, path = pdf_study
    write_pdf(path, TEXT.replace('iShares Core MSCI World UCITS ETF','Other Fund'));settings['reports'][0]['sha256'] = annual.sha256(path)
    with pytest.raises(ValueError, match='identity mismatch'):annual.build_annual_core_study(raw, settings, tmp_path/'wrong')
    changed = copy.deepcopy(settings);changed['reports'][0]['pages_1based'] = [1,3]
    with pytest.raises(ValueError, match='contiguous'):annual.validate_settings(changed, baseline)
    changed = copy.deepcopy(settings);changed['reports'][0]['snapshot_date'] = '2027-06-30'
    with pytest.raises(ValueError, match='cutoff'):annual.validate_settings(changed, baseline)


def test_derived_views_preserve_the_legacy_fresh_csv_read_boundary(pdf_study, tmp_path):
    import pandas as pd
    raw, settings, _, path = pdf_study
    text = TEXT.replace('financial year 100 100.00', 'financial year 193 100.00')
    text = text.replace('Total United States 90 90.00', 'Total United States 90 46.63')
    text = text.replace('Total Switzerland 10 10.00', 'Total Switzerland 10 5.18')
    write_pdf(path, text);settings['reports'][0]['sha256'] = annual.sha256(path)
    output = tmp_path/'precision';result = annual.build_annual_core_study(raw, settings, output)
    fresh = pd.read_csv(output/'annual_core/historical_equity_holdings.csv')
    top = result['frames']['historical_top10_security_lines.csv']
    assert top.reconstructed_weight.iloc[0] == fresh.reconstructed_weight.max()
    assert top.reconstructed_weight.iloc[0] != result['frames']['historical_equity_holdings.csv'].reconstructed_weight.iloc[0]
    assert 'default float reader' in result['definitions']['csv_precision']
