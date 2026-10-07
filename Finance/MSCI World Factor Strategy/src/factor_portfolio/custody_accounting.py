"""Isolated custody sensitivity; main historical accounting remains immutable."""
from __future__ import annotations

import math
import numpy as np
import pandas as pd

from .config import SwissquoteStandardFeeSchedule
from .historical import Run

MODES=['none','private_full','private_excess','legal_entity']
DEFAULT_RATES=dict(private_base_chf=50.,private_quarterly_rate=.000075,private_threshold_chf=1e6,
    entity_quarterly_rate=.00025,entity_minimum_chf=20.,vat_multiplier=1.081)


def validate_rates(rates):
    if set(rates)!=set(DEFAULT_RATES) or any(not math.isfinite(v) or v<0 for v in rates.values()):
        raise ValueError('invalid custody rate contract')
    if rates['vat_multiplier']<1 or rates['private_quarterly_rate']>=1 or rates['entity_quarterly_rate']>=1:
        raise ValueError('invalid custody percentage/VAT')


def quarter_charge_dates(dates):
    charges={}
    for quarter in dates.to_period('Q').unique():
        begin=max(dates[0],quarter.start_time.normalize());end=min(dates[-1],quarter.end_time.normalize())
        fraction=((end-begin).days+1)/((quarter.end_time.normalize()-quarter.start_time.normalize()).days+1)
        charges[dates[dates.to_period('Q')==quarter][-1]]=fraction
    return charges


def quarter_amount(assets,mode,rates,fx):
    if mode=='none':return 0.
    if mode=='private_full':amount=rates['private_base_chf']*fx+rates['private_quarterly_rate']*assets
    elif mode=='private_excess':amount=rates['private_base_chf']*fx+rates['private_quarterly_rate']*max(assets-rates['private_threshold_chf']*fx,0.)
    elif mode=='legal_entity':amount=max(rates['entity_minimum_chf']*fx,rates['entity_quarterly_rate']*assets)
    else:raise ValueError('unsupported custody mode')
    return amount*rates['vat_multiplier']


