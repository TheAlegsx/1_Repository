"""Contemporaneous factor identity, direct PDF schedules and overlap denominators."""
import copy
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
pytest.importorskip('pypdf')
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject,NameObject,DecodedStreamObject

from factor_portfolio import backtest_factor_holdings as factors
from test_backtest_annual_holdings import TEXT

ROOT = Path(__file__).resolve().parents[1]


def write_pdf(path, texts):
    writer = PdfWriter()
    font = DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
    font_ref = writer._add_object(font)
    for text in texts:
        page = writer.add_blank_page(width=600,height=900)
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):font_ref})})
        commands = ['BT /F1 10 Tf 40 850 Td']
        for line in text.splitlines():
            line = line.replace('\\','\\\\').replace('(','\\(').replace(')','\\)')
            commands.append('('+line+') Tj 0 -15 Td')
        commands.append('ET');stream = DecodedStreamObject();stream.set_data('\n'.join(commands).encode('ascii'))
        page[NameObject('/Contents')] = writer._add_object(stream)
    with path.open('wb') as f:writer.write(f)


@pytest.fixture
def factor_pdf(tmp_path):
    baseline = json.loads((ROOT/'config/backtest_absolute_decoupled_2026-10-05.json').read_text())
    settings = json.loads((ROOT/'config/backtest_annual_factors_2026-10-05.json').read_text())
    settings['sources'] = settings['sources'][:1];settings['schedules'] = settings['schedules'][:3]
    raw = tmp_path/'raw';raw.mkdir();path = raw/settings['sources'][0]['path'];texts = []
    for page,schedule in enumerate(settings['schedules'],1):
        schedule.update(pages_1based=[page],expected_holdings=4,expected_country_groups=2)
        text = TEXT.replace('iShares Core MSCI World UCITS ETF',factors.FUND_NAMES[schedule['fund']])
        texts.append(text.replace('30 June 2023','31 May 2024').replace('30 June 2022','31 May 2023'))
    write_pdf(path,texts);settings['sources'][0]['sha256'] = factors.sha256(path)
    return raw,settings,baseline,path


def equity_fixture():
    rows = []
    for fund,positions in dict(momentum=[('Alpha A','USD',40),('Alpha  A','USD',20),('Beta','USD',40)],
                               quality=[('Alpha A','USD',50),('Beta','USD',50)],
                               value=[('Alpha A','EUR',30),('Beta','USD',70)]).items():
        for name,currency,fair in positions:
            rows.append(dict(fund=fund,snapshot_date='2024-05-31',name=name,currency=currency,
                fair_value_000_usd=float(fair),reconstructed_weight=fair/200))
    return pd.DataFrame(rows)


def test_overlap_groups_duplicate_names_and_normalizes_equity_not_nav():
    h = equity_fixture();result = factors.historical_factor_overlap(h)
    assert list(zip(result.fund_a,result.fund_b)) == [('momentum','quality'),('momentum','value'),('quality','value')]
    np.testing.assert_allclose(result.weighted_equity_overlap,[.9,.4,.5],atol=1e-15)
    assert result.holdings_keys_a.iloc[0] == 2  # duplicated Alpha lines group
    assert result.matched_keys.iloc[1] == 1  # EUR Alpha remains separate from USD


def test_missing_dates_nonfactor_rows_and_nonpositive_equity_are_rejected():
    h = equity_fixture();h.loc[h.fund.eq('value'),'snapshot_date'] = '2024-06-30'
    with pytest.raises(ValueError,match='contemporaneous'):factors.historical_factor_overlap(h)
    h = equity_fixture();h.loc[0,'fund'] = 'core'
    with pytest.raises(ValueError,match='factor security'):factors.historical_factor_overlap(h)
    h = equity_fixture();h.loc[h.fund.eq('quality'),'fair_value_000_usd'] = 0.
    with pytest.raises(ValueError,match='denominator'):factors.historical_factor_overlap(h)


def test_factor_contract_requires_three_subfunds_per_may_date(factor_pdf):
    _,settings,baseline,_ = factor_pdf
    factors.validate_settings(settings,baseline)
    changed = copy.deepcopy(settings);changed['schedules'] = changed['schedules'][:-1]
    with pytest.raises(ValueError,match='three contemporaneous'):factors.validate_settings(changed,baseline)
    changed = copy.deepcopy(settings);changed['schedules'][0]['fund_identity'] = factors.FUND_NAMES['quality']
    with pytest.raises(ValueError,match='identity'):factors.validate_settings(changed,baseline)
    changed = copy.deepcopy(settings);changed['sources'][0]['snapshot_date'] = '2024-06-30'
    for schedule in changed['schedules']:schedule['snapshot_date'] = '2024-06-30'
    with pytest.raises(ValueError,match='May year end'):factors.validate_settings(changed,baseline)


def test_subfund_pages_are_read_directly_with_preserved_labels_and_units(factor_pdf,tmp_path):
    raw,settings,_,_ = factor_pdf
    (raw/'ishares_iv_annual_2024_page_1.txt').write_text('wrong cached source')
    result = factors.build_factor_annual_study(raw,settings,tmp_path/'output')
    h = result['frames']['historical_equity_holdings.csv']
    assert len(h) == 12 and set(h.fund) == set(factors.FACTORS)
    assert h.groupby('fund').pdf_page.first().to_dict() == dict(momentum=1,quality=2,value=3)
    assert h.shares_units.eq('units').all()
    assert result['frames']['historical_snapshot_summary.csv'].difference_000_usd.eq(0).all()
    np.testing.assert_allclose(result['frames']['factor_name_overlap.csv'].weighted_equity_overlap,1.,atol=1e-15,rtol=0)
    assert len(result['definitions']['extracted_pages']) == 3


def test_wrong_subfund_page_and_substituted_pdf_fail(factor_pdf,tmp_path):
    raw,settings,_,path = factor_pdf
    changed = copy.deepcopy(settings);changed['schedules'][0]['pages_1based'] = [2]
    with pytest.raises(ValueError,match='identity mismatch'):factors.build_factor_annual_study(raw,changed,tmp_path/'wrong')
    path.write_text('%PDF- changed provider file')
    with pytest.raises(ValueError,match='checksum'):factors.admit_sources(raw,settings)
