"""Snapshot admission, period restarts and retained-run integrity."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from factor_portfolio import backtest_workflow as workflow
from factor_portfolio.historical import simulate, metrics

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def study(tmp_path, monkeypatch):
    config = json.loads((ROOT / 'config/backtest_baseline.json').read_text())
    config['initial_equity_usd'] = 12000
    dates = pd.bdate_range('2020-01-02', periods=32, name='date')
    config['periods'] = {
        'full': dict(start=str(dates[0].date()), end=str(dates[-1].date())),
        'calibration': dict(start=str(dates[0].date()), end=str(dates[15].date())),
        'confirmation': dict(start=str(dates[16].date()), end=str(dates[-1].date()))}
    config['policies'] = ['hybrid20']
    returns = pd.DataFrame({c: .002 + .003 * np.sin(np.arange(32) + i)
        for i, c in enumerate(['core', 'momentum', 'quality', 'value', 'dimensional'])}, index=dates)
    reference = pd.Series(.02, index=pd.date_range(dates[0], dates[-1]))
    spec = json.loads((ROOT / 'config/backtest_sources.json').read_text())
    raw = tmp_path / 'raw'
    for item in spec['sources']:
        path = raw / item['path']
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('artificial admission fixture: ' + item['role'])
        item['sha256'] = workflow.sha256(path)
    config_path, sources_path = tmp_path / 'baseline.json', tmp_path / 'sources.json'
    config_path.write_text(json.dumps(config))
    sources_path.write_text(json.dumps(spec))

    def synthetic_import(*args):
        output = args[-1]
        (output / 'inputs').mkdir()
        return returns.copy(), reference.copy()

    # Admission remains real; only provider parsing is substituted in unit tests.
    monkeypatch.setattr(workflow, 'prepare_inputs', synthetic_import)
    return raw, config_path, sources_path, config, spec, returns, reference


def test_replaced_raw_source_is_rejected_before_creating_output(study, tmp_path):
    raw, cp, sp, _, spec, *_ = study
    (raw / spec['sources'][0]['path']).write_text('substituted snapshot')
    output = tmp_path / 'rejected'
    with pytest.raises(ValueError, match='checksum mismatch'):
        workflow.run_backtest_study(raw, cp, sp, output)
    assert not output.exists()


def test_source_contract_cannot_escape_raw_root(study, tmp_path):
    raw, _, _, _, spec, *_ = study
    outside = tmp_path / 'outside'
    outside.write_text('outside source')
    spec['sources'][0].update(path='../outside', sha256=workflow.sha256(outside))
    with pytest.raises(ValueError, match='outside declared raw root'):
        workflow.admit_sources(raw, spec)


def test_same_set_of_isins_cannot_be_swapped_between_sleeves(study):
    raw, _, _, _, spec, *_ = study
    first, second = spec['sources'][:2]
    first['identity'], second['identity'] = second['identity'], first['identity']
    with pytest.raises(ValueError, match='unexpected ETF identity'):
        workflow.admit_sources(raw, spec)


def test_exposures_cannot_overwrite_same_curve_name(study):
    config = study[3]
    config['leverage_levels'] = [1.25, 1.251]
    with pytest.raises(ValueError, match='collide'):
        workflow.validate_config(config)


def test_each_period_restarts_committed_capital_and_opening_costs(study):
    _, _, _, config, _, returns, reference = study
    result = workflow.policy_comparison(returns, reference, config)
    assert len(result['metrics']) == 21  # seven controls per period in this reduced fixture
    confirmation = returns.loc[config['periods']['confirmation']['start']:].copy()
    confirmation.iloc[0] = 0
    core = simulate(confirmation[['core']], reference, [1.], 1., 'no_sleeve',
        initial_equity_usd=config['initial_equity_usd'])
    expected = metrics(core, reference, core, [1.])
    row = result['metrics'].query("period == 'confirmation' and strategy == 'core' and leverage == 1").iloc[0]
    assert row['ending_equity_usd'] == pytest.approx(expected['ending_equity_usd'])
    assert core.history.equity_usd.iloc[0] < config['initial_equity_usd']
    assert row['beta_vs_unlevered_core'] == pytest.approx(1.)
    assert result['periods']['confirmation']['levels'] == 16


def test_configuration_changes_during_run_do_not_mix_assumptions(study, tmp_path, monkeypatch):
    raw, cp, sp, config, *_ = study
    original = cp.read_bytes()
    builder = workflow.policy_comparison

    def altered_source(returns, reference, captured):
        edited = dict(config, initial_equity_usd=999)
        cp.write_text(json.dumps(edited))
        return builder(returns, reference, captured)

    monkeypatch.setattr(workflow, 'policy_comparison', altered_source)
    output = tmp_path / 'run'
    manifest = workflow.run_backtest_study(raw, cp, sp, output)
    assert manifest['status'] == 'complete'
    assert (output / 'config/baseline.json').read_bytes() == original
    history = pd.read_csv(output / 'results/full_factor_hybrid20_1.00_history.csv')
    assert history.equity_usd.iloc[0] == pytest.approx(12000 - history.transaction_cost_usd.iloc[0])
    assert workflow.verify_run(output)['verified_files'] > 2


def test_existing_runs_and_modified_artifacts_are_rejected(study, tmp_path):
    raw, cp, sp, *_ = study
    output = tmp_path / 'run'
    workflow.run_backtest_study(raw, cp, sp, output)
    before = (output / 'run_manifest.json').read_bytes()
    with pytest.raises(FileExistsError, match='never overwritten'):
        workflow.run_backtest_study(raw, cp, sp, output)
    assert (output / 'run_manifest.json').read_bytes() == before
    (output / 'results/equity_curves.csv').write_text('altered evidence')
    with pytest.raises(ValueError, match='missing or changed'):
        workflow.verify_run(output)


def test_failed_calculation_is_not_accepted_as_complete(study, tmp_path, monkeypatch):
    raw, cp, sp, *_ = study

    def failed(*args):
        raise RuntimeError('injected policy failure')

    monkeypatch.setattr(workflow, 'policy_comparison', failed)
    output = tmp_path / 'failed'
    with pytest.raises(RuntimeError, match='injected'):
        workflow.run_backtest_study(raw, cp, sp, output)
    manifest = json.loads((output / 'run_manifest.json').read_text())
    assert manifest['status'] == 'failed'
    assert [s['id'] for s in manifest['stages']] == ['raw_import']
    with pytest.raises(ValueError, match='not complete'):
        workflow.verify_run(output)


def funding_config(tmp_path):
    settings = json.loads((ROOT / 'config/backtest_funding.json').read_text())
    settings['margin_bps'] = [0, 300]
    settings['threshold']['iterations'] = 4
    path = tmp_path / 'funding.json'
    path.write_text(json.dumps(settings))
    return path


def test_funding_settings_are_captured_and_artifacts_verified(study, tmp_path, monkeypatch):
    raw, cp, sp, *_ = study
    fp = funding_config(tmp_path)
    original = fp.read_bytes()
    builder = workflow.funding_comparison

    def changed_source(returns, reference, baseline, captured):
        edited = json.loads(fp.read_text())
        edited['margin_bps'] = [999]
        fp.write_text(json.dumps(edited))
        return builder(returns, reference, baseline, captured)

    monkeypatch.setattr(workflow, 'funding_comparison', changed_source)
    output = tmp_path / 'with-funding'
    manifest = workflow.run_backtest_study(raw, cp, sp, output, funding_config_path=fp)
    assert manifest['funding_included'] is True
    assert manifest['counts']['funding_cases'] == 12
    assert [s['id'] for s in manifest['stages']] == ['raw_import', 'policy_comparison', 'funding_comparison']
    assert (output / 'config/funding.json').read_bytes() == original
    assert set(pd.read_csv(output / 'results/funding_metrics.csv').margin_bps) == {0, 300}
    workflow.verify_run(output)
    (output / 'results/financing_threshold.json').write_text('{}')
    with pytest.raises(ValueError, match='missing or changed'):
        workflow.verify_run(output)


def test_invalid_funding_settings_fail_before_output_creation(study, tmp_path):
    raw, cp, sp, *_ = study
    fp = funding_config(tmp_path)
    settings = json.loads(fp.read_text())
    settings['margin_bps'] = [-100]
    fp.write_text(json.dumps(settings))
    output = tmp_path / 'rejected-funding'
    with pytest.raises(ValueError, match='nonnegative'):
        workflow.run_backtest_study(raw, cp, sp, output, funding_config_path=fp)
    assert not output.exists()


def test_failed_funding_stage_does_not_seal_partial_run(study, tmp_path, monkeypatch):
    raw, cp, sp, *_ = study
    fp = funding_config(tmp_path)

    def failed(*args):
        raise RuntimeError('injected funding failure')

    monkeypatch.setattr(workflow, 'funding_comparison', failed)
    output = tmp_path / 'failed-funding'
    with pytest.raises(RuntimeError, match='injected funding'):
        workflow.run_backtest_study(raw, cp, sp, output, funding_config_path=fp)
    manifest = json.loads((output / 'run_manifest.json').read_text())
    assert manifest['status'] == 'failed'
    assert [s['id'] for s in manifest['stages']] == ['raw_import', 'policy_comparison']
    with pytest.raises(ValueError, match='not complete'):
        workflow.verify_run(output)


def bridge_config(tmp_path):
    path = tmp_path / 'bridge.json'
    path.write_bytes((ROOT / 'config/backtest_bridge.json').read_bytes())
    return path


def test_bridge_is_independent_optional_stage_with_captured_settings(study, tmp_path, monkeypatch):
    raw, cp, sp, *_ = study
    bp = bridge_config(tmp_path)
    original = bp.read_bytes()
    builder = workflow.bridge_comparison

    def changed_source(returns, reference, baseline, captured):
        edited = json.loads(bp.read_text())
        edited['cases'][2]['reference_interest'] = True
        bp.write_text(json.dumps(edited))
        return builder(returns, reference, baseline, captured)

    monkeypatch.setattr(workflow, 'bridge_comparison', changed_source)
    output = tmp_path / 'bridge-only'
    manifest = workflow.run_backtest_study(raw, cp, sp, output, bridge_config_path=bp)
    assert manifest['bridge_included'] and not manifest['funding_included']
    assert manifest['counts']['bridge_cases'] == 7
    assert manifest['counts']['bridge_differences'] == 6
    assert [s['id'] for s in manifest['stages']] == ['raw_import','policy_comparison','counterfactual_bridge']
    assert (output / 'config/bridge.json').read_bytes() == original
    table = pd.read_csv(output / 'results/counterfactual_bridge.csv').set_index('counterfactual')
    assert table.loc['factor_levered_zero_interest', 'financing_cost_usd'] == 0
    workflow.verify_run(output)
    (output / 'results/counterfactual_steps.csv').write_text('altered comparison')
    with pytest.raises(ValueError, match='missing or changed'):
        workflow.verify_run(output)


def test_invalid_bridge_settings_fail_before_output_creation(study, tmp_path):
    raw, cp, sp, *_ = study
    bp = bridge_config(tmp_path)
    settings = json.loads(bp.read_text())
    settings['cases'][0]['leverage'] = -.1
    bp.write_text(json.dumps(settings))
    output = tmp_path / 'invalid-bridge'
    with pytest.raises(ValueError, match='economic settings'):
        workflow.run_backtest_study(raw, cp, sp, output, bridge_config_path=bp)
    assert not output.exists()


def test_failed_bridge_preserves_prior_stage_status_and_rejects_completion(study, tmp_path, monkeypatch):
    raw, cp, sp, *_ = study
    bp, fp = bridge_config(tmp_path), funding_config(tmp_path)

    def failed(*args):
        raise RuntimeError('injected bridge failure')

    monkeypatch.setattr(workflow, 'bridge_comparison', failed)
    output = tmp_path / 'failed-bridge'
    with pytest.raises(RuntimeError, match='injected bridge'):
        workflow.run_backtest_study(raw, cp, sp, output, funding_config_path=fp, bridge_config_path=bp)
    manifest = json.loads((output / 'run_manifest.json').read_text())
    assert manifest['status'] == 'failed'
    assert [s['id'] for s in manifest['stages']] == ['raw_import','policy_comparison','funding_comparison']
    with pytest.raises(ValueError, match='not complete'):
        workflow.verify_run(output)


def test_new_primary_has_its_own_metrics_and_histories_without_relabelling_old_cases(study, tmp_path):
    raw, cp, sp, config, *_ = study
    config.update(primary_policy='absolute_decoupled', primary_leverage=1.25,
        policies=['absolute_decoupled','hybrid20','annual','no_sleeve'],
        comparison_policies=['hybrid20','annual','no_sleeve'], history_policies=['absolute_decoupled','hybrid20'])
    cp.write_text(json.dumps(config))
    output = tmp_path / 'absolute-primary'
    manifest = workflow.run_backtest_study(raw, cp, sp, output)
    selection = json.loads((output / 'results/selection.json').read_text())
    assert selection['primary_policy'] == 'absolute_decoupled'
    table = pd.read_csv(output / 'results/primary_metrics.csv')
    assert set(table.query("strategy == 'factor'").policy) == {'absolute_decoupled'}
    assert len(table) == 18
    assert len(pd.read_csv(output / 'results/selected_comparison_metrics.csv')) == 36
    assert (output / 'results/full_factor_absolute_decoupled_1.25_history.csv').exists()
    assert (output / 'results/full_factor_hybrid20_1.25_history.csv').exists()
    assert manifest['counts']['full_policy_histories'] == 4
    assert manifest['counts']['full_hybrid_histories'] == 2
    assert not manifest['funding_included'] and not manifest['bridge_included']
    workflow.verify_run(output)


def test_new_primary_cannot_accidentally_run_archived_hybrid_followup(study, tmp_path):
    raw, cp, sp, config, *_ = study
    config.update(primary_policy='absolute_decoupled', policies=['absolute_decoupled','hybrid20'])
    cp.write_text(json.dumps(config))
    output = tmp_path / 'mixed-policy'
    with pytest.raises(ValueError, match='disagrees'):
        workflow.run_backtest_study(raw, cp, sp, output, funding_config_path=funding_config(tmp_path))
    assert not output.exists()


def entry_config(study,tmp_path):
    _,cp,_,baseline,_,ret,_ = study
    baseline.update(primary_policy='absolute_decoupled',policies=['absolute_decoupled','hybrid20'])
    cp.write_text(json.dumps(baseline))
    settings=json.loads((ROOT/'config/backtest_entries_absolute_decoupled_2026-10-05.json').read_text())
    starts=[str(ret.index[0].date()),str(ret.index[16].date())]
    settings.update(requested_starts=starts,research_reference_starts=starts,legacy_reference_starts=starts)
    path=tmp_path/'entries.json';path.write_text(json.dumps(settings))
    return path


def test_entry_stage_captures_settings_and_verifies_new_artifacts(study,tmp_path,monkeypatch):
    ep=entry_config(study,tmp_path)
    raw,cp,sp,*_=study
    original=ep.read_bytes();builder=workflow.entry_comparison
    def edited_source(ret,reference,baseline,captured):
        edited=json.loads(ep.read_text());edited['requested_starts']=['2030-01-01']
        ep.write_text(json.dumps(edited))
        return builder(ret,reference,baseline,captured)
    monkeypatch.setattr(workflow,'entry_comparison',edited_source)
    output=tmp_path/'entries'
    manifest=workflow.run_backtest_study(raw,cp,sp,output,entry_config_path=ep)
    assert manifest['entries_included'] and manifest['counts']['entry_cases']==16
    assert [x['id'] for x in manifest['stages']]==['raw_import','policy_comparison','fresh_entries']
    assert (output/'config/entries.json').read_bytes()==original
    workflow.verify_run(output)
    (output/'results/entry_policy_comparison.csv').write_text('altered')
    with pytest.raises(ValueError,match='missing or changed'):workflow.verify_run(output)


def test_failed_entry_stage_does_not_seal_previous_results_as_complete(study,tmp_path,monkeypatch):
    ep=entry_config(study,tmp_path);raw,cp,sp,*_=study
    def failure(*args):raise RuntimeError('injected entry failure')
    monkeypatch.setattr(workflow,'entry_comparison',failure)
    output=tmp_path/'failed-entry'
    with pytest.raises(RuntimeError,match='injected entry'):
        workflow.run_backtest_study(raw,cp,sp,output,entry_config_path=ep)
    assert json.loads((output/'run_manifest.json').read_text())['status']=='failed'
    with pytest.raises(ValueError,match='not complete'):workflow.verify_run(output)


def rolling_config(study,tmp_path,monkeypatch):
    _,cp,_,baseline,_,old,_=study
    dates=pd.bdate_range('2020-01-02',periods=800,name='date')
    ret=pd.DataFrame(np.resize(old.to_numpy(),(800,len(old.columns))),index=dates,columns=old.columns)
    ret.iloc[0]=0
    reference=pd.Series(.02,index=pd.date_range(dates[0],dates[-1]))
    baseline.update(primary_policy='absolute_decoupled',policies=['absolute_decoupled','hybrid20'],
        history_policies=['absolute_decoupled','hybrid20'])
    baseline['periods']=dict(full=dict(start=str(dates[0].date()),end=str(dates[-1].date())),
        calibration=dict(start=str(dates[0].date()),end=str(dates[399].date())),
        confirmation=dict(start=str(dates[400].date()),end=str(dates[-1].date())))
    cp.write_text(json.dumps(baseline))
    def synthetic_import(*args):
        (args[-1]/'inputs').mkdir()
        return ret.copy(),reference.copy()
    monkeypatch.setattr(workflow,'prepare_inputs',synthetic_import)
    settings=json.loads((ROOT/'config/backtest_rolling_absolute_decoupled_2026-10-05.json').read_text())
    settings.update(horizon_years=1,minimum_fresh_levels=4,monthly_horizons_years=[1])
    for key in ['fresh_start_grid','ongoing_start_grid']:
        settings[key]=dict(start='2021-01-01',end='2021-01-01',step_months=12)
    p=tmp_path/'rolling.json';p.write_text(json.dumps(settings))
    return p


def test_rolling_stage_captures_settings_and_verifies_window_evidence(study,tmp_path,monkeypatch):
    rp=rolling_config(study,tmp_path,monkeypatch);raw,cp,sp,*_=study
    original=rp.read_bytes();builder=workflow.rolling_comparison
    def altered_source(*args):
        edited=json.loads(rp.read_text());edited['fresh_start_grid']['step_months']=0
        rp.write_text(json.dumps(edited))
        return builder(*args)
    monkeypatch.setattr(workflow,'rolling_comparison',altered_source)
    output=tmp_path/'rolling'
    manifest=workflow.run_backtest_study(raw,cp,sp,output,rolling_config_path=rp)
    assert manifest['rolling_included'] and manifest['counts']['rolling_fresh_cases']==2
    assert manifest['counts']['rolling_ongoing_cases']==2
    assert (output/'config/rolling.json').read_bytes()==original
    assert [x['id'] for x in manifest['stages']]==['raw_import','policy_comparison','rolling_windows']
    workflow.verify_run(output)
    (output/'results/rolling_monthly_vs_core.csv').write_text('changed comparison')
    with pytest.raises(ValueError,match='missing or changed'):workflow.verify_run(output)


def test_failed_rolling_stage_is_not_accepted_as_complete(study,tmp_path,monkeypatch):
    rp=rolling_config(study,tmp_path,monkeypatch);raw,cp,sp,*_=study
    def failure(*args):raise RuntimeError('injected rolling failure')
    monkeypatch.setattr(workflow,'rolling_comparison',failure)
    output=tmp_path/'failed-rolling'
    with pytest.raises(RuntimeError,match='injected rolling'):
        workflow.run_backtest_study(raw,cp,sp,output,rolling_config_path=rp)
    assert json.loads((output/'run_manifest.json').read_text())['status']=='failed'
    with pytest.raises(ValueError,match='not complete'):workflow.verify_run(output)


def margin_config(study,tmp_path):
    _,cp,_,baseline,*_=study
    baseline.update(primary_policy='absolute_decoupled',policies=['absolute_decoupled','hybrid20','no_sleeve'],
        history_policies=['absolute_decoupled','hybrid20'])
    cp.write_text(json.dumps(baseline))
    p=tmp_path/'margin.json';p.write_bytes((ROOT/'config/backtest_margin_absolute_decoupled_2026-10-05.json').read_bytes())
    return p


def test_margin_stage_captures_terms_and_detects_changed_gap_evidence(study,tmp_path,monkeypatch):
    mp=margin_config(study,tmp_path);raw,cp,sp,*_=study
    original=mp.read_bytes();builder=workflow.margin_comparison
    def changed_source(*args):
        edited=json.loads(mp.read_text());edited['maintenance_ltv']=[.7]
        mp.write_text(json.dumps(edited))
        return builder(*args)
    monkeypatch.setattr(workflow,'margin_comparison',changed_source)
    output=tmp_path/'margin'
    manifest=workflow.run_backtest_study(raw,cp,sp,output,margin_config_path=mp)
    assert manifest['margin_included'] and manifest['counts']['margin_cases']==24
    assert manifest['counts']['gap_probes']==15
    assert [x['id'] for x in manifest['stages']]==['raw_import','policy_comparison','margin_gap_controls']
    assert (output/'config/margin.json').read_bytes()==original
    assert set(pd.read_csv(output/'results/margin_metrics.csv').maintenance_ltv)=={.25,.4,.6}
    workflow.verify_run(output)
    (output/'results/margin_gap_probes.csv').write_text('changed probe')
    with pytest.raises(ValueError,match='missing or changed'):workflow.verify_run(output)


def test_failed_margin_stage_does_not_seal_partial_run(study,tmp_path,monkeypatch):
    mp=margin_config(study,tmp_path);raw,cp,sp,*_=study
    def failure(*args):raise RuntimeError('injected margin failure')
    monkeypatch.setattr(workflow,'margin_comparison',failure)
    output=tmp_path/'failed-margin'
    with pytest.raises(RuntimeError,match='injected margin'):
        workflow.run_backtest_study(raw,cp,sp,output,margin_config_path=mp)
    assert json.loads((output/'run_manifest.json').read_text())['status']=='failed'
    with pytest.raises(ValueError,match='not complete'):workflow.verify_run(output)


def synthetic_config(study,tmp_path):
    _,cp,_,baseline,*_=study
    baseline.update(primary_policy='absolute_decoupled',policies=['absolute_decoupled','hybrid20','no_sleeve'],
        history_policies=['absolute_decoupled','hybrid20'])
    cp.write_text(json.dumps(baseline))
    settings=json.loads((ROOT/'config/backtest_synthetic_absolute_decoupled_2026-10-05.json').read_text())
    settings['levels']=80
    p=tmp_path/'synthetic.json';p.write_text(json.dumps(settings))
    return p


def test_synthetic_stage_captures_assumptions_and_keeps_artificial_files_separate(study,tmp_path,monkeypatch):
    sy=synthetic_config(study,tmp_path);raw,cp,sp,*_=study
    original=sy.read_bytes();builder=workflow.synthetic_comparison
    def changed_source(*args):
        edited=json.loads(sy.read_text());edited['levels']=81
        sy.write_text(json.dumps(edited))
        return builder(*args)
    monkeypatch.setattr(workflow,'synthetic_comparison',changed_source)
    output=tmp_path/'artificial'
    manifest=workflow.run_backtest_study(raw,cp,sp,output,synthetic_config_path=sy)
    assert manifest['synthetic_included'] and manifest['counts']['synthetic_cases']==224
    assert (output/'config/synthetic.json').read_bytes()==original
    assert len(pd.read_csv(output/'synthetic/synthetic_levels.csv'))==8*80
    assert [x['id'] for x in manifest['stages']]==['raw_import','policy_comparison','artificial_regimes']
    workflow.verify_run(output)
    (output/'synthetic/synthetic_returns.csv').write_text('changed inputs')
    with pytest.raises(ValueError,match='missing or changed'):workflow.verify_run(output)


def test_failed_synthetic_stage_is_not_accepted_as_complete(study,tmp_path,monkeypatch):
    sy=synthetic_config(study,tmp_path);raw,cp,sp,*_=study
    def failure(*args):raise RuntimeError('injected artificial failure')
    monkeypatch.setattr(workflow,'synthetic_comparison',failure)
    output=tmp_path/'failed-artificial'
    with pytest.raises(RuntimeError,match='injected artificial'):
        workflow.run_backtest_study(raw,cp,sp,output,synthetic_config_path=sy)
    assert json.loads((output/'run_manifest.json').read_text())['status']=='failed'
    with pytest.raises(ValueError,match='not complete'):workflow.verify_run(output)


def product_config(study,tmp_path):
    raw,cp,_,baseline,_,ret,_=study
    baseline.update(primary_policy='absolute_decoupled',policies=['absolute_decoupled','hybrid20'],
        history_policies=['absolute_decoupled','hybrid20'])
    cp.write_text(json.dumps(baseline))
    settings=json.loads((ROOT/'config/backtest_products_absolute_decoupled_2026-10-05.json').read_text())
    for item in settings['sources']:
        path=raw/item['path'];path.parent.mkdir(parents=True,exist_ok=True);path.write_text('product admission fixture '+item['role'])
        item['sha256']=workflow.sha256(path)
    settings.update(expected_common=dict(start=str(ret.index[0].date()),end=str(ret.index[-1].date()),levels=len(ret)),expected_market_levels=len(ret))
    p=tmp_path/'products.json';p.write_text(json.dumps(settings))
    return p


def test_product_stage_captures_extra_sources_and_short_evidence(study,tmp_path,monkeypatch):
    from types import SimpleNamespace
    from factor_portfolio.backtest_products import product_comparison
    pp=product_config(study,tmp_path);raw,cp,sp,baseline,_,ret,reference=study
    nav=(1+ret[['core','momentum','quality','value']]).cumprod()*10
    dataset=SimpleNamespace(nav_usd=nav,returns_usd=ret[['core','momentum','quality','value']])
    market=SimpleNamespace(benchmark_overlap=pd.DataFrame({'mxwoldnu_index_level_usd':nav.core*10,'amundi_2x_nav_usd':nav.core*9},index=nav.index))
    original=pp.read_bytes()
    monkeypatch.setattr(workflow,'load_canonical_dataset',lambda *args:dataset)
    def builder(raw_root,captured,data,ref,base,output):
        edited=json.loads(pp.read_text());edited['factor_exposures']=[1.5]
        pp.write_text(json.dumps(edited));(output/'products').mkdir()
        return product_comparison(data,ref,market,base,captured)
    monkeypatch.setattr(workflow,'build_product_study',builder)
    output=tmp_path/'product-run'
    manifest=workflow.run_backtest_study(raw,cp,sp,output,product_config_path=pp)
    assert manifest['products_included'] and manifest['counts']['product_cases']==7
    assert len(manifest['raw_sources'])==15
    assert (output/'config/products.json').read_bytes()==original
    assert [x['id'] for x in manifest['stages']]==['raw_import','policy_comparison','short_product_comparison']
    workflow.verify_run(output)
    (output/'products/product_overlap_curves.csv').write_text('changed comparison')
    with pytest.raises(ValueError,match='missing or changed'):workflow.verify_run(output)


def test_failed_product_stage_does_not_seal_partial_run(study,tmp_path,monkeypatch):
    pp=product_config(study,tmp_path);raw,cp,sp,*_=study
    monkeypatch.setattr(workflow,'load_canonical_dataset',lambda *args:None)
    def failure(*args):raise RuntimeError('injected product failure')
    monkeypatch.setattr(workflow,'build_product_study',failure)
    output=tmp_path/'failed-products'
    with pytest.raises(RuntimeError,match='injected product'):
        workflow.run_backtest_study(raw,cp,sp,output,product_config_path=pp)
    assert json.loads((output/'run_manifest.json').read_text())['status']=='failed'
    with pytest.raises(ValueError,match='not complete'):workflow.verify_run(output)


def correlation_config(study, tmp_path):
    _, _, _, baseline, _, ret, _ = study
    settings = json.loads((ROOT/'config/backtest_correlations_2026-10-05.json').read_text())
    settings['expected_panels']['long_full'].update(level_start=baseline['periods']['full']['start'],
        last_return_end=baseline['periods']['full']['end'])
    settings['excluded_month'] = str(ret.index[-1].to_period('M'))
    path = tmp_path/'correlations.json';path.write_text(json.dumps(settings))
    return path


def test_correlations_without_admitted_product_stage_are_rejected_before_outputs(study, tmp_path):
    raw, cp, sp, *_ = study
    corr = correlation_config(study, tmp_path);output = tmp_path/'missing-product'
    with pytest.raises(ValueError, match='require'):
        workflow.run_backtest_study(raw, cp, sp, output, correlation_config_path=corr)
    assert not output.exists()


def test_correlation_stage_captures_settings_and_rejects_partial_or_changed_evidence(study, tmp_path, monkeypatch):
    pp = product_config(study, tmp_path);raw, cp, sp, *_ = study
    corr = correlation_config(study, tmp_path);original = corr.read_bytes()
    monkeypatch.setattr(workflow, 'load_canonical_dataset', lambda *args: None)
    def product_builder(*args):
        (args[-1]/'products').mkdir()
        return dict(metrics=pd.DataFrame(), curves=pd.DataFrame(), legacy_metrics=pd.DataFrame(),
            legacy_curves=pd.DataFrame(), definitions={})
    monkeypatch.setattr(workflow, 'build_product_study', product_builder)
    def correlation_builder(output, baseline, captured):
        corr.write_text('{}')
        assert captured == json.loads(original)
        return dict(frames={'pairwise_correlations.csv':pd.DataFrame({'correlation':[.5]}),
            'rolling_252.csv':pd.DataFrame({'correlation':[.4]})}, definitions=dict(panels=captured['expected_panels']))
    monkeypatch.setattr(workflow, 'build_correlation_study', correlation_builder)
    output = tmp_path/'correlation-stage'
    m = workflow.run_backtest_study(raw, cp, sp, output, product_config_path=pp, correlation_config_path=corr)
    assert m['correlations_included'] and m['counts']['correlation_panels'] == 7
    assert m['stages'][-1]['id'] == 'product_return_correlations'
    assert (output/'config/correlations.json').read_bytes() == original
    workflow.verify_run(output)
    (output/'correlations/pairwise_correlations.csv').write_text('changed evidence')
    with pytest.raises(ValueError, match='missing or changed'):workflow.verify_run(output)
    corr.write_bytes(original)
    def failure(*args):raise RuntimeError('injected correlation failure')
    monkeypatch.setattr(workflow, 'build_correlation_study', failure)
    output = tmp_path/'failed-correlations'
    with pytest.raises(RuntimeError, match='injected correlation'):
        workflow.run_backtest_study(raw, cp, sp, output, product_config_path=pp, correlation_config_path=corr)
    assert json.loads((output/'run_manifest.json').read_text())['status'] == 'failed'
    with pytest.raises(ValueError, match='not complete'):workflow.verify_run(output)


def test_later_holdings_stage_is_independent_captured_and_verified(study, tmp_path, monkeypatch):
    raw, cp, sp, *_ = study
    hp = tmp_path/'holdings.json'
    original = (ROOT/'config/backtest_holdings_snapshot_2026-10-05.json').read_bytes()
    hp.write_bytes(original)
    def builder(sources, baseline, captured):
        assert set(baseline['target_weights']).issubset(sources)
        assert captured == json.loads(original)
        hp.write_text('{}')
        return dict(frames={'equity_holdings.csv':pd.DataFrame({'fund_weight':[.8]}),
            'combined_equity_holdings.csv':pd.DataFrame({'portfolio_weight':[.48]}),
            'pairwise_overlap.csv':pd.DataFrame({'sum_min_fund_weight':[.7]})},
            summary={'snapshot_date':captured['snapshot_date']}, definitions={'no_leverage_multiplier':True})
    monkeypatch.setattr(workflow, 'snapshot_comparison', builder)
    output = tmp_path/'later-holdings'
    m = workflow.run_backtest_study(raw, cp, sp, output, holdings_config_path=hp)
    assert m['holdings_snapshot_included'] and not m['products_included']
    assert m['stages'][-1]['id'] == 'later_holdings_snapshot'
    assert len(m['raw_sources']) == 9
    assert (output/'config/holdings.json').read_bytes() == original
    workflow.verify_run(output)
    (output/'holdings_snapshot/summary.json').write_text('changed evidence')
    with pytest.raises(ValueError, match='missing or changed'):workflow.verify_run(output)


def test_failed_holdings_stage_does_not_seal_partial_run(study, tmp_path, monkeypatch):
    raw, cp, sp, *_ = study
    hp = tmp_path/'holdings.json';hp.write_bytes((ROOT/'config/backtest_holdings_snapshot_2026-10-05.json').read_bytes())
    def failure(*args):raise RuntimeError('injected holdings failure')
    monkeypatch.setattr(workflow, 'snapshot_comparison', failure)
    output = tmp_path/'failed-holdings'
    with pytest.raises(RuntimeError, match='injected holdings'):
        workflow.run_backtest_study(raw, cp, sp, output, holdings_config_path=hp)
    assert json.loads((output/'run_manifest.json').read_text())['status'] == 'failed'
    with pytest.raises(ValueError, match='not complete'):workflow.verify_run(output)


def annual_config(tmp_path):
    pytest.importorskip('pypdf')
    settings = json.loads((ROOT/'config/backtest_annual_core_2026-10-05.json').read_text())
    raw = tmp_path/'annual_raw';raw.mkdir()
    # Artificial admission years precede this workflow fixture's 2020 end.
    for year, report in zip([2017,2018,2019], settings['reports']):
        report['snapshot_date'] = f'{year}-06-30'
        report['path'] = f'ishares_iii_annual_{year}.pdf'
        path = raw/report['path'];path.write_text('%PDF- annual admission fixture '+report['snapshot_date'])
        report['sha256'] = workflow.sha256(path)
    cp = tmp_path/'annual.json';cp.write_text(json.dumps(settings))
    return cp, raw


def test_annual_pdf_root_pair_and_substituted_pdf_are_rejected_before_outputs(study, tmp_path):
    raw, cp, sp, *_ = study;ap, pdf_root = annual_config(tmp_path);output = tmp_path/'rejected-annual'
    with pytest.raises(ValueError, match='both configuration'):
        workflow.run_backtest_study(raw, cp, sp, output, annual_config_path=ap)
    assert not output.exists()
    first = json.loads(ap.read_text())['reports'][0]
    (pdf_root/first['path']).write_text('%PDF- substituted')
    with pytest.raises(ValueError, match='checksum'):
        workflow.run_backtest_study(raw, cp, sp, output, annual_config_path=ap, annual_raw_root=pdf_root)
    assert not output.exists()


def test_annual_stage_captures_sources_settings_and_verifies_outputs(study, tmp_path, monkeypatch):
    raw, cp, sp, *_ = study;ap, pdf_root = annual_config(tmp_path);original = ap.read_bytes()
    def builder(pdf_inputs, captured, output):
        assert pdf_inputs == pdf_root and captured == json.loads(original)
        ap.write_text('{}');(output/'annual_core').mkdir()
        return dict(frames={'historical_equity_holdings.csv':pd.DataFrame({'fund':['core']}),
            'historical_country_exposures.csv':pd.DataFrame({'country':['United States']}),
            'historical_snapshot_summary.csv':pd.DataFrame({'fund':['core']})},
            definitions=dict(extracted_pages=[{'physical_page_1based':1}]))
    monkeypatch.setattr(workflow, 'build_annual_core_study', builder)
    output = tmp_path/'annual-stage'
    m = workflow.run_backtest_study(raw, cp, sp, output, annual_config_path=ap, annual_raw_root=pdf_root)
    assert m['annual_core_included'] and not m['holdings_snapshot_included']
    assert len(m['raw_sources']) == 12 and m['environment']['distributions']['pypdf'] == '6.19.0'
    assert (output/'config/annual.json').read_bytes() == original
    assert m['stages'][-1]['id'] == 'historical_core_annual_holdings'
    workflow.verify_run(output)
    (output/'annual_core/annual_definitions.json').write_text('changed PDF evidence')
    with pytest.raises(ValueError, match='missing or changed'):workflow.verify_run(output)


def test_failed_annual_stage_does_not_seal_partial_run(study, tmp_path, monkeypatch):
    raw, cp, sp, *_ = study;ap, pdf_root = annual_config(tmp_path)
    def failure(*args):raise RuntimeError('injected annual failure')
    monkeypatch.setattr(workflow, 'build_annual_core_study', failure)
    output = tmp_path/'failed-annual'
    with pytest.raises(RuntimeError, match='injected annual'):
        workflow.run_backtest_study(raw, cp, sp, output, annual_config_path=ap, annual_raw_root=pdf_root)
    assert json.loads((output/'run_manifest.json').read_text())['status'] == 'failed'
    with pytest.raises(ValueError, match='not complete'):workflow.verify_run(output)


def factor_annual_config(tmp_path):
    pytest.importorskip('pypdf')
    settings = json.loads((ROOT/'config/backtest_annual_factors_2026-10-05.json').read_text())
    raw = tmp_path/'factor_pdfs';raw.mkdir();mapping = {}
    for year,source in zip([2017,2018,2019],settings['sources']):
        old = source['path'];source.update(path=f'ishares_iv_annual_{year}.pdf',snapshot_date=f'{year}-05-31')
        mapping[old] = source
        path = raw/source['path'];path.write_text('%PDF- artificial factor admission '+str(year));source['sha256'] = workflow.sha256(path)
    for schedule in settings['schedules']:
        source = mapping[schedule['path']];schedule.update(path=source['path'],snapshot_date=source['snapshot_date'])
    cp = tmp_path/'factor_annual.json';cp.write_text(json.dumps(settings));return cp,raw


def test_factor_annual_missing_root_and_changed_pdf_reject_before_outputs(study,tmp_path):
    raw,cp,sp,*_ = study;fp,pdf_root = factor_annual_config(tmp_path);output = tmp_path/'rejected-factor-annual'
    with pytest.raises(ValueError,match='both configuration'):
        workflow.run_backtest_study(raw,cp,sp,output,factor_annual_config_path=fp)
    assert not output.exists()
    first = json.loads(fp.read_text())['sources'][0]
    (pdf_root/first['path']).write_text('%PDF- substituted')
    with pytest.raises(ValueError,match='checksum'):
        workflow.run_backtest_study(raw,cp,sp,output,factor_annual_config_path=fp,factor_annual_raw_root=pdf_root)
    assert not output.exists()


def test_factor_annual_captured_independent_stage_and_changed_evidence(study,tmp_path,monkeypatch):
    raw,cp,sp,*_ = study;fp,pdf_root = factor_annual_config(tmp_path);original = fp.read_bytes()
    def builder(root,captured,output):
        assert root == pdf_root and captured == json.loads(original)
        fp.write_text('{}');(output/'annual_factors').mkdir()
        frame = pd.DataFrame({'fund':['momentum']})
        return dict(frames={name:frame for name in ['historical_equity_holdings.csv','historical_country_exposures.csv',
            'historical_snapshot_summary.csv','factor_name_overlap.csv']},definitions=dict(extracted_pages=[{}]))
    monkeypatch.setattr(workflow,'build_factor_annual_study',builder)
    output = tmp_path/'factor-annual'
    m = workflow.run_backtest_study(raw,cp,sp,output,factor_annual_config_path=fp,factor_annual_raw_root=pdf_root)
    assert m['annual_factors_included'] and not m['annual_core_included']
    assert len(m['raw_sources']) == 12 and (output/'config/factor_annual.json').read_bytes() == original
    assert m['stages'][-1]['id'] == 'historical_factor_annual_holdings'
    workflow.verify_run(output)
    (output/'annual_factors/factor_name_overlap.csv').write_text('changed overlap')
    with pytest.raises(ValueError,match='missing or changed'):workflow.verify_run(output)


def test_failed_factor_annual_stage_does_not_seal_partial_run(study,tmp_path,monkeypatch):
    raw,cp,sp,*_ = study;fp,pdf_root = factor_annual_config(tmp_path)
    def failure(*args):raise RuntimeError('injected factor annual failure')
    monkeypatch.setattr(workflow,'build_factor_annual_study',failure)
    output = tmp_path/'failed-factor-annual'
    with pytest.raises(RuntimeError,match='injected factor annual'):
        workflow.run_backtest_study(raw,cp,sp,output,factor_annual_config_path=fp,factor_annual_raw_root=pdf_root)
    assert json.loads((output/'run_manifest.json').read_text())['status'] == 'failed'
    with pytest.raises(ValueError,match='not complete'):workflow.verify_run(output)


def dimensional_annual_config(tmp_path):
    pytest.importorskip('pdfplumber')
    settings=json.loads((ROOT/'config/backtest_annual_dimensional_2026-10-05.json').read_text())
    raw=tmp_path/'dimensional_pdfs';raw.mkdir()
    for year,report in zip([2018,2019],settings['reports']):
        report.update(path=f'dimensional_annual_{year}.pdf',snapshot_date=f'{year}-11-30')
        p=raw/report['path'];p.write_text('%PDF- artificial Dimensional admission '+str(year));report['sha256']=workflow.sha256(p)
    cp=tmp_path/'dimensional_annual.json';cp.write_text(json.dumps(settings));return cp,raw


def test_dimensional_missing_root_and_changed_pdf_reject_before_outputs(study,tmp_path):
    raw,cp,sp,*_=study;dp,pdf_root=dimensional_annual_config(tmp_path);out=tmp_path/'rejected-dimensional'
    with pytest.raises(ValueError,match='both configuration'):
        workflow.run_backtest_study(raw,cp,sp,out,dimensional_annual_config_path=dp)
    assert not out.exists()
    first=json.loads(dp.read_text())['reports'][0];(pdf_root/first['path']).write_text('%PDF- changed')
    with pytest.raises(ValueError,match='checksum'):
        workflow.run_backtest_study(raw,cp,sp,out,dimensional_annual_config_path=dp,dimensional_annual_raw_root=pdf_root)
    assert not out.exists()


def test_dimensional_captured_independent_stage_and_changed_checks(study,tmp_path,monkeypatch):
    raw,cp,sp,*_=study;dp,pdf_root=dimensional_annual_config(tmp_path);original=dp.read_bytes()
    def builder(root,captured,out):
        assert root==pdf_root and captured==json.loads(original)
        dp.write_text('{}');(out/'annual_dimensional').mkdir();frame=pd.DataFrame({'fund':['dimensional']})
        return dict(frames={n:frame for n in ['historical_equity_holdings.csv','historical_country_exposures.csv','historical_snapshot_summary.csv']},
            checks=[dict(missing=[],extra=[])],definitions=dict(extracted_pages=[{}]))
    monkeypatch.setattr(workflow,'build_dimensional_study',builder)
    out=tmp_path/'dimensional-stage'
    m=workflow.run_backtest_study(raw,cp,sp,out,dimensional_annual_config_path=dp,dimensional_annual_raw_root=pdf_root)
    assert m['annual_dimensional_included'] and not m['annual_core_included'] and not m['annual_factors_included']
    assert len(m['raw_sources'])==11 and m['environment']['distributions']['pdfplumber']=='0.11.9'
    assert (out/'config/dimensional_annual.json').read_bytes()==original
    workflow.verify_run(out)
    (out/'annual_dimensional/dimensional_second_reader_checks.json').write_text('changed evidence')
    with pytest.raises(ValueError,match='missing or changed'):workflow.verify_run(out)


def test_failed_dimensional_stage_does_not_seal_partial_run(study,tmp_path,monkeypatch):
    raw,cp,sp,*_=study;dp,pdf_root=dimensional_annual_config(tmp_path)
    def failure(*args):raise RuntimeError('injected Dimensional failure')
    monkeypatch.setattr(workflow,'build_dimensional_study',failure);out=tmp_path/'failed-dimensional'
    with pytest.raises(RuntimeError,match='injected Dimensional'):
        workflow.run_backtest_study(raw,cp,sp,out,dimensional_annual_config_path=dp,dimensional_annual_raw_root=pdf_root)
    assert json.loads((out/'run_manifest.json').read_text())['status']=='failed'
    with pytest.raises(ValueError,match='not complete'):workflow.verify_run(out)


def collateral_config(tmp_path):
    s=json.loads((ROOT/'config/backtest_collateral_2026-10-05.json').read_text());raw=tmp_path/'collateral_raw';raw.mkdir()
    p=raw/s['source']['path'];p.write_text('%PDF- artificial collateral evidence');s['source']['sha256']=workflow.sha256(p)
    cp=tmp_path/'collateral.json';cp.write_text(json.dumps(s));return cp,raw


def test_collateral_root_pair_and_evidence_reject_before_outputs(study,tmp_path):
    raw,cp,sp,*_=study;cc,evidence=collateral_config(tmp_path);out=tmp_path/'rejected-collateral'
    with pytest.raises(ValueError,match='both configuration'):workflow.run_backtest_study(raw,cp,sp,out,collateral_config_path=cc)
    assert not out.exists()
    (evidence/'swissquote_collateral_agreement.pdf').write_text('%PDF- substituted')
    with pytest.raises(ValueError,match='checksum'):
        workflow.run_backtest_study(raw,cp,sp,out,collateral_config_path=cc,collateral_raw_root=evidence)
    assert not out.exists()


def test_collateral_stage_captures_assumptions_and_verifies_states(study,tmp_path,monkeypatch):
    raw,cp,sp,*_=study;cc,evidence=collateral_config(tmp_path);original=cc.read_bytes();builder=workflow.collateral_comparison
    def changed(base,captured):
        cc.write_text('{}');return builder(base,captured)
    monkeypatch.setattr(workflow,'collateral_comparison',changed);out=tmp_path/'collateral'
    m=workflow.run_backtest_study(raw,cp,sp,out,collateral_config_path=cc,collateral_raw_root=evidence)
    assert m['collateral_included'] and m['counts']['collateral_states']==50
    assert len(m['raw_sources'])==10 and (out/'config/collateral.json').read_bytes()==original
    workflow.verify_run(out);(out/'collateral/collateral_limit_diagnostics.csv').write_text('changed states')
    with pytest.raises(ValueError,match='missing or changed'):workflow.verify_run(out)


def test_failed_collateral_stage_does_not_seal_partial_run(study,tmp_path,monkeypatch):
    raw,cp,sp,*_=study;cc,evidence=collateral_config(tmp_path)
    def failure(*args):raise RuntimeError('injected collateral failure')
    monkeypatch.setattr(workflow,'collateral_comparison',failure);out=tmp_path/'failed-collateral'
    with pytest.raises(RuntimeError,match='injected collateral'):
        workflow.run_backtest_study(raw,cp,sp,out,collateral_config_path=cc,collateral_raw_root=evidence)
    assert json.loads((out/'run_manifest.json').read_text())['status']=='failed'
    with pytest.raises(ValueError,match='not complete'):workflow.verify_run(out)


def custody_config(study,tmp_path):
    raw,cp,_,b,*_=study
    b.update(primary_policy='absolute_decoupled',policies=['hybrid20','absolute_decoupled'],history_policies=['hybrid20','absolute_decoupled'])
    cp.write_text(json.dumps(b));s=json.loads((ROOT/'config/backtest_custody_absolute_decoupled_2026-10-05.json').read_text())
    evidence=tmp_path/'custody_raw';evidence.mkdir();p=evidence/s['source']['path'];p.write_text('<html>artificial pricing fixture</html>');s['source']['sha256']=workflow.sha256(p)
    path=tmp_path/'custody.json';path.write_text(json.dumps(s));return path,evidence


def test_custody_root_pair_and_evidence_reject_before_outputs(study,tmp_path):
    cs,evidence=custody_config(study,tmp_path);raw,cp,sp,*_=study;out=tmp_path/'rejected-custody'
    with pytest.raises(ValueError,match='both configuration'):workflow.run_backtest_study(raw,cp,sp,out,custody_config_path=cs)
    assert not out.exists()
    (evidence/'swissquote_account_fees.html').write_text('changed')
    with pytest.raises(ValueError,match='checksum'):
        workflow.run_backtest_study(raw,cp,sp,out,custody_config_path=cs,custody_raw_root=evidence)
    assert not out.exists()


def test_custody_stage_captures_assumptions_and_checks_no_fee_paths(study,tmp_path,monkeypatch):
    cs,evidence=custody_config(study,tmp_path);raw,cp,sp,*_=study;original=cs.read_bytes();builder=workflow.custody_comparison
    def altered(ret,ref,b,captured):
        cs.write_text('{}');return builder(ret,ref,b,captured)
    monkeypatch.setattr(workflow,'custody_comparison',altered);out=tmp_path/'custody'
    m=workflow.run_backtest_study(raw,cp,sp,out,custody_config_path=cs,custody_raw_root=evidence)
    assert m['custody_included'] and m['counts']['custody_cases']==32 and m['counts']['custody_no_fee_checks']==8
    assert (out/'config/custody.json').read_bytes()==original and len(m['raw_sources'])==10
    workflow.verify_run(out);(out/'custody/custody_ledger.csv').write_text('changed')
    with pytest.raises(ValueError,match='missing or changed'):workflow.verify_run(out)


def test_failed_custody_stage_does_not_seal_partial_run(study,tmp_path,monkeypatch):
    cs,evidence=custody_config(study,tmp_path);raw,cp,sp,*_=study
    def failure(*args):raise RuntimeError('injected custody failure')
    monkeypatch.setattr(workflow,'custody_comparison',failure);out=tmp_path/'failed-custody'
    with pytest.raises(RuntimeError,match='injected custody'):
        workflow.run_backtest_study(raw,cp,sp,out,custody_config_path=cs,custody_raw_root=evidence)
    assert json.loads((out/'run_manifest.json').read_text())['status']=='failed'
    with pytest.raises(ValueError,match='not complete'):workflow.verify_run(out)
