"""Regenerate hypothetical inflows and assemble the two linked discussion reports."""
from __future__ import annotations

import argparse
from datetime import datetime,timezone
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import uuid

import pandas as pd

from .inflow_workflow import CONFIG_NAMES,run_study,sha256,source_hashes,verify_run,write_json
from .inflow_report import configuration_digest,prose_claims
from .inflow_report_tables import markdown_table as hypothetical_table
from .backtest_report import cell,data_table,manual,markdown_table,select_one,validate_links,POLICIES
from .report_contract import contained,verify_bindings,source_markdown,validate_source_register

TOKEN=re.compile(r'\{\{(claim|table|figure|historical|htable|hfigure|disclosure):([a-zA-Z0-9_]+)\}\}')
INFLOW_NAME='CAPITAL_INFLOWS_REPORT_2026-10-06.md'
BACKTEST_NAME='BACKTEST_REPORT_2026-10-06.md'
FLOW_LABELS={'no_flows':'No external flows','limited':'Limited demand','steady':'Steady acquisition','strong':'Strong acquisition',
    'sales_stop':'Sales stop','constant_monthly':'Constant monthly','rising_monthly':'Rising monthly','even_steps':'Even tranches',
    'early_steps':'Early tranches','late_steps':'Late tranches','no_flow_zero_added_fee':'No-flow / no added fund fee'}


def copy_recorded(source,destination,exclude=()):
    """Copy sealed payloads only, never cache directories or a stale root manifest."""
    source,destination=Path(source),Path(destination);verify_run(source)
    if destination.exists():raise FileExistsError('new child destination required')
    destination.mkdir(parents=True);m=json.loads((source/'run_manifest.json').read_text());copied=[]
    for relative in {**m['configuration_snapshots'],**m['artifacts']}:
        if any(relative.startswith(prefix) for prefix in exclude):continue
        src=contained(source,relative);dest=contained(destination,relative);dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(src,dest);copied.append(relative)
    return m,copied


def adapt_backtest(text):
    target='../../inflow/report/'+INFLOW_NAME
    replacements={
        'The coordinated companion report is the next assembly step.':f'The [coordinated companion report]({target}) retains hypothetical scenarios and integrates the dated historical branch.',
        'Coordinated companion business report pending':'Coordinated companion business report included',
        'The coordinated capital-inflow report remains to be assembled with these distinctions and the same source/AI disclosure.':f'The [coordinated capital-inflow report]({target}) carries these distinctions and the same source/AI disclosure.'}
    records=[]
    for old,new in replacements.items():
        if text.count(old)!=1:raise ValueError('expected backtest cross-reference state differs')
        text=text.replace(old,new,1);records.append(dict(original=old,replacement=new))
    return text,records


def validate_historical(frames):
    returns=frames['historical_returns'];paired=frames['historical_interpretation'];manager=frames['manager'];headline=frames['historical_headline']
    if (len(returns)!=46 or len(paired)!=22 or len(manager)!=48 or len(headline)!=24
        or set(returns.policy)!= {'absolute_decoupled','hybrid20'}
        or set(returns.fund_window_start)!= {'2014-10-03'} or set(returns.fund_window_end)!= {'2024-10-03'}):
        raise ValueError('reviewed dated historical scope differs')
    if (returns.duplicated(['kind','run_id']).any() or paired.run_id.duplicated().any()
        or manager.duplicated(['run_id','manager_receipt_fraction']).any() or headline.run_id.duplicated().any()
        or not paired.months.eq(120).all()):raise ValueError('unique complete historical cases required')
    undefined=returns.mwr_status.eq('undefined_no_invested_external_cohort')
    if not returns.loc[undefined,'aggregate_external_mwr_annual'].isna().all():raise ValueError('no-investor MWR must remain undefined')
    if not returns.loc[undefined,'terminal_external_equity_usd'].eq(0).all():raise ValueError('undefined no-cohort scope contains invested equity')
    if not manager.cumulative_external_business_cash_usd.lt(0).all():raise ValueError('reviewed negative-manager interpretation no longer supported')
    for policy,g in paired.groupby('policy'):
        if len(g)!=11 or g.overlay_unit_twr_annual.max()-g.overlay_unit_twr_annual.min()>1e-10:
            raise ValueError('reviewed overlay invariance or plan count differs')
    if not (headline.owner_equity_usd+headline.external_equity_usd-headline.closing_aum_usd).abs().le(1e-6+2e-12*headline.closing_aum_usd.abs()).all():
        raise ValueError('owner/external/total identity differs')


