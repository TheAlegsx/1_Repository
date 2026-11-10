
"""Build the iShares/New York Fed/Amundi assessment reader from the source exports."""
from datetime import date
from pathlib import Path
import json
import sys

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfReader
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import PageBreak, Paragraph

from factor_portfolio import research_reader_pdf as pdf
from factor_portfolio.config import SwissquoteStandardFeeSchedule
from factor_portfolio.data import DEFAULT_PRODUCTS, build_canonical_dataset
from factor_portfolio.historical import metrics, simulate
from factor_portfolio.inflows import simulate as simulate_inflows
from factor_portfolio.market_data import read_amundi_nav
from factor_portfolio.paired_robustness import run_account, stationary_draws
from factor_portfolio.rates import build_funding_dataset
from factor_portfolio.security_io import require_runtime

project, out = (Path(x).resolve() for x in sys.argv[1:3])
raw = project / 'Inputs/market_data'
src = project / 'Code/src/factor_portfolio'
evidence = out / 'Evidence'
figures = evidence / 'Figures'
out.mkdir(parents=True, exist_ok=False)
figures.mkdir(parents=True)
runtime = require_runtime()
config_path = project / 'Code/config/backtest_absolute_decoupled_2026-10-05.json'
c = json.loads(config_path.read_text())
period = c['periods']['full']
start, end = date.fromisoformat(period['start']), date.fromisoformat(period['end'])
cutoff = date(2026, 8, 31)
capital = c['initial_equity_usd']
sleeves = list(c['target_weights'])
fee = SwissquoteStandardFeeSchedule(**c['fee_schedule'])
amundi_name = 'NAV History_Amundi MSCI World (2x) Leveraged UCITS ETF Acc_FR0014010HV4_30_09_2025.xlsx'
input_paths = [raw/'ishares'/p.filename for p in DEFAULT_PRODUCTS] + [
    raw/'ishares/source_manifest.json',
    raw/'rates/new_york_fed/Data Release.xlsx',
    raw/'rates/new_york_fed/sofr_official_2018-04-02_2026-08-31.json',
    raw/'rates/new_york_fed/source_manifest.json',
    raw/'amundi'/amundi_name,
    raw/'dimensional/IE00B2PC0153_Morningstar_Finanzfluss_2026-11-10.json',
]

def digest(p):
    with p.open('rb') as stream:
        from hashlib import file_digest
        return file_digest(stream,'sha256').hexdigest()

input_hashes = {p.relative_to(raw).as_posix():digest(p) for p in input_paths}
assert input_hashes[f'amundi/{amundi_name}']=='22f0780124d0ca4609c9f677a4920d03890b3fe5ccfe94a611c11b26bb39ae95'
dimensional_path = input_paths[-1]
assert input_hashes[dimensional_path.relative_to(raw).as_posix()] == '26ce9209a97e69a2578581652e8044bedf3c7dc091c6f38decdcb6fbd0bdd5fe'
nav_all = build_canonical_dataset(raw/'ishares',cutoff=cutoff).nav_usd.round(6)
nav = nav_all.loc[str(start):str(end)]
assert nav.index[0].date()==start and nav.index[-1].date()==end and len(nav)==3027
funding = build_funding_dataset(raw/'rates/new_york_fed',start=start,cutoff=cutoff,
                                broker_spread=c['borrowing_margin_annual'])
ref = funding.daily_borrow_rates.reference_rate_annual.round(8)

def returns(levels):
    values=levels.pct_change(fill_method=None)
    values.iloc[0]=0.
    return values

def account(ret, lev, *, policy='absolute_decoupled', margin=None, sleeve=None, band=None, single=None, weights=None):
    if single is None and policy=='no_sleeve':
        single='core'
    cols=[single] if single else sleeves
    if single:
        weights = [1.]
    elif weights is None:
        weights = list(c['target_weights'].values())
    ret=ret.loc[:,cols].copy()
    ret.iloc[0]=0.
    result=simulate(ret,ref,weights,leverage=lev,policy=policy,
                    margin=c['borrowing_margin_annual'] if margin is None else margin,
                    sleeve_band=c['sleeve_band'] if sleeve is None else sleeve,
                    leverage_band=c['leverage_band'] if band is None else band,
                    initial_equity_usd=capital,fee_schedule=fee)
    assert result.status=='complete' and result.history.index.equals(ret.index)
    assert np.allclose(result.history.equity_usd,
                       result.history.gross_assets_usd-result.history.debt_usd,rtol=1e-12,atol=1e-7)
    return result

def cagr(run):
    values=run.history.equity_usd
    years=(values.index[-1]-values.index[0]).days/c['measurement']['cagr_calendar_year_days']
    return float((values.iloc[-1]/capital)**(1/years)-1)

