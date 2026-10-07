"""Financial contract tests for the separate scenario layer."""
import math
import unittest
from factor_portfolio.inflows import simulate


class FundFlows(unittest.TestCase):
    def run_path(self, **overrides):
        params=dict(initial_aum=1000,initial_nav=100,annual_fee=0,
                    monthly_returns=[0,0],subscriptions=[0,0])
        params.update(overrides)
        return simulate(**params)

    def test_flat_no_flow_preserves_capital(self):
        self.assertEqual(self.run_path()[-1]['closing_net_aum_usd'],1000)

    def test_end_month_subscription_does_not_earn_prior_return(self):
        rows=self.run_path(monthly_returns=[.1,.1],subscriptions=[1000,0])
        self.assertAlmostEqual(rows[0]['closing_net_aum_usd'],2100)
        self.assertAlmostEqual(rows[1]['closing_net_aum_usd'],2310)
        self.assertAlmostEqual(rows[1]['start_cohort_equity_usd'],1210)
        self.assertAlmostEqual(rows[1]['new_cohort_equity_usd'],1100)

    def test_nav_is_independent_of_flows(self):
        args=dict(monthly_returns=[-.2,.25])
        a=self.run_path(**args)
        b=self.run_path(**args,subscriptions=[10000,20000],redemption_fraction=.5)
        self.assertEqual([r['nav_per_unit'] for r in a],[r['nav_per_unit'] for r in b])
        self.assertAlmostEqual(a[-1]['nav_per_unit'],100)

    def test_fee_only_path_has_known_compounding(self):
        rows=self.run_path(annual_fee=.12)
        self.assertAlmostEqual(rows[-1]['closing_net_aum_usd'],1000*.99**2)
        self.assertAlmostEqual(rows[0]['administrative_fee_usd'],10)

    def test_fee_split_and_new_subscription_timing(self):
        rows=self.run_path(annual_fee=.12,subscriptions=[1000,0])
        self.assertEqual(rows[0]['fee_new_cohort_usd'],0)
        self.assertAlmostEqual(rows[1]['fee_new_cohort_usd'],10)
        self.assertAlmostEqual(rows[1]['administrative_fee_usd'],19.9)

    def test_redemption_changes_units_not_return(self):
        rows=self.run_path(subscriptions=[1000,0],redemption_fraction=.5)
        self.assertAlmostEqual(rows[1]['new_cohort_redemptions_usd'],500)
        self.assertEqual(rows[1]['nav_per_unit'],100)
        self.assertAlmostEqual(rows[1]['closing_net_aum_usd'],1500)

    def test_loss_remains_visible_in_reconciliation(self):
        row=self.run_path(monthly_returns=[-.3,0],subscriptions=[1000,0])[-1]
        self.assertAlmostEqual(row['cumulative_investment_pnl_after_admin_usd'],-300)
        self.assertAlmostEqual(row['closing_net_aum_usd'],1700)
        self.assertAlmostEqual(row['cumulative_net_contributed_usd'],2000)

    def test_invalid_inputs_fail(self):
        cases=[dict(initial_aum=0),dict(annual_fee=-.1),dict(monthly_returns=[-1,0]),
               dict(monthly_returns=[math.nan,0]),dict(subscriptions=[-1,0]),
               dict(subscriptions=[0]),dict(redemption_fraction=1),
               dict(seed_redemptions=[1001,0]),dict(monthly_returns=[-.99999,0],annual_fee=.5)]
        for case in cases:
            with self.subTest(case=case),self.assertRaises(ValueError):
                self.run_path(**case)


if __name__=='__main__':
    unittest.main()
