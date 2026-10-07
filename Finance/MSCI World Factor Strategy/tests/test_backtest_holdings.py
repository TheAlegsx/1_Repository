"""Later snapshot dates, gross-weight denominators and security-line identity."""
import copy
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import numpy as np
import pytest

from factor_portfolio import backtest_holdings as holdings
from factor_portfolio.data import SPREADSHEET_NS

ROOT = Path(__file__).resolve().parents[1]


def write_sheets(path, sheets):
    ns = '{'+SPREADSHEET_NS+'}'
    root = ET.Element(ns+'Workbook')
    for name, rows in sheets.items():
        sheet = ET.SubElement(root, ns+'Worksheet', {ns+'Name':name})
        table = ET.SubElement(sheet, ns+'Table')
        for values in rows:
            row = ET.SubElement(table, ns+'Row')
            for value in values:
                cell = ET.SubElement(row, ns+'Cell')
                ET.SubElement(cell, ns+'Data').text = str(value)
    path.write_bytes(ET.tostring(root))


@pytest.fixture
def snapshot(tmp_path):
    baseline = json.loads((ROOT/'config/backtest_absolute_decoupled_2026-10-05.json').read_text())
    settings = json.loads((ROOT/'config/backtest_holdings_snapshot_2026-10-05.json').read_text())
    settings['expected_rows'] = dict(zip(holdings.FILES, [9,3,11,3,11,3,6]))
    allocations = dict(core=[('A','USD',60),('B','USD',40)],
        momentum=[('A','USD',20),('A','USD',30),('B','USD',50)],
        quality=[('A','USD',60),('A','EUR',40)], value=[('B','USD',70),('A','USD',30)])
    sources, sheets = {}, {}
    for sleeve, positions in allocations.items():
        header = ['Issuer Ticker','Name','Market Currency','Sector','Asset Class','Weight (%)']
        if sleeve == 'core':header.append('Location')
        tag = 'Fund Holdings as of' if sleeve == 'core' else 'as of'
        rows = [[tag,'25/Sept/2026'], header]
        for ticker, currency, weight in positions:
            values = [ticker, 'Name '+ticker, currency,
                'Information Technology' if ticker == 'A' else 'Health Care', 'Equity', weight]
            if sleeve == 'core':values.append('United States' if ticker == 'A' else 'Switzerland')
            rows.append(values)
        # A large non-equity row must never enter the equity concentration denominator.
        rows.append(['CASH','Cash','USD','Cash and/or Derivatives','Cash',75]+(['United States'] if sleeve=='core' else []))
        data = {'Holdings':rows}
        if sleeve != 'core':
            data['Exposure Breakdowns'] = [['Sector'],['as of','25/Sept/2026'],['Type','Fund'],
                ['Information Technology',65],['Health Care',30],['Cash and/or Derivatives',5],
                ['Geography/Locations'],['as of','25/Sept/2026'],['Type','Fund'],
                ['United States',60],['Switzerland',35],['Cash and/or Derivatives',5]]
        path = tmp_path/(sleeve+'.xls');write_sheets(path, data)
        sources[sleeve] = path;sheets[sleeve] = data
    return sources, baseline, settings, sheets


def test_duplicate_lines_sum_but_currency_identity_remains_separate(snapshot):
    sources, baseline, settings, _ = snapshot
    result = holdings.snapshot_comparison(sources, baseline, settings)
    combined = result['frames']['combined_equity_holdings.csv'].set_index('identifier_proxy')
    assert len(combined) == 3
    assert combined.loc['A|Name A|USD','portfolio_weight'] == pytest.approx(.54)
    assert combined.loc['B|Name B|USD','portfolio_weight'] == pytest.approx(.42)
    assert combined.loc['A|Name A|EUR','portfolio_weight'] == pytest.approx(.04)
    assert combined.loc['A|Name A|USD','sleeves'] == 4
    pair = result['frames']['pairwise_overlap.csv'].iloc[0]
    assert pair['matched_equity_lines'] == 2 and pair['sum_min_fund_weight'] == pytest.approx(.9)
    assert result['summary']['top10_combined_equity_weight'] == pytest.approx(1.)
    assert result['definitions']['no_leverage_multiplier']
    changed = copy.deepcopy(baseline);changed['primary_leverage'] = 2
    again = holdings.snapshot_comparison(sources, changed, settings)
    np.testing.assert_array_equal(combined.portfolio_weight.to_numpy(), again['frames']['combined_equity_holdings.csv'].portfolio_weight.to_numpy())


