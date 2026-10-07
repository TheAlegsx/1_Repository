"""Fixed weight proposals, no borrowing and independently restarted periods."""
import copy
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from factor_portfolio.backtest_allocations import allocation_comparison,validate_settings,run_allocations
from factor_portfolio.config import SwissquoteStandardFeeSchedule
from factor_portfolio.historical import simulate

CONFIG=Path(__file__).resolve().parents[1]/'config'


def fixture():
    b=json.loads((CONFIG/'backtest_absolute_decoupled_2026-10-05.json').read_text());s=json.loads((CONFIG/'backtest_allocations_absolute_decoupled_2026-10-05.json').read_text())
    dates=pd.bdate_range('2020-01-02',periods=60,name='date');b['initial_equity_usd']=12000.
    for period,a,z in [('full',0,59),('calibration',0,29),('confirmation',30,59)]:b['periods'][period]=dict(start=str(dates[a].date()),end=str(dates[z].date()))
    ret=pd.DataFrame({name:.001+.008*np.sin(np.arange(len(dates))*.7+i) for i,name in enumerate(['core','momentum','quality','value','dimensional'])},index=dates);ret.iloc[0]=0.;ret.iloc[30]=.4
    ref=pd.Series(.02,index=pd.date_range(dates[0],dates[-1]));return ret,ref,b,s


def test_scope_keeps_eight_weights_both_rules_and_shared_benchmarks_without_selection():
    ret,ref,b,s=fixture();before=copy.deepcopy(b);r=allocation_comparison(ret,ref,b,s)
    assert len(r['metrics'])==54 and len(r['legacy'])==30 and len(r['pairs'])==24 and len(r['histories'])==2160
    assert len(r['metrics'][r['metrics'].strategy!='factor'])==6
    assert r['definitions']['selected_weights']==b['target_weights'] and r['definitions']['no_automatic_selection']
    assert r['histories'].debt_usd.abs().max()<1e-7 and r['histories'].cumulative_financing_cost_usd.abs().max()<1e-7
    assert (r['histories'].leverage-1).abs().max()<1e-12 and b==before


def test_confirmation_restarts_capital_entry_cost_and_first_return():
    ret,ref,b,s=fixture();before=ret.copy(deep=True);r=allocation_comparison(ret,ref,b,s)
    h=r['histories'].query("run_id=='confirmation__factor__absolute_decoupled__original'").set_index('date')
    assert h.equity_usd.iloc[0]<b['initial_equity_usd'] and h.equity_usd.iloc[0]>b['initial_equity_usd']*.9
    assert h.equity_usd.iloc[0]+h.transaction_cost_usd.iloc[0]==pytest.approx(b['initial_equity_usd'],abs=1e-7)
    assert (h.weight_core.iloc[0],h.weight_momentum.iloc[0],h.weight_quality.iloc[0],h.weight_value.iloc[0])==pytest.approx([.6,.15,.1,.15])
    event=r['events'].query("run_id=='confirmation__factor__absolute_decoupled__original'").iloc[0]
    assert event.reason=='initialise' and event.fees_usd>0
    pd.testing.assert_frame_equal(ret,before,check_exact=True)


def test_legacy_path_is_exact_original_simulator_with_same_target_and_costs():
    ret,ref,b,s=fixture();r=allocation_comparison(ret,ref,b,s);target=list(s['allocations']['previous'].values())
    base=simulate(ret[list(b['target_weights'])],ref,target,1.,'hybrid20',margin=b['borrowing_margin_annual'],
        sleeve_band=b['sleeve_band'],leverage_band=b['leverage_band'],initial_equity_usd=b['initial_equity_usd'],fee_schedule=SwissquoteStandardFeeSchedule(**b['fee_schedule']))
    h=r['histories'].query("run_id=='full__factor__hybrid20__previous'").set_index('date')[base.history.columns]
    pd.testing.assert_frame_equal(h,base.history,check_exact=True,check_freq=False,check_dtype=False)


def test_weight_key_order_does_not_change_sleeve_assignment():
    ret,ref,b,s=fixture();old=allocation_comparison(ret,ref,b,s);s=copy.deepcopy(s)
    for name in s['allocations']:s['allocations'][name]=dict(reversed(list(s['allocations'][name].items())))
    new=allocation_comparison(ret,ref,b,s)
    pd.testing.assert_frame_equal(old['metrics'],new['metrics'],check_exact=True)
    pd.testing.assert_frame_equal(old['histories'],new['histories'],check_exact=True)


def test_comparator_differences_and_joint_risk_flags_use_same_period():
    ret,ref,b,s=fixture();r=allocation_comparison(ret,ref,b,s);t=r['metrics']
    for period,g in t.groupby('period',sort=False):
        core=g[g.allocation=='core'].iloc[0]
        np.testing.assert_allclose(g.cagr_difference_vs_core,g.cagr-core.cagr,atol=1e-15)
        actual=(g.cagr>core.cagr)&(g.annualised_volatility<=core.annualised_volatility)&(g.maximum_drawdown>=core.maximum_drawdown)
        assert actual.tolist()==g.joint_pass_vs_core.tolist()
        assert not bool(core.joint_pass_vs_core)


def test_invalid_weight_borrowing_policy_selection_and_calendar_are_rejected():
    ret,ref,b,s=fixture()
    for change in [dict(leverage=1.25),dict(factor_policies=['absolute_decoupled']),dict(legacy_policy='absolute_decoupled'),dict(selected_allocation='momentum_focus')]:
        with pytest.raises(ValueError):validate_settings(dict(s,**change),b)
    for weight in [-.1,.2,float('nan')]:
        bad=copy.deepcopy(s);bad['allocations']['previous']['core']=weight
        with pytest.raises(ValueError):validate_settings(bad,b)
    bad=copy.deepcopy(s);bad['allocations']['original']=s['allocations']['previous']
    with pytest.raises(ValueError,match='baseline target'):validate_settings(bad,b)
    with pytest.raises(ValueError,match='allocation period'):allocation_comparison(ret.iloc[1:],ref,b,s)


def test_output_preservation_and_failed_source_run(tmp_path):
    from factor_portfolio.inflow_workflow import verify_run
    paths=[CONFIG/n for n in ['backtest_absolute_decoupled_2026-10-05.json','backtest_sources.json','backtest_allocations_absolute_decoupled_2026-10-05.json']]
    p=tmp_path/'preserve';p.write_text('unchanged')
    with pytest.raises(FileExistsError):run_allocations(tmp_path/'raw',*paths,tmp_path)
    assert p.read_text()=='unchanged'
    out=tmp_path/'missing'
    with pytest.raises(ValueError,match='source missing'):run_allocations(tmp_path/'raw',*paths,out)
    assert json.loads((out/'run_manifest.json').read_text())['status']=='failed'
    with pytest.raises(ValueError,match='not complete'):verify_run(out)
