"""Historical financing crossing scan and separate static fee-aware gap cures."""
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
from .independent_gap_cure import solve_gap
from .inflow_workflow import sha256, source_hashes, verify_run, write_json

SCAN_COLUMNS=['margin_bps','cagr_difference','trades']
CROSS_COLUMNS=['bracket_low_bps','bracket_high_bps','crossing_bps','residual_cagr_difference','type','left_difference','right_difference']
GAP_COLUMNS=['maintenance_ltv','gap_loss','post_gap_equity','status','cure_sale_usd','liquidation_cost_usd','post_cure_debt_usd']


def validate_settings(settings,baseline):
    validate_config(baseline);validate_independent(settings)
    expected=dict(period='full',target_leverage=1.25,factor_policies=['hybrid20','absolute_decoupled'],
        scan_low_bps=0,scan_high_bps=1000,scan_step_bps=10,refinement_iterations=25,
        approximate_zero_residual=1e-6,base_cagr_decimal_places=12,maintenance_ltv=[.25,.4,.6],
        gap_losses=[.2,.4,.6,.8,.85],liquidation_extra_spread=.01,fee_iterations=100,fee_convergence_usd=1e-8)
    if any(settings.get(k)!=v for k,v in expected.items()):
        raise ValueError('preserved ten-bp scan, 25 refinements and fifteen gap-cure settings required')
    if (baseline['primary_policy']!='absolute_decoupled' or baseline['primary_leverage']!=1.25
        or baseline['initial_equity_usd']!=7000000 or list(baseline['target_weights'].values())!=[.6,.15,.1,.15]):
        raise ValueError('fixed research capital, weights and primary policy required')


def crossing_scan(difference,points,iterations=25,residual_limit=1e-6):
    """Retain the old finite grid/local protocol; it does not imply continuity."""
    points=list(points)
    if (len(points)<2 or not all(math.isfinite(x) for x in points)
        or any(b<=a for a,b in zip(points[:-1],points[1:])) or type(iterations) is not int or iterations<=0
        or not math.isfinite(residual_limit) or residual_limit<=0):raise ValueError('invalid scan grid/refinement')
    def diff(x):
        v=float(difference(x))
        if not math.isfinite(v):raise ValueError('nonfinite scan difference')
        return v
    values=[diff(x) for x in points];rows=[]
    for a,z,fa,fz in zip(points[:-1],points[1:],values[:-1],values[1:]):
        if fa*fz>0:continue
        lo,hi=float(a),float(z)
        for _ in range(iterations):
            mid=(lo+hi)/2;fm=diff(mid)
            if fm*diff(lo)>0:lo=mid
            else:hi=mid
        bp=(lo+hi)/2;residual=diff(bp)
        rows.append(dict(bracket_low_bps=a,bracket_high_bps=z,crossing_bps=bp,
            residual_cagr_difference=residual,type='approximate_zero' if abs(residual)<residual_limit else 'policy_discontinuity',
            left_difference=diff(lo),right_difference=diff(hi)))
    return pd.DataFrame(rows,columns=CROSS_COLUMNS)


def gap_cure(capital,maintenance,loss,weights,leverage,fee,extra,*,iterations=100,tolerance=1e-8):
    if (not all(math.isfinite(x) for x in [capital,maintenance,loss,leverage,extra,*weights,tolerance])
        or capital<=0 or not 0<maintenance<1 or not 0<=loss<1 or leverage<1 or extra<0
        or not weights or min(weights)<=0 or abs(sum(weights)-1)>1e-10
        or type(iterations) is not int or iterations<=0 or tolerance<=0):raise ValueError('invalid gap-cure inputs')
    original=capital/(1-maintenance);debt=original*maintenance;assets=original*(1-loss);equity=assets-debt
    row=dict(maintenance_ltv=maintenance,gap_loss=loss,post_gap_equity=equity,status='insolvent_before_cure',
        cure_sale_usd=None,liquidation_cost_usd=None,post_cure_debt_usd=None)
    if equity<=0:return row
    charge=0.
    for _ in range(iterations):
        sale=max(assets-leverage*(equity-charge),0.)
        new=sum(fee.cost(sale*w) for w in weights)+sale*extra
        if not math.isfinite(new):raise ArithmeticError('nonfinite liquidation charge')
        if abs(new-charge)<tolerance:charge=new;break
        charge=new
    else:raise ArithmeticError('liquidation fee convergence failed')
    row['cure_sale_usd']=sale
    if equity-charge<=0:return dict(row,status='insolvent_after_liquidation_costs')
    return dict(row,status='cured_at_assumed_next_NAV',liquidation_cost_usd=charge,
        post_cure_debt_usd=(leverage-1)*(equity-charge))


