"""Preparation audit: real valuation calendar and unchanged hypothetical flow plans."""
from __future__ import annotations

import argparse
from datetime import datetime,timezone
import json
import math
from pathlib import Path
import uuid

import numpy as np
import pandas as pd

from .backtest_workflow import run_backtest_study,validate_config
from .inflow_workflow import sha256,source_hashes,write_json,verify_run


def validate_contract(contract,baseline,business,timing):
    if contract['schema_version']!=1 or contract['status']!='implementation_proposal' or contract['audit_scope']!='calendar_and_no_flow_basis_only':
        raise ValueError('unsupported historical inflow preparation contract')
    if contract['project_months']!=120 or contract['calendar_rule']!='anniversary_month_first_common_nav_on_or_after':
        raise ValueError('historical business horizon must preserve 120 declared project months')
    if contract['policies']!=[baseline['primary_policy'],'hybrid20'] or contract['leverage']!=baseline['primary_leverage']:
        raise ValueError('historical calendar must identify primary and matched comparison')
    if contract['start']!=baseline['periods']['full']['start']:
        raise ValueError('historical calendar starts with the unchanged main inception')
    if business['initial_owner_capital_usd']!=baseline['initial_equity_usd'] or timing['owner_capital_usd']!=baseline['initial_equity_usd']:
        raise ValueError('owner capital must match the source backtest')
    if business['annual_fee']!=timing['annual_fee'] or business['annual_returns']!=timing['annual_returns']:
        raise ValueError('preserved hypothetical layers must retain their shared assumptions')
    for values in business['annual_new_client_equivalents'].values():
        if len(values)!=10 or any(not math.isfinite(x) or x<0 for x in values):raise ValueError('ten-year client schedules required')
    for values in timing['monthly_schedules_usd'].values():
        if len(values)!=120 or any(not math.isfinite(x) or x<0 for x in values):raise ValueError('120 nonnegative subscription entries required')


def historical_calendar(dates,start,months=120):
    dates=pd.DatetimeIndex(dates)
    if not dates.is_unique or not dates.is_monotonic_increasing or dates.hasnans:
        raise ValueError('historical valuation dates must be complete, unique and ordered')
    anchor=pd.Timestamp(start)
    if dates[0]!=anchor:raise ValueError('historical calendar needs the actual inception level')
    rows=[];prior=anchor
    for month in range(1,months+1):
        nominal=anchor+pd.DateOffset(months=month);position=dates.searchsorted(nominal)
        if position>=len(dates):raise ValueError('historical source does not cover the declared anniversary horizon')
        actual=dates[position]
        if actual<=prior:raise ValueError('month valuation dates must be distinct; no interpolation')
        rows.append(dict(month=month,project_year=(month-1)//12+1,
            nominal_start=str((anchor+pd.DateOffset(months=month-1)).date()),nominal_end=str(nominal.date()),
            actual_start=str(prior.date()),actual_end=str(actual.date()),
            calendar_days=(actual-prior).days,deferred_calendar_days=(actual-nominal).days))
        prior=actual
    return pd.DataFrame(rows)


def return_basis(history,calendar,capital,policy,nav=100.):
    h=history.set_index('date') if 'date' in history else history.copy();h.index=pd.DatetimeIndex(h.index)
    if not np.isfinite(h.equity_usd).all() or (h.equity_usd<=0).any():raise ValueError('positive complete no-flow equity path required')
    opening=float(h.equity_usd.iloc[0]);entry=capital-opening
    if not math.isclose(entry,float(h.transaction_cost_usd.iloc[0]),rel_tol=2e-12,abs_tol=1e-6):
        raise ValueError('opening investment charge must occur exactly once')
    owner_units=capital/nav;replayed=opening;rows=[];maximum_error=0.
    for c in calendar.itertuples(index=False):
        before=float(h.loc[pd.Timestamp(c.actual_start),'equity_usd']);after=float(h.loc[pd.Timestamp(c.actual_end),'equity_usd'])
        r=after/before-1.;replayed*=1+r;error=abs(replayed-after);maximum_error=max(maximum_error,error)
        if not math.isclose(replayed,after,rel_tol=2e-12,abs_tol=1e-6):raise ValueError('geometric no-flow calendar reference fails')
        rows.append(dict(policy=policy,month=c.month,actual_start=c.actual_start,actual_end=c.actual_end,
            source_opening_equity_usd=before,source_closing_equity_usd=after,strategy_net_interval_return=r,
            no_flow_zero_added_fee_owner_equity_usd=replayed,no_flow_unit_nav=after/owner_units))
    return pd.DataFrame(rows),dict(policy=policy,opening_committed_capital_usd=capital,opening_investment_cost_usd=entry,
        opening_owner_equity_usd=opening,owner_units=owner_units,initial_unit_nav_before_cost=nav,
        initial_unit_nav_after_cost=opening/owner_units,source_full_end=str(h.index[-1].date()),
        historical_business_end=calendar.actual_end.iloc[-1],no_flow_maximum_reconstruction_error_usd=maximum_error,
        zero_added_fee_control_only=True,cohort_flow_simulation_included=False)


