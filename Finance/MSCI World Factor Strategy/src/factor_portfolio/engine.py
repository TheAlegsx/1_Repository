"""Deterministic daily accounting engine.

The engine deliberately works from return series rather than downloading data.
It keeps assets, debt, equity, costs, and trade events as separate balances.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd

from .config import PortfolioConfig


COST_COMPONENTS = (
    "commission_usd",
    "platform_fee_usd",
    "stamp_duty_usd",
    "spread_cost_usd",
    "other_fee_usd",
)


class InsolventPortfolioError(RuntimeError):
    """Raised when debt equals or exceeds gross assets."""


@dataclass(frozen=True)
class BacktestResult:
    history: pd.DataFrame
    events: pd.DataFrame


def _validate_inputs(
    returns: pd.DataFrame,
    annual_borrow_rate: pd.Series,
    config: PortfolioConfig,
) -> tuple[pd.DataFrame, pd.Series]:
    if returns.empty:
        raise ValueError("returns must not be empty")
    if not isinstance(returns.index, pd.DatetimeIndex):
        raise TypeError("returns index must be a DatetimeIndex")
    if returns.index.has_duplicates:
        raise ValueError("returns index contains duplicate dates")
    if not returns.index.is_monotonic_increasing:
        raise ValueError("returns index must be sorted")
    if set(returns.columns) != set(config.target_weights):
        raise ValueError("returns columns must exactly match target_weights")
    if returns.isna().any().any():
        raise ValueError("returns contain missing values")
    if not np.isfinite(returns.to_numpy(dtype=float)).all():
        raise ValueError("returns contain non-finite values")
    if (returns <= -1.0).any().any():
        raise ValueError("returns must be greater than -100%")
    if (returns.iloc[0] != 0.0).any():
        raise ValueError("initialisation row must contain zero returns for every asset")

    if not isinstance(annual_borrow_rate.index, pd.DatetimeIndex):
        raise TypeError("annual_borrow_rate index must be a DatetimeIndex")
    if annual_borrow_rate.index.has_duplicates:
        raise ValueError("annual_borrow_rate index contains duplicate dates")
    if not annual_borrow_rate.index.is_monotonic_increasing:
        raise ValueError("annual_borrow_rate index must be sorted")
    required_calendar = pd.date_range(
        returns.index[0], returns.index[-1], freq="D", name="date"
    )
    rates = annual_borrow_rate.reindex(required_calendar)
    if rates.isna().any():
        raise ValueError(
            "annual_borrow_rate must cover every calendar day in the return window"
        )
    if not np.isfinite(rates.to_numpy(dtype=float)).all():
        raise ValueError("annual_borrow_rate contains non-finite values")
    if (rates <= -1.0).any():
        raise ValueError("annual_borrow_rate must be greater than -100%")

    ordered = returns.loc[:, list(config.target_weights)].astype(float)
    return ordered, rates.astype(float)


def _zero_costs() -> dict[str, float]:
    result = {name: 0.0 for name in COST_COMPONENTS}
    result["total_usd"] = 0.0
    return result


def _fees_for_trades(trades: pd.Series, config: PortfolioConfig) -> dict[str, float]:
    result = _zero_costs()
    for value in trades:
        leg = config.fee_schedule.breakdown(value)
        for name in COST_COMPONENTS:
            result[name] += float(leg[name])
    result["total_usd"] = float(sum(result[name] for name in COST_COMPONENTS))
    return result


def _solve_target_positions(
    positions: pd.Series,
    debt: float,
    equity_before_cost: float,
    config: PortfolioConfig,
    *,
    reset_leverage: bool,
) -> tuple[pd.Series, float, dict[str, float]]:
    """Solve post-cost target positions, debt, and total fees.

    Fees depend on trade size, which depends on post-cost assets. A short fixed-point
    iteration keeps the accounting identity exact for proportional and minimum fees.
    """

    total_assets_before = float(positions.sum())
    fees = 0.0
    weights = pd.Series(config.target_weights, dtype=float)

    for _ in range(100):
        equity_after_cost = equity_before_cost - fees
        if equity_after_cost <= 0.0:
            raise InsolventPortfolioError("transaction costs exhaust investor equity")
        if reset_leverage:
            target_assets = config.target_leverage * equity_after_cost
        else:
            target_assets = total_assets_before - fees
        target = weights * target_assets
        new_costs = _fees_for_trades(target - positions, config)
        new_fees = new_costs["total_usd"]
        if abs(new_fees - fees) <= 1e-10:
            fees = new_fees
            break
        fees = new_fees
    else:
        raise RuntimeError("transaction-cost solver did not converge")

    equity_after_cost = equity_before_cost - fees
    target_assets = (
        config.target_leverage * equity_after_cost
        if reset_leverage
        else total_assets_before - fees
    )
    target = weights * target_assets
    costs = _fees_for_trades(target - positions, config)
    new_debt = target_assets - equity_after_cost
    if not reset_leverage and abs(new_debt - debt) > 1e-8:
        raise AssertionError("sleeve-only rebalance changed debt")
    if abs(costs["total_usd"] - fees) > 1e-8:
        raise AssertionError("transaction-cost solution is inconsistent")
    return target, float(new_debt), costs


def _initialise(config: PortfolioConfig) -> tuple[pd.Series, float, dict[str, float]]:
    empty = pd.Series(0.0, index=list(config.target_weights), dtype=float)
    return _solve_target_positions(
        empty,
        debt=0.0,
        equity_before_cost=config.initial_equity_usd,
        config=config,
        reset_leverage=True,
    )


def _sleeve_breach(weights: pd.Series, config: PortfolioConfig) -> bool:
    targets = pd.Series(config.target_weights, dtype=float)
    return bool(((weights - targets).abs() > config.sleeve_band + 1e-12).any())


def _leverage_breach(leverage: float, config: PortfolioConfig) -> bool:
    if config.leverage_band is None:
        return False
    return abs(leverage - config.target_leverage) > config.leverage_band + 1e-12


def _assert_identity(assets: float, debt: float, equity: float) -> None:
    if not np.isclose(equity, assets - debt, rtol=1e-11, atol=1e-8):
        raise AssertionError("portfolio accounting identity failed")


def _event_frame(events: Iterable[dict[str, object]]) -> pd.DataFrame:
    columns = [
        "date",
        "event",
        "reason",
        "fees_usd",
        *COST_COMPONENTS,
        "gross_assets_usd",
        "debt_usd",
        "equity_usd",
    ]
    frame = pd.DataFrame(events, columns=columns)
    if not frame.empty:
        frame = frame.set_index("date")
    return frame


def run_backtest(
    returns: pd.DataFrame,
    annual_borrow_rate: pd.Series,
    config: PortfolioConfig,
) -> BacktestResult:
    """Run the deterministic daily portfolio simulation.

    The first row is the initialisation date and must contain zero returns for every asset.
    Voluntary band signals execute on the next observation. A maximum-leverage breach
    is treated as a same-day risk event and immediately resets leverage and sleeves.
    The borrowing-rate input must cover every calendar day. Financing between two
    valuations uses the rates on [prior valuation date, current valuation date).
    """

    returns, rates = _validate_inputs(returns, annual_borrow_rate, config)
    positions, debt, initial_costs = _initialise(config)
    pending_reason: str | None = None
    cumulative_financing = 0.0
    cumulative_fees = initial_costs["total_usd"]
    cumulative_costs = {
        name: initial_costs[name] for name in COST_COMPONENTS
    }
    rows: list[dict[str, float | bool | str]] = []
    events: list[dict[str, object]] = []

    first_date = returns.index[0]
    assets = float(positions.sum())
    equity = assets - debt
    _assert_identity(assets, debt, equity)
    events.append(
        {
            "date": first_date,
            "event": "initialise",
            "reason": "target allocation and leverage",
            "fees_usd": initial_costs["total_usd"],
            **{name: initial_costs[name] for name in COST_COMPONENTS},
            "gross_assets_usd": assets,
            "debt_usd": debt,
            "equity_usd": equity,
        }
    )

    previous_date = first_date
    for number, date in enumerate(returns.index):
        executed = False
        event_reason = ""
        daily_financing = 0.0

        if number > 0:
            positions = positions * (1.0 + returns.loc[date])
            interval_end = date - pd.Timedelta(days=1)
            interval_rates = rates.loc[previous_date:interval_end]
            daily_financing = debt * float(interval_rates.sum()) / config.day_count
            debt += daily_financing
            cumulative_financing += daily_financing

        assets = float(positions.sum())
        equity = assets - debt
        if equity <= 0.0:
            raise InsolventPortfolioError(f"portfolio insolvent on {date.date()}")
        leverage = assets / equity

        forced = config.max_leverage is not None and leverage >= config.max_leverage
        if forced:
            pending_reason = None
            positions, debt, costs = _solve_target_positions(
                positions,
                debt,
                equity,
                config,
                reset_leverage=True,
            )
            fees = costs["total_usd"]
            cumulative_fees += fees
            for name in COST_COMPONENTS:
                cumulative_costs[name] += costs[name]
            executed = True
            event_reason = "maximum leverage breach"
        elif pending_reason is not None:
            positions, debt, costs = _solve_target_positions(
                positions,
                debt,
                equity,
                config,
                reset_leverage=config.reset_leverage_on_rebalance or pending_reason == "leverage band breach",
            )
            fees = costs["total_usd"]
            cumulative_fees += fees
            for name in COST_COMPONENTS:
                cumulative_costs[name] += costs[name]
            executed = True
            event_reason = pending_reason
            pending_reason = None
        else:
            costs = initial_costs if number == 0 else _zero_costs()
            fees = costs["total_usd"]

        assets = float(positions.sum())
        equity = assets - debt
        if equity <= 0.0:
            raise InsolventPortfolioError(f"portfolio insolvent after trading on {date.date()}")
        leverage = assets / equity
        weights = positions / assets
        _assert_identity(assets, debt, equity)

        if executed:
            events.append(
                {
                    "date": date,
                    "event": "forced_deleverage" if forced else "rebalance",
                    "reason": event_reason,
                    "fees_usd": fees,
                    **{name: costs[name] for name in COST_COMPONENTS},
                    "gross_assets_usd": assets,
                    "debt_usd": debt,
                    "equity_usd": equity,
                }
            )

        if not forced and pending_reason is None:
            if _leverage_breach(leverage, config):
                pending_reason = "leverage band breach"
            elif _sleeve_breach(weights, config):
                pending_reason = "sleeve band breach"

        row: dict[str, float | bool | str] = {
            "gross_assets_usd": assets,
            "debt_usd": debt,
            "equity_usd": equity,
            "leverage": leverage,
            "annual_borrow_rate": float(rates.loc[date]),
            "financing_cost_usd": daily_financing,
            "cumulative_financing_cost_usd": cumulative_financing,
            "transaction_cost_usd": fees,
            "cumulative_transaction_cost_usd": cumulative_fees,
            "trade_executed": executed,
            "pending_signal": pending_reason or "",
        }
        for name in COST_COMPONENTS:
            row[f"transaction_{name}"] = costs[name]
            row[f"cumulative_{name}"] = cumulative_costs[name]
        for asset in positions.index:
            row[f"position_{asset}_usd"] = float(positions[asset])
            row[f"weight_{asset}"] = float(weights[asset])
        rows.append(row)
        previous_date = date

    history = pd.DataFrame(rows, index=returns.index)
    history.index.name = "date"
    return BacktestResult(history=history, events=_event_frame(events))