def gap_comparison(baseline,settings):
    weights=list(baseline['target_weights'].values());capital=baseline['initial_equity_usd'];leverage=settings['target_leverage']
    fee=SwissquoteStandardFeeSchedule(**baseline['fee_schedule']);rows=[];other=[];checks=[]
    tol=baseline['reconciliation_tolerances']
    for maintenance in settings['maintenance_ltv']:
        for loss in settings['gap_losses']:
            row=gap_cure(capital,maintenance,loss,weights,leverage,fee,settings['liquidation_extra_spread'],
                iterations=settings['fee_iterations'],tolerance=settings['fee_convergence_usd']);rows.append(row)
            independent=solve_gap(capital,maintenance,loss,weights,leverage,baseline['fee_schedule'],settings['liquidation_extra_spread'])
            other.append(dict(maintenance_ltv=maintenance,gap_loss=loss,**independent))
            status_match=row['status']==independent['status'];maxgap=0.;passed=status_match
            for field in GAP_COLUMNS[2:]:
                if field=='status':continue
                a,b=row[field],independent[field]
                if a is None or b is None:passed=passed and a is None and b is None;continue
                delta=abs(a-b);maxgap=max(maxgap,delta);passed=passed and delta<=tol['account_usd_atol']+tol['account_rtol']*abs(a)
            assets=capital/(1-maintenance)*(1-loss);debt=capital/(1-maintenance)*maintenance
            residual=None;actual_leverage=None;funding_residual=None;ordinary_cost=None;extra_cost=None
            if row['status']=='cured_at_assumed_next_NAV':
                sale,cost,newdebt=row['cure_sale_usd'],row['liquidation_cost_usd'],row['post_cure_debt_usd']
                neweq=row['post_gap_equity']-cost
                residual=(assets-sale)-(debt-sale+cost)-neweq
                funding_residual=debt-sale+cost-newdebt;actual_leverage=(assets-sale)/neweq
                ordinary_cost=sum(fee.cost(sale*w) for w in weights);extra_cost=sale*settings['liquidation_extra_spread']
                limit=tol['account_usd_atol']+tol['account_rtol']*abs(assets)
                passed=passed and (neweq>0 and 0<=sale<=assets and abs(residual)<=limit and abs(funding_residual)<=limit
                    and abs(actual_leverage-leverage)<=tol['metric_atol'] and abs(cost-ordinary_cost-extra_cost)<=limit)
            checks.append(dict(maintenance_ltv=maintenance,gap_loss=loss,status_match=status_match,
                maximum_independent_difference_usd=maxgap,balance_residual_usd=residual,debt_residual_usd=funding_residual,
                post_cure_leverage=actual_leverage,ordinary_trade_cost_usd=ordinary_cost,extra_liquidation_cost_usd=extra_cost,
                external_cash_usd=0.,passed=bool(passed)))
    if not all(x['passed'] for x in checks):raise ValueError('independent gap cure or self-financing identities differ')
    return dict(gaps=pd.DataFrame(rows,columns=GAP_COLUMNS),independent_gaps=pd.DataFrame(other,columns=GAP_COLUMNS),gap_checks=pd.DataFrame(checks))


