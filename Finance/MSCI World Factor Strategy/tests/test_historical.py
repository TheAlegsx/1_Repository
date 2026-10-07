"""Economic invariants and timing checks for research-only policy extensions."""
import unittest
import numpy as np
import pandas as pd
from factor_portfolio.historical import simulate as research_simulate, metrics
SLEEVES=['core','momentum','quality','value']
WEIGHTS=np.array([.6,.15,.1,.15])
CAPITAL=7e6

def simulate(*args, **kwargs):
    kwargs.setdefault('initial_equity_usd', CAPITAL)
    return research_simulate(*args, **kwargs)

class ResearchTests(unittest.TestCase):
    def inputs(self,n=12):
        idx=pd.bdate_range('2020-01-02',periods=n)
        r=pd.DataFrame(0.,index=idx,columns=SLEEVES)
        ref=pd.Series(0.,index=pd.date_range(idx[0],idx[-1]))
        return r,ref
    def test_unlevered_buy_hold_has_only_initial_trade_and_exact_drift(self):
        r,rf=self.inputs();r.loc[r.index[2],'momentum']=.4
        run=simulate(r,rf,WEIGHTS,1.,'no_sleeve',fee_free=True)
        self.assertEqual(len(run.events),1)
        np.testing.assert_allclose(run.history.equity_usd.iloc[-1],CAPITAL*(1+.15*.4))
        self.assertAlmostEqual(run.history.weight_momentum.iloc[-1],.15*1.4/1.06)
    def test_band_signal_executes_next_observation(self):
        r,rf=self.inputs();r.loc[r.index[2],'value']=.4
        run=simulate(r,rf,WEIGHTS,1.,'hybrid20',fee_free=True)
        self.assertEqual(run.events.iloc[1].date,r.index[3])
        np.testing.assert_allclose(run.history.loc[r.index[3],[f'weight_{s}' for s in SLEEVES]].to_numpy(float),WEIGHTS)
    def test_relative_band_can_trade_before_absolute_band(self):
        r,rf=self.inputs();r.loc[r.index[2],'value']=.3
        relative=simulate(r,rf,WEIGHTS,1.,'hybrid20',fee_free=True)
        absolute=simulate(r,rf,WEIGHTS,1.,'absolute_decoupled',fee_free=True)
        self.assertGreater(len(relative.events),len(absolute.events))
    def test_leverage_adjustment_preserves_drifting_sleeve_mix(self):
        r,rf=self.inputs();r.loc[r.index[2]]= -.30;r.loc[r.index[2],'momentum']=-.1
        run=simulate(r,rf,WEIGHTS,1.25,'no_sleeve',fee_free=True)
        self.assertEqual(run.events.iloc[1].reason,'leverage')
        a=run.history.loc[r.index[2],[f'weight_{s}' for s in SLEEVES]].to_numpy(float)
        b=run.history.loc[r.index[3],[f'weight_{s}' for s in SLEEVES]].to_numpy(float)
        np.testing.assert_allclose(a,b);self.assertFalse(np.allclose(b,WEIGHTS))
    def test_passive_debt_finances_calendar_days_and_never_rebalances(self):
        r,rf=self.inputs();rf[:]=.036
        run=simulate(r,rf,WEIGHTS,1.25,'no_sleeve',passive=True,margin=0,fee_free=True)
        expected=CAPITAL*.25
        for a,b in zip(r.index[:-1],r.index[1:]):expected*=1+.036*(b-a).days/360
        self.assertAlmostEqual(run.history.debt_usd.iloc[-1],expected,places=6)
        self.assertEqual(len(run.events),1)
    def test_margin_call_priority_and_cure_costs(self):
        r,rf=self.inputs();r.loc[r.index[2]]= -.25
        run=simulate(r,rf,WEIGHTS,1.25,'no_sleeve',maintenance=.25,extra_liquidation_spread=.01)
        self.assertEqual(run.events.iloc[1].reason,'margin_call')
        self.assertEqual(run.events.iloc[1].date,r.index[3])
        self.assertGreater(run.events.iloc[1].fees_usd,0)
        self.assertAlmostEqual(run.history.leverage.iloc[3],1.25)
        self.assertLess(run.history.debt_usd.iloc[3],run.history.debt_usd.iloc[2])
    def test_gap_can_default_before_pending_call_cure(self):
        r,rf=self.inputs();r.loc[r.index[2]]= -.25;r.loc[r.index[3]]= -.85
        run=simulate(r,rf,WEIGHTS,1.25,'no_sleeve',maintenance=.25,fee_free=True)
        self.assertEqual(run.status,'insolvent')
    def test_periodic_signal_uses_monthend_then_next_observation(self):
        r,rf=self.inputs(80);r.iloc[1:,1]=.001
        run=simulate(r,rf,WEIGHTS,1.,'quarterly',fee_free=True)
        event=run.events.iloc[1].date
        self.assertEqual(event.month,4);self.assertEqual(r.index[r.index.get_loc(event)-1].month,3)
    def test_legacy_production_reconciliation(self):
        from factor_portfolio.engine import run_backtest
        from factor_portfolio.config import PortfolioConfig
        r,rf=self.inputs(100);rng=np.random.default_rng(42);r.iloc[1:]=rng.normal(0,.012,(99,4))
        config=PortfolioConfig(target_weights=dict(zip(SLEEVES,WEIGHTS)),initial_equity_usd=CAPITAL,sleeve_band=.02)
        a=simulate(r,rf,WEIGHTS,1.25,'legacy_absolute',sleeve_band=.02)
        b=run_backtest(r,rf+.03,config)
        np.testing.assert_allclose(a.history.equity_usd,b.history.equity_usd,rtol=2e-12,atol=2e-7)
    def test_identical_market_beta_one_alpha_zero(self):
        r,rf=self.inputs(100);r.iloc[1:,0]=np.sin(np.arange(99))*.01+.0003
        run=simulate(r[['core']],rf,[1.],1.,'no_sleeve',fee_free=True)
        m=metrics(run,rf,run)
        self.assertAlmostEqual(m['beta_vs_unlevered_core'],1)
        self.assertAlmostEqual(m['jensen_alpha'],0)

if __name__=='__main__':unittest.main()