ret=returns(nav)
runs={(k,l):account(ret,l,policy=k) for k in ('absolute_decoupled','no_sleeve','hybrid20') for l in (1.,1.25)}
market=runs['no_sleeve',1.]
performance={}
for (k,l),run in runs.items():
    m=metrics(run,ref,market,[1.] if k=='no_sleeve' else list(c['target_weights'].values()))
    assert np.isclose(m['cagr'],cagr(run),rtol=1e-13)
    performance[f'{k}_{l:.2f}']={key:m[key] for key in
        ('cagr','annualised_volatility','maximum_drawdown','sharpe_ratio','ending_equity_usd')}

quality_weights = {'core': .60, 'momentum': .10, 'quality': .20, 'value': .10}
quality_results = {}
for policy in ('hybrid20', 'absolute_decoupled'):
    weights = [quality_weights[sleeve] for sleeve in sleeves]
    comparison = metrics(account(ret, 1., policy=policy, weights=weights), ref, market, weights)
    baseline_result = performance[f'{policy}_1.00']
    quality_results[policy] = {
        'baseline_cagr': baseline_result['cagr'],
        'comparison_cagr': comparison['cagr'],
        'cagr_difference_pp': 100 * (comparison['cagr'] - baseline_result['cagr']),
        'baseline_maximum_drawdown': baseline_result['maximum_drawdown'],
        'comparison_maximum_drawdown': comparison['maximum_drawdown'],
    }

capped_quality = quality_results['hybrid20']
capped_drawdown_change_pp = 100 * (
    capped_quality['comparison_maximum_drawdown'] - capped_quality['baseline_maximum_drawdown']
)

aum_config = project / 'Code/config/steady_acquisition_video.json'
assumptions = json.loads(aum_config.read_text())
ticket = assumptions['ticket_usd']
first_year_months = assumptions['first_year_subscription_months']
first_year_clients, *later_clients = assumptions['annual_new_client_equivalents']
subscriptions = [
    first_year_clients * ticket / len(first_year_months) if month in first_year_months else 0.
    for month in range(1, 13)
]
subscriptions.extend(clients * ticket / 12 for clients in later_clients for _ in range(12))
monthly_return = (1 + assumptions['annual_return_before_fund_fee']) ** (1 / 12) - 1
monthly_redemption = 1 - (1 - assumptions['annual_external_unit_redemption']) ** (1 / 12)
annual_fund_fee = assumptions['video_annual_fund_fee']
aum_history = simulate_inflows(
    initial_aum=assumptions['initial_owner_capital_usd'], initial_nav=100,
    annual_fee=annual_fund_fee, monthly_returns=[monthly_return] * len(subscriptions),
    subscriptions=subscriptions, redemption_fraction=monthly_redemption,
)
aum_last = aum_history[-1]
aum_result = {
    'annual_fund_fee': annual_fund_fee, 'closing_aum_usd': aum_last['closing_net_aum_usd'],
    'owner_equity_usd': aum_last['start_cohort_equity_usd'],
    'external_equity_usd': aum_last['new_cohort_equity_usd'],
}

factor=runs['absolute_decoupled',1.25].history.equity_usd
core=runs['no_sleeve',1.25].history.equity_usd
relative=100*(factor/core-1)
checkpoint_dates=[relative.loc[:f'{y}-12-31'].index[-1] for y in range(2022,2026)]+[relative.index[-1]]
checkpoints={str(d.date()):float(relative.loc[d]) for d in checkpoint_dates}
baseline={'margin_bps':300,'fund_fee_bps':0.,'leverage_band':.10,'sleeve_band':.05}
cases=[('baseline',0,{})]+[(f'start_{n}',n,{}) for n in range(1,6)]+[
    (f'{key}_{v}',0,{key:v}) for key,values in
    [('margin_bps',(250,350)),('fund_fee_bps',(2.5,5)),('leverage_band',(.09,.11)),('sleeve_band',(.045,.055))]
    for v in values
]
assert len(cases)==14 and np.isclose(c['borrowing_margin_annual'],.03)
pair_rows=[]
for endpoint in checkpoint_dates[1:]:
    for label,offset,changes in cases:
        case=baseline | changes
        subset=ret.loc[ret.index[offset]:endpoint].copy()
        subset.iloc[0]=0.
        if case['fund_fee_bps']:
            f,_=run_account(subset,ref,c,case,'factor')
            b,_=run_account(subset,ref,c,case,'core')
        else:
            args=dict(margin=case['margin_bps']/10000.,sleeve=case['sleeve_band'],band=case['leverage_band'])
            f=account(subset,1.25,**args)
            b=account(subset,1.25,policy='no_sleeve',**args)
        pair_rows.append(dict(endpoint=str(endpoint.date()),case=label,start=str(subset.index[0].date()),
                              **case,factor_cagr=cagr(f),core_cagr=cagr(b),gap_pp=100*(cagr(f)-cagr(b))))
