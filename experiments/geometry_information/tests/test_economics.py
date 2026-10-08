import math
import unittest
import numpy as np
from experiments.geometry_information.economics import run_ledger


class LedgerTests(unittest.TestCase):
    def run_case(self, ts, op, p, **kw):
        options = dict(start=0, end=int(ts[-1])+1, interval_seconds=60,
                       fee_bps=0, slippage_bps=0)
        options.update(kw)
        return run_ledger(ts, op, p, **options)

    def test_signal_executes_next_open_and_terminal_sell_charged(self):
        r = self.run_case(np.arange(5)*60, [100, 110, 121, 133.1, 146.41],
                          [0.6]*5, fee_bps=10, slippage_bps=2)
        expected = 146.41/110 * (1-.001)**2 * (1-.0002)/(1+.0002)
        self.assertAlmostEqual(r['metrics']['net_return'], expected-1)
        self.assertEqual(r['metrics']['one_way_turnover'], 2)
        self.assertEqual(r['trades'][0]['entry_row'], 1)
        self.assertTrue(r['trades'][0]['terminal_liquidation'])

    def test_gap_is_carried_and_cash_request_executes_after_gap(self):
        ts = [0, 60, 120, 300, 360, 420]
        r = self.run_case(ts, [100, 100, 110, 55, 50, 50],
                          [.7, .7, .1, np.nan, np.nan, .7])
        self.assertAlmostEqual(r['metrics']['net_return'], -.45)
        gap = r['gaps'][0]
        self.assertEqual(gap['position_before'], 1)
        self.assertEqual(gap['position_after'], 0)
        self.assertEqual(gap['delay_seconds'], 120)
        self.assertAlmostEqual(gap['gap_gross_log_return'], math.log(.5))

    def test_pending_buy_before_gap_is_delayed_not_dropped(self):
        r = self.run_case([0, 60, 240, 300, 360], [100, 100, 80, 88, 88],
                          [.1, .9, np.nan, np.nan, np.nan])
        self.assertAlmostEqual(r['metrics']['net_return'], .1)
        self.assertEqual(r['trades'][0]['entry_row'], 2)
        self.assertEqual(r['trades'][0]['entry_delay_seconds'], 120)
        self.assertEqual(r['trades'][0]['exit_row'], 3)

    def test_fold_reset_ignores_preceding_signal_and_terminal_does_not_buy(self):
        r = self.run_case([0, 60, 120, 180], [100, 100, 100, 200],
                          [.9, .1, .9, .9], start=60)
        self.assertEqual(r['metrics']['one_way_turnover'], 0)
        self.assertEqual(r['metrics']['net_return'], 0)

    def test_future_prices_do_not_change_earlier_decisions(self):
        ts=np.arange(8)*60
        a=self.run_case(ts, [100]*8, [.7,.4,.8,.1,.9,.9,.9,.9])
        b=self.run_case(ts, [100]*5+[500,20,700], [.7,.4,.8,.1,.9,.9,.9,.9])
        np.testing.assert_array_equal(a['trace']['position_after'], b['trace']['position_after'])
        np.testing.assert_array_equal(a['trace']['net_log_return'][:5], b['trace']['net_log_return'][:5])

    def test_hysteresis_costs_only_on_exposure_changes_and_full_daily_grid(self):
        r=self.run_case(np.arange(7)*86400, [100]*7, [.8,.55,.6,.3,.8,.8,.8],
                        interval_seconds=86400, entry_threshold=.7, exit_threshold=.4,
                        fee_bps=10)
        self.assertEqual(r['metrics']['one_way_turnover'], 4)
        self.assertEqual(len(r['daily_days']), 7)
        self.assertAlmostEqual(r['metrics']['net_log_return'], 4*math.log1p(-.001))

    def test_cash_and_buy_hold_have_the_same_period_boundaries(self):
        ts=[0,60,240,300,360]
        for policy, expected in [('cash',0),('buy_hold',.2)]:
            r=self.run_case(ts,[100,100,110,110,120],[np.nan]*5,policy=policy)
            self.assertAlmostEqual(r['metrics']['net_return'],expected)
            self.assertEqual(r['metrics']['terminal_open'],360)

    def test_invalid_source_or_policy_fails(self):
        with self.assertRaises(ValueError):
            self.run_case([0,60,60],[100]*3,[.5]*3)
        with self.assertRaises(ValueError):
            self.run_case([0,60,120],[100]*3,[1.1]*3)


if __name__ == '__main__':
    unittest.main()
