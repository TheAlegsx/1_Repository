"""Fee bridge conserves account wealth and rejects mismatched evidence."""
import json
from pathlib import Path
import pandas as pd
import pytest
from factor_portfolio.inflow_fee_diagnostics import summaries


IDS = ['absolute_decoupled__control__no_flow_zero_added_fee',
       'absolute_decoupled__acquisition__no_flows',
       'absolute_decoupled__acquisition__steady']


@pytest.fixture
def source(tmp_path):
    folder=tmp_path/'inflow/evidence';folder.mkdir(parents=True)
    config=tmp_path/'inflow/config';config.mkdir();(config/'inflow_acquisition.json').write_text(json.dumps({'annual_fee':.0005}))
    config=tmp_path/'backtest/config';config.mkdir(parents=True)
    (config/'backtest_absolute_decoupled_2026-10-05.json').write_text(json.dumps({'initial_equity_usd':7e6,'measurement':{'cagr_calendar_year_days':365.2425}}))
    heads=[];monthly=[]
    for rid,pnl,trade,funding,fee,subs,redemptions,owner in [
        (IDS[0],100000.,100.,1000.,0.,0.,0.,7098900.),
        (IDS[1],80000.,200.,800.,3500.,0.,0.,7075500.),
        (IDS[2],79000.,220.,780.,3600.,100000.,10000.,7074400.)]:
        equity=7e6+pnl-trade-funding-fee+subs-redemptions
        heads.append(dict(run_id=rid,start='2014-10-03',end='2024-10-03',observations=2462,
                          owner_equity_usd=owner,external_equity_usd=equity-owner,
                          closing_aum_usd=equity,transaction_cost_usd=trade,financing_cost_usd=funding,
                          fund_fee_usd=fee,gross_subscriptions_usd=subs,redemptions_usd=redemptions))
        monthly.extend(dict(run_id=rid,month=n,owner_units=70000.,investment_price_pnl_usd=pnl if n==120 else 0.) for n in range(1,121))
    pd.DataFrame(heads).to_csv(folder/'historical_headline.csv',index=False)
    pd.DataFrame(monthly).to_csv(folder/'coupled_monthly.csv',index=False)
    pd.DataFrame([dict(run_id=IDS[1],month=n,event_date='2024-10-03',start_cohort_equity_usd=7095350.) for n in range(1,121)]).to_csv(folder/'overlay_monthly.csv',index=False)
    events=[]
    for rid in IDS[:2]:
        events.extend([dict(run_id=rid,reason='sleeve',date='2020-09-03'),
                       dict(run_id=rid,reason='leverage',date='2021-04-09' if rid==IDS[0] else '2021-04-16')])
    events.append(dict(run_id=IDS[1],reason='leverage',date='2022-10-03'))
    pd.DataFrame(events).to_csv(folder/'coupled_events.csv',index=False)
    pd.DataFrame([dict(run_id=rid,date='2022-09-30',leverage=1.3439 if rid==IDS[0] else 1.3519) for rid in IDS[:2]]).to_csv(folder/'coupled_daily.csv',index=False)
    return tmp_path


def test_signed_bridge_conserves_wealth_and_keeps_unrounded_inputs(source):
    result=summaries(source)
    assert [row[1]['value'] for row in result['wealth_bridge']['rows']]==[-20000.,200.,-100.,-3500.,-23400.]
    assert result['fee_chain']['rows'][2][1]['value']==7075500.
    assert result['fee_events']['rows'][2][1]['value'] is None
    assert result['fee_events']['rows'][2][2]['value']=='2022-10-03'
    assert result['checks']['wealth_bridge_error_usd']==0


@pytest.mark.parametrize('change,match',[
    ('finance','account identity'),('window','same observation window'),
    ('client','no-client controls'),('duplicate','one exact retained historical account')])
def test_mismatched_account_evidence_is_rejected(source,change,match):
    path=source/'inflow/evidence/historical_headline.csv';frame=pd.read_csv(path)
    if change=='finance':frame.loc[1,'financing_cost_usd']+=1
    elif change=='window':frame.loc[1,'end']='2024-10-04'
    elif change=='client':frame.loc[1,'external_equity_usd']=1
    else:frame=pd.concat([frame,frame.iloc[[1]]],ignore_index=True)
    frame.to_csv(path,index=False)
    with pytest.raises(ValueError,match=match):summaries(source)
