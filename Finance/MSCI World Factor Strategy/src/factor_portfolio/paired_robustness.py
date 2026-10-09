"""Frozen paired specification matrix and conditional return-pair bootstrap.

No financial engine is modified. Nonzero-fee cases use the existing no-client
fund ledger with the protocol's terminal accrual convention.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import uuid

import numpy as np
import pandas as pd

from .config import SwissquoteStandardFeeSchedule
from .historical import simulate
from .coupled_inflow_accounting import simulate_coupled
from .benchmark import investor_equity_returns
from .inflow_workflow import verify_run, write_json, sha256
from .security_io import require_runtime, require_installation

PROTOCOL_SHA = '251169af59938f7040fa18a6e5b27d7e01d5ab886a015d317f24811ed6b84955'


def validate_protocol(project, path):
    project, path = Path(project), Path(path)
    if sha256(path) != PROTOCOL_SHA:
        raise ValueError('frozen robustness protocol differs; a dated amendment is required')
    protocol = json.loads(path.read_text())
    for relative, expected in protocol['baseline_pins'].items():
        selected = project / relative
        if relative == 'config/reproduction_reference_2026-10-06.json' and sha256(selected) != expected:
            selected = project / 'config/robustness_baseline_reference_2026-10-09.json'
        if not selected.is_file() or sha256(selected) != expected:
            raise ValueError('protected baseline source differs: '+relative)
    if len(protocol['cases']) != 19 or sum(c['available'] for c in protocol['cases']) != 14:
        raise ValueError('frozen case inventory differs')
    return protocol


def fee_calendar(dates, annual_fee, year_days=365.2425):
    """Original monthly payments plus one explicitly specified terminal accrual."""
    dates = pd.DatetimeIndex(dates)
    if len(dates) < 2 or not dates.is_unique or not dates.is_monotonic_increasing:
        raise ValueError('ordered common NAV dates required')
    if not math.isfinite(annual_fee) or annual_fee < 0:
        raise ValueError('nonnegative annual fund fee required')
    start, end = dates[0], dates[-1]
    rows=[]; month=1; prior=start
    while True:
        nominal=start+pd.DateOffset(months=month)
        position=dates.searchsorted(nominal)
        if position>=len(dates):break
        actual=dates[position]
        if actual<=prior:raise ValueError('anniversary payments require distinct common NAVs')
        rows.append(dict(event_date=actual,month=month,project_year=(month-1)//12+1,
            scheduled_subscription_usd=0.,monthly_external_unit_redemption_fraction=0.,
            proposed_fund_fee_fraction=annual_fee/12,payment_kind='regular_month',
            nominal_date=str(nominal.date()),stub_calendar_days=0))
        prior=actual;month+=1
    if end>prior:
        days=(end-prior).days
        rows.append(dict(event_date=end,month=month,project_year=(month-1)//12+1,
            scheduled_subscription_usd=0.,monthly_external_unit_redemption_fraction=0.,
            proposed_fund_fee_fraction=annual_fee*days/year_days,payment_kind='terminal_stub',
            nominal_date=None,stub_calendar_days=days))
    return pd.DataFrame(rows)


def run_account(returns, reference, baseline, case, strategy):
    cols=list(baseline['target_weights']) if strategy=='factor' else ['core']
    weights=list(baseline['target_weights'].values()) if strategy=='factor' else [1.]
    policy='absolute_decoupled' if strategy=='factor' else 'no_sleeve'
    kwargs=dict(leverage=1.25,policy=policy,margin=case['margin_bps']/10000,
        sleeve_band=case['sleeve_band'],leverage_band=case['leverage_band'],
        initial_equity_usd=baseline['initial_equity_usd'],
        fee_schedule=SwissquoteStandardFeeSchedule(**baseline['fee_schedule']))
    ret=returns[cols].copy();ret.iloc[0]=0.
    plan=fee_calendar(ret.index,case['fund_fee_bps']/10000,
        baseline['measurement']['cagr_calendar_year_days'])
    result=simulate_coupled(ret,reference,weights,flows=plan,initial_unit_nav=100.,**kwargs)
    if result.status!='complete' or len(result.history)!=len(ret):
        raise ValueError('complete paired account required')
    if case['fund_fee_bps']==0:
        original=simulate(ret,reference,weights,**kwargs)
        pd.testing.assert_frame_equal(result.history[original.history.columns],original.history,check_exact=True)
        pd.testing.assert_frame_equal(result.events,original.events,check_exact=True)
    return result,plan


def outcome(run, case, strategy, requested_end, baseline):
    h=run.history;capital=run.initial_equity_usd
    years=(h.index[-1]-h.index[0]).days/baseline['measurement']['cagr_calendar_year_days']
    events=run.events.iloc[1:];reasons=events.reason
    allowed={'sleeve','leverage','sleeve+leverage'}
    if not set(reasons).issubset(allowed):raise ValueError('unexpected transaction in no-client study')
    return dict(case_id=case['id'],dimension=case['dimension'],strategy=strategy,
        requested_end=requested_end,start=str(h.index[0].date()),end=str(h.index[-1].date()),
        observations=len(h),elapsed_years=years,initial_equity_usd=capital,
        ending_equity_usd=float(h.equity_usd.iloc[-1]),cagr=float((h.equity_usd.iloc[-1]/capital)**(1/years)-1),
        post_entry_events=len(events),sleeve_only_events=int(reasons.eq('sleeve').sum()),
        leverage_only_events=int(reasons.eq('leverage').sum()),joint_events=int(reasons.eq('sleeve+leverage').sum()),
        transaction_cost_usd=float(h.cumulative_transaction_cost_usd.iloc[-1]),
        financing_cost_usd=float(h.cumulative_financing_cost_usd.iloc[-1]),
        fund_fee_usd=float(h.cumulative_fund_fee_usd.iloc[-1]),
        mean_leverage=float(h.leverage.mean()),minimum_leverage=float(h.leverage.min()),
        maximum_leverage=float(h.leverage.max()),maximum_pretrade_leverage=float(h.pretrade_leverage.max()),
        margin_bps=case['margin_bps'],fund_fee_bps=case['fund_fee_bps'],
        leverage_band=case['leverage_band'],sleeve_band=case['sleeve_band'] if strategy=='factor' else None,
        execution_nav_delay=1,case_sha256=hashlib.sha256(json.dumps(case,sort_keys=True).encode()).hexdigest())


def stationary_draws(log_pairs, entry_factors, years, block_length, replications, seed):
    """Paired stationary circular blocks; opening charges remain fixed once."""
    pairs=np.asarray(log_pairs,dtype=float);entry=np.asarray(entry_factors,dtype=float)
    if pairs.ndim!=2 or pairs.shape[1]!=2 or len(pairs)<2 or not np.isfinite(pairs).all():
        raise ValueError('finite two-column aligned log-return pair required')
    if entry.shape!=(2,) or (entry<=0).any() or years<=0 or block_length<1 or replications<1:
        raise ValueError('valid entry factors and bootstrap controls required')
    rng=np.random.default_rng(seed);n=len(pairs);index=rng.integers(0,n,size=replications)
    totals=np.tile(np.log(entry),(replications,1))
    for t in range(n):
        if t:
            restart=rng.random(replications)<1/block_length
            replacement=rng.integers(0,n,size=replications)
            index=np.where(restart,replacement,(index+1)%n)
        totals+=pairs[index]
    return np.expm1(totals/years)


def bootstrap(factor, core, baseline, protocol):
    if not factor.history.index.equals(core.history.index):raise ValueError('paired bootstrap dates differ')
    eq=np.column_stack([factor.history.equity_usd,core.history.equity_usd]);capital=baseline['initial_equity_usd']
    entry=eq[0]/capital;logs=np.log(eq[1:]/eq[:-1])
    years=(factor.history.index[-1]-factor.history.index[0]).days/baseline['measurement']['cagr_calendar_year_days']
    recovered=np.expm1((np.log(entry)+logs.sum(axis=0))/years)
    for i,name in enumerate(['factor','core']):
        if abs(recovered[i]-protocol['baseline_expected'][name]['cagr'])>protocol['validation']['metric_atol']:
            raise ValueError('original-order bootstrap identity differs')
    investor=np.column_stack([investor_equity_returns(x.history.equity_usd,initial_committed_capital_usd=capital)
                             for x in [factor,core]])
    active=investor[:,0]-investor[:,1];tracking=float(np.std(active,ddof=1)*math.sqrt(252))
    ir=float(np.mean(active)*252/tracking) if tracking else None
    records=[];summaries=[];cfg=protocol['bootstrap']
    for length in cfg['expected_block_lengths_common_nav_intervals']:
        seed=cfg['seeds'][str(length)];draws=stationary_draws(logs,entry,years,length,cfg['replications_per_block_length'],seed)
        gaps=100*(draws[:,0]-draws[:,1]);low,high=np.quantile(gaps,[.025,.975],method='linear')
        for i,(f,c) in enumerate(draws):records.append(dict(block_length=length,replicate=i+1,factor_cagr=float(f),core_cagr=float(c),gap_pp=float(100*(f-c))))
        summaries.append(dict(block_length=length,replications=len(gaps),seed=seed,
            observed_gap_pp=float(100*(recovered[0]-recovered[1])),median_gap_pp=float(np.median(gaps)),
            mean_gap_pp=float(np.mean(gaps)),ci_low_pp=float(low),ci_high_pp=float(high),
            standard_deviation_pp=float(np.std(gaps,ddof=1)),ci_includes_zero=bool(low<=0<=high)))
    return pd.DataFrame(records),pd.DataFrame(summaries),dict(
        original_order_cagrs=dict(zip(['factor','core'],map(float,recovered))),
        opening_cost_factors=dict(zip(['factor','core'],map(float,entry))),
        resampled_post_entry_intervals=len(logs),elapsed_years=years,
        tracking_error_annual=tracking,information_ratio=ir,
        tracking_error_opening_charge='folded once into first investor interval, matching historical measurement',
        bootstrap_opening_charge='fixed once, excluded from resampled post-entry returns',
        return_precision='recomputed from the pinned common NAV levels, matching the original in-memory simulator; rounded return CSV retained as an identity pin',
        bootstrap_scope=cfg['limits'],numpy_version=np.__version__,rng='numpy.default_rng PCG64')


def run(project, core_directory, output, protocol_path=None):
    project,core_directory,output=map(lambda p:Path(p).resolve(),[project,core_directory,output])
    require_runtime();require_installation(project)
    path=project/'config/paired_robustness_protocol_2026-10-09.json' if protocol_path is None else Path(protocol_path)
    protocol=validate_protocol(project,path)
    verify_run(core_directory)
    for relative,expected in protocol['admitted_input_pins'].items():
        if sha256(core_directory/relative)!=expected:raise ValueError('admitted study input differs: '+relative)
    if output.exists() or not output.is_relative_to(project):raise ValueError('choose a new study output inside the project')
    baseline=json.loads((project/'config/backtest_absolute_decoupled_2026-10-05.json').read_text())
    nav=pd.read_csv(core_directory/'inputs/common_nav_usd.csv',index_col='date',parse_dates=True,float_precision='round_trip')
    # The original simulator recomputes returns from admitted NAVs before the
    # display CSV rounds return intervals to twelve decimals. Restore that
    # exact precision contract rather than relax the account tolerance.
    returns=nav.pct_change(fill_method=None);returns.iloc[0]=0.
    reference=pd.read_csv(core_directory/'inputs/canonical/daily_borrow_rates_usd.csv',index_col='date',parse_dates=True,float_precision='round_trip').reference_rate_annual
    curves=pd.read_csv(core_directory/'results/equity_curves.csv',index_col='date',parse_dates=True,float_precision='round_trip')
    for requested,actual in zip(protocol['requested_end_dates'],protocol['actual_end_dates']):
        if str(returns.loc[:requested].index[-1].date())!=actual:raise ValueError('endpoint mapping differs')
    output.mkdir(parents=True);(output/'config').mkdir();(output/'histories').mkdir();(output/'events').mkdir();(output/'fee_calendars').mkdir()
    shutil.copyfile(path,output/'config/PROTOCOL.json')
    shutil.copyfile(project/'config/backtest_absolute_decoupled_2026-10-05.json',output/'config/baseline.json')
    initial_pin=sha256(path);source_pins={str(p.relative_to(project)):sha256(p) for p in [Path(__file__).resolve(),project/'src/factor_portfolio/historical.py',project/'src/factor_portfolio/coupled_inflow_accounting.py',project/'src/factor_portfolio/config.py']}
    manifest=dict(schema_version=1,run_id=str(uuid.uuid4()),status='running',figures_included=False,
        configuration_snapshots={'config/PROTOCOL.json':initial_pin,'config/baseline.json':sha256(output/'config/baseline.json')},
        code=source_pins,artifacts={},scope='Frozen paired OAT matrix and conditional realised-return bootstrap; no original financial engine changes')
    write_json(output/'run_manifest.json',manifest)
    try:
        original_case=protocol['cases'][0];base_runs={};baseline_checks={}
        for strategy in ['factor','core']:
            result,plan=run_account(returns,reference,baseline,original_case,strategy)
            out=outcome(result,original_case,strategy,protocol['requested_end_dates'][-1],baseline)
            checks={}
            for field,expected in protocol['baseline_expected'][strategy].items():
                actual=out['post_entry_events'] if field=='trades_after_entry' else out[field]
                tolerance=protocol['validation']['metric_atol'] if field=='cagr' else protocol['validation']['account_usd_atol']
                if abs(actual-expected)>tolerance:raise ValueError('baseline mismatch: '+strategy+' '+field)
                checks[field]=dict(expected=expected,actual=actual,absolute_difference=abs(actual-expected),tolerance=tolerance)
            wealth=curves['full_factor_absolute_decoupled_1.25' if strategy=='factor' else 'full_core_1.25']
            if not result.history.index.equals(wealth.index):raise ValueError('original wealth calendar differs')
            difference=float((result.history.equity_usd-wealth).abs().max())
            if difference>protocol['validation']['account_usd_atol']:raise ValueError('baseline original wealth path differs')
            checks['all_observation_wealth']=dict(maximum_absolute_difference_usd=difference,observations=len(wealth))
            checks['zero_fee_coupled_equals_original_every_field_and_event']=True
            baseline_checks[strategy]=checks;base_runs[strategy]=result
        write_json(output/'baseline_checks.json',dict(status='passed',checks=baseline_checks))
        print('Exact baseline verified before variants.',flush=True)
        accounts=[];pairs=[];availability=[]
        for case in protocol['cases']:
            if not case['available']:
                if case['start'] is not None:raise ValueError('unavailable start must remain missing')
                for requested,end in zip(protocol['requested_end_dates'],protocol['actual_end_dates']):
                    availability.append(dict(case_id=case['id'],requested_end=requested,end=end,available=False,reason=case['unavailable_reason']))
                continue
            if pd.Timestamp(case['start']) not in returns.index:raise ValueError('case start absent from admitted calendar')
            for requested,end in zip(protocol['requested_end_dates'],protocol['actual_end_dates']):
                available_row=dict(case_id=case['id'],requested_end=requested,end=end,available=True,reason='')
                availability.append(available_row)
                ret=returns.loc[case['start']:end].copy();ret.iloc[0]=0.;outcomes={}
                for strategy in ['factor','core']:
                    result,calendar=run_account(ret,reference,baseline,case,strategy)
                    row=outcome(result,case,strategy,requested,baseline);accounts.append(row);outcomes[strategy]=row
                    label=case['id']+'__'+end+'__'+strategy
                    result.history.to_csv(output/'histories'/(label+'.csv'),lineterminator='\n')
                    result.events.to_csv(output/'events'/(label+'.csv'),index=False,lineterminator='\n')
                    calendar.to_csv(output/'fee_calendars'/(label+'.csv'),index=False,lineterminator='\n')
                a,b=outcomes['factor'],outcomes['core']
                pairs.append(dict(case_id=case['id'],dimension=case['dimension'],start=a['start'],end=end,requested_end=requested,
                    factor_cagr=a['cagr'],core_cagr=b['cagr'],cagr_gap_pp=100*(a['cagr']-b['cagr']),
                    factor_post_entry_events=a['post_entry_events'],core_post_entry_events=b['post_entry_events'],
                    factor_sleeve_only_events=a['sleeve_only_events'],factor_leverage_only_events=a['leverage_only_events'],factor_joint_events=a['joint_events'],
                    core_leverage_only_events=b['leverage_only_events'],factor_fund_fee_usd=a['fund_fee_usd'],core_fund_fee_usd=b['fund_fee_usd'],
                    margin_bps=case['margin_bps'],fund_fee_bps=case['fund_fee_bps'],leverage_band=case['leverage_band'],sleeve_band=case['sleeve_band'],case_sha256=a['case_sha256']))
            print('Completed '+case['id'],flush=True)
        account_frame,pair_frame=pd.DataFrame(accounts),pd.DataFrame(pairs)
        if len(pair_frame)!=56 or len(account_frame)!=112:raise ValueError('complete frozen matrix coverage required')
        summary=[];families=[]
        for end,group in pair_frame.groupby('end',sort=True):
            base_gap=float(group.loc[group.case_id.eq('baseline'),'cagr_gap_pp'].iloc[0])
            def describe(g):
                values=g.cagr_gap_pp.to_numpy();return dict(available_pairs=len(g),baseline_gap_pp=base_gap,
                    median_gap_pp=float(np.median(values)),minimum_gap_pp=float(values.min()),maximum_gap_pp=float(values.max()),
                    positive_pairs=int((values>0).sum()),negative_pairs=int((values<0).sum()),zero_pairs=int((values==0).sum()))
            summary.append(dict(end=end,**describe(group)))
            for dimension,g in group.groupby('dimension',sort=True):families.append(dict(end=end,dimension=dimension,**describe(g)))
        for name,frame in [('accounts.csv',account_frame),('paired_matrix.csv',pair_frame),('availability.csv',pd.DataFrame(availability)),
                           ('endpoint_summary.csv',pd.DataFrame(summary)),('family_summary.csv',pd.DataFrame(families))]:
            frame.to_csv(output/name,index=False,lineterminator='\n')
        draws,bootstrap_summary,definitions=bootstrap(base_runs['factor'],base_runs['core'],baseline,protocol)
        draws.to_csv(output/'bootstrap_draws.csv',index=False,lineterminator='\n');bootstrap_summary.to_csv(output/'bootstrap_summary.csv',index=False,lineterminator='\n')
        write_json(output/'measurement_definitions.json',definitions)
        write_json(output/'study_checks.json',dict(status='passed',available_variants=14,unavailable_variants=5,paired_endpoint_results=56,
            account_endpoint_results=112,unavailable_endpoint_rows=20,bootstrap_draws=len(draws),original_order_bootstrap_checked=True,
            secondary_timing='not run; excluded by frozen conditional gate',primary_strategy_changed=False,
            scope='Conditional scenario sensitivity and realised-return sampling uncertainty are separate; no probability or CAGR significance inferred from parameter span'))
        if sha256(path)!=initial_pin or any(sha256(project/relative)!=digest for relative,digest in source_pins.items()):
            raise RuntimeError('protocol or code changed during study')
        manifest.update(status='complete',artifacts={str(p.relative_to(output)):sha256(p) for p in sorted(output.rglob('*'))
            if p.is_file() and p!=output/'run_manifest.json' and p.relative_to(output).parts[0]!='config'})
        write_json(output/'run_manifest.json',manifest);verify_run(output)
        print(json.dumps(dict(endpoint_summary=summary,bootstrap=bootstrap_summary.to_dict('records'),active_return_metrics=definitions),indent=2))
        return manifest
    except Exception as error:
        manifest.update(status='failed',failure=dict(type=type(error).__name__,message=str(error)))
        write_json(output/'run_manifest.json',manifest);raise


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root',type=Path,default=Path.cwd())
    parser.add_argument('--core',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--protocol',type=Path)
    args=parser.parse_args();run(args.project_root,args.core,args.output,args.protocol)

if __name__=='__main__':main()