def simulate_custody(ret, ref, weights, leverage=1.25, policy='hybrid20', margin=.03,
             sleeve_band=.05, leverage_band=.10, passive=False, maintenance=None,
             extra_liquidation_spread=0., fee_free=False, *, initial_equity_usd=10000., fee_schedule=None, custody_mode="none", custody_rates=None, custody_fx_usd_per_chf=1.):
    """Mark, accrue previous interval funding, execute previous signals, form new signals."""
    if (not np.isfinite(initial_equity_usd) or initial_equity_usd <= 0
        or not np.isfinite(leverage) or leverage < 1 or not np.isfinite(margin) or margin < 0
        or not np.isfinite(sleeve_band) or not 0 <= sleeve_band < 1
        or not np.isfinite(leverage_band) or leverage_band < 0
        or len(weights) != len(ret.columns) or len(ret) < 2):
        raise ValueError('invalid research simulation inputs')
    if custody_mode not in MODES:raise ValueError('unsupported custody mode')
    custody_rates=DEFAULT_RATES if custody_rates is None else custody_rates
    validate_rates(custody_rates)
    if not math.isfinite(custody_fx_usd_per_chf) or custody_fx_usd_per_chf<=0:raise ValueError('invalid custody FX')
    capital = float(initial_equity_usd)
    assert ret.index.is_monotonic_increasing and not ret.index.has_duplicates
    assert np.isfinite(ret.to_numpy()).all() and (ret.iloc[0]==0).all() and (ret>-1).all().all()
    w=np.array(weights,dtype=float); assert (w>0).all() and abs(w.sum()-1)<1e-10
    dates=ret.index
    charge_dates=quarter_charge_dates(dates) if custody_mode!='none' else {}
    custody_total=0.
    rr=ret.to_numpy(float); n=len(dates); k=len(w)
    cal=pd.date_range(dates[0],dates[-1]); rates=ref.reindex(cal)
    assert rates.notna().all()
    # Every interval uses rates on [prior date,current date), ACT360.
    daily=rates.to_numpy(float)+margin
    cumulative=np.r_[0.,np.cumsum(daily)]
    offsets=(dates-cal[0]).days.to_numpy(); accrual=np.zeros(n)
    accrual[1:]=(cumulative[offsets[1:]]-cumulative[offsets[:-1]])/360
    fee=SwissquoteStandardFeeSchedule() if fee_schedule is None else fee_schedule; events=[]; pos=np.zeros(k); debt=0.; pending=''
    cumfee=0.; cumfund=0.; rows=[]; status='complete'
    def costs(delta,forced=False):
        if fee_free:return 0.
        total=0.
        for x in delta:
            total+=fee.cost(float(x))
        if forced:total+=float(np.abs(delta).sum())*extra_liquidation_spread
        return total
    def trade(targetw,reset,forced=False):
        nonlocal pos,debt,cumfee
        assets=pos.sum(); eq=capital if not rows else assets-debt
        charge=0.
        for _ in range(100):
            e=eq-charge
            if e<=0:raise ArithmeticError('insolvent after trade costs')
            a=leverage*e if reset else assets-charge
            target=targetw*a
            new=costs(target-pos,forced)
            if abs(new-charge)<=1e-10:charge=new;break
            charge=new
        else:raise ArithmeticError('cost solver convergence')
        e=eq-charge; a=leverage*e if reset else assets-charge
        target=targetw*a; delta=target-pos
        assert abs(costs(delta,forced)-charge)<1e-7
        olddebt=debt; debt=a-e
        if not reset:assert abs(olddebt-debt)<1e-7
        gross=float(np.abs(delta).sum())
        turnover=gross/assets if assets else 0.
        pos=target;cumfee+=charge
        return charge,gross,turnover
    c,g,t=trade(w,True);cumfee=c
    events.append(dict(date=dates[0],reason='initialise',fees_usd=c,gross_trade_usd=g,turnover=0.))
    for i,d in enumerate(dates):
        fund=0.;charge=c if i==0 else 0.;reason=''
        if i:
            pos*=1+rr[i];fund=debt*accrual[i];debt+=fund;cumfund+=fund
        custody_charge=0.
        if d in charge_dates:
            assets=float(pos.sum())
            custody_charge=quarter_amount(assets,custody_mode,custody_rates,custody_fx_usd_per_chf)*charge_dates[d]
            custody_total+=custody_charge
            if leverage>1:debt+=custody_charge
            else:
                sale=custody_charge
                for _ in range(100):
                    delta=pos/assets*sale;new=custody_charge+costs(delta)
                    if abs(new-sale)<1e-8:sale=new;break
                    sale=new
                else:raise ArithmeticError('custody sale convergence')
                salecharge=costs(pos/assets*sale)
                assert abs(sale-custody_charge-salecharge)<1e-6
                pos*=1-sale/assets;cumfee+=salecharge;charge+=salecharge
                events.append(dict(date=d,reason='custody_sale',fees_usd=salecharge,gross_trade_usd=sale,turnover=sale/assets))
        assets=float(pos.sum());eq=assets-debt
        if eq<=0:
            status='insolvent';break
        prelev=assets/eq;preltv=debt/assets
        if i and pending:
            reason=pending
            targetw=w if 'sleeve' in pending or policy=='legacy_absolute' else pos/assets
            forced=pending=='margin_call'
            if forced:targetw=pos/assets
            reset=forced or 'leverage' in pending
            trade_charge,g,t=trade(targetw,reset,forced);charge+=trade_charge
            events.append(dict(date=d,reason=reason,fees_usd=trade_charge,gross_trade_usd=g,turnover=t))
            pending=''
        assets=float(pos.sum());eq=assets-debt;lev=assets/eq;actual=pos/assets
        assert eq>0 and debt>=-1e-7 and abs(eq-(assets-debt))<1e-7
        sleeve=False; leverage_hit=False
        if policy in ('legacy_absolute','absolute_decoupled'):
            sleeve=bool((abs(actual-w)>sleeve_band+1e-12).any())
        elif policy=='relative20':sleeve=bool((abs(actual-w)>.2*w+1e-12).any())
        elif policy=='hybrid20':sleeve=bool((abs(actual-w)>np.minimum(.05,.2*w)+1e-12).any())
        elif policy in ('quarterly','annual'):
            monthend=i<n-1 and d.to_period('M')!=dates[i+1].to_period('M')
            sleeve=monthend and (d.month in (3,6,9,12) if policy=='quarterly' else d.month==12)
        elif policy!='no_sleeve':raise ValueError(policy)
        if leverage>1 and not passive:
            leverage_hit=abs(lev-leverage)>leverage_band+1e-12
        if maintenance is not None and debt/assets>maintenance+1e-12:pending='margin_call'
        elif policy=='legacy_absolute' and leverage_hit:pending='leverage'
        elif sleeve and leverage_hit:pending='sleeve+leverage'
        elif leverage_hit:pending='leverage'
        elif sleeve:pending='sleeve'
        row=dict(equity_usd=eq,gross_assets_usd=assets,debt_usd=debt,leverage=lev,
                 pretrade_leverage=prelev,pretrade_debt_to_assets=preltv,
                 cumulative_transaction_cost_usd=cumfee,cumulative_financing_cost_usd=cumfund,
                 transaction_cost_usd=charge,financing_cost_usd=fund,pending_signal=pending,custody_cost_usd=custody_charge,cumulative_custody_cost_usd=custody_total)
        row.update({f'weight_{s}':v for s,v in zip(ret.columns,actual)})
        row.update({f'position_{s}_usd':v for s,v in zip(ret.columns,pos)})
        rows.append(row)
    h=pd.DataFrame(rows,index=dates[:len(rows)]);h.index.name='date'
    return Run(h,pd.DataFrame(events),status,capital)
