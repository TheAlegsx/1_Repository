"""Separate short-window product/leveraged-index evidence from admitted local sources."""
from __future__ import annotations

from datetime import date
import math
from pathlib import Path

import numpy as np
import pandas as pd

from .config import PortfolioConfig, SwissquoteStandardFeeSchedule
from .historical import simulate
from .inflow_workflow import sha256
from .market_data import (DEFAULT_BLOOMBERG_SPECS, DEFAULT_AMUNDI_FILENAME, AMUNDI_ISIN,
    build_market_dataset, write_market_dataset, load_market_dataset)
from .reference import build_investable_reference_comparison, write_investable_reference_comparison


def validate_settings(settings,baseline):
    if settings['schema_version']!=1:raise ValueError('unsupported product study schema')
    date.fromisoformat(settings['cutoff'])
    policies=settings['factor_policies'];primary=baseline.get('primary_policy','hybrid20')
    if not policies or len(set(policies))!=len(policies) or primary not in policies or 'hybrid20' not in policies or any(p not in baseline['policies'] for p in policies):
        raise ValueError('product comparison must include the selected calculated primary')
    exposures=settings['factor_exposures']
    if (not exposures or len(set(exposures))!=len(exposures) or any(not math.isfinite(x) or x<1 for x in exposures)
        or len({f'{x:.2f}' for x in exposures})!=len(exposures)
        or baseline.get('primary_leverage',max(baseline['leverage_levels'])) not in exposures):
        raise ValueError('invalid distinct product comparison exposures')
    expected=settings['expected_common']
    if expected['levels']<2 or date.fromisoformat(expected['start'])>=date.fromisoformat(expected['end']):
        raise ValueError('invalid expected product calendar')


def admit_sources(raw_root,settings):
    root=Path(raw_root).resolve();records={x['role']:x for x in settings['sources']}
    expected={s.key for s in DEFAULT_BLOOMBERG_SPECS}|{'amundi_2x'}
    if len(settings['sources'])!=6 or set(records)!=expected:
        raise ValueError('product source contract requires exactly six listing/index/NAV files')
    paths={}
    for role,item in records.items():
        path=(root/item['path']).resolve()
        if not path.is_relative_to(root) or not path.is_file():raise ValueError('product source missing or outside raw root: '+role)
        if sha256(path)!=item['sha256']:raise ValueError('product source checksum mismatch: '+role)
        paths[role]=path
    folder=paths['iwda'].parent
    for spec in DEFAULT_BLOOMBERG_SPECS:
        if paths[spec.key]!=folder/spec.filename or records[spec.key]['identity']!=spec.security:
            raise ValueError('product listing/index role or importer layout mismatch')
    if paths['amundi_2x'].name!=DEFAULT_AMUNDI_FILENAME or records['amundi_2x']['identity']!=AMUNDI_ISIN:
        raise ValueError('unexpected Amundi file or identity')
    return paths


