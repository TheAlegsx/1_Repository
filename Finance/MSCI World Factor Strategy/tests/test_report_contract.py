"""Evidence/ownership separation, dated return links and source privacy."""
import copy
import json
from pathlib import Path

import pandas as pd
import pytest

from factor_portfolio.report_contract import (contained,validate_settings,validate_source_register,
    select_claim,link_historical_returns,ai_disclosure,verify_bindings,run_contract,validate_table_catalog)
from factor_portfolio.inflow_workflow import sha256

ROOT=Path(__file__).resolve().parents[1]


def test_report_inventory_separates_primary_periods_and_hypothetical_scenarios():
    settings=json.loads((ROOT/'config/coordinated_reports_2026-10-06.json').read_text());validate_settings(settings)
    for key,value in [('historical_inflow_period',['2014-10-03','2026-08-28']),
        ('primary_backtest_cagr_is_not_constant_inflow_return',False),('manager_cash_excludes_owner_and_external_portfolio_wealth',False),
        ('execution_contract','original_proposal')]:
        wrong=copy.deepcopy(settings);wrong['report_separation'][key]=value
        with pytest.raises(ValueError,match='separation'):validate_settings(wrong)
    duplicate=copy.deepcopy(settings);duplicate['tables'][1]['id']=duplicate['tables'][0]['id']
    with pytest.raises(ValueError,match='inventory'):validate_settings(duplicate)
    unreviewed=copy.deepcopy(settings);unreviewed['tables'][0]['assembly_status']='complete'
    with pytest.raises(ValueError,match='final report'):validate_settings(unreviewed)


def test_sources_preserve_unknown_dates_and_reject_private_url_parameters():
    registry=json.loads((ROOT/'docs/SOURCE_DOWNLOAD_REGISTER_2026-10-06.json').read_text());validate_source_register(registry)
    for query in ['track1=private','user=private','access_token=private','sig=private']:
        wrong=copy.deepcopy(registry);wrong['sources'][0]['source_url']='https://example.org/paper?'+query
        with pytest.raises(ValueError,match='private'):validate_source_register(wrong)
    wrong=copy.deepcopy(registry);amundi=next(x for x in wrong['sources'] if x['id']=='amundi_2x');amundi['retrieved_date']='2025-09-30'
    with pytest.raises(ValueError,match='Amundi'):validate_source_register(wrong)


def test_exact_claim_selection_never_substitutes_the_comparison_or_duplicates():
    frame=pd.DataFrame([dict(policy='absolute_decoupled',cagr=.1324),dict(policy='hybrid20',cagr=.1292)])
    definition=dict(id='headline',selection=dict(policy='absolute_decoupled'),field='cagr',display='percent_4dp')
    selected=select_claim(frame,definition);assert selected['value']==.1324 and selected['display_value']=='13.2400'
    with pytest.raises(ValueError,match='exactly one'):select_claim(pd.concat([frame,frame]),definition)
    with pytest.raises(ValueError,match='finite'):select_claim(frame.assign(cagr=float('nan')),definition)


def historical_fixture():
    baseline=json.loads((ROOT/'config/backtest_absolute_decoupled_2026-10-05.json').read_text());capital=baseline['initial_equity_usd']
    dates=pd.DatetimeIndex([pd.Timestamp('2014-10-03')+pd.DateOffset(months=m) for m in range(121)],name='date')
    histories={};rows=[]
    for policy in ['absolute_decoupled','hybrid20']:
        # Opening costs reduce equity before the first interval; owner NAV uses committed capital.
        equity=[capital*.99*1.003**m for m in range(121)]
        histories[policy]=pd.DataFrame(dict(equity_usd=equity),index=dates)
        for m in range(1,121):
            rows.append(dict(policy=policy,month=m,actual_start=str(dates[m-1].date()),actual_end=str(dates[m].date()),
                source_opening_equity_usd=equity[m-1],source_closing_equity_usd=equity[m],strategy_net_interval_return=.003,
                no_flow_zero_added_fee_owner_equity_usd=equity[m],no_flow_unit_nav=equity[m]/capital*100))
    return pd.DataFrame(rows),histories,baseline


