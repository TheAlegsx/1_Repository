"""Reproducible comparison of verified coupled and overlay diagnostics."""
from __future__ import annotations

import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import uuid

import numpy as np
import pandas as pd

from .inflow_workflow import sha256,source_hashes,verify_run,write_json

INPUTS=['pilot/coupled_monthly.csv','pilot/overlay_diagnostic_monthly.csv',
        'pilot/coupled_headline.csv','dated_investor_returns.csv','manager_headline.csv']


def compare_accounts(coupled,overlay,headlines,returns):
    """Align actual dates and cohort definitions; differences are not attribution."""
    c=coupled[coupled.layer!='control'].copy();o=overlay.copy()
    keys=['run_id','month']
    if c.empty or o.empty or set(c.run_id)!=set(o.run_id):
        raise ValueError('complete matching coupled and overlay runs required')
    if c.duplicated(keys).any() or o.duplicated(keys).any():
        raise ValueError('duplicate monthly account')
    cc=['closing_unit_nav','closing_aum_usd','owner_equity_usd','external_equity_usd','subscriptions_usd','redemptions_usd','flow_transaction_cost_usd']
    oc=['nav_per_unit','closing_net_aum_usd','start_cohort_equity_usd','new_cohort_equity_usd','subscriptions_usd','new_cohort_redemptions_usd']
    if not np.isfinite(c[cc].to_numpy(float)).all() or not np.isfinite(o[oc].to_numpy(float)).all():
        raise ValueError('finite account evidence required')
    if (c.closing_unit_nav<=0).any() or (o.nav_per_unit<=0).any():
        raise ValueError('positive unit values required')
    joined=c.merge(o,on=keys,how='outer',suffixes=('_coupled','_overlay'),validate='one_to_one',indicator=True)
    if not joined['_merge'].eq('both').all() or not joined.event_date_coupled.eq(joined.event_date_overlay).all():
        raise ValueError('same actual monthly observations required')
    if not np.array_equal(joined.subscriptions_usd_coupled.to_numpy(),joined.subscriptions_usd_overlay.to_numpy()):
        raise ValueError('same gross subscriptions required')
    monthly=pd.DataFrame(dict(run_id=joined.run_id,month=joined.month,event_date=joined.event_date_coupled,
        coupled_unit_nav=joined.closing_unit_nav,overlay_unit_nav=joined.nav_per_unit,
        unit_nav_difference=joined.closing_unit_nav-joined.nav_per_unit,
        total_equity_difference_usd=joined.closing_aum_usd-joined.closing_net_aum_usd,
        owner_equity_difference_usd=joined.owner_equity_usd-joined.start_cohort_equity_usd,
        external_equity_difference_usd=joined.external_equity_usd-joined.new_cohort_equity_usd,
        redemption_difference_usd=joined.redemptions_usd-joined.new_cohort_redemptions_usd,
        coupled_flow_transaction_cost_usd=joined.flow_transaction_cost_usd))
    if returns.duplicated(['kind','run_id']).any() or headlines.run_id.duplicated().any():
        raise ValueError('unique return and headline rows required')
    ret=returns.set_index(['kind','run_id']);heads=headlines.set_index('run_id');summary=[]
    for run_id,g in monthly.groupby('run_id',sort=False):
        g=g.sort_values('month');a=ret.loc[('coupled',run_id),:];b=ret.loc[('overlay',run_id),:];h=heads.loc[run_id]
        if (a.fund_window_start,a.fund_window_end)!=(b.fund_window_start,b.fund_window_end):
            raise ValueError('same return windows required')
        if a.first_external_subscription_date!=b.first_external_subscription_date and not (pd.isna(a.first_external_subscription_date) and pd.isna(b.first_external_subscription_date)):
            raise ValueError('same first external subscription date required')
        policy,layer,plan=run_id.split('__')
        summary.append(dict(run_id=run_id,policy=policy,layer=layer,flow_plan=plan,
            start=a.fund_window_start,end=a.fund_window_end,months=len(g),
            coupled_unit_twr_annual=a.fund_unit_twr_annual,overlay_unit_twr_annual=b.fund_unit_twr_annual,
            unit_twr_difference_pp=100*(a.fund_unit_twr_annual-b.fund_unit_twr_annual),
            coupled_external_mwr_annual=a.aggregate_external_mwr_annual,overlay_external_mwr_annual=b.aggregate_external_mwr_annual,
            external_mwr_difference_pp=100*(a.aggregate_external_mwr_annual-b.aggregate_external_mwr_annual),
            coupled_mwr_status=a.mwr_status,overlay_mwr_status=b.mwr_status,
            terminal_unit_nav_difference=g.unit_nav_difference.iloc[-1],
            terminal_total_equity_difference_usd=g.total_equity_difference_usd.iloc[-1],
            terminal_owner_equity_difference_usd=g.owner_equity_difference_usd.iloc[-1],
            terminal_external_equity_difference_usd=g.external_equity_difference_usd.iloc[-1],
            gross_subscriptions_usd=h.gross_subscriptions_usd,
            coupled_flow_transaction_cost_usd=g.coupled_flow_transaction_cost_usd.sum()))
    summary=pd.DataFrame(summary);invariance=[]
    for policy,g in returns[returns.kind=='overlay'].groupby('policy',sort=False):
        values=g.fund_unit_twr_annual.to_numpy(float);spread=float(values.max()-values.min())
        if not np.isfinite(values).all() or spread>1e-10:
            raise ValueError('overlay unit return changes across the fixed-fee flow plans')
        invariance.append(dict(policy=policy,flow_labels=len(g),unit_twr_range=spread,tolerance=1e-10))
    return summary,monthly,invariance