def flow_plans(calendar,business,timing):
    rows=[];totals={};months=business['first_year_subscription_months']
    if not months or len(set(months))!=len(months) or any(m not in range(1,13) for m in months):raise ValueError('invalid first-year launch delay')
    for layer,schedules in [('acquisition',business['annual_new_client_equivalents']),('timing',timing['monthly_schedules_usd'])]:
        for name,values in schedules.items():
            amounts=[]
            for c in calendar.itertuples(index=False):
                if layer=='acquisition':
                    annual=values[c.project_year-1]*business['ticket_usd']
                    sub=(annual/len(months) if c.month in months else 0.) if c.project_year==1 else annual/12
                    annual_red=0. if name=='no_flows' else (business['sales_stop_annual_redemption'] if name=='sales_stop' else business['normal_annual_redemption'])
                else:sub=values[c.month-1];annual_red=0. if name=='no_flows' else timing['annual_external_unit_redemption']
                amounts.append(sub)
                rows.append(dict(layer=layer,flow_plan=name,month=c.month,project_year=c.project_year,event_date=c.actual_end,
                    scheduled_subscription_usd=sub,annual_external_unit_redemption=annual_red,
                    monthly_external_unit_redemption_fraction=1-(1-annual_red)**(1/12),
                    proposed_fund_fee_fraction=business['annual_fee']/12,
                    fixed_manager_cost_scheduled_usd=business['annual_fixed_manager_cost_usd']*(1+business['fixed_cost_inflation'])**(c.project_year-1)/12,
                    setup_cost_scheduled_usd=business['setup_cost_usd'] if c.month==1 else 0.,
                    acquisition_cost_scheduled_usd=business['acquisition_cost_fraction_of_gross_subscriptions']*sub,
                    servicing_rate_annual=business['annual_servicing_cost_fraction_of_opening_external_assets'],
                    future_return_conditioning=False,executed_cash_flow=False))
            total=math.fsum(amounts);totals[layer+'/'+name]=total
            expected=(math.fsum(values)*business['ticket_usd']) if layer=='acquisition' else math.fsum(values)
            if not math.isclose(total,expected,abs_tol=1e-6,rel_tol=2e-12):raise ValueError('subscription mapping changes the preserved gross total')
    return pd.DataFrame(rows),totals


