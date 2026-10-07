"""Presentation controls for configured starting wealth and signed business cash."""
import json
from pathlib import Path
import pytest
from factor_portfolio.inflow_scenarios import acquisition, timing
from factor_portfolio.inflow_results import sensitivity_tables
from factor_portfolio.inflow_figures import plot_specs

ROOT = Path(__file__).resolve().parents[1]


def specs(capital):
    b = json.loads((ROOT / 'config/inflow_acquisition.json').read_text())
    t = json.loads((ROOT / 'config/inflow_timing.json').read_text())
    b['initial_owner_capital_usd'] = t['owner_capital_usd'] = capital
    a = [r for rid in b['annual_returns'] for sid in b['annual_new_client_equivalents'] for r in acquisition(b, rid, sid)]
    ts = [r for rid in b['annual_returns'] for sid in t['monthly_schedules_usd'] for r in timing(b, t, rid, sid)]
    fees, _ = sensitivity_tables(b)
    return plot_specs({'acquisition_monthly.csv': a, 'timing_monthly.csv': ts,
                       'fee_ticket_receipt_sensitivity.csv': fees}, b, t)


def test_asset_charts_start_at_configured_owner_capital():
    charts = specs(123456)
    asset = [x for x in charts if x['field'] in {'closing_aum_usd', 'closing_net_aum_usd'}]
    assert len(asset) == 4
    for chart in asset:
        for series in chart['series']:
            assert series['y'][0] == pytest.approx(.123456)
            assert series['x'][0] == 0
            assert series['x'][-1] == 10


def test_cash_losses_remain_visible_and_timing_steps_are_matched_volume():
    charts = specs(7000000)
    for chart in charts:
        if 'cash' in chart['field']:
            assert chart['zero_floor'] is False
            assert any(min(s['y']) < 0 for s in chart['series'])
    step = next(x for x in charts if x['kind'] == 'step')
    assert len(step['series']) == 5
    assert all(s['y'][-1] == pytest.approx(27.5) for s in step['series'])