pairs=pd.DataFrame(pair_rows)
pairs.to_csv(evidence/'paired_cases.csv',index=False,float_format='%.12f')
summaries=[]
for endpoint,g in pairs.groupby('endpoint',sort=True):
    gap=g.gap_pp
    summaries.append(dict(endpoint=endpoint,baseline_pp=float(g.loc[g.case.eq('baseline'),'gap_pp'].iloc[0]),
        median_pp=float(gap.median()),minimum_pp=float(gap.min()),maximum_pp=float(gap.max()),
        positive=int(gap.gt(0).sum()),total=len(gap)))

equities=np.column_stack([factor,core])
entry=equities[0]/capital
logs=np.log(equities[1:]/equities[:-1])
years=(end-start).days/c['measurement']['cagr_calendar_year_days']
original_order=np.expm1((np.log(entry)+logs.sum(axis=0))/years)
assert np.allclose(original_order,[performance['absolute_decoupled_1.25']['cagr'],
                                  performance['no_sleeve_1.25']['cagr']],rtol=0,atol=1e-12)
boot=[]
for length,seed in [(20,2026100920),(60,2026100960)]:
    samples=stationary_draws(logs,entry,years,length,5000,seed)
    low,high=np.quantile(100*(samples[:,0]-samples[:,1]),[.025,.975])
    boot.append(dict(block=length,draws=5000,seed=seed,observed_pp=float(100*np.diff(original_order)[0]*-1),
                     low_pp=float(low),high_pp=float(high),includes_zero=bool(low<=0<=high)))
assert np.isclose(boot[0]['observed_pp'],summaries[-1]['baseline_pp'],rtol=0,atol=1e-10)

am=read_amundi_nav(raw/'amundi'/amundi_name,cutoff=cutoff).nav_usd
overlap=nav_all.index.intersection(am.index)
assert len(overlap)==232 and overlap[0].date()==date(2025,9,30) and overlap[-1].date()==cutoff
am_factor=account(returns(nav_all.loc[overlap[0]:overlap[-1]]),2.).history.equity_usd.loc[overlap]
amundi={}
for key,v in [('factor_2x',am_factor),('amundi_2x',am.loc[overlap])]:
    norm=v/v.iloc[0]
    rr=norm.pct_change(fill_method=None).iloc[1:]
    amundi[key]=dict(cumulative_return=float(norm.iloc[-1]-1),
                     maximum_drawdown=float((norm/norm.cummax()-1).min()),
                     annualised_volatility=float(rr.std(ddof=1)*np.sqrt(252)))
later=ret.loc[c['periods']['confirmation']['start']:]
margins={str(bp):{'full_cagr':cagr(account(ret,1.25,margin=bp/10000.)),
                 'later_cagr':cagr(account(later,1.25,margin=bp/10000.))}
         for bp in (0,300,500,1000)}
assert np.isclose(margins['300']['full_cagr'],performance['absolute_decoupled_1.25']['cagr'],rtol=0,atol=1e-13)

# Dimensional is a separate product comparison on the matched NAV calendar.
dimensional_data=json.loads(dimensional_path.read_bytes())
assert dimensional_data['priceSeriesId']==42858
dimensional_levels=pd.DataFrame(dimensional_data['navs'])
assert len(dimensional_levels)==2931
dimensional_levels=dimensional_levels.assign(date=pd.to_datetime(dimensional_levels.date,format='%Y-%m-%d')).set_index('date').value.sort_index()
assert dimensional_levels.index.is_unique and np.isfinite(dimensional_levels).all() and dimensional_levels.gt(0).all()
matched=nav.join(dimensional_levels.rename('dimensional'),how='inner')
assert len(matched)==2929 and matched.index[0].date()==start and matched.index[-1].date()==end
dimensional_returns=returns(matched)
matched_core=account(dimensional_returns,1.,policy='no_sleeve')
dimensional_metrics={}
for label,run,weights in (
    ('portfolio',account(dimensional_returns,1.25),list(c['target_weights'].values())),
    ('dimensional',account(dimensional_returns,1.25,policy='no_sleeve',single='dimensional'),[1.]),
):
    computed=metrics(run,ref,matched_core,weights)
    dimensional_metrics[label]={key:computed[key] for key in
        ('cagr','annualised_volatility','maximum_drawdown','sharpe_ratio','ending_equity_usd')}
    dimensional_metrics[label]['post_entry_rebalances']=[
        str(d.date()) for d in run.events.date.iloc[1:]
    ]
assert np.isclose(dimensional_metrics['portfolio']['cagr'],.1324364961,rtol=0,atol=1e-10)
assert np.isclose(dimensional_metrics['dimensional']['cagr'],.1131744726,rtol=0,atol=1e-10)

def drawdown(v):
    return 100*(v/v.cummax().clip(lower=capital)-1)

