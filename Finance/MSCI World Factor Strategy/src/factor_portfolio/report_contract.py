"""Bind coordinated report preparation to verified local evidence, without recalculation."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
import uuid

import pandas as pd

from .inflow_workflow import sha256, source_hashes, verify_run, write_json


def contained(root,relative):
    path=Path(relative)
    if path.is_absolute() or '..' in path.parts:raise ValueError('relative contained evidence path required')
    result=(Path(root)/path).resolve()
    if not result.is_relative_to(Path(root).resolve()):raise ValueError('evidence escapes project root')
    return result


def validate_settings(settings):
    if (settings['schema_version']!=1 or settings['primary_policy']!='absolute_decoupled'
        or settings['comparison_policy']!='hybrid20'):raise ValueError('current primary/comparison selection required')
    separation=settings['report_separation']
    if (separation['main_period']!=['2014-10-03','2026-08-28']
        or separation['historical_inflow_period']!=['2014-10-03','2024-10-03'] or separation['project_months']!=120
        or any(separation[k] is not True for k in ['primary_backtest_cagr_is_not_constant_inflow_return',
            'hypothetical_v4_scenarios_preserved','manager_cash_excludes_owner_and_external_portfolio_wealth'])
        or separation['execution_contract']!='executed_v2_not_archived_original_proposal'):
        raise ValueError('explicit backtest/historical/hypothetical and ownership separation required')
    tables=settings['tables'];ids=[x['id'] for x in tables]
    if len(ids)!=len(set(ids)) or len(ids)!=42 or sum(x['report']=='backtest' for x in tables)!=30:
        raise ValueError('unique thirty/twelve original table inventory required')
    for t in tables:
        if t['assembly_status']!='pending':raise ValueError('contract must not certify final report assembly')
        for key in t['dataset_refs']:
            if key not in settings['datasets']:raise ValueError('unknown table evidence dataset')
    ids=[x['id'] for x in settings['claims']]
    if len(ids)!=len(set(ids)):raise ValueError('unique numerical claim ids required')
    for definition in settings['datasets'].values():
        if definition['run'] not in settings['runs']:raise ValueError('unknown evidence run')
        contained(Path.cwd(),definition['path'])
    for path in settings['runs'].values():contained(Path.cwd(),path)



def validate_table_catalog(catalog, settings):
    """Bind report families without publishing private execution/archive metadata."""
    if (set(catalog) != {'schema_version', 'scope', 'tables'}
            or catalog['schema_version'] != 1
            or catalog['scope'] != 'public_table_catalog_without_private_execution_history'):
        raise ValueError('strict public table catalog required')
    allowed = {'id', 'report', 'section', 'header'}
    rows = catalog['tables']
    if not isinstance(rows, list) or any(not isinstance(row, dict) or set(row) != allowed for row in rows):
        raise ValueError('strict public table catalog fields required')
    if any(not isinstance(row[key], str) or not row[key] for row in rows for key in allowed):
        raise ValueError('nonempty public table catalog labels required')
    ids = [row['id'] for row in rows]
    if len(ids) != 42 or len(set(ids)) != 42 or any(row['report'] not in {'backtest', 'capital_inflows'} for row in rows):
        raise ValueError('unique public table catalog inventory required')
    inventory = [(row['id'], row['report'], row['section'], row['header']) for row in rows]
    bound = [(table['id'], table['report'], table['original_section'], table['original_header']) for table in settings['tables']]
    if inventory != bound:
        raise ValueError('table bindings differ from public table catalog')


def validate_source_register(register):
    if register['schema_version']!=1 or register['online_reverification_performed'] is not False:
        raise ValueError('saved-source attribution scope required')
    ids=[x['id'] for x in register['sources']]
    if len(ids)!=len(set(ids)):raise ValueError('duplicate source identity')
    inputs=[x for x in register['sources'] if x['category'] in ['raw_market_or_metadata','annual_report']]
    if len(inputs)!=register['raw_input_count']:raise ValueError('source input count differs')
    for entry in register['sources']:
        url=entry.get('source_url')
        if url:
            parsed=urlsplit(url)
            if parsed.scheme!='https' or not parsed.netloc or parsed.username or parsed.password:
                raise ValueError('plain HTTPS publisher citation required')
            keys={k.lower() for k in parse_qs(parsed.query)}
            if any(k.startswith('track') or k in {'user','token','key','apikey','api_key','signature','sig','access_token'} for k in keys):
                raise ValueError('private tracking or credential parameters cannot enter source register')
        if entry['id']=='amundi_2x' and (entry['source_url'] is not None or entry['retrieved_date'] is not None):
            raise ValueError('unresolved original Amundi provenance must remain explicit')


def select_claim(frame,definition):
    rows=frame
    for key,value in definition['selection'].items():rows=rows[rows[key].eq(value)]
    if len(rows)!=1:raise ValueError('claim requires exactly one selected evidence row')
    value=float(rows[definition['field']].iloc[0])
    if not math.isfinite(value):raise ValueError('finite claim value required')
    formats={'usd_million_3dp':(1e-6,'.3f'),'decimal_3dp':(1.,'.3f'),'percent_4dp':(100.,'.4f'),
        'pp_4dp':(1.,'.4f'),'usd_2dp':(1.,'.2f')}
    scale,form=formats[definition['display']]
    return dict(**definition,value=value,display_value=format(scale*value,form))


def link_historical_returns(basis,histories,baseline):
    """Check 240 actual-date links, including the cost-inclusive owner NAV basis."""
    required={'absolute_decoupled','hybrid20'}
    if set(basis.policy)!=required or len(basis)!=240 or basis.duplicated(['policy','month']).any():
        raise ValueError('two complete unique 120-month historical bases required')
    capital=baseline['initial_equity_usd'];tol=baseline['reconciliation_tolerances'];checks=[]
    for policy,group in basis.groupby('policy',sort=False):
        g=group.sort_values('month');h=histories[policy].copy();h.index=pd.to_datetime(h.index)
        if g.month.tolist()!=list(range(1,121)) or g.actual_start.iloc[0]!='2014-10-03' or g.actual_end.iloc[-1]!='2024-10-03':
            raise ValueError('historical horizon differs from declared ten project years')
        if g.actual_end.iloc[:-1].tolist()!=g.actual_start.iloc[1:].tolist():raise ValueError('noncontiguous historical windows')
        for row in g.to_dict('records'):
            opening=float(h.loc[pd.Timestamp(row['actual_start']),'equity_usd']);closing=float(h.loc[pd.Timestamp(row['actual_end']),'equity_usd'])
            errors={
                'opening_equity_usd':abs(opening-row['source_opening_equity_usd']),
                'closing_equity_usd':abs(closing-row['source_closing_equity_usd']),
                'owner_equity_usd':abs(closing-row['no_flow_zero_added_fee_owner_equity_usd']),
                'interval_return':abs(closing/opening-1-row['strategy_net_interval_return']),
                'owner_nav':abs(closing/capital*100-row['no_flow_unit_nav'])}
            limits=dict(opening_equity_usd=tol['account_usd_atol']+tol['account_rtol']*abs(opening),
                closing_equity_usd=tol['account_usd_atol']+tol['account_rtol']*abs(closing),
                owner_equity_usd=tol['account_usd_atol']+tol['account_rtol']*abs(closing),
                interval_return=tol['metric_atol'],owner_nav=tol['metric_atol'])
            for field,error in errors.items():
                checks.append(dict(policy=policy,month=row['month'],field=field,absolute_difference=error,
                    allowed_difference=limits[field],passed=error<=limits[field]))
    if not all(x['passed'] for x in checks):raise ValueError('historical inflow basis does not match main account history')
    return pd.DataFrame(checks)


def ai_disclosure(document):
    paragraphs=document.split('\n\n')
    selected=[x.strip() for x in paragraphs if x.startswith('This portfolio-backtest and capital-inflow research package')]
    if len(selected)!=1 or 'extensive assistance' not in selected[0]:raise ValueError('preserved comprehensive AI disclosure required')
    return selected[0]


def verify_bindings(root,contract):
    for definition in contract['resolved_runs'].values():
        directory=contained(root,definition['path']);m=json.loads((directory/'run_manifest.json').read_text())
        if m['run_id']!=definition['run_id'] or sha256(directory/'run_manifest.json')!=definition['manifest_sha256']:
            raise ValueError('selected source run identity or manifest changed')
        verify_run(directory)
    for definition in contract['resolved_datasets'].values():
        if sha256(contained(root,definition['project_path']))!=definition['sha256']:raise ValueError('bound dataset changed')


def source_markdown(register,disclosure):
    lines=['# Sources and Download Evidence','',
        'Saved provenance consolidated for report preparation. URLs and prices were not updated online in this block. '
        'Retrieval dates, valuation dates and inferred export dates are distinguished. Raw data and detailed provider-derived files stay local.','',
        '| Source / role | Publisher | Recorded retrieval date | Date evidence / qualification |','|---|---|---|---|']
    for entry in register['sources']:
        label=f"[{entry['id']}]({entry['source_url']})" if entry.get('source_url') else entry['id']
        lines.append('| '+ ' | '.join([label,entry.get('publisher') or 'Project metadata',entry.get('retrieved_date') or 'Unknown',entry['date_basis']])+' |')
    lines+=['','## Known provenance limits','']+['- '+x for x in register['open_provenance']]
    lines+=['','## Model assumptions','']+['- '+x for x in register['model_assumptions']]
    lines+=['','## AI use','',disclosure,'','This declaration covers Alex’s research contribution; it does not attribute unverified AI use to other group members or the video.']
    return '\n'.join(lines)+'\n'


def run_contract(root,settings_path,output):
    root=Path(root).resolve();settings_path=Path(settings_path);output=Path(output)
    if output.exists():raise FileExistsError('choose a new report-contract output directory')
    settings=json.loads(settings_path.read_text());validate_settings(settings)
    paths=[settings_path]+[contained(root,settings[k]) for k in ['source_register','coverage','ai_document','baseline','inflow_assumptions','execution']]
    captured={p.name:p.read_bytes() for p in paths}
    if len(captured)!=len(paths):raise ValueError('distinct captured input filenames required')
    read=lambda key:json.loads(captured[Path(settings[key]).name])
    register=read('source_register');coverage=read('coverage');baseline=read('baseline');acq=read('inflow_assumptions');execution=read('execution')
    validate_source_register(register);disclosure=ai_disclosure(captured[Path(settings['ai_document']).name].decode())
    if (baseline['primary_policy']!=settings['primary_policy'] or baseline['target_weights']!={'core':.6,'momentum':.15,'quality':.1,'value':.15}
        or baseline['initial_equity_usd']!=7000000 or baseline['primary_leverage']!=1.25 or baseline['sleeve_band']!=.05
        or baseline['leverage_band']!=.1 or execution['execution_version']!=2):raise ValueError('fixed baseline and executed historical v2 required')
    if acq['annual_returns']!={'flat':[0]*10,'growth':[.06]*10,'early_loss':[-.3]+[0]*9,'late_loss':[.06]*3+[-.3]+[0]*6}:
        raise ValueError('retained explicitly hypothetical v4 paths required')
    validate_table_catalog(coverage, settings)
    output.mkdir(parents=True);(output/'config').mkdir()
    for name,data in captured.items():(output/'config'/name).write_bytes(data)
    code=source_hashes();manifest=dict(schema_version=1,run_id=str(uuid.uuid4()),status='running',figures_included=False,
        started_at_utc=datetime.now(timezone.utc).isoformat(),scope=settings['scope'],code=code,
        configuration_snapshots={f'config/{n}':sha256(output/'config'/n) for n in captured},artifacts={})
    write_json(output/'run_manifest.json',manifest)
    try:
        runs={};manifests={}
        for name,path in settings['runs'].items():
            directory=contained(root,path);verification=verify_run(directory);m=json.loads((directory/'run_manifest.json').read_text());manifests[name]=m
            runs[name]=dict(path=path,run_id=m['run_id'],manifest_sha256=sha256(directory/'run_manifest.json'),verified_files=verification['verified_files'])
        # Reviewed current settings must match the selected calculation snapshots.
        for run_name,relative,input_key in [('core','config/'+Path(settings['baseline']).name,'baseline'),
            ('historical','pilot/basis/core/config/'+Path(settings['baseline']).name,'baseline'),
            ('inflow_v4','config/'+Path(settings['inflow_assumptions']).name,'inflow_assumptions'),
            ('historical','pilot/config/'+Path(settings['execution']).name,'execution')]:
            f=contained(root,settings['runs'][run_name]+'/'+relative)
            if f.read_bytes()!=captured[Path(settings[input_key]).name]:raise ValueError('selected evidence uses different captured assumptions')
        resolved={};frames={}
        for key,definition in settings['datasets'].items():
            run=definition['run'];path=definition['path'];m=manifests[run]
            if path not in m['artifacts']:raise ValueError('dataset absent from selected run manifest')
            project_path=settings['runs'][run]+'/'+path;f=contained(root,project_path)
            resolved[key]=dict(**definition,project_path=project_path,sha256=m['artifacts'][path],run_id=m['run_id'])
            if sha256(f)!=m['artifacts'][path]:raise ValueError('dataset hash differs')
            if path.endswith('.csv'):frames[key]=pd.read_csv(f,float_precision='round_trip')
        claims=[select_claim(frames[d['dataset']],d) for d in settings['claims']]
        histories={p:frames[k].set_index('date') for p,k in [('absolute_decoupled','absolute_history'),('hybrid20','hybrid_history')]}
        historical=link_historical_returns(frames['historical_basis'],histories,baseline)
        contract=dict(schema_version=1,scope=settings['scope'],resolved_runs=runs,resolved_datasets=resolved,
            tables=settings['tables'],claims=claims,report_separation=settings['report_separation'],disclosure=disclosure,
            disclosure_placements=settings['disclosure_placements'],supplementary_evidence=settings['supplementary_evidence'],remaining_scope=settings['remaining_scope'])
        verify_bindings(root,contract)
        write_json(output/'evidence_contract.json',contract)
        pd.DataFrame(claims).assign(selection=lambda x:x.selection.map(lambda v:json.dumps(v,sort_keys=True))).to_csv(output/'selected_claims.csv',index=False)
        rows=[dict(id=t['id'],report=t['report'],original_section=t['original_section'],original_rows=t['original_rows'],
            binding_scope=t['binding_scope'],datasets=';'.join(t['dataset_refs']),assembly_status=t['assembly_status']) for t in settings['tables']]
        pd.DataFrame(rows).to_csv(output/'table_bindings.csv',index=False);historical.to_csv(output/'historical_return_link_checks.csv',index=False)
        (output/'source_register.md').write_text(source_markdown(register,disclosure))
        (output/'ai_disclosure.md').write_text('# AI Use Disclosure\n\n'+disclosure+'\n\nFor visible placement in both report introductions and the package/source-register entry. Scope: Alex’s research contribution; no claim about other group members or future video narration.\n')
        (output/'README.md').write_text('# Coordinated Report Evidence Preparation\n\n'
            'Forty-two legacy table-family bindings and selected current headline claims, not finished reports or every narrative/cell verification. '
            'The historical inflow branch uses the actual portfolio path over its own ten-year calendar; v4 hypothetical paths remain separate.\n\n'
            '[Contract](evidence_contract.json) · [Table bindings](table_bindings.csv) · [Selected claims](selected_claims.csv) · '
            '[Historical links](historical_return_link_checks.csv) · [Sources](source_register.md) · [AI disclosure](ai_disclosure.md) · [Manifest](run_manifest.json)\n')
        if source_hashes()!=code or any(p.read_bytes()!=captured[p.name] for p in paths):raise RuntimeError('report preparation inputs/code changed during execution')
        manifest['artifacts']={str(p.relative_to(output)):sha256(p) for p in sorted(output.rglob('*')) if p.is_file()
            and p!=output/'run_manifest.json' and p.relative_to(output).parts[0]!='config'}
        manifest.update(status='complete',finished_at_utc=datetime.now(timezone.utc).isoformat(),counts=dict(evidence_runs=len(runs),
            datasets=len(resolved),legacy_table_bindings=len(rows),selected_claims=len(claims),historical_link_checks=len(historical),source_entries=len(register['sources'])))
        write_json(output/'run_manifest.json',manifest);verify_run(output)
    except Exception as error:
        manifest.update(status='failed',failure=dict(type=type(error).__name__,message=str(error)));write_json(output/'run_manifest.json',manifest);raise
    return manifest


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--project-root',type=Path,default=Path.cwd())
    p.add_argument('--settings',type=Path,default=Path('config/coordinated_reports_2026-10-06.json'))
    p.add_argument('--output',type=Path);p.add_argument('--verify-contract',type=Path);a=p.parse_args()
    if a.verify_contract:
        verified=verify_run(a.verify_contract);verify_bindings(a.project_root,json.loads((a.verify_contract/'evidence_contract.json').read_text()));print(json.dumps(verified));return
    if a.output is None:p.error('--output or --verify-contract required')
    m=run_contract(a.project_root,a.settings,a.output);print(json.dumps(dict(run_id=m['run_id'],counts=m['counts']),indent=2))


if __name__=='__main__':main()
