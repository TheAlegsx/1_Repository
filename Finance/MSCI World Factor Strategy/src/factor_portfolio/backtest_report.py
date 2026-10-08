"""Assemble the selected backtest report from sealed component evidence."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
from urllib.parse import unquote, urlsplit
import uuid

import pandas as pd

from .inflow_workflow import sha256, source_hashes, verify_run, write_json
from .report_contract import contained, verify_bindings, validate_source_register, source_markdown

TOKEN=re.compile(r'\{\{(table|claim|figure|disclosure):([a-zA-Z0-9_]+)\}\}')
LINK=re.compile(r'\[[^\]]*\]\(([^)]+)\)')
POLICIES={'absolute_decoupled':'Absolute / separate leverage','hybrid20':'Capped-relative comparison',
    'legacy_absolute':'Legacy coupled absolute','relative20':'Relative 20%','quarterly':'Quarterly','annual':'Annual',
    'no_sleeve':'No sleeve resets','passive_debt':'Passive debt','leverage_managed':'Leverage managed'}
STRATEGIES={'factor':'Factor portfolio','core':'MSCI World Core','dimensional':'Dimensional'}


def plain(value):
    if hasattr(value,'item'):value=value.item()
    return value


def display(value,kind='text'):
    if pd.isna(value):return 'Unavailable'
    formats={'pct':(100.,'.2f','%'),'pp':(100.,'.4f',' pp'),'already_pp':(1.,'.4f',' pp'),
        'ratio':(1.,'.3f',''),'million':(1e-6,'.2f',''),'usd':(1.,',.2f',''),'int':(1.,'.0f',''),
        'bps':(1.,'.6f','')}
    if kind not in formats:return str(value)
    scale,form,suffix=formats[kind]
    if not math.isfinite(float(value)):raise ValueError('finite displayed result required')
    return format(float(value)*scale,form)+suffix


def cell(value,kind='text',*,dataset=None,row=None,field=None,expression=None,origins=None):
    return dict(value=plain(value) if not pd.isna(value) else None,display=display(value,kind),
        origins=origins or ([dict(dataset=dataset,row=row,field=field)] if dataset else []),expression=expression)


def data_table(frame,dataset,columns):
    """Keep original CSV row indices as the source of every displayed cell."""
    rows=[]
    for index,row in frame.iterrows():
        cells=[cell(row[field],kind,dataset=dataset,row=int(index),field=field) for field,label,kind in columns]
        for entry,(field,label,kind) in zip(cells,columns):
            if kind=='text':
                if field=='policy':entry['display']=POLICIES.get(entry['value'],entry['display'])
                elif field=='strategy':entry['display']=STRATEGIES.get(entry['value'],entry['display'].replace('_',' '))
                elif field=='period':entry['display']={'calibration':'Early (retrospective)','confirmation':'Later (retrospective)'}.get(entry['value'],entry['display'])
                elif field in ['allocation','regime','counterfactual','type','status']:entry['display']=entry['display'].replace('_',' ')
        rows.append(cells)
    return dict(headers=[label for field,label,kind in columns],rows=rows,datasets=[dataset])


def manual(headers,rows):
    return dict(headers=headers,rows=[[cell(x) for x in row] for row in rows],datasets=[],manual=True)


def select_one(frame,**selection):
    for key,value in selection.items():frame=frame[frame[key].eq(value)]
    if len(frame)!=1:raise ValueError('report requires exactly one selected source row')
    return frame.iloc[0]


def result_tables(frames,baseline,registry,contract):
    tables={};weights=baseline['target_weights'];main=frames['main']
    select=lambda **q:select_one(main,**q)
    factor=lambda lev,policy='absolute_decoupled':select(period='full',strategy='factor',policy=policy,leverage=lev)
    result_cols=[('cagr','CAGR','pct'),('annualised_volatility','Volatility','pct'),('maximum_drawdown','Drawdown','pct'),
        ('sharpe_ratio','Sharpe','ratio'),('ending_equity_usd','Ending equity, USD m','million')]
    def portfolio_table(exposure):
        rows=[]
        for strategy,policy in [('factor','absolute_decoupled'),('factor','hybrid20'),('core','leverage_managed'),('dimensional','leverage_managed')]:
            r=select(period='full',strategy=strategy,policy=policy,leverage=exposure)
            label=POLICIES[policy] if strategy=='factor' else STRATEGIES[strategy]
            rows.append([cell(label)]+[cell(r[f],k,dataset='main',row=int(r.name),field=f) for f,l,k in result_cols])
        return dict(headers=['Investment / rule']+[l for f,l,k in result_cols],rows=rows,datasets=['main'])
    tables['backtest_01']=manual(['Sleeve','Target','Economic role'],[[s.title(),display(w,'pct'),role] for (s,w),role in zip(weights.items(),['Broad developed-market anchor','Relative-performance selection','Financial-quality selection','Valuation selection'])])
    for row,(s,w) in zip(tables['backtest_01']['rows'],weights.items()):row[1]=cell(w,'pct',origins=[dict(config='baseline',field='target_weights.'+s)])
    tables['backtest_02']=manual(['Reference','Purpose','Qualification'],[
        ['MSCI World Core ETF','Investable broad-market alternative','NAV already includes fund expenses'],
        ['Dimensional Global Core Equity','Existing systematic alternative','Broader mandate; user-confirmed USD share-class mapping'],
        ['Amundi daily 2x product','Separate implementation diagnostic','Daily reset, different exposure and shorter available history']])
    tables['backtest_03']=manual(['Input','Role','Limit'],[
        ['Four iShares USD accumulating NAV exports','Sleeves and Core','Provider NAV precision, not executable fills'],
        ['Dimensional Bloomberg USD hardcopy','Systematic comparator','Independent parsing, no second complete feed'],
        ['New York Fed indicative / official SOFR','Reference financing and risk-free accrual','Indicative early series; not account-specific credit'],
        ['Amundi NAV and Bloomberg listing/index evidence','Short product comparison / spreads','Separate calendar; Amundi original download provenance unknown'],
        ['Issuer exports and annual PDFs','Holdings / concentration','Sparse, non-synchronized dates; no full historical sector panel']])
    tables['backtest_04']=manual(['Assumption','Basis','Challenge'],[
        ['Next common NAV execution','Previously formed signal','No executable/intraday/settlement reconstruction'],
        ['Current ordinary broker tariff','Fixed scenario throughout history','Not historical invoices or a negotiated offer'],
        ['Duty / one-way spread','Declared model components','Account tax/venue treatment and launch/tail spreads differ'],
        ['Reference plus fixed markup','Research financing scenario','Margin grid and joint-cost stress; no approved credit terms'],
        ['Calendar ACT/360 and NAV-date capitalization','Explicit accounting convention','Actual fixing/day count/posting unconfirmed'],
        ['Absolute bands and separate leverage','Simplicity and consciously accepted factor drift','Ex-post selection; retained capped-relative and other controls'],
        ['Baseline without custody','Separate cost layers','Private full/excess and legal-entity paths separately recalculated']])
    tables['backtest_05']=portfolio_table(1.);tables['backtest_06']=portfolio_table(1.25)
    ep=frames['endpoints'];ep_rows=[]
    for date in ep.requested_end.drop_duplicates():
        for lev in [1.,1.25]:
            group=ep[ep.requested_end.eq(date)&ep.leverage.eq(lev)];r=select_one(group,strategy='factor',policy='absolute_decoupled');old=select_one(group,strategy='factor',policy='hybrid20');core=select_one(group,strategy='core')
            ep_rows.append([cell(r['end'],dataset='endpoints',row=int(r.name),field='end'),cell(lev,'ratio',dataset='endpoints',row=int(r.name),field='leverage')]+[
                cell(z.cagr,'pct',dataset='endpoints',row=int(z.name),field='cagr') for z in [r,old,core]]+
                [cell(r.cagr-core.cagr,'pp',expression='primary cagr minus core cagr',origins=[dict(dataset='endpoints',row=int(z.name),field='cagr') for z in [r,core]])])
    tables['backtest_07']=dict(headers=['Observed end','Exposure','Primary CAGR','Capped-relative CAGR','Core CAGR','Primary − Core'],rows=ep_rows,datasets=['endpoints'])
    letters=list('ABCDEFGHIJKL');titles=['Allocations / hindsight','Policies / drift','Risk measures / alpha','Periods / windows / entries','Correlations','Financing / costs','Gap cures / implementation','Artificial regimes','Historical holdings','Leveraged-product overlap','Sources / checks / evidence','Scope / capital-inflow connection']
    tables['backtest_08']=manual(['Appendix','Material'],[[f'[{l}](#appendix-{l.lower()})',t] for l,t in zip(letters,titles)])
    allocations=frames['allocations'];g=allocations[allocations.period.eq('full')&allocations.strategy.eq('factor')]
    tables['backtest_09']=data_table(g,'allocations',[('allocation','Allocation','text'),('policy','Rule','text'),('core_weight','Core','pct'),('momentum_weight','Momentum','pct'),('quality_weight','Quality','pct'),('value_weight','Value','pct')]+result_cols[:-1])
    h=frames['hindsight'];tables['backtest_10']=data_table(h[h.display_representative.eq(True)],'hindsight',[
        ('leverage','Exposure','ratio'),('core_weight','Core','pct'),('momentum_weight','Momentum','pct'),('quality_weight','Quality','pct'),('value_weight','Value','pct'),('sleeve_band','Absolute band','pp'),('leverage_band','Leverage band','ratio'),('cagr','Grid maximum CAGR','pct'),('exact_tie_count','Exact ties','int')])
    bands=[]
    for sleeve,w in weights.items():
        smaller=min(.05,.2*w)
        bands.append([cell(sleeve.title()),cell(w,'pct',origins=[dict(config='baseline',field='target_weights.'+sleeve)]),
            cell(f'{100*(w-.05):g}–{100*(w+.05):g}%',expression='target ± sleeve_band',origins=[dict(config='baseline',field='target_weights.'+sleeve),dict(config='baseline',field='sleeve_band')]),cell(f'{100*(w-smaller):g}–{100*(w+smaller):g}%',expression='target ± min(0.05, 0.2*target)',origins=[dict(config='baseline',field='target_weights.'+sleeve)])])
    tables['backtest_11']=dict(headers=['Sleeve','Target','New absolute band','Capped-relative comparison'],rows=bands,datasets=[])
    tables['backtest_12']=data_table(main[main.period.eq('full')&main.strategy.eq('factor')],'main',[
        ('policy','Rule','text'),('leverage','Exposure','ratio')]+result_cols[:3]+[('trades_after_entry','Post-entry events','int'),('transaction_cost_usd','Trading costs, USD','usd'),('mean_absolute_sleeve_drift','Mean absolute drift','pp')])
    headline=main[main.period.eq('full')&((main.strategy.eq('factor')&main.policy.isin(['absolute_decoupled','hybrid20']))|main.strategy.isin(['core','dimensional']))]
    tables['backtest_13']=data_table(headline,'main',[('strategy','Investment','text'),('policy','Rule','text'),('leverage','Exposure','ratio'),('beta_vs_unlevered_core','Beta','ratio'),('jensen_alpha','Alpha / year','pct'),('alpha_ci_low','HAC low','pct'),('alpha_ci_high','HAC high','pct'),('treynor_ratio','Treynor','ratio'),('sortino_ratio','Sortino','ratio'),('calmar_ratio','Calmar','ratio')])
    periods=main[main.period.isin(['calibration','confirmation'])&((main.strategy.eq('factor')&main.policy.isin(['absolute_decoupled','hybrid20']))|main.strategy.isin(['core','dimensional']))]
    tables['backtest_14']=data_table(periods,'main',[('period','Retrospective period','text'),('strategy','Investment','text'),('policy','Rule','text'),('leverage','Exposure','ratio')]+result_cols[:3])
    tables['backtest_15']=data_table(frames['rolling'],'rolling',[('policy','Rule','text'),('leverage','Exposure','ratio'),('horizon_years','Years','int'),('windows','Windows','int'),('higher_cagr_share','Higher CAGR share','pct'),('median_cagr_difference','Median CAGR gap','pp'),('no_higher_volatility_share','No higher volatility','pct'),('no_deeper_drawdown_share','No deeper drawdown','pct')])
    entry_rows=[];en=frames['entries']
    for date in en.requested_entry.drop_duplicates():
        g=en[en.requested_entry.eq(date)&en.leverage.eq(1.25)];parts=[select_one(g,strategy='factor',policy=p) for p in ['absolute_decoupled','hybrid20']]+[select_one(g,strategy=s) for s in ['core','dimensional']]
        if len({r['start'] for r in parts})!=1:raise ValueError('entry comparison calendars differ')
        entry_rows.append([cell(date),cell(parts[0]['start'],dataset='entries',row=int(parts[0].name),field='start')]+[cell(r.cagr,'pct',dataset='entries',row=int(r.name),field='cagr') for r in parts])
    tables['backtest_16']=dict(headers=['Requested entry','Actual start','Primary CAGR','Capped-relative CAGR','Core CAGR','Dimensional CAGR'],rows=entry_rows,datasets=['entries'])
    for id,key in [('backtest_17','long_correlations'),('backtest_18','short_correlations')]:
        f=frames[key];tables[id]=data_table(f,key,[(col,'Product' if i==0 else col,'text' if i==0 else 'ratio') for i,col in enumerate(f.columns)])
    tables['backtest_19']=data_table(frames['comparator_costs'],'comparator_costs',[
        ('policy','Factor rule','text'),('leverage','Exposure','ratio'),('factor_baseline_cagr','Factor CAGR','pct'),('dimensional_zero_external_cost_cagr','Dimensional zero external fees','pct'),('factor_cagr_gap','Gap','pp')])
    tables['backtest_20']=data_table(frames['bridge'],'bridge',[('counterfactual','Counterfactual','text'),('cagr','CAGR','pct'),('ending_equity_usd','Equity, USD m','million')])
    fu=frames['funding'];fu=fu[fu.strategy.eq('factor')];funding=[]
    for bp in fu.margin_bps.drop_duplicates():
        full=select_one(fu,period='full',margin_bps=bp);late=select_one(fu,period='confirmation',margin_bps=bp)
        funding.append([cell(bp,'int',dataset='funding',row=int(full.name),field='margin_bps')]+[cell(r.cagr,'pct',dataset='funding',row=int(r.name),field='cagr') for r in [full,late]])
    tables['backtest_21']=dict(headers=['Markup above reference, bp','Primary full CAGR','Primary later CAGR'],rows=funding,datasets=['funding'])
    cu=frames['custody'];custody=[]
    for mode in cu.custody_mode.drop_duplicates():
        for lev in [1.,1.25]:
            g=cu[cu.custody_mode.eq(mode)&cu.leverage.eq(lev)];parts=[select_one(g,strategy='factor',policy=p) for p in ['absolute_decoupled','hybrid20']]+[select_one(g,strategy=s) for s in ['core','dimensional']]
            custody.append([cell(mode,dataset='custody',row=int(parts[0].name),field='custody_mode'),cell(lev,'ratio',dataset='custody',row=int(parts[0].name),field='leverage')]+[cell(r.cagr,'pct',dataset='custody',row=int(r.name),field='cagr') for r in parts])
    tables['backtest_22']=dict(headers=['Custody scenario','Exposure','Primary CAGR','Capped-relative CAGR','Core CAGR','Dimensional CAGR'],rows=custody,datasets=['custody'])
    sy=frames['synthetic'];sy=sy[sy.strategy.eq('factor_absolute')&sy.total_borrow_rate.eq(.06)]
    if len(sy)!=16:raise ValueError('sixteen selected artificial primary controls required')
    tables['backtest_23']=data_table(sy,'synthetic',[('regime','Artificial regime','text'),('leverage','Exposure','ratio'),('ending_equity_usd','Equity, USD m','million')]+result_cols[:3])
    annual=pd.concat([frames['annual_core'],frames['annual_factors'],frames['annual_dimensional']],keys=['annual_core','annual_factors','annual_dimensional'])
    rows=[]
    columns=[('fund','Fund','text'),('snapshot_date','Valuation date','text'),('holdings','Security lines','int'),('equity_weight','Equity / NAV','pct'),('top10_security_line_weight','Top ten lines / NAV','pct'),('difference_000_usd','Extracted − published, USD000','usd')]
    for (key,index),row in annual.iterrows():rows.append([cell(row[f],kind,dataset=key,row=int(index),field=f) for f,l,kind in columns])
    tables['backtest_24']=dict(headers=[l for f,l,k in columns],rows=rows,datasets=['annual_core','annual_factors','annual_dimensional'])
    tables['backtest_25']=data_table(frames['products'],'products',[('strategy','Short-overlap investment','text'),('cumulative_return','Cumulative return','pct'),('annualised_volatility','Volatility','pct'),('maximum_drawdown','Drawdown','pct')])
    identity={e['id']:e for e in registry['sources']}
    tables['backtest_26']=manual(['Investment','Identifier','Source qualification'],[[s.title(),identity[s]['identity'],identity[s]['publisher']] for s in ['core','momentum','quality','value']]+[
        ['Dimensional','IE00B2PC0153 (author-confirmed)','DIMGCEA ID Equity; ISIN not embedded in supplied workbook']])
    fee=baseline['fee_schedule']
    tables['backtest_27']=manual(['Baseline parameter','Selected value','Interpretation'],[
        ['Committed opening equity',f"USD {baseline['initial_equity_usd']:,.0f}",'One opening cost charge per independently restarted run'],
        ['Target exposure',str(baseline['primary_leverage'])+'x','Separate leverage control; no lender-approved ceiling'],
        ['Leverage band','±'+str(baseline['leverage_band']),'Strict breach, execution at next common NAV'],
        ['Sleeve band',display(baseline['sleeve_band'],'pp'),'All four sleeves; weights against gross invested assets'],
        ['Credit markup',display(baseline['borrowing_margin_annual'],'pct'),'Above calendar-carried reference rate'],
        ['Reference day count','ACT/'+str(baseline['measurement']['reference_day_count']),'Previous NAV inclusive to current NAV exclusive'],
        ['Platform fee per traded leg',f"USD {fee['platform_fee_usd']:.2f}",'No charge for an untraded leg'],
        ['Investor-side duty',display(fee['stamp_duty_rate'],'pct'),'One-way model assumption'],
        ['Ordinary one-way spread',f"{fee['spread_rate']*10000:g} bp",'Fixed current-cost scenario, not historical execution'],
        ['USD per CHF',f"{fee['usd_per_chf']:.10f}",'Fixed research-endpoint conversion for commissions'],
        ['Administration fee / inflows in main model','Excluded','Companion business-layer models remain separate'],
        ['Embedded fund expenses','Already in accumulating NAV','No duplicate TER deduction'],
        ['Custody','Separate path sensitivity','Not silently added to baseline']])
    def evidence_map(ids):
        return manual(['Result family','Evidence / treatment'],[[key,f'[{key}](../evidence/{key}.csv)' if contract['resolved_datasets'][key]['path'].endswith('.csv') else f'[{key}](../evidence/{key}.json)'] for key in ids])
    tables['backtest_28']=evidence_map(['main','endpoints','allocations','hindsight','rolling','entries','long_correlations','short_correlations','bridge','funding','custody','synthetic'])
    tables['backtest_29']=evidence_map(['comparator_costs','annual_core','annual_factors','annual_dimensional','products','issuer','independent','joint_cost','funding_crossings','gap_cures'])
    tables['backtest_30']=manual(['Research contribution','Provided here','Separate work'],[
        ['Strategy / rationale','Allocation, rule and economic design','Team explanation and lecture connections'],
        ['Advantages / challenges','Historical return/risk and counter-evidence','Prospective evaluation and actual implementation'],
        ['Backtest / value creation','Equal-calendar comparisons and counterfactuals','No causal factor/manager-skill claim'],
        ['Capital inflows','Historical connection explained below','Coordinated companion business report pending'],
        ['Marketing','Qualified evidence and limitations','Marketing strategy and claims are separate'],
        ['Video / slides','Research inputs and sources','Narration, presentation and submission production'],
        ['Publication','Locally reproducible report evidence','Fresh installation and actual-release reconstruction']])
    tables['financing_crossings']=data_table(frames['funding_crossings'],'funding_crossings',[('policy','Rule','text'),('crossing_bps','Local markup, bp','bps'),('type','Residual classification','text'),('residual_cagr_difference','Residual CAGR gap','pp')])
    tables['gap_cures']=data_table(frames['gap_cures'],'gap_cures',[('maintenance_ltv','Boundary LTV','pct'),('gap_loss','Instantaneous loss','pct'),('post_gap_equity','Pre-cure equity, USD m','million'),('status','Cure state','text'),('cure_sale_usd','Sale, USD m','million'),('liquidation_cost_usd','Liquidation cost, USD','usd'),('post_cure_debt_usd','Post-cure debt, USD m','million')])
    joint=frames['joint_cost'];joint_rows=[]
    for policy,g in joint.groupby('policy',sort=False):
        joint_rows.append([cell(POLICIES[policy]),cell(len(g),'int',expression='selected row count',origins=[dict(dataset='joint_cost',selection=dict(policy=policy))]),cell(int(g.joint_pass.sum()),'int',expression='sum joint_pass',origins=[dict(dataset='joint_cost',field='joint_pass',selection=dict(policy=policy))]),cell(g.gap_pp.min(),'already_pp',expression='minimum gap_pp',origins=[dict(dataset='joint_cost',field='gap_pp',selection=dict(policy=policy))]),cell(g.gap_pp.max(),'already_pp',expression='maximum gap_pp',origins=[dict(dataset='joint_cost',field='gap_pp',selection=dict(policy=policy))])])
    tables['joint_cost']=dict(headers=['Rule','Selected cells','Joint passes','Minimum CAGR gap','Maximum CAGR gap'],rows=joint_rows,datasets=['joint_cost'])
    historical=frames['historical_interpretation'];historical=historical[historical.layer.eq('acquisition')&historical.flow_plan.eq('steady')]
    tables['historical_link']=data_table(historical,'historical_interpretation',[('policy','Rule','text'),('coupled_unit_twr_annual','Coupled unit TWR / year','pct'),('overlay_unit_twr_annual','Overlay unit TWR / year','pct'),('unit_twr_difference_pp','Coupled − overlay','already_pp')])
    return tables


def report_claims(frames,baseline,contract):
    claims={}
    def add(key,value,kind,origins,expression=None):claims[key]=cell(value,kind,origins=origins,expression=expression)
    m=frames['main'];primary={}
    for exposure in [1.,1.25]:
        r=select_one(m,period='full',strategy='factor',policy='absolute_decoupled',leverage=exposure);primary[exposure]=r
        core=select_one(m,period='full',strategy='core',leverage=exposure);dim=select_one(m,period='full',strategy='dimensional',leverage=exposure)
        if not (r.cagr>core.cagr and r.annualised_volatility<=core.annualised_volatility and r.maximum_drawdown>=core.maximum_drawdown
            and r.cagr>dim.cagr and r.annualised_volatility<=dim.annualised_volatility and r.maximum_drawdown>=dim.maximum_drawdown):
            raise ValueError('reviewed full-period joint ordering no longer supported')
        if not r.alpha_ci_low<=0<=r.alpha_ci_high:raise ValueError('reviewed alpha uncertainty statement no longer supported')
        prefix='unlevered' if exposure==1 else 'levered'
        for field,kind in [('cagr','pct'),('annualised_volatility','pct'),('maximum_drawdown','pct')]:add(prefix+'_'+field,r[field],kind,[dict(dataset='main',row=int(r.name),field=field)])
        for name,other in [('core',core),('dimensional',dim)]:add(prefix+'_gap_'+name,r.cagr-other.cagr,'pp',[dict(dataset='main',row=int(x.name),field='cagr') for x in [r,other]],'factor cagr minus comparator cagr')
    for key,value in [('capital',baseline['initial_equity_usd']),('gross',baseline['initial_equity_usd']*baseline['primary_leverage']),('debt',baseline['initial_equity_usd']*(baseline['primary_leverage']-1))]:add(key,value,'million',[dict(config='baseline',field='initial_equity_usd'),dict(config='baseline',field='primary_leverage')],'capital times exposure or exposure minus one')
    issuer=frames['issuer']
    if not issuer.compatible_with_rounding.eq(True).all():raise ValueError('issuer rounding compatibility statement no longer supported')
    add('issuer_count',len(issuer),'int',[dict(dataset='issuer')],'row count')
    add('issuer_max_gap',issuer.difference_percentage_points.abs().max(),'already_pp',[dict(dataset='issuer',field='difference_percentage_points')],'max absolute published/reconstructed central difference')
    annual=[frames[x] for x in ['annual_core','annual_factors','annual_dimensional']]
    add('annual_snapshots',sum(len(x) for x in annual),'int',[dict(dataset=x) for x in ['annual_core','annual_factors','annual_dimensional']],'sum source rows')
    add('holding_lines',sum(x.holdings.sum() for x in annual),'int',[dict(dataset=x,field='holdings') for x in ['annual_core','annual_factors','annual_dimensional']],'sum security-line counts')
    add('levels',int(primary[1.25].observations),'int',[dict(dataset='main',row=int(primary[1.25].name),field='observations')])
    add('intervals',int(primary[1.25].observations)-1,'int',[dict(dataset='main',row=int(primary[1.25].name),field='observations')],'levels minus one')
    gaps=frames['gap_cures']
    for key,status in [('cures','cured_at_assumed_next_NAV'),('insolvent','insolvent_before_cure')]:add(key,int(gaps.status.eq(status).sum()),'int',[dict(dataset='gap_cures',field='status',selection=dict(status=status))],'matching rows')
    return claims


def markdown_table(spec):
    safe=lambda text:str(text).replace('|','\\|').replace('\n',' ')
    text='| '+' | '.join(map(safe,spec['headers']))+' |\n| '+' | '.join(['---']*len(spec['headers']))+' |\n'
    for row in spec['rows']:
        if len(row)!=len(spec['headers']):raise ValueError('report table shape mismatch')
        text+='| '+' | '.join(safe(x['display']) for x in row)+' |\n'
    if spec['datasets']:
        text+='\n**Calculation evidence:** '+', '.join(f'[{key}](../evidence/{key}.csv)' for key in spec['datasets'])+'.\n'
    return text.rstrip()


def validate_links(text,report_dir,root):
    anchors=set(re.findall(r'<a id="([^"]+)"></a>',text));links=[]
    for target in LINK.findall(text):
        parsed=urlsplit(target)
        if parsed.scheme in ['http','https']:links.append(dict(target=target,kind='external retained citation'));continue
        if parsed.scheme or parsed.netloc:raise ValueError('unsupported report link')
        if not parsed.path:
            if parsed.fragment not in anchors:raise ValueError('unknown report anchor')
            links.append(dict(target=target,kind='anchor'));continue
        path=(report_dir/unquote(parsed.path)).resolve()
        if not path.is_relative_to(root.resolve()) or not path.is_file():raise ValueError('missing or escaping report evidence link')
        links.append(dict(target=target,kind='local',artifact=str(path.relative_to(root.resolve()))))
    return links


def render(template,tables,claims,disclosure):
    used={'table':[],'claim':[],'figure':[],'disclosure':[]}
    def sub(match):
        kind,key=match.groups();used[kind].append(key)
        if kind=='table':return markdown_table(tables[key])
        if kind=='claim':return claims[key]['display']
        if kind=='disclosure':return disclosure
        if key not in ['equity','drawdown']:raise ValueError('unknown figure')
        return f'![Historical {key} at matched target exposure](../figures/{key}.png)'
    text=TOKEN.sub(sub,template)
    if '{{' in text or '}}' in text:raise ValueError('unresolved backtest template token')
    if len(used['table'])!=len(set(used['table'])) or set(used['table'])!=set(tables):raise ValueError('every declared table must appear once')
    if used['disclosure']!=['author'] or set(used['figure'])!={'equity','drawdown'}:raise ValueError('visible disclosure and both historical figures required')
    return text,used


def plot_history(curves,baseline,directory):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    capital=baseline['initial_equity_usd'];dates=pd.to_datetime(curves.date)
    series=[('full_factor_absolute_decoupled_1.25','Factor: absolute / separate','#17676b'),
        ('full_factor_hybrid20_1.25','Factor: capped-relative','#b36a28'),('full_core_1.25','Core at 1.25x','#505865'),
        ('full_dimensional_1.25','Dimensional at 1.25x','#9a8a9e')]
    directory.mkdir();data=[]
    for kind in ['equity','drawdown']:
        fig,ax=plt.subplots(figsize=(9.2,4.8),layout='constrained')
        for key,label,color in series:
            values=curves[key];plotted=values/1e6 if kind=='equity' else (values/values.cummax().clip(lower=capital)-1)*100
            ax.plot(dates,plotted,label=label,color=color,linewidth=1.6)
            data.extend(dict(date=str(day.date()),figure=kind,series=key,value=float(value)) for day,value in zip(dates,plotted))
        ax.set_ylabel('Investor equity, USD million' if kind=='equity' else 'Drawdown from committed-capital high-water mark, %')
        ax.set_title('Matched historical target exposure: 1.25x',loc='left',fontsize=12,pad=12)
        ax.grid(axis='y',color='#dfe4e7',linewidth=.6);ax.spines[['top','right']].set_visible(False)
        ax.legend(frameon=False,fontsize=8,loc='upper left' if kind=='equity' else 'lower left')
        fig.savefig(directory/(kind+'.png'),dpi=160,metadata={'Software':'MSCI World Factor Strategy report'});plt.close(fig)
    pd.DataFrame(data).to_csv(directory/'figure_data.csv',index=False)
    return dict(figures=['equity','drawdown'],series=[x[0] for x in series],source='equity_curves',opening_cost_preserved=True,drawdown_high_water_floor=capital)


def run_backtest_report(root,contract_dir,output):
    root=Path(root).resolve();contract_dir=Path(contract_dir);output=Path(output)
    if output.exists():raise FileExistsError('choose a new backtest-report output directory')
    verify_run(contract_dir);contract=json.loads((contract_dir/'evidence_contract.json').read_text());verify_bindings(root,contract)
    baseline=json.loads((contract_dir/'config/backtest_absolute_decoupled_2026-10-05.json').read_text());registry=json.loads((contract_dir/'config/SOURCE_DOWNLOAD_REGISTER_2026-10-06.json').read_text());validate_source_register(registry)
    resource=Path(__file__).parent/'templates';template=(resource/'backtest_report_2026-10-06.md').read_bytes();review_bytes=(resource/'backtest_report_review_2026-10-06.json').read_bytes();review=json.loads(review_bytes)
    semantic=hashlib.sha256(json.dumps(baseline,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    if review['template_sha256']!=hashlib.sha256(template).hexdigest() or review['baseline_semantic_sha256']!=semantic:
        raise ValueError('backtest interpretation/template requires renewed review')
    output.mkdir(parents=True);(output/'config').mkdir();evidence=output/'evidence';evidence.mkdir();(output/'report').mkdir()
    for f in (contract_dir/'config').iterdir():shutil.copyfile(f,output/'config'/f.name)
    (output/'config/backtest_report_template.md').write_bytes(template);(output/'config/backtest_report_review.json').write_bytes(review_bytes)
    captured={str(f.relative_to(output)):sha256(f) for f in (output/'config').iterdir()}
    code=source_hashes();manifest=dict(schema_version=1,run_id=str(uuid.uuid4()),status='running',figures_included=True,
        started_at_utc=datetime.now(timezone.utc).isoformat(),code=code,configuration_snapshots=captured,artifacts={},
        source_contract_run_id=json.loads((contract_dir/'run_manifest.json').read_text())['run_id'],source_contract_manifest_sha256=sha256(contract_dir/'run_manifest.json'),
        scope='New version9 backtest discussion report from accepted evidence; original reports preserved. Companion coordinated inflow report not assembled here.')
    write_json(output/'run_manifest.json',manifest)
    try:
        shutil.copyfile(contract_dir/'evidence_contract.json',evidence/'report_evidence_contract.json');frames={};origins={}
        needed=['main','endpoints','allocations','hindsight','rolling','entries','long_correlations','short_correlations','comparator_costs','bridge','funding','custody','synthetic','annual_core','annual_factors','annual_dimensional','products','issuer','independent','joint_cost','funding_crossings','gap_cures','historical_interpretation']
        for key in needed:
            d=contract['resolved_datasets'][key];src=contained(root,d['project_path']);suffix=src.suffix;dest=evidence/(key+suffix);shutil.copyfile(src,dest)
            origins[key]=dict(**d,artifact=str(dest.relative_to(output)))
            if suffix=='.csv':frames[key]=pd.read_csv(dest,float_precision='round_trip')
        # Additional plot and interpretation inputs are admitted by the same selected sealed run.
        for key,run_name,relative in [('primary_history','core','results/full_factor_absolute_decoupled_1.25_history.csv'),('equity_curves','core','results/equity_curves.csv'),('synthetic_settings','expanded','config/backtest_synthetic_absolute_decoupled_2026-10-05.json'),('source_settings','core','config/backtest_sources.json'),('funding_gap_settings','funding_gap','config/backtest_funding_scan_gap_2026-10-06.json')]:
            run=contract['resolved_runs'][run_name];src=contained(root,run['path']+'/'+relative);m=json.loads((contained(root,run['path'])/'run_manifest.json').read_text());expected={**m['configuration_snapshots'],**m['artifacts']}[relative]
            if sha256(src)!=expected:raise ValueError('additional sealed evidence differs')
            dest=evidence/(key+src.suffix);shutil.copyfile(src,dest);origins[key]=dict(project_path=run['path']+'/'+relative,sha256=expected,artifact=str(dest.relative_to(output)))
        sy=json.loads((evidence/'synthetic_settings.json').read_text())
        if not any(x['id']=='factor_absolute' and x['policy']=='absolute_decoupled' for x in sy['strategies']):raise ValueError('artificial primary label has different semantics')
        if json.loads((evidence/'source_settings.json').read_text())['dimensional_isin']!='IE00B2PC0153':raise ValueError('reviewed author-confirmed share-class mapping differs')
        gap_settings=json.loads((evidence/'funding_gap_settings.json').read_text())
        if any(gap_settings[k]!=v for k,v in dict(scan_step_bps=10,refinement_iterations=25,approximate_zero_residual=1e-6,liquidation_extra_spread=.01).items()):
            raise ValueError('reviewed financing scan or liquidation friction differs')
        tables=result_tables(frames,baseline,registry,contract);claims=report_claims(frames,baseline,contract)
        coverage=json.loads((evidence/'independent.json').read_text())
        for key,field in [('independent_retained','retained_labels'),('independent_additional','additional_labels'),('independent_comparisons','outcome_comparisons')]:claims[key]=cell(coverage['counts'][field],'int',origins=[dict(dataset='independent',field='counts.'+field)])
        if coverage['all_comparisons_passed'] is not True:raise ValueError('independent audit statement unsupported')
        text,used=render(template.decode(),tables,claims,contract['disclosure'])
        write_json(evidence/'input_bindings.json',origins);write_json(output/'report/tables.json',tables);write_json(output/'report/claims.json',dict(claims=claims,used_claims=used['claim'],manual_context=review['manual_context'],scope=review['scope']))
        curves=pd.read_csv(evidence/'equity_curves.csv',float_precision='round_trip');figures=plot_history(curves,baseline,output/'figures');write_json(output/'figures/plot_definitions.json',figures)
        (output/'report/source_register.md').write_text(source_markdown(registry,contract['disclosure']))
        (output/'report/BACKTEST_REPORT_2026-10-06.md').write_text(text)
        write_json(output/'report/assembly_checks.json',dict(status='assembling'))
        links=validate_links(text,output/'report',output)
        write_json(output/'report/assembly_checks.json',dict(status='complete',tables=len(tables),mapped_original_backtest_locations=30,
            numerical_prose_claims=len(set(used['claim'])),claim_occurrences=len(used['claim']),figures=2,links=links,
            same_author_disclosure=True,scope='Selected numerical cells/prose, table presence, source seals and local links checked. Manually authored interpretation is not an expert review or new investment validation.'))
        (output/'README.md').write_text('# Backtest Report Working Package\n\n'
            '[New version9 backtest report](report/BACKTEST_REPORT_2026-10-06.md) · [Sources](report/source_register.md) · [Assembly checks](report/assembly_checks.json) · [Manifest](run_manifest.json)\n\n'
            'Absolute five-percentage-point sleeve bands with separate leverage, retained capped-relative comparison. Local research discussion draft; companion report integration and final release remain pending. Detailed provider-derived evidence is included locally and is not automatically public content.\n')
        verify_bindings(root,contract)
        if source_hashes()!=code or sha256(contract_dir/'run_manifest.json')!=manifest['source_contract_manifest_sha256']:
            raise RuntimeError('source/template or evidence contract changed during assembly')
        manifest['artifacts']={str(f.relative_to(output)):sha256(f) for f in sorted(output.rglob('*')) if f.is_file()
            and f!=output/'run_manifest.json' and f.relative_to(output).parts[0]!='config'}
        manifest.update(status='complete',finished_at_utc=datetime.now(timezone.utc).isoformat(),counts=dict(tables=len(tables),mapped_original_backtest_locations=30,
            numerical_prose_claims=len(set(used['claim'])),claim_occurrences=len(used['claim']),figures=2,local_links=sum(x['kind']=='local' for x in links)))
        write_json(output/'run_manifest.json',manifest);verify_run(output)
    except Exception as error:
        manifest.update(status='failed',failure=dict(type=type(error).__name__,message=str(error)));write_json(output/'run_manifest.json',manifest);raise
    return manifest


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--project-root',type=Path,default=Path.cwd())
    p.add_argument('--contract',type=Path,default=Path('outputs/coordinated_report_contract_v2_2026-10-06'));p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();m=run_backtest_report(a.project_root,a.contract,a.output);print(json.dumps(dict(run_id=m['run_id'],counts=m['counts']),indent=2))


if __name__=='__main__':main()
