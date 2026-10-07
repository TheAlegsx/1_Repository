"""Independent funding-account and bracketed crossing comparison for both policies."""
from __future__ import annotations

import argparse
from datetime import datetime,timezone
import json
import math
from pathlib import Path
import uuid

import pandas as pd

from .backtest_workflow import run_backtest_study,validate_config
from .backtest_funding import validate_settings as validate_funding
from .backtest_independent_core import comparison_rows,validate_settings as validate_comparison
from .independent_scalar import calculate
from .inflow_workflow import sha256,source_hashes,verify_run,write_json

NAMES=['backtest_absolute_decoupled_2026-10-05.json','backtest_baseline.json','backtest_sources.json',
       'backtest_funding_absolute_decoupled_2026-10-05.json','backtest_funding.json','independent_funding_2026-10-05.json']


def validate_pair(primary,legacy,primary_funding,legacy_funding,settings):
    validate_config(primary);validate_config(legacy);validate_comparison(settings)
    validate_funding(primary_funding,primary);validate_funding(legacy_funding,legacy)
    if settings['branches']!=['legacy','primary'] or primary_funding['factor_policy']!='absolute_decoupled' or legacy_funding['factor_policy']!='hybrid20':
        raise ValueError('distinct retained and primary funding branches required')
    for field in ['initial_equity_usd','target_weights','leverage_levels','policies','borrowing_margin_annual','sleeve_band','leverage_band','fee_schedule','periods','measurement','reconciliation_tolerances']:
        if primary[field]!=legacy[field]:raise ValueError('funding branch economics differ: '+field)
    for field in ['periods','margin_bps','target_leverage','threshold','reconciliation_tolerances']:
        if primary_funding[field]!=legacy_funding[field]:raise ValueError('funding comparison grids differ: '+field)


def independent_crossing(difference,bracket,iterations):
    """Separate fixed-iteration bisection; evaluate only independent account returns."""
    if len(bracket)!=2 or any(not math.isfinite(x) for x in bracket) or not 0<=bracket[0]<bracket[1] or type(iterations) is not int or not 1<=iterations<=60:
        raise ValueError('invalid independent crossing specification')
    trace=[]
    def evaluate(bp):
        value=float(difference(bp))
        if not math.isfinite(value):raise ValueError('finite independent crossing differences required')
        trace.append(dict(margin_bps=bp,cagr_difference=value));return value
    low,high=map(float,bracket);left=evaluate(low);right=evaluate(high);estimate=residual=None;status='not_bracketed'
    if left==0 or right==0:
        estimate,residual=(low,left) if left==0 else (high,right);status='endpoint_zero'
    elif (left<0<right) or (right<0<left):
        for _ in range(iterations):
            middle=(low+high)/2;value=evaluate(middle)
            if (value>0 and left>0) or (value<0 and left<0):low=middle;left=value
            else:high=middle;right=value
        estimate=(low+high)/2;residual=evaluate(estimate);status='bracketed_estimate'
    return dict(status=status,margin_bps=estimate,difference_at_threshold=residual,final_bracket_bps=[low,high],evaluations=trace,
        interpretation='Bounded local estimate, not uniqueness, continuity, global monotonicity or actual lending terms.')