def run_calendar_audit(raw_root,baseline_path,sources_path,business_path,timing_path,contract_path,output):
    output=Path(output)
    if output.exists():raise FileExistsError('choose a new preparation output; earlier runs are preserved')
    paths=[baseline_path,sources_path,business_path,timing_path,contract_path];captured={Path(p).name:Path(p).read_bytes() for p in paths}
    if len(captured)!=len(paths):raise ValueError('distinct captured filenames required')
    baseline,spec,business,timing,contract=(json.loads(captured[Path(p).name]) for p in paths)
    validate_config(baseline);validate_contract(contract,baseline,business,timing)
    output.mkdir(parents=True);(output/'config').mkdir()
    for name,data in captured.items():(output/'config'/name).write_bytes(data)
    code=source_hashes();manifest=dict(schema_version=1,run_id=str(uuid.uuid4()),status='running',figures_included=False,
        started_at_utc=datetime.now(timezone.utc).isoformat(),scope='Preparation only: calendar, no-flow return basis and unchanged hypothetical subscription plans. No coupled or overlay inflow execution.',
        code=code,configuration_snapshots={f'config/{n}':sha256(output/'config'/n) for n in captured},artifacts={})
    write_json(output/'run_manifest.json',manifest)
    try:
        core=run_backtest_study(raw_root,output/'config'/Path(baseline_path).name,output/'config'/Path(sources_path).name,output/'core')
        histories={p:pd.read_csv(output/f'core/results/full_factor_{p}_{contract["leverage"]:.2f}_history.csv',parse_dates=['date'],float_precision='round_trip') for p in contract['policies']}
        calendar=historical_calendar(histories[contract['policies'][0]].date,contract['start'],contract['project_months'])
        basis=[];checks=[]
        for policy,h in histories.items():
            frame,check=return_basis(h,calendar,baseline['initial_equity_usd'],policy,contract['initial_unit_nav']);basis.append(frame);checks.append(check)
        plans,totals=flow_plans(calendar,business,timing)
        calendar.to_csv(output/'historical_calendar.csv',index=False);pd.concat(basis,ignore_index=True).to_csv(output/'historical_return_basis.csv',index=False)
        plans.to_csv(output/'hypothetical_flow_calendar.csv',index=False)
        definitions=dict(contract=contract,no_flow_checks=checks,scheduled_gross_subscription_totals=totals,
            source_core_manifest='core/run_manifest.json',source_full_period=baseline['periods']['full'],actual_business_start=calendar.actual_start.iloc[0],
            actual_business_end=calendar.actual_end.iloc[-1],months=len(calendar),deferred_month_boundaries=int(calendar.deferred_calendar_days.gt(0).sum()),
            flow_plan_rows=len(plans),coupled_replay_executed=False,overlay_cohort_simulation_executed=False)
        write_json(output/'calendar_definitions.json',definitions)
        (output/'README.md').write_text('# Historical inflow preparation audit\n\nCalendar and no-flow return basis from freshly regenerated backtests. '
            'Hypothetical subscription plans are mapped, not executed. Coupled portfolio/cohort accounts and investor return diagnostics remain pending.\n\n'
            '[Calendar](historical_calendar.csv) · [Return basis](historical_return_basis.csv) · [Flow plans](hypothetical_flow_calendar.csv) · '
            '[Definitions](calendar_definitions.json) · [Fresh core calculation](core/README.md) · [Manifest](run_manifest.json)\n')
        if source_hashes()!=code:raise RuntimeError('source changed during preparation audit')
        manifest['artifacts']={str(p.relative_to(output)):sha256(p) for p in sorted(output.rglob('*')) if p.is_file() and p!=output/'run_manifest.json' and p.relative_to(output).parts[0]!='config'}
        manifest.update(status='complete',finished_at_utc=datetime.now(timezone.utc).isoformat(),counts=dict(months=len(calendar),return_intervals=len(calendar)*len(histories),flow_plan_rows=len(plans)),raw_sources=core['raw_sources'])
        write_json(output/'run_manifest.json',manifest);verify_run(output)
    except Exception as error:
        manifest.update(status='failed',failure=dict(type=type(error).__name__,message=str(error)));write_json(output/'run_manifest.json',manifest);raise
    return manifest


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--raw-root',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--baseline',type=Path,default=Path('config/backtest_absolute_decoupled_2026-10-05.json'));p.add_argument('--sources',type=Path,default=Path('config/backtest_sources.json'))
    p.add_argument('--business',type=Path,default=Path('config/inflow_acquisition.json'));p.add_argument('--timing',type=Path,default=Path('config/inflow_timing.json'))
    p.add_argument('--contract',type=Path,default=Path('config/historical_inflows_contract_2026-10-05.json'));a=p.parse_args()
    m=run_calendar_audit(a.raw_root,a.baseline,a.sources,a.business,a.timing,a.contract,a.output);print(json.dumps(dict(run_id=m['run_id'],status=m['status'],counts=m['counts']),indent=2))


if __name__=='__main__':main()
