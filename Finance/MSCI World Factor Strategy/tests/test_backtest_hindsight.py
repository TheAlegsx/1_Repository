"""Original grid identity, explicit exposure metadata, ties and no primary selection."""
import copy
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from factor_portfolio.backtest_hindsight import scenario_definitions,summarize_maxima,hindsight_comparison,account_check,run_hindsight

CONFIG=Path(__file__).resolve().parents[1]/'config'


@pytest.fixture(scope='module')
def inputs():
    b=json.loads((CONFIG/'backtest_absolute_decoupled_2026-10-05.json').read_text());s=json.loads((CONFIG/'backtest_legacy_hindsight_2026-10-05.json').read_text())
    dates=pd.bdate_range('2020-01-02',periods=20,name='date');b['initial_equity_usd']=12000.
    b['periods']['full']=dict(start=str(dates[0].date()),end=str(dates[-1].date()))
    ret=pd.DataFrame({name:.002+.012*np.sin(np.arange(len(dates))*.7+i) for i,name in enumerate(['core','momentum','quality','value','dimensional'])},index=dates);ret.iloc[0]=0.
    ref=pd.Series(.02,index=pd.date_range(dates[0],dates[-1]));return ret,ref,b,s


@pytest.fixture(scope='module')
def result(inputs):return hindsight_comparison(*inputs)


def test_generated_original_definition_identity_and_named_sleeves(inputs):
    _,_,b,s=inputs;g=scenario_definitions(s,b)
    assert g.shape==(150,9) and g.scenario_id.is_unique
    assert g.is_baseline.sum()==1 and g[g.is_baseline].scenario_id.iloc[0]=='W13-SB05-LB10'
    assert g.target_leverage.eq(1.25).all()  # metadata, not the override exposure
    reordered=copy.deepcopy(s)
    reordered['weight_vectors']=[dict(reversed(list(x.items()))) for x in s['weight_vectors']]
    pd.testing.assert_frame_equal(scenario_definitions(reordered,b),g,check_exact=True)


def test_altered_policy_dimensions_or_definition_cannot_claim_original_grid(inputs):
    _,_,b,s=inputs
    for change in [dict(policy='absolute_decoupled'),dict(leverage_levels=[1.25]),dict(sleeve_bands=[.05]),dict(definition_source_sha256='0'*64)]:
        with pytest.raises(ValueError):scenario_definitions(dict(s,**change),b)
    bad=copy.deepcopy(s);bad['weight_vectors'][0]['core']=-.1
    with pytest.raises(ValueError):scenario_definitions(bad,b)
    bad=copy.deepcopy(s);bad['weight_vectors'][1]=bad['weight_vectors'][0]
    with pytest.raises(ValueError,match='distinct'):scenario_definitions(bad,b)


def test_both_exposures_override_metadata_and_no_primary_configuration_changes(inputs,result):
    _,_,b,s=inputs;before=copy.deepcopy(b)
    assert len(result['metrics'])==300 and len(result['checks'])==300
    assert result['metrics'].groupby('leverage').size().to_dict()=={1.:150,1.25:150}
    assert result['scope']['unchanged_primary_policy']=='absolute_decoupled' and result['scope']['no_automatic_primary_selection']
    assert result['scope']['unchanged_primary_weights']==b['target_weights'] and b==before
    unlevered=result['metrics'][result['metrics'].leverage==1.]
    assert unlevered.financing_cost_usd.abs().max()<1e-7
    assert result['metrics'][result['metrics'].leverage==1.25].financing_cost_usd.min()>0


def test_unlevered_leverage_band_variants_are_equal_and_all_exact_maximum_ties_remain(result):
    t=result['metrics'];one=t[t.leverage==1.]
    for _,g in one.groupby(['core_weight','momentum_weight','quality_weight','value_weight','sleeve_band']):
        assert len(g)==3 and g.cagr.nunique()==1 and g.ending_equity_usd.nunique()==1
    for selected in result['selection']:
        g=t[t.leverage==selected['leverage']];maximum=g.cagr.max()
        assert selected['exact_tie_scenarios']==g[g.cagr==maximum].scenario_id.tolist()
        assert selected['display_scenario_id']==selected['exact_tie_scenarios'][0]
    assert len(result['selected_histories'])==40


def test_summary_retains_all_ties_and_uses_original_order_only_for_display():
    rows=[]
    for name,value in [('third',.2),('first',.2),('lower',.1)]:rows.append(dict(leverage=1.,scenario_id=name,cagr=value,core_weight=.6,momentum_weight=.15,quality_weight=.1,value_weight=.15,sleeve_band=.05,leverage_band=.1))
    top,selection=summarize_maxima(pd.DataFrame(rows))
    assert top.scenario_id.tolist()==['third','first'] and top.exact_tie_count.tolist()==[2,2]
    assert top.display_representative.tolist()==[True,False] and selection[0]['display_scenario_id']=='third'


def test_changed_account_identity_or_incomplete_history_is_rejected(inputs,result):
    from factor_portfolio.historical import simulate
    ret,ref,b,s=inputs;run=simulate(ret[['core']],ref,[1.],1.,'no_sleeve',initial_equity_usd=12000.)
    run.history.loc[run.history.index[-1],'equity_usd']+=10.
    with pytest.raises(ValueError,match='unreconciled'):account_check(run)
    with pytest.raises(ValueError,match='full-period grid calendar'):hindsight_comparison(ret.iloc[1:],ref,b,s)


def test_existing_outputs_and_missing_source_failure(tmp_path):
    from factor_portfolio.inflow_workflow import verify_run
    paths=[CONFIG/n for n in ['backtest_absolute_decoupled_2026-10-05.json','backtest_sources.json','backtest_legacy_hindsight_2026-10-05.json']]
    p=tmp_path/'preserve';p.write_text('old')
    with pytest.raises(FileExistsError):run_hindsight(tmp_path/'raw',*paths,tmp_path)
    assert p.read_text()=='old'
    out=tmp_path/'missing'
    with pytest.raises(ValueError,match='source missing'):run_hindsight(tmp_path/'raw',*paths,out)
    assert json.loads((out/'run_manifest.json').read_text())['status']=='failed'
    with pytest.raises(ValueError,match='not complete'):verify_run(out)
