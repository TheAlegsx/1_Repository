from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from factor_portfolio import FeeSchedule, PortfolioConfig
from factor_portfolio.benchmark import MEASUREMENT_POLICY_VERSION
from factor_portfolio.confirmation import (
    build_confirmation_evaluation,
    load_confirmation_evaluation,
    write_confirmation_evaluation,
)
from factor_portfolio.grid import (
    BASELINE_WEIGHTS,
    REPRESENTATIVE_SCENARIO_ID,
    CalibrationGrid,
    generate_predeclared_grid,
)


def _selection() -> CalibrationGrid:
    scenarios = generate_predeclared_grid()
    results = scenarios.copy()
    results["robust_candidate"] = results["scenario_id"].isin(
        [REPRESENTATIVE_SCENARIO_ID, "W07-SB05-LB10"]
    )
    return CalibrationGrid(
        scenarios=scenarios,
        results=results,
        manifest={
            "confirmation_data_used": False,
            "selection_data_end": "2021-12-31",
        },
    )


def _inputs() -> tuple[pd.DataFrame, pd.Series, pd.Series, PortfolioConfig]:
    index = pd.to_datetime(
        ["2021-12-31", "2022-01-04", "2022-01-05", "2022-01-06"]
    )
    returns = pd.DataFrame(
        {
            "core": [0.40, 0.80, 0.01, -0.01],
            "momentum": [0.40, 0.80, 0.02, -0.01],
            "quality": [0.40, 0.80, 0.01, 0.00],
            "value": [0.40, 0.80, 0.00, -0.02],
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


def test_confirmation_uses_only_frozen_robust_ids_and_zeroes_first_return() -> None:
    returns, rates, reference, config = _inputs()
    first = build_confirmation_evaluation(
        returns, rates, reference, config, _selection()
    )
    changed = returns.copy()
    changed.loc[pd.Timestamp("2021-12-31"), :] = -0.95
    changed.loc[pd.Timestamp("2022-01-04"), :] = -0.95
    second = build_confirmation_evaluation(
        changed, rates, reference, config, _selection()
    )

    assert first.results["scenario_id"].tolist() == [
        "W07-SB05-LB10",
        REPRESENTATIVE_SCENARIO_ID,
    ]
    pd.testing.assert_frame_equal(first.results, second.results)
    assert first.manifest["retuning_permitted"] is False
    assert first.manifest["confirmation_start"] == "2022-01-04"


def test_confirmation_rejects_unfrozen_or_missing_representative() -> None:
    returns, rates, reference, config = _inputs()
    selection = _selection()
    selection.results.loc[:, "robust_candidate"] = False

    with pytest.raises(ValueError, match="no robust candidates"):
        build_confirmation_evaluation(returns, rates, reference, config, selection)


def test_confirmation_outputs_are_deterministic_and_tamper_checked(
    tmp_path: Path,
) -> None:
    returns, rates, reference, config = _inputs()
    result = build_confirmation_evaluation(
        returns, rates, reference, config, _selection()
    )

    first = write_confirmation_evaluation(result, tmp_path / "first")
    second = write_confirmation_evaluation(result, tmp_path / "second")
    repeated = write_confirmation_evaluation(result, tmp_path / "first")
    for key in first:
        assert first[key].read_bytes() == second[key].read_bytes()
        assert first[key].read_bytes() == repeated[key].read_bytes()

    loaded = load_confirmation_evaluation(tmp_path / "first")
    assert loaded.results["scenario_id"].tolist() == result.results["scenario_id"].tolist()

    first["summary"].write_bytes(first["summary"].read_bytes() + b"\n")
    with pytest.raises(ValueError, match="checksum mismatch"):
        load_confirmation_evaluation(tmp_path / "first")


def test_revised_measurement_grid_cannot_reselect_confirmation_region() -> None:
    returns, rates, reference, config = _inputs()
    selection = _selection()
    selection.manifest["measurement_policy"] = {"version": MEASUREMENT_POLICY_VERSION}
    with pytest.raises(ValueError, match="original frozen selection"):
        build_confirmation_evaluation(returns, rates, reference, config, selection)
