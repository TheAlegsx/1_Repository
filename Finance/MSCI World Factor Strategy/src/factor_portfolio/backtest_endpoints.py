"""Continuing endpoint sensitivity with explicit main and legacy risk conventions."""
from __future__ import annotations

import argparse
from datetime import date,datetime,timezone
import json
import math
from pathlib import Path
import uuid

import numpy as np
import pandas as pd

from .backtest_workflow import run_backtest_study,validate_config
from .benchmark import investor_equity_returns
from .inflow_workflow import sha256,source_hashes,verify_run,write_json

CONVENTIONS=['committed_capital_first_interval']


def validate_settings(settings,baseline):
    if settings['schema_version']!=1:raise ValueError('unsupported endpoint schema')
    policies=settings['factor_policies'];exposures=settings['leverage_levels']
    if (len(set(policies))!=len(policies) or not policies or baseline['primary_policy'] not in policies
        or settings['legacy_policy'] not in policies or any(p not in baseline['policies'] for p in policies)):
        raise ValueError('endpoint policies must include primary and legacy selections')
    if not exposures or len(set(exposures))!=len(exposures) or any(x not in baseline['leverage_levels'] for x in exposures):
        raise ValueError('endpoint exposures must match baseline')
    if settings['risk_conventions']!=CONVENTIONS or settings['primary_risk_convention']!=CONVENTIONS[0]:
        raise ValueError('existing committed-capital first-interval risk convention required')
    if type(settings['minimum_levels']) is not int or settings['minimum_levels']<3:
        raise ValueError('endpoint risk metrics need at least three levels')
    cuts=[date.fromisoformat(x) for x in settings['requested_endpoints']]
    start,end=(date.fromisoformat(baseline['periods']['full'][k]) for k in ['start','end'])
    if not cuts or cuts!=sorted(set(cuts)) or any(x<=start or x>end for x in cuts):
        raise ValueError('unique ordered cutoffs within full period required')


def endpoint_metrics(equity,dates,capital,convention):
    equity=np.asarray(equity,float);dates=pd.DatetimeIndex(dates)
    if (len(equity)!=len(dates) or len(equity)<3 or not dates.is_monotonic_increasing or dates.has_duplicates
        or dates.hasnans or not np.isfinite(equity).all() or (equity<=0).any() or not math.isfinite(capital) or capital<=0):
        raise ValueError('positive finite common endpoint history required')
    elapsed=(dates[-1]-dates[0]).days
    if elapsed<=0:raise ValueError('positive calendar horizon required')
    if convention!=CONVENTIONS[0]:raise ValueError('unknown endpoint risk convention')
    returns=investor_equity_returns(pd.Series(equity,index=dates),initial_committed_capital_usd=capital).to_numpy()
    peak=np.maximum.accumulate(np.r_[capital,equity])[1:]
    return dict(cagr=float((equity[-1]/capital)**(365.2425/elapsed)-1),
        volatility=float(returns.std(ddof=1)*np.sqrt(252)),drawdown=float((equity/peak-1).min()),
        ending_equity_usd=float(equity[-1]),observations=len(equity),return_observations=len(returns))


def latest_crossing(factor,core,dates):
    factor,core=np.asarray(factor,float),np.asarray(core,float);dates=pd.DatetimeIndex(dates)
    if (len(factor)!=len(core) or len(factor)!=len(dates) or not len(factor)
        or not np.isfinite(factor).all() or not np.isfinite(core).all() or (factor<=0).any() or (core<=0).any()
        or dates.hasnans or dates.has_duplicates or not dates.is_monotonic_increasing):
        raise ValueError('positive aligned crossing paths required')
    relative=factor/core-1;negative=np.flatnonzero(relative<=0)
    if not len(negative):
        last=None;following=str(dates[0].date());previous=0;status='positive_at_every_observation'
    else:
        k=int(negative[-1]);last=str(dates[k].date());previous=int((relative[:k]>0).sum())
        following=str(dates[k+1].date()) if k<len(dates)-1 else None
        status='terminal_positive_run' if following else 'terminal_not_positive'
    return dict(status=status,last_nonpositive_date=last,next_positive_date=following,
        previous_positive_observations=previous,all_observations=len(dates))


