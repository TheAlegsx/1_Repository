from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from factor_portfolio import FeeSchedule, PortfolioConfig
from factor_portfolio.benchmark import (
    build_same_leverage_comparison,
    calculate_risk_adjusted_metrics,
    calendar_metadata,
    exclude_unchanged_nav_sensitivity,
    investor_drawdown,
    investor_equity_returns,
    load_benchmark_comparison,
    write_benchmark_comparison,
)


TARGETS = {"core": 0.60, "momentum": 0.15, "quality": 0.10, "value": 0.15}


def _rates(index: pd.DatetimeIndex) -> pd.Series:
    calendar = pd.date_range(index[0], index[-1], freq="D", name="date")
    return pd.Series(0.04, index=calendar, name="borrow_rate_annual")


def _reference_rates(index: pd.DatetimeIndex) -> pd.Series:
    calendar = pd.date_range(index[0], index[-1], freq="D", name="date")
    return pd.Series(0.01, index=calendar, name="reference_rate_annual")


def _config(*, fees: bool = False) -> PortfolioConfig:
    return PortfolioConfig(
        target_weights=TARGETS,
        initial_equity_usd=10_000.0,
        target_leverage=1.25,
        sleeve_band=0.05,
        leverage_band=0.10,
        fee_schedule=FeeSchedule(minimum_per_trade=5.0) if fees else FeeSchedule(),
    )


def test_identical_asset_returns_produce_identical_equal_leverage_paths() -> None:
    index = pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06"])
    common = [0.0, 0.02, -0.01]
    returns = pd.DataFrame({asset: common for asset in TARGETS}, index=index)

    comparison = build_same_leverage_comparison(
        returns,
        _rates(index),
        _reference_rates(index),
        _config(),
        leverage_levels=(1.0, 1.25),
    )

    for leverage in ("1.00x", "1.25x"):
        pd.testing.assert_series_equal(
            comparison.equity_curves[f"factor_{leverage}"],
            comparison.equity_curves[f"core_{leverage}"],
            check_names=False,
        )
    differences = comparison.relative_metrics.drop(columns="target_leverage")
    assert (differences.abs() < 1e-8).all().all()


def test_relative_metrics_are_factor_minus_core() -> None:
    index = pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06"])
    returns = pd.DataFrame(
        {
            "core": [0.0, 0.00, 0.00],
            "momentum": [0.0, 0.10, 0.00],
            "quality": [0.0, 0.05, 0.00],
            "value": [0.0, 0.05, 0.00],
        },
        index=index,
    )

    comparison = build_same_leverage_comparison(
        returns,
        _rates(index),
        _reference_rates(index),
        _config(),
        leverage_levels=(1.0,),
    )
    metrics = comparison.metrics.set_index("strategy")
    relative = comparison.relative_metrics.iloc[0]

    expected = (
        metrics.loc["factor_portfolio", "ending_equity_usd"]
        - metrics.loc["core_benchmark", "ending_equity_usd"]
    )
    assert relative["factor_minus_core_ending_equity_usd"] == pytest.approx(expected)
    assert expected > 0.0


def test_costs_follow_actual_number_of_trade_legs() -> None:
    index = pd.to_datetime(["2026-01-02", "2026-01-05"])
    returns = pd.DataFrame({asset: [0.0, 0.0] for asset in TARGETS}, index=index)

    comparison = build_same_leverage_comparison(
        returns,
        _rates(index),
        _reference_rates(index),
        _config(fees=True),
        leverage_levels=(1.25,),
    )
    metrics = comparison.metrics.set_index("strategy")

    factor_cost = metrics.loc[
        "factor_portfolio", "cumulative_transaction_cost_usd"
    ]
    core_cost = metrics.loc["core_benchmark", "cumulative_transaction_cost_usd"]
    assert factor_cost == pytest.approx(20.0)
    assert core_cost == pytest.approx(5.0)


