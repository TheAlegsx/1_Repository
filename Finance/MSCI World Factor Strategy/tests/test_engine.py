from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from factor_portfolio import (
    ECB_USD_PER_CHF_2026_08_31,
    FeeSchedule,
    PortfolioConfig,
    SwissquoteStandardFeeSchedule,
    run_backtest,
)


ASSETS = ["core", "momentum", "quality", "value"]
TARGETS = {"core": 0.75, "momentum": 0.15, "quality": 0.05, "value": 0.05}


def _frame(rows: list[list[float]]) -> pd.DataFrame:
    dates = pd.date_range("2026-01-02", periods=len(rows), freq="D")
    return pd.DataFrame(rows, index=dates, columns=ASSETS)


def _rates(index: pd.DatetimeIndex, value: float = 0.0) -> pd.Series:
    return pd.Series(value, index=index, name="annual_borrow_rate")


@pytest.mark.parametrize("asset", ASSETS)
@pytest.mark.parametrize("initial_return", [0.20, -0.20, 1e-14])
def test_nonzero_initialisation_return_fails_loudly(
    asset: str, initial_return: float
) -> None:
    returns = _frame([[0.0] * 4, [0.01] * 4])
    returns.loc[returns.index[0], asset] = initial_return

    with pytest.raises(ValueError, match="initialisation row must contain zero returns"):
        run_backtest(returns, _rates(returns.index), PortfolioConfig(target_weights=TARGETS))


def test_offsetting_initialisation_returns_fail_loudly() -> None:
    returns = _frame([[0.20, -0.20, 0.0, 0.0], [0.0] * 4])

    with pytest.raises(ValueError, match="initialisation row must contain zero returns"):
        run_backtest(returns, _rates(returns.index), PortfolioConfig(target_weights=TARGETS))


def test_flat_assets_lose_only_financing_cost() -> None:
    returns = _frame([[0.0] * 4, [0.0] * 4])
    config = PortfolioConfig(target_weights=TARGETS, target_leverage=1.5, sleeve_band=0.5)

    result = run_backtest(returns, _rates(returns.index, 0.06), config)
    history = result.history

    initial_debt = history.iloc[0]["debt_usd"]
    expected_interest = initial_debt * 0.06 / 360.0
    assert history.iloc[1]["equity_usd"] == pytest.approx(
        history.iloc[0]["equity_usd"] - expected_interest
    )
    assert history.iloc[1]["financing_cost_usd"] == pytest.approx(expected_interest)


def test_financing_uses_interval_rates_without_look_ahead() -> None:
    dates = pd.DatetimeIndex(["2026-01-02", "2026-01-05"])
    returns = pd.DataFrame(0.0, index=dates, columns=ASSETS)
    rate_calendar = pd.Series(
        [0.036, 0.036, 0.036, 0.99],
        index=pd.date_range("2026-01-02", "2026-01-05", freq="D"),
        name="annual_borrow_rate",
    )
    config = PortfolioConfig(target_weights=TARGETS, target_leverage=1.5, sleeve_band=0.5)

    history = run_backtest(returns, rate_calendar, config).history

    initial_debt = history.iloc[0]["debt_usd"]
    expected_interest = initial_debt * 0.036 * 3.0 / 360.0
    assert history.iloc[1]["financing_cost_usd"] == pytest.approx(expected_interest)
    assert history.iloc[1]["annual_borrow_rate"] == pytest.approx(0.99)


def test_financing_includes_rate_change_inside_nav_gap() -> None:
    dates = pd.DatetimeIndex(["2026-01-02", "2026-01-06"])
    returns = pd.DataFrame(0.0, index=dates, columns=ASSETS)
    rate_calendar = pd.Series(
        [0.036, 0.036, 0.036, 0.05, 0.99],
        index=pd.date_range("2026-01-02", "2026-01-06", freq="D"),
        name="annual_borrow_rate",
    )
    config = PortfolioConfig(target_weights=TARGETS, target_leverage=1.5, sleeve_band=0.5)

    history = run_backtest(returns, rate_calendar, config).history

    initial_debt = history.iloc[0]["debt_usd"]
    expected_interest = initial_debt * (0.036 * 3.0 + 0.05) / 360.0
    assert history.iloc[1]["financing_cost_usd"] == pytest.approx(expected_interest)


def test_missing_calendar_rate_fails_loudly() -> None:
    dates = pd.DatetimeIndex(["2026-01-02", "2026-01-05"])
    returns = pd.DataFrame(0.0, index=dates, columns=ASSETS)
    incomplete_rates = pd.Series(
        0.036,
        index=pd.DatetimeIndex(["2026-01-02", "2026-01-03", "2026-01-05"]),
    )

    with pytest.raises(ValueError, match="every calendar day"):
        run_backtest(
            returns,
            incomplete_rates,
            PortfolioConfig(target_weights=TARGETS),
        )


def test_accounting_identity_holds_every_day() -> None:
    returns = _frame(
        [
            [0.0, 0.0, 0.0, 0.0],
            [0.01, -0.02, 0.005, 0.0],
            [-0.03, 0.04, 0.01, -0.01],
        ]
    )
    config = PortfolioConfig(target_weights=TARGETS, target_leverage=1.75)

    history = run_backtest(returns, _rates(returns.index, 0.05), config).history

    np.testing.assert_allclose(
        history["equity_usd"],
        history["gross_assets_usd"] - history["debt_usd"],
        rtol=1e-11,
        atol=1e-8,
    )


