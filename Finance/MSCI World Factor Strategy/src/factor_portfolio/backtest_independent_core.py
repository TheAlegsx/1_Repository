"""Fresh core reconciled with a separately implemented scalar accounting model."""
from __future__ import annotations

import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import uuid

import numpy as np
import pandas as pd

from .backtest_workflow import run_backtest_study,validate_config
from .independent_scalar import calculate
from .inflow_workflow import sha256,source_hashes,verify_run,write_json

FIELDS=['ending_equity_usd','cagr','maximum_drawdown','annualised_volatility','transaction_cost_usd','financing_cost_usd','trades_after_entry','margin_calls']


def validate_settings(settings):
    if (settings['schema_version']!=1 or settings['comparison_fields']!=FIELDS
        or settings['currency_fields']!=['ending_equity_usd','transaction_cost_usd','financing_cost_usd']
        or settings['integer_fields']!=['trades_after_entry','margin_calls']):
        raise ValueError('declared independent eight-field core scope required')


def comparison_rows(expected,observed,baseline,settings,case_id):
    tol=baseline['reconciliation_tolerances'];rows=[]
    for field in FIELDS:
        a=float(expected[field]);b=float(observed[field])
        if not np.isfinite([a,b]).all():raise ValueError('finite independent outcomes required')
        limit=(tol['account_usd_atol']+tol['account_rtol']*abs(a)) if field in settings['currency_fields'] else 0. if field in settings['integer_fields'] else tol['metric_atol']
        error=abs(a-b);passed=bool(error<=limit)
        rows.append(dict(case_id=case_id,field=field,production_value=a,independent_value=b,absolute_difference=error,allowed_difference=limit,passed=passed))
    return rows


def reconcile_core(levels,reference,production,curves,baseline,settings):
    validate_settings(settings);records=[];histories=[];events=[];checks=[];wealth=[];sleeves=list(baseline['target_weights']);target=list(baseline['target_weights'].values())
    if production.duplicated(['period','strategy','policy','leverage']).any():raise ValueError('unique production cases required')
    for row in production.to_dict('records'):
        factor=row['strategy']=='factor';policy=row['policy'] if factor else 'no_sleeve';passive=policy=='passive_debt'
        if passive:policy='no_sleeve'
        subset=levels.loc[row['start']:row['end'],sleeves if factor else [row['strategy']]]
        outcome,h,e=calculate(subset,reference,target if factor else [1.],row['leverage'],policy,
            initial_equity_usd=baseline['initial_equity_usd'],fee_parameters=baseline['fee_schedule'],margin=baseline['borrowing_margin_annual'],
            sleeve_band=baseline['sleeve_band'],leverage_band=baseline['leverage_band'],passive=passive)
        if len(h)!=row['observations'] or str(h.date.iloc[0].date())!=row['start'] or str(h.date.iloc[-1].date())!=row['end']:
            raise ValueError('independent case calendar differs')
        label=f"{row['period']}__{row['strategy']}__{row['policy']}__{row['leverage']:.2f}"
        checks.extend(comparison_rows(row,outcome,baseline,settings,label))
        records.append(dict(case_id=label,period=row['period'],strategy=row['strategy'],policy=row['policy'],leverage=row['leverage'],**outcome))
        histories.append(h.assign(case_id=label));events.append(e.assign(case_id=label))
        if row['period']=='full':
            name=f"full_factor_{row['policy']}_{row['leverage']:.2f}" if factor else f"full_{row['strategy']}_{row['leverage']:.2f}"
            expected=curves[name].to_numpy(float);actual=h.equity_usd.to_numpy(float)
            if not pd.DatetimeIndex(pd.to_datetime(curves.date)).equals(pd.DatetimeIndex(h.date)):
                raise ValueError('common full wealth dates differ')
            limits=baseline['reconciliation_tolerances']['account_usd_atol']+baseline['reconciliation_tolerances']['account_rtol']*np.abs(expected)
            wealth.append(dict(case_id=label,observations=len(actual),maximum_equity_difference_usd=float(np.abs(expected-actual).max()),all_dates_passed=bool((np.abs(expected-actual)<=limits).all())))
    return dict(metrics=pd.DataFrame(records),histories=pd.concat(histories,ignore_index=True),events=pd.concat(events,ignore_index=True),checks=pd.DataFrame(checks),wealth=pd.DataFrame(wealth))