chart=pd.DataFrame({'portfolio_equity_usd':factor,'core_equity_usd':core,'relative_wealth_pct':relative,
                    'portfolio_drawdown_pct':drawdown(factor),'core_drawdown_pct':drawdown(core)})
chart.to_csv(evidence/'chart_series.csv',float_format='%.12f')
results={'scope':'Portfolio backtest, Amundi product comparison and private Dimensional comparison.',
         'runtime':runtime,'numpy':np.__version__,'pandas':pd.__version__,
         'code_sha256':{f:digest(src/f) for f in ('data.py','rates.py','historical.py','config.py',
                         'benchmark.py','market_data.py','paired_robustness.py','coupled_inflow_accounting.py','research_reader_pdf.py','security_io.py','inflows.py')},
         'baseline_config_sha256':digest(config_path),'inputs_relative_to_market_data_sha256':input_hashes,
         'calendar':{'start':str(start),'end':str(end),'nav_dates':len(nav),'intervals':len(nav)-1},
         'performance':performance,'relative_wealth_pct':checkpoints,'paired_summary':summaries,'bootstrap':boot,
         'amundi_window':{'start':str(overlap[0].date()),'end':str(overlap[-1].date()),'nav_dates':len(overlap)},
         'amundi':amundi,'margin_sensitivity':margins,
         'dimensional_comparison':{'source':'Morningstar via Finanzfluss','isin':'IE00B2PC0153','currency':'USD',
            'retrieved':'2026-11-10','price_series_id':42858,'target_leverage':1.25,
            'source_url':'https://hippoverse.finanzfluss.de/api/v1/funds/IE00B2PC0153/prices?startDate=2014-10-03&endDate=2026-08-28&includeNav=true',
            'common_nav_dates':len(matched),'start':str(start),'end':str(end),
            'metrics':dimensional_metrics},
         'video_supplement': {
             'quality_weight_test': {
                 'target_leverage': 1., 'nav_dates': len(nav),
                 'baseline_weights': c['target_weights'], 'comparison_weights': quality_weights,
                 'rules': quality_results,
             },
             'steady_acquisition': {
                 'config_sha256': digest(aum_config), 'assumptions': assumptions,
                 'months': len(subscriptions), 'gross_subscriptions_usd': round(sum(subscriptions), 2),
                 'scenarios': {'video': aum_result},
             },
         }}
(evidence/'results.json').write_text(json.dumps(results,indent=2,allow_nan=False)+'\n')

fonts=Path('/System/Library/Fonts/Supplemental')
blue='#1e4d78'
grey='#555555'
font=ImageFont.truetype(str(fonts/'Arial.ttf'),24)
small=ImageFont.truetype(str(fonts/'Arial.ttf'),21)
bold=ImageFont.truetype(str(fonts/'Arial Bold.ttf'),23)

def plot_area(draw, box, data, bounds, ticks, label, *, x_labels):
    left,top,right,bottom=box
    low,high=bounds
    x=(chart.index-chart.index[0]).days.to_numpy()
    def tx(n): return left+n*(right-left)/x[-1]
    def ty(v): return bottom-(v-low)*(bottom-top)/(high-low)
    draw.text((left,top-37),label,font=bold,fill='#293844')
    for v in ticks:
        y=ty(v)
        draw.line((left,y,right,y),fill='#b6c0c9' if v==0 else '#e3e9ee',width=2)
        draw.text((left-12,y),f'{v:g}',anchor='rm',font=small,fill=grey)
    draw.line((left,top,left,bottom,right,bottom),fill='#8d99a2',width=2)
    if x_labels:
        for y in (2015,2017,2019,2021,2023,2025):
            point=tx((pd.Timestamp(y,1,1)-chart.index[0]).days)
            draw.text((point,bottom+16),str(y),font=small,anchor='mt',fill=grey)
    for v,color in data:
        draw.line(list(zip(map(tx,x),map(ty,v))),fill=color,width=3)

def make_chart(path, *, drawdowns):
    size=(1440,610 if drawdowns else 875)
    image=Image.new('RGB',size,'white')
    draw=ImageDraw.Draw(image)
    for x,colour,label in [(106,blue,'Factor portfolio (1.25x)'),(440,grey,'MSCI World Core (1.25x)')]:
        draw.line((x,45,x+36,45),fill=colour,width=4)
        draw.text((x+45,45),label,font=font,anchor='lm',fill='#293844')
    if drawdowns:
        plot_area(draw,(96,120,1412,537),[(chart.portfolio_drawdown_pct,blue),(chart.core_drawdown_pct,grey)],
                  (-45,1),[-40,-30,-20,-10,0],'Drawdown (%)',x_labels=True)
    else:
        plot_area(draw,(96,120,1412,486),[(factor/1e6,blue),(core/1e6,grey)],
                  (3,33),[5,10,15,20,25,30],'Investor equity (USD million)',x_labels=False)
        plot_area(draw,(96,565,1412,798),[(relative,blue)],(-8,9),[-5,0,5],'Portfolio relative to Core (%)',x_labels=True)
    image.save(path,optimize=True)

