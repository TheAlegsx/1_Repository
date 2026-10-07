"""Single-state lending-limit contraction with proportional liquidation costs."""
from __future__ import annotations

import math
from pathlib import Path

import pandas as pd

from .config import SwissquoteStandardFeeSchedule
from .inflow_workflow import sha256

MEASUREMENT = dict(state='prefee target gross assets/debt from configured initial equity and primary leverage',
    price_shock='uniform instantaneous asset loss; debt unchanged',
    sales='proportional target sleeve mixture; no external cash',
    fees='baseline per-leg trade cost plus optional extra forced spread',
    cure='debt after sale costs <= safety fraction * new lending limit * remaining assets',
    timing='single state; no financing accrual, settlement or historical path',
    iterations=80, branch_tolerance_usd=1e-7, cure_check_tolerance_usd=1e-6)


def validate_settings(settings,baseline):
    if settings['schema_version']!=1 or settings['measurement']!=MEASUREMENT:
        raise ValueError('unsupported collateral diagnostic contract')
    for key in ['market_losses','new_lending_limits','extra_forced_spreads']:
        values=settings[key]
        if not values or len(set(values))!=len(values) or any(not math.isfinite(x) or not 0<=x<1 for x in values):
            raise ValueError('invalid distinct collateral grid: '+key)
    if not math.isfinite(settings['safety_fraction']) or not 0<settings['safety_fraction']<=1:
        raise ValueError('collateral safety fraction must be in (0,1]')
    if baseline.get('primary_leverage',max(baseline['leverage_levels']))<=1:
        raise ValueError('collateral diagnostic requires a borrowed initial target')
    if settings['source']['path']!='swissquote_collateral_agreement.pdf':
        raise ValueError('unexpected preserved collateral evidence filename')


def admit_source(raw_root,settings):
    root=Path(raw_root).resolve();item=settings['source'];path=(root/item['path']).resolve()
    if not path.is_relative_to(root) or not path.is_file():raise ValueError('collateral evidence missing or outside declared raw root')
    if sha256(path)!=item['sha256']:raise ValueError('collateral evidence checksum mismatch')
    if path.read_bytes()[:5]!=b'%PDF-':raise ValueError('collateral evidence is not a PDF')
    return path


def solve_state(assets,debt,weights,fee,loss,limit,extra,safety):
    a=assets*(1-loss);d=debt;cure=safety*limit
    def cost(s):return sum(fee.cost(s*x) for x in weights)+extra*s
    def breach(s):return d-s+cost(s)-cure*(a-s)
    if breach(0)<=MEASUREMENT['branch_tolerance_usd']:
        sale=0.;status='within_limit'
    elif breach(a)>MEASUREMENT['branch_tolerance_usd']:
        sale=a;status='cannot_repay_after_liquidation'
    else:
        lo,hi=0.,a
        for _ in range(MEASUREMENT['iterations']):
            middle=(lo+hi)/2
            if breach(middle)>0:lo=middle
            else:hi=middle
        sale=hi;status='sale_cures_limit'
    charges=cost(sale);cash=d-sale+charges;equity=a-d-charges
    if status=='sale_cures_limit' and (breach(sale)>MEASUREMENT['cure_check_tolerance_usd'] or equity<=0):
        raise ValueError('collateral sale does not produce a solvent buffered cure')
    result=dict(market_loss=loss,new_lending_limit=limit,safety_fraction=safety,extra_forced_spread=extra,
        assets_before_sale_usd=a,debt_before_sale_usd=d,sale_usd=sale,sale_cost_usd=charges,
        assets_after_sale_usd=a-sale,debt_after_sale_usd=max(cash,0),equity_after_sale_usd=equity,status=status)
    if abs(result['equity_after_sale_usd']-(result['assets_after_sale_usd']-result['debt_after_sale_usd']))>1e-6:
        raise ValueError('collateral post-sale balance identity does not reconcile')
    return result


def collateral_comparison(baseline,settings):
    validate_settings(settings,baseline)
    capital=float(baseline['initial_equity_usd']);leverage=baseline.get('primary_leverage',max(baseline['leverage_levels']))
    assets=capital*leverage;debt=assets-capital;weights=list(baseline['target_weights'].values())
    fee=SwissquoteStandardFeeSchedule(**baseline['fee_schedule']);rows=[]
    for loss in settings['market_losses']:
        for limit in settings['new_lending_limits']:
            for extra in settings['extra_forced_spreads']:
                rows.append(solve_state(assets,debt,weights,fee,loss,limit,extra,settings['safety_fraction']))
    table=pd.DataFrame(rows)
    return dict(states=table,definitions=dict(measurement=MEASUREMENT,source=settings['source'],
        initial_equity_usd=capital,initial_gross_assets_usd=assets,initial_debt_usd=debt,
        target_weights=baseline['target_weights'],primary_leverage=leverage,primary_rule_not_changed=True,
        status_counts={str(k):int(v) for k,v in table.groupby('status').size().items()},
        interpretation=settings['interpretation']))
