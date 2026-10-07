from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from factor_portfolio import FeeSchedule, PortfolioConfig
from factor_portfolio.grid import (
    BASELINE_WEIGHTS,
    build_calibration_grid,
    generate_predeclared_grid,
    load_calibration_grid,
    write_calibration_grid,
)


def _inputs() -> tuple[pd.DataFrame, pd.Series, pd.Series, PortfolioConfig]:
    index = pd.to_datetime(
        ["2021-12-29", "2021-12-31", "2022-01-04", "2022-01-05"]
    )
    returns = pd.DataFrame(
        {
            "core": [0.30, 0.01, 0.80, 0.02],
            "momentum": [0.30, 0.02, 0.80, 0.03],
            "quality": [0.30, 0.00, 0.80, 0.01],
            "value": [0.30, -0.01, 0.80, 0.02],
        },
        index=index,
    )
    calendar = pd.date_range(index[0], index[-1], freq="D", name="date")
    rates = pd.Series(0.04, index=calendar, name="borrow_rate_annual")
    reference = pd.Series(0.01, index=calendar, name="reference_rate_annual")
    config = PortfolioConfig(
        target_weights=BASELINE_WEIGHTS,
        fee_schedule=FeeSchedule(),
    )
    return returns, rates, reference, config


def test_predeclared_grid_has_exact_shape_and_one_baseline() -> None:
    scenarios = generate_predeclared_grid()

    assert len(scenarios) == 150
    assert scenarios[
        ["core_weight", "momentum_weight", "quality_weight", "value_weight"]
    ].drop_duplicates().shape[0] == 25
    assert set(scenarios["sleeve_band"]) == {0.03, 0.05}
    assert set(scenarios["leverage_band"]) == {0.05, 0.10, 0.15}
    assert scenarios["is_baseline"].sum() == 1
    weight_sums = scenarios[
        ["core_weight", "momentum_weight", "quality_weight", "value_weight"]
    ].sum(axis=1)
    assert ((weight_sums - 1.0).abs() < 1e-12).all()


def test_grid_excludes_returns_after_calibration_boundary() -> None:
    returns, rates, reference, config = _inputs()
    first = build_calibration_grid(
        returns,
        rates,
        reference,
        config,
        calibration_end=date(2021, 12, 31),
    )
    changed = returns.copy()
    changed.loc[changed.index > "2021-12-31", :] = -0.95
    second = build_calibration_grid(
        changed,
        rates,
        reference,
        config,
        calibration_end=date(2021, 12, 31),
    )

    pd.testing.assert_frame_equal(first.results, second.results)
    assert first.manifest["confirmation_data_used"] is False
    assert first.manifest["selection_data_end"] == "2021-12-31"


def test_grid_neighbour_diagnostics_are_bounded() -> None:
    returns, rates, reference, config = _inputs()
    result = build_calibration_grid(
        returns,
        rates,
        reference,
        config,
        calibration_end=date(2021, 12, 31),
    ).results

    assert (result["neighbour_count"] > 0).all()
    assert result["neighbour_positive_cagr_share"].between(0.0, 1.0).all()
    assert result["neighbour_joint_screen_share"].between(0.0, 1.0).all()


def test_grid_outputs_are_deterministic_and_tamper_checked(tmp_path: Path) -> None:
    returns, rates, reference, config = _inputs()
    result = build_calibration_grid(
        returns,
        rates,
        reference,
        config,
        calibration_end=date(2021, 12, 31),
    )

    first = write_calibration_grid(result, tmp_path / "first")
    second = write_calibration_grid(result, tmp_path / "second")
    repeated = write_calibration_grid(result, tmp_path / "first")
    for key in first:
        assert first[key].read_bytes() == second[key].read_bytes()
        assert first[key].read_bytes() == repeated[key].read_bytes()

    loaded = load_calibration_grid(tmp_path / "first")
    pd.testing.assert_frame_equal(loaded.scenarios, result.scenarios)
    assert loaded.results["scenario_id"].tolist() == result.results["scenario_id"].tolist()

    first["results"].write_bytes(first["results"].read_bytes() + b"\n")
    with pytest.raises(ValueError, match="checksum mismatch"):
        load_calibration_grid(tmp_path / "first")
