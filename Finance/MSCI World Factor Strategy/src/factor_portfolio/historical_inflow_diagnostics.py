"""Dated investor return diagnostics and separately paid manager cash accounts."""
from __future__ import annotations

import argparse
from datetime import datetime,timezone
import json
import math
from pathlib import Path
import uuid

import numpy as np
import pandas as pd

from .historical_inflow_replay import run_replay
from .inflow_workflow import source_hashes,sha256,write_json,verify_run


def validate_settings(s):
    if s['schema_version']!=1 or s['year_days']!=365.2425:
        raise ValueError('unsupported dated diagnostic conventions')
    if not math.isfinite(s['log_annual_discount_min']) or not math.isfinite(s['log_annual_discount_max']) or s['log_annual_discount_min']>=s['log_annual_discount_max']:
        raise ValueError('invalid dated root range')
    if type(s['scan_points']) is not int or s['scan_points']<2 or type(s['bisection_iterations']) is not int or s['bisection_iterations']<1:
        raise ValueError('invalid dated root resolution')
    if not math.isfinite(s['npv_residual_tolerance_usd']) or s['npv_residual_tolerance_usd']<=0:
        raise ValueError('positive dated NPV tolerance required')


def dated_mwr(dates,cashflows,settings):
    validate_settings(settings)
    if len(dates)!=len(cashflows) or not len(dates):raise ValueError('matching dated cash flows required')
    cf=pd.DataFrame({'date':pd.to_datetime(dates),'cash':cashflows})
    if cf.date.isna().any() or not np.isfinite(cf.cash.to_numpy(float)).all():raise ValueError('finite dated investor cash flows required')
    cf=cf.groupby('date',as_index=False,sort=True).cash.sum();cf=cf[cf.cash!=0]
    empty=dict(status='undefined_no_invested_external_cohort',annual_mwr=None,npv_residual_usd=None,scanned_root_count=0,roots=[])
    if cf.empty:return empty
    if cf.cash.iloc[0]>=0 or not (cf.cash>0).any():raise ValueError('investor cash flow must start with an outflow and include proceeds')
    times=((cf.date-cf.date.iloc[0]).dt.days/settings['year_days']).to_numpy(float);values=cf.cash.to_numpy(float)
    if times[-1]<=0:return dict(empty,status='undefined_zero_duration')
    def npv(q):return math.fsum(float(c)*math.exp(-q*float(t)) for c,t in zip(values,times))
    grid=np.linspace(settings['log_annual_discount_min'],settings['log_annual_discount_max'],settings['scan_points']);f=[npv(q) for q in grid]
    exact=[float(q) for q,x in zip(grid,f) if x==0.]
    brackets=[(float(a),float(b)) for a,b,fa,fb in zip(grid[:-1],grid[1:],f[:-1],f[1:]) if (fa<0<fb) or (fb<0<fa)]
    candidates=exact[:]
    for lo,hi in brackets:
        flo=npv(lo)
        for _ in range(settings['bisection_iterations']):
            middle=(lo+hi)/2;fm=npv(middle)
            if fm==0:lo=hi=middle;break
            if (fm>0)==(flo>0):lo=middle;flo=fm
            else:hi=middle
        candidates.append((lo+hi)/2)
    roots=[]
    for q in sorted(candidates):
        residual=npv(q)
        if abs(residual)>settings['npv_residual_tolerance_usd']:raise ValueError('dated root residual exceeds fixed tolerance')
        roots.append(dict(log_annual_discount=q,annual_return=math.expm1(q),npv_residual_usd=residual))
    if len(roots)!=1:return dict(empty,status='multiple_scanned_roots' if roots else 'no_root_in_scanned_range',scanned_root_count=len(roots),roots=roots)
    return dict(status='unique_root_in_scanned_range',annual_mwr=roots[0]['annual_return'],npv_residual_usd=roots[0]['npv_residual_usd'],
        scanned_root_count=1,roots=roots,first_investor_date=str(cf.date.iloc[0].date()),terminal_date=str(cf.date.iloc[-1].date()))