def test_benchmark_outputs_are_deterministic_and_tamper_checked(tmp_path: Path) -> None:
    index = pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06"])
    returns = pd.DataFrame(
        {
            "core": [0.0, 0.01, -0.01],
            "momentum": [0.0, 0.02, -0.01],
            "quality": [0.0, 0.00, 0.01],
            "value": [0.0, -0.01, 0.02],
        },
        index=index,
    )
    comparison = build_same_leverage_comparison(
        returns,
        _rates(index),
        _reference_rates(index),
        _config(),
        leverage_levels=(1.0, 1.25),
    )

    first = write_benchmark_comparison(comparison, tmp_path / "first")
    second = write_benchmark_comparison(comparison, tmp_path / "second")
    repeated = write_benchmark_comparison(comparison, tmp_path / "first")
    for key in first:
        assert first[key].read_bytes() == second[key].read_bytes()
        assert first[key].read_bytes() == repeated[key].read_bytes()

    loaded = load_benchmark_comparison(tmp_path / "first")
    pd.testing.assert_frame_equal(loaded.metrics, comparison.metrics)
    pd.testing.assert_frame_equal(loaded.equity_curves, comparison.equity_curves)

    first["equity"].write_bytes(first["equity"].read_bytes() + b"\n")
    with pytest.raises(ValueError, match="checksum mismatch"):
        load_benchmark_comparison(tmp_path / "first")


def test_alpha_beta_and_sharpe_follow_declared_daily_excess_return_formulas() -> None:
    index = pd.bdate_range("2026-01-02", periods=5, name="date")
    benchmark_returns = pd.Series([0.01, -0.01, 0.02, -0.005], index=index[1:])
    portfolio_returns = 0.001 + 1.2 * benchmark_returns
    benchmark_equity = pd.concat(
        [pd.Series([100.0], index=index[:1]), 100.0 * (1.0 + benchmark_returns).cumprod()]
    )
    portfolio_equity = pd.concat(
        [pd.Series([100.0], index=index[:1]), 100.0 * (1.0 + portfolio_returns).cumprod()]
    )
    reference = pd.Series(
        0.0,
        index=pd.date_range(index[0], index[-1], freq="D", name="date"),
    )

    metrics = calculate_risk_adjusted_metrics(
        portfolio_equity,
        reference,
        benchmark_equity=benchmark_equity,
    )

    assert metrics["beta_vs_core"] == pytest.approx(1.2)
    assert metrics["annualised_alpha_vs_core"] == pytest.approx(0.252)
    assert metrics["sharpe_ratio"] > 0.0


def test_investor_returns_include_entry_once_and_link_to_committed_capital() -> None:
    dates = pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06"])
    equity = pd.Series([90.0, 99.0, 108.9], index=dates)
    primary = investor_equity_returns(equity, initial_committed_capital_usd=100.0)
    ongoing = investor_equity_returns(equity)

    assert primary.index.tolist() == dates[1:].tolist()
    np.testing.assert_allclose(primary, [-0.01, 0.10])
    np.testing.assert_allclose(ongoing, [0.10, 0.10])
    assert (1.0 + primary).prod() == pytest.approx(108.9 / 100.0)
    assert (1.0 + ongoing).prod() == pytest.approx(108.9 / 90.0)
    # A later ongoing window must not recharge the original entry loss.
    np.testing.assert_allclose(investor_equity_returns(equity.iloc[1:]), [0.10])


def test_drawdown_includes_entry_loss_until_committed_capital_is_recovered() -> None:
    equity = pd.Series(
        [90.0, 95.0, 101.0, 98.0],
        index=pd.bdate_range("2026-01-02", periods=4),
    )
    primary = investor_drawdown(equity, initial_committed_capital_usd=100.0)
    ongoing = investor_drawdown(equity)

    np.testing.assert_allclose(primary, [-0.10, -0.05, 0.0, 98.0 / 101.0 - 1.0])
    assert ongoing.iloc[0] == 0.0


def test_unequal_entry_costs_and_first_interval_reference_accrual_are_consistent() -> None:
    dates = pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07"])
    equity = pd.Series([98.0, 99.96, 98.9604, 100.444806], index=dates)
    benchmark = pd.Series([99.0, 100.98, 99.9702, 101.469753], index=dates)
    reference = pd.Series(0.036, index=pd.date_range(dates[0], dates[-1]))
    reference.iloc[-1] = 0.99  # The final closing rate must not accrue retrospectively.
    metrics = calculate_risk_adjusted_metrics(
        equity, reference, benchmark_equity=benchmark,
        initial_committed_capital_usd=100.0,
        benchmark_initial_committed_capital_usd=100.0,
    )
    portfolio_excess = np.array([-0.0004, -0.01, 0.015]) - np.array([0.0003, 0.0001, 0.0001])
    benchmark_excess = np.array([0.0098, -0.01, 0.015]) - np.array([0.0003, 0.0001, 0.0001])
    slope, intercept = np.polyfit(benchmark_excess, portfolio_excess, 1)

    assert metrics["beta_vs_core"] == pytest.approx(slope)
    assert metrics["annualised_alpha_vs_core"] == pytest.approx(intercept * 252.0)
    assert metrics["sharpe_ratio"] == pytest.approx(
        portfolio_excess.mean() / portfolio_excess.std(ddof=1) * np.sqrt(252.0)
    )
    core = calculate_risk_adjusted_metrics(
        benchmark, reference, benchmark_equity=benchmark,
        initial_committed_capital_usd=100.0,
        benchmark_initial_committed_capital_usd=100.0,
    )
    assert core["beta_vs_core"] == pytest.approx(1.0)
    assert core["annualised_alpha_vs_core"] == pytest.approx(0.0, abs=1e-14)