def test_historical_link_preserves_opening_cost_and_checks_all_dated_intervals():
    basis,histories,baseline=historical_fixture();checks=link_historical_returns(basis,histories,baseline)
    assert len(checks)==1200 and checks.passed.all()
    wrong=basis.copy();wrong.loc[0,'no_flow_unit_nav']=100*1.003
    with pytest.raises(ValueError,match='does not match'):link_historical_returns(wrong,histories,baseline)
    wrong=basis.copy();wrong.loc[0,'strategy_net_interval_return']=.1324/12
    with pytest.raises(ValueError,match='does not match'):link_historical_returns(wrong,histories,baseline)


def test_incomplete_duplicated_or_extended_historical_horizons_fail():
    basis,histories,baseline=historical_fixture()
    for wrong in [basis.iloc[:-1],pd.concat([basis.iloc[:-1],basis.iloc[[0]]])]:
        with pytest.raises(ValueError,match='complete unique'):link_historical_returns(wrong,histories,baseline)
    wrong=basis.copy();wrong.loc[119,'actual_end']='2026-08-28'
    with pytest.raises(ValueError,match='horizon'):link_historical_returns(wrong,histories,baseline)


def test_comprehensive_author_disclosure_is_copied_without_other_member_claims():
    doc=(ROOT/'docs/AI_USE.md').read_text();paragraph=ai_disclosure(doc)
    assert 'extensive assistance' in paragraph and paragraph in doc
    assert 'methodology development' in paragraph and 'report drafting' in paragraph
    with pytest.raises(ValueError,match='comprehensive'):ai_disclosure('AI helped with spelling.')


def test_paths_and_source_binding_detect_escape_and_identity_drift(tmp_path):
    for path in ['../private','/tmp/private']:
        with pytest.raises(ValueError,match='contained'):contained(tmp_path,path)
    (tmp_path/'escape').symlink_to(ROOT)
    with pytest.raises(ValueError,match='escapes'):contained(tmp_path,'escape/README.md')
    directory=tmp_path/'source';directory.mkdir();f=directory/'run_manifest.json';f.write_text(json.dumps(dict(run_id='old')))
    contract=dict(resolved_runs=dict(main=dict(path='source',run_id='old',manifest_sha256=sha256(f))),resolved_datasets={})
    f.write_text(json.dumps(dict(run_id='new')))
    with pytest.raises(ValueError,match='identity'):verify_bindings(tmp_path,contract)


def test_existing_destination_and_its_contents_are_preserved(tmp_path):
    (tmp_path/'retain').write_text('existing')
    with pytest.raises(FileExistsError):run_contract(ROOT,ROOT/'config/coordinated_reports_2026-10-06.json',tmp_path)
    assert (tmp_path/'retain').read_text()=='existing'


def public_catalog_fixture():
    settings = json.loads((ROOT/'config/coordinated_reports_2026-10-06.json').read_text())
    catalog = json.loads((ROOT/settings['coverage']).read_text())
    return settings, catalog


def test_public_catalog_retains_all_families_without_private_archive_fields():
    settings, catalog = public_catalog_fixture()
    validate_settings(settings)
    validate_table_catalog(catalog, settings)
    assert len(catalog['tables']) == 42
    assert sum(row['report'] == 'backtest' for row in catalog['tables']) == 30
    assert sum(row['report'] == 'capital_inflows' for row in catalog['tables']) == 12
    assert all('original_report_sha256' not in table and 'original_report' not in table for table in settings['tables'])


@pytest.mark.parametrize('corruption', ['missing', 'duplicate', 'reordered', 'section', 'fingerprint'])
def test_public_catalog_rejects_lost_or_changed_bindings_and_private_fingerprints(corruption):
    settings, catalog = public_catalog_fixture()
    validate_table_catalog(catalog, settings)
    wrong = copy.deepcopy(catalog)
    if corruption == 'missing':
        wrong['tables'].pop()
    elif corruption == 'duplicate':
        wrong['tables'][1] = copy.deepcopy(wrong['tables'][0])
    elif corruption == 'reordered':
        wrong['tables'][0], wrong['tables'][1] = wrong['tables'][1], wrong['tables'][0]
    elif corruption == 'section':
        wrong['tables'][0]['section'] = 'unreviewed section'
    else:
        wrong['tables'][0]['private_artifact_sha256'] = 'a'*64
    expected_error = 'inventory' if corruption in ['missing', 'duplicate'] else 'fields' if corruption == 'fingerprint' else 'bindings'
    with pytest.raises(ValueError, match=expected_error):
        validate_table_catalog(wrong, settings)