def investor_diagnostics(coupled,overlay,contract,settings):
    rows=[];cash_rows=[];details=[];start=pd.Timestamp(contract['start']);initial=contract['initial_unit_nav']
    for kind,table in [('coupled',coupled),('overlay',overlay)]:
        for run_id,g in table.groupby('run_id',sort=False):
            g=g.sort_values('month');end=pd.Timestamp(g.event_date.iloc[-1]);years=(end-start).days/settings['year_days']
            if years<=0:raise ValueError('positive actual investor horizon required')
            nav=float(g.closing_unit_nav.iloc[-1] if kind=='coupled' else g.nav_per_unit.iloc[-1])
            red=g.redemptions_usd if kind=='coupled' else g.new_cohort_redemptions_usd
            terminal=float(g.external_equity_usd.iloc[-1] if kind=='coupled' else g.new_cohort_equity_usd.iloc[-1])
            cf=(red-g.subscriptions_usd).to_numpy(float);cf[-1]+=terminal
            if g.subscriptions_usd.sum()==0:
                solved=dict(status='undefined_no_invested_external_cohort',annual_mwr=None,npv_residual_usd=None,scanned_root_count=0,roots=[])
                external_twr=None;first_date=None
            else:
                solved=dated_mwr(g.event_date.tolist(),cf.tolist(),settings)
                first=g[g.subscriptions_usd>0].iloc[0];first_date=str(pd.Timestamp(first.event_date).date())
                quoted=float(first.quote_unit_nav if kind=='coupled' else first.nav_per_unit)
                elapsed=(end-pd.Timestamp(first.event_date)).days/settings['year_days']
                external_twr=(nav/quoted)**(1/elapsed)-1 if elapsed>0 else None
            policy,layer,plan=run_id.split('__')
            rows.append(dict(kind=kind,run_id=run_id,policy=policy,layer=layer,flow_plan=plan,
                fund_window_start=str(start.date()),fund_window_end=str(end.date()),actual_years=years,
                fund_unit_twr_annual=math.expm1(math.log(nav/initial)/years),fund_unit_total_return=nav/initial-1,
                first_external_subscription_date=first_date,external_window_unit_twr_annual=external_twr,
                aggregate_external_mwr_annual=solved['annual_mwr'],mwr_status=solved['status'],scanned_root_count=solved['scanned_root_count'],
                npv_residual_usd=solved['npv_residual_usd'],terminal_external_equity_usd=terminal))
            for date_,sub,r,c in zip(g.event_date,g.subscriptions_usd,red,cf):cash_rows.append(dict(kind=kind,run_id=run_id,date=date_,subscription_outflow_usd=-float(sub),redemption_inflow_usd=float(r),terminal_external_value_usd=terminal if date_==g.event_date.iloc[-1] else 0.,net_investor_cash_flow_usd=float(c)))
            details.append(dict(kind=kind,run_id=run_id,**solved))
    return pd.DataFrame(rows),pd.DataFrame(cash_rows),details


def manager_accounts(monthly,business):
    rows=[];headline=[];annual=[]
    for run_id,g in monthly.groupby('run_id',sort=False):
        g=g.sort_values('month')
        for receipt in business['manager_fee_receipt_fractions']:
            if not math.isfinite(receipt) or not 0<=receipt<=1:raise ValueError('invalid manager receipt fraction')
            external_cash=total_cash=owner_fees=external_fees=0.;min_external=min_total=0.;cost_total=0.
            year_groups={}
            for r in g.itertuples(index=False):
                year=int(r.project_year);fixed=business['annual_fixed_manager_cost_usd']*(1+business['fixed_cost_inflation'])**(year-1)/12
                setup=business['setup_cost_usd'] if r.month==1 else 0.
                acquisition=business['acquisition_cost_fraction_of_gross_subscriptions']*r.subscriptions_usd
                servicing=business['annual_servicing_cost_fraction_of_opening_external_assets']*r.opening_external_aum_usd/12
                cost=fixed+setup+acquisition+servicing;external_receipt=r.external_fee_usd*receipt;owner_receipt=r.owner_fee_usd*receipt
                external_net=external_receipt-cost;total_net=external_net+owner_receipt
                external_cash+=external_net;total_cash+=total_net;external_fees+=external_receipt;owner_fees+=owner_receipt;cost_total+=cost
                min_external=min(min_external,external_cash);min_total=min(min_total,total_cash)
                row=dict(run_id=run_id,manager_receipt_fraction=receipt,month=r.month,project_year=year,event_date=r.event_date,
                    external_fee_receipts_usd=external_receipt,conditional_owner_fee_receipts_usd=owner_receipt,
                    fixed_cost_usd=fixed,setup_cost_usd=setup,acquisition_cost_usd=acquisition,servicing_cost_usd=servicing,total_manager_cost_usd=cost,
                    external_business_net_cash_usd=external_net,conditional_total_fee_treasury_net_cash_usd=total_net,
                    cumulative_external_business_cash_usd=external_cash,cumulative_conditional_total_fee_treasury_usd=total_cash)
                rows.append(row);year_groups.setdefault(year,[]).append(row)
            for year,values in year_groups.items():
                annual.append(dict(run_id=run_id,manager_receipt_fraction=receipt,project_year=year,
                    external_fee_receipts_usd=math.fsum(x['external_fee_receipts_usd'] for x in values),
                    conditional_owner_fee_receipts_usd=math.fsum(x['conditional_owner_fee_receipts_usd'] for x in values),
                    total_manager_cost_usd=math.fsum(x['total_manager_cost_usd'] for x in values),
                    external_business_net_cash_usd=math.fsum(x['external_business_net_cash_usd'] for x in values),
                    cumulative_external_business_cash_usd=values[-1]['cumulative_external_business_cash_usd']))
            headline.append(dict(run_id=run_id,manager_receipt_fraction=receipt,external_fee_receipts_usd=external_fees,
                conditional_owner_fee_receipts_usd=owner_fees,total_manager_cost_usd=cost_total,
                cumulative_external_business_cash_usd=external_cash,external_business_peak_funding_gap_usd=-min_external,
                conditional_total_fee_treasury_usd=total_cash,conditional_total_fee_peak_funding_gap_usd=-min_total))
    return pd.DataFrame(rows),pd.DataFrame(annual),pd.DataFrame(headline)


