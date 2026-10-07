"""Matched financing/spread stress grid with separate scalar account verification."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import uuid

import numpy as np
import pandas as pd

from .backtest_workflow import run_backtest_study, prepare_inputs, admit_sources, validate_config
from .backtest_independent_core import comparison_rows, validate_settings as validate_independent
from .backtest_independent_complete import account_checks, compare_event_paths
from .config import SwissquoteStandardFeeSchedule
from .historical import simulate, metrics
from .independent_scalar import calculate
from .inflow_workflow import sha256, source_hashes, verify_run, write_json


def validate_settings(settings,baseline):
    validate_config(baseline);validate_independent(settings)
    if (settings['period']!='full' or settings['target_leverage']!=baseline['primary_leverage']
        or settings['factor_policies']!=['hybrid20','absolute_decoupled']
        or baseline['primary_policy']!='absolute_decoupled'
        or settings['margin_bps']!=[200,300,425,500,700,1000]
        or settings['one_way_spread_bps']!=[0,5,10,20,30,50,100]):
        raise ValueError('preserved 42-cell grid, matched policies and primary exposure required')
    if any(p not in baseline['policies'] for p in settings['factor_policies']):
        raise ValueError('joint-cost policies must exist in baseline')


def joint_criterion(factor,core):
    fields=['cagr','annualised_volatility','maximum_drawdown']
    if not all(math.isfinite(float(r[k])) for r in [factor,core] for k in fields):
        raise ValueError('finite joint-risk outcomes required')
    return bool(factor['cagr']>core['cagr'] and factor['annualised_volatility']<=core['annualised_volatility']
        and factor['maximum_drawdown']>=core['maximum_drawdown'])


def cost_comparison(returns,reference,levels,baseline,settings):
    validate_settings(settings,baseline);bounds=baseline['periods']['full']
    ret=returns.loc[bounds['start']:bounds['end']].copy();nav=levels.loc[ret.index]
    if len(ret)<4 or str(ret.index[0].date())!=bounds['start'] or str(ret.index[-1].date())!=bounds['end']:
        raise ValueError('complete configured cost-grid calendar required')
    ret.iloc[0]=0.;sleeves=list(baseline['target_weights']);weights=list(baseline['target_weights'].values())
    shared=dict(initial_equity_usd=baseline['initial_equity_usd'],sleeve_band=baseline['sleeve_band'],leverage_band=baseline['leverage_band'])
    market=simulate(ret[['core']],reference,[1.],1.,'no_sleeve',margin=baseline['borrowing_margin_annual'],
        fee_schedule=SwissquoteStandardFeeSchedule(**baseline['fee_schedule']),**shared)
    rows=[];scalar_rows=[];histories=[];scalar_histories=[];events=[];scalar_events=[];checks=[];paths=[];pairs=[];definitions=[]
    for margin in settings['margin_bps']:
        for spread in settings['one_way_spread_bps']:
            fee=dict(baseline['fee_schedule'],spread_rate=spread/10000)
            definitions.append(dict(margin_bps=margin,one_way_spread_bps=spread,**fee))
            cell={}
            for strategy,policy in [('core','no_sleeve')]+[('factor',p) for p in settings['factor_policies']]:
                factor=strategy=='factor';cols,target=(sleeves,weights) if factor else (['core'],[1.])
                run=simulate(ret[cols],reference,target,settings['target_leverage'],policy,
                    margin=margin/10000,fee_schedule=SwissquoteStandardFeeSchedule(**fee),**shared)
                if run.status!='complete':raise ValueError('incomplete joint-cost account')
                values=metrics(run,reference,market,target)
                outcome,h,e=calculate(nav[cols],reference,target,settings['target_leverage'],policy,
                    margin=margin/10000,fee_parameters=fee,**shared)
                label=f'{margin}__{spread}__{strategy}__{policy}'
                metadata=dict(case_id=label,margin_bps=margin,one_way_spread_bps=spread,strategy=strategy,policy=policy,
                    target_leverage=settings['target_leverage'])
                rows.append(dict(**metadata,**values));scalar_rows.append(dict(**metadata,**outcome));cell[policy]=values
                histories.append(run.history.reset_index().assign(**metadata));scalar_histories.append(h.assign(**metadata))
                events.append(run.events.assign(**metadata));scalar_events.append(e.assign(**metadata))
                checks.extend(comparison_rows(values,outcome,baseline,settings,label))
                account=account_checks(h,e,baseline);trade=compare_event_paths(e,run.events,baseline)
                columns=['equity_usd','gross_assets_usd','debt_usd','transaction_cost_usd','financing_cost_usd',
                    'cumulative_transaction_cost_usd','cumulative_financing_cost_usd']+[f'position_{s}_usd' for s in cols]
                actual=h[columns].to_numpy();expected=run.history[columns].to_numpy();gaps=np.abs(actual-expected)
                tolerance=baseline['reconciliation_tolerances'];limits=tolerance['account_usd_atol']+tolerance['account_rtol']*np.abs(expected)
                leverage_error=float(np.abs(h.leverage.to_numpy()-run.history.leverage.to_numpy()).max())
                passed=bool((gaps<=limits).all() and leverage_error<=tolerance['metric_atol'] and account['passed'])
                if h.date.tolist()!=run.history.index.tolist() or h.pending_signal.tolist()!=run.history.pending_signal.tolist():
                    raise ValueError('joint-cost dates or next-observation signals differ')
                paths.append(dict(case_id=label,**account,maximum_account_difference_usd=float(gaps.max()),
                    maximum_leverage_difference=leverage_error,matched_events=trade['events'],daily_path_passed=passed))
            for policy in settings['factor_policies']:
                factor,core=cell[policy],cell['no_sleeve']
                pairs.append(dict(margin_bps=margin,one_way_spread_bps=spread,policy=policy,
                    factor_cagr=factor['cagr'],core_cagr=core['cagr'],gap_pp=100*(factor['cagr']-core['cagr']),
                    volatility_gap_pp=100*(factor['annualised_volatility']-core['annualised_volatility']),
                    drawdown_gap_pp=100*(factor['maximum_drawdown']-core['maximum_drawdown']),
                    factor_trades=factor['trades_after_entry'],core_trades=core['trades_after_entry'],
                    factor_fees=factor['transaction_cost_usd'],core_fees=core['transaction_cost_usd'],joint_pass=joint_criterion(factor,core)))
    pairs=pd.DataFrame(pairs);legacy=pairs[pairs.policy.eq('hybrid20')][['margin_bps','one_way_spread_bps','factor_cagr','core_cagr','gap_pp','factor_trades','core_trades','factor_fees','core_fees']]
    if not all(c['passed'] for c in checks) or not all(p['daily_path_passed'] for p in paths):
        raise ValueError('joint-cost scalar comparison exceeds unchanged tolerances')
    summary={policy:dict(cells=len(g),joint_pass=int(g.joint_pass.sum()),positive_cagr=int(g.gap_pp.gt(0).sum()),
        minimum_cagr_gap_pp=float(g.gap_pp.min()),maximum_cagr_gap_pp=float(g.gap_pp.max()),
        minimum_volatility_gap_pp=float(g.volatility_gap_pp.min()),maximum_volatility_gap_pp=float(g.volatility_gap_pp.max()),
        minimum_drawdown_gap_pp=float(g.drawdown_gap_pp.min()),maximum_drawdown_gap_pp=float(g.drawdown_gap_pp.max()))
        for policy,g in pairs.groupby('policy',sort=False)}
    return dict(metrics=pd.DataFrame(rows),scalar_metrics=pd.DataFrame(scalar_rows),comparisons=pd.DataFrame(checks),
        paths=pd.DataFrame(paths),pairs=pairs,legacy=legacy,fee_definitions=pd.DataFrame(definitions),summary=summary,
        histories=pd.concat(histories,ignore_index=True),scalar_histories=pd.concat(scalar_histories,ignore_index=True),
        events=pd.concat(events,ignore_index=True),scalar_events=pd.concat(scalar_events,ignore_index=True))


def run_joint_cost(raw_root,baseline_path,sources_path,settings_path,output):
    output=Path(output)
    if output.exists():raise FileExistsError('choose a new joint-cost output directory')
    paths=[baseline_path,sources_path,settings_path];captured={Path(p).name:Path(p).read_bytes() for p in paths}
    if len(captured)!=3:raise ValueError('distinct configuration filenames required')
    baseline,spec,settings=[json.loads(captured[Path(p).name]) for p in paths];validate_settings(settings,baseline)
    output.mkdir(parents=True);(output/'config').mkdir()
    for name,data in captured.items():(output/'config'/name).write_bytes(data)
    code=source_hashes();manifest=dict(schema_version=1,run_id=str(uuid.uuid4()),status='running',figures_included=False,
        started_at_utc=datetime.now(timezone.utc).isoformat(),code=code,configuration_snapshots={f'config/{n}':sha256(output/'config'/n) for n in captured},artifacts={},
        scope='Original 42 joint-cost cells and 42 current-policy cells against shared matched Core; 126 production/scalar accounts. Not funding-only grid, bootstrap inference or bank quotations.')
    write_json(output/'run_manifest.json',manifest)
    try:
        cp=output/'config';core=run_backtest_study(raw_root,cp/Path(baseline_path).name,cp/Path(sources_path).name,output/'core')
        fresh=output/'grid_inputs';fresh.mkdir();returns,reference=prepare_inputs(raw_root,admit_sources(raw_root,spec),spec,baseline,fresh)
        levels=pd.read_csv(fresh/'inputs/common_nav_usd.csv',index_col=0,parse_dates=True)
        result=cost_comparison(returns,reference,levels,baseline,settings)
        for key,name in dict(metrics='cost_metrics.csv',scalar_metrics='independent_cost_metrics.csv',comparisons='independent_comparisons.csv',
            paths='daily_path_checks.csv',pairs='cost_policy_comparisons.csv',legacy='legacy_hybrid_cost_stress.csv',fee_definitions='fee_definitions.csv',
            events='trade_events.csv',scalar_events='independent_events.csv').items():
            result[key].to_csv(output/name,index=False,lineterminator='\n')
        for key,name in [('histories','account_histories.csv.gz'),('scalar_histories','independent_histories.csv.gz')]:
            result[key].to_csv(output/name,index=False,float_format='%.17g',lineterminator='\n',compression=dict(method='gzip',mtime=0))
        write_json(output/'cost_summary.json',dict(policies=result['summary'],settings=settings,baseline_fee_schedule=baseline['fee_schedule'],
            criterion='Strictly higher CAGR, no higher investor volatility and no deeper committed-capital drawdown, at matched exposure/costs.',
            limitations=['42 selected retrospective cells, not a probability, continuous/global robustness proof or future validation.',
                'Margin replaces only the markup above observed reference; spread replaces only ordinary one-way spread, not stamp duty, platform or commissions.',
                'All 126 cases share frozen data/model conventions; no approved lender tariff, execution guarantee or independent market feed.',
                'Discontinuous fee tiers, intervention timing and risk comparisons can make cell changes non-monotone.',
                'No original block-bootstrap or broader stress-catalogue claim.']))
        (output/'README.md').write_text('# Joint Financing and Trading Cost Stress\n\n42 retained and 42 primary policy/Core comparisons; 126 accounts and independent scalar/daily checks. '
            'Baseline economics remain unchanged; each stress cell explicitly replaces the borrowing markup and ordinary one-way spread.\n\n'
            '[Summary](cost_summary.json) · [Pairs](cost_policy_comparisons.csv) · [Outcomes](cost_metrics.csv) · [Independent checks](independent_comparisons.csv) · '
            '[Daily checks](daily_path_checks.csv) · [Actual leverage histories](account_histories.csv.gz) · [Manifest](run_manifest.json)\n')
        if source_hashes()!=code:raise RuntimeError('source changed during joint-cost study')
        manifest['artifacts']={str(p.relative_to(output)):sha256(p) for p in sorted(output.rglob('*')) if p.is_file() and p!=output/'run_manifest.json' and p.relative_to(output).parts[0]!='config'}
        manifest.update(status='complete',finished_at_utc=datetime.now(timezone.utc).isoformat(),raw_sources=core['raw_sources'],
            counts=dict(cost_cells=42,matched_policy_pairs=84,account_cases=126,independent_outcomes=1008,
                daily_path_checks=len(result['paths']),history_rows=len(result['histories'])))
        write_json(output/'run_manifest.json',manifest);verify_run(output)
    except Exception as error:
        manifest.update(status='failed',failure=dict(type=type(error).__name__,message=str(error)));write_json(output/'run_manifest.json',manifest);raise
    return manifest


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--raw-root',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    for key,name in [('baseline','backtest_absolute_decoupled_2026-10-05.json'),('sources','backtest_sources.json'),('settings','backtest_joint_cost_2026-10-06.json')]:p.add_argument('--'+key,type=Path,default=Path('config')/name)
    a=p.parse_args();m=run_joint_cost(a.raw_root,a.baseline,a.sources,a.settings,a.output);print(json.dumps(dict(run_id=m['run_id'],status=m['status'],counts=m['counts']),indent=2))


if __name__=='__main__':main()
