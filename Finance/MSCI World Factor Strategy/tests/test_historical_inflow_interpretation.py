"""Matched calendars, explicit difference units and failed evidence admission."""
import pandas as pd
import pytest

from factor_portfolio.historical_inflow_interpretation import compare_accounts,run_interpretation


def fixture():
    rid='absolute_decoupled__acquisition__steady'
    c=pd.DataFrame(dict(run_id=[rid]*2,month=[1,2],layer=['acquisition']*2,event_date=['2020-02-03','2020-03-03'],
        closing_unit_nav=[100.,101.9],closing_aum_usd=[150.,152.85],owner_equity_usd=[100.,101.9],external_equity_usd=[50.,50.95],
        subscriptions_usd=[50.,0.],redemptions_usd=[0.,0.],flow_transaction_cost_usd=[.1,0.]))
    o=pd.DataFrame(dict(run_id=[rid]*2,month=[1,2],event_date=c.event_date,nav_per_unit=[100.,102.],
        closing_net_aum_usd=[150.,153.],start_cohort_equity_usd=[100.,102.],new_cohort_equity_usd=[50.,51.],
        subscriptions_usd=[50.,0.],new_cohort_redemptions_usd=[0.,0.]))
    h=pd.DataFrame(dict(run_id=[rid],gross_subscriptions_usd=[50.]))
    r=pd.DataFrame(dict(run_id=[rid]*2,kind=['coupled','overlay'],policy=['absolute_decoupled']*2,
        fund_window_start=['2020-01-03']*2,fund_window_end=['2020-03-03']*2,first_external_subscription_date=['2020-02-03']*2,
        fund_unit_twr_annual=[.099,.1],aggregate_external_mwr_annual=[.119,.12],mwr_status=['unique_root_in_scanned_range']*2))
    return c,o,h,r


def test_paired_differences_keep_owner_external_and_percentage_point_units_separate():
    c,o,h,r=fixture();before=c.copy(deep=True)
    summary,monthly,checks=compare_accounts(c,o,h,r)
    s=summary.iloc[0]
    assert s.unit_twr_difference_pp==pytest.approx(-.1)
    assert s.external_mwr_difference_pp==pytest.approx(-.1)
    assert s.terminal_owner_equity_difference_usd==pytest.approx(-.1)
    assert s.terminal_external_equity_difference_usd==pytest.approx(-.05)
    assert s.terminal_total_equity_difference_usd==pytest.approx(-.15)
    assert s.coupled_flow_transaction_cost_usd==.1 and len(monthly)==2
    assert checks[0]['unit_twr_range']==0
    pd.testing.assert_frame_equal(c,before,check_exact=True)


def test_missing_or_duplicate_dates_are_rejected():
    c,o,h,r=fixture()
    with pytest.raises(ValueError,match='monthly observations'):compare_accounts(c,o.iloc[:1],h,r)
    with pytest.raises(ValueError,match='duplicate'):compare_accounts(pd.concat([c,c.iloc[:1]]),o,h,r)
    o.loc[1,'event_date']='2020-03-04'
    with pytest.raises(ValueError,match='monthly observations'):compare_accounts(c,o,h,r)


def test_subscription_and_window_mismatch_are_rejected():
    c,o,h,r=fixture();o.loc[0,'subscriptions_usd']=51
    with pytest.raises(ValueError,match='gross subscriptions'):compare_accounts(c,o,h,r)
    c,o,h,r=fixture();r.loc[1,'fund_window_end']='2020-03-04'
    with pytest.raises(ValueError,match='return windows'):compare_accounts(c,o,h,r)


def test_fixed_fee_overlay_invariance_is_checked_and_no_investor_mwr_stays_undefined():
    c,o,h,r=fixture();r['aggregate_external_mwr_annual']=float('nan');r['mwr_status']='undefined_no_invested_external_cohort'
    summary,_,_=compare_accounts(c,o,h,r)
    assert pd.isna(summary.external_mwr_difference_pp.iloc[0])
    extra=r.iloc[1].copy();extra['run_id']='absolute_decoupled__timing__front_loaded';extra['fund_unit_twr_annual']=.2
    with pytest.raises(ValueError,match='overlay unit return changes'):compare_accounts(c,o,h,pd.concat([r,extra.to_frame().T],ignore_index=True))


def test_existing_outputs_and_changed_source_evidence_are_rejected(tmp_path):
    from factor_portfolio.inflow_workflow import write_json,sha256
    with pytest.raises(FileExistsError):run_interpretation(tmp_path/'absent',tmp_path)
    source=tmp_path/'source';source.mkdir();p=source/'record.csv';p.write_text('sealed')
    write_json(source/'run_manifest.json',dict(status='complete',configuration_snapshots={},artifacts={'record.csv':sha256(p)},figures_included=False,run_id='test'))
    p.write_text('changed')
    with pytest.raises(ValueError,match='changed'):run_interpretation(source,tmp_path/'new')
    assert not (tmp_path/'new').exists()
