"""Offline accounting demonstration on entirely invented observations."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import sys
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from factor_portfolio import FeeSchedule, PortfolioConfig, run_backtest


def calculate() -> dict:
    fixture = ROOT / "examples/synthetic_inputs.csv"
    frame = pd.read_csv(fixture, index_col="date", parse_dates=["date"])
    assets = ["core", "momentum", "quality", "value"]
    assert frame.columns.tolist() == [*assets, "annual_borrow_rate"]
    assert len(frame) == 600 and frame.index[0] == pd.Timestamp("2030-01-02")
    assert frame.annual_borrow_rate.eq(0.04).all()
    calendar = pd.date_range(frame.index[0], frame.index[-1], freq="D")
    rates = pd.Series(0.04, index=calendar, name="annual_borrow_rate")
    config = PortfolioConfig(
        target_weights={"core": 0.60, "momentum": 0.15, "quality": 0.15, "value": 0.10},
        initial_equity_usd=10000.0, target_leverage=1.25,
        sleeve_band=0.05, leverage_band=0.10,
        fee_schedule=FeeSchedule(proportional_rate=0.001, minimum_per_trade=1.0),
    )
    result = run_backtest(frame[assets], rates, config)
    history = result.history
    identity = history.gross_assets_usd - history.debt_usd - history.equity_usd
    assert np.isfinite(history.select_dtypes(include="number").to_numpy()).all()
    assert identity.abs().max() < 1e-8 and history.equity_usd.gt(0).all()
    assert history.cumulative_financing_cost_usd.iloc[-1] > 0
    reasons = sorted(set(result.events.reason.iloc[1:]))
    assert "sleeve band breach" in reasons and "leverage band breach" in reasons
    last = history.iloc[-1]
    return {
        "input_status": "synthetic; no market observations",
        "fixture_sha256": hashlib.sha256(fixture.read_bytes()).hexdigest(),
        "valuation_rows": len(frame), "start": str(frame.index[0].date()),
        "end": str(frame.index[-1].date()), "initial_equity_usd": 10000.0,
        "ending_equity_usd": round(float(last.equity_usd), 6),
        "financing_cost_usd": round(float(last.cumulative_financing_cost_usd), 6),
        "transaction_cost_usd": round(float(last.cumulative_transaction_cost_usd), 6),
        "events_including_initialization": len(result.events),
        "post_initialization_event_reasons": reasons,
        "summary_rounding": "six decimal USD; exact fixture and discrete fields",
    }


def main() -> None:
    expected = json.loads((ROOT / "examples/synthetic_demo_expected.json").read_text())
    fixture = ROOT / "examples/synthetic_inputs.csv"
    assert hashlib.sha256(fixture.read_bytes()).hexdigest() == expected["fixture_sha256"]
    actual = calculate()
    assert actual == expected, "Synthetic summary changed; review the candidate"
    print(json.dumps(actual, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