def run_diagnostics(raw_root,config_dir,output):
    output=Path(output);config_dir=Path(config_dir)
    if output.exists():raise FileExistsError('choose a new diagnostics output directory')
    names=['backtest_absolute_decoupled_2026-10-05.json','backtest_sources.json','inflow_acquisition.json','inflow_timing.json',
        'historical_inflows_contract_2026-10-05.json','historical_inflows_execution_v2_2026-10-05.json','historical_inflows_diagnostics_2026-10-05.json']
    captured={n:(config_dir/n).read_bytes() for n in names};settings=json.loads(captured[names[-1]]);validate_settings(settings)
    business=json.loads(captured['inflow_acquisition.json']);contract=json.loads(captured['historical_inflows_contract_2026-10-05.json'])
    output.mkdir(parents=True);(output/'config').mkdir()
    for n,data in captured.items():(output/'config'/n).write_bytes(data)
    code=source_hashes();manifest=dict(schema_version=1,run_id=str(uuid.uuid4()),status='running',figures_included=False,
        started_at_utc=datetime.now(timezone.utc).isoformat(),scope='Dated coupled/overlay investor diagnostics and hypothetical manager external-business/conditional fee-treasury accounts. No forecasts or final report assembly.',
        code=code,configuration_snapshots={f'config/{n}':sha256(output/'config'/n) for n in names},artifacts={})
    write_json(output/'run_manifest.json',manifest)
    try:
        paths=[output/'config'/n for n in names]
        pilot=run_replay(raw_root,*paths[:6],output/'pilot')
        coupled=pd.read_csv(output/'pilot/coupled_monthly.csv',float_precision='round_trip');overlay=pd.read_csv(output/'pilot/overlay_diagnostic_monthly.csv',float_precision='round_trip')
        returns,cash,roots=investor_diagnostics(coupled,overlay,contract,settings);manager,annual,head=manager_accounts(coupled,business)
        for name,frame in [('dated_investor_returns.csv',returns),('dated_investor_cashflows.csv',cash),('manager_monthly.csv',manager),('manager_annual.csv',annual),('manager_headline.csv',head)]:frame.to_csv(output/name,index=False,lineterminator='\n')
        write_json(output/'dated_return_roots.json',roots)
        write_json(output/'diagnostic_definitions.json',dict(settings=settings,actual_calendar_year_basis=365.2425,
            root_scope='Sign-changing brackets and exact grid roots only; no global uniqueness or unsampled tangency guarantee.',
            fund_twr='Before initial investment expenses NAV100 to terminal unit NAV, actual full business horizon; external-window TWR uses first subscription quote.',
            manager='Budgets paid outside fund. External business cash excludes owner fees. Conditional treasury assumes same receipt fraction for owner fees, monthly availability, no distribution/settlement lag.',
            limitations=['Historical hypothetical flows, not observed fundraising or future-return forecasts.','Dated annualisation is actual/365.2425; not Excel XIRR actual/365.','No investor taxes, fee proposals, account approval or manager funding interest.']))
        (output/'README.md').write_text('# Historical investor and manager diagnostics\n\n[Dated returns](dated_investor_returns.csv) · [Cash flows](dated_investor_cashflows.csv) · '
            '[Root checks](dated_return_roots.json) · [Manager monthly cash](manager_monthly.csv) · [Manager headlines](manager_headline.csv) · '
            '[Definitions](diagnostic_definitions.json) · [Coupled pilot](pilot/README.md) · [Manifest](run_manifest.json)\n\nHistorical hypothetical experiments with defined calendar/fee/cost assumptions. Reports remain pending.\n')
        if source_hashes()!=code:raise RuntimeError('source changed during historical diagnostics')
        manifest['artifacts']={str(p.relative_to(output)):sha256(p) for p in sorted(output.rglob('*')) if p.is_file() and p!=output/'run_manifest.json' and p.relative_to(output).parts[0]!='config'}
        manifest.update(status='complete',finished_at_utc=datetime.now(timezone.utc).isoformat(),raw_sources=pilot['raw_sources'],
            counts=dict(investor_return_rows=len(returns),dated_cash_flow_rows=len(cash),manager_monthly_rows=len(manager),manager_headline_rows=len(head),
                mwr_status_counts={str(k):int(v) for k,v in returns.groupby('mwr_status').size().items()}))
        write_json(output/'run_manifest.json',manifest);verify_run(output)
    except Exception as error:
        manifest.update(status='failed',failure=dict(type=type(error).__name__,message=str(error)));write_json(output/'run_manifest.json',manifest);raise
    return manifest


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--raw-root',type=Path,required=True);p.add_argument('--config-dir',type=Path,default=Path('config'));p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    m=run_diagnostics(a.raw_root,a.config_dir,a.output);print(json.dumps(dict(run_id=m['run_id'],status=m['status'],counts=m['counts']),indent=2))


if __name__=='__main__':main()
