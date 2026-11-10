"""Investor-return, drawdown and rate calculations retained from the research engine."""

import numpy as np
import pandas as pd


def _validate_equity(equity: pd.Series) -> None:
    if not isinstance(equity.index, pd.DatetimeIndex):
        raise TypeError("equity index must be a DatetimeIndex")
    if equity.empty or equity.index.has_duplicates or not equity.index.is_monotonic_increasing:
        raise ValueError("equity dates must be non-empty, unique and sorted")
    values = equity.to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values <= 0.0).any():
        raise ValueError("equity must contain finite positive values")


def _validate_capital(capital: float) -> None:
    if not np.isfinite(capital) or capital <= 0.0:
        raise ValueError("initial committed capital must be finite and positive")


def investor_equity_returns(
    equity: pd.Series, *, initial_committed_capital_usd: float | None = None
) -> pd.Series:
    """Return valuation-interval investor returns, optionally including entry costs.

    With committed capital, the first interval is E1 / capital - 1. Without it,
    returns describe the ongoing post-entry portfolio. No extra date is inserted.
    """

    _validate_equity(equity)
    if len(equity) < 2:
        raise ValueError("investor returns require at least two valuations")
    returns = equity.pct_change(fill_method=None).iloc[1:].copy()
    if initial_committed_capital_usd is not None:
        _validate_capital(initial_committed_capital_usd)
        returns.iloc[0] = equity.iloc[1] / initial_committed_capital_usd - 1.0
    return returns


def investor_drawdown(
    equity: pd.Series, *, initial_committed_capital_usd: float | None = None
) -> pd.Series:
    """Measure drawdown with an optional committed-capital opening high-water mark."""

    _validate_equity(equity)
    high_water = equity.cummax()
    if initial_committed_capital_usd is not None:
        _validate_capital(initial_committed_capital_usd)
        high_water = high_water.clip(lower=initial_committed_capital_usd)
    return equity / high_water - 1.0


def _interval_reference_returns(
    valuation_index: pd.DatetimeIndex,
    annual_reference_rate: pd.Series,
    *,
    day_count: float,
) -> pd.Series:
    """Convert calendar-daily annual rates to valuation-interval returns."""

    if len(valuation_index) < 2:
        raise ValueError("risk metrics require at least two valuation dates")
    if not isinstance(annual_reference_rate.index, pd.DatetimeIndex):
        raise TypeError("annual_reference_rate index must be a DatetimeIndex")
    if annual_reference_rate.index.has_duplicates:
        raise ValueError("annual_reference_rate contains duplicate dates")
    required = pd.date_range(
        valuation_index[0], valuation_index[-1], freq="D", name="date"
    )
    rates = annual_reference_rate.reindex(required)
    if rates.isna().any():
        raise ValueError(
            "annual_reference_rate must cover every calendar day in the valuation window"
        )
    if not np.isfinite(rates.to_numpy(dtype=float)).all():
        raise ValueError("annual_reference_rate contains non-finite values")
    if not np.isfinite(day_count) or day_count <= 0.0:
        raise ValueError("day_count must be finite and positive")
    daily = rates.astype(float) / day_count
    accrued_before_date = daily.cumsum().shift(1, fill_value=0.0)
    starts = accrued_before_date.reindex(valuation_index[:-1]).to_numpy(dtype=float)
    ends = accrued_before_date.reindex(valuation_index[1:]).to_numpy(dtype=float)
    return pd.Series(
        ends - starts,
        index=valuation_index[1:],
        name="risk_free_interval_return",
    )