make_chart(figures/'equity.png',drawdowns=False)
make_chart(figures/'drawdown.png',drawdowns=True)

def table(label, headers, rows):
    def row(values): return '| '+' | '.join(map(str,values))+' |'
    return '**'+label+'**\n\n'+'\n'.join([row(headers),row(['---']*len(headers)),*(row(r) for r in rows)])

def pct(x): return f'{x:.2%}'
def pp(x): return f'{x:+.2f}'
def market_rows(l):
    return [[label,pct(m['cagr']),pct(m['annualised_volatility']),pct(m['maximum_drawdown']),
             f"{m['sharpe_ratio']:.3f}",f"{m['ending_equity_usd']/1e6:.2f}"]
            for label,key in [('Factor portfolio','absolute_decoupled'),('MSCI World Core','no_sleeve')]
            for m in [performance[f'{key}_{l:.2f}']]]
m1=performance['absolute_decoupled_1.25']
m2=performance['no_sleeve_1.00']
spread=100*(m1['cagr']-performance['no_sleeve_1.25']['cagr'])
caps=[[label,f'{lev:g}x',pct(m['cagr']),pct(m['annualised_volatility']),pct(m['maximum_drawdown'])]
      for lev in (1.,1.25) for key,label in [('absolute_decoupled','Absolute / separate leverage'),('hybrid20','Capped-relative comparison')]
      for m in [performance[f'{key}_{lev:.2f}']]]