def run_interpretation(diagnostics,output):
    diagnostics=Path(diagnostics);output=Path(output)
    if output.exists():raise FileExistsError('choose a new interpretation output directory')
    verified=verify_run(diagnostics)
    source_manifest=json.loads((diagnostics/'run_manifest.json').read_text())
    if source_manifest.get('counts',{}).get('investor_return_rows')!=46:
        raise ValueError('expected complete historical investor diagnostic run')
    captured={name:(diagnostics/name).read_bytes() for name in INPUTS}
    # Capture only declared inputs, retaining their connection to the verified parent.
    for name,data in captured.items():
        if hashlib.sha256(data).hexdigest()!=source_manifest['artifacts'][name]:
            raise ValueError('diagnostic evidence changed during capture')
    output.mkdir(parents=True);(output/'inputs').mkdir()
    for name,data in captured.items():
        p=output/'inputs'/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
    code=source_hashes();manifest=dict(schema_version=1,run_id=str(uuid.uuid4()),status='running',figures_included=False,
        started_at_utc=datetime.now(timezone.utc).isoformat(),code=code,
        scope='Postprocessing of verified historical diagnostics; no portfolio recalculation, causal attribution or final report.',
        configuration_snapshots={f'inputs/{name}':sha256(output/'inputs'/name) for name in INPUTS},
        source_run_id=verified['run_id'],source_manifest_sha256=sha256(diagnostics/'run_manifest.json'),artifacts={})
    write_json(output/'run_manifest.json',manifest)
    try:
        frames=[pd.read_csv(output/'inputs'/name,float_precision='round_trip') for name in INPUTS]
        summary,monthly,invariance=compare_accounts(*frames[:4]);manager=frames[4]
        if len(summary)!=22 or len(monthly)!=2640 or len(manager)!=48:
            raise ValueError('complete declared interpretation scope required')
        summary.to_csv(output/'coupled_overlay_comparison.csv',index=False,lineterminator='\n')
        monthly.to_csv(output/'coupled_overlay_monthly_differences.csv',index=False,lineterminator='\n')
        facts=dict(overlay_unit_return_invariance=invariance,
            manager_cases=len(manager),external_business_negative_terminal_cash_cases=int((manager.cumulative_external_business_cash_usd<0).sum()),
            external_business_terminal_cash_min_usd=float(manager.cumulative_external_business_cash_usd.min()),
            external_business_terminal_cash_max_usd=float(manager.cumulative_external_business_cash_usd.max()),
            limitations=['Hypothetical flow plans and fixed model terms, not observed fundraising or a forecast.',
                'Coupled-minus-overlay differences combine trading, fee/debt/funding and signal feedback; not additive causal attribution.',
                'Terminal total fund equity includes externally owned assets; it is not owner wealth or manager profit.',
                'Historical business horizon ends October 2024, distinct from the full backtest endpoint in August 2026.',
                'Manager budgets are outside the fund; conditional owner receipts are separate internal transfers.',
                'Acquisition/timing no-flow labels duplicate economics; label counts are not independent observations.'])
        write_json(output/'interpretation_checks.json',facts)
        lines=['# Historical Coupled Versus Overlay Evidence','','This generated note postprocesses a verified diagnostic run. It is not a final report.',
            '','The overlay holds the no-flow portfolio return path fixed. Coupled paths execute flows through positions/debt and costs, which can change later signals.',
            'Differences therefore cannot be attributed solely to subscription trading charges. Compare the same policy, plan and actual calendar.',
            '','| Policy | Layer | Plan | Coupled unit TWR | Overlay unit TWR | Difference pp | Coupled flow costs USD |',
            '|---|---|---|---:|---:|---:|---:|']
        for r in summary.itertuples(index=False):lines.append(f'| {r.policy} | {r.layer} | {r.flow_plan} | {100*r.coupled_unit_twr_annual:.4f}% | {100*r.overlay_unit_twr_annual:.4f}% | {r.unit_twr_difference_pp:+.4f} | {r.coupled_flow_transaction_cost_usd:.2f} |')
        lines+=['',f"External-business terminal cash is negative in {facts['external_business_negative_terminal_cash_cases']} of {facts['manager_cases']} manager labels at the declared budgets/receipts.",
            '',*[f'- {x}' for x in facts['limitations']],
            '', '[Paired investor/equity comparisons](coupled_overlay_comparison.csv) · [Monthly differences](coupled_overlay_monthly_differences.csv) · [Checks](interpretation_checks.json) · [Manifest](run_manifest.json)','']
        (output/'README.md').write_text('\n'.join(lines))
        if source_hashes()!=code:raise RuntimeError('source changed during interpretation')
        verify_run(diagnostics)
        if sha256(diagnostics/'run_manifest.json')!=manifest['source_manifest_sha256']:raise ValueError('source run changed')
        manifest['artifacts']={str(p.relative_to(output)):sha256(p) for p in sorted(output.rglob('*')) if p.is_file() and p.parent==output and p.name!='run_manifest.json'}
        manifest.update(status='complete',finished_at_utc=datetime.now(timezone.utc).isoformat(),counts=dict(paired_cases=len(summary),monthly_differences=len(monthly),manager_cases=len(manager)))
        write_json(output/'run_manifest.json',manifest);verify_run(output)
    except Exception as error:
        manifest.update(status='failed',failure=dict(type=type(error).__name__,message=str(error)));write_json(output/'run_manifest.json',manifest);raise
    return manifest


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--diagnostics',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    m=run_interpretation(a.diagnostics,a.output);print(json.dumps(dict(run_id=m['run_id'],status=m['status'],counts=m['counts']),indent=2))


if __name__=='__main__':main()
