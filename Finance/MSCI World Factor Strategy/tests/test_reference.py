from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from factor_portfolio import FeeSchedule, PortfolioConfig
from factor_portfolio.market_data import MarketDataset
from factor_portfolio.reference import (
    build_investable_reference_comparison,
    load_investable_reference_comparison,
    write_investable_reference_comparison,
)


TARGETS = {"core": 0.60, "momentum": 0.15, "quality": 0.10, "value": 0.15}


def _inputs() -> tuple[pd.DataFrame, pd.Series, MarketDataset, PortfolioConfig]:
    dates = pd.to_datetime(
        ["2025-09-30", "2025-10-01", "2025-10-02", "2025-10-03"]
    )
    returns = pd.DataFrame(
        {
            "core": [0.0, 0.01, -0.01, 0.02],
            "momentum": [0.0, 0.02, -0.01, 0.03],
            "quality": [0.0, 0.00, 0.01, 0.01],
            "value": [0.0, -0.01, 0.02, 0.02],
        },
        index=dates,
    )
    calendar = pd.date_range(dates[0], dates[-1], freq="D", name="date")
    rates = pd.Series(0.04, index=calendar, name="borrow_rate_annual")
    overlap_dates = pd.to_datetime(["2025-09-30", "2025-10-01", "2025-10-03"])
    overlap = pd.DataFrame(
        {
            "mxwoldnu_index_level_usd": [100.0, 102.0, 104.0],
            "amundi_2x_nav_usd": [5.0, 5.1, 5.2],
        },
        index=overlap_dates,
    )
    overlap.index.name = "date"
    vendor = MarketDataset(
        listing_quotes=pd.DataFrame(),
        spread_calibration=pd.DataFrame(),
        mxwoldnu_index=overlap[["mxwoldnu_index_level_usd"]],
        amundi_nav=overlap[["amundi_2x_nav_usd"]],
        benchmark_overlap=overlap,
        manifest={},
    )
    config = PortfolioConfig(target_weights=TARGETS, fee_schedule=FeeSchedule())
    return returns, rates, vendor, config


def test_reference_uses_three_way_intersection_and_normalizes_levels() -> None:
    returns, rates, vendor, config = _inputs()

    comparison = build_investable_reference_comparison(
        returns, rates, vendor, config
    )

    assert len(comparison.levels) == 3
    assert comparison.levels.index.tolist() == vendor.benchmark_overlap.index.tolist()
    normalized = comparison.levels.filter(like="normalized_")
    assert (normalized.iloc[0] == 1.0).all()
    assert set(comparison.metrics["strategy"]) == {
        "core_banded_2x",
        "amundi_2x_etf",
        "mxwoldnu_2x_index",
    }
    index_row = comparison.metrics.set_index("strategy").loc["mxwoldnu_2x_index"]
    assert index_row["daily_correlation_with_index"] == pytest.approx(1.0)
    assert index_row["annualised_tracking_error_vs_index"] == pytest.approx(0.0)


def test_reference_outputs_are_deterministic_and_tamper_checked(tmp_path: Path) -> None:
    returns, rates, vendor, config = _inputs()
    comparison = build_investable_reference_comparison(
        returns, rates, vendor, config
    )

    first = write_investable_reference_comparison(comparison, tmp_path / "first")
    second = write_investable_reference_comparison(comparison, tmp_path / "second")
    repeated = write_investable_reference_comparison(comparison, tmp_path / "first")
    for key in first:
        assert first[key].read_bytes() == second[key].read_bytes()
        assert first[key].read_bytes() == repeated[key].read_bytes()

    loaded = load_investable_reference_comparison(tmp_path / "first")
    pd.testing.assert_frame_equal(loaded.levels, comparison.levels)
    pd.testing.assert_frame_equal(loaded.metrics, comparison.metrics)

    first["levels"].write_bytes(first["levels"].read_bytes() + b"\n")
    with pytest.raises(ValueError, match="checksum mismatch"):
        load_investable_reference_comparison(tmp_path / "first")
