"""Published issuer annual returns compared with frozen NAV precision intervals."""
from __future__ import annotations

import argparse
from datetime import datetime,timezone
import json
import math
from pathlib import Path
import uuid

import numpy as np
import pandas as pd

from .backtest_workflow import run_backtest_study,validate_config
from .inflow_workflow import sha256,source_hashes,verify_run,write_json


def validate_settings(settings,sources):
    if (settings['schema_version']!=1 or settings['years']!=list(range(2016,2026))
        or settings['published_rounding_half_width_percentage_points']!=.05
        or settings['maximum_year_end_deferral_days']!=7
        or list(settings['products'])!=['core','momentum','quality','value']):
        raise ValueError('original four-product/ten-year rounding contract required')
    identities={r['role']:r.get('identity') for r in sources['sources']}
    for name,p in settings['products'].items():
        precision=.0000005 if name=='core' else .005
        if p['isin']!=identities[name] or p['nav_rounding_half_width_usd']!=precision or not p['url'].startswith('https://www.ishares.com/'):
            raise ValueError('issuer identity/source/NAV precision mismatch')
        values=p['published_returns_pct']
        if len(values)!=10 or any(not math.isfinite(x) or x<=-100 or abs(x*10-round(x*10))>1e-9 for x in values):
            raise ValueError('ten finite one-decimal fund observations required')


def rounding_comparison(start,end,published,nav_half_width,published_half_width):
    if not all(math.isfinite(x) for x in [start,end,published,nav_half_width,published_half_width]) or min(start,end)<=nav_half_width or nav_half_width<=0 or published_half_width<=0:
        raise ValueError('positive NAVs and finite positive rounding bounds required')
    central=100*(end/start-1)
    low=100*((end-nav_half_width)/(start+nav_half_width)-1)
    high=100*((end+nav_half_width)/(start-nav_half_width)-1)
    return dict(published_return_pct=published,reconstructed_return_pct=central,difference_percentage_points=central-published,
        nav_rounding_lower_pct=low,nav_rounding_upper_pct=high,compatible_with_rounding=bool(low<=published+published_half_width and high>=published-published_half_width))


def issuer_comparison(levels,settings):
    levels=levels.copy();dates=pd.DatetimeIndex(pd.to_datetime(levels.pop('date')))
    if dates.hasnans or dates.has_duplicates or not dates.is_monotonic_increasing:raise ValueError('unique ordered NAV calendar required')
    products=list(settings['products'])
    if not np.isfinite(levels[products].to_numpy(float)).all() or (levels[products]<=0).any().any():raise ValueError('finite positive NAVs required')
    levels.index=dates;ends=levels.groupby(levels.index.year).tail(1);rows=[];endpoints=[]
    required=range(settings['years'][0]-1,settings['years'][-1]+1)
    for name,p in settings['products'].items():
        for year in required:
            matches=ends[ends.index.year==year]
            if len(matches)!=1:raise ValueError('complete prior and current calendar-year endpoints required')
            day=matches.index[0];deferral=(pd.Timestamp(year=year,month=12,day=31)-day).days
            if not 0<=deferral<=settings['maximum_year_end_deferral_days']:raise ValueError('annual endpoint is truncated or too early')
            endpoints.append(dict(sleeve=name,year=year,actual_date=str(day.date()),calendar_year_end=f'{year}-12-31',deferral_days=deferral,nav_usd=float(matches[name].iloc[0]),nav_rounding_half_width_usd=p['nav_rounding_half_width_usd']))
        for year,published in zip(settings['years'],p['published_returns_pct']):
            start=float(ends[ends.index.year==year-1][name].iloc[0]);end=float(ends[ends.index.year==year][name].iloc[0])
            rows.append(dict(sleeve=name,year=year,**rounding_comparison(start,end,published,p['nav_rounding_half_width_usd'],settings['published_rounding_half_width_percentage_points'])))
    return pd.DataFrame(rows),pd.DataFrame(endpoints)


