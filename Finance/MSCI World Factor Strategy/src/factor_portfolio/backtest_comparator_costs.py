"""Dimensional zero-external-trading-cost control with factor costs retained."""
from __future__ import annotations

import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import uuid

import pandas as pd

from .backtest_workflow import admit_sources,prepare_inputs,run_backtest_study,validate_config
from .config import SwissquoteStandardFeeSchedule
from .historical import simulate,metrics
from .inflow_workflow import sha256,source_hashes,verify_run,write_json


def validate_settings(settings,baseline):
    if (settings['schema_version']!=1 or settings['period']!='full'
        or settings['comparator']!='dimensional' or settings['comparator_policy']!='no_sleeve'
        or settings['zero_external_transaction_costs'] is not True
        or settings['factor_baseline_transaction_costs'] is not True or settings['retain_reference_and_margin'] is not True):
        raise ValueError('only Dimensional external trading charges may be removed')
    policies=settings['factor_policies'];exposures=settings['leverage_levels']
    if (not policies or len(set(policies))!=len(policies) or baseline['primary_policy'] not in policies
        or settings['legacy_policy'] not in policies or any(p not in baseline['policies'] for p in policies)):
        raise ValueError('distinct primary/legacy factor policies required')
    if not exposures or len(set(exposures))!=len(exposures) or any(x not in baseline['leverage_levels'] for x in exposures):
        raise ValueError('comparator exposures must match baseline')


def comparator_cost_comparison(returns,reference,baseline,settings):
    validate_settings(settings,baseline);boundaries=baseline['periods']['full']
    ret=returns.loc[boundaries['start']:boundaries['end']].copy()
    if len(ret)<4:raise ValueError('complete comparator histories need enough observations')
    if str(ret.index[0].date())!=boundaries['start'] or str(ret.index[-1].date())!=boundaries['end']:
        raise ValueError('complete declared full-period calendar required')
    ret.iloc[0]=0.;fee=SwissquoteStandardFeeSchedule(**baseline['fee_schedule'])
    sleeves=list(baseline['target_weights']);weights=list(baseline['target_weights'].values())
    records=[];histories=[];events=[];runs={};summary=[]

    def account(cols,target,lev,policy,free=False):
        run=simulate(ret[cols],reference,target,lev,policy,margin=baseline['borrowing_margin_annual'],
            sleeve_band=baseline['sleeve_band'],leverage_band=baseline['leverage_band'],fee_free=free,
            initial_equity_usd=baseline['initial_equity_usd'],fee_schedule=fee)
        if run.status!='complete' or len(run.history)!=len(ret):raise ValueError('incomplete comparator path rejected')
        if free and (not run.events.fees_usd.eq(0).all() or not run.history.cumulative_transaction_cost_usd.eq(0).all()):
            raise ValueError('zero-external-cost control contains transaction charges')
        return run

    market=account(['core'],[1.],1.,'no_sleeve')
    for lev in settings['leverage_levels']:
        cases=[('dimensional','no_sleeve','baseline',False),('dimensional','no_sleeve','zero_external',True)]
        cases.extend(('factor',policy,'baseline',False) for policy in settings['factor_policies'])
        for strategy,policy,mode,free in cases:
            cols,target=(sleeves,weights) if strategy=='factor' else (['dimensional'],[1.])
            run=account(cols,target,lev,policy,free);run_id=f'{strategy}__{policy}__{mode}__{lev:.2f}'
            measured=metrics(run,reference,market,target);runs[strategy,policy,mode,lev]=measured
            records.append(dict(run_id=run_id,strategy=strategy,policy=policy,external_cost_mode=mode,leverage=lev,**measured))
            histories.append(run.history.reset_index().assign(run_id=run_id));events.append(run.events.assign(run_id=run_id))
        zero=runs['dimensional','no_sleeve','zero_external',lev];normal=runs['dimensional','no_sleeve','baseline',lev]
        for policy in settings['factor_policies']:
            factor=runs['factor',policy,'baseline',lev]
            summary.append(dict(policy=policy,leverage=lev,dimensional_zero_external_cost_cagr=zero['cagr'],factor_baseline_cagr=factor['cagr'],
                factor_cagr_gap=factor['cagr']-zero['cagr'],dimensional_zero_external_cost_drawdown=zero['maximum_drawdown'],
                dimensional_zero_external_cost_volatility=zero['annualised_volatility'],factor_drawdown=factor['maximum_drawdown'],factor_volatility=factor['annualised_volatility'],
                factor_joint_growth_risk_pass=bool(factor['cagr']>zero['cagr'] and factor['maximum_drawdown']>=zero['maximum_drawdown'] and factor['annualised_volatility']<=zero['annualised_volatility']),
                dimensional_baseline_cagr=normal['cagr'],dimensional_cagr_change=zero['cagr']-normal['cagr'],
                dimensional_baseline_transaction_cost_usd=normal['transaction_cost_usd'],dimensional_zero_external_transaction_cost_usd=zero['transaction_cost_usd'],
                dimensional_baseline_financing_cost_usd=normal['financing_cost_usd'],dimensional_zero_external_financing_cost_usd=zero['financing_cost_usd']))
    table=pd.DataFrame(summary)
    legacy_columns=['leverage','dimensional_zero_external_cost_cagr','factor_baseline_cagr','factor_cagr_gap','dimensional_zero_external_cost_drawdown','dimensional_zero_external_cost_volatility']
    return dict(metrics=pd.DataFrame(records),histories=pd.concat(histories,ignore_index=True),events=pd.concat(events,ignore_index=True),
        comparison=table,legacy=table[table.policy==settings['legacy_policy']][legacy_columns].reset_index(drop=True),
        definitions=dict(settings=settings,source_full_period=boundaries,initial_equity_usd=baseline['initial_equity_usd'],
            cost_scope='Only Dimensional external transaction charges removed via the unchanged simulator fee_free option. Baseline factor costs and NAV-embedded expenses remain.',
            financing='Same observed reference plus baseline margin and ACT360. Financing dollar amounts can differ as portfolio/debt scale changes.',
            risk_reference='Net-cost unlevered Core, original investor/risk conventions.',
            limitations=['Favourable hypothetical comparator control, not a verified fund-distribution or execution tariff.',
                'No additive embedded-versus-external fund cost attribution or future-performance conclusion.',
                'No custody charge, capital flow, actual lending approval or final report included.']))


