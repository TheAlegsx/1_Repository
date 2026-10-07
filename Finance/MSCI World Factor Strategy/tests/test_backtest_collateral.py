"""Analytic sale cures, cost drag, zero lending value and impossible repayment."""
import copy
import json
from pathlib import Path

import numpy as np
import pytest

from factor_portfolio import backtest_collateral as collateral
from factor_portfolio.config import FeeSchedule

ROOT=Path(__file__).resolve().parents[1]
WEIGHTS=[.6,.15,.1,.15]


def test_cost_free_sale_matches_closed_form_buffered_cure():
    r=collateral.solve_state(125.,25.,WEIGHTS,FeeSchedule(),0.,.1,0.,.9)
    expected=(25-.09*125)/(1-.09)
    assert r['status']=='sale_cures_limit' and r['sale_usd']==pytest.approx(expected,abs=1e-12)
    assert r['debt_after_sale_usd']==pytest.approx(.09*r['assets_after_sale_usd'],abs=1e-12)
    assert r['equity_after_sale_usd']==pytest.approx(100.)


def test_proportional_and_forced_costs_raise_required_sale():
    r=collateral.solve_state(125.,25.,WEIGHTS,FeeSchedule(proportional_rate=.005),0.,.1,.01,.9)
    expected=(25-.09*125)/(1-.09-.015)
    assert r['sale_usd']==pytest.approx(expected,abs=1e-12)
    assert r['sale_cost_usd']==pytest.approx(.015*expected)
    assert r['equity_after_sale_usd']==pytest.approx(100-.015*expected)


def test_zero_lending_value_requires_full_repayment_and_cost_cover():
    r=collateral.solve_state(125.,25.,WEIGHTS,FeeSchedule(proportional_rate=.005),0.,0.,0.,.9)
    assert r['status']=='sale_cures_limit' and r['sale_usd']==pytest.approx(25/.995)
    assert abs(r['debt_after_sale_usd'])<1e-12


def test_within_limit_and_exhausted_equity_are_distinct():
    fee=FeeSchedule(proportional_rate=.01)
    r=collateral.solve_state(125.,25.,WEIGHTS,fee,0.,.4,0.,.9)
    assert r['status']=='within_limit' and r['sale_usd']==r['sale_cost_usd']==0
    r=collateral.solve_state(125.,25.,WEIGHTS,fee,.8,.4,0.,.9)
    assert r['status']=='cannot_repay_after_liquidation' and r['assets_after_sale_usd']==0
    assert r['equity_after_sale_usd']<0 and r['debt_after_sale_usd']>0
    assert r['equity_after_sale_usd']==pytest.approx(-r['debt_after_sale_usd'])


def test_policy_independence_and_unchanged_main_configuration():
    b=json.loads((ROOT/'config/backtest_absolute_decoupled_2026-10-05.json').read_text())
    s=json.loads((ROOT/'config/backtest_collateral_2026-10-05.json').read_text());original=copy.deepcopy(b)
    absolute=collateral.collateral_comparison(b,s);b['primary_policy']='hybrid20'
    hybrid=collateral.collateral_comparison(b,s)
    np.testing.assert_array_equal(absolute['states'].to_numpy(),hybrid['states'].to_numpy())
    b['primary_policy']=original['primary_policy'];assert b==original
    assert len(absolute['states'])==50 and absolute['definitions']['status_counts']==dict(cannot_repay_after_liquidation=10,sale_cures_limit=34,within_limit=6)


def test_invalid_grid_and_substituted_or_escaped_evidence_are_rejected(tmp_path):
    b=json.loads((ROOT/'config/backtest_absolute_decoupled_2026-10-05.json').read_text())
    s=json.loads((ROOT/'config/backtest_collateral_2026-10-05.json').read_text());changed=copy.deepcopy(s);changed['new_lending_limits']=[.2,.2]
    with pytest.raises(ValueError,match='distinct'):collateral.validate_settings(changed,b)
    p=tmp_path/s['source']['path'];p.write_text('%PDF- static evidence fixture');s['source']['sha256']=collateral.sha256(p)
    collateral.admit_source(tmp_path,s);p.write_text('%PDF- changed')
    with pytest.raises(ValueError,match='checksum'):collateral.admit_source(tmp_path,s)
    s['source']['path']='../outside.pdf'
    with pytest.raises(ValueError,match='outside'):collateral.admit_source(tmp_path,s)
