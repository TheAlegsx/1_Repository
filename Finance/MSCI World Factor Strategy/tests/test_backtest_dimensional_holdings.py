"""Common-stock scope, thousands units, rounded totals and independent tuple checks."""
import copy
import json
from pathlib import Path

import pandas as pd
import pytest
pytest.importorskip('pdfplumber')
from factor_portfolio import backtest_dimensional_holdings as dim
from test_backtest_annual_holdings import write_pdf

ROOT=Path(__file__).resolve().parents[1]
TEXT='''Global Core Equity Fund
Portfolio of Investments as at 30 November 2024
Dimensional Funds plc
Investment Funds
18 Liquidity Fund 50 25.00
Common Stock
United States - 45.00%
2 Rami Levy Chain Stores Hashikma Marketing
2006 Ltd. 60 30.00
3 Beta Company 30 15.00
- Zero Position - -
90 45.00
Switzerland - 5.00%
1 Swiss Company 10 5.00
10 5.00
Total Common Stock - 50.00% (30 November 2023: 50.00%) 100 50.00
Preferred Stock
1 Preferred Company 50 25.00
Total Net Assets 200 100.00
'''


@pytest.fixture
def dim_pdf(tmp_path):
    baseline=json.loads((ROOT/'config/backtest_absolute_decoupled_2026-10-05.json').read_text())
    settings=json.loads((ROOT/'config/backtest_annual_dimensional_2026-10-05.json').read_text())
    settings['reports']=settings['reports'][:1];report=settings['reports'][0]
    report.update(pages_1based=[1],layout_pages_1based=[1],expected_holdings=4,expected_country_groups=2)
    raw=tmp_path/'raw';raw.mkdir();path=raw/report['path'];write_pdf(path,TEXT);report['sha256']=dim.sha256(path)
    return raw,settings,baseline,path


def test_scope_thousands_units_missing_currency_and_numeric_name_continuation(dim_pdf):
    _,settings,_,_=dim_pdf
    h,c,s,_=dim.parse_common_stock([(1,TEXT)],settings['reports'][0])
    assert len(h)==4 and h[0]['name'].endswith('Marketing 2006 Ltd.')
    assert all(x['shares_units']=='000' and x['currency'] is None for x in h)
    assert not any('Liquidity' in x['name'] or 'Preferred' in x['name'] for x in h)
    assert h[0]['reconstructed_weight']==pytest.approx(.3)
    assert s['equity_weight']==pytest.approx(.5) and s['difference_000_usd']==0
    assert len(c)==2 and 'reported_value_000_usd' not in c[0]


def test_rounded_total_residual_is_retained_without_balancing_stock(dim_pdf):
    _,settings,_,_=dim_pdf;r=settings['reports'][0]
    h,_,s,_=dim.parse_common_stock([(1,TEXT.replace(') 100 50.00',') 102 51.00'))],r)
    assert len(h)==4 and s['difference_000_usd']==-2
    assert s['reported_equity_value_000_usd']==102 and s['extracted_equity_value_000_usd']==100
    with pytest.raises(ValueError,match='rounding tolerance'):
        dim.parse_common_stock([(1,TEXT.replace(') 100 50.00',') 110 55.00'))],r)


def test_exact_known_rh_spacing_repair_is_auditable(dim_pdf):
    _,settings,_,_=dim_pdf;r=copy.deepcopy(settings['reports'][0])
    r.update(snapshot_date='2025-11-30',path='dimensional_annual_2025.pdf',pages_1based=[223],expected_holdings=1,expected_country_groups=1)
    text='Common Stock\nUnited States - 0.00%\n2R H 3 6 7 -\nTotal Common Stock - 0.00% 367 -\nTotal Net Assets 9,000,000 100.00'
    h,_,s,fixes=dim.parse_common_stock([(223,text)],r)
    assert h[0]['name']=='RH' and h[0]['shares_reported']=='2' and h[0]['fair_value_000_usd']==367
    assert fixes[0]['before']=='2R H 3 6 7 -' and s['difference_000_usd']==0


def test_independent_reader_compares_multisets_and_detects_lost_duplicates():
    primary=pd.DataFrame([dict(shares_reported='2',fair_value_000_usd=3.,reported_weight_pct=0.)]*2)
    rows=[dict(name='different name outside numeric scope',shares=2.,value=3.,weight=0.)]*2
    assert dim.compare_page(primary,rows,2024,1)['layout_count']==2
    with pytest.raises(ValueError,match='numeric tuples disagree'):dim.compare_page(primary,rows[:1],2024,1)
    parsed,_=dim.parse_layout_lines(['Investment Funds','1 Liquidity 4 1.00','Common Stock','1 Equity 5 2.00','Total Common Stock','2 Other 8 3.00'])
    assert len(parsed)==1 and parsed[0]['name']=='Equity'


def test_direct_two_reader_pdf_build_preserves_uncertainty(dim_pdf,tmp_path):
    raw,settings,baseline,_=dim_pdf;dim.validate_settings(settings,baseline)
    (raw/'dimensional_annual_2024_page_1.txt').write_text('wrong cache')
    result=dim.build_dimensional_study(raw,settings,tmp_path/'output')
    assert len(result['frames']['historical_equity_holdings.csv'])==4
    assert len(result['frames']['dimensional_second_reader_rows.csv'])==4
    assert result['checks'][0]['missing']==[] and result['checks'][0]['extra']==[]
    assert result['frames']['historical_country_exposures.csv'].reported_value_000_usd.isna().all()
    assert result['frames']['historical_top10_security_lines.csv'].shares_units.eq('000').all()
    assert result['definitions']['reader_versions']['pdfplumber']=='0.11.9'


def test_source_containment_substitution_and_invalid_dates_are_rejected(dim_pdf):
    raw,settings,baseline,path=dim_pdf
    changed=copy.deepcopy(settings);changed['reports'][0]['path']='../outside.pdf'
    with pytest.raises(ValueError,match='outside'):dim.admit_sources(raw,changed)
    changed=copy.deepcopy(settings);changed['reports'][0]['snapshot_date']='2024-06-30'
    with pytest.raises(ValueError,match='November'):dim.validate_settings(changed,baseline)
    path.write_text('%PDF- substituted')
    with pytest.raises(ValueError,match='checksum'):dim.admit_sources(raw,settings)


def test_wrong_subfund_identity_and_missing_positive_nav_fail(dim_pdf,tmp_path):
    raw,settings,_,path=dim_pdf
    write_pdf(path,TEXT.replace('Global Core Equity Fund','Other Fund'));settings['reports'][0]['sha256']=dim.sha256(path)
    with pytest.raises(ValueError,match='identity mismatch'):dim.build_dimensional_study(raw,settings,tmp_path/'wrong')
    with pytest.raises(ValueError,match='positive disclosed'):
        dim.parse_common_stock([(1,TEXT.replace('Total Net Assets 200','Total Net Assets 0'))],settings['reports'][0])
