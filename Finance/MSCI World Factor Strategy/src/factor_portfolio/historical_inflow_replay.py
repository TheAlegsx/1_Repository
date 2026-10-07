"""Coupled historical portfolio/cohort pilot, with explicit overlay diagnostics."""
from __future__ import annotations

import argparse
from datetime import datetime,timezone
import json
import math
from pathlib import Path
import uuid

import pandas as pd

from .backtest_workflow import admit_sources,prepare_inputs
from .config import SwissquoteStandardFeeSchedule
from .historical import simulate
from .historical_inflow_calendar import run_calendar_audit
from .coupled_inflow_accounting import simulate_coupled
from .inflows import simulate as overlay_simulate
from .inflow_workflow import source_hashes,sha256,write_json,verify_run


def calculate_replays(returns,reference,calendar,plans,baseline,contract,execution):
    end=calendar.actual_end.iloc[-1];ret=returns.loc[:end,list(baseline['target_weights'])].copy();ret.iloc[0]=0
    fee=SwissquoteStandardFeeSchedule(**baseline['fee_schedule'])
    kwargs=dict(leverage=contract['leverage'],margin=baseline['borrowing_margin_annual'],sleeve_band=baseline['sleeve_band'],
        leverage_band=baseline['leverage_band'],initial_equity_usd=baseline['initial_equity_usd'],fee_schedule=fee)
    histories=[];events=[];months=[];overlays=[];headlines=[];checks=[]
    for policy in contract['policies']:
        base=simulate(ret,reference,list(baseline['target_weights'].values()),policy=policy,**kwargs)
        if base.status!='complete':raise ValueError('complete historical source path required')
        empty=plans[(plans.layer=='timing')&(plans.flow_plan=='no_flows')].copy();empty['proposed_fund_fee_fraction']=0.
        control=simulate_coupled(ret,reference,list(baseline['target_weights'].values()),policy=policy,flows=empty,initial_unit_nav=contract['initial_unit_nav'],**kwargs)
        pd.testing.assert_frame_equal(control.history[base.history.columns],base.history,check_exact=True)
        pd.testing.assert_frame_equal(control.events,base.events,check_exact=True)
        checks.append(dict(policy=policy,no_flow_zero_added_fee_exact_every_observation=True,observations=len(ret)))
        cases=[('control','no_flow_zero_added_fee',empty)]+[(str(layer),str(name),frame) for (layer,name),frame in plans.groupby(['layer','flow_plan'],sort=False)]
        source_points=base.history.equity_usd.reindex(pd.to_datetime([calendar.actual_start.iloc[0]]+calendar.actual_end.tolist()))
        source_returns=source_points.pct_change(fill_method=None).iloc[1:].tolist()
        for layer,name,flow in cases:
            run=control if layer=='control' else simulate_coupled(ret,reference,list(baseline['target_weights'].values()),policy=policy,flows=flow,initial_unit_nav=contract['initial_unit_nav'],**kwargs)
            if run.status!='complete' or len(run.monthly)!=len(calendar):raise ValueError('incomplete coupled history or monthly event coverage')
            run_id=f'{policy}__{layer}__{name}'
            histories.append(run.history.reset_index().assign(run_id=run_id));events.append(run.events.assign(run_id=run_id));months.append(run.monthly.assign(run_id=run_id,policy=policy,layer=layer,flow_plan=name))
            final=run.history.iloc[-1]
            headlines.append(dict(run_id=run_id,policy=policy,layer=layer,flow_plan=name,start=str(ret.index[0].date()),end=str(ret.index[-1].date()),
                observations=len(ret),owner_equity_usd=final.owner_equity_usd,external_equity_usd=final.external_equity_usd,
                closing_aum_usd=final.equity_usd,closing_unit_nav=final.unit_nav,
                gross_subscriptions_usd=math.fsum(run.monthly.subscriptions_usd),redemptions_usd=math.fsum(run.monthly.redemptions_usd),
                transaction_cost_usd=final.cumulative_transaction_cost_usd,financing_cost_usd=final.cumulative_financing_cost_usd,
                fund_fee_usd=final.cumulative_fund_fee_usd,flow_transaction_cost_usd=math.fsum(run.monthly.flow_transaction_cost_usd)))
            if layer!='control':
                fractions=flow.monthly_external_unit_redemption_fraction.unique()
                if len(fractions)!=1:raise ValueError('pilot overlay needs constant declared redemption fraction')
                annual_fee=float(flow.proposed_fund_fee_fraction.iloc[0])*12
                overlay=overlay_simulate(initial_aum=float(base.history.equity_usd.iloc[0]),
                    initial_nav=float(base.history.equity_usd.iloc[0])/(baseline['initial_equity_usd']/contract['initial_unit_nav']),
                    annual_fee=annual_fee,monthly_returns=source_returns,subscriptions=flow.scheduled_subscription_usd.tolist(),redemption_fraction=float(fractions[0]))
                overlays.append(pd.DataFrame(overlay).assign(run_id=run_id,event_date=calendar.actual_end.tolist(),diagnostic_scope='return_path_overlay_without_portfolio_flow_cost_debt_feedback'))
    return dict(daily=pd.concat(histories,ignore_index=True),events=pd.concat(events,ignore_index=True),monthly=pd.concat(months,ignore_index=True),
        overlay=pd.concat(overlays,ignore_index=True),headline=pd.DataFrame(headlines),checks=checks,
        definitions=dict(execution=execution,actual_end=end,source_full_end=baseline['periods']['full']['end'],
            coupled_accounting_executed=True,manager_cash_executed=False,dated_investor_return_diagnostics_executed=False,
            limitations=['Hypothetical subscriptions/redemptions, fixed borrowing terms and fees.',
                'No market impact, swing pricing, exit levy, investor-specific taxes or actual lender capacity.',
                'Flow costs allocated to remaining fund units at post-fee/pre-flow-cost quotation.',
                'Overlay is diagnostic and omits portfolio feedback; not a substitute for the coupled results.']))