def reader_table(frame,dataset,columns):
    spec=data_table(frame,dataset,columns)
    for row in spec['rows']:
        for item,(field,label,style) in zip(row,columns):
            if field=='flow_plan':item['display']=FLOW_LABELS.get(item['value'],item['display'])
            elif field in ['mwr_status','kind','layer']:item['display']=item['display'].replace('_',' ')
    return spec


def historical_content(frames):
    validate_historical(frames);tables={};claims={};paired=frames['historical_interpretation'];headline=frames['historical_headline'];returns=frames['historical_returns'];manager=frames['manager']
    tables['historical_scope']=manual(['Layer','Return input','Horizon / qualification'],[
        ['Hypothetical v4 controls','Imposed flat/growth/loss paths','Ten scenario years; no portfolio debt or actual market replay'],
        ['Historical coupled fund','Actual market observations with portfolio fee/flow feedback','3 October 2014–3 October 2024; hypothetical fundraising and budgets'],
        ['Historical overlay','Accepted no-flow investment path plus cohort accounting','Same actual dates, without portfolio cash-flow/debt feedback'],
        ['Companion investment backtest','Main borrowed/unlevered strategy comparisons','3 October 2014–28 August 2026; no subscriptions or manager revenue']])
    selected=paired[paired.layer.eq('acquisition')&paired.flow_plan.eq('steady')]
    tables['historical_selected']=reader_table(selected,'historical_interpretation',[
        ('policy','Rule','text'),('coupled_unit_twr_annual','Coupled unit TWR / year','pct'),('overlay_unit_twr_annual','Overlay unit TWR / year','pct'),
        ('unit_twr_difference_pp','Difference','already_pp'),('coupled_external_mwr_annual','Coupled external MWR / year','pct'),('coupled_flow_transaction_cost_usd','Flow charges, USD','usd')])
    ownership=headline[headline.layer.eq('acquisition')]
    tables['historical_ownership']=reader_table(ownership,'historical_headline',[
        ('policy','Rule','text'),('flow_plan','Acquisition plan','text'),('gross_subscriptions_usd','Gross subscriptions, USD m','million'),
        ('owner_equity_usd','Owner invested equity, USD m','million'),('external_equity_usd','External closing equity, USD m','million'),
        ('closing_aum_usd','Total net fund assets, USD m','million'),('redemptions_usd','Cumulative redemptions, USD m','million')])
    rows=[]
    for policy in ['absolute_decoupled','hybrid20']:
        for receipt in [1.,.5]:
            r=select_one(manager,run_id=policy+'__acquisition__steady',manager_receipt_fraction=receipt)
            columns=[('manager_receipt_fraction','pct'),('external_fee_receipts_usd','usd'),('total_manager_cost_usd','usd'),
                ('cumulative_external_business_cash_usd','usd'),('external_business_peak_funding_gap_usd','usd'),
                ('conditional_total_fee_treasury_usd','usd'),('conditional_total_fee_peak_funding_gap_usd','usd')]
            rows.append([cell(POLICIES[policy])]+[cell(r[k],style,dataset='manager',row=int(r.name),field=k) for k,style in columns])
    tables['historical_manager']=dict(headers=['Rule','Receipt','External receipts, USD','Costs, USD','External-business cash, USD',
        'External peak gap, USD','Conditional total-fee cash, USD','Conditional peak gap, USD'],rows=rows,datasets=['manager'])
    tables['historical_returns_full']=reader_table(returns,'historical_returns',[
        ('policy','Rule','text'),('kind','Scope','text'),('layer','Plan family','text'),('flow_plan','Plan','text'),
        ('fund_unit_twr_annual','Fund-window unit TWR','pct'),('external_window_unit_twr_annual','External-window unit TWR','pct'),
        ('aggregate_external_mwr_annual','External MWR','pct'),('mwr_status','Root status','text')])
    controls=headline[headline.layer.eq('control')]
    tables['historical_controls']=reader_table(controls,'historical_headline',[
        ('policy','Rule','text'),('flow_plan','Control','text'),('owner_equity_usd','Owner ending equity, USD m','million'),
        ('fund_fee_usd','Added fund fee, USD','usd'),('transaction_cost_usd','Investment trading cost, USD','usd'),('financing_cost_usd','Financing, USD','usd')])
    def add(key,value,style,origins,expression=None):
        c=cell(value,style,origins=origins,expression=expression)
        if style=='pct4':c['display']=f'{float(value)*100:.4f}%'
        elif style=='money':c['display']=f'USD {float(value):,.2f}'
        claims[key]=c
    for prefix,policy in [('absolute','absolute_decoupled'),('hybrid','hybrid20')]:
        r=select_one(paired,policy=policy,layer='acquisition',flow_plan='steady')
        for key,column,style in [('coupled_twr','coupled_unit_twr_annual','pct4'),('overlay_twr','overlay_unit_twr_annual','pct4'),
            ('gap','unit_twr_difference_pp','already_pp'),('flow_cost','coupled_flow_transaction_cost_usd','money')]:
            add(prefix+'_'+key,r[column],style,[dict(dataset='historical_interpretation',row=int(r.name),field=column)])
    r=select_one(manager,run_id='absolute_decoupled__acquisition__steady',manager_receipt_fraction=1.)
    for key,column in [('absolute_external_receipts','external_fee_receipts_usd'),('absolute_manager_costs','total_manager_cost_usd'),('absolute_peak_gap','external_business_peak_funding_gap_usd')]:
        add(key,r[column],'money',[dict(dataset='manager',row=int(r.name),field=column)])
    add('months',int(paired.months.iloc[0]),'int',[dict(dataset='historical_interpretation',row=0,field='months')])
    add('dated_return_rows',len(returns),'int',[dict(dataset='historical_returns')],'row count')
    add('undefined_mwr',int(returns.mwr_status.eq('undefined_no_invested_external_cohort').sum()),'int',[dict(dataset='historical_returns',field='mwr_status')],'undefined no-invested-external-cohort status count')
    add('manager_cases',len(manager),'int',[dict(dataset='manager')],'row count')
    add('negative_manager_cases',int(manager.cumulative_external_business_cash_usd.lt(0).sum()),'int',[dict(dataset='manager',field='cumulative_external_business_cash_usd')],'negative terminal external-business cash count')
    for key,func in [('manager_cash_min','min'),('manager_cash_max','max')]:
        add(key,getattr(manager.cumulative_external_business_cash_usd,func)(),'money',[dict(dataset='manager',field='cumulative_external_business_cash_usd')],func)
    return tables,claims