perf_headers=['Investment','CAGR','Volatility','Drawdown','Sharpe','Ending equity, USD m']
quality_core_returns = nav[['core', 'quality']].pct_change(fill_method=None).dropna()
quality_core_correlation = quality_core_returns['core'].corr(quality_core_returns['quality'])
assert len(quality_core_returns) == len(nav) - 1
pages=[
    [
        '# MSCI World Factor Strategy',
        'Portfolio backtest · 3 October 2014–28 August 2026 · USD',
        '## Portfolio rules and benchmark',
        table('Table 1. Target allocation',['Sleeve','Target','iShares ETF ISIN'],
              [[s.title(),f"{c['target_weights'][s]:.0%}",next(p.isin for p in DEFAULT_PRODUCTS if p.sleeve==s)] for s in sleeves]),
        'Weight bands are ±5 percentage points around the targets. A strict breach signals a reset at the next common NAV. The leverage target is 1.25x, with a separate 1.15x–1.35x band that triggers rebalancing at the next common NAV. Actual leverage can move outside the band. The simulation does not model lender margin calls. A weight-only signal preserves debt, a leverage-only signal scales holdings proportionally, and a joint signal resets both.',
        'Committed equity is USD 7.00 million. At 1.25x the initial gross exposure and debt before trading costs are USD 8.75 million and USD 1.75 million. The benchmark is the iShares Core MSCI World UCITS ETF, evaluated with and without modelled borrowing.',
        '## Data and cost assumptions',
        table('Table 2. Investment cost assumptions',['Parameter','Selected value'],
              [['Financing markup','300 bp over the reference rate'],['Interest accrual','ACT/360'],
               ['Platform fee per traded leg','USD 0.85'],['Investor-side duty','0.15%'],
               ['One-way spread','5 bp'],['USD per CHF','1.2368']]),
        'The common calendar has 3,027 NAV observations and 3,026 return intervals. It uses four iShares USD accumulating NAV histories (BlackRock, 2026a, 2026b, 2026c, 2026d). Financing uses the New York Fed indicative reference series followed by official SOFR (Federal Reserve Bank of New York, 2018, 2026b). Interest is capitalised at NAV dates. A stepped CHF broker commission is included per traded leg.',
        'The model takes the USD 0.85 platform fee and stepped CHF commission schedule from Swissquote Bank Ltd. (n.d., section 1.1). It models investor-side transfer duty at 0.15%, half the 0.30% total rate for foreign securities (Eidgenössische Steuerverwaltung, 2025, paras. 2 and 10). The fixed conversion for CHF commissions is 1.1596 USD/EUR divided by 0.9376 CHF/EUR, using the ECB rates for 31 August 2026 (European Commission, 2026, p. 1).',
        'The model applies a fixed 300 bp markup (see p. 6) and a fixed 5 bp one-way spread per purchase or sale. The baseline includes modelled trading and financing costs and excludes custody fees, external subscriptions, operating costs and additional fund fees. Product expenses are embedded in the NAVs.'
    ],
    [
        '## Compounded investment performance',
        'CAGR measures growth from committed opening capital over elapsed calendar years, including opening trading costs. '
        f'The portfolio-minus-Core CAGR gap at the matched 1.25x target is {pp(spread)} percentage points.',
        table('Table 3. Unlevered comparison',perf_headers,market_rows(1.)),
        table('Table 4. Matched 1.25x leverage target',perf_headers,market_rows(1.25)),
        '![Portfolio and Core equity curves](Evidence/Figures/equity.png)',
        '*Figure 1. Investor equity at the matched 1.25x target. Relative wealth is 100 × (portfolio equity / Core equity − 1).*',
    ],
    [
        '## Drawdown and relative wealth',
        'Drawdown uses the running equity high-water mark, with committed opening capital as the initial floor. Volatility uses 252-observation annualisation. The Sharpe ratio uses excess returns over the reference rate.',
        table('Table 5. Factor portfolio at 1.25x versus unlevered Core (1x)',['Investment','Target','CAGR','Volatility','Sharpe'],
              [[label,target,pct(m['cagr']),pct(m['annualised_volatility']),f"{m['sharpe_ratio']:.3f}"]
               for label,target,m in [('Factor portfolio','1.25x',m1),('MSCI World Core','1x',m2)]]),
        '### Drawdowns at a matched 1.25x target',
        '![Portfolio and Core drawdowns](Evidence/Figures/drawdown.png)',
        '*Figure 2. Drawdowns from committed-capital high-water marks. Both investments target 1.25x.*',
        table('Table 6. Relative wealth at selected endpoints',['Last common NAV','Portfolio relative to Core, 1.25x'],
              [[day,f'{value:+.2f}%'] for day,value in checkpoints.items()]),
        'The checkpoints are read from the continuing full-period accounts.',
        '### Quality and Core return correlation',
        f'The Pearson correlation between iShares Core and Quality returns is {quality_core_correlation:.6f} '
        f'({quality_core_correlation:.3f} rounded). The calculation uses the {len(nav):,} common iShares NAV dates '
        'from 3 October 2014 to 28 August 2026 (BlackRock, 2026a, 2026c). For each ETF, the return is the current USD NAV '
        f'divided by the previous common-date NAV minus one. The first date provides opening NAVs, leaving '
        f'{len(quality_core_returns):,} paired returns for the correlation.',
    ],
    [
        '## Paired specifications and bootstrap intervals',
        'The 14 cases include the baseline and one-at-a-time changes to start date, financing markup, fund fee, leverage band and sleeve band. The five later starts advance one to five iShares NAV observations. Earlier starts fall outside the sample. Both accounts target 1.25x. The baseline charges no additional fund fee. The two fee variants charge both accounts 2.5 or 5 bp per year.',
        table('Table 7. Portfolio minus Core CAGR across paired specifications',
              ['Endpoint','Baseline pp','Median pp','Minimum pp','Maximum pp','Positive'],
              [[x['endpoint'],pp(x['baseline_pp']),pp(x['median_pp']),pp(x['minimum_pp']),pp(x['maximum_pp']),
                f"{x['positive']}/{x['total']}"] for x in summaries]),
        f'The baseline gap was {pp(summaries[1]["baseline_pp"])} percentage points at the 2024 year-end and '
        f'{pp(summaries[-1]["baseline_pp"])} at the August 2026 endpoint. Positive gaps rose from 0 of 14 cases at the '
        '2023 and 2024 year-ends to 5 of 14 at the 2025 year-end and 14 of 14 in August 2026.',
        table('Table 8. Conditional stationary bootstrap of the 1.25x CAGR gap',
              ['Mean block','Draws','Gap pp','95% low pp','95% high pp'],
              [[x['block'],f"{x['draws']:,}",pp(x['observed_pp']),pp(x['low_pp']),pp(x['high_pp'])] for x in boot]),
        'The stationary bootstrap (Politis & Romano, 1994, pp. 1303–1304) resamples paired realised account returns, with opening costs '
        'counted once per draw. For both mean block lengths, the central 95% of resampled CAGR gaps spans negative and '
        'positive values and includes zero. The resampled returns already reflect the trading rules applied to the historical paths.',
        '## Weight-band comparison',
        'The capped-relative rule uses the smaller of 5 percentage points and 20% of each sleeve target.',
        table('Table 9. Absolute and capped-relative weight bands',['Rule','Target','CAGR','Volatility','Drawdown'],caps),
        'Both band rules were evaluated retrospectively. The wider bands delivered higher CAGR in this sample, while the narrower bands had slightly lower volatility at the 1.25x target.',
    ],
    [
        '## Product comparisons',
        '### Dimensional at the matched 1.25x leverage target',
        'The comparison uses the daily USD NAV of the Dimensional Global Core Equity Fund USD Accumulation share class (IE00B2PC0153), supplied through Finanzfluss (Morningstar, n.d.). The common iShares and Dimensional sample contains 2,929 NAV dates from 3 October 2014 to 28 August 2026.',
        table('Table 10. Portfolio and Dimensional at a 1.25x target',
              ['Investment','CAGR','Volatility','Drawdown'],
              [[label,pct(m['cagr']),pct(m['annualised_volatility']),pct(m['maximum_drawdown'])]
               for label,key in [('Factor portfolio','portfolio'),('Dimensional','dimensional')] for m in [dimensional_metrics[key]]]),
        'Both accounts use a 1.25x target with the same leverage adjustment band and modelled trading and financing costs. The Dimensional account holds one fund. The main portfolio and Core comparison uses its own iShares-only calendar.',
        '### Amundi 2x product comparison',
        'The comparison uses 232 dates common to the four iShares NAVs and the official USD NAV of Amundi MSCI World (2x) Leveraged UCITS ETF Acc (FR0014010HV4), from 30 September 2025 to 31 August 2026 (Amundi Asset Management, 2026a). The NAV data are in the supplied workbook, sheet “Nav History”, column “Official NAV”.',
        table('Table 11. Portfolio and Amundi over the common NAV window',
              ['Investment','Cumulative return','Volatility','Drawdown'],
              [[label,pct(m['cumulative_return']),pct(m['annualised_volatility']),pct(m['maximum_drawdown'])]
               for label,key in [('Factor portfolio, 2x target','factor_2x'),('Amundi 2x ETF NAV','amundi_2x')] for m in [amundi[key]]]),
        'The portfolio is simulated on the full iShares calendar within the comparison window. Its equity is sampled on common dates. The portfolio uses band-managed leverage. The Amundi series uses the ETF’s reported NAV. Both paths are normalised to the first common post-entry observation. This normalisation excludes the modelled opening charge from the displayed cumulative return.',
        'The Amundi ETF tracks an index with daily 2x leverage, and its NAV reflects borrowing costs and product expenses (Amundi Asset Management, 2026b, pp. 1–3). Investor trading charges on Amundi are outside the series.'
    ],
    [
        '## Financing markup scenarios',
        'The project brief records a 6.65% USD borrowing rate from a private Swissquote account snapshot dated 26 September 2026. The New York Fed 30-day SOFR average was 3.705% on 25 September (Federal Reserve Bank of New York, 2026a, 25 September observation). The 294.5 bp difference was rounded to a fixed 300 bp markup. The account category and historical broker rates remain unverified.',
        table('Table 12. Portfolio CAGR by financing markup at a 1.25x target',['Markup above reference, bp','Full-period CAGR','Later-period CAGR'],
              [[bp,pct(m['full_cagr']),pct(m['later_cagr'])] for bp,m in margins.items()]),
        'The full period starts on 3 October 2014. The later period restarts with committed opening equity on 4 January 2022. Both end on 28 August 2026. Each row is a separate simulation. The reference rate applies in every scenario, including at a zero markup.',
        '## Sources and reproducibility',
        'The market data, cost and method references are on the final page. The iShares and New York Fed exports were captured on 27 and 28 September 2026, respectively. The Amundi workbook identifies its update as 25 September 2026. The ZIP contains the workbook used in the comparison under Inputs/market_data/amundi. The original workbook download URL and retrieval date are unverified.',
        'Interest accrues for calendar days from the prior NAV date up to but excluding the current NAV date, using the latest available reference rate. The ACT/360 day count and rate carry-forward follow the conventions described for the SOFR Averages and Index (Federal Reserve Bank of New York, n.d., SOFR Averages and Index section).',
        'The accompanying calculation files record source checksums, the computed results, the cases and the plotted series.',
    ],
    [
        '## Appendix. Supplementary calculations for the video',
        '### 1. Unlevered Quality allocation test',
        'The test uses the 3,027 common iShares NAVs from 3 October 2014 to 28 August 2026, with the same USD 7 million starting equity and trading-cost assumptions as the main backtest. There is no borrowing. In Core / Momentum / Quality / Value order, the target weights change from 60% / 15% / 10% / 15% to 60% / 10% / 20% / 10%.',
        'Within each comparison both allocations follow the same rule. The earlier rule caps each band at the smaller of 5 percentage points and 20% of the sleeve target. The final rule uses absolute 5-percentage-point bands. A strict breach signals a reset at the next common valuation.',
        table('Table 13. Quality allocation under each rebalancing rule',
              ['Rule', 'CAGR at 10%', 'CAGR at 20%', 'CAGR change, pp', 'Max. drawdown at 10%', 'Max. drawdown at 20%'],
              [[label, pct(m['baseline_cagr']), pct(m['comparison_cagr']), pp(m['cagr_difference_pp']),
                pct(m['baseline_maximum_drawdown']), pct(m['comparison_maximum_drawdown'])]
               for key, label in [('hybrid20', 'Capped-relative'), ('absolute_decoupled', 'Absolute')]
               for m in [quality_results[key]]]),
        'The roughly 0.1-percentage-point reduction described in the video matches the earlier capped-relative comparison. Using the unrounded values, maximum drawdown is '
        f'{capped_drawdown_change_pp:.5f} percentage points shallower under that rule. '
        'The comparison includes the corresponding changes to Momentum and Value.',
        '### 2. Hypothetical fund assets after ten years',
        'The steady-acquisition model starts with USD 7 million in founder capital, assumes a fixed 6% annual return before the fund fee and uses USD 250,000 per new client equivalent. Scheduled new client equivalents rise from 2 in year 1 to 20 in year 10 in steps of 2. Gross subscriptions total USD 27.5 million. Year-one subscriptions start in month 7. The model assumes 10% annual attrition of external units.',
        'The 0.30% annual fund fee applies to this projection. The model converts return and attrition to monthly rates. Each month it applies investment return and charges one twelfth of the annual fund fee on opening assets, then processes redemptions and subscriptions. Year-ten fund assets are the sum of the closing founder and external holdings.',
        table('Table 14. Closing fund assets after 120 months, USD million',
              ['Annual fund fee', 'Founder equity', 'External equity', 'Total fund assets'],
              [[pct(aum_result['annual_fund_fee']), f"{aum_result['owner_equity_usd']/1e6:.2f}",
                f"{aum_result['external_equity_usd']/1e6:.2f}", f"{aum_result['closing_aum_usd']/1e6:.2f}"]]),
        'Under these assumptions, we expect about USD 36 million in fund assets after ten years.',
        'Reproduction files: Evidence/results.json, section video_supplement, records full-precision results. Code/config/steady_acquisition_video.json records the model inputs. The package runner rebuilds both calculations.',
    ],
]
pdf.SOURCE=out
pdf.register_fonts(fonts)
report=out/'MSCI_World_Factor_Strategy_Backtest.pdf'
story=[]
audit=dict(tables=0,table_cells=0,table_values=[],images=[])
for page in pages:
    if story: story.append(PageBreak())
    pdf.convert('\n\n'.join(page),out,story,audit)