def funding_comparison(returns,reference,levels,base_table,baseline,settings):
    validate_settings(settings,baseline);bounds=baseline['periods']['full'];ret=returns.loc[bounds['start']:bounds['end']].copy()
    if len(ret)<4 or str(ret.index[0].date())!=bounds['start'] or str(ret.index[-1].date())!=bounds['end']:
        raise ValueError('complete configured scan calendar required')
    ret.iloc[0]=0.;sleeves=list(baseline['target_weights']);weights=list(baseline['target_weights'].values());nav=levels.loc[ret.index,sleeves]
    shared=dict(initial_equity_usd=baseline['initial_equity_usd'],sleeve_band=baseline['sleeve_band'],leverage_band=baseline['leverage_band'])
    fee=SwissquoteStandardFeeSchedule(**baseline['fee_schedule']);market=simulate(ret[['core']],reference,[1.],1.,'no_sleeve',fee_schedule=fee,**shared)
    records=[];independent_records=[];checks=[];path_checks=[];scans=[];crossings=[];bases=[]
    for policy in settings['factor_policies']:
        subset=base_table[base_table.period.eq('full')&base_table.strategy.eq('factor')&base_table.policy.eq(policy)&base_table.leverage.eq(1.)]
        if len(subset)!=1:raise ValueError('unique freshly generated unlevered policy baseline required')
        base=float(subset.cagr.iloc[0]);base_outcome,h,e=calculate(nav,reference,weights,1.,policy,
            fee_parameters=baseline['fee_schedule'],margin=baseline['borrowing_margin_annual'],**shared)
        # The archived scan used the twelve-decimal main CSV, not an unrounded CAGR.
        scalar_base=float(f"{base_outcome['cagr']:.12f}")
        if abs(scalar_base-base)>baseline['reconciliation_tolerances']['metric_atol']:raise ValueError('independent unlevered base differs')
        bases.append(dict(policy=policy,cagr_from_fresh_twelve_decimal_core=base,independent_twelve_decimal_cagr=scalar_base))
        checks.extend(comparison_rows(subset.iloc[0].to_dict(),base_outcome,baseline,settings,policy+'__unlevered'))
        cache={};scalar_cache={}
        def difference(bp):
            if bp not in cache:
                run=simulate(ret[sleeves],reference,weights,settings['target_leverage'],policy,margin=bp/10000,fee_schedule=fee,**shared)
                if run.status!='complete':raise ArithmeticError('incomplete funding scan account')
                outcome=metrics(run,reference,market,weights)
                scalar,h,e=calculate(nav,reference,weights,settings['target_leverage'],policy,margin=bp/10000,
                    fee_parameters=baseline['fee_schedule'],**shared)
                label=f'{policy}__{bp:.17g}';meta=dict(case_id=label,policy=policy,margin_bps=bp)
                records.append(dict(**meta,**{k:outcome[k] for k in settings['comparison_fields']}))
                independent_records.append(dict(**meta,**scalar));checks.extend(comparison_rows(outcome,scalar,baseline,settings,label))
                account=account_checks(h,e,baseline);events=compare_event_paths(e,run.events,baseline)
                cols=['equity_usd','gross_assets_usd','debt_usd','transaction_cost_usd','financing_cost_usd',
                    'cumulative_transaction_cost_usd','cumulative_financing_cost_usd']+[f'position_{s}_usd' for s in sleeves]
                expected=run.history[cols].to_numpy();gap=np.abs(expected-h[cols].to_numpy());tol=baseline['reconciliation_tolerances']
                leverage_error=float(np.abs(h.leverage.to_numpy()-run.history.leverage.to_numpy()).max())
                passed=bool((gap<=tol['account_usd_atol']+tol['account_rtol']*np.abs(expected)).all()
                    and leverage_error<=tol['metric_atol'] and account['passed'])
                if h.date.tolist()!=run.history.index.tolist() or h.pending_signal.tolist()!=run.history.pending_signal.tolist():
                    raise ValueError('scan dates or next-observation signals differ')
                path_checks.append(dict(**meta,**account,matched_events=events['events'],
                    maximum_account_difference_usd=float(gap.max()),maximum_leverage_difference=leverage_error,daily_path_passed=passed))
                cache[bp]=(outcome['cagr']-base,int(len(run.events)-1))
                scalar_cache[bp]=(scalar['cagr']-scalar_base,scalar['trades_after_entry'])
            return cache[bp][0]
        points=np.arange(settings['scan_low_bps'],settings['scan_high_bps']+1,settings['scan_step_bps'],dtype=float)
        crossing=crossing_scan(difference,points,settings['refinement_iterations'],settings['approximate_zero_residual'])
        crossing['independent_residual']=[scalar_cache[x][0] for x in crossing.crossing_bps]
        crossing['independent_type']=['approximate_zero' if abs(x)<settings['approximate_zero_residual'] else 'policy_discontinuity' for x in crossing.independent_residual]
        if not (crossing.type==crossing.independent_type).all():raise ValueError('independent residual classification differs')
        crossings.append(crossing.assign(policy=policy))
        scans.append(pd.DataFrame([dict(margin_bps=k,cagr_difference=v[0],trades=v[1],
            independent_cagr_difference=scalar_cache[k][0],independent_trades=scalar_cache[k][1],policy=policy) for k,v in sorted(cache.items())]))
    if not all(x['passed'] for x in checks) or not all(x['daily_path_passed'] for x in path_checks):
        raise ValueError('funding scan comparison exceeds unchanged tolerances')
    return dict(scan=pd.concat(scans,ignore_index=True),crossings=pd.concat(crossings,ignore_index=True),
        metrics=pd.DataFrame(records),independent_metrics=pd.DataFrame(independent_records),comparisons=pd.DataFrame(checks),
        paths=pd.DataFrame(path_checks),bases=pd.DataFrame(bases))


