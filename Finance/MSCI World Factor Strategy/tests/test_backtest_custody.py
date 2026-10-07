"""Quarter proration, financed versus sold expenses and unchanged no-fee paths."""
import copy
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from factor_portfolio.config import FeeSchedule
from factor_portfolio.historical import simulate
from factor_portfolio.custody_accounting import simulate_custody,quarter_charge_dates,quarter_amount,DEFAULT_RATES
from factor_portfolio import backtest_custody as custody

ROOT=Path(__file__).resolve().parents[1]
WEIGHTS=[.6,.15,.1,.15]


def fixture(dates):
    dates=pd.DatetimeIndex(dates,name='date')
    ret=pd.DataFrame(0.,index=dates,columns=['core','momentum','quality','value'])
    ref=pd.Series(0.,index=pd.date_range(dates[0],dates[-1]));return ret,ref


def test_quarter_end_observation_and_calendar_stub_days():
    dates=pd.DatetimeIndex(['2014-10-03','2014-12-30','2015-03-30','2015-04-01'])
    charges=quarter_charge_dates(dates)
    assert charges[dates[1]]==pytest.approx(90/92)
    assert charges[dates[2]]==1 and charges[dates[3]]==pytest.approx(1/91)
    assert dates[0] not in charges


def test_full_excess_threshold_vat_and_entity_minimum():
    rates=DEFAULT_RATES;fx=1.2;assets=2e6
    full=quarter_amount(assets,'private_full',rates,fx);excess=quarter_amount(assets,'private_excess',rates,fx)
    assert full-excess==pytest.approx(.000075*1e6*fx*1.081)
    assert quarter_amount(10000.,'legal_entity',rates,fx)==pytest.approx(20*fx*1.081)
    assert quarter_amount(assets,'none',rates,fx)==0


def test_none_exactly_matches_main_history_and_events_for_both_policies():
    dates=pd.bdate_range('2020-01-02',periods=80);ret,ref=fixture(dates)
    for i,c in enumerate(ret):ret[c]=.001+.008*np.sin(np.arange(80)/3+i)
    ret.iloc[0]=0
    for policy in ['absolute_decoupled','hybrid20']:
        for lev in [1.,1.25]:
            base=simulate(ret,ref,WEIGHTS,lev,policy,initial_equity_usd=100000.)
            run=simulate_custody(ret,ref,WEIGHTS,lev,policy,initial_equity_usd=100000.)
            pd.testing.assert_frame_equal(run.history[base.history.columns],base.history,check_exact=True)
            pd.testing.assert_frame_equal(run.events,base.events,check_exact=True)
            assert run.history.custody_cost_usd.eq(0).all()


def test_borrowed_cost_adds_debt_and_unlevered_cost_sells_assets():
    ret,ref=fixture(['2020-01-02','2020-02-03','2020-03-31','2020-04-01','2020-06-30'])
    for lev in [1.,1.25]:
        run=simulate_custody(ret,ref,WEIGHTS,lev,'absolute_decoupled',margin=0.,fee_schedule=FeeSchedule(),
            initial_equity_usd=100000.,custody_mode='private_full',custody_fx_usd_per_chf=1.2)
        h=run.history;first=quarter_amount(100000.*lev,'private_full',DEFAULT_RATES,1.2)*90/91
        assert h.loc['2020-03-31','custody_cost_usd']==pytest.approx(first)
        if lev==1:
            assert h.debt_usd.eq(0).all()
            assert h.loc['2020-03-31','gross_assets_usd']==pytest.approx(100000.-first)
            assert len(run.events[run.events.reason.eq('custody_sale')])==2
        else:
            assert h.gross_assets_usd.eq(125000.).all()
            assert h.loc['2020-03-31','debt_usd']==pytest.approx(25000.+first)
            assert not run.events.reason.eq('custody_sale').any()


def test_sale_pays_own_transaction_friction_and_keeps_cumulative_ledger():
    ret,ref=fixture(['2020-03-30','2020-03-31'])
    run=simulate_custody(ret,ref,WEIGHTS,1.,'absolute_decoupled',margin=0.,fee_schedule=FeeSchedule(proportional_rate=.01),
        initial_equity_usd=100000.,custody_mode='private_full',custody_fx_usd_per_chf=1.2)
    event=run.events.iloc[-1];cost=run.history.custody_cost_usd.iloc[-1]
    assert event.reason=='custody_sale' and event.gross_trade_usd==pytest.approx(cost/.99,abs=1e-8)
    assert event.fees_usd==pytest.approx(event.gross_trade_usd*.01)
    assert run.history.transaction_cost_usd.sum()==pytest.approx(run.events.fees_usd.sum(),abs=1e-6)


def test_same_day_custody_sale_and_prior_signal_both_keep_charges():
    ret,ref=fixture(['2020-03-27','2020-03-30','2020-03-31']);ret.loc['2020-03-30','momentum']=.6
    run=simulate_custody(ret,ref,WEIGHTS,1.,'absolute_decoupled',margin=0.,fee_schedule=FeeSchedule(proportional_rate=.002),
        initial_equity_usd=100000.,custody_mode='private_full',custody_fx_usd_per_chf=1.2)
    events=run.events[run.events.date.eq(pd.Timestamp('2020-03-31'))]
    assert set(events.reason)=={'custody_sale','sleeve'}
    assert run.history.loc['2020-03-31','transaction_cost_usd']==pytest.approx(events.fees_usd.sum(),abs=1e-6)


def test_invalid_modes_rates_and_substituted_source_are_rejected(tmp_path):
    ret,ref=fixture(['2020-01-02','2020-03-31'])
    with pytest.raises(ValueError,match='mode'):simulate_custody(ret,ref,WEIGHTS,custody_mode='wrong')
    rates=copy.deepcopy(DEFAULT_RATES);rates['vat_multiplier']=.8
    with pytest.raises(ValueError,match='percentage/VAT'):simulate_custody(ret,ref,WEIGHTS,custody_rates=rates)
    s=json.loads((ROOT/'config/backtest_custody_absolute_decoupled_2026-10-05.json').read_text())
    p=tmp_path/s['source']['path'];p.write_text('<html>fixture</html>');s['source']['sha256']=custody.sha256(p)
    custody.admit_source(tmp_path,s);p.write_text('changed')
    with pytest.raises(ValueError,match='checksum'):custody.admit_source(tmp_path,s)
