"""Fee and client-plan account reconciliation from existing sealed ledgers."""
from pathlib import Path
import hashlib
import json
import math
import pandas as pd


def summaries(source):
    source = Path(source)
    folder = source / 'inflow/evidence'
    files = {k: folder / name for k, name in {
        'headlines': 'historical_headline.csv', 'monthly': 'coupled_monthly.csv',
        'overlay': 'overlay_monthly.csv', 'events': 'coupled_events.csv',
        'daily': 'coupled_daily.csv'}.items()}
    frames = {k: pd.read_csv(p, float_precision='round_trip') for k, p in files.items()}
    config_file = source / 'inflow/config/inflow_acquisition.json'
    config = json.loads(config_file.read_text())
    baseline_file = source / 'backtest/config/backtest_absolute_decoupled_2026-10-05.json'
    baseline = json.loads(baseline_file.read_text())
    capital = float(baseline['initial_equity_usd'])
    ids = ['absolute_decoupled__control__no_flow_zero_added_fee',
           'absolute_decoupled__acquisition__no_flows',
           'absolute_decoupled__acquisition__steady']
    heads = {}
    pnls = {}
    errors = {}
    for rid in ids:
        chosen = frames['headlines'][frames['headlines'].run_id.eq(rid)]
        if len(chosen) != 1:
            raise ValueError('one exact retained historical account required')
        h = chosen.iloc[0]; heads[rid] = h
        m = frames['monthly'][frames['monthly'].run_id.eq(rid)]
        if len(m) != 120 or not m.month.is_unique or not m.owner_units.eq(capital / 100).all():
            raise ValueError('same 120-month owner cohort required')
        pnl = math.fsum(m.investment_price_pnl_usd); pnls[rid] = pnl
        expected = (capital + pnl - h.transaction_cost_usd - h.financing_cost_usd
                    - h.fund_fee_usd + h.gross_subscriptions_usd - h.redemptions_usd)
        errors[rid] = float(expected - h.closing_aum_usd)
        if abs(errors[rid]) > 1e-6:
            raise ValueError('historical account identity differs')
    a, b, c = [heads[k] for k in ids]
    if len({(h.start, h.end, h.observations) for h in heads.values()}) != 1:
        raise ValueError('fee bridge requires the same observation window')
    if any(h.gross_subscriptions_usd != 0 or h.redemptions_usd != 0 or h.external_equity_usd != 0
           or abs(h.owner_equity_usd-h.closing_aum_usd)>1e-6 for h in [a, b]):
        raise ValueError('no-client controls must contain only the original owner investment')
    if a.fund_fee_usd != 0:
        raise ValueError('no-fee control contains fund fees')
    overlay = frames['overlay'][frames['overlay'].run_id.eq(ids[1])].sort_values('month')
    if len(overlay) != 120:
        raise ValueError('complete matched no-client overlay required')
    o = overlay.iloc[-1]
    if str(o.event_date) != str(a.end):
        raise ValueError('overlay endpoint differs')
    years = (pd.Timestamp(a.end)-pd.Timestamp(a.start)).days / baseline['measurement']['cagr_calendar_year_days']
    owner_values = [float(a.owner_equity_usd), float(o.start_cohort_equity_usd),
                    float(b.owner_equity_usd), float(c.owner_equity_usd)]
    returns = [(x/capital)**(1/years)-1 for x in owner_values]

    def cell(value, display, artifact, field, selector=None, expression=None):
        return dict(value=value, display=display,
                    origins=[dict(artifact=str(artifact.relative_to(source)), field=field, selector=selector)],
                    expression=expression)

    labels = ['Investment control, no added fund fee', 'Overlay with fund fee, no portfolio feedback',
              'Executed fund with fee, no external clients', 'Executed fund with fee, steady acquisition']
    chain=[]
    for i, (label, value, rate) in enumerate(zip(labels, owner_values, returns)):
        path = files['overlay'] if i == 1 else files['headlines']
        selector = ids[1] if i == 1 else ids[[0,0,1,2][i]]
        chain.append([cell(label,label,path,'run_id',selector),
                      cell(value,f'{value/1e6:.3f}',path,'owner_equity_usd' if i!=1 else 'start_cohort_equity_usd',selector),
                      cell(rate,f'{100*rate:.2f}%',path,'owner return',selector,'(ending_owner_equity / initial_capital) ** (1 / elapsed_years) - 1')])
    components=[('Change in investment price P/L',pnls[ids[1]]-pnls[ids[0]],'investment_price_pnl_usd'),
                ('Financing-cost saving',float(a.financing_cost_usd-b.financing_cost_usd),'financing_cost_usd'),
                ('Additional trading costs',float(a.transaction_cost_usd-b.transaction_cost_usd),'transaction_cost_usd'),
                ('Added fund fees',-float(b.fund_fee_usd),'fund_fee_usd')]
    total=math.fsum(x[1] for x in components)
    if abs(total-(b.owner_equity_usd-a.owner_equity_usd))>1e-6:
        raise ValueError('signed wealth bridge does not reconcile')
    reconciliation=[[cell(label,label,files['monthly'] if field=='investment_price_pnl_usd' else files['headlines'],field,ids[:2]),
                     cell(value,f'{value:+,.0f}',files['monthly'] if field=='investment_price_pnl_usd' else files['headlines'],field,ids[:2],'fee no-client account minus no-fee control, with expense signs reversed')]
                    for label,value,field in components]
    reconciliation.append([cell('Total wealth difference','Total wealth difference',files['headlines'],'owner_equity_usd',ids[:2]),
                           cell(total,f'{total:+,.0f}',files['headlines'],'owner_equity_usd',ids[:2],'sum of signed account components')])
    events=frames['events']; rows=[]
    for label, reason, ordinal in [('Sleeve reset','sleeve',0),('First leverage adjustment','leverage',0),
                                  ('Additional leverage reduction','leverage',1)]:
        row=[cell(label,label,files['events'],'reason',ids[:2])]
        for rid in ids[:2]:
            matches=events[events.run_id.eq(rid)&events.reason.eq(reason)].sort_values('date')
            value=str(matches.iloc[ordinal].date) if len(matches)>ordinal else None
            row.append(cell(value,value or 'None',files['events'],'date',dict(run_id=rid,reason=reason,ordinal=ordinal)))
        rows.append(row)
    daily=frames['daily']; at={}
    for rid in ids[:2]:
        match=daily[daily.run_id.eq(rid)&daily.date.eq('2022-09-30')]
        if len(match)!=1:raise ValueError('one pre-intervention observation required')
        at[rid]=float(match.iloc[0].leverage)
    gaps=[100*(returns[2]-returns[1]),100*(returns[3]-returns[2]),100*(returns[3]-returns[1])]
    result={'fee_chain':dict(kind='table',headers=['Account / comparison','Ending founder equity, USD m','Unit return / year'],rows=chain),
            'wealth_bridge':dict(kind='table',headers=['Fee no-client account minus no-fee control','Effect on ending equity, USD'],rows=reconciliation),
            'fee_events':dict(kind='table',headers=['Post-entry intervention','No fund fee','5 bp fee, no clients'],rows=rows)}
    for key,value in [('no_client_gap',gaps[0]),('additional_plan_gap',gaps[1])]:
        result[key]=dict(kind='claim',**cell(value,f'{value:+.2f} pp',files['headlines'],'annual owner/unit return',ids,'successive matched account-return difference'))
    result['no_client_gap_share']=dict(kind='claim',**cell(gaps[0]/gaps[2],f'{100*gaps[0]/gaps[2]:.0f}%',files['headlines'],'return gap',ids,'no-client coupled-minus-overlay gap / steady coupled-minus-overlay gap'))
    result['threshold_control']=dict(kind='claim',**cell(at[ids[0]],f'{at[ids[0]]:.4f}x',files['daily'],'leverage',dict(run_id=ids[0],date='2022-09-30')))
    result['threshold_fee']=dict(kind='claim',**cell(at[ids[1]],f'{at[ids[1]]:.4f}x',files['daily'],'leverage',dict(run_id=ids[1],date='2022-09-30')))
    result['checks']=dict(account_identity_errors_usd=errors,wealth_bridge_error_usd=float(total-(b.owner_equity_usd-a.owner_equity_usd)),
                          window=[a.start,a.end],initial_owner_capital_usd=capital,annual_fund_fee=config['annual_fee'],
                          scope='Arithmetic account comparison, not an order-independent causal decomposition or a new simulation')
    result['source_files_sha256']={str(p.relative_to(source)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [*files.values(),config_file,baseline_file]}
    return result
