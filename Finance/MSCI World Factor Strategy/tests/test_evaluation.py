from __future__ import annotations

from datetime import date
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

from factor_portfolio import FeeSchedule, PortfolioConfig
from factor_portfolio.evaluation import (
    build_split_evaluation,
    load_split_evaluation,
    write_split_evaluation,
)


TARGETS = {"core": 0.60, "momentum": 0.15, "quality": 0.10, "value": 0.15}


def _inputs() -> tuple[pd.DataFrame, pd.Series, pd.Series, PortfolioConfig]:
    index = pd.to_datetime(
        ["2021-12-29", "2021-12-31", "2022-01-04", "2022-01-05"]
    )
    returns = pd.DataFrame(
        {
            "core": [0.25, 0.01, 0.50, 0.02],
            "momentum": [0.25, 0.02, 0.50, 0.03],
            "quality": [0.25, 0.00, 0.50, 0.01],
            "value": [0.25, -0.01, 0.50, 0.02],
        },
        index=index,
    )
    calendar = pd.date_range(index[0], index[-1], freq="D", name="date")
    rates = pd.Series(0.04, index=calendar, name="borrow_rate_annual")
    reference = pd.Series(0.01, index=calendar, name="reference_rate_annual")
    config = PortfolioConfig(
        target_weights=TARGETS,
        fee_schedule=FeeSchedule(),
    )
    return returns, rates, reference, config


def test_periods_are_independent_and_first_returns_are_zeroed() -> None:
    returns, rates, reference, config = _inputs()

    result = build_split_evaluation(
        returns,
        rates,
        reference,
        config,
        calibration_end=date(2021, 12, 31),
        confirmation_start=date(2022, 1, 4),
    )

    assert result.manifest["periods"]["calibration"]["observations"] == 2
    assert result.manifest["periods"]["confirmation"]["observations"] == 2
    first_rows = result.equity_curves.groupby("period", sort=False).first()
    assert first_rows.loc["calibration", "factor_1.25x"] == pytest.approx(
        first_rows.loc["confirmation", "factor_1.25x"]
    )
    assert first_rows.loc["calibration", "core_1.25x"] == pytest.approx(
        first_rows.loc["confirmation", "core_1.25x"]
    )


def test_split_must_use_next_common_observation() -> None:
    returns, rates, reference, config = _inputs()

    with pytest.raises(ValueError, match="first common observation"):
        build_split_evaluation(
            returns,
            rates,
            reference,
            config,
            calibration_end=date(2021, 12, 29),
            confirmation_start=date(2022, 1, 4),
        )


def test_split_outputs_are_deterministic_and_tamper_checked(tmp_path: Path) -> None:
    returns, rates, reference, config = _inputs()
    result = build_split_evaluation(
        returns,
        rates,
        reference,
        config,
        calibration_end=date(2021, 12, 31),
        confirmation_start=date(2022, 1, 4),
    )

    first = write_split_evaluation(result, tmp_path / "first")
    second = write_split_evaluation(result, tmp_path / "second")
    repeated = write_split_evaluation(result, tmp_path / "first")
    for key in first:
        assert first[key].read_bytes() == second[key].read_bytes()
        assert first[key].read_bytes() == repeated[key].read_bytes()

    loaded = load_split_evaluation(tmp_path / "first")
    pd.testing.assert_frame_equal(loaded.metrics, result.metrics)
    pd.testing.assert_frame_equal(loaded.equity_curves, result.equity_curves)

    first["metrics"].write_bytes(first["metrics"].read_bytes() + b"\n")
    with pytest.raises(ValueError, match="checksum mismatch"):
        load_split_evaluation(tmp_path / "first")


def test_each_restarted_period_has_its_own_opening_cost_and_high_water_mark() -> None:
    returns, rates, reference, config = _inputs()
    config = replace(config, fee_schedule=FeeSchedule(minimum_per_trade=100.0))
    result = build_split_evaluation(returns, rates, reference, config)
    factor = result.metrics.query("strategy == 'factor_portfolio' and target_leverage == 1.0")
    assert set(factor["period"]) == {"calibration", "confirmation"}
    for row in factor.to_dict(orient="records"):
        assert row["opening_transaction_cost_usd"] == pytest.approx(400.0)
        assert row["maximum_drawdown"] == pytest.approx(-400.0 / config.initial_equity_usd)
        assert row["ongoing_maximum_drawdown"] == 0.0
    assert result.manifest["periods"]["confirmation"]["calendar"]["return_observations"] == 1


@pytest.mark.parametrize("capital", [15_000.0, 42_000.0])
def test_split_manifest_and_periods_use_configured_capital(capital: float) -> None:
    returns, rates, reference, config = _inputs()
    config = replace(config, initial_equity_usd=capital)
    result = build_split_evaluation(returns, rates, reference, config)
    assert f"USD {capital:,.2f}," in result.manifest["initialisation_policy"]
    assert (result.metrics["initial_committed_capital_usd"] == capital).all()
    first_rows = result.equity_curves.groupby("period", sort=False).first()
    for period in ("calibration", "confirmation"):
        assert first_rows.loc[period, "factor_1.25x"] == pytest.approx(capital)
        assert first_rows.loc[period, "core_1.25x"] == pytest.approx(capital)