def test_core_equity_and_factor_supplied_exposures_keep_distinct_scopes(snapshot):
    sources, baseline, settings, _ = snapshot
    result = holdings.snapshot_comparison(sources, baseline, settings)
    equity = result['frames']['equity_holdings.csv']
    assert not equity.ticker.eq('CASH').any()
    sector = result['frames']['sector_by_sleeve.csv']
    assert not sector.loc[sector.sleeve.eq('core'),'category'].eq('Cash and/or Derivatives').any()
    assert len(sector.loc[sector.category.eq('Cash and/or Derivatives')]) == 3
    combined = result['frames']['sector_combined.csv'].set_index('category')
    assert combined.loc['Information Technology','portfolio_weight'] == pytest.approx(.62)
    assert combined.loc['Cash and/or Derivatives','portfolio_weight'] == pytest.approx(.02)
    assert equity.loc[equity.sleeve.eq('momentum'),'location'].isna().all()


def test_holdings_and_each_breakdown_date_are_checked(snapshot):
    sources, baseline, settings, sheets = snapshot
    sheets['core']['Holdings'][0][1] = '24/Sept/2026';write_sheets(sources['core'], sheets['core'])
    with pytest.raises(ValueError, match='valuation date'):holdings.snapshot_comparison(sources, baseline, settings)
    sheets['core']['Holdings'][0][1] = '25/Sept/2026';write_sheets(sources['core'], sheets['core'])
    sheets['quality']['Exposure Breakdowns'][7][1] = '24/Sept/2026';write_sheets(sources['quality'], sheets['quality'])
    with pytest.raises(ValueError, match='valuation date'):holdings.snapshot_comparison(sources, baseline, settings)


def test_malformed_equity_weights_and_incomplete_classification_are_not_skipped(snapshot):
    sources, baseline, settings, sheets = snapshot
    for bad in ['invalid','nan','-1']:
        sheets['core']['Holdings'][2][5] = bad;write_sheets(sources['core'], sheets['core'])
        with pytest.raises(ValueError, match='weight'):holdings.snapshot_comparison(sources, baseline, settings)
    sheets['core']['Holdings'][2][5] = 60;sheets['core']['Holdings'][2][2] = ''
    write_sheets(sources['core'], sheets['core'])
    with pytest.raises(ValueError, match='classification'):holdings.snapshot_comparison(sources, baseline, settings)


def test_snapshot_date_scope_and_row_count_drift_are_rejected(snapshot):
    sources, baseline, settings, _ = snapshot
    wrong = copy.deepcopy(settings);wrong['snapshot_date'] = '2026-08-28'
    with pytest.raises(ValueError, match='outside'):holdings.validate_settings(wrong, baseline)
    wrong = copy.deepcopy(settings);wrong['expected_rows']['equity_holdings.csv'] += 1
    with pytest.raises(ValueError, match='row count'):holdings.snapshot_comparison(sources, baseline, wrong)
    wrong = copy.deepcopy(settings);wrong['measurement']['overlap'] = 'equity normalized'
    with pytest.raises(ValueError, match='measurement'):holdings.validate_settings(wrong, baseline)


def test_partial_equity_coverage_is_not_renormalized(snapshot):
    sources, baseline, settings, sheets = snapshot
    sheets['core']['Holdings'][2][5] = 57
    sheets['core']['Holdings'][3][5] = 38
    write_sheets(sources['core'], sheets['core'])
    result = holdings.snapshot_comparison(sources, baseline, settings)
    assert result['summary']['equity_weight_coverage']['core'] == pytest.approx(.95)
    assert result['summary']['top10_combined_equity_weight'] == pytest.approx(.97)
    pair = result['frames']['pairwise_overlap.csv'].iloc[0]
    assert pair['sum_min_fund_weight'] == pytest.approx(.88)
