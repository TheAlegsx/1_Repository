"""Preserved scenarios, dated historical meanings and portable linked reports."""
import copy
import json

import pandas as pd
import pytest

from factor_portfolio.coordinated_inflow_report import (validate_historical,adapt_backtest,copy_recorded,render_inflow,run_coordinated)
from factor_portfolio.inflow_workflow import sha256


def fixtures():
    returns=[];paired=[];headline=[];manager=[]
    for policy in ['absolute_decoupled','hybrid20']:
        for i in range(23):
            returns.append(dict(policy=policy,kind='coupled' if i<12 else 'overlay',run_id=policy+f'__{i}',fund_window_start='2014-10-03',fund_window_end='2024-10-03',
                mwr_status='undefined_no_invested_external_cohort' if i<5 else 'unique_root_in_scanned_range',aggregate_external_mwr_annual=float('nan') if i<5 else .1,terminal_external_equity_usd=0. if i<5 else 2.))
        for i in range(11):paired.append(dict(policy=policy,run_id=policy+f'__pair_{i}',months=120,overlay_unit_twr_annual=.1))
        for i in range(12):
            id=policy+f'__head_{i}';headline.append(dict(run_id=id,owner_equity_usd=1.,external_equity_usd=2.,closing_aum_usd=3.))
            for fraction in [1.,.5]:manager.append(dict(run_id=id,manager_receipt_fraction=fraction,cumulative_external_business_cash_usd=-100.))
    return dict(historical_returns=pd.DataFrame(returns),historical_interpretation=pd.DataFrame(paired),historical_headline=pd.DataFrame(headline),manager=pd.DataFrame(manager))


def test_actual_historical_window_and_unique_full_cases_cannot_be_extended_or_duplicated():
    frames=fixtures();validate_historical(frames)
    wrong=copy.deepcopy(frames);wrong['historical_returns'].loc[0,'fund_window_end']='2026-08-28'
    with pytest.raises(ValueError,match='dated'):validate_historical(wrong)
    wrong=copy.deepcopy(frames);wrong['historical_interpretation'].loc[0,'months']=119
    with pytest.raises(ValueError,match='unique complete'):validate_historical(wrong)
    wrong=copy.deepcopy(frames);wrong['historical_interpretation'].loc[1,'run_id']=wrong['historical_interpretation'].loc[0,'run_id']
    with pytest.raises(ValueError,match='unique complete'):validate_historical(wrong)


def test_no_investor_mwr_is_not_zero_and_cannot_hide_external_equity():
    for field,value in [('aggregate_external_mwr_annual',0.),('terminal_external_equity_usd',1.)]:
        wrong=fixtures();wrong['historical_returns'].loc[0,field]=value
        with pytest.raises(ValueError):validate_historical(wrong)


def test_negative_business_cash_overlay_invariance_and_ownership_are_interpretation_guards():
    for frame,field,value in [('manager','cumulative_external_business_cash_usd',1.),
        ('historical_interpretation','overlay_unit_twr_annual',.12),('historical_headline','closing_aum_usd',4.)]:
        wrong=fixtures();wrong[frame].loc[0,field]=value
        with pytest.raises(ValueError):validate_historical(wrong)


def test_backtest_link_adaptation_changes_status_not_original_performance_text():
    original='13.24% and 12.92%. The coordinated companion report is the next assembly step.\nCoordinated companion business report pending\nThe coordinated capital-inflow report remains to be assembled with these distinctions and the same source/AI disclosure.'
    linked,changes=adapt_backtest(original)
    assert len(changes)==3 and '13.24% and 12.92%' in linked and '../../inflow/report/' in linked
    assert 'pending' in original and 'business report pending' not in linked
    with pytest.raises(ValueError,match='state differs'):adapt_backtest(linked)


def test_copy_only_sealed_payloads_excludes_caches_and_never_overwrites(tmp_path):
    source=tmp_path/'source';source.mkdir();(source/'config').mkdir();(source/'data.csv').write_text('value\n1\n');(source/'untracked-cache').write_text('excluded')
    (source/'run_manifest.json').write_text(json.dumps(dict(status='complete',run_id='source',figures_included=False,configuration_snapshots={},artifacts={'data.csv':sha256(source/'data.csv')})))
    dest=tmp_path/'dest';manifest,files=copy_recorded(source,dest)
    assert files==['data.csv'] and (dest/'data.csv').read_bytes()==(source/'data.csv').read_bytes()
    assert not (dest/'run_manifest.json').exists() and not (dest/'untracked-cache').exists()
    with pytest.raises(FileExistsError):copy_recorded(source,dest)
    (source/'data.csv').write_text('tampered')
    with pytest.raises(ValueError,match='changed'):copy_recorded(source,tmp_path/'other')


def render_fixture():
    tables=[dict(id=f't{i}',columns=[dict(heading='Case',format='text')],rows=[['Control']]) for i in range(12)]
    claims={'x':dict(display='Hypothetical 6%')};review=dict(figures={f'f{i}':dict(alt='Hypothetical',path=f'../figures/{i}.png') for i in range(8)})
    htables={'h':dict(headers=['Historical'],rows=[],datasets=[])};hclaims={'result':dict(display='10.7339%')}
    template='{{disclosure:author}} {{claim:x}} {{historical:result}} '+''.join('{{table:'+t['id']+'}}' for t in tables)+''.join('{{figure:f'+str(i)+'}}' for i in range(8))+'{{htable:h}}{{hfigure:historical_nav}}{{hfigure:historical_manager}}'
    return template,claims,tables,review,htables,hclaims


def test_hypothetical_and_historical_tokens_remain_separate_and_all_tables_are_required():
    args=render_fixture();text,used=render_inflow(*args,'Comprehensive disclosure')
    assert 'Hypothetical 6%' in text and '10.7339%' in text and len(used['table'])==12 and len(used['hfigure'])==2
    with pytest.raises(ValueError,match='twelve'):render_inflow(args[0].replace('{{table:t11}}',''),*args[1:],'Disclosure')
    with pytest.raises(ValueError,match='identities'):render_inflow(args[0].replace('{{claim:x}}',''),*args[1:],'Disclosure')


def test_visible_disclosure_and_eight_preserved_plus_two_historical_figures_are_required():
    args=render_fixture()
    for token in ['{{disclosure:author}}','{{figure:f7}}','{{hfigure:historical_manager}}']:
        with pytest.raises(ValueError,match='disclosure'):render_inflow(args[0].replace(token,''),*args[1:],'Disclosure')


def test_existing_coordinated_destinations_remain_intact(tmp_path):
    (tmp_path/'preserved').write_text('old')
    with pytest.raises(FileExistsError):run_coordinated(tmp_path,tmp_path/'missing',tmp_path/'missing2',tmp_path)
    assert (tmp_path/'preserved').read_text()=='old'