def run_replay(raw_root,baseline_path,sources_path,business_path,timing_path,contract_path,execution_path,output):
    output=Path(output)
    if output.exists():raise FileExistsError('choose a new coupled output directory')
    paths=[baseline_path,sources_path,business_path,timing_path,contract_path,execution_path]
    captured={Path(p).name:Path(p).read_bytes() for p in paths}
    if len(captured)!=len(paths):raise ValueError('distinct captured configuration names required')
    baseline,spec,business,timing,contract,execution=(json.loads(captured[Path(p).name]) for p in paths)
    if execution['schema_version']!=1 or execution['status']!='coupled_accounting_pilot' or execution.get('execution_version')!=2 or execution['calendar_contract_sha256']!=sha256(contract_path):
        raise ValueError('coupled execution must identify the preserved calendar/accounting proposal')
    output.mkdir(parents=True);(output/'config').mkdir()
    for name,data in captured.items():(output/'config'/name).write_bytes(data)
    code=source_hashes();manifest=dict(schema_version=1,run_id=str(uuid.uuid4()),status='running',figures_included=False,
        started_at_utc=datetime.now(timezone.utc).isoformat(),scope='Coupled historical portfolio/cohort pilot and labeled overlay. Excludes manager cash, dated TWR/MWR diagnostics and final reports.',
        code=code,configuration_snapshots={f'config/{n}':sha256(output/'config'/n) for n in captured},artifacts={})
    write_json(output/'run_manifest.json',manifest)
    try:
        cp=[output/'config'/Path(p).name for p in paths]
        basis=run_calendar_audit(raw_root,*cp[:5],output/'basis')
        inputs=output/'replay_inputs';inputs.mkdir()
        ret,ref=prepare_inputs(raw_root,admit_sources(raw_root,spec),spec,baseline,inputs)
        calendar=pd.read_csv(output/'basis/historical_calendar.csv');plans=pd.read_csv(output/'basis/hypothetical_flow_calendar.csv',float_precision='round_trip')
        result=calculate_replays(ret,ref,calendar,plans,baseline,contract,execution)
        names={'daily':'coupled_daily.csv','events':'coupled_trade_events.csv','monthly':'coupled_monthly.csv','headline':'coupled_headline.csv','overlay':'overlay_diagnostic_monthly.csv'}
        for key,name in names.items():result[key].to_csv(output/name,index=False,lineterminator='\n')
        write_json(output/'coupled_checks.json',result['checks']);write_json(output/'coupled_definitions.json',result['definitions'])
        (output/'README.md').write_text('# Historical coupled inflow pilot\n\nHypothetical flows executed through dated portfolio/cohort accounting. '
            'No manager cash or dated investor IRR/TWR conclusions are generated here.\n\n[Monthly accounts](coupled_monthly.csv) · '
            '[Headlines](coupled_headline.csv) · [Trade events](coupled_trade_events.csv) · [Daily identities](coupled_daily.csv) · '
            '[Overlay diagnostic](overlay_diagnostic_monthly.csv) · [Checks](coupled_checks.json) · [Definitions](coupled_definitions.json) · [Manifest](run_manifest.json)\n')
        admit_sources(raw_root,spec)
        if source_hashes()!=code:raise RuntimeError('source changed during coupled pilot')
        manifest['artifacts']={str(p.relative_to(output)):sha256(p) for p in sorted(output.rglob('*')) if p.is_file() and p!=output/'run_manifest.json' and p.relative_to(output).parts[0]!='config'}
        manifest.update(status='complete',finished_at_utc=datetime.now(timezone.utc).isoformat(),raw_sources=basis['raw_sources'],
            counts=dict(coupled_cases=len(result['headline']),monthly_rows=len(result['monthly']),daily_rows=len(result['daily']),trade_events=len(result['events']),no_flow_exact_checks=len(result['checks']),overlay_rows=len(result['overlay'])))
        write_json(output/'run_manifest.json',manifest);verify_run(output)
    except Exception as error:
        manifest.update(status='failed',failure=dict(type=type(error).__name__,message=str(error)));write_json(output/'run_manifest.json',manifest);raise
    return manifest


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--raw-root',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    defaults={'baseline':'backtest_absolute_decoupled_2026-10-05.json','sources':'backtest_sources.json','business':'inflow_acquisition.json',
        'timing':'inflow_timing.json','contract':'historical_inflows_contract_2026-10-05.json','execution':'historical_inflows_execution_v2_2026-10-05.json'}
    for field,name in defaults.items():p.add_argument('--'+field,type=Path,default=Path('config')/name)
    a=p.parse_args();m=run_replay(a.raw_root,a.baseline,a.sources,a.business,a.timing,a.contract,a.execution,a.output)
    print(json.dumps(dict(run_id=m['run_id'],status=m['status'],counts=m['counts']),indent=2))


if __name__=='__main__':main()