def reconcile_funding(levels,reference,production,baseline,funding,settings,branch):
    if production.duplicated(['period','strategy','margin_bps']).any():raise ValueError('unique funding cases required')
    expected={(p,s,m) for p in funding['periods'] for s in ['factor','core','dimensional'] for m in funding['margin_bps']}
    actual=set(zip(production.period,production.strategy,production.margin_bps))
    if actual!=expected:raise ValueError('complete declared funding case grid required')
    sleeves=list(baseline['target_weights']);weights=list(baseline['target_weights'].values());metrics=[];histories=[];events=[];checks=[]
    for row in production.to_dict('records'):
        boundaries=baseline['periods'][row['period']]
        if row['start']!=boundaries['start'] or row['end']!=boundaries['end']:raise ValueError('funding case differs from configured period')
        factor=row['strategy']=='factor';policy=funding['factor_policy'] if factor else 'no_sleeve'
        subset=levels.loc[row['start']:row['end'],sleeves if factor else [row['strategy']]]
        result,h,e=calculate(subset,reference,weights if factor else [1.],funding['target_leverage'],policy,
            initial_equity_usd=baseline['initial_equity_usd'],fee_parameters=baseline['fee_schedule'],margin=row['margin_bps']/10000,
            sleeve_band=baseline['sleeve_band'],leverage_band=baseline['leverage_band'])
        if len(h)!=row['observations'] or str(h.date.iloc[0].date())!=row['start'] or str(h.date.iloc[-1].date())!=row['end']:
            raise ValueError('independent funding calendar differs')
        label=f"{branch}__{row['period']}__{row['strategy']}__{row['margin_bps']:g}"
        metrics.append(dict(case_id=label,branch=branch,period=row['period'],strategy=row['strategy'],margin_bps=row['margin_bps'],**result))
        checks.extend(comparison_rows(row,result,baseline,settings,label));histories.append(h.assign(case_id=label));events.append(e.assign(case_id=label))
    full=baseline['periods']['full'];full_levels=levels.loc[full['start']:full['end'],sleeves]
    def factor_cagr(exposure,margin):
        result,_,_=calculate(full_levels,reference,weights,exposure,funding['factor_policy'],initial_equity_usd=baseline['initial_equity_usd'],fee_parameters=baseline['fee_schedule'],
            margin=margin,sleeve_band=baseline['sleeve_band'],leverage_band=baseline['leverage_band'])
        return result['cagr']
    target=factor_cagr(1.,baseline['borrowing_margin_annual'])
    search=independent_crossing(lambda bp:factor_cagr(funding['target_leverage'],bp/10000)-target,funding['threshold']['bracket_bps'],funding['threshold']['iterations'])
    search['unlevered_factor_cagr']=target
    return dict(metrics=pd.DataFrame(metrics),histories=pd.concat(histories,ignore_index=True),events=pd.concat(events,ignore_index=True),checks=pd.DataFrame(checks),search=search)


def compare_crossing(independent,production,limits):
    a=independent['margin_bps'];b=production['margin_bps']
    if a is None or b is None:
        passed=a is None and b is None;gap=None;residual_gap=None
    else:
        gap=abs(a-b);residual_gap=abs(independent['difference_at_threshold']-production['difference_at_threshold'])
        passed=gap<=limits['threshold_margin_bps_atol'] and residual_gap<=limits['threshold_cagr_difference_atol']
    return dict(passed=passed,independent_margin_bps=a,production_margin_bps=b,margin_difference_bps=gap,cagr_residual_difference=residual_gap,
        fixed_tolerances=limits,scope='Same initial bracket/iteration rule, separate account and search implementations; no global/root uniqueness guarantee.')