def run_issuer_returns(raw_root,baseline_path,sources_path,settings_path,output):
    output=Path(output)
    if output.exists():raise FileExistsError('choose a new issuer-return output directory')
    paths=[baseline_path,sources_path,settings_path];captured={Path(p).name:Path(p).read_bytes() for p in paths}
    if len(captured)!=3:raise ValueError('distinct configuration filenames required')
    baseline,spec,settings=[json.loads(captured[Path(p).name]) for p in paths]
    validate_config(baseline);validate_settings(settings,spec)
    output.mkdir(parents=True);(output/'config').mkdir()
    for name,data in captured.items():(output/'config'/name).write_bytes(data)
    code=source_hashes();manifest=dict(schema_version=1,run_id=str(uuid.uuid4()),status='running',figures_included=False,
        started_at_utc=datetime.now(timezone.utc).isoformat(),code=code,
        scope='Fresh original-input core and forty issuer annual NAV-return/rounding comparisons against captured published observations. Not a second daily NAV feed or final report.',
        configuration_snapshots={f'config/{name}':sha256(output/'config'/name) for name in captured},artifacts={})
    write_json(output/'run_manifest.json',manifest)
    try:
        core=run_backtest_study(raw_root,output/'config'/Path(baseline_path).name,output/'config'/Path(sources_path).name,output/'core')
        # Match the original published-return producer's serialized-level read.
        levels=pd.read_csv(output/'core/inputs/common_nav_usd.csv')
        table,endpoints=issuer_comparison(levels,settings)
        table.to_csv(output/'published_issuer_return_comparison.csv',index=False,lineterminator='\n')
        endpoints.to_csv(output/'annual_nav_endpoints.csv',index=False,lineterminator='\n')
        compatible=bool(table.compatible_with_rounding.all())
        write_json(output/'issuer_return_checks.json',dict(comparisons=len(table),compatible_count=int(table.compatible_with_rounding.sum()),all_compatible=compatible,
            maximum_absolute_difference_percentage_points=float(table.difference_percentage_points.abs().max()),
            nearest_rounding_assumption='Core NAV six decimals, factors to cents; published fund returns one decimal. Closed interval overlap is compatibility, not high-precision equality.',
            calendar='Last common observation in each completed year; prior year ends 2015-2024 and current year ends 2016-2025. Partial 2026 excluded.',
            references=settings['products'],primary_page_values_rechecked_on=settings['primary_page_values_rechecked_on'],
            limitations=['Captured annual observations are distinct reference inputs, not new daily prices.',
                'Current page recheck does not recover the complete original October 2 HTML snapshot.',
                'Annual compatibility does not independently prove every daily NAV, execution prices or future returns.']))
        (output/'README.md').write_text('# Issuer Annual Return Checks\n\nPublished fund USD total-return observations versus regenerated common NAV year-end ratios and nearest-rounding bounds. '
            'Compatibility is not exact equality or a second complete daily NAV feed. All mismatches remain visible.\n\n'
            '[Forty comparisons](published_issuer_return_comparison.csv) · [Year-end NAV evidence](annual_nav_endpoints.csv) · [Bounds/sources](issuer_return_checks.json) · [Fresh core](core/README.md) · [Manifest](run_manifest.json)\n')
        if source_hashes()!=code:raise RuntimeError('source changed during issuer-return comparison')
        manifest['artifacts']={str(p.relative_to(output)):sha256(p) for p in sorted(output.rglob('*')) if p.is_file() and p!=output/'run_manifest.json' and p.relative_to(output).parts[0]!='config'}
        manifest.update(status='complete',finished_at_utc=datetime.now(timezone.utc).isoformat(),raw_sources=core['raw_sources'],
            counts=dict(issuer_comparisons=len(table),compatible_comparisons=int(table.compatible_with_rounding.sum()),annual_nav_endpoints=len(endpoints),core_cases=core['counts']['policy_cases']))
        write_json(output/'run_manifest.json',manifest);verify_run(output)
    except Exception as error:
        manifest.update(status='failed',failure=dict(type=type(error).__name__,message=str(error)));write_json(output/'run_manifest.json',manifest);raise
    return manifest


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--raw-root',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    for key,name in [('baseline','backtest_absolute_decoupled_2026-10-05.json'),('sources','backtest_sources.json'),('settings','issuer_annual_returns_2026-10-05.json')]:p.add_argument('--'+key,type=Path,default=Path('config')/name)
    a=p.parse_args();m=run_issuer_returns(a.raw_root,a.baseline,a.sources,a.settings,a.output);print(json.dumps(dict(run_id=m['run_id'],status=m['status'],counts=m['counts']),indent=2))


if __name__=='__main__':main()
