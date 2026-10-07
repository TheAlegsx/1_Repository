"""Isolated portfolio/cohort accounting with dated net-flow trades."""
from __future__ import annotations

from dataclasses import dataclass
import math
import numpy as np
import pandas as pd

from .config import SwissquoteStandardFeeSchedule
from .historical import Run


@dataclass
class CoupledRun(Run):
    monthly: pd.DataFrame|None=None


def flow_target(positions,debt,net_flow,cost_function):
    """Scale at pre-cost leverage, then debt-fund actual trade expenses.

    Fee steps can make an exact post-cost leverage fixed point nonexistent.
    Cost-induced drift feeds the unchanged next-signal rule instead.
    """
    assets=float(positions.sum());equity=assets-debt
    if equity<=0 or assets<=0:raise ArithmeticError('insolvent before flow adjustment')
    if net_flow==0:return positions.copy(),debt,0.,0.
    leverage=assets/equity;mix=positions/assets
    if equity+net_flow<=0:raise ArithmeticError('flow adjustment exhausts fund equity')
    delta=mix*(leverage*net_flow);target=positions+delta;charge=cost_function(delta)
    if debt<=0 and charge>0:raise ValueError('paid flow trades in this pilot require positive borrowed debt')
    new_debt=debt+(leverage-1)*net_flow+charge
    if float(target.sum())-new_debt<=0:raise ArithmeticError('flow trade costs exhaust fund equity')
    return target,new_debt,charge,float(np.abs(delta).sum())


def validate_flows(flows,dates):
    required={'event_date','month','project_year','scheduled_subscription_usd','monthly_external_unit_redemption_fraction','proposed_fund_fee_fraction'}
    if not required.issubset(flows):raise ValueError('dated flow accounting fields missing')
    frame=flows.copy();frame['event_date']=pd.to_datetime(frame.event_date)
    if not frame.event_date.is_unique or not frame.event_date.is_monotonic_increasing or not set(frame.event_date).issubset(set(dates)) or (frame.event_date<=dates[0]).any():
        raise ValueError('flows require distinct ordered valuation dates after inception')
    for column in ['scheduled_subscription_usd','monthly_external_unit_redemption_fraction','proposed_fund_fee_fraction']:
        values=frame[column].to_numpy(float)
        if not np.isfinite(values).all() or (values<0).any() or (column!='scheduled_subscription_usd' and (values>=1).any()):raise ValueError('invalid flow amount/fraction')
    return {r.event_date:r for r in frame.itertuples(index=False)}


