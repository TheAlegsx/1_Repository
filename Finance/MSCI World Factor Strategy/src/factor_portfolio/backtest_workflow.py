"""Rebuild the main historical policy comparison from separately supplied raw files."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import json
import math
import hashlib
import importlib.metadata
import platform
from pathlib import Path
import uuid

import pandas as pd

from .config import SwissquoteStandardFeeSchedule
from .data import DEFAULT_PRODUCTS, build_canonical_dataset, write_canonical_dataset, load_canonical_dataset
from .dimensional import _common_returns
from .historical import simulate, metrics
from .backtest_funding import funding_comparison, validate_settings
from .backtest_bridge import bridge_comparison, validate_settings as validate_bridge_settings
from .backtest_entries import entry_comparison, validate_settings as validate_entry_settings
from .backtest_rolling import rolling_comparison, validate_settings as validate_rolling_settings
from .backtest_margin import margin_comparison, validate_settings as validate_margin_settings
from .backtest_synthetic import synthetic_comparison, validate_settings as validate_synthetic_settings
from .backtest_products import build_product_study, validate_settings as validate_product_settings, admit_sources as admit_product_sources
from .backtest_correlations import build_correlation_study, validate_settings as validate_correlation_settings
from .backtest_holdings import snapshot_comparison, validate_settings as validate_holdings_settings
from .backtest_annual_holdings import build_annual_core_study, validate_settings as validate_annual_settings, admit_sources as admit_annual_sources, require_reader
from .backtest_factor_holdings import build_factor_annual_study, validate_settings as validate_factor_annual_settings, admit_sources as admit_factor_annual_sources
from .backtest_dimensional_holdings import build_dimensional_study, validate_settings as validate_dimensional_settings, admit_sources as admit_dimensional_sources, require_layout_reader
from .backtest_collateral import collateral_comparison, validate_settings as validate_collateral_settings, admit_source as admit_collateral_source
from .backtest_custody import custody_comparison, validate_settings as validate_custody_settings, admit_source as admit_custody_source
from .inflow_workflow import sha256, source_hashes, write_json, verify_run
from .market_data import BloombergSpec, read_bloomberg_hardcopy
from .rates import build_funding_dataset, write_funding_dataset, load_funding_dataset

POLICIES = ['legacy_absolute', 'absolute_decoupled', 'relative20', 'hybrid20',
            'quarterly', 'annual', 'no_sleeve']
MEASUREMENT = dict(reference_day_count=360, annualisation_intervals=252,
    cagr_calendar_year_days=365.2425, alpha_hac_lags=5, normal_interval_multiplier=1.96,
    include_opening_cost_in_investor_returns=True)


def validate_config(config):
    if config['schema_version'] != 1 or config['measurement'] != MEASUREMENT:
        raise ValueError('unsupported backtest schema or metric conventions')
    weights = config['target_weights']
    if list(weights) != ['core', 'momentum', 'quality', 'value']:
        raise ValueError('ordered target weights must identify the four ETF sleeves')
    if any(not math.isfinite(w) or w <= 0 for w in weights.values()) or abs(sum(weights.values()) - 1) > 1e-10:
        raise ValueError('positive target weights must sum to one')
    for field in ['initial_equity_usd', 'borrowing_margin_annual', 'sleeve_band', 'leverage_band']:
        if not math.isfinite(config[field]) or config[field] < 0:
            raise ValueError('invalid configured ' + field)
    if config['initial_equity_usd'] == 0 or config['sleeve_band'] >= 1:
        raise ValueError('invalid capital or sleeve band')
    levels = config['leverage_levels']
    if not levels or len(set(levels)) != len(levels) or any(not math.isfinite(x) or x < 1 for x in levels):
        raise ValueError('invalid unique target exposures')
    if len({f'{x:.2f}' for x in levels}) != len(levels):
        raise ValueError('target exposures collide in the two-decimal output names')
    policies = config['policies']
    if not policies or len(set(policies)) != len(policies) or any(p not in POLICIES for p in policies):
        raise ValueError('unknown or repeated sleeve policy')
    primary = config.get('primary_policy', 'hybrid20')
    if primary not in policies or config.get('primary_leverage', max(levels)) not in levels:
        raise ValueError('primary policy and exposure must be calculated in this run')
    for key, fallback in [('comparison_policies', []), ('history_policies', ['hybrid20'])]:
        selected = config.get(key, fallback)
        if len(set(selected)) != len(selected) or any(p not in policies for p in selected):
            raise ValueError('unknown or repeated ' + key)
    if 'history_policies' in config and primary not in config['history_policies']:
        raise ValueError('primary policy requires a retained account history')
    if primary in config.get('comparison_policies', []):
        raise ValueError('primary policy must be distinct from comparison policies')
    if list(config['periods']) != ['full', 'calibration', 'confirmation']:
        raise ValueError('declare full, calibration and confirmation periods explicitly')
    for period in config['periods'].values():
        if date.fromisoformat(period['start']) >= date.fromisoformat(period['end']):
            raise ValueError('period requires start before end')
    SwissquoteStandardFeeSchedule(**config['fee_schedule'])


def admit_sources(raw_root, spec):
    """Reject substitutions before parsing; no earlier processed output is admitted."""
    raw_root = Path(raw_root).resolve()
    if spec['schema_version'] != 1:
        raise ValueError('unsupported raw-source contract')
    roles = [s['role'] for s in spec['sources']]
    expected = {'core', 'momentum', 'quality', 'value', 'ishares_manifest',
        'funding_manifest', 'indicative_sofr', 'official_sofr', 'dimensional'}
    if len(roles) != len(expected) or set(roles) != expected:
        raise ValueError('source contract must identify exactly nine main-comparison files')
    sources = {}
    for item in spec['sources']:
        path = (raw_root / item['path']).resolve()
        if not path.is_relative_to(raw_root) or not path.is_file():
            raise ValueError('source missing or outside declared raw root: ' + item['role'])
        if sha256(path) != item['sha256']:
            raise ValueError('raw source checksum mismatch: ' + item['role'])
        sources[item['role']] = path
    records = {item['role']: item for item in spec['sources']}
    for product in DEFAULT_PRODUCTS:
        if records[product.sleeve].get('identity') != product.isin:
            raise ValueError('unexpected ETF identity: ' + product.sleeve)
        if sources[product.sleeve] != sources['core'].parent / product.filename:
            raise ValueError('ETF paths must match the documented importer layout')
    if sources['ishares_manifest'] != sources['core'].parent / 'source_manifest.json':
        raise ValueError('ETF manifest must accompany the imported files')
    funding_dir = sources['indicative_sofr'].parent
    if (sources['indicative_sofr'].name != 'Data Release.xlsx'
        or sources['funding_manifest'] != funding_dir / 'source_manifest.json'
        or sources['official_sofr'] != funding_dir / 'sofr_official_2018-04-02_2026-08-31.json'):
        raise ValueError('funding paths must match the documented importer layout')
    return sources


def prepare_inputs(raw_root, sources, spec, config, output):
    """Reuse tested importers and their persisted/reloaded precision contract."""
    cutoff = date.fromisoformat(spec['cutoff'])
    canonical = output / 'inputs/canonical'
    etf = build_canonical_dataset(sources['core'].parent, cutoff=cutoff)
    write_canonical_dataset(etf, canonical)
    # The original research consumed the serialized canonical snapshots. Reload
    # the freshly generated files to preserve those exact precision conventions.
    etf = load_canonical_dataset(canonical)
    rates = build_funding_dataset(sources['indicative_sofr'].parent,
        start=date.fromisoformat(spec['start']), cutoff=cutoff,
        broker_spread=config['borrowing_margin_annual'])
    write_funding_dataset(rates, canonical)
    rates = load_funding_dataset(canonical)
    dimensional = read_bloomberg_hardcopy(sources['dimensional'],
        BloombergSpec('dimensional', spec['dimensional_security'], sources['dimensional'].name),
        cutoff=date.fromisoformat(spec['dimensional_cutoff']))
    returns, common = _common_returns(etf.nav_usd, dimensional.data.px_last_usd.rename('dimensional'))
    expected = spec['expected_common']
    if (len(common) != expected['levels'] or common[0].date().isoformat() != expected['start']
        or common[-1].date().isoformat() != expected['end']):
        raise ValueError('common calendar differs from the admitted baseline snapshot')
    levels = etf.nav_usd.loc[common].copy()
    levels['dimensional'] = dimensional.data.px_last_usd.loc[common]
    frame_csv(output / 'inputs/common_nav_usd.csv', levels, index=True)
    frame_csv(output / 'inputs/common_returns_usd.csv', returns, index=True)
    write_json(output / 'inputs/calendar.json', dict(start=expected['start'], end=expected['end'],
        levels=len(common), intervals=len(common)-1, etf_only_levels=len(etf.nav_usd),
        alignment='intersect levels before calculating interval returns; no NAV filling',
        canonical_precision='ETF NAV six decimals, interval returns and reference rates twelve decimals; freshly serialized ETF/funding snapshots reloaded before simulation',
        dimensional_security=spec['dimensional_security'], dimensional_isin=spec['dimensional_isin'],
        dimensional_identity_basis='user-confirmed security/share-class mapping; ISIN is not embedded in the Bloomberg workbook',
        dimensional_missing_dates_excluded=[x.isoformat() for x in dimensional.excluded_missing_px_last_dates]))
    # Confirm none of the raw files changed during import.
    admit_sources(raw_root, spec)
    return returns, rates.daily_borrow_rates.reference_rate_annual


def frame_csv(path, frame, *, index=False):
    frame.to_csv(path, index=index, float_format='%.12f', date_format='%Y-%m-%d', lineterminator='\n')


def policy_comparison(returns, reference, config):
    """Same 57 baseline cases as the source runner; each period restarts capital."""
    weights = list(config['target_weights'].values())
    sleeves = list(config['target_weights'])
    fee = SwissquoteStandardFeeSchedule(**config['fee_schedule'])
    rows, curves, events, histories, periods = [], {}, [], {}, {}

    def run(ret, cols, target, exposure, policy, *, passive=False):
        result = simulate(ret[cols], reference, target, exposure, policy,
            margin=config['borrowing_margin_annual'], sleeve_band=config['sleeve_band'],
            leverage_band=config['leverage_band'], passive=passive,
            initial_equity_usd=config['initial_equity_usd'], fee_schedule=fee)
        if result.status != 'complete':
            raise ValueError('incomplete historical path; not a complete baseline comparison')
        return result

    for period, boundaries in config['periods'].items():
        ret = returns.loc[boundaries['start']:boundaries['end']].copy()
        if len(ret) < 4:
            raise ValueError('period needs sufficient observations for reported regression metrics')
        ret.iloc[0] = 0
        periods[period] = dict(start=ret.index[0].date().isoformat(), end=ret.index[-1].date().isoformat(), levels=len(ret), independent_capital_restart=True)
        core1 = run(ret, ['core'], [1.], 1., 'no_sleeve')

        def record(result, label, strategy, policy, exposure, target):
            rows.append(dict(period=period, strategy=strategy, policy=policy, leverage=exposure,
                **metrics(result, reference, core1, target)))
            if period == 'full':
                curves[label] = result.history.equity_usd

        for lev in config['leverage_levels']:
            for policy in config['policies']:
                result = run(ret, sleeves, weights, lev, policy)
                label = f'{period}_factor_{policy}_{lev:.2f}'
                record(result, label, 'factor', policy, lev, weights)
                if period == 'full':
                    events.append(result.events.assign(run_id=label))
                    if policy in config.get('history_policies', ['hybrid20']):
                        histories[label + '_history.csv'] = result.history.reset_index()
            for strategy in ['core', 'dimensional']:
                result = run(ret, [strategy], [1.], lev, 'no_sleeve')
                record(result, f'{period}_{strategy}_{lev:.2f}', strategy, 'leverage_managed', lev, [1.])
            if lev > 1 and config['passive_debt_control']:
                result = run(ret, sleeves, weights, lev, 'no_sleeve', passive=True)
                record(result, f'{period}_factor_passive_debt_{lev:.2f}', 'factor', 'passive_debt', lev, weights)
    return dict(metrics=pd.DataFrame(rows), curves=pd.DataFrame(curves).rename_axis('date').reset_index(),
        events=pd.concat(events, ignore_index=True), histories=histories, periods=periods)


def run_backtest_study(raw_root, config_path, sources_path, output, *, funding_config_path=None, bridge_config_path=None, entry_config_path=None, rolling_config_path=None, margin_config_path=None, synthetic_config_path=None, product_config_path=None, correlation_config_path=None, holdings_config_path=None, annual_config_path=None, annual_raw_root=None, factor_annual_config_path=None, factor_annual_raw_root=None, dimensional_annual_config_path=None, dimensional_annual_raw_root=None, collateral_config_path=None, collateral_raw_root=None, custody_config_path=None, custody_raw_root=None):
    output = Path(output)
    if output.exists():
        raise FileExistsError('choose a new output directory; existing runs are never overwritten')
    paths = [config_path, sources_path] + ([funding_config_path] if funding_config_path is not None else [])
    if bridge_config_path is not None:
        paths.append(bridge_config_path)
    if entry_config_path is not None:
        paths.append(entry_config_path)
    if rolling_config_path is not None:
        paths.append(rolling_config_path)
    if margin_config_path is not None:
        paths.append(margin_config_path)
    if synthetic_config_path is not None:
        paths.append(synthetic_config_path)
    if product_config_path is not None:
        paths.append(product_config_path)
    if correlation_config_path is not None:
        paths.append(correlation_config_path)
    if holdings_config_path is not None:
        paths.append(holdings_config_path)
    if annual_config_path is not None:
        paths.append(annual_config_path)
    if (annual_config_path is None) != (annual_raw_root is None):
        raise ValueError('annual holdings require both configuration and separate PDF raw root')
    if factor_annual_config_path is not None:
        paths.append(factor_annual_config_path)
    if (factor_annual_config_path is None) != (factor_annual_raw_root is None):
        raise ValueError('factor annual holdings require both configuration and separate PDF raw root')
    if dimensional_annual_config_path is not None:
        paths.append(dimensional_annual_config_path)
    if (dimensional_annual_config_path is None) != (dimensional_annual_raw_root is None):
        raise ValueError('Dimensional annual holdings require both configuration and separate PDF raw root')
    if collateral_config_path is not None:
        paths.append(collateral_config_path)
    if (collateral_config_path is None) != (collateral_raw_root is None):
        raise ValueError('collateral diagnostics require both configuration and evidence raw root')
    if custody_config_path is not None:
        paths.append(custody_config_path)
    if (custody_config_path is None) != (custody_raw_root is None):
        raise ValueError('custody diagnostics require both configuration and evidence raw root')
    originals = {Path(p).name: Path(p).read_bytes() for p in paths}
    if len(originals) != len(paths):
        raise ValueError('configuration files and source contract need distinct filenames')
    config, spec = (json.loads(originals[Path(p).name]) for p in [config_path, sources_path])
    validate_config(config)
    funding_settings = json.loads(originals[Path(funding_config_path).name]) if funding_config_path is not None else None
    if funding_settings is not None:
        validate_settings(funding_settings, config)
    bridge_settings = json.loads(originals[Path(bridge_config_path).name]) if bridge_config_path is not None else None
    if bridge_settings is not None:
        validate_bridge_settings(bridge_settings, config)
    entry_settings = json.loads(originals[Path(entry_config_path).name]) if entry_config_path is not None else None
    if entry_settings is not None:
        validate_entry_settings(entry_settings, config)
    rolling_settings = json.loads(originals[Path(rolling_config_path).name]) if rolling_config_path is not None else None
    if rolling_settings is not None:
        validate_rolling_settings(rolling_settings, config)
    margin_settings = json.loads(originals[Path(margin_config_path).name]) if margin_config_path is not None else None
    if margin_settings is not None:
        validate_margin_settings(margin_settings,config)
    synthetic_settings = json.loads(originals[Path(synthetic_config_path).name]) if synthetic_config_path is not None else None
    if synthetic_settings is not None:
        validate_synthetic_settings(synthetic_settings,config)
    product_settings = json.loads(originals[Path(product_config_path).name]) if product_config_path is not None else None
    if product_settings is not None:
        validate_product_settings(product_settings,config)
        if product_settings['cutoff']!=spec['cutoff']:
            raise ValueError('product cutoff must match the separate ETF/import snapshot cutoff')
        admit_product_sources(raw_root,product_settings)
    correlation_settings = json.loads(originals[Path(correlation_config_path).name]) if correlation_config_path is not None else None
    if correlation_settings is not None:
        validate_correlation_settings(correlation_settings, config, product_settings)
    holdings_settings = json.loads(originals[Path(holdings_config_path).name]) if holdings_config_path is not None else None
    if holdings_settings is not None:
        validate_holdings_settings(holdings_settings, config)
    annual_settings = json.loads(originals[Path(annual_config_path).name]) if annual_config_path is not None else None
    if annual_settings is not None:
        validate_annual_settings(annual_settings, config)
        require_reader()
        admit_annual_sources(annual_raw_root, annual_settings)
    factor_annual_settings = json.loads(originals[Path(factor_annual_config_path).name]) if factor_annual_config_path is not None else None
    if factor_annual_settings is not None:
        validate_factor_annual_settings(factor_annual_settings, config)
        require_reader()
        admit_factor_annual_sources(factor_annual_raw_root, factor_annual_settings)
    dimensional_settings = json.loads(originals[Path(dimensional_annual_config_path).name]) if dimensional_annual_config_path is not None else None
    if dimensional_settings is not None:
        validate_dimensional_settings(dimensional_settings, config)
        require_layout_reader()
        admit_dimensional_sources(dimensional_annual_raw_root, dimensional_settings)
    collateral_settings = json.loads(originals[Path(collateral_config_path).name]) if collateral_config_path is not None else None
    if collateral_settings is not None:
        validate_collateral_settings(collateral_settings, config)
        admit_collateral_source(collateral_raw_root, collateral_settings)
    custody_settings=json.loads(originals[Path(custody_config_path).name]) if custody_config_path is not None else None
    if custody_settings is not None:
        validate_custody_settings(custody_settings,config)
        admit_custody_source(custody_raw_root,custody_settings)
    sources = admit_sources(raw_root, spec)
    output.mkdir(parents=True, exist_ok=False)
    (output / 'config').mkdir()
    for name, raw in originals.items():
        (output / 'config' / name).write_bytes(raw)
    code = source_hashes()
    manifest = dict(schema_version=1, run_id=str(uuid.uuid4()), status='running',
        started_at_utc=datetime.now(timezone.utc).isoformat(), figures_included=False,
        scope='Historical core with optional financial diagnostics, artificial regimes and separate short-window product comparison. Excludes remaining evidence branches, complete report assembly and public release.',
        funding_included=funding_settings is not None,
        bridge_included=bridge_settings is not None,
        entries_included=entry_settings is not None,
        rolling_included=rolling_settings is not None,
        margin_included=margin_settings is not None,
        synthetic_included=synthetic_settings is not None,
        products_included=product_settings is not None,
        correlations_included=correlation_settings is not None,
        holdings_snapshot_included=holdings_settings is not None,
        annual_core_included=annual_settings is not None,
        annual_factors_included=factor_annual_settings is not None,
        annual_dimensional_included=dimensional_settings is not None,
        collateral_included=collateral_settings is not None,
        custody_included=custody_settings is not None,
        configuration_snapshots={f'config/{n}': sha256(output / 'config' / n) for n in originals},
        raw_sources={r['role']: dict(relative_path=r['path'], sha256=r['sha256']) for r in spec['sources']},
        code=code, code_snapshot_sha256=hashlib.sha256(json.dumps(code, sort_keys=True).encode()).hexdigest(),
        environment=dict(python=platform.python_version(), system=platform.system(), machine=platform.machine(),
            distributions={name: importlib.metadata.version(name) for name in ['numpy', 'pandas', 'openpyxl']}),
        stages=[], artifacts={})
    write_json(output / 'run_manifest.json', manifest)
    if annual_settings is not None:
        manifest['raw_sources'].update({f"annual_core_{date.fromisoformat(r['snapshot_date']).year}":dict(
            relative_path=r['path'], sha256=r['sha256'], input_root='annual_raw_root') for r in annual_settings['reports']})
        manifest['environment']['distributions']['pypdf'] = importlib.metadata.version('pypdf')
        write_json(output/'run_manifest.json', manifest)
    if product_settings is not None:
        manifest['raw_sources'].update({f"product_{item['role']}":dict(relative_path=item['path'],sha256=item['sha256']) for item in product_settings['sources']})
        write_json(output/'run_manifest.json',manifest)
    if factor_annual_settings is not None:
        manifest['raw_sources'].update({f"annual_factor_{date.fromisoformat(r['snapshot_date']).year}":dict(
            relative_path=r['path'],sha256=r['sha256'],input_root='factor_annual_raw_root') for r in factor_annual_settings['sources']})
        manifest['environment']['distributions']['pypdf'] = importlib.metadata.version('pypdf')
        write_json(output/'run_manifest.json',manifest)
    if dimensional_settings is not None:
        manifest['raw_sources'].update({f"annual_dimensional_{date.fromisoformat(r['snapshot_date']).year}":dict(
            relative_path=r['path'],sha256=r['sha256'],input_root='dimensional_annual_raw_root') for r in dimensional_settings['reports']})
        manifest['environment']['distributions'].update({'pypdf':importlib.metadata.version('pypdf'),**require_layout_reader()})
        write_json(output/'run_manifest.json',manifest)
    if collateral_settings is not None:
        item=collateral_settings['source']
        manifest['raw_sources']['collateral_evidence']=dict(relative_path=item['path'],sha256=item['sha256'],input_root='collateral_raw_root')
        write_json(output/'run_manifest.json',manifest)
    if custody_settings is not None:
        item=custody_settings['source'];manifest['raw_sources']['custody_evidence']=dict(relative_path=item['path'],sha256=item['sha256'],input_root='custody_raw_root')
        write_json(output/'run_manifest.json',manifest)
    try:
        returns, reference = prepare_inputs(raw_root, sources, spec, config, output)
        manifest['stages'].append(dict(id='raw_import', inputs=[r['path'] for r in spec['sources']],
            outputs=[str(p.relative_to(output)) for p in sorted((output / 'inputs').rglob('*')) if p.is_file()]))
        write_json(output / 'run_manifest.json', manifest)
        comparison = policy_comparison(returns, reference, config)
        (output / 'results').mkdir()
        frame_csv(output / 'results/policy_metrics.csv', comparison['metrics'])
        frame_csv(output / 'results/equity_curves.csv', comparison['curves'])
        frame_csv(output / 'results/trade_events.csv', comparison['events'])
        for name, frame in comparison['histories'].items():
            frame_csv(output / 'results' / name, frame)
        primary = config.get('primary_policy', 'hybrid20')
        selected = [primary] + config.get('comparison_policies', [])
        table = comparison['metrics']
        primary_rows = table[(table.strategy != 'factor') | (table.policy == primary)]
        selected_rows = table[(table.strategy != 'factor') | table.policy.isin(selected)]
        frame_csv(output / 'results/primary_metrics.csv', primary_rows)
        frame_csv(output / 'results/selected_comparison_metrics.csv', selected_rows)
        write_json(output / 'results/selection.json', dict(primary_policy=primary,
            primary_leverage=config.get('primary_leverage', max(config['leverage_levels'])),
            comparison_policies=config.get('comparison_policies', []),
            history_policies=config.get('history_policies', ['hybrid20']),
            configuration_scope=config.get('scope', ''),
            complete_backtest_report_included=False))
        write_json(output / 'inputs/periods.json', comparison['periods'])
        manifest['stages'].append(dict(id='policy_comparison',
            inputs=['inputs/common_returns_usd.csv', 'inputs/canonical/daily_borrow_rates_usd.csv'],
            outputs=[str(p.relative_to(output)) for p in sorted((output / 'results').iterdir())] + ['inputs/periods.json']))
        write_json(output / 'run_manifest.json', manifest)
        funding = None
        if funding_settings is not None:
            funding = funding_comparison(returns, reference, config, funding_settings)
            frame_csv(output / 'results/funding_metrics.csv', funding['metrics'])
            write_json(output / 'results/financing_threshold.json', funding['threshold'])
            write_json(output / 'results/funding_search.json', funding['diagnostics'])
            manifest['stages'].append(dict(id='funding_comparison',
                inputs=['inputs/common_returns_usd.csv', 'inputs/canonical/daily_borrow_rates_usd.csv',
                    f'config/{Path(config_path).name}', f'config/{Path(funding_config_path).name}'],
                outputs=['results/funding_metrics.csv', 'results/financing_threshold.json', 'results/funding_search.json']))
            write_json(output / 'run_manifest.json', manifest)
        bridge = None
        if bridge_settings is not None:
            bridge = bridge_comparison(returns, reference, config, bridge_settings)
            frame_csv(output / 'results/counterfactual_bridge.csv', bridge['metrics'])
            frame_csv(output / 'results/counterfactual_steps.csv', bridge['differences'])
            manifest['stages'].append(dict(id='counterfactual_bridge',
                inputs=['inputs/common_returns_usd.csv', 'inputs/canonical/daily_borrow_rates_usd.csv',
                    f'config/{Path(config_path).name}', f'config/{Path(bridge_config_path).name}'],
                outputs=['results/counterfactual_bridge.csv', 'results/counterfactual_steps.csv']))
            write_json(output / 'run_manifest.json', manifest)
        entries = None
        if entry_settings is not None:
            entries = entry_comparison(returns, reference, config, entry_settings)
            frame_csv(output / 'results/fresh_entry_metrics.csv', entries['metrics'])
            frame_csv(output / 'results/legacy_hybrid_entry_metrics.csv', entries['legacy_metrics'])
            frame_csv(output / 'results/entry_policy_comparison.csv', entries['comparison'])
            write_json(output / 'results/entry_dates.json', entries['dates'])
            write_json(output / 'results/entry_comparison_summary.json', entries['summary'])
            manifest['stages'].append(dict(id='fresh_entries',
                inputs=['inputs/common_returns_usd.csv','inputs/canonical/daily_borrow_rates_usd.csv',
                    f'config/{Path(config_path).name}', f'config/{Path(entry_config_path).name}'],
                outputs=['results/fresh_entry_metrics.csv','results/legacy_hybrid_entry_metrics.csv',
                    'results/entry_policy_comparison.csv','results/entry_dates.json','results/entry_comparison_summary.json']))
            write_json(output / 'run_manifest.json', manifest)
        rolling = None
        if rolling_settings is not None:
            rolling = rolling_comparison(returns,reference,config,rolling_settings,comparison['histories'],comparison['curves'])
            rolling_files = dict(fresh='rolling_fresh_metrics.csv',ongoing='rolling_ongoing_metrics.csv',
                pairs='rolling_policy_comparison.csv',monthly='rolling_monthly_vs_core.csv',
                monthly_summary='rolling_monthly_summary.csv',legacy_monthly='legacy_hybrid_rolling_windows.csv',
                legacy_summary='legacy_hybrid_rolling_summary.csv')
            for key,name in rolling_files.items():frame_csv(output/'results'/name,rolling[key])
            write_json(output/'results/rolling_definitions.json',rolling['definitions'])
            history_inputs=[f'results/full_factor_{p}_{lev:.2f}_history.csv'
                for p in rolling_settings['factor_policies']
                for lev in sorted(set(rolling_settings['monthly_leverage_levels']+[rolling_settings['study_leverage']]))]
            manifest['stages'].append(dict(id='rolling_windows',
                inputs=['inputs/common_returns_usd.csv','inputs/canonical/daily_borrow_rates_usd.csv','results/equity_curves.csv',
                    f'config/{Path(config_path).name}',f'config/{Path(rolling_config_path).name}']+history_inputs,
                outputs=[f'results/{n}' for n in rolling_files.values()]+['results/rolling_definitions.json']))
            write_json(output/'run_manifest.json',manifest)
        margin = None
        if margin_settings is not None:
            margin = margin_comparison(returns,reference,config,margin_settings)
            margin_files=dict(metrics='margin_metrics.csv',events='margin_events.csv',gaps='margin_gap_probes.csv',
                legacy_metrics='legacy_hybrid_margin_metrics.csv',legacy_events='legacy_hybrid_margin_events.csv')
            for key,name in margin_files.items():frame_csv(output/'results'/name,margin[key])
            write_json(output/'results/margin_definitions.json',margin['definitions'])
            manifest['stages'].append(dict(id='margin_gap_controls',
                inputs=['inputs/common_returns_usd.csv','inputs/canonical/daily_borrow_rates_usd.csv',
                    f'config/{Path(config_path).name}',f'config/{Path(margin_config_path).name}'],
                outputs=[f'results/{n}' for n in margin_files.values()]+['results/margin_definitions.json']))
            write_json(output/'run_manifest.json',manifest)
        synthetic = None
        if synthetic_settings is not None:
            synthetic = synthetic_comparison(config,synthetic_settings)
            (output/'synthetic').mkdir()
            synthetic_files=dict(metrics='synthetic_metrics.csv',legacy_metrics='legacy_hybrid_synthetic_metrics.csv',
                histories='synthetic_histories.csv',events='synthetic_events.csv',recoveries='synthetic_recovery.csv')
            for key,name in synthetic_files.items():frame_csv(output/'synthetic'/name,synthetic[key])
            for key,name in [('levels','synthetic_levels.csv'),('returns','synthetic_returns.csv'),('rates','synthetic_rates.csv')]:
                synthetic[key].to_csv(output/'synthetic'/name,index=False,float_format='%.17g',lineterminator='\n')
            write_json(output/'synthetic/synthetic_definitions.json',synthetic['definitions'])
            manifest['stages'].append(dict(id='artificial_regimes',
                inputs=[f'config/{Path(config_path).name}',f'config/{Path(synthetic_config_path).name}'],
                outputs=[f'synthetic/{n}' for n in synthetic_files.values()]+['synthetic/synthetic_levels.csv',
                    'synthetic/synthetic_returns.csv','synthetic/synthetic_rates.csv','synthetic/synthetic_definitions.json']))
            write_json(output/'run_manifest.json',manifest)
        products = None
        if product_settings is not None:
            fresh_etf=load_canonical_dataset(output/'inputs/canonical')
            products=build_product_study(raw_root,product_settings,fresh_etf,reference,config,output)
            product_files=dict(metrics='product_overlap_metrics.csv',curves='product_overlap_curves.csv',
                legacy_metrics='legacy_hybrid_product_metrics.csv',legacy_curves='legacy_hybrid_product_curves.csv')
            for key,name in product_files.items():frame_csv(output/'products'/name,products[key])
            write_json(output/'products/product_definitions.json',dict(**products['definitions'],source_provenance=product_settings['provenance']))
            manifest['stages'].append(dict(id='short_product_comparison',
                inputs=['inputs/canonical/daily_nav_usd.csv','inputs/canonical/daily_returns_usd.csv',
                    'inputs/canonical/daily_borrow_rates_usd.csv',f'config/{Path(config_path).name}',
                    f'config/{Path(product_config_path).name}']+[item['path'] for item in product_settings['sources']],
                outputs=[str(p.relative_to(output)) for p in sorted((output/'products').rglob('*')) if p.is_file()]))
        correlations = None
        if correlation_settings is not None:
            correlations = build_correlation_study(output, config, correlation_settings)
            (output/'correlations').mkdir()
            for name, frame in correlations['frames'].items():
                frame_csv(output/'correlations'/name, frame, index=isinstance(frame.index, pd.DatetimeIndex) or frame.index.name=='product')
            write_json(output/'correlations/correlation_definitions.json', correlations['definitions'])
            manifest['stages'].append(dict(id='product_return_correlations',
                inputs=['inputs/common_nav_usd.csv', 'products/market_data/amundi_2x_nav_usd.csv',
                    f'config/{Path(config_path).name}', f'config/{Path(correlation_config_path).name}'],
                outputs=[str(p.relative_to(output)) for p in sorted((output/'correlations').iterdir())]))
            write_json(output/'run_manifest.json', manifest)
        holdings = None
        if holdings_settings is not None:
            holdings = snapshot_comparison(sources, config, holdings_settings)
            (output/'holdings_snapshot').mkdir()
            for name, frame in holdings['frames'].items():
                frame_csv(output/'holdings_snapshot'/name, frame)
            write_json(output/'holdings_snapshot/summary.json', holdings['summary'])
            write_json(output/'holdings_snapshot/snapshot_definitions.json', holdings['definitions'])
            manifest['stages'].append(dict(id='later_holdings_snapshot',
                inputs=[r['path'] for r in spec['sources'] if r['role'] in config['target_weights']]
                    + [f'config/{Path(config_path).name}', f'config/{Path(holdings_config_path).name}'],
                outputs=[str(p.relative_to(output)) for p in sorted((output/'holdings_snapshot').iterdir())]))
            write_json(output/'run_manifest.json', manifest)
        annual = None
        if annual_settings is not None:
            annual = build_annual_core_study(annual_raw_root, annual_settings, output)
            for name, frame in annual['frames'].items():
                # Preserve the historical schedule's full float serialization,
                # rather than the investment-account CSV precision convention.
                frame.to_csv(output/'annual_core'/name, index=False, lineterminator='\n')
            write_json(output/'annual_core/annual_definitions.json', annual['definitions'])
            manifest['stages'].append(dict(id='historical_core_annual_holdings',
                inputs=[f"annual_raw_root/{r['path']}" for r in annual_settings['reports']]
                    + [f'config/{Path(annual_config_path).name}'],
                outputs=[str(p.relative_to(output)) for p in sorted((output/'annual_core').rglob('*')) if p.is_file()]))
            write_json(output/'run_manifest.json', manifest)
        factor_annual = None
        if factor_annual_settings is not None:
            factor_annual = build_factor_annual_study(factor_annual_raw_root, factor_annual_settings, output)
            for name,frame in factor_annual['frames'].items():
                frame.to_csv(output/'annual_factors'/name,index=False,lineterminator='\n')
            write_json(output/'annual_factors/annual_definitions.json',factor_annual['definitions'])
            manifest['stages'].append(dict(id='historical_factor_annual_holdings',
                inputs=[f"factor_annual_raw_root/{r['path']}" for r in factor_annual_settings['sources']]
                    + [f'config/{Path(factor_annual_config_path).name}'],
                outputs=[str(p.relative_to(output)) for p in sorted((output/'annual_factors').rglob('*')) if p.is_file()]))
            write_json(output/'run_manifest.json',manifest)
        dimensional_annual = None
        if dimensional_settings is not None:
            dimensional_annual = build_dimensional_study(dimensional_annual_raw_root,dimensional_settings,output)
            for name,frame in dimensional_annual['frames'].items():
                frame.to_csv(output/'annual_dimensional'/name,index=False,lineterminator='\n')
            write_json(output/'annual_dimensional/annual_definitions.json',dimensional_annual['definitions'])
            write_json(output/'annual_dimensional/dimensional_second_reader_checks.json',dimensional_annual['checks'])
            manifest['stages'].append(dict(id='historical_dimensional_annual_holdings',
                inputs=[f"dimensional_annual_raw_root/{r['path']}" for r in dimensional_settings['reports']]
                    + [f'config/{Path(dimensional_annual_config_path).name}'],
                outputs=[str(p.relative_to(output)) for p in sorted((output/'annual_dimensional').rglob('*')) if p.is_file()]))
            write_json(output/'run_manifest.json',manifest)
        collateral = None
        if collateral_settings is not None:
            collateral = collateral_comparison(config,collateral_settings)
            (output/'collateral').mkdir()
            collateral['states'].to_csv(output/'collateral/collateral_limit_diagnostics.csv',index=False,lineterminator='\n')
            write_json(output/'collateral/collateral_definitions.json',collateral['definitions'])
            manifest['stages'].append(dict(id='single_state_collateral_limits',
                inputs=[f'config/{Path(config_path).name}',f'config/{Path(collateral_config_path).name}',
                    f"collateral_raw_root/{collateral_settings['source']['path']}"],
                outputs=['collateral/collateral_limit_diagnostics.csv','collateral/collateral_definitions.json']))
            write_json(output/'run_manifest.json',manifest)
        custody = None
        if custody_settings is not None:
            custody=custody_comparison(returns,reference,config,custody_settings)
            (output/'custody').mkdir()
            custody_files=dict(metrics='custody_metrics.csv',curves='custody_equity_curves.csv',events='custody_trade_events.csv',ledger='custody_ledger.csv',
                legacy_metrics='legacy_hybrid_custody_metrics.csv',legacy_curves='legacy_hybrid_custody_equity_curves.csv',
                legacy_events='legacy_hybrid_custody_trade_events.csv',legacy_ledger='legacy_hybrid_custody_ledger.csv')
            for key,name in custody_files.items():custody[key].to_csv(output/'custody'/name,index=key in {'curves','legacy_curves'},lineterminator='\n')
            for name,frame in custody['histories'].items():frame.to_csv(output/'custody'/name,index=False,lineterminator='\n')
            write_json(output/'custody/custody_definitions.json',custody['definitions'])
            manifest['stages'].append(dict(id='quarterly_custody_sensitivities',
                inputs=['inputs/common_returns_usd.csv','inputs/canonical/daily_borrow_rates_usd.csv',
                    f'config/{Path(config_path).name}',f'config/{Path(custody_config_path).name}',f"custody_raw_root/{custody_settings['source']['path']}"],
                outputs=[str(p.relative_to(output)) for p in sorted((output/'custody').iterdir())]))
            write_json(output/'run_manifest.json',manifest)
        (output / 'README.md').write_text('# Historical baseline calculation run\n\n'
            'Local research output from separately supplied raw data.\n\n'
            '- [Policy and period metrics](results/policy_metrics.csv)\n'
            '- [Selected primary metrics](results/primary_metrics.csv)\n'
            '- [Selected comparison metrics](results/selected_comparison_metrics.csv)\n'
            '- [Policy selection](results/selection.json)\n'
            '- [Historical equity curves](results/equity_curves.csv)\n'
            '- [Factor trade events](results/trade_events.csv)\n'
            '- [Input calendar](inputs/calendar.json)\n'
            '- [Independent period restarts](inputs/periods.json)\n'
            '- [Captured configurations](config/)\n'
            '- [Run manifest](run_manifest.json)\n\n'
            + f'Primary sleeve policy: `{primary}`. See captured configuration and selection metadata.\n\n'
            + (f"Funding experiments included: [{len(funding['metrics'])}-case grid](results/funding_metrics.csv), "
               '[CAGR crossing](results/financing_threshold.json) and [search diagnostics](results/funding_search.json). '
               'Margins are added to observed reference rates; nonbaseline terms are hypothetical.\n\n' if funding is not None else 'Funding experiments explicitly excluded from this run.\n\n')
            + (f"Counterfactual comparison included: [{len(bridge['metrics'])} cases](results/counterfactual_bridge.csv) and "
               '[sequential/control differences](results/counterfactual_steps.csv). '
               'Differences depend on order; they are not an additive causal attribution.\n\n' if bridge is not None else 'Counterfactual comparison explicitly excluded from this run.\n\n')
            + (f"Fresh-entry sensitivity included: [{len(entries['metrics'])} cases](results/fresh_entry_metrics.csv), "
               '[policy comparisons](results/entry_policy_comparison.csv), [date mapping](results/entry_dates.json), '
               '[descriptive counts](results/entry_comparison_summary.json) and [legacy reference view](results/legacy_hybrid_entry_metrics.csv). '
               'Capital, debt and entry charges restart; unequal overlapping horizons are retrospective.\n\n' if entries is not None else 'Fresh-entry sensitivity explicitly excluded from this run.\n\n')
            + ('Rolling analysis included: [fresh accounts](results/rolling_fresh_metrics.csv), '
               '[ongoing accounts](results/rolling_ongoing_metrics.csv), [policy comparison](results/rolling_policy_comparison.csv), '
               '[monthly windows against Core](results/rolling_monthly_vs_core.csv), [monthly summary](results/rolling_monthly_summary.csv) '
               'and [definitions](results/rolling_definitions.json). Overlapping retrospective windows; fresh and ongoing wealth bases differ.\n\n' if rolling is not None else 'Rolling analysis explicitly excluded from this run.\n\n')
            + ('Hypothetical margin/gap controls included: [account metrics](results/margin_metrics.csv), '
               '[trade/call events](results/margin_events.csv), [static gap probes](results/margin_gap_probes.csv) '
               'and [definitions](results/margin_definitions.json). Assumed terms and NAV timing, not verified bank contracts.\n\n' if margin is not None else 'Margin/gap controls explicitly excluded from this run.\n\n')
            + ('Artificial regimes included in a separate directory: [mechanics results](synthetic/synthetic_metrics.csv), '
               '[account paths](synthetic/synthetic_histories.csv), [recovery/censoring](synthetic/synthetic_recovery.csv) '
               'and [definitions](synthetic/synthetic_definitions.json). Fictional prices and weekday labels, not market observations or forecasts.\n\n' if synthetic is not None else 'Artificial regimes explicitly excluded from this run.\n\n')
            + ('Separate short-window product comparison included: [metrics](products/product_overlap_metrics.csv), '
               '[normalized curves](products/product_overlap_curves.csv) and [calendar/provenance definitions](products/product_definitions.json). '
               'Daily-reset ETF/index and band-managed 1.25x/2x portfolios have different economics; this does not change the long main calendar.\n\n' if products is not None else 'Short product comparison explicitly excluded from this run.\n\n')
            + ('Product-return correlations included: [long daily matrix](correlations/long_full_pearson.csv), '
               '[short six-product matrix](correlations/short_with_amundi_pearson.csv), '
               '[all pairs](correlations/pairwise_correlations.csv), [rolling summary](correlations/rolling_summary.csv) '
               'and [definitions](correlations/correlation_definitions.json). Common levels precede returns; daily/monthly, long/short '
               'and conditional samples stay separate. Descriptive co-movement, not causal factor independence.\n\n' if correlations is not None else 'Product-return correlations explicitly excluded from this run.\n\n')
            + ('Later issuer holdings snapshot included: [combined security lines](holdings_snapshot/combined_equity_holdings.csv), '
               '[dated summary](holdings_snapshot/summary.json), [pairwise overlap](holdings_snapshot/pairwise_overlap.csv) '
               'and [definitions](holdings_snapshot/snapshot_definitions.json). Target-weight gross-asset exposure after the backtest cutoff, '
               'not historical attribution or an ISIN-reconciled issuer master.\n\n' if holdings is not None else 'Later holdings snapshot explicitly excluded from this run.\n\n')
            + ('Historical Core annual schedules included: [security lines](annual_core/historical_equity_holdings.csv), '
               '[country exposures](annual_core/historical_country_exposures.csv), '
               '[dated concentration](annual_core/historical_concentration_summary.csv) and [source/page definitions](annual_core/annual_definitions.json). '
               'Three June year ends; published NAV denominator, separate listings/classes and no historical return attribution.\n\n' if annual is not None else 'Historical Core annual schedules explicitly excluded from this run.\n\n')
            + ('Historical factor annual schedules included: [security lines](annual_factors/historical_equity_holdings.csv), '
               '[concentration](annual_factors/historical_concentration_summary.csv), [dated equity-normalized overlap](annual_factors/factor_name_overlap.csv) '
               'and [source/page definitions](annual_factors/annual_definitions.json). May snapshots remain separate from Core June/Dimensional November; '
               'name/currency overlap differs from the later ticker-based snapshot and NAV-return correlations.\n\n' if factor_annual is not None else 'Historical factor annual schedules explicitly excluded from this run.\n\n')
            + ('Dimensional annual schedules included: [security lines](annual_dimensional/historical_equity_holdings.csv), '
               '[dated concentration](annual_dimensional/historical_concentration_summary.csv), '
               '[independent layout checks](annual_dimensional/dimensional_second_reader_checks.json) and [definitions](annual_dimensional/annual_definitions.json). '
               'Common stock, shares/values in thousands, retained rounding residuals; numeric reader agreement does not prove unrounded books or issuer/ISIN classification.\n\n' if dimensional_annual is not None else 'Dimensional annual schedules explicitly excluded from this run.\n\n')
            + ('Single-state collateral-limit diagnostics included: [states](collateral/collateral_limit_diagnostics.csv) '
               'and [source/assumption definitions](collateral/collateral_definitions.json). Imposed losses/lending fractions and buffered sale cures, '
               'not approved account terms, historical lender actions or changes to the main leverage rule.\n\n' if collateral is not None else 'Single-state collateral diagnostics explicitly excluded from this run.\n\n')
            + ('Quarterly custody sensitivities included: [metrics](custody/custody_metrics.csv), [expense ledger](custody/custody_ledger.csv), '
               '[trade events](custody/custody_trade_events.csv) and [definitions](custody/custody_definitions.json). Current-tariff hypotheses with '
               'fee-induced signal changes; no-custody histories/events reproduce the unchanged main accounting.\n\n' if custody is not None else 'Custody sensitivities explicitly excluded from this run.\n\n')
            + 'Remaining diagnostics, the required historical inflow connection and full reports remain separate work. Raw and derived provider observations have no public inclusion decision.\n', encoding='utf-8')
        admit_sources(raw_root, spec)
        if product_settings is not None:admit_product_sources(raw_root,product_settings)
        if annual_settings is not None:admit_annual_sources(annual_raw_root,annual_settings)
        if factor_annual_settings is not None:admit_factor_annual_sources(factor_annual_raw_root,factor_annual_settings)
        if dimensional_settings is not None:admit_dimensional_sources(dimensional_annual_raw_root,dimensional_settings)
        if collateral_settings is not None:admit_collateral_source(collateral_raw_root,collateral_settings)
        if custody_settings is not None:admit_custody_source(custody_raw_root,custody_settings)
        if source_hashes() != code:
            raise RuntimeError('package source changed during calculation; repeat in a stable working copy')
        manifest['artifacts'] = {str(p.relative_to(output)): sha256(p) for p in sorted(output.rglob('*'))
            if p.is_file() and p.name != 'run_manifest.json' and p.relative_to(output).parts[0] != 'config'}
        manifest['periods'] = comparison['periods']
        manifest['selection'] = json.loads((output / 'results/selection.json').read_text())
        manifest['counts'] = dict(policy_cases=len(comparison['metrics']), full_levels=len(returns),
            curve_columns=len(comparison['curves'].columns)-1, factor_trade_events=len(comparison['events']),
            full_hybrid_histories=sum('factor_hybrid20_' in name for name in comparison['histories']),
            full_policy_histories=len(comparison['histories']))
        if funding is not None:
            manifest['counts'].update(funding_cases=len(funding['metrics']),
                threshold_evaluations=len(funding['diagnostics']['evaluations']))
        if bridge is not None:
            manifest['counts'].update(bridge_cases=len(bridge['metrics']), bridge_differences=len(bridge['differences']))
        if entries is not None:
            manifest['counts'].update(entry_dates=len(entries['dates']), entry_cases=len(entries['metrics']),
                legacy_entry_cases=len(entries['legacy_metrics']), entry_policy_comparisons=len(entries['comparison']))
        if rolling is not None:
            manifest['counts'].update(rolling_fresh_cases=len(rolling['fresh']),rolling_ongoing_cases=len(rolling['ongoing']),
                rolling_policy_comparisons=len(rolling['pairs']),rolling_monthly_comparisons=len(rolling['monthly']),
                legacy_rolling_windows=len(rolling['legacy_monthly']))
        if margin is not None:
            manifest['counts'].update(margin_cases=len(margin['metrics']),margin_events=len(margin['events']),
                gap_probes=len(margin['gaps']),legacy_margin_cases=len(margin['legacy_metrics']))
        if synthetic is not None:
            manifest['counts'].update(synthetic_cases=len(synthetic['metrics']),
                legacy_synthetic_cases=len(synthetic['legacy_metrics']),synthetic_history_rows=len(synthetic['histories']),
                synthetic_failures=len(synthetic['definitions']['failures']))
        if products is not None:
            manifest['counts'].update(product_cases=len(products['metrics']),product_common_levels=len(products['curves']),
                additional_product_sources=len(product_settings['sources']))
        if correlations is not None:
            manifest['counts'].update(correlation_panels=len(correlations['definitions']['panels']),
                correlation_pairs=len(correlations['frames']['pairwise_correlations.csv']),
                rolling_correlation_rows=len(correlations['frames']['rolling_252.csv']))
        if holdings is not None:
            manifest['counts'].update(snapshot_equity_lines=len(holdings['frames']['equity_holdings.csv']),
                snapshot_combined_lines=len(holdings['frames']['combined_equity_holdings.csv']),
                snapshot_overlap_pairs=len(holdings['frames']['pairwise_overlap.csv']))
        if annual is not None:
            manifest['counts'].update(annual_core_snapshots=len(annual['frames']['historical_snapshot_summary.csv']),
                annual_core_equity_lines=len(annual['frames']['historical_equity_holdings.csv']),
                annual_core_country_groups=len(annual['frames']['historical_country_exposures.csv']),
                annual_core_pdf_pages=len(annual['definitions']['extracted_pages']))
        if factor_annual is not None:
            manifest['counts'].update(annual_factor_snapshots=len(factor_annual['frames']['historical_snapshot_summary.csv']),
                annual_factor_equity_lines=len(factor_annual['frames']['historical_equity_holdings.csv']),
                annual_factor_country_groups=len(factor_annual['frames']['historical_country_exposures.csv']),
                annual_factor_pdf_pages=len(factor_annual['definitions']['extracted_pages']),
                annual_factor_overlap_pairs=len(factor_annual['frames']['factor_name_overlap.csv']))
        if dimensional_annual is not None:
            manifest['counts'].update(annual_dimensional_snapshots=len(dimensional_annual['frames']['historical_snapshot_summary.csv']),
                annual_dimensional_equity_lines=len(dimensional_annual['frames']['historical_equity_holdings.csv']),
                annual_dimensional_country_groups=len(dimensional_annual['frames']['historical_country_exposures.csv']),
                annual_dimensional_pdf_pages=len(dimensional_annual['definitions']['extracted_pages']),
                annual_dimensional_layout_checks=len(dimensional_annual['checks']))
        if collateral is not None:
            manifest['counts'].update(collateral_states=len(collateral['states']),collateral_status_counts=collateral['definitions']['status_counts'])
        if custody is not None:
            manifest['counts'].update(custody_cases=len(custody['metrics']),custody_ledger_rows=len(custody['ledger']),
                custody_trade_events=len(custody['events']),custody_no_fee_checks=len(custody['definitions']['no_custody_checks']))
        manifest['status'] = 'complete'
        manifest['finished_at_utc'] = datetime.now(timezone.utc).isoformat()
        write_json(output / 'run_manifest.json', manifest)
        verify_run(output)
    except Exception as error:
        manifest['status'] = 'failed'
        manifest['finished_at_utc'] = datetime.now(timezone.utc).isoformat()
        manifest['failure'] = dict(type=type(error).__name__, message=str(error))
        write_json(output / 'run_manifest.json', manifest)
        raise
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw-root', type=Path)
    parser.add_argument('--config', type=Path, default=Path('config/backtest_absolute_decoupled_2026-10-05.json'))
    parser.add_argument('--sources', type=Path, default=Path('config/backtest_sources.json'))
    parser.add_argument('--output', type=Path)
    parser.add_argument('--funding-config', type=Path, help='include the configured funding grid and CAGR threshold')
    parser.add_argument('--bridge-config', type=Path, help='include the configured allocation/trading/financing counterfactuals')
    parser.add_argument('--entry-config', type=Path, help='include independently restarted entry-date comparisons')
    parser.add_argument('--rolling-config', type=Path, help='include fresh/ongoing rolling-window comparisons')
    parser.add_argument('--margin-config', type=Path, help='include hypothetical margin-call and gap-loss controls')
    parser.add_argument('--synthetic-config', type=Path, help='include prespecified artificial market regimes')
    parser.add_argument('--product-config', type=Path, help='include a separate short Amundi/index comparison and six extra raw sources')
    parser.add_argument('--correlation-config', type=Path, help='include long/short product-return correlations; requires --product-config')
    parser.add_argument('--holdings-config', type=Path, help='include the later issuer holdings snapshot from the four admitted ETF exports')
    parser.add_argument('--annual-holdings-config', type=Path, help='include the historical Core annual-report schedules')
    parser.add_argument('--annual-raw-root', type=Path, help='separately supplied original annual PDFs; required with annual holdings')
    parser.add_argument('--factor-holdings-config', type=Path, help='include historical factor annual schedules and dated overlap')
    parser.add_argument('--factor-annual-raw-root', type=Path, help='separately supplied original iShares IV annual PDFs')
    parser.add_argument('--dimensional-holdings-config', type=Path, help='include Dimensional annual common-stock schedules and independent layout checks')
    parser.add_argument('--dimensional-annual-raw-root', type=Path, help='separately supplied original Dimensional annual PDFs')
    parser.add_argument('--collateral-config', type=Path, help='include hypothetical single-state lending-limit contractions')
    parser.add_argument('--collateral-raw-root', type=Path, help='preserved public collateral evidence PDF root')
    parser.add_argument('--custody-config', type=Path, help='include quarterly custody-cost full-path sensitivities')
    parser.add_argument('--custody-raw-root', type=Path, help='preserved public custody-pricing evidence root')
    parser.add_argument('--verify-run', type=Path)
    args = parser.parse_args()
    if args.verify_run:
        if args.output or args.raw_root or args.funding_config or args.bridge_config or args.entry_config or args.rolling_config or args.margin_config or args.synthetic_config or args.product_config or args.correlation_config or args.holdings_config or args.annual_holdings_config or args.annual_raw_root or args.factor_holdings_config or args.factor_annual_raw_root or args.dimensional_holdings_config or args.dimensional_annual_raw_root or args.collateral_config or args.collateral_raw_root or args.custody_config or args.custody_raw_root:
            parser.error('--verify-run cannot be combined with raw input/output arguments')
        print(json.dumps(verify_run(args.verify_run), indent=2))
    else:
        if args.raw_root is None or args.output is None:
            parser.error('--raw-root and --output are required for a new run')
        result = run_backtest_study(args.raw_root, args.config, args.sources, args.output,
            funding_config_path=args.funding_config, bridge_config_path=args.bridge_config, entry_config_path=args.entry_config,
            rolling_config_path=args.rolling_config, margin_config_path=args.margin_config,synthetic_config_path=args.synthetic_config,
            product_config_path=args.product_config, correlation_config_path=args.correlation_config, holdings_config_path=args.holdings_config,
            annual_config_path=args.annual_holdings_config, annual_raw_root=args.annual_raw_root,
            factor_annual_config_path=args.factor_holdings_config, factor_annual_raw_root=args.factor_annual_raw_root,
            dimensional_annual_config_path=args.dimensional_holdings_config, dimensional_annual_raw_root=args.dimensional_annual_raw_root,
            collateral_config_path=args.collateral_config,collateral_raw_root=args.collateral_raw_root,
            custody_config_path=args.custody_config,custody_raw_root=args.custody_raw_root)
        print(json.dumps(dict(status=result['status'], run_id=result['run_id'], counts=result['counts']), indent=2))


if __name__ == '__main__':
    main()
