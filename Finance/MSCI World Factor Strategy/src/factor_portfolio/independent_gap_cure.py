"""Independent piecewise-linear liquidation solution; no production imports."""
from __future__ import annotations

import math
from .independent_scalar import charge


def solve_gap(capital, maintenance, loss, weights, leverage, fee, extra):
    """Solve each possible commission interval analytically, including fee steps."""
    if (not all(math.isfinite(x) for x in [capital,maintenance,loss,leverage,extra,*weights])
        or capital<=0 or not 0<maintenance<1 or not 0<=loss<1 or leverage<1 or extra<0
        or not weights or min(weights)<=0 or abs(sum(weights)-1)>1e-10):
        raise ValueError('invalid independent gap inputs')
    assets=capital/(1-maintenance)*(1-loss);debt=capital/(1-maintenance)*maintenance;equity=assets-debt
    row=dict(post_gap_equity=equity,status='insolvent_before_cure',cure_sale_usd=None,
        liquidation_cost_usd=None,post_cure_debt_usd=None)
    if equity<=0:return row
    intercept=assets-leverage*equity
    if intercept<=0:return dict(row,status='cured_at_assumed_next_NAV',cure_sale_usd=0.,liquidation_cost_usd=0.,post_cure_debt_usd=debt)
    slope=fee['stamp_duty_rate']+fee['spread_rate']+extra
    if leverage*slope>=1:raise ArithmeticError('no stable independent liquidation solution')
    boundaries=sorted({0.,*[limit/w for w in weights for limit in [500,1000,2000,10000,15000,25000,50000]],math.inf})
    for lo,hi in zip(boundaries[:-1],boundaries[1:]):
        probe=(lo+hi)/2 if math.isfinite(hi) else lo+max(1.,lo)
        fixed=charge([probe*w for w in weights],fee)-probe*(fee['stamp_duty_rate']+fee['spread_rate'])
        sale=(intercept+leverage*fixed)/(1-leverage*slope)
        if not lo<sale<=hi:continue
        cost=charge([sale*w for w in weights],fee)+sale*extra
        residual=sale-max(assets-leverage*(equity-cost),0.)
        if abs(residual)>1e-6+2e-12*abs(sale):continue
        if equity-cost<=0:return dict(row,status='insolvent_after_liquidation_costs',cure_sale_usd=sale)
        return dict(row,status='cured_at_assumed_next_NAV',cure_sale_usd=sale,
            liquidation_cost_usd=cost,post_cure_debt_usd=(leverage-1)*(equity-cost))
    raise ArithmeticError('independent fee-step liquidation solution missing')
