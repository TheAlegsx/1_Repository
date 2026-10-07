"""Eight unlevered weight proposals with retained and current policy comparisons."""
from __future__ import annotations

import argparse
from datetime import datetime,timezone
import json
import math
from pathlib import Path
import uuid

import numpy as np
import pandas as pd

from .backtest_workflow import admit_sources,prepare_inputs,run_backtest_study,validate_config
from .config import SwissquoteStandardFeeSchedule
from .historical import simulate,metrics
from .inflow_workflow import sha256,source_hashes,verify_run,write_json

ALLOCATION_NAMES=['original','previous','equal_factors','stronger_anchor','stronger_factors','momentum_focus','quality_focus','value_focus']


def validate_settings(settings,baseline):
    if settings['schema_version']!=1 or settings['leverage']!=1. or settings['periods']!=['full','calibration','confirmation']:
        raise ValueError('allocation comparisons require unlevered independently restarted baseline periods')
    policies=settings['factor_policies']
    if (len(policies)!=2 or len(set(policies))!=len(policies) or settings['legacy_policy']!='hybrid20'
        or baseline['primary_policy']==settings['legacy_policy'] or baseline['primary_policy'] not in policies
        or settings['legacy_policy'] not in policies or any(p not in baseline['policies'] for p in policies)):
        raise ValueError('distinct primary and legacy allocation policies required')
    if list(settings['allocations'])!=ALLOCATION_NAMES or settings['selected_allocation']!='original':
        raise ValueError('preserved eight allocation labels and original selection required')
    sleeves=list(baseline['target_weights'])
    for name,weights in settings['allocations'].items():
        if (set(weights)!=set(sleeves) or any(not math.isfinite(v) or v<=0 for v in weights.values())
            or abs(math.fsum(weights.values())-1)>1e-10):
            raise ValueError('positive complete allocation weights must sum to one')
    if settings['allocations']['original']!=baseline['target_weights']:
        raise ValueError('selected allocation must preserve baseline target weights')


def allocation_comparison(returns,reference,baseline,settings):
    validate_settings(settings,baseline);fee=SwissquoteStandardFeeSchedule(**baseline['fee_schedule'])
    sleeves=list(baseline['target_weights']);rows=[];histories=[];events=[]
    for period in settings['periods']:
        boundaries=baseline['periods'][period];ret=returns.loc[boundaries['start']:boundaries['end']].copy()
        if len(ret)<4 or str(ret.index[0].date())!=boundaries['start'] or str(ret.index[-1].date())!=boundaries['end']:
            raise ValueError('complete declared allocation period required')
        ret.iloc[0]=0.

        def account(cols,target,policy):
            run=simulate(ret[cols],reference,target,1.,policy,margin=baseline['borrowing_margin_annual'],
                sleeve_band=baseline['sleeve_band'],leverage_band=baseline['leverage_band'],initial_equity_usd=baseline['initial_equity_usd'],fee_schedule=fee)
            if run.status!='complete' or len(run.history)!=len(ret):raise ValueError('incomplete allocation account')
            h=run.history
            if (h.debt_usd.abs().max()>1e-7 or h.cumulative_financing_cost_usd.abs().max()>1e-7 or (h.leverage-1).abs().max()>1e-12):
                raise ValueError('unlevered allocation develops borrowing')
            return run

        market=account(['core'],[1.],'no_sleeve')

        def record(run,name,strategy,policy,weights):
            label=f'{period}__{strategy}__{policy}__{name}'
            weight_fields={f'{s}_weight':v for s,v in zip(sleeves,weights)} if strategy=='factor' else {}
            rows.append(dict(run_id=label,policy=policy,strategy=strategy,period=period,allocation=name,**weight_fields,
                **metrics(run,reference,market,weights)))
            histories.append(run.history.reset_index().assign(run_id=label));events.append(run.events.assign(run_id=label))

        for policy in settings['factor_policies']:
            for name,weights in settings['allocations'].items():
                target=[weights[s] for s in sleeves];record(account(sleeves,target,policy),name,'factor',policy,target)
        for name in ['core','dimensional']:
            run=market if name=='core' else account(['dimensional'],[1.],'no_sleeve')
            record(run,name,name,'no_sleeve',[1.])
    table=pd.DataFrame(rows)
    for name in ['core','dimensional']:
        bench=table[table.allocation==name].set_index('period')
        for field in ['cagr','annualised_volatility','maximum_drawdown','ending_equity_usd']:
            table[f'{field}_difference_vs_{name}']=table[field]-table.period.map(bench[field])
        table[f'joint_pass_vs_{name}']=((table[f'cagr_difference_vs_{name}']>0)&(table[f'annualised_volatility_difference_vs_{name}']<=0)&(table[f'maximum_drawdown_difference_vs_{name}']>=0))
    pairs=[];primary=baseline['primary_policy'];legacy=settings['legacy_policy']
    for period in settings['periods']:
        for name in settings['allocations']:
            a=table[(table.period==period)&(table.allocation==name)&(table.policy==primary)].iloc[0]
            b=table[(table.period==period)&(table.allocation==name)&(table.policy==legacy)].iloc[0]
            pairs.append(dict(period=period,allocation=name,primary_policy=primary,legacy_policy=legacy,
                primary_cagr=a.cagr,legacy_cagr=b.cagr,cagr_difference_pp=100*(a.cagr-b.cagr),
                primary_volatility=a.annualised_volatility,legacy_volatility=b.annualised_volatility,
                primary_drawdown=a.maximum_drawdown,legacy_drawdown=b.maximum_drawdown,
                primary_transaction_cost_usd=a.transaction_cost_usd,legacy_transaction_cost_usd=b.transaction_cost_usd,
                primary_trades_after_entry=a.trades_after_entry,legacy_trades_after_entry=b.trades_after_entry))
    old=table[(table.strategy!='factor')|(table.policy==legacy)].drop(columns=['run_id','policy','strategy']).reset_index(drop=True)
    return dict(metrics=table,legacy=old,pairs=pd.DataFrame(pairs),histories=pd.concat(histories,ignore_index=True),events=pd.concat(events,ignore_index=True),
        definitions=dict(settings=settings,selected_weights=baseline['target_weights'],selected_policy=primary,
            period_convention='Independent initial capital/debt/entry-cost restart at every declared period; first return reset to zero before accounting.',
            comparison='Equal unlevered exposure, common dates, original costs and unlevered net Core risk reference. Benchmarks are shared between policies.',
            no_automatic_selection=True,limitations=['All weight/policy/period comparisons are retrospective. Confirmation is not newly untouched out-of-sample data.',
                'Higher full-sample return does not select a prospective optimal allocation.',
                'No borrowed allocation variants, optimiser, administration fees, capital flows or final report.']))