def test_risk_metrics_reject_mixed_opening_cost_views() -> None:
    dates = pd.bdate_range("2026-01-02", periods=3)
    equity = pd.Series([100.0, 102.0, 101.0], index=dates)
    with pytest.raises(ValueError, match="same opening-cost view"):
        calculate_risk_adjusted_metrics(
            equity, _reference_rates(dates), benchmark_equity=equity,
            initial_committed_capital_usd=100.0,
        )


def test_zero_entry_costs_leave_both_measurement_views_identical() -> None:
    dates = pd.bdate_range("2026-01-02", periods=3)
    equity = pd.Series([100.0, 102.0, 101.0], index=dates)
    pd.testing.assert_series_equal(
        investor_equity_returns(equity),
        investor_equity_returns(equity, initial_committed_capital_usd=100.0),
    )
    pd.testing.assert_series_equal(
        investor_drawdown(equity),
        investor_drawdown(equity, initial_committed_capital_usd=100.0),
    )
    ongoing = calculate_risk_adjusted_metrics(
        equity, _reference_rates(dates), benchmark_equity=equity,
    )
    primary = calculate_risk_adjusted_metrics(
        equity, _reference_rates(dates), benchmark_equity=equity,
        initial_committed_capital_usd=100.0,
        benchmark_initial_committed_capital_usd=100.0,
    )
    assert primary == pytest.approx(ongoing)


def test_summary_separates_actual_entry_loss_from_flat_ongoing_risk() -> None:
    dates = pd.bdate_range("2026-01-02", periods=3)
    returns = pd.DataFrame(0.0, index=dates, columns=TARGETS)
    zero_rates = pd.Series(0.0, index=pd.date_range(dates[0], dates[-1]))
    config = PortfolioConfig(
        target_weights=TARGETS, initial_equity_usd=1_000.0, target_leverage=1.0,
        fee_schedule=FeeSchedule(minimum_per_trade=25.0),
    )
    comparison = build_same_leverage_comparison(
        returns, zero_rates, zero_rates, config, leverage_levels=(1.0,),
    )
    metrics = comparison.metrics.set_index("strategy")
    factor = metrics.loc["factor_portfolio"]
    core = metrics.loc["core_benchmark"]

    assert factor["opening_transaction_cost_usd"] == pytest.approx(100.0)
    assert factor["ending_equity_usd"] == pytest.approx(900.0)
    assert factor["maximum_drawdown"] == pytest.approx(-0.10)
    assert core["maximum_drawdown"] == pytest.approx(-0.025)
    assert factor["annualised_volatility"] == pytest.approx(np.std([-0.1, 0.0], ddof=1) * np.sqrt(252.0))
    assert factor["ongoing_annualised_volatility"] == 0.0
    assert factor["ongoing_maximum_drawdown"] == 0.0
    assert factor["return_observations"] == 2


def test_calendar_sensitivity_preserves_endpoints_and_product_compounding() -> None:
    dates = pd.to_datetime(["2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05", "2026-01-06"])
    navs = pd.DataFrame(
        {"core": [100.0, 100.0, 100.0, 110.0, 110.0],
         "momentum": [100.0, 100.0, 105.0, 105.0, 105.0]}, index=dates,
    )
    original = navs.copy(deep=True)
    retained = exclude_unchanged_nav_sensitivity(navs)
    assert retained.index.tolist() == [dates[0], dates[2], dates[3], dates[4]]
    pd.testing.assert_frame_equal(navs, original)
    compounded = (1.0 + retained.pct_change(fill_method=None).iloc[1:]).prod()
    np.testing.assert_allclose(compounded, navs.iloc[-1] / navs.iloc[0])
    metadata = calendar_metadata(retained.index, calendar_id="sensitivity")
    assert metadata["return_observations"] == 3
    assert metadata["maximum_interval_calendar_days"] == 2
    assert metadata["nominal_annualisation_periods"] == 252.0