def run_independent_funding(raw_root,config_dir,output):
    output=Path(output);config_dir=Path(config_dir)
    if output.exists():raise FileExistsError('choose a new independent funding output directory')
    captured={n:(config_dir/n).read_bytes() for n in NAMES};objects={n:json.loads(data) for n,data in captured.items()}
    primary,legacy=objects[NAMES[0]],objects[NAMES[1]];pf,lf=objects[NAMES[3]],objects[NAMES[4]];settings=objects[NAMES[5]]
    validate_pair(primary,legacy,pf,lf,settings)
    output.mkdir(parents=True);(output/'config').mkdir()
    for name,data in captured.items():(output/'config'/name).write_bytes(data)
    code=source_hashes();manifest=dict(schema_version=1,run_id=str(uuid.uuid4()),status='running',figures_included=False,
        started_at_utc=datetime.now(timezone.utc).isoformat(),code=code,
        scope='Independent old sixty-case funding family plus sixty primary labels and two local crossing searches. Shared admitted inputs; partial original 625-run coverage only.',
        configuration_snapshots={f'config/{name}':sha256(output/'config'/name) for name in captured},artifacts={})
    write_json(output/'run_manifest.json',manifest)
    try:
        outputs={};searches={};crossings={};raw=None
        for branch,baseline,baseline_name,funding,funding_name in [('legacy',legacy,NAMES[1],lf,NAMES[4]),('primary',primary,NAMES[0],pf,NAMES[3])]:
            folder=output/branch
            run=run_backtest_study(raw_root,output/'config'/baseline_name,output/'config'/NAMES[2],folder,funding_config_path=output/'config'/funding_name)
            if raw is not None and raw!=run['raw_sources']:raise ValueError('funding branch raw inputs differ')
            raw=run['raw_sources']
            levels=pd.read_csv(folder/'inputs/common_nav_usd.csv',index_col=0,parse_dates=True)
            reference=pd.read_csv(folder/'inputs/canonical/daily_borrow_rates_usd.csv',index_col=0,parse_dates=True).reference_rate_annual
            table=pd.read_csv(folder/'results/funding_metrics.csv',float_precision='round_trip')
            if len(table)!=60:raise ValueError('complete declared sixty-case funding branch required')
            result=reconcile_funding(levels,reference,table,baseline,funding,settings,branch);outputs[branch]=result;searches[branch]=result['search']
            expected=json.loads((folder/'results/financing_threshold.json').read_text());crossings[branch]=compare_crossing(result['search'],expected,funding['reconciliation_tolerances'])
        for name in ['inputs/common_nav_usd.csv','inputs/canonical/daily_borrow_rates_usd.csv']:
            if (output/'legacy'/name).read_bytes()!=(output/'primary'/name).read_bytes():raise ValueError('funding branch source calendars differ')
        for key,name in [('metrics','independent_funding_metrics.csv'),('histories','independent_funding_histories.csv'),('events','independent_funding_events.csv'),('checks','independent_funding_comparisons.csv')]:
            pd.concat([outputs[b][key] for b in settings['branches']],ignore_index=True).to_csv(output/name,index=False,lineterminator='\n')
        write_json(output/'independent_searches.json',searches);write_json(output/'crossing_comparisons.json',crossings)
        passed=all(outputs[b]['checks'].passed.all() and crossings[b]['passed'] for b in settings['branches'])
        write_json(output/'funding_definitions.json',dict(settings=settings,all_comparisons_passed=bool(passed),baseline_tolerances=primary['reconciliation_tolerances'],
            scope='120 branch labels; Core/Dimensional repeat between branches. Only sixty legacy cases add to original-audit coverage.',
            limitations=['Same admitted sources/model terms; not independent daily data or approved bank terms.',
                'Threshold is sample-dependent bounded local search, not a global optimum or generally attainable funding limit.',
                'Eight independent outcomes; alpha/HAC and full original 625 cases remain separate coverage.']))
        if not passed:raise ValueError('independent funding deviates beyond unchanged tolerances; inspect retained comparisons')
        (output/'README.md').write_text('# Independent Funding Accounts\n\nSixty retained and sixty primary branch labels with eight outcomes each, plus independently calculated local financing crossings. '
            'Benchmark labels repeat between branches; only sixty cases add to the original independent audit scope.\n\n'
            '[Outcomes](independent_funding_metrics.csv) · [960 comparisons](independent_funding_comparisons.csv) · [Accounts](independent_funding_histories.csv) · '
            '[Events](independent_funding_events.csv) · [Scalar searches](independent_searches.json) · [Crossing checks](crossing_comparisons.json) · [Scope](funding_definitions.json) · [Manifest](run_manifest.json)\n')
        if source_hashes()!=code:raise RuntimeError('source changed during independent funding')
        manifest['artifacts']={str(p.relative_to(output)):sha256(p) for p in sorted(output.rglob('*')) if p.is_file() and p!=output/'run_manifest.json' and p.relative_to(output).parts[0]!='config'}
        manifest.update(status='complete',finished_at_utc=datetime.now(timezone.utc).isoformat(),raw_sources=raw,
            counts=dict(independent_cases=120,outcome_comparisons=960,scalar_history_rows=sum(len(x['histories']) for x in outputs.values()),
                independent_search_evaluations=sum(len(s['evaluations']) for s in searches.values()),all_comparisons_passed=True,old_audit_cases_added=60))
        write_json(output/'run_manifest.json',manifest);verify_run(output)
    except Exception as error:
        manifest.update(status='failed',failure=dict(type=type(error).__name__,message=str(error)));write_json(output/'run_manifest.json',manifest);raise
    return manifest


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--raw-root',type=Path,required=True);p.add_argument('--config-dir',type=Path,default=Path('config'));p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    m=run_independent_funding(a.raw_root,a.config_dir,a.output);print(json.dumps(dict(run_id=m['run_id'],status=m['status'],counts=m['counts']),indent=2))


if __name__=='__main__':main()