def simulate_coupled(ret, ref, weights, leverage=1.25, policy='hybrid20', margin=.03,
             sleeve_band=.05, leverage_band=.10, passive=False, maintenance=None,
             extra_liquidation_spread=0., fee_free=False, *, initial_equity_usd=10000., fee_schedule=None, flows=None, initial_unit_nav=100.):
    """Mark, accrue previous interval funding, execute previous signals, form new signals."""
    if (not np.isfinite(initial_equity_usd) or initial_equity_usd <= 0
        or not np.isfinite(leverage) or leverage < 1 or not np.isfinite(margin) or margin < 0
        or not np.isfinite(sleeve_band) or not 0 <= sleeve_band < 1
        or not np.isfinite(leverage_band) or leverage_band < 0
        or len(weights) != len(ret.columns) or len(ret) < 2):
        raise ValueError('invalid research simulation inputs')
    if not math.isfinite(initial_unit_nav) or initial_unit_nav<=0:raise ValueError('positive initial unit NAV required')
    capital = float(initial_equity_usd)
    owner_units=capital/initial_unit_nav;external_units=0.
    flow_events={} if flows is None else validate_flows(flows,ret.index)
    monthly_rows=[];cum_contributions=capital;cum_profit=0.;cum_fund_fee=0.
    period_pnl=period_financing=period_trade=0.
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
    period_opening=float(pos.sum())-debt
    prior_event_nav=period_opening/owner_units
    prior_event_date=dates[0]
    for i,d in enumerate(dates):
        fund=0.;charge=c if i==0 else 0.;reason='';price_pnl=0.;fund_fee_charge=0.;net_flow=0.;monthly=None
        if i:
            price_pnl=float((pos*rr[i]).sum());pos*=1+rr[i];fund=debt*accrual[i];debt+=fund;cumfund+=fund
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
        if d in flow_events:
            event=flow_events[d];units_before=owner_units+external_units
            owner_fee=owner_units*prior_event_nav*event.proposed_fund_fee_fraction
            external_fee=external_units*prior_event_nav*event.proposed_fund_fee_fraction
            fund_fee_charge=owner_fee+external_fee;cum_fund_fee+=fund_fee_charge
            opening_external=external_units*prior_event_nav
            if fund_fee_charge:
                if leverage>1:debt+=fund_fee_charge
                else:
                    a=float(pos.sum());sale=fund_fee_charge
                    for _ in range(100):
                        updated=fund_fee_charge+costs(pos/a*sale)
                        if abs(updated-sale)<1e-8:sale=updated;break
                        sale=updated
                    else:raise ArithmeticError('fund fee sale convergence')
                    fee_sale_charge=costs(pos/a*sale);pos*=1-sale/a;cumfee+=fee_sale_charge;charge+=fee_sale_charge
                    events.append(dict(date=d,reason='fund_fee_sale',fees_usd=fee_sale_charge,gross_trade_usd=sale,turnover=sale/a))
            a=float(pos.sum());equity_before_flow=a-debt
            if equity_before_flow<=0:raise ArithmeticError('fund fee exhausts equity')
            quote_nav=equity_before_flow/units_before
            redeemed_units=external_units*event.monthly_external_unit_redemption_fraction
            redemption=redeemed_units*quote_nav;subscription=event.scheduled_subscription_usd
            subscribed_units=subscription/quote_nav
            external_units=external_units-redeemed_units+subscribed_units
            net_flow=subscription-redemption
            target,new_debt,flow_charge,gross_flow=flow_target(pos,debt,net_flow,costs)
            pos=target;debt=new_debt;cumfee+=flow_charge;charge+=flow_charge
            if net_flow!=0:events.append(dict(date=d,reason='capital_flow',fees_usd=flow_charge,gross_trade_usd=gross_flow,turnover=gross_flow/a))
            equity_after=float(pos.sum())-debt;nav_after=equity_after/(owner_units+external_units)
            monthly=dict(month=event.month,project_year=event.project_year,event_date=d,period_start=prior_event_date,
                opening_aum_usd=period_opening,opening_external_aum_usd=opening_external,
                subscriptions_usd=subscription,redemptions_usd=redemption,net_flow_usd=net_flow,
                owner_fee_usd=owner_fee,external_fee_usd=external_fee,fund_fee_usd=fund_fee_charge,
                flow_transaction_cost_usd=flow_charge,quote_unit_nav=quote_nav,closing_unit_nav=nav_after,
                owner_units=owner_units,external_units=external_units,redeemed_external_units=redeemed_units,
                subscribed_external_units=subscribed_units,closing_aum_usd=equity_after,
                owner_equity_usd=owner_units*nav_after,external_equity_usd=external_units*nav_after)
            prior_event_nav=nav_after;prior_event_date=d
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
        cum_contributions+=net_flow;cum_profit+=price_pnl-fund-charge-fund_fee_charge
        period_pnl+=price_pnl;period_financing+=fund
        if i:period_trade+=charge
        if not math.isclose(eq,cum_contributions+cum_profit,rel_tol=2e-12,abs_tol=1e-6):raise ArithmeticError('coupled cumulative equity identity fails')
        nav=eq/(owner_units+external_units)
        row.update(unit_nav=nav,owner_units=owner_units,external_units=external_units,
            owner_equity_usd=owner_units*nav,external_equity_usd=external_units*nav,
            net_capital_flow_usd=net_flow,fund_fee_usd=fund_fee_charge,
            cumulative_fund_fee_usd=cum_fund_fee,cumulative_net_contributions_usd=cum_contributions,
            cumulative_net_investment_profit_usd=cum_profit)
        if monthly is not None:
            expected=period_opening+period_pnl-period_financing-period_trade-fund_fee_charge+net_flow
            if not math.isclose(eq,expected,rel_tol=2e-12,abs_tol=1e-6):raise ArithmeticError('coupled monthly balance identity fails')
            monthly.update(investment_price_pnl_usd=period_pnl,financing_cost_usd=period_financing,
                transaction_cost_usd=period_trade,cumulative_net_contributions_usd=cum_contributions,
                cumulative_net_investment_profit_usd=cum_profit)
            monthly_rows.append(monthly);period_opening=eq;period_pnl=period_financing=period_trade=0.
        rows.append(row)
    h=pd.DataFrame(rows,index=dates[:len(rows)]);h.index.name='date'
    return CoupledRun(h,pd.DataFrame(events),status,capital,pd.DataFrame(monthly_rows))