def build_endpoints(curves,baseline,settings):
    validate_settings(settings,baseline)
    curves=curves.copy();dates=pd.DatetimeIndex(pd.to_datetime(curves.pop('date')))
    if dates.hasnans or dates.has_duplicates or not dates.is_monotonic_increasing:raise ValueError('unique ordered common dates required')
    if str(dates[0].date())!=baseline['periods']['full']['start'] or str(dates[-1].date())!=baseline['periods']['full']['end']:
        raise ValueError('complete declared full-period paths required')
    policies=settings['factor_policies'];exposures=settings['leverage_levels'];capital=baseline['initial_equity_usd']
    paths={};mapping=[];endpoints=[];monthly=[];crossings=[]
    for lev in exposures:
        for strategy,policy in [('factor',p) for p in policies]+[('core','leverage_managed'),('dimensional','leverage_managed')]:
            key=f'full_{strategy}_{policy}_{lev:.2f}' if strategy=='factor' else f'full_{strategy}_{lev:.2f}'
            value=curves[key].to_numpy(float)
            if not np.isfinite(value).all() or (value<=0).any():raise ValueError('complete positive curves required')
            paths[strategy,policy,lev]=value
    for cutoff in settings['requested_endpoints']:
        n=int(dates.searchsorted(pd.Timestamp(cutoff),side='right'))
        if n<settings['minimum_levels']:raise ValueError('cutoff lacks required levels')
        actual=str(dates[n-1].date());mapping.append(dict(requested_end=cutoff,actual_end=actual,levels=n,days_before_requested=(pd.Timestamp(cutoff)-dates[n-1]).days))
        for (strategy,policy,lev),values in paths.items():
            for convention in CONVENTIONS:
                endpoints.append(dict(requested_end=cutoff,end=actual,strategy=strategy,policy=policy,leverage=lev,risk_convention=convention,
                    **endpoint_metrics(values[:n],dates[:n],capital,convention)))
    last_monthly=pd.Series(np.arange(len(dates)),index=dates).groupby(dates.to_period('M')).last().to_numpy()
    for policy in policies:
        for lev in exposures:
            factor=paths['factor',policy,lev];core=paths['core','leverage_managed',lev]
            crossings.append(dict(policy=policy,leverage=lev,**latest_crossing(factor,core,dates)))
            for k in last_monthly:
                if k+1<settings['minimum_levels']:continue
                for convention in CONVENTIONS:
                    a=endpoint_metrics(factor[:k+1],dates[:k+1],capital,convention);b=endpoint_metrics(core[:k+1],dates[:k+1],capital,convention)
                    monthly.append(dict(date=str(dates[k].date()),policy=policy,leverage=lev,risk_convention=convention,
                        cagr_gap_pp=100*(a['cagr']-b['cagr']),vol_gap_pp=100*(a['volatility']-b['volatility']),drawdown_gap_pp=100*(a['drawdown']-b['drawdown']),
                        joint_pass=bool(a['cagr']>b['cagr'] and a['volatility']<=b['volatility'] and a['drawdown']>=b['drawdown'])))
    monthly=pd.DataFrame(monthly);summary=[]
    for (policy,lev,convention),g in monthly.groupby(['policy','leverage','risk_convention'],sort=False):
        summary.append(dict(policy=policy,leverage=lev,risk_convention=convention,endpoints=len(g),positive_cagr=int(g.cagr_gap_pp.gt(0).sum()),joint_pass=int(g.joint_pass.sum())))
    return dict(endpoints=pd.DataFrame(endpoints),monthly=monthly,crossings=crossings,summary=summary,mapping=mapping,
        definitions=dict(wealth_base='Original committed capital and same initial date at every cutoff; no restart or repeated entry cost.',
            investor_risk='Existing main/reference convention: first subsequent equity divided by committed capital minus one, then subsequent interval returns. No extra opening-return observation.',
            crossing='Strict factor/Core wealth ratio >1; equality is nonpositive. Latest terminal positive run, not first-ever outperformance.',
            monthly='Last common observation in each represented month; final August 2026 is a partial month.',
            limitations=['Overlapping retrospective endpoints, not independent observations or future probabilities.',
                'Policy selection is ex post; no model parameters tuned.',
                'No joint funding/spread grid, alpha inference or final report produced here.']))