def run_funding_scan_gap(raw_root,baseline_path,sources_path,settings_path,output):
    output=Path(output)
    if output.exists():raise FileExistsError('choose a new scan/gap output directory')
    paths=[baseline_path,sources_path,settings_path];captured={Path(p).name:Path(p).read_bytes() for p in paths}
    if len(captured)!=3:raise ValueError('distinct configuration filenames required')
    baseline,spec,settings=[json.loads(captured[Path(p).name]) for p in paths];validate_settings(settings,baseline)
    output.mkdir(parents=True);(output/'config').mkdir()
    for name,data in captured.items():(output/'config'/name).write_bytes(data)
    code=source_hashes();manifest=dict(schema_version=1,run_id=str(uuid.uuid4()),status='running',figures_included=False,
        started_at_utc=datetime.now(timezone.utc).isoformat(),code=code,
        configuration_snapshots={f'config/{n}':sha256(output/'config'/n) for n in captured},artifacts={},
        scope='Both policies: 101-point funding scan plus 25-step sign-bracket refinement. Separate shared fifteen static fee-aware price-gap cures; no historic lender account or global zero enumeration.')
    write_json(output/'run_manifest.json',manifest)
    try:
        cp=output/'config';core=run_backtest_study(raw_root,cp/Path(baseline_path).name,cp/Path(sources_path).name,output/'core')
        fresh=output/'scan_inputs';fresh.mkdir();returns,reference=prepare_inputs(raw_root,admit_sources(raw_root,spec),spec,baseline,fresh)
        levels=pd.read_csv(fresh/'inputs/common_nav_usd.csv',index_col=0,parse_dates=True)
        # Match the original saved-core CSV parsing boundary exactly.
        base_table=pd.read_csv(output/'core/results/policy_metrics.csv')
        result=funding_comparison(returns,reference,levels,base_table,baseline,settings);result.update(gap_comparison(baseline,settings))
        for key,name in dict(scan='funding_scan.csv',crossings='funding_crossings.csv',metrics='scan_account_metrics.csv',
            independent_metrics='independent_scan_account_metrics.csv',comparisons='independent_comparisons.csv',paths='daily_path_checks.csv',
            bases='unlevered_cagr_bases.csv',gaps='gap_cure_metrics.csv',independent_gaps='independent_gap_cures.csv',gap_checks='gap_cure_checks.csv').items():
            result[key].to_csv(output/name,index=False,lineterminator='\n')
        result['scan'][result['scan'].policy.eq('hybrid20')][SCAN_COLUMNS].to_csv(output/'legacy_funding_scan.csv',index=False,float_format='%.12f')
        result['crossings'][result['crossings'].policy.eq('hybrid20')][CROSS_COLUMNS].to_csv(output/'legacy_funding_crossings.csv',index=False,float_format='%.12f')
        result['gaps'].to_csv(output/'legacy_gap_cure_metrics.csv',index=False,float_format='%.12f')
        counts=dict(scanned_account_cases=len(result['metrics']),independent_outcomes=len(result['comparisons']),
            daily_rows=int(result['paths'].observations.sum()),gap_cases=len(result['gaps']),cured=int(result['gaps'].status.eq('cured_at_assumed_next_NAV').sum()))
        summaries={p:dict(evaluations=len(result['scan'][result['scan'].policy.eq(p)]),
            crossings=result['crossings'][result['crossings'].policy.eq(p)][CROSS_COLUMNS].to_dict('records')) for p in settings['factor_policies']}
        write_json(output/'diagnostic_summary.json',dict(counts=counts,policies=summaries,settings=settings,
            limitations=['Crossover compares levered factor to its own unlevered rule; not Core, an approved borrowing cap or a forecast.',
                'Ten-bp grid can miss narrower sign changes and tangencies. Refinement classification is residual-based, not a continuity proof.',
                'Independent scalar verifies every production cache point and residual class; no independently selected search brackets or second price feed.',
                'Unlevered base uses fresh main CSV twelve-decimal precision as in the retained scan; endpoints and fee/event discontinuities remain explicit.',
                'Fifteen uniform instantaneous losses start at hypothetical maintenance boundaries; shared pro-rata cure geometry is not policy dependent.',
                'Liquidation charges are ordinary fees plus 100bp friction, paid from sales; no external cash, historic lender execution or solvency guarantee.']))
        (output/'README.md').write_text('# Financing Scan and Static Price-Gap Cures\n\n'
            'Both rules use their own unlevered CAGR baseline. Finite local crossings distinguish near-zero residuals from policy jumps. '
            'The fifteen hypothetical gap-cure attempts share weights, fees and target leverage across rules.\n\n'
            '[Summary](diagnostic_summary.json) · [Crossings](funding_crossings.csv) · [Scan](funding_scan.csv) · '
            '[Gap cures](gap_cure_metrics.csv) · [Independent account checks](independent_comparisons.csv) · '
            '[Daily checks](daily_path_checks.csv) · [Cure checks](gap_cure_checks.csv) · [Manifest](run_manifest.json)\n')
        if source_hashes()!=code:raise RuntimeError('source changed during financing/gap diagnostics')
        manifest['artifacts']={str(p.relative_to(output)):sha256(p) for p in sorted(output.rglob('*')) if p.is_file()
            and p!=output/'run_manifest.json' and p.relative_to(output).parts[0]!='config'}
        manifest.update(status='complete',finished_at_utc=datetime.now(timezone.utc).isoformat(),raw_sources=core['raw_sources'],counts=counts)
        write_json(output/'run_manifest.json',manifest);verify_run(output)
    except Exception as error:
        manifest.update(status='failed',failure=dict(type=type(error).__name__,message=str(error)));write_json(output/'run_manifest.json',manifest);raise
    return manifest


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--raw-root',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    for key,name in [('baseline','backtest_absolute_decoupled_2026-10-05.json'),('sources','backtest_sources.json'),('settings','backtest_funding_scan_gap_2026-10-06.json')]:
        p.add_argument('--'+key,type=Path,default=Path('config')/name)
    a=p.parse_args();m=run_funding_scan_gap(a.raw_root,a.baseline,a.sources,a.settings,a.output)
    print(json.dumps(dict(run_id=m['run_id'],status=m['status'],counts=m['counts']),indent=2))


if __name__=='__main__':main()
