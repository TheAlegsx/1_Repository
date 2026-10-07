from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from factor_portfolio import FeeSchedule, PortfolioConfig
from factor_portfolio.dimensional import (
    build_three_way_comparison,
    load_three_way_comparison,
    write_three_way_comparison,
)


TARGETS = {"core": 0.60, "momentum": 0.15, "quality": 0.15, "value": 0.10}


def _rates(index: pd.DatetimeIndex, value: float, name: str) -> pd.Series:
    calendar = pd.date_range(index[0], index[-1], freq="D", name="date")
    return pd.Series(value, index=calendar, name=name)


def _config() -> PortfolioConfig:
    return PortfolioConfig(
        target_weights=TARGETS,
        initial_equity_usd=10_000.0,
        target_leverage=1.25,
        sleeve_band=0.05,
        leverage_band=0.10,
        fee_schedule=FeeSchedule(),
    )


def _inputs() -> tuple[pd.DataFrame, pd.Series]:
    etf_index = pd.to_datetime(
        ["2025-01-02", "2025-01-03", "2025-01-06", "2025-01-07"]
    )
    etf_nav = pd.DataFrame(
        {
            "core": [100.0, 110.0, 121.0, 133.1],
            "momentum": [100.0, 110.0, 121.0, 133.1],
            "quality": [100.0, 110.0, 121.0, 133.1],
            "value": [100.0, 110.0, 121.0, 133.1],
        },
        index=etf_index,
    )
    dimensional = pd.Series(
        [10.0, 12.1, 13.31],
        index=pd.to_datetime(["2025-01-02", "2025-01-06", "2025-01-07"]),
        name="dimensional",
    )
    return etf_nav, dimensional


def test_comparison_aligns_levels_before_calculating_returns() -> None:
    etf_nav, dimensional = _inputs()
    common = etf_nav.index.intersection(dimensional.index)
    comparison = build_three_way_comparison(
        etf_nav,
        dimensional,
        _rates(common, 0.0, "borrow_rate_annual"),
        _rates(common, 0.0, "reference_rate_annual"),
        _config(),
        leverage_levels=(1.0,),
    )

    metrics = comparison.metrics.set_index("strategy")
    assert comparison.equity_curves.index.tolist() == common.tolist()
    assert metrics.loc["msci_world", "ending_equity_usd"] == pytest.approx(
        10_000.0 * 1.331
    )
    assert metrics.loc["factor_portfolio", "ending_equity_usd"] == pytest.approx(
        10_000.0 * 1.331
    )
    assert metrics.loc[
        "dimensional_global_core", "ending_equity_usd"
    ] == pytest.approx(10_000.0 * 1.331)
    assert metrics.loc["msci_world", "beta_vs_same_leverage_msci_world"] == pytest.approx(
        1.0
    )


def test_comparison_supports_unlevered_and_one_point_two_five() -> None:
    etf_nav, dimensional = _inputs()
    common = etf_nav.index.intersection(dimensional.index)
    comparison = build_three_way_comparison(
        etf_nav,
        dimensional,
        _rates(common, 0.04, "borrow_rate_annual"),
        _rates(common, 0.01, "reference_rate_annual"),
        _config(),
        leverage_levels=(1.0, 1.25),
    )

    assert len(comparison.metrics) == 6
    assert set(comparison.metrics["target_leverage"]) == {1.0, 1.25}
    assert len(comparison.equity_curves.columns) == 6
    assert comparison.manifest["dimensional_isin"] == "IE00B2PC0153"
    assert "User confirmed" in comparison.manifest["dimensional_identity_status"]


def test_outputs_are_deterministic_and_tamper_checked(tmp_path: Path) -> None:
    etf_nav, dimensional = _inputs()
    common = etf_nav.index.intersection(dimensional.index)
    comparison = build_three_way_comparison(
        etf_nav,
        dimensional,
        _rates(common, 0.04, "borrow_rate_annual"),
        _rates(common, 0.01, "reference_rate_annual"),
        _config(),
        leverage_levels=(1.0, 1.25),
    )

    first = write_three_way_comparison(comparison, tmp_path / "first")
    second = write_three_way_comparison(comparison, tmp_path / "second")
    repeated = write_three_way_comparison(comparison, tmp_path / "first")
    for key in first:
        assert first[key].read_bytes() == second[key].read_bytes()
        assert first[key].read_bytes() == repeated[key].read_bytes()

    loaded = load_three_way_comparison(tmp_path / "first")
    pd.testing.assert_frame_equal(loaded.metrics, comparison.metrics)
    pd.testing.assert_frame_equal(loaded.equity_curves, comparison.equity_curves)

    first["equity"].write_bytes(first["equity"].read_bytes() + b"\n")
    with pytest.raises(ValueError, match="checksum mismatch"):
        load_three_way_comparison(tmp_path / "first")