def run_allocations(raw_root,baseline_path,sources_path,settings_path,output):
    output=Path(output)
    if output.exists():raise FileExistsError('choose a new allocation output directory')
    paths=[baseline_path,sources_path,settings_path];captured={Path(p).name:Path(p).read_bytes() for p in paths}
    if len(captured)!=3:raise ValueError('distinct configuration filenames required')
    baseline,spec,settings=[json.loads(captured[Path(p).name]) for p in paths]
    validate_config(baseline);validate_settings(settings,baseline)
    output.mkdir(parents=True);(output/'config').mkdir()
    for name,data in captured.items():(output/'config'/name).write_bytes(data)
    code=source_hashes();manifest=dict(schema_version=1,run_id=str(uuid.uuid4()),status='running',figures_included=False,
        started_at_utc=datetime.now(timezone.utc).isoformat(),code=code,
        scope='Eight unlevered allocation proposals under current and preserved policies on independently restarted periods, plus original-input core. No optimisation or final reports.',
        configuration_snapshots={f'config/{name}':sha256(output/'config'/name) for name in captured},artifacts={})
    write_json(output/'run_manifest.json',manifest)
    try:
        core=run_backtest_study(raw_root,output/'config'/Path(baseline_path).name,output/'config'/Path(sources_path).name,output/'core')
        inputs=output/'allocation_inputs';inputs.mkdir()
        returns,reference=prepare_inputs(raw_root,admit_sources(raw_root,spec),spec,baseline,inputs)
        result=allocation_comparison(returns,reference,baseline,settings)
        for key,name in [('metrics','allocation_metrics.csv'),('pairs','allocation_policy_comparison.csv'),('histories','allocation_histories.csv'),('events','allocation_events.csv')]:
            result[key].to_csv(output/name,index=False,lineterminator='\n')
        # Preserve the old 44-column serialization boundary for exact acceptance.
        result['legacy'].to_csv(output/'legacy_allocation_metrics.csv',index=False,float_format='%.12f',lineterminator='\n')
        write_json(output/'allocation_definitions.json',result['definitions'])
        (output/'README.md').write_text('# Unlevered Allocation Evidence\n\nEight preserved proposals, both factor rules, three independently restarted periods and shared Core/Dimensional benchmarks. '
            'Selected 60/15/10/15 weights stay unchanged; no automatic optimisation or future best-allocation claim.\n\n'
            '[Metrics](allocation_metrics.csv) · [Policy pairs](allocation_policy_comparison.csv) · [Accounts](allocation_histories.csv) · '
            '[Trades](allocation_events.csv) · [Legacy 44-column view](legacy_allocation_metrics.csv) · [Definitions](allocation_definitions.json) · [Fresh core](core/README.md) · [Manifest](run_manifest.json)\n')
        admit_sources(raw_root,spec)
        if source_hashes()!=code:raise RuntimeError('source changed during allocation comparison')
        manifest['artifacts']={str(p.relative_to(output)):sha256(p) for p in sorted(output.rglob('*')) if p.is_file() and p!=output/'run_manifest.json' and p.relative_to(output).parts[0]!='config'}
        manifest.update(status='complete',finished_at_utc=datetime.now(timezone.utc).isoformat(),raw_sources=core['raw_sources'],
            counts=dict(allocation_cases=len(result['metrics']),legacy_cases=len(result['legacy']),policy_pairs=len(result['pairs']),history_rows=len(result['histories']),trade_events=len(result['events']),core_cases=core['counts']['policy_cases']))
        write_json(output/'run_manifest.json',manifest);verify_run(output)
    except Exception as error:
        manifest.update(status='failed',failure=dict(type=type(error).__name__,message=str(error)));write_json(output/'run_manifest.json',manifest);raise
    return manifest


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--raw-root',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    for key,name in [('baseline','backtest_absolute_decoupled_2026-10-05.json'),('sources','backtest_sources.json'),('settings','backtest_allocations_absolute_decoupled_2026-10-05.json')]:p.add_argument('--'+key,type=Path,default=Path('config')/name)
    a=p.parse_args();m=run_allocations(a.raw_root,a.baseline,a.sources,a.settings,a.output);print(json.dumps(dict(run_id=m['run_id'],status=m['status'],counts=m['counts']),indent=2))


if __name__=='__main__':main()
