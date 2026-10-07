"""Separate scalar accounting; imports no production model, metrics or fee code.

Adapted statically from the preserved pre-editorial independent accounting source.
Capital, reference rates and fee components replace its hard-coded globals.
"""
from __future__ import annotations

import math
import numpy as np
import pandas as pd


def charge(changes,fee,extra=0.):
    total=0.
    for amount in changes:
        value=abs(float(amount))
        if value<=1e-12:continue
        commission=190.
        for threshold,price in [(500,3),(1000,5),(2000,10),(10000,29),(15000,49),(25000,79),(50000,129)]:
            if value<=threshold:commission=price;break
        total+=commission*fee['usd_per_chf']+fee['platform_fee_usd']+value*(fee['stamp_duty_rate']+fee['spread_rate']+extra)
    return total


def calculate(levels,reference,weights,leverage,policy,*,initial_equity_usd,fee_parameters,
              margin=.03,sleeve_band=.05,leverage_band=.1,passive=False,maintenance=None,extra=0.):
    dates=levels.index;w=np.asarray(weights,float);capital=float(initial_equity_usd)
    if (not isinstance(dates,pd.DatetimeIndex) or dates.hasnans or dates.has_duplicates or not dates.is_monotonic_increasing or len(dates)<3
        or (dates[-1]-dates[0]).days<=0 or not np.isfinite(levels.to_numpy(float)).all() or (levels<=0).any().any()
        or len(w)!=len(levels.columns) or not np.isfinite(w).all() or (w<=0).any() or abs(w.sum()-1)>1e-10
        or not math.isfinite(capital) or capital<=0 or not math.isfinite(leverage) or leverage<1
        or not math.isfinite(margin) or margin<0 or not 0<=sleeve_band<1 or not math.isfinite(leverage_band) or leverage_band<0
        or policy not in ['legacy_absolute','absolute_decoupled','relative20','hybrid20','quarterly','annual','no_sleeve']):
        raise ValueError('invalid independent scalar account inputs')
    for key in ['usd_per_chf','platform_fee_usd','stamp_duty_rate','spread_rate']:
        if not math.isfinite(fee_parameters[key]) or fee_parameters[key]<0:raise ValueError('invalid independent fee parameters')
    if fee_parameters['usd_per_chf']<=0 or type(passive) is not bool:raise ValueError('invalid independent conversion/passive flag')
    if (maintenance is not None and (not math.isfinite(maintenance) or not 0<maintenance<1)) or not math.isfinite(extra) or extra<0:
        raise ValueError('invalid independent maintenance/friction')
    returns=levels.values[1:]/levels.values[:-1]-1;positions=np.zeros(len(w));debt=0.;pending='initialise'
    equities=[];fees=0.;interest=0.;trades=0;calls=0;rows=[];events=[]
    calendar=pd.date_range(dates[0],dates[-1]);rates=reference.reindex(calendar)
    if not np.isfinite(rates.to_numpy(float)).all():raise ValueError('complete finite independent funding calendar required')
    cumulative=np.r_[0.,np.cumsum(rates.to_numpy(float)+margin)];offsets=(dates-calendar[0]).days.to_numpy()
    for t,day in enumerate(dates):
        funding=0.;tradedcost=0.;reason=pending
        if t:
            positions=positions*(1+returns[t-1]);funding=debt*(cumulative[offsets[t]]-cumulative[offsets[t-1]])/360
            debt+=funding;interest+=funding
        equity=capital if t==0 else sum(positions)-debt
        if equity<=0:raise ArithmeticError('independent account insolvent')
        if pending:
            initialise=t==0;reset=initialise or 'leverage' in pending or pending=='margin_call'
            target=w if initialise or 'sleeve' in pending or policy=='legacy_absolute' else positions/sum(positions)
            if pending=='margin_call':target=positions/sum(positions);calls+=1
            before=positions.copy()
            for _ in range(100):
                assets=leverage*(equity-tradedcost) if reset else sum(positions)-tradedcost
                proposed=target*assets;nextcost=charge(proposed-positions,fee_parameters,extra if pending=='margin_call' else 0.)
                if abs(nextcost-tradedcost)<1e-10:tradedcost=nextcost;break
                tradedcost=nextcost
            else:raise ArithmeticError('independent fee convergence failed')
            if equity-tradedcost<=0:raise ArithmeticError('independent trade exhausts equity')
            assets=leverage*(equity-tradedcost) if reset else sum(positions)-tradedcost
            positions=target*assets;debt=assets-equity+tradedcost;fees+=tradedcost;trades+=not initialise
            events.append(dict(date=day,reason=reason,fees_usd=tradedcost,gross_trade_usd=float(sum(abs(positions-before)))))
        assets=sum(positions);equity=assets-debt
        if equity<=0:raise ArithmeticError('independent account insolvent after trade')
        equities.append(equity);actual=positions/assets
        if policy in ['legacy_absolute','absolute_decoupled']:hit=any(abs(actual-w)>sleeve_band+1e-12)
        elif policy in ['hybrid20','relative20']:hit=any(abs(actual-w)>(np.minimum(.05,.2*w) if policy=='hybrid20' else .2*w)+1e-12)
        elif policy in ['annual','quarterly']:hit=t<len(dates)-1 and day.month!=dates[t+1].month and (day.month==12 if policy=='annual' else day.month in [3,6,9,12])
        else:hit=False
        leverage_hit=leverage>1 and not passive and abs(assets/equity-leverage)>leverage_band+1e-12
        if maintenance is not None and debt/assets>maintenance+1e-12:pending='margin_call'
        elif policy=='legacy_absolute' and leverage_hit:pending='leverage'
        elif hit and leverage_hit:pending='sleeve+leverage'
        else:pending='sleeve' if hit else 'leverage' if leverage_hit else ''
        record=dict(date=day,equity_usd=equity,gross_assets_usd=assets,debt_usd=debt,leverage=assets/equity,
            transaction_cost_usd=tradedcost,financing_cost_usd=funding,cumulative_transaction_cost_usd=fees,cumulative_financing_cost_usd=interest,pending_signal=pending)
        record.update({f'position_{name}_usd':float(value) for name,value in zip(levels.columns,positions)})
        rows.append(record)
    values=np.asarray(equities);r=values[1:]/values[:-1]-1;r[0]=values[1]/capital-1
    dd=values/np.maximum.accumulate(np.r_[capital,values])[1:]-1
    result=dict(ending_equity_usd=float(values[-1]),cagr=float((values[-1]/capital)**(365.2425/(dates[-1]-dates[0]).days)-1),
        maximum_drawdown=float(dd.min()),annualised_volatility=float(r.std(ddof=1)*np.sqrt(252)),
        transaction_cost_usd=float(fees),financing_cost_usd=float(interest),trades_after_entry=int(trades),margin_calls=int(calls))
    return result,pd.DataFrame(rows),pd.DataFrame(events)