def run_comparator_costs(raw_root,baseline_path,sources_path,settings_path,output):
    output=Path(output)
    if output.exists():raise FileExistsError('choose a new comparator-cost output directory')
    paths=[baseline_path,sources_path,settings_path];captured={Path(p).name:Path(p).read_bytes() for p in paths}
    if len(captured)!=3:raise ValueError('distinct configuration filenames required')
    baseline,spec,settings=[json.loads(captured[Path(p).name]) for p in paths]
    validate_config(baseline);validate_settings(settings,baseline)
    output.mkdir(parents=True);(output/'config').mkdir()
    for name,data in captured.items():(output/'config'/name).write_bytes(data)
    code=source_hashes();manifest=dict(schema_version=1,run_id=str(uuid.uuid4()),status='running',figures_included=False,
        started_at_utc=datetime.now(timezone.utc).isoformat(),code=code,
        scope='Fresh original-input core plus Dimensional zero-external-trading-cost control; baseline factor charges and all financing/NAV conventions retained. No final report.',
        configuration_snapshots={f'config/{name}':sha256(output/'config'/name) for name in captured},artifacts={})
    write_json(output/'run_manifest.json',manifest)
    try:
        core=run_backtest_study(raw_root,output/'config'/Path(baseline_path).name,output/'config'/Path(sources_path).name,output/'core')
        inputs=output/'control_inputs';inputs.mkdir()
        # Regenerate in-memory full-precision returns from raw files. Serialized
        # return tables have fewer decimals and are evidence, not simulation inputs.
        returns,reference=prepare_inputs(raw_root,admit_sources(raw_root,spec),spec,baseline,inputs)
        result=comparator_cost_comparison(returns,reference,baseline,settings)
        for key,name in [('metrics','comparator_cost_metrics.csv'),('histories','comparator_cost_histories.csv'),('events','comparator_cost_events.csv'),
                         ('comparison','comparator_cost_comparison.csv'),('legacy','legacy_dimensional_external_cost_sensitivity.csv')]:
            result[key].to_csv(output/name,index=False,lineterminator='\n')
        write_json(output/'comparator_cost_definitions.json',result['definitions'])
        (output/'README.md').write_text('# Dimensional External-Cost Control\n\nDimensional external transaction charges are set to zero; NAV-embedded expenses and existing funding/leverage rules remain. '
            'Factor portfolios retain baseline costs. This is a hypothetical favourable control, not a tariff estimate or forecast.\n\n'
            '[Comparison](comparator_cost_comparison.csv) · [Metrics](comparator_cost_metrics.csv) · [Accounts](comparator_cost_histories.csv) · '
            '[Trades](comparator_cost_events.csv) · [Legacy view](legacy_dimensional_external_cost_sensitivity.csv) · [Definitions](comparator_cost_definitions.json) · [Fresh core](core/README.md) · [Manifest](run_manifest.json)\n')
        admit_sources(raw_root,spec)
        if source_hashes()!=code:raise RuntimeError('source changed during comparator control')
        manifest['artifacts']={str(p.relative_to(output)):sha256(p) for p in sorted(output.rglob('*')) if p.is_file() and p!=output/'run_manifest.json' and p.relative_to(output).parts[0]!='config'}
        manifest.update(status='complete',finished_at_utc=datetime.now(timezone.utc).isoformat(),raw_sources=core['raw_sources'],
            counts=dict(control_cases=len(result['metrics']),comparison_rows=len(result['comparison']),history_rows=len(result['histories']),trade_events=len(result['events']),core_cases=core['counts']['policy_cases']))
        write_json(output/'run_manifest.json',manifest);verify_run(output)
    except Exception as error:
        manifest.update(status='failed',failure=dict(type=type(error).__name__,message=str(error)));write_json(output/'run_manifest.json',manifest);raise
    return manifest


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--raw-root',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    for key,name in [('baseline','backtest_absolute_decoupled_2026-10-05.json'),('sources','backtest_sources.json'),('settings','backtest_comparator_costs_absolute_decoupled_2026-10-05.json')]:p.add_argument('--'+key,type=Path,default=Path('config')/name)
    a=p.parse_args();m=run_comparator_costs(a.raw_root,a.baseline,a.sources,a.settings,a.output);print(json.dumps(dict(run_id=m['run_id'],status=m['status'],counts=m['counts']),indent=2))


if __name__=='__main__':main()