def historical_figures(frames,directory):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    directory.mkdir();records=[];coupled=frames['coupled_monthly'];overlay=frames['overlay_monthly'];manager=frames['manager_monthly']
    choices=[('coupled steady',coupled[coupled.run_id.eq('absolute_decoupled__acquisition__steady')],'closing_unit_nav','#17676b'),
        ('overlay steady',overlay[overlay.run_id.eq('absolute_decoupled__acquisition__steady')],'nav_per_unit','#b36a28'),
        ('no-flow / no added fund fee',coupled[coupled.run_id.eq('absolute_decoupled__control__no_flow_zero_added_fee')],'closing_unit_nav','#505865')]
    fig,ax=plt.subplots(figsize=(9.2,4.8),layout='constrained')
    for label,g,field,color in choices:
        g=g.sort_values('month')
        if g.month.tolist()!=list(range(1,121)):raise ValueError('complete monthly historical chart required')
        ax.plot(pd.to_datetime(g.event_date),g[field],label=label,color=color,linewidth=1.7)
        records.extend(dict(figure='historical_nav',series=label,date=row.event_date,value=float(row[field])) for _,row in g.iterrows())
    ax.set(title='Absolute primary: hypothetical historical fund unit NAV',ylabel='Closing unit NAV; initial committed basis 100')
    ax.legend(frameon=False,fontsize=8);ax.grid(axis='y',color='#dfe4e7',linewidth=.6);ax.spines[['top','right']].set_visible(False)
    fig.savefig(directory/'historical_nav.png',dpi=160,metadata={'Software':'MSCI World Factor Strategy reports'});plt.close(fig)
    fig,ax=plt.subplots(figsize=(9.2,4.8),layout='constrained')
    for policy,color in [('absolute_decoupled','#17676b'),('hybrid20','#b36a28')]:
        g=manager[manager.run_id.eq(policy+'__acquisition__steady')&manager.manager_receipt_fraction.eq(1.)].sort_values('month')
        if g.month.tolist()!=list(range(1,121)):raise ValueError('complete manager chart required')
        for field,suffix,style in [('cumulative_external_business_cash_usd','external only','-'),('cumulative_conditional_total_fee_treasury_usd','including conditional owner fees','--')]:
            label=POLICIES[policy]+': '+suffix;values=g[field]/1000
            ax.plot(pd.to_datetime(g.event_date),values,label=label,color=color,linestyle=style,linewidth=1.7)
            records.extend(dict(figure='historical_manager',series=label,date=row.event_date,value=float(row[field])/1000) for _,row in g.iterrows())
    ax.axhline(0,color='#606060',linewidth=.7);ax.set(title='Historical steady acquisition: manager cash outside the fund',ylabel='Cumulative manager cash, USD thousand')
    ax.legend(frameon=False,fontsize=7.5,loc='lower left');ax.grid(axis='y',color='#dfe4e7',linewidth=.6);ax.spines[['top','right']].set_visible(False)
    fig.savefig(directory/'historical_manager.png',dpi=160,metadata={'Software':'MSCI World Factor Strategy reports'});plt.close(fig)
    pd.DataFrame(records).to_csv(directory/'figure_data.csv',index=False)
    return dict(figures=2,points=len(records),scope='Actual-date monthly closing NAV and outside-fund hypothetical manager cash. No future return or fundraising forecast.')