source_notes = (project / 'Evidence/Data_Sources.md').read_text(encoding='utf-8')
_, references_marker, remainder = source_notes.partition('## References\n\n')
reference_list, notes_marker, _ = remainder.partition('\n\n## Snapshot and file notes')
assert references_marker and notes_marker
references = reference_list.split('\n\n')
assert len(references) == 15
# Keep the provenance URLs in Data_Sources.md and show reader-facing references in the PDF.
for i, entry in enumerate(references):
    if entry.startswith('BlackRock. '):
        references[i] = entry.split(' [https://www.ishares.com/', 1)[0]
    elif entry.startswith('Morningstar. '):
        citation = entry.split(' Retrieved November 10, 2026, from ', 1)[0]
        references[i] = (
            citation + ' Snapshot dated November 10, 2026. '
            '[Finanzfluss fund page](https://www.finanzfluss.de/informer/fonds/ie00b2pc0153/).'
        )
reference_style = ParagraphStyle('DataReference', parent=pdf.STYLE, leading=16, spaceAfter=0,
                                 leftIndent=36, firstLineIndent=-36)
story.append(PageBreak())
pdf.convert('## References', out, story, audit)
story.extend(Paragraph(pdf.inline(entry), reference_style) for entry in references)
total_pages = len(pages) + 1
doc=pdf.ReadingDocument(report,'MSCI World Factor Strategy',total_pages=total_pages,report_date='10 November 2026')
doc.author=''
doc.subject='Portfolio backtest using issuer NAVs and New York Fed reference rates'
doc.invariant=True
doc.build(story)
reader=PdfReader(report)
assert len(reader.pages)==total_pages and audit['tables']==14 and len(audit['images'])==2, (len(reader.pages),audit['tables'])
texts=[' '.join(page.extract_text().split()) for page in reader.pages]
assert '3,027 NAV observations' in texts[0] and 'Table 9.' in texts[3] and '232 dates' in texts[4]
assert '11.32%' in texts[4] and '13.24%' in texts[4] and 'Table 10.' in texts[4]
assert f'{quality_core_correlation:.3f} rounded' in texts[2]
assert f'{len(quality_core_returns):,} paired returns' in texts[2]
assert f"{aum_result['closing_aum_usd']/1e6:.2f}" in texts[6]
assert all(pct(result['comparison_cagr']) in texts[6] for result in quality_results.values())
assert all(digest(p)==input_hashes[p.relative_to(raw).as_posix()] for p in input_paths)
for row,page in zip((market_rows(1.)+market_rows(1.25),caps,[[pct(m['cumulative_return'])] for m in amundi.values()]), (texts[1],texts[3],texts[4])):
    assert all(cell in page for record in row for cell in record if '%' in cell)
print(json.dumps({'calendar':results['calendar'],'performance':performance,'bootstrap':boot,'amundi':amundi},indent=2))