def product_comparison(dataset,reference,market,baseline,settings):
    validate_settings(settings,baseline)
    fee=SwissquoteStandardFeeSchedule(**baseline['fee_schedule'])
    config=PortfolioConfig(target_weights=baseline['target_weights'],initial_equity_usd=baseline['initial_equity_usd'],
        target_leverage=baseline.get('primary_leverage',max(baseline['leverage_levels'])),sleeve_band=baseline['sleeve_band'],
        leverage_band=baseline['leverage_band'],day_count=baseline['measurement']['reference_day_count'],fee_schedule=fee)
    ref=build_investable_reference_comparison(dataset.returns_usd,
        reference+baseline['borrowing_margin_annual'],market,config)
    panel=ref.levels;common=panel.index;expected=settings['expected_common']
    if len(common)!=expected['levels'] or str(common[0].date())!=expected['start'] or str(common[-1].date())!=expected['end']:
        raise ValueError('product/ETF intersection differs from admitted short reference window')
    if len(market.benchmark_overlap)!=settings['expected_market_levels']:
        raise ValueError('Amundi/index intersection differs from admitted source window')
    sleeves=list(baseline['target_weights']);weights=list(baseline['target_weights'].values())
    rows=[];curves={}
    for policy in settings['factor_policies']:
        for leverage in settings['factor_exposures']:
            # Simulate the full ETF calendar, then sample common levels, as the reference did.
            returns=dataset.nav_usd.loc[common[0]:common[-1],sleeves].pct_change(fill_method=None)
            returns.iloc[0]=0
            run=simulate(returns,reference,weights,leverage,policy,
                margin=baseline['borrowing_margin_annual'],sleeve_band=baseline['sleeve_band'],leverage_band=baseline['leverage_band'],
                initial_equity_usd=baseline['initial_equity_usd'],fee_schedule=fee)
            if run.status!='complete':raise ValueError('incomplete product comparison account')
            eq=run.history.equity_usd.loc[common];norm=eq/eq.iloc[0];r=norm.pct_change().iloc[1:]
            name=f'factor_{policy}_{leverage:.2f}x'
            rows.append(dict(strategy=name,start=str(common[0].date()),end=str(common[-1].date()),observations=len(norm),
                cumulative_return=float(norm.iloc[-1]-1),maximum_drawdown=float((norm/norm.cummax()-1).min()),
                annualised_volatility=float(r.std(ddof=1)*np.sqrt(252))))
            curves[name]=norm
    for name,column in [('amundi_2x','normalized_amundi_2x_nav_usd'),('index_2x','normalized_mxwoldnu_index_level_usd'),
                         ('core_banded_2x','normalized_core_banded_2x_equity_usd')]:
        norm=panel[column];r=norm.pct_change().iloc[1:]
        rows.append(dict(strategy=name,start=str(common[0].date()),end=str(common[-1].date()),observations=len(norm),
            cumulative_return=float(norm.iloc[-1]-1),maximum_drawdown=float((norm/norm.cummax()-1).min()),
            annualised_volatility=float(r.std(ddof=1)*np.sqrt(252))))
        curves[name]=norm
    metrics=pd.DataFrame(rows);curve_table=pd.DataFrame(curves).rename_axis('date').reset_index()
    legacy_metrics=metrics[~metrics.strategy.str.startswith('factor_')|metrics.strategy.str.startswith('factor_hybrid20_')].copy()
    legacy_metrics['strategy']=legacy_metrics.strategy.str.replace('factor_hybrid20_','factor_hybrid_',regex=False)
    legacy_columns=['date']+[f'factor_hybrid20_{x:.2f}x' for x in settings['factor_exposures']]+['amundi_2x','index_2x','core_banded_2x']
    legacy_curves=curve_table[legacy_columns].rename(columns={f'factor_hybrid20_{x:.2f}x':f'factor_{x:.2f}x' for x in settings['factor_exposures']})
    return dict(reference=ref,metrics=metrics,curves=curve_table,legacy_metrics=legacy_metrics,legacy_curves=legacy_curves,
        definitions=dict(start=str(common[0].date()),end=str(common[-1].date()),common_levels=len(common),
            market_only_levels=len(market.benchmark_overlap),etf_levels_in_span=len(returns),
            excluded_market_dates=[str(x.date()) for x in market.benchmark_overlap.index.difference(common)],
            main_common_calendar_unchanged=True,normalization='Divide by first common post-entry value; initial modeled charges removed by normalization.',
            comparability='Daily-reset ETF/net index versus band-managed debt portfolios, with different embedded/modelled costs. 1.25x/2x exposure controls do not imply equivalent tracking or a new primary target.',
            interpretation='Short-window cumulative returns, not the long backtest CAGR. No investor purchase/exit costs imputed to product NAV/index.'))


def build_product_study(raw_root,settings,dataset,reference,baseline,output):
    paths=admit_sources(raw_root,settings)
    market=build_market_dataset(paths['iwda'].parent,paths['amundi_2x'].parent,cutoff=date.fromisoformat(settings['cutoff']))
    destination=Path(output)/'products';write_market_dataset(market,destination/'market_data')
    market=load_market_dataset(destination/'market_data')
    result=product_comparison(dataset,reference,market,baseline,settings)
    write_investable_reference_comparison(result['reference'],destination/'reference')
    admit_sources(raw_root,settings)
    return result