def render_inflow(template,legacy_claims,legacy_tables,legacy_review,htables,hclaims,disclosure):
    used={key:[] for key in ['claim','table','figure','historical','htable','hfigure','disclosure']};by_id={t['id']:t for t in legacy_tables}
    def sub(match):
        kind,key=match.groups();used[kind].append(key)
        if kind=='claim':return legacy_claims[key]['display']
        if kind=='table':return hypothetical_table(by_id[key])
        if kind=='figure':f=legacy_review['figures'][key];return f'![{f["alt"]}]({f["path"]})'
        if kind=='historical':return hclaims[key]['display']
        if kind=='htable':return markdown_table(htables[key])
        if kind=='hfigure':return f'![{key.replace("_"," ")}](../figures/historical/{key}.png)'
        return disclosure
    text=TOKEN.sub(sub,template)
    if '{{' in text or '}}' in text:raise ValueError('unresolved coordinated inflow token')
    if used['table']!=list(by_id) or len(set(used['table']))!=12:raise ValueError('preserved twelve hypothetical tables required once')
    if set(used['claim'])!=set(legacy_claims):raise ValueError('all retained hypothetical claim identities required')
    if set(used['htable'])!=set(htables) or len(used['htable'])!=len(htables):raise ValueError('all historical tables required once')
    if used['disclosure']!=['author'] or set(used['hfigure'])!={'historical_nav','historical_manager'} or len(used['figure'])!=8:
        raise ValueError('visible disclosure, eight preserved and two historical figures required')
    return text,used


