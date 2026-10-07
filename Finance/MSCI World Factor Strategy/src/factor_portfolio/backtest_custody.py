"""Full-path quarterly custody sensitivities for the primary and legacy policies."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .config import SwissquoteStandardFeeSchedule
from .custody_accounting import MODES, validate_rates, simulate_custody, quarter_charge_dates
from .historical import simulate, metrics
from .inflow_workflow import sha256

MEASUREMENT=dict(period='full',valuation='marked gross invested assets before pending trades',
    charge_date='last observed common NAV in each calendar quarter',
    proration='inclusive calendar days; opening/closing stubs use declared data endpoints',
    payment='borrowed exposure: add to debt; unlevered: proportional asset sale including original costs',
    ordering='mark and accrue funding, charge custody, execute prior signal, form next signal',
    private_base='CHF50 quarterly capped-bracket simplification at this capital scale',
    fee_type='current-tariff hypothetical sensitivity; no administration-fee revenue',
    transaction_sale_iterations=100,transaction_sale_tolerance_usd=1e-8)


def validate_settings(settings,baseline):
    if settings['schema_version']!=1 or settings['measurement']!=MEASUREMENT or settings['modes']!=MODES:
        raise ValueError('unsupported custody study contract')
    policies=settings['factor_policies']
    if len(set(policies))!=len(policies) or not policies or 'hybrid20' not in policies or baseline.get('primary_policy','hybrid20') not in policies or any(p not in baseline['policies'] for p in policies):
        raise ValueError('custody policies must include selected primary and legacy comparison')
    if settings['leverage_levels']!=baseline['leverage_levels']:
        raise ValueError('custody exposures must match the selected baseline controls')
    validate_rates(settings['rates'])
    if settings['source']['path']!='swissquote_account_fees.html':raise ValueError('unexpected custody evidence filename')


def admit_source(raw_root,settings):
    root=Path(raw_root).resolve();item=settings['source'];path=(root/item['path']).resolve()
    if not path.is_relative_to(root) or not path.is_file():raise ValueError('custody evidence missing or outside declared raw root')
    if sha256(path)!=item['sha256']:raise ValueError('custody evidence checksum mismatch')
    return path


def custody_comparison(returns,reference,baseline,settings):
    validate_settings(settings,baseline);bounds=baseline['periods']['full'];ret=returns.loc[bounds['start']:bounds['end']].copy();ret.iloc[0]=0
    fee=SwissquoteStandardFeeSchedule(**baseline['fee_schedule']);capital=baseline['initial_equity_usd'];sleeves=list(baseline['target_weights']);weights=list(baseline['target_weights'].values())
    kwargs=dict(margin=baseline['borrowing_margin_annual'],sleeve_band=baseline['sleeve_band'],leverage_band=baseline['leverage_band'],initial_equity_usd=capital,fee_schedule=fee)
    benchmark=simulate(ret[['core']],reference,[1.],1.,'no_sleeve',**kwargs)
    rows=[];curves={};events=[];ledgers=[];histories={};checks=[];legacy_labels={};legacy_ids=[]
    for lev in settings['leverage_levels']:
        cases=[('factor',p,sleeves,weights) for p in settings['factor_policies']]+[('core','no_sleeve',['core'],[1.]),('dimensional','no_sleeve',['dimensional'],[1.])]
        for strategy,policy,columns,target in cases:
            base=simulate(ret[columns],reference,target,lev,policy,**kwargs)
            for mode in settings['modes']:
                run=simulate_custody(ret[columns],reference,target,lev,policy,custody_mode=mode,
                    custody_rates=settings['rates'],custody_fx_usd_per_chf=fee.usd_per_chf,**kwargs)
                if run.status!='complete':raise ValueError('incomplete custody path; full-period comparison rejected')
                h=run.history
                np.testing.assert_allclose(h.equity_usd,h.gross_assets_usd-h.debt_usd,rtol=0,atol=1e-7)
                for flow,total,tolerance in [('custody_cost_usd','cumulative_custody_cost_usd',1e-7),('transaction_cost_usd','cumulative_transaction_cost_usd',1e-6),('financing_cost_usd','cumulative_financing_cost_usd',1e-5)]:
                    if abs(h[flow].sum()-h[total].iloc[-1])>=tolerance:raise ValueError('custody path cumulative ledger fails: '+flow)
                if abs(run.events.fees_usd.sum()-h.cumulative_transaction_cost_usd.iloc[-1])>=1e-6:raise ValueError('custody trade event charges do not reconcile')
                if mode=='none':
                    pd.testing.assert_frame_equal(h[base.history.columns],base.history,check_exact=True)
                    pd.testing.assert_frame_equal(run.events,base.events,check_exact=True)
                    checks.append(dict(strategy=strategy,policy=policy,leverage=lev,no_custody_exact_original=True))
                rows.append(dict(strategy=strategy,policy=policy,leverage=lev,custody_mode=mode,
                    **metrics(run,reference,benchmark,target),custody_cost_usd=float(h.cumulative_custody_cost_usd.iloc[-1])))
                label=f'factor_{policy}_{lev:.2f}_{mode}' if strategy=='factor' else f'{strategy}_{lev:.2f}_{mode}'
                curves[label]=h.equity_usd;events.append(run.events.assign(run_id=label))
                ledger=h[h.custody_cost_usd>0][['gross_assets_usd','debt_usd','equity_usd','custody_cost_usd','cumulative_custody_cost_usd']].reset_index().assign(run_id=label)
                ledgers.append(ledger)
                if strategy=='factor' and policy==baseline.get('primary_policy','hybrid20') and mode!='none':histories[label+'_history.csv']=h.reset_index()
                if strategy!='factor' or policy=='hybrid20':
                    legacy_labels[label]=f'{strategy}_{lev:.2f}_{mode}';legacy_ids.append(label)
    table=pd.DataFrame(rows);curve_table=pd.DataFrame(curves).rename_axis('date');event_table=pd.concat(events,ignore_index=True);ledger_table=pd.concat(ledgers,ignore_index=True)
    old_metrics=table[(table.strategy!='factor')|table.policy.eq('hybrid20')].drop(columns='policy')
    def legacy_frame(frame):
        f=frame[frame.run_id.isin(legacy_ids)].copy();f['run_id']=f.run_id.map(legacy_labels);return f
    return dict(metrics=table,curves=curve_table,events=event_table,ledger=ledger_table,histories=histories,
        legacy_metrics=old_metrics,legacy_curves=curve_table[legacy_ids].rename(columns=legacy_labels),
        legacy_events=legacy_frame(event_table),legacy_ledger=legacy_frame(ledger_table),
        definitions=dict(measurement=MEASUREMENT,rates=settings['rates'],source=settings['source'],fx_usd_per_chf=fee.usd_per_chf,
            no_custody_checks=checks,quarter_charge_fractions={str(k.date()):v for k,v in quarter_charge_dates(ret.index).items()},
            interpretation=settings['interpretation'],main_accounting_unchanged=True))
