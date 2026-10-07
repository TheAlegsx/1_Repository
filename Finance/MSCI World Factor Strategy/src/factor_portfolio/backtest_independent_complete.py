"""Reproduce and independently check all original 625 accounting cases and extensions."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gzip
import io
import json
from pathlib import Path
import uuid

import numpy as np
import pandas as pd

from .backtest_independent_core import run_independent_core, comparison_rows, validate_settings
from .backtest_independent_funding import run_independent_funding, NAMES as FUNDING_NAMES
from .backtest_hindsight import run_hindsight
from .backtest_workflow import run_backtest_study
from .independent_scalar import calculate
from .independent_validation import raw_source_checks, risk_statistics, RISK_FIELDS
from .inflow_workflow import sha256, source_hashes, verify_run, write_json

CORE_SETTINGS = 'independent_core_2026-10-05.json'
ENTRY = 'backtest_entries_absolute_decoupled_2026-10-05.json'
MARGIN = 'backtest_margin_absolute_decoupled_2026-10-05.json'
SYNTHETIC = 'backtest_synthetic_absolute_decoupled_2026-10-05.json'
ROLLING = 'backtest_rolling_absolute_decoupled_2026-10-05.json'
GRID = 'backtest_legacy_hindsight_2026-10-05.json'
SETTINGS = 'independent_complete_2026-10-06.json'
NAMES = FUNDING_NAMES + [CORE_SETTINGS, ENTRY, MARGIN, SYNTHETIC, ROLLING, GRID, SETTINGS]
RETAINED = dict(main_policy_period=57, funding=60, fresh_entry=30, maintenance_margin=18,
    bounded_hindsight=300, synthetic=160)
KEYS = dict(entry=['requested_entry', 'strategy', 'leverage', 'policy'],
    margin=['variant', 'maintenance_ltv', 'extra_liquidation_spread'],
    grid=['scenario_id', 'leverage'], synthetic=['regime', 'strategy', 'leverage', 'total_borrow_rate'])


def validate_scope(settings):
    validate_settings(settings)
    if settings['retained_case_families'] != RETAINED or settings['expected_extended_cases'] != dict(entry=88, margin=24, grid=300, synthetic=224):
        raise ValueError('complete original and declared extended case scope required')


def case_definitions(baseline, entry, margin, grid, synthetic):
    """Declare cases from captured configurations, never select from expected outcomes."""
    weights = list(baseline['target_weights'].values()); sleeves = list(baseline['target_weights'])
    base = dict(weights=weights, columns=sleeves, policy=baseline['primary_policy'],
        margin=baseline['borrowing_margin_annual'], sleeve_band=baseline['sleeve_band'],
        leverage_band=baseline['leverage_band'], passive=False, maintenance=None, extra=0.)
    cases = []
    for start in entry['requested_starts']:
        for lev in entry['leverage_levels']:
            for strategy, policy in [('factor', p) for p in entry['factor_policies']] + [('core', 'leverage_managed'), ('dimensional', 'leverage_managed')]:
                factor = strategy == 'factor'
                cases.append(dict(**base, family='entry', key=(start, strategy, lev, policy),
                    leverage=lev, requested=start, retained=start in entry['legacy_reference_starts'] and (not factor or policy=='hybrid20'),
                    overrides=dict(policy=policy if factor else 'no_sleeve', columns=sleeves if factor else [strategy], weights=weights if factor else [1.])))
    for variant in margin['variants']:
        for limit in margin['maintenance_ltv']:
            for extra in margin['extra_liquidation_spreads']:
                cases.append(dict(**base, family='margin', key=(variant['id'], limit, extra), leverage=margin['target_leverage'],
                    retained=variant['policy']!='absolute_decoupled', overrides=dict(policy=variant['policy'], passive=variant['passive_debt'], maintenance=limit, extra=extra)))
    for lev in grid['leverage_levels']:
        for i, vector in enumerate(grid['weight_vectors'], start=1):
            for sb in grid['sleeve_bands']:
                for lb in grid['leverage_bands']:
                    name = f'W{i:02d}-SB{int(sb*100):02d}-LB{int(lb*100):02d}'
                    # The original producer reloaded its twelve-decimal definitions.
                    w = [float(f'{vector[s]:.12f}') for s in sleeves]
                    cases.append(dict(**base, family='grid', key=(name, lev), leverage=lev, retained=True,
                        overrides=dict(policy=grid['policy'], weights=w, sleeve_band=sb, leverage_band=lb)))
    for regime in synthetic['regimes']:
        for lev, rate in synthetic['exposure_funding_pairs']:
            for strategy in synthetic['strategies']:
                core = strategy['portfolio']=='core'
                cases.append(dict(**base, family='synthetic', key=(regime, strategy['id'], lev, rate), leverage=lev,
                    retained=strategy['id'] in synthetic['legacy_strategies'],
                    overrides=dict(policy=strategy['policy'], passive=strategy['passive_debt'], maintenance=strategy['maintenance_ltv'],
                        margin=rate-synthetic['reference_rate'], columns=['core'] if core else sleeves, weights=[1.] if core else weights)))
    for case in cases:
        case.update(case.pop('overrides'))
    return cases


def validate_case_tables(cases, tables):
    for family, columns in KEYS.items():
        table = tables[family]
        expected = {c['key'] for c in cases if c['family']==family}
        actual = set(table[columns].itertuples(index=False, name=None))
        if table.duplicated(columns).any() or actual != expected:
            raise ValueError('complete unique independent case grid required: '+family)
        if 'status' not in table or not table.status.eq('complete').all():
            raise ValueError('declared cases need complete production paths: '+family)


def account_checks(history, events, baseline):
    tolerance = baseline['reconciliation_tolerances']
    assets = history.gross_assets_usd.to_numpy(); equity = history.equity_usd.to_numpy()
    positions = history.filter(regex='^position_').sum(axis=1).to_numpy()
    errors = [np.abs(positions-assets), np.abs(assets-history.debt_usd.to_numpy()-equity)]
    if not np.isfinite(history.select_dtypes('number')).all().all() or (equity <= 0).any():
        raise ValueError('finite solvent independent accounts required')
    limits = tolerance['account_usd_atol'] + tolerance['account_rtol']*np.abs(assets)
    passed = all((x <= limits).all() for x in errors)
    fee_error = abs(events.fees_usd.sum()-history.cumulative_transaction_cost_usd.iloc[-1])
    funding_error = abs(history.financing_cost_usd.sum()-history.cumulative_financing_cost_usd.iloc[-1])
    for error, total in [(fee_error, history.cumulative_transaction_cost_usd.iloc[-1]), (funding_error, history.cumulative_financing_cost_usd.iloc[-1])]:
        passed = passed and error <= tolerance['account_usd_atol']+tolerance['account_rtol']*abs(total)
    return dict(observations=len(history), minimum_equity_usd=float(equity.min()), passed=bool(passed),
        maximum_position_identity_error_usd=float(errors[0].max()), maximum_equity_identity_error_usd=float(errors[1].max()),
        fee_reconciliation_error_usd=float(fee_error), funding_reconciliation_error_usd=float(funding_error))


def compare_event_paths(actual, expected, baseline):
    if len(actual)!=len(expected) or actual.date.tolist()!=pd.to_datetime(expected.date).tolist() or actual.reason.tolist()!=expected.reason.tolist():
        raise ValueError('independent event date/reason/count differs')
    errors = {}
    for field in ['fees_usd', 'gross_trade_usd']:
        gap = np.abs(actual[field].to_numpy()-expected[field].to_numpy())
        limits = baseline['reconciliation_tolerances']['account_usd_atol']+baseline['reconciliation_tolerances']['account_rtol']*np.abs(expected[field].to_numpy())
        if not (gap <= limits).all(): raise ValueError('independent trade values differ: '+field)
        errors[field] = float(gap.max()) if len(gap) else 0.
    return dict(events=len(actual), maximum_differences_usd=errors, passed=True)


def compare_artificial_daily(actual, saved, baseline):
    # The preserved producer attaches case metadata with assign(leverage=target),
    # overwriting its daily leverage column. Derive actual leverage from accounts.
    common=[c for c in actual if c not in ['date','pending_signal','leverage'] and actual[c].notna().all()]
    if pd.to_datetime(saved.date).tolist()!=actual.date.tolist():
        raise ValueError('independent artificial daily dates differ')
    gaps=np.abs(actual[common].to_numpy()-saved[common].to_numpy())
    limits=baseline['reconciliation_tolerances']['account_usd_atol']+baseline['reconciliation_tolerances']['account_rtol']*np.abs(saved[common].to_numpy())
    leverage_gap=np.abs(actual.leverage.to_numpy()-saved.gross_assets_usd.to_numpy()/saved.equity_usd.to_numpy())
    if (not (gaps<=limits).all() or not (leverage_gap<=baseline['reconciliation_tolerances']['metric_atol']).all()
        or actual.pending_signal.fillna('').tolist()!=saved.pending_signal.fillna('').tolist()):
        raise ValueError('independent artificial daily account/signal differs')
    return dict(observations=len(actual),numerical_fields=len(common)+1,maximum_account_difference_usd=float(gaps.max()),
        maximum_derived_leverage_difference=float(leverage_gap.max()),passed=True)


def scalar_families(output, config, baseline, settings):
    folder=output/'production'; levels=pd.read_csv(folder/'inputs/common_nav_usd.csv',index_col=0,parse_dates=True)
    reference=pd.read_csv(folder/'inputs/canonical/daily_borrow_rates_usd.csv',index_col=0,parse_dates=True).reference_rate_annual
    tables={f:pd.read_csv(output/name,float_precision='round_trip') for f,name in dict(entry='production/results/fresh_entry_metrics.csv',
        margin='production/results/margin_metrics.csv',grid='hindsight/hindsight_grid.csv',synthetic='production/synthetic/synthetic_metrics.csv').items()}
    cases=case_definitions(baseline,config[ENTRY],config[MARGIN],config[GRID],config[SYNTHETIC]); validate_case_tables(cases,tables)
    indexed={f:t.set_index(KEYS[f]) for f,t in tables.items()}
    artificial=pd.read_csv(folder/'synthetic/synthetic_levels.csv',parse_dates=['date'])
    paths={name:g.set_index('date')[list(baseline['target_weights'])] for name,g in artificial.groupby('regime',sort=False)}
    synthetic_reference=pd.Series(config[SYNTHETIC]['reference_rate'],index=pd.date_range(artificial.date.min(),artificial.date.max()))
    margin_events=pd.read_csv(folder/'results/margin_events.csv',parse_dates=['date'],float_precision='round_trip')
    grid_events=pd.read_csv(output/'hindsight/grid_events.csv',parse_dates=['date'],float_precision='round_trip')
    synthetic_events=pd.read_csv(folder/'synthetic/synthetic_events.csv',parse_dates=['date'],float_precision='round_trip')
    synthetic_histories=pd.read_csv(folder/'synthetic/synthetic_histories.csv',parse_dates=['date'],float_precision='round_trip')
    grouped_events={k:g for k,g in synthetic_events.groupby(KEYS['synthetic'],sort=False)}
    grouped_histories={k:g for k,g in synthetic_histories.groupby(KEYS['synthetic'],sort=False)}
    checks=[]; metrics=[]; accounts=[]; event_checks=[]; path_checks=[]; event_rows=[]
    with (output/'scalar_accounts.csv.gz').open('wb') as raw, gzip.GzipFile(filename='',mode='wb',fileobj=raw,mtime=0) as binary:
        with io.TextIOWrapper(binary,encoding='utf-8',newline='') as text:
            for i,case in enumerate(cases):
                family,key=case['family'],case['key']; expected=indexed[family].loc[key].to_dict()
                subset=paths[key[0]][case['columns']] if family=='synthetic' else levels.loc[case.get('requested',baseline['periods']['full']['start']):baseline['periods']['full']['end'],case['columns']]
                if len(subset)!=expected['observations'] or str(subset.index[0].date())!=expected['start'] or str(subset.index[-1].date())!=expected['end']:
                    raise ValueError('independently selected first-common-NAV calendar differs')
                if family=='grid':
                    if any(expected[f'{s}_weight']!=w for s,w in zip(case['columns'],case['weights'])) or expected['sleeve_band']!=case['sleeve_band'] or expected['leverage_band']!=case['leverage_band']:
                        raise ValueError('independent grid definitions differ')
                outcome,h,e=calculate(subset,synthetic_reference if family=='synthetic' else reference,case['weights'],case['leverage'],case['policy'],
                    initial_equity_usd=baseline['initial_equity_usd'],fee_parameters=baseline['fee_schedule'],margin=case['margin'],sleeve_band=case['sleeve_band'],
                    leverage_band=case['leverage_band'],passive=case['passive'],maintenance=case['maintenance'],extra=case['extra'])
                label=family+'__'+'__'.join(map(str,key)); checks.extend(comparison_rows(expected,outcome,baseline,settings,label))
                metrics.append(dict(case_id=label,family=family,retained=case['retained'],**outcome));accounts.append(dict(case_id=label,**account_checks(h,e,baseline)))
                h=h.reindex(columns=['date','equity_usd','gross_assets_usd','debt_usd','leverage','transaction_cost_usd','financing_cost_usd',
                    'cumulative_transaction_cost_usd','cumulative_financing_cost_usd','pending_signal']+[f'position_{s}_usd' for s in levels.columns])
                h.assign(case_id=label).to_csv(text,index=False,header=i==0,float_format='%.17g',lineterminator='\n')
                event_rows.append(e.assign(case_id=label))
                expected_events=None
                if family=='margin': expected_events=margin_events[margin_events.variant.eq(key[0]) & margin_events.run_id.eq(f'{case["policy"]}_passive{case["passive"]}_ltv{key[1]}_extra{key[2]}')]
                elif family=='grid': expected_events=grid_events[grid_events.run_id.eq(f'{key[1]:.2f}__{key[0]}')]
                elif family=='synthetic': expected_events=grouped_events[key]
                if expected_events is not None: event_checks.append(dict(case_id=label,**compare_event_paths(e,expected_events,baseline)))
                if family=='synthetic':
                    path_checks.append(dict(case_id=label,**compare_artificial_daily(h,grouped_histories[key],baseline)))
                if (i+1)%100==0: print(f'Independent additional cases {i+1}/{len(cases)}',flush=True)
    for name,records in [('additional_metrics',metrics),('additional_comparisons',checks),('account_checks',accounts),('event_checks',event_checks),('synthetic_path_checks',path_checks)]:
        pd.DataFrame(records).to_csv(output/(name+'.csv'),index=False,lineterminator='\n')
    pd.concat(event_rows,ignore_index=True).to_csv(output/'scalar_events.csv',index=False,lineterminator='\n')
    if not all(c['passed'] for c in checks+accounts): raise ValueError('independent additional cases exceed unchanged tolerances')
    return dict(cases=len(cases), comparisons=len(checks), account_rows=sum(c['observations'] for c in accounts),
        retained={f:sum(c['family']==f and c['retained'] for c in cases) for f in KEYS},synthetic_daily_paths=len(path_checks),event_paths=len(event_checks))


def risk_and_rolling(output,baseline,settings):
    core=output/'main/core';table=pd.read_csv(core/'results/policy_metrics.csv',float_precision='round_trip')
    histories=pd.read_csv(output/'main/independent_histories.csv',parse_dates=['date'],float_precision='round_trip')
    full={k:g.set_index('date').equity_usd for k,g in histories.groupby('case_id',sort=False) if k.startswith('full__')}
    market=full['full__core__leverage_managed__1.00'];ref=pd.read_csv(core/'inputs/canonical/daily_borrow_rates_usd.csv',index_col=0,parse_dates=True).reference_rate_annual
    checks=[];risk=[]
    for row in table[table.period.eq('full')].to_dict('records'):
        label=f'full__{row["strategy"]}__{row["policy"]}__{row["leverage"]:.2f}'
        values=risk_statistics(full[label],market,ref,baseline['initial_equity_usd']);risk.append(dict(case_id=label,**values))
        for field in RISK_FIELDS:
            a,b=float(row[field]),float(values[field]);limit=baseline['reconciliation_tolerances']['account_usd_atol']+baseline['reconciliation_tolerances']['account_rtol']*abs(a) if field=='ending_equity_usd' else baseline['reconciliation_tolerances']['metric_atol']
            checks.append(dict(case_id=label,field=field,production_value=a,independent_value=b,absolute_difference=abs(a-b),allowed_difference=limit,passed=abs(a-b)<=limit))
    rolling=pd.read_csv(output/'production/results/rolling_monthly_vs_core.csv',parse_dates=['start','end'],float_precision='round_trip');windows=[]
    for row in rolling.to_dict('records'):
        a=full[f'full__factor__{row["policy"]}__{row["leverage"]:.2f}'].loc[row['start']:row['end']].to_numpy()
        b=full[f'full__core__leverage_managed__{row["leverage"]:.2f}'].loc[row['start']:row['end']].to_numpy()
        years=(row['end']-row['start']).days/365.2425
        values=dict(cagr_difference=(a[-1]/a[0])**(1/years)-(b[-1]/b[0])**(1/years),
            volatility_difference=(np.std(a[1:]/a[:-1]-1,ddof=1)-np.std(b[1:]/b[:-1]-1,ddof=1))*np.sqrt(252),
            drawdown_difference=(a/np.maximum.accumulate(a)-1).min()-(b/np.maximum.accumulate(b)-1).min())
        for field,value in values.items():
            error=abs(row[field]-value); windows.append(dict(policy=row['policy'],leverage=row['leverage'],horizon_years=row['horizon_years'],
                start=row['start'],end=row['end'],field=field,absolute_difference=error,passed=error<=baseline['reconciliation_tolerances']['metric_atol']))
    pd.DataFrame(risk).to_csv(output/'independent_risk_metrics.csv',index=False,lineterminator='\n')
    pd.DataFrame(checks).to_csv(output/'risk_comparisons.csv',index=False,lineterminator='\n')
    pd.DataFrame(windows).to_csv(output/'rolling_comparisons.csv',index=False,lineterminator='\n')
    if len(risk)!=19 or len(rolling)!=1284 or not all(c['passed'] for c in checks+windows): raise ValueError('independent risk/rolling scope failed')
    return dict(full_risk_paths=19,risk_fields_per_path=13,risk_comparisons=len(checks),monthly_rolling_windows=len(rolling),rolling_comparisons=len(windows))


def run_complete(raw_root,config_dir,output):
    output=Path(output);config_dir=Path(config_dir)
    if output.exists(): raise FileExistsError('choose a new independent complete output directory')
    captured={n:(config_dir/n).read_bytes() for n in NAMES};config={n:json.loads(data) for n,data in captured.items()};settings=config[SETTINGS];validate_scope(settings);baseline=config[NAMES[0]]
    output.mkdir(parents=True);(output/'config').mkdir()
    for name,data in captured.items(): (output/'config'/name).write_bytes(data)
    code=source_hashes();manifest=dict(schema_version=1,run_id=str(uuid.uuid4()),status='running',figures_included=False,
        started_at_utc=datetime.now(timezone.utc).isoformat(),code=code,configuration_snapshots={f'config/{n}':sha256(output/'config'/n) for n in NAMES},artifacts={},
        scope='All original 625 eight-outcome accounting labels plus 188 additional current labels; independent main risk/raw-source/rolling checks. Shared sources and conventions; not all evidence of the original broader pre-editorial audit.')
    write_json(output/'run_manifest.json',manifest)
    try:
        cp=output/'config'
        print('Rebuilding main and financing independent checks',flush=True)
        main=run_independent_core(raw_root,cp/NAMES[0],cp/NAMES[2],cp/CORE_SETTINGS,output/'main')
        funding=run_independent_funding(raw_root,cp,output/'funding')
        print('Rebuilding entry, margin, artificial and rolling production',flush=True)
        production=run_backtest_study(raw_root,cp/NAMES[0],cp/NAMES[2],output/'production',entry_config_path=cp/ENTRY,
            margin_config_path=cp/MARGIN,synthetic_config_path=cp/SYNTHETIC,rolling_config_path=cp/ROLLING)
        print('Rebuilding original bounded grid production',flush=True)
        grid=run_hindsight(raw_root,cp/NAMES[0],cp/NAMES[2],cp/GRID,output/'hindsight')
        if any(m['raw_sources']!=main['raw_sources'] for m in [funding,production,grid]): raise ValueError('audit branches use different raw snapshots')
        levels=pd.read_csv(output/'main/core/inputs/common_nav_usd.csv',index_col=0,parse_dates=True)
        ref=pd.read_csv(output/'main/core/inputs/canonical/daily_borrow_rates_usd.csv',index_col=0,parse_dates=True).reference_rate_annual
        raw_checks=raw_source_checks(raw_root,config[NAMES[2]],levels,ref);write_json(output/'raw_source_checks.json',raw_checks)
        additional=scalar_families(output,config,baseline,settings);risk=risk_and_rolling(output,baseline,settings)
        retained=dict(main_policy_period=main['counts']['independent_cases'],funding=funding['counts']['old_audit_cases_added'],
            fresh_entry=additional['retained']['entry'],maintenance_margin=additional['retained']['margin'],bounded_hindsight=additional['retained']['grid'],synthetic=additional['retained']['synthetic'])
        if retained!=RETAINED or sum(retained.values())!=625: raise ValueError('complete original audit family coverage required')
        all_metrics=[];all_checks=[]
        for path,family,retained_label in [('main/independent_metrics.csv','main',True),('funding/independent_funding_metrics.csv','funding',None),('additional_metrics.csv',None,None)]:
            t=pd.read_csv(output/path,float_precision='round_trip')
            if family: t['family']=family
            if retained_label is True: t['retained']=True
            elif family=='funding': t['retained']=t.branch.eq('legacy')
            all_metrics.append(t)
        for path in ['main/independent_comparisons.csv','funding/independent_funding_comparisons.csv','additional_comparisons.csv']: all_checks.append(pd.read_csv(output/path,float_precision='round_trip'))
        metrics=pd.concat(all_metrics,ignore_index=True);checks=pd.concat(all_checks,ignore_index=True)
        if len(metrics)!=813 or metrics.case_id.duplicated().any() or not checks.passed.all(): raise ValueError('combined independent audit coverage or checks failed')
        metrics.to_csv(output/'all_independent_metrics.csv',index=False,lineterminator='\n');checks.to_csv(output/'all_outcome_comparisons.csv',index=False,lineterminator='\n')
        counts=dict(retained_case_families=retained,retained_labels=625,additional_labels=188,total_labels=813,outcome_comparisons=len(checks),
            additional_scalar_account_rows=additional['account_rows'],event_paths=additional['event_paths'],synthetic_daily_paths=additional['synthetic_daily_paths'],**risk)
        write_json(output/'coverage.json',dict(all_comparisons_passed=True,counts=counts,source_reader_checks=raw_checks,
            limitations=['Same frozen source observations and declared model conventions; no independent complete daily price feed.',
                '625 parameter/run labels include duplicates and overlapping horizons, not independent samples or future validation.',
                'This closes the original eight-outcome engine family audit plus declared source/risk/rolling checks, not every narrative or all broader pre-editorial evidence.',
                'Fresh dependency installation, coordinated reports and publication remain separate work.']))
        (output/'README.md').write_text('# Complete Independent Accounting Check\n\nAll original 625 eight-outcome case labels and 188 additional current labels pass unchanged tolerances. '
            'Independent source readers, nineteen thirteen-field risk calculations and 1,284 monthly rolling windows also reconcile.\n\n'
            '[Coverage](coverage.json) · [All outcomes](all_independent_metrics.csv) · [All comparisons](all_outcome_comparisons.csv) · '
            '[Additional scalar accounts](scalar_accounts.csv.gz) · [Risk](risk_comparisons.csv) · [Raw sources](raw_source_checks.json) · [Manifest](run_manifest.json)\n')
        if source_hashes()!=code: raise RuntimeError('source changed during complete independent check')
        manifest['artifacts']={str(p.relative_to(output)):sha256(p) for p in sorted(output.rglob('*')) if p.is_file() and p!=output/'run_manifest.json' and p.relative_to(output).parts[0]!='config'}
        manifest.update(status='complete',finished_at_utc=datetime.now(timezone.utc).isoformat(),raw_sources=main['raw_sources'],counts=counts)
        write_json(output/'run_manifest.json',manifest);verify_run(output)
    except Exception as error:
        manifest.update(status='failed',failure=dict(type=type(error).__name__,message=str(error)));write_json(output/'run_manifest.json',manifest);raise
    return manifest


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--raw-root',type=Path,required=True)
    parser.add_argument('--config-dir',type=Path,default=Path('config'));parser.add_argument('--output',type=Path,required=True);a=parser.parse_args()
    m=run_complete(a.raw_root,a.config_dir,a.output);print(json.dumps(dict(run_id=m['run_id'],status=m['status'],counts=m['counts']),indent=2))


if __name__=='__main__': main()