def run_endpoints(raw_root,baseline_path,sources_path,settings_path,output):
    output=Path(output)
    if output.exists():raise FileExistsError('choose a new endpoint output directory')
    paths=[baseline_path,sources_path,settings_path];captured={Path(p).name:Path(p).read_bytes() for p in paths}
    if len(captured)!=3:raise ValueError('distinct configuration filenames required')
    baseline=json.loads(captured[Path(baseline_path).name]);settings=json.loads(captured[Path(settings_path).name])
    validate_config(baseline);validate_settings(settings,baseline)
    output.mkdir(parents=True);(output/'config').mkdir()
    for name,data in captured.items():(output/'config'/name).write_bytes(data)
    code=source_hashes();manifest=dict(schema_version=1,run_id=str(uuid.uuid4()),status='running',figures_included=False,
        started_at_utc=datetime.now(timezone.utc).isoformat(),code=code,
        scope='Fresh original-input core and continuing endpoints/month-ends/crossings under unchanged committed-capital investor-risk convention. No joint-cost grid or final reports.',
        configuration_snapshots={f'config/{name}':sha256(output/'config'/name) for name in captured},artifacts={})
    write_json(output/'run_manifest.json',manifest)
    try:
        core=run_backtest_study(raw_root,output/'config'/Path(baseline_path).name,output/'config'/Path(sources_path).name,output/'core')
        curves=pd.read_csv(output/'core/results/equity_curves.csv',float_precision='round_trip')
        result=build_endpoints(curves,baseline,settings)
        result['endpoints'].to_csv(output/'endpoint_metrics.csv',index=False,lineterminator='\n')
        result['monthly'].to_csv(output/'monthly_endpoints.csv',index=False,lineterminator='\n')
        legacy=settings['legacy_policy'];e=result['endpoints'];m=result['monthly']
        # Retain the original columns/order for explicit comparison after calculation.
        retained=e[(e.strategy!='factor')|(e.policy==legacy)]
        retained.to_csv(output/'legacy_endpoint_metrics.csv',index=False,lineterminator='\n')
        m[m.policy==legacy][['date','leverage','cagr_gap_pp','vol_gap_pp','drawdown_gap_pp','joint_pass']].to_csv(output/'legacy_monthly_endpoints.csv',index=False,lineterminator='\n')
        write_json(output/'endpoint_checks.json',dict(crossings=result['crossings'],monthly_endpoint_summary=result['summary'],date_mapping=result['mapping'],definitions=result['definitions']))
        (output/'README.md').write_text('# Continuing Endpoint Diagnostics\n\nSame original start and committed capital; endpoint truncation does not restart accounts. '
            'Existing main and reference risk convention is retained: entry costs fold into the first subsequent return without another opening observation. Overlapping descriptive endpoints are not future probabilities.\n\n'
            '[Metrics](endpoint_metrics.csv) · [Monthly comparisons](monthly_endpoints.csv) · [Crossings and definitions](endpoint_checks.json) · '
            '[Legacy endpoint view](legacy_endpoint_metrics.csv) · [Legacy monthly view](legacy_monthly_endpoints.csv) · [Fresh core](core/README.md) · [Manifest](run_manifest.json)\n')
        if source_hashes()!=code:raise RuntimeError('source changed during endpoint calculation')
        manifest['artifacts']={str(p.relative_to(output)):sha256(p) for p in sorted(output.rglob('*')) if p.is_file() and p!=output/'run_manifest.json' and p.relative_to(output).parts[0]!='config'}
        manifest.update(status='complete',finished_at_utc=datetime.now(timezone.utc).isoformat(),raw_sources=core['raw_sources'],
            counts=dict(endpoint_rows=len(e),monthly_comparisons=len(m),crossings=len(result['crossings']),core_cases=core['counts']['policy_cases']))
        write_json(output/'run_manifest.json',manifest);verify_run(output)
    except Exception as error:
        manifest.update(status='failed',failure=dict(type=type(error).__name__,message=str(error)));write_json(output/'run_manifest.json',manifest);raise
    return manifest


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--raw-root',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    for key,name in [('baseline','backtest_absolute_decoupled_2026-10-05.json'),('sources','backtest_sources.json'),('settings','backtest_endpoints_absolute_decoupled_v2_2026-10-05.json')]:p.add_argument('--'+key,type=Path,default=Path('config')/name)
    a=p.parse_args();m=run_endpoints(a.raw_root,a.baseline,a.sources,a.settings,a.output);print(json.dumps(dict(run_id=m['run_id'],status=m['status'],counts=m['counts']),indent=2))


if __name__=='__main__':main()