def test_band_signal_executes_on_next_observation() -> None:
    returns = _frame(
        [
            [0.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 0.0, 0.0],
        ]
    )
    config = PortfolioConfig(target_weights=TARGETS, target_leverage=1.0, sleeve_band=0.02)

    history = run_backtest(returns, _rates(returns.index), config).history

    assert not bool(history.iloc[1]["trade_executed"])
    assert history.iloc[1]["pending_signal"] == "sleeve band breach"
    assert bool(history.iloc[2]["trade_executed"])
    for asset, target in TARGETS.items():
        assert history.iloc[2][f"weight_{asset}"] == pytest.approx(target)


def test_minimum_fee_is_charged_for_each_traded_sleeve() -> None:
    returns = _frame(
        [
            [0.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 0.0, 0.0],
        ]
    )
    config = PortfolioConfig(
        target_weights=TARGETS,
        target_leverage=1.0,
        sleeve_band=0.02,
        fee_schedule=FeeSchedule(minimum_per_trade=5.0),
    )

    history = run_backtest(returns, _rates(returns.index), config).history

    assert history.iloc[2]["transaction_cost_usd"] == pytest.approx(20.0)


def test_default_baseline_is_illustrative_capital_at_one_point_two_five_leverage() -> None:
    config = PortfolioConfig(target_weights=TARGETS)

    assert config.initial_equity_usd == 10_000.0
    assert config.target_leverage == 1.25
    assert config.leverage_band == 0.10


def test_leverage_band_executes_next_observation_and_resets_target() -> None:
    returns = _frame(
        [
            [0.0, 0.0, 0.0, 0.0],
            [-0.40, -0.40, -0.40, -0.40],
            [0.0, 0.0, 0.0, 0.0],
        ]
    )
    config = PortfolioConfig(
        target_weights=TARGETS,
        target_leverage=1.25,
        sleeve_band=0.5,
        leverage_band=0.10,
        fee_schedule=FeeSchedule(),
    )

    result = run_backtest(returns, _rates(returns.index), config)
    history = result.history

    assert not bool(history.iloc[1]["trade_executed"])
    assert history.iloc[1]["pending_signal"] == "leverage band breach"
    assert bool(history.iloc[2]["trade_executed"])
    assert history.iloc[2]["leverage"] == pytest.approx(1.25)
    assert result.events.iloc[-1]["reason"] == "leverage band breach"


def test_swissquote_standard_fee_breakdown_is_auditable() -> None:
    schedule = SwissquoteStandardFeeSchedule()

    costs = schedule.breakdown(100_000.0)

    assert costs["commission_usd"] == pytest.approx(
        190.0 * ECB_USD_PER_CHF_2026_08_31
    )
    assert costs["platform_fee_usd"] == pytest.approx(0.85)
    assert costs["stamp_duty_usd"] == pytest.approx(150.0)
    assert costs["spread_cost_usd"] == pytest.approx(50.0)
    assert costs["other_fee_usd"] == 0.0
    assert costs["total_usd"] == pytest.approx(
        sum(costs[name] for name in costs if name != "total_usd")
    )


@pytest.mark.parametrize(
    ("notional", "expected_commission_chf"),
    [
        (500.0, 3.0),
        (500.01, 5.0),
        (1_000.01, 10.0),
        (2_000.01, 29.0),
        (10_000.01, 49.0),
        (15_000.01, 79.0),
        (25_000.01, 129.0),
        (50_000.01, 190.0),
    ],
)
def test_swissquote_standard_commission_tiers(
    notional: float, expected_commission_chf: float
) -> None:
    assert (
        SwissquoteStandardFeeSchedule.commission_chf(notional)
        == expected_commission_chf
    )


def test_initial_cost_components_are_recorded_on_first_date() -> None:
    returns = _frame([[0.0] * 4])
    config = PortfolioConfig(target_weights=TARGETS, target_leverage=1.5)

    result = run_backtest(returns, _rates(returns.index), config)
    first = result.history.iloc[0]
    event = result.events.iloc[0]

    component_total = sum(
        first[f"transaction_{name}"]
        for name in (
            "commission_usd",
            "platform_fee_usd",
            "stamp_duty_usd",
            "spread_cost_usd",
            "other_fee_usd",
        )
    )
    assert first["transaction_cost_usd"] > 0.0
    assert first["transaction_cost_usd"] == pytest.approx(component_total)
    assert first["cumulative_transaction_cost_usd"] == pytest.approx(component_total)
    assert event["fees_usd"] == pytest.approx(component_total)


def test_forced_deleveraging_sells_assets_and_resets_leverage() -> None:
    returns = _frame(
        [
            [0.0, 0.0, 0.0, 0.0],
            [-0.35, -0.35, -0.35, -0.35],
        ]
    )
    config = PortfolioConfig(
        target_weights=TARGETS,
        target_leverage=1.5,
        sleeve_band=0.5,
        max_leverage=2.0,
    )

    result = run_backtest(returns, _rates(returns.index), config)

    assert result.history.iloc[1]["leverage"] == pytest.approx(1.5)
    assert result.events.iloc[-1]["event"] == "forced_deleverage"


def test_unsorted_dates_fail_loudly() -> None:
    returns = _frame([[0.0] * 4, [0.0] * 4]).sort_index(ascending=False)

    with pytest.raises(ValueError, match="sorted"):
        run_backtest(returns, _rates(returns.index), PortfolioConfig(target_weights=TARGETS))