def seal(directory,scope,code,**metadata):
    directory=Path(directory);configs={str(f.relative_to(directory)):sha256(f) for f in (directory/'config').rglob('*') if f.is_file()}
    artifacts={str(f.relative_to(directory)):sha256(f) for f in sorted(directory.rglob('*')) if f.is_file() and f!=directory/'run_manifest.json'
        and f.relative_to(directory).parts[0]!='config' and '_cache' not in f.relative_to(directory).parts}
    m=dict(schema_version=1,run_id=str(uuid.uuid4()),status='complete',figures_included=True,finished_at_utc=datetime.now(timezone.utc).isoformat(),
        scope=scope,code=code,configuration_snapshots=configs,artifacts=artifacts,**metadata)
    write_json(directory/'run_manifest.json',m);verify_run(directory);return m


def run_coordinated(root,contract_dir,backtest_dir,output):
    root=Path(root).resolve();contract_dir=Path(contract_dir);backtest_dir=Path(backtest_dir);output=Path(output)
    if output.exists():raise FileExistsError('choose a new coordinated-report output directory')
    verify_run(contract_dir);verify_run(backtest_dir);contract=json.loads((contract_dir/'evidence_contract.json').read_text());verify_bindings(root,contract)
    resource=Path(__file__).parent/'templates';template=(resource/'coordinated_inflow_report_2026-10-06.md').read_bytes();review_bytes=(resource/'coordinated_inflow_review_2026-10-06.json').read_bytes();review=json.loads(review_bytes)
    if hashlib.sha256(template).hexdigest()!=review['template_sha256']:raise ValueError('coordinated template requires renewed review')
    legacy_run=contained(root,contract['resolved_runs']['inflow_v4']['path'])
    configs={n:(legacy_run/'config'/n).read_bytes() for n in CONFIG_NAMES};parsed={n:json.loads(b) for n,b in configs.items()}
    if any(configuration_digest(parsed[n])!=review['reviewed_configuration_sha256'][n] for n in CONFIG_NAMES):raise ValueError('retained hypothetical assumptions require renewed review')
    backtest_manifest=json.loads((backtest_dir/'run_manifest.json').read_text());contract_manifest=json.loads((contract_dir/'run_manifest.json').read_text())
    if backtest_manifest['source_contract_run_id']!=contract_manifest['run_id']:raise ValueError('backtest and inflow preparation use different evidence selections')
    output.mkdir();(output/'config').mkdir();code=source_hashes()
    for n,b in configs.items():(output/'config'/n).write_bytes(b)
    (output/'config/coordinated_inflow_template.md').write_bytes(template);(output/'config/coordinated_inflow_review.json').write_bytes(review_bytes)
    m=dict(schema_version=1,run_id=str(uuid.uuid4()),status='running',figures_included=True,started_at_utc=datetime.now(timezone.utc).isoformat(),code=code,
        configuration_snapshots={str(f.relative_to(output)):sha256(f) for f in (output/'config').iterdir()},artifacts={},
        source_contract_run_id=contract_manifest['run_id'],source_backtest_run_id=backtest_manifest['run_id'],scope='Linked backtest version9 and inflow version5 working reports; no original replacement or publication.')
    write_json(output/'run_manifest.json',m)
    try:
        import matplotlib
        with matplotlib.rc_context({'svg.hashsalt':'msci-world-factor-coordinated-reports'}):
            hypothetical=run_study(output/'config',output/'hypothetical_v4',figures=True,report=True)
        copy_recorded(output/'hypothetical_v4',output/'inflow',exclude=('report/','README.md'))
        inflow=output/'inflow';(inflow/'report').mkdir();evidence=inflow/'evidence';evidence.mkdir();frames={};bindings={}
        for key in ['historical_headline','historical_returns','manager','historical_interpretation','actual_execution','historical_definitions']:
            d=contract['resolved_datasets'][key];src=contained(root,d['project_path']);dest=evidence/(key+src.suffix);shutil.copyfile(src,dest);bindings[key]=dict(**d,artifact=str(dest.relative_to(inflow)))
            if src.suffix=='.csv':frames[key]=pd.read_csv(dest,float_precision='round_trip')
        historical_run=contract['resolved_runs']['historical'];hd=contained(root,historical_run['path']);hm=json.loads((hd/'run_manifest.json').read_text())
        for key,relative in [('coupled_events','pilot/coupled_trade_events.csv'),('coupled_daily','pilot/coupled_daily.csv'),('coupled_monthly','pilot/coupled_monthly.csv'),('overlay_monthly','pilot/overlay_diagnostic_monthly.csv'),('manager_monthly','manager_monthly.csv')]:
            src=contained(hd,relative)
            if sha256(src)!=hm['artifacts'][relative]:raise ValueError('historical monthly source differs')
            dest=evidence/(key+'.csv');shutil.copyfile(src,dest);bindings[key]=dict(project_path=historical_run['path']+'/'+relative,sha256=sha256(src),artifact=str(dest.relative_to(inflow)));frames[key]=pd.read_csv(dest,float_precision='round_trip')
        if json.loads((evidence/'actual_execution.json').read_text())['execution_version']!=2:raise ValueError('executed historical v2 required')
        htables,hclaims=historical_content(frames);plot=historical_figures(frames,inflow/'figures/historical')
        specs=json.loads((inflow/'report_tables/report_tables.json').read_text());legacy_payload=json.loads((output/'hypothetical_v4/report/claims.json').read_text());legacy_claims=legacy_payload['claims'];legacy_review=json.loads((output/'hypothetical_v4/report/template_review.json').read_text())
        text,used=render_inflow(template.decode(),legacy_claims,specs,legacy_review,htables,hclaims,contract['disclosure'])
        (inflow/'report'/INFLOW_NAME).write_text(text);(inflow/'report/template.md').write_bytes(template);(inflow/'report/template_review.json').write_bytes(review_bytes)
        write_json(inflow/'report/claims.json',dict(**legacy_payload,coordinated_scope='Preserved hypothetical claim values, now accompanied by a distinct dated historical branch.'))
        write_json(inflow/'report/historical_claims.json',dict(claims=hclaims,occurrences={k:used['historical'].count(k) for k in sorted(set(used['historical']))},manual_context=review['manual_context']))
        write_json(inflow/'report/historical_tables.json',htables);write_json(evidence/'input_bindings.json',bindings);write_json(inflow/'figures/historical/plot_definitions.json',plot)
        registry=json.loads((contract_dir/'config/SOURCE_DOWNLOAD_REGISTER_2026-10-06.json').read_text());validate_source_register(registry)
        shutil.copyfile(contract_dir/'config/SOURCE_DOWNLOAD_REGISTER_2026-10-06.json',inflow/'config/SOURCE_DOWNLOAD_REGISTER_2026-10-06.json')
        (inflow/'report/source_register.md').write_text(source_markdown(registry,contract['disclosure']))
        source,copied=copy_recorded(backtest_dir,output/'backtest');backtest=output/'backtest';f=backtest/'report'/BACKTEST_NAME;linked,adaptations=adapt_backtest(f.read_text());f.write_text(linked)
        t=json.loads((backtest/'report/tables.json').read_text());changed=0
        for row in t['backtest_30']['rows']:
            for value in row:
                if value['display']=='Coordinated companion business report pending':value['display']=value['value']='Coordinated companion business report included';changed+=1
        if changed!=1:raise ValueError('expected backtest manual scope cell differs')
        write_json(backtest/'report/tables.json',t);write_json(backtest/'report/link_adaptation.json',dict(source_run_id=source['run_id'],text_changes=adaptations,
            changed_manual_scope_cells=1,numerical_cells_claims_and_figures_unchanged=True,scope='Cross-reference/status adaptation only, original standalone report preserved.'))
        (backtest/'README.md').write_text('# Linked Backtest Report\n\n[Backtest version9](report/'+BACKTEST_NAME+') · [Coordinated inflow version5](../inflow/report/'+INFLOW_NAME+') · [Link adaptation](report/link_adaptation.json) · [Manifest](run_manifest.json)\n\nNumerical results, claims and charts retained from the verified standalone backtest; only companion references/status are adapted. Local discussion package, not a public release.\n')
        (inflow/'README.md').write_text('# Coordinated Capital-Inflow Report\n\n[Inflow version5](report/'+INFLOW_NAME+') · [Companion backtest](../backtest/report/'+BACKTEST_NAME+') · [Sources](report/source_register.md) · [Manifest](run_manifest.json)\n\nPreserved hypothetical assumptions and regenerated tables/plots plus captured dated historical evidence. Owner, external and manager quantities remain distinct.\n')
        # All cross-report targets and linked manifests exist before link admission.
        for child in [inflow,backtest]:
            write_json(child/'run_manifest.json',dict(status='assembling'));write_json(child/'report/assembly_checks.json',dict(status='assembling'))
        inflow_links=validate_links(text,inflow/'report',output);backtest_links=validate_links(linked,backtest/'report',output)
        write_json(inflow/'report/assembly_checks.json',dict(status='complete',hypothetical_tables=12,historical_tables=len(htables),hypothetical_claims=len(legacy_claims),
            historical_claims=len(hclaims),figures=10,links=inflow_links,same_author_disclosure=True,scope='Hypothetical and historical branches distinct; cells/claims/provenance/links, not expert approval or future business validation.'))
        bc=json.loads((backtest_dir/'report/assembly_checks.json').read_text());bc['links']=backtest_links;bc['coordinated_companion_included']=True;write_json(backtest/'report/assembly_checks.json',bc)
        seal(backtest,'Linked version9 copy; numerical content/plots unchanged, companion references adapted.',code,source_run_id=source['run_id'])
        seal(inflow,'New version5 with preserved v4 hypothetical assumptions and declared historical evidence.',code,source_hypothetical_run_id=hypothetical['run_id'])
        (output/'README.md').write_text('# MSCI World Factor Strategy — Coordinated Research Reports\n\n'
            '- [Investment backtest, version9](backtest/report/'+BACKTEST_NAME+')\n- [Capital inflows and fund economics, version5](inflow/report/'+INFLOW_NAME+')\n'
            '- [Source/download register](inflow/report/source_register.md)\n- [Run manifest](run_manifest.json)\n\n'
            'Local discussion package. Absolute sleeve bands and separate leverage are primary; capped-relative remains a comparison. '
            'Historical and hypothetical business scenarios remain separate. Extensive AI assistance is disclosed visibly in both reports. '
            'Detailed provider-derived evidence here remains local; no publication or prior group-package replacement is implied.\n')
        verify_bindings(root,contract);verify_run(backtest_dir);verify_run(output/'hypothetical_v4')
        if source_hashes()!=code:raise RuntimeError('source/templates changed during coordinated assembly')
        m['artifacts']={str(f.relative_to(output)):sha256(f) for f in sorted(output.rglob('*')) if f.is_file() and f!=output/'run_manifest.json'
            and f.relative_to(output).parts[0]!='config' and '_cache' not in f.relative_to(output).parts}
        m.update(status='complete',finished_at_utc=datetime.now(timezone.utc).isoformat(),counts=dict(reports=2,hypothetical_tables=12,historical_tables=len(htables),
            hypothetical_claims=len(legacy_claims),historical_claims=len(hclaims),inflow_figures=10,backtest_figures=2,historical_plot_rows=plot['points']))
        write_json(output/'run_manifest.json',m);verify_run(output)
    except Exception as error:
        m.update(status='failed',failure=dict(type=type(error).__name__,message=str(error)));write_json(output/'run_manifest.json',m);raise
    return m


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--project-root',type=Path,default=Path.cwd())
    p.add_argument('--contract',type=Path,default=Path('outputs/coordinated_report_contract_v2_2026-10-06'))
    p.add_argument('--backtest',type=Path,default=Path('outputs/backtest_report_v4_2026-10-06'));p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();m=run_coordinated(a.project_root,a.contract,a.backtest,a.output);print(json.dumps(dict(run_id=m['run_id'],counts=m['counts']),indent=2))


if __name__=='__main__':main()
