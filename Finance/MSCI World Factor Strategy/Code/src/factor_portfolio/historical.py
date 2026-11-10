"""Current research policy accounting extracted from the frozen final-allocation runner.

Preserves next-observation signals, capped-relative/decoupled policies and the
original metric conventions. No raw inputs or old result-folder dependencies.
"""
from __future__ import annotations
from dataclasses import dataclass
import math
import numpy as np
import pandas as pd
from .config import SwissquoteStandardFeeSchedule
from .benchmark import investor_equity_returns, investor_drawdown, _interval_reference_returns

@dataclass
class Run:
    history: pd.DataFrame
    events: pd.DataFrame
    status: str='complete'
    initial_equity_usd: float=10000.

def simulate(ret, ref, weights, leverage=1.25, policy='hybrid20', margin=.03,
             sleeve_band=.05, leverage_band=.10, passive=False, maintenance=None,
             extra_liquidation_spread=0., fee_free=False, *, initial_equity_usd=10000., fee_schedule=None):
    """Mark, accrue previous interval funding, execute previous signals, form new signals."""
    if (not np.isfinite(initial_equity_usd) or initial_equity_usd <= 0
        or not np.isfinite(leverage) or leverage < 1 or not np.isfinite(margin) or margin < 0
        or not np.isfinite(sleeve_band) or not 0 <= sleeve_band < 1
        or not np.isfinite(leverage_band) or leverage_band < 0
        or len(weights) != len(ret.columns) or len(ret) < 2):
        raise ValueError('invalid research simulation inputs')
    capital = float(initial_equity_usd)
    assert ret.index.is_monotonic_increasing and not ret.index.has_duplicates
    assert np.isfinite(ret.to_numpy()).all() and (ret.iloc[0]==0).all() and (ret>-1).all().all()
    w=np.array(weights,dtype=float); assert (w>0).all() and abs(w.sum()-1)<1e-10
    dates=ret.index; rr=ret.to_numpy(float); n=len(dates); k=len(w)
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
            charge,g,t=trade(targetw,reset,forced)
            events.append(dict(date=d,reason=reason,fees_usd=charge,gross_trade_usd=g,turnover=t))
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
                 transaction_cost_usd=charge,financing_cost_usd=fund,pending_signal=pending)
        row.update({f'weight_{s}':v for s,v in zip(ret.columns,actual)})
        row.update({f'position_{s}_usd':v for s,v in zip(ret.columns,pos)})
        rows.append(row)
    h=pd.DataFrame(rows,index=dates[:len(rows)]);h.index.name='date'
    return Run(h,pd.DataFrame(events),status,capital)

def metrics(run, reference, market, weights=None):
    if run.status != 'complete' or market.status != 'complete':
        raise ValueError('complete common-calendar runs are required for reported risk metrics')
    capital = run.initial_equity_usd
    eq=run.history.equity_usd; r=investor_equity_returns(eq,initial_committed_capital_usd=capital)
    b=investor_equity_returns(market.history.equity_usd,initial_committed_capital_usd=market.initial_equity_usd)
    assert eq.index.equals(market.history.index)
    rf=_interval_reference_returns(eq.index,reference,day_count=360)
    y=(r-rf).to_numpy();x=(b-rf).to_numpy();n=len(y)
    X=np.column_stack([np.ones(n),x]); coef=np.linalg.lstsq(X,y,rcond=None)[0]
    resid=y-X@coef; scores=X*resid[:,None]; meat=scores.T@scores
    for lag in range(1,min(5,n-1)+1):
        cov=scores[lag:].T@scores[:-lag];meat+=(1-lag/6)*(cov+cov.T)
    inv=np.linalg.inv(X.T@X);cov=inv@meat@inv*n/(n-2)
    se=math.sqrt(max(0.,cov[0,0]))*252;alpha=coef[0]*252;beta=coef[1]
    dd=investor_drawdown(eq,initial_committed_capital_usd=capital)
    years=(eq.index[-1]-eq.index[0]).days/365.2425;cagr=(eq.iloc[-1]/capital)**(1/years)-1
    # Observed underwater spans; a final open episode is censored.
    high=capital;peak=eq.index[0];maxdays=0;current=False
    for date,value in eq.items():
        if value>=high:high=value;peak=date;current=False
        else:current=True;maxdays=max(maxdays,(date-peak).days)
    downside=math.sqrt(np.minimum(y,0).dot(np.minimum(y,0))/n*252)
    events=run.events;tr=events.iloc[1:]
    result=dict(start=str(eq.index[0].date()),end=str(eq.index[-1].date()),observations=len(eq),
        status=run.status,ending_equity_usd=float(eq.iloc[-1]),cagr=float(cagr),
        annualised_volatility=float(r.std(ddof=1)*math.sqrt(252)),maximum_drawdown=float(dd.min()),
        sharpe_ratio=float(np.mean(y)/np.std(y,ddof=1)*math.sqrt(252)),
        beta_vs_unlevered_core=float(beta),jensen_alpha=float(alpha),alpha_hac_se=float(se),
        alpha_ci_low=float(alpha-1.96*se),alpha_ci_high=float(alpha+1.96*se),
        treynor_ratio=float(np.mean(y)*252/beta) if beta>0 else None,
        sortino_ratio=float(np.mean(y)*252/downside) if downside>0 else None,
        calmar_ratio=float(cagr/abs(dd.min())) if dd.min()<0 else None,
        transaction_cost_usd=float(run.history.cumulative_transaction_cost_usd.iloc[-1]),
        financing_cost_usd=float(run.history.cumulative_financing_cost_usd.iloc[-1]),
        trades_after_entry=len(tr),gross_turnover_sum=float(tr.turnover.sum()),
        mean_leverage=float(run.history.leverage.mean()),max_pretrade_leverage=float(run.history.pretrade_leverage.max()),
        longest_observed_underwater_days=maxdays,terminal_underwater_censored=current,
        margin_calls=int((events.reason=='margin_call').sum()))
    if weights is not None:
        cols=[c for c in run.history if c.startswith('weight_')]
        dev=abs(run.history[cols].to_numpy()-np.array(weights))
        result.update(mean_absolute_sleeve_drift=float(dev.mean()),maximum_sleeve_drift=float(dev.max()))
    assert np.isclose(np.prod(1+r),eq.iloc[-1]/capital,rtol=1e-11)
    return result