def run_independent_core(raw_root,baseline_path,sources_path,settings_path,output):
    output=Path(output)
    if output.exists():raise FileExistsError('choose a new independent-core output directory')
    paths=[baseline_path,sources_path,settings_path];captured={Path(p).name:Path(p).read_bytes() for p in paths}
    if len(captured)!=3:raise ValueError('distinct configuration filenames required')
    baseline=json.loads(captured[Path(baseline_path).name]);settings=json.loads(captured[Path(settings_path).name]);validate_config(baseline);validate_settings(settings)
    output.mkdir(parents=True);(output/'config').mkdir()
    for name,data in captured.items():(output/'config'/name).write_bytes(data)
    code=source_hashes();manifest=dict(schema_version=1,run_id=str(uuid.uuid4()),status='running',figures_included=False,
        started_at_utc=datetime.now(timezone.utc).isoformat(),code=code,
        scope='First independent slice: 57 core cases/eight outcomes plus 19 full wealth curves. Shared admitted NAV/funding inputs; not full 625-run audit, independent data feed or risk-inference audit.',
        configuration_snapshots={f'config/{name}':sha256(output/'config'/name) for name in captured},artifacts={})
    write_json(output/'run_manifest.json',manifest)
    try:
        core=run_backtest_study(raw_root,output/'config'/Path(baseline_path).name,output/'config'/Path(sources_path).name,output/'core')
        levels=pd.read_csv(output/'core/inputs/common_nav_usd.csv',index_col=0,parse_dates=True)
        reference=pd.read_csv(output/'core/inputs/canonical/daily_borrow_rates_usd.csv',index_col=0,parse_dates=True).reference_rate_annual
        production=pd.read_csv(output/'core/results/policy_metrics.csv',float_precision='round_trip');curves=pd.read_csv(output/'core/results/equity_curves.csv',float_precision='round_trip')
        result=reconcile_core(levels,reference,production,curves,baseline,settings)
        for key,name in [('metrics','independent_metrics.csv'),('histories','independent_histories.csv'),('events','independent_events.csv'),('checks','independent_comparisons.csv'),('wealth','full_wealth_checks.csv')]:result[key].to_csv(output/name,index=False,lineterminator='\n')
        passed=bool(result['checks'].passed.all() and result['wealth'].all_dates_passed.all())
        write_json(output/'independent_definitions.json',dict(settings=settings,baseline_tolerances=baseline['reconciliation_tolerances'],all_comparisons_passed=passed,
            implementation='Separate scalar positions/debt/cost/signal and eight-metric calculations; no production simulator/fee/metric imports and no runtime AST extraction.',
            limitations=['Shared frozen NAV/funding and model assumptions, not an independent daily price feed.',
                'Eight accounting/basic risk outcomes; alpha, HAC, Sharpe and other inference are not independently recomputed in this slice.',
                'Funding/entry/margin/grid/synthetic families from the original 625-run audit remain separate scope.']))
        if not passed:raise ValueError('independent core deviates beyond unchanged baseline tolerances; inspect retained comparisons')
        if len(result['metrics'])!=57 or len(result['wealth'])!=19:raise ValueError('complete declared 57-case/19-curve scope required')
        (output/'README.md').write_text('# Independent Core Accounting\n\n57 main cases, eight outcomes each, and all 19 full-period wealth curves against a separate scalar implementation. '
            'Shared admitted inputs/model assumptions; not a second price feed or complete replay of the old 625-run audit.\n\n'
            '[Outcomes](independent_metrics.csv) · [456 comparisons](independent_comparisons.csv) · [Full wealth checks](full_wealth_checks.csv) · '
            '[Scalar accounts](independent_histories.csv) · [Scalar events](independent_events.csv) · [Scope](independent_definitions.json) · [Fresh core](core/README.md) · [Manifest](run_manifest.json)\n')
        if source_hashes()!=code:raise RuntimeError('source changed during independent core')
        manifest['artifacts']={str(p.relative_to(output)):sha256(p) for p in sorted(output.rglob('*')) if p.is_file() and p!=output/'run_manifest.json' and p.relative_to(output).parts[0]!='config'}
        manifest.update(status='complete',finished_at_utc=datetime.now(timezone.utc).isoformat(),raw_sources=core['raw_sources'],
            counts=dict(independent_cases=len(result['metrics']),outcome_comparisons=len(result['checks']),full_wealth_curves=len(result['wealth']),scalar_history_rows=len(result['histories']),all_comparisons_passed=passed))
        write_json(output/'run_manifest.json',manifest);verify_run(output)
    except Exception as error:
        manifest.update(status='failed',failure=dict(type=type(error).__name__,message=str(error)));write_json(output/'run_manifest.json',manifest);raise
    return manifest


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--raw-root',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    for key,name in [('baseline','backtest_absolute_decoupled_2026-10-05.json'),('sources','backtest_sources.json'),('settings','independent_core_2026-10-05.json')]:p.add_argument('--'+key,type=Path,default=Path('config')/name)
    a=p.parse_args();m=run_independent_core(a.raw_root,a.baseline,a.sources,a.settings,a.output);print(json.dumps(dict(run_id=m['run_id'],status=m['status'],counts=m['counts']),indent=2))


if __name__=='__main__':main()
