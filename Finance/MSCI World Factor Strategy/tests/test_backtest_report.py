"""Report selections, uncertainty, provenance, missing states and portable links."""
import json
from pathlib import Path

import pandas as pd
import pytest

from factor_portfolio.backtest_report import (display,data_table,markdown_table,render,validate_links,
    select_one,report_claims,run_backtest_report)


def test_missing_liquidation_fields_are_unavailable_not_zero_and_nonfinite_results_fail():
    assert display(float('nan'),'usd')=='Unavailable'
    assert display(0.,'usd')=='0.00'
    with pytest.raises(ValueError,match='finite'):display(float('inf'),'pct')


def test_result_cells_preserve_source_rows_when_selected_and_human_policy_labels_change():
    frame=pd.DataFrame([dict(policy='hybrid20',cagr=.1292),dict(policy='absolute_decoupled',cagr=.1324)])
    spec=data_table(frame.iloc[[1]],'main',[('policy','Rule','text'),('cagr','CAGR','pct')])
    assert spec['rows'][0][0]['value']=='absolute_decoupled'
    assert spec['rows'][0][0]['display']=='Absolute / separate leverage'
    number=spec['rows'][0][1];assert number['value']==.1324 and number['origins']==[dict(dataset='main',row=1,field='cagr')]
    assert '13.24%' in markdown_table(spec)


def test_unique_selectors_prevent_silent_policy_or_duplicate_substitution():
    frame=pd.DataFrame([dict(policy='absolute_decoupled',cagr=.1324),dict(policy='hybrid20',cagr=.1292)])
    assert select_one(frame,policy='absolute_decoupled').cagr==.1324
    with pytest.raises(ValueError,match='exactly one'):select_one(frame,policy='quarterly')
    with pytest.raises(ValueError,match='exactly one'):select_one(pd.concat([frame,frame]),policy='absolute_decoupled')


def test_template_requires_every_table_once_disclosure_and_both_figures():
    tables={'x':dict(headers=['Outcome'],rows=[],datasets=[])};claims={}
    template='{{disclosure:author}}\n{{table:x}}\n{{figure:equity}}\n{{figure:drawdown}}'
    text,used=render(template,tables,claims,'Actual author disclosure');assert 'Actual author disclosure' in text and used['table']==['x']
    with pytest.raises(ValueError,match='once'):render(template+'\n{{table:x}}',tables,claims,'Disclosure')
    with pytest.raises(ValueError,match='disclosure'):render(template.replace('{{disclosure:author}}',''),tables,claims,'Disclosure')


def test_local_links_and_anchors_must_resolve_inside_the_run(tmp_path):
    report=tmp_path/'report';report.mkdir();(report/'checks.json').write_text('{}')
    links=validate_links('<a id="appendix-a"></a>\n[A](#appendix-a) [checks](checks.json)',report,tmp_path)
    assert [x['kind'] for x in links]==['anchor','local']
    for text in ['[bad](missing.csv)','[bad](#missing)','[bad](../../outside.csv)']:
        with pytest.raises(ValueError):validate_links(text,report,tmp_path)


def test_provisional_assembly_record_must_exist_before_link_validation(tmp_path):
    report=tmp_path/'report';report.mkdir();text='[Checks](assembly_checks.json)'
    with pytest.raises(ValueError,match='missing'):validate_links(text,report,tmp_path)
    (report/'assembly_checks.json').write_text(json.dumps(dict(status='assembling')))
    assert validate_links(text,report,tmp_path)[0]['kind']=='local'


def test_reviewed_ordering_and_alpha_interpretation_are_not_reused_when_outcomes_change():
    root=Path(__file__).resolve().parents[1]
    # The fixture only exercises the interpretation guards, before supplemental claims are read.
    rows=[]
    for exposure in [1.,1.25]:
        for strategy in ['factor','core','dimensional']:
            rows.append(dict(period='full',strategy=strategy,policy='absolute_decoupled' if strategy=='factor' else 'leverage_managed',
                leverage=exposure,cagr=.13 if strategy=='factor' else .12,annualised_volatility=.18,maximum_drawdown=-.3,alpha_ci_low=-.01,alpha_ci_high=.01))
    frame=pd.DataFrame(rows);baseline=json.loads((root/'config/backtest_absolute_decoupled_2026-10-05.json').read_text())
    worse=frame.copy();worse.loc[0,'cagr']=.11
    with pytest.raises(ValueError,match='ordering'):report_claims(dict(main=worse),baseline,{})
    positive=frame.copy();positive.loc[0,'alpha_ci_low']=.001
    with pytest.raises(ValueError,match='alpha'):report_claims(dict(main=positive),baseline,{})


def test_existing_report_destinations_are_never_overwritten(tmp_path):
    (tmp_path/'preserved').write_text('old report')
    with pytest.raises(FileExistsError):run_backtest_report(tmp_path,tmp_path/'absent_contract',tmp_path)
    assert (tmp_path/'preserved').read_text()=='old report'
