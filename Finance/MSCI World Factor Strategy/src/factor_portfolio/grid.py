"""Pre-declared calibration-only parameter grid.

This module deliberately has no confirmation-period path. Its input is truncated at
the fixed calibration boundary before any scenario is simulated or ranked.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
from dataclasses import dataclass, replace
from datetime import date
from itertools import product
from pathlib import Path
from typing import Mapping

import numpy as np
import pandas as pd

from .benchmark import calendar_metadata, measurement_policy, summarise_backtest
from .config import PortfolioConfig
from .data import load_canonical_dataset
from .engine import run_backtest
from .evaluation import DEFAULT_CALIBRATION_END
from .rates import load_funding_dataset
from .result_io import continuous_result_columns, write_immutable_result_package


CORE_WEIGHTS = (0.50, 0.55, 0.60, 0.65, 0.70)
MOMENTUM_WEIGHTS = (0.10, 0.15, 0.20)
VALUE_WEIGHTS = (0.10, 0.15, 0.20)
QUALITY_WEIGHTS = (0.05, 0.10, 0.15)
SLEEVE_BANDS = (0.03, 0.05)
LEVERAGE_BANDS = (0.05, 0.10, 0.15)
TARGET_LEVERAGE = 1.25
ROBUST_NEIGHBOUR_SHARE = 0.60
REPRESENTATIVE_SCENARIO_ID = "W12-SB05-LB10"
BASELINE_WEIGHTS = {
    "core": 0.60,
    "momentum": 0.15,
    "quality": 0.10,
    "value": 0.15,
}


@dataclass(frozen=True)
class CalibrationGrid:
    """Scenario definitions, calibration results, and provenance."""

    scenarios: pd.DataFrame
    results: pd.DataFrame
    manifest: dict[str, object]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def generate_predeclared_grid() -> pd.DataFrame:
    """Return the fixed 150-scenario grid in deterministic order."""

    weights: list[dict[str, float | str]] = []
    for core, momentum, value in product(
        CORE_WEIGHTS, MOMENTUM_WEIGHTS, VALUE_WEIGHTS
    ):
        quality = round(1.0 - core - momentum - value, 2)
        if quality not in QUALITY_WEIGHTS:
            continue
        weights.append(
            {
                "core_weight": core,
                "momentum_weight": momentum,
                "quality_weight": quality,
                "value_weight": value,
            }
        )
    if len(weights) != 25:
        raise AssertionError("pre-declared weight grid must contain 25 allocations")

    rows: list[dict[str, float | bool | str]] = []
    for weight_number, allocation in enumerate(weights, start=1):
        for sleeve_band, leverage_band in product(SLEEVE_BANDS, LEVERAGE_BANDS):
            scenario_id = (
                f"W{weight_number:02d}-SB{int(sleeve_band * 100):02d}"
                f"-LB{int(leverage_band * 100):02d}"
            )
            is_baseline = (
                all(
                    np.isclose(allocation[f"{asset}_weight"], target)
                    for asset, target in BASELINE_WEIGHTS.items()
                )
                and np.isclose(sleeve_band, 0.05)
                and np.isclose(leverage_band, 0.10)
            )
            rows.append(
                {
                    "scenario_id": scenario_id,
                    **allocation,
                    "sleeve_band": sleeve_band,
                    "target_leverage": TARGET_LEVERAGE,
                    "leverage_band": leverage_band,
                    "is_baseline": is_baseline,
                }
            )
    frame = pd.DataFrame(rows)
    if len(frame) != 150 or int(frame["is_baseline"].sum()) != 1:
        raise AssertionError("pre-declared grid must contain 150 scenarios and one baseline")
    return frame


def _are_neighbours(left: pd.Series, right: pd.Series) -> bool:
    weight_columns = [
        "core_weight",
        "momentum_weight",
        "quality_weight",
        "value_weight",
    ]
    same_weights = all(
        np.isclose(left[column], right[column]) for column in weight_columns
    )
    same_sleeve = np.isclose(left["sleeve_band"], right["sleeve_band"])
    same_leverage = np.isclose(left["leverage_band"], right["leverage_band"])
    if same_weights:
        sleeve_step = not same_sleeve and same_leverage
        leverage_step = same_sleeve and (
            abs(float(left["leverage_band"]) - float(right["leverage_band"]))
            <= 0.050000000001
        )
        return bool(sleeve_step or leverage_step)
    if not (same_sleeve and same_leverage):
        return False
    distance = sum(
        abs(float(left[column]) - float(right[column])) for column in weight_columns
    )
    return bool(np.isclose(distance, 0.10))


def _add_neighbourhood_diagnostics(results: pd.DataFrame) -> pd.DataFrame:
    enriched = results.copy()
    neighbour_counts: list[int] = []
    positive_shares: list[float] = []
    joint_shares: list[float] = []
    for _, scenario in enriched.iterrows():
        mask = enriched.apply(lambda candidate: _are_neighbours(scenario, candidate), axis=1)
        neighbours = enriched.loc[mask]
        if neighbours.empty:
            raise AssertionError("every grid scenario must have at least one neighbour")
        neighbour_counts.append(int(len(neighbours)))
        positive_shares.append(float(neighbours["positive_cagr_advantage"].mean()))
        joint_shares.append(float(neighbours["passes_joint_screen"].mean()))
    enriched["neighbour_count"] = neighbour_counts
    enriched["neighbour_positive_cagr_share"] = positive_shares
    enriched["neighbour_joint_screen_share"] = joint_shares
    enriched["robust_candidate"] = (
        enriched["passes_joint_screen"]
        & (enriched["neighbour_joint_screen_share"] >= ROBUST_NEIGHBOUR_SHARE)
    )
    return enriched


def build_calibration_grid(
    returns_usd: pd.DataFrame,
    annual_borrow_rate: pd.Series,
    annual_reference_rate: pd.Series,
    base_config: PortfolioConfig,
    *,
    calibration_end: date = DEFAULT_CALIBRATION_END,
    input_provenance: Mapping[str, object] | None = None,
) -> CalibrationGrid:
    """Evaluate the fixed grid using calibration observations only."""

    if returns_usd.empty or not isinstance(returns_usd.index, pd.DatetimeIndex):
        raise ValueError("returns_usd must have a non-empty DatetimeIndex")
    if returns_usd.index.has_duplicates or not returns_usd.index.is_monotonic_increasing:
        raise ValueError("returns_usd dates must be unique and sorted")
    expected_assets = set(BASELINE_WEIGHTS)
    if set(returns_usd.columns) != expected_assets:
        raise ValueError("returns_usd must contain exactly core, momentum, quality, and value")
    calibration_end_ts = pd.Timestamp(calibration_end)
    if calibration_end_ts not in returns_usd.index:
        raise ValueError("calibration_end must be a common ETF observation date")
    calibration = returns_usd.loc[:calibration_end_ts].copy()
    if len(calibration) < 2:
        raise ValueError("calibration period must contain at least two observations")
    calibration.iloc[0] = 0.0

    scenarios = generate_predeclared_grid()
    benchmark_metrics: dict[float, dict[str, float | int | str]] = {}
    benchmark_runs = {}
    for leverage_band in LEVERAGE_BANDS:
        benchmark_config = replace(
            base_config,
            target_weights={"core": 1.0},
            target_leverage=TARGET_LEVERAGE,
            leverage_band=leverage_band,
        )
        benchmark = run_backtest(
            calibration[["core"]], annual_borrow_rate, benchmark_config
        )
        benchmark_runs[leverage_band] = benchmark
        benchmark_metrics[leverage_band] = summarise_backtest(
            benchmark,
            strategy="core_benchmark",
            target_leverage=TARGET_LEVERAGE,
            initial_equity_usd=base_config.initial_equity_usd,
            annual_reference_rate=annual_reference_rate,
            benchmark_result=benchmark,
            benchmark_initial_equity_usd=base_config.initial_equity_usd,
            day_count=base_config.day_count,
        )

    result_rows: list[dict[str, object]] = []
    for scenario in scenarios.to_dict(orient="records"):
        target_weights = {
            asset: float(scenario[f"{asset}_weight"])
            for asset in BASELINE_WEIGHTS
        }
        config = replace(
            base_config,
            target_weights=target_weights,
            target_leverage=TARGET_LEVERAGE,
            sleeve_band=float(scenario["sleeve_band"]),
            leverage_band=float(scenario["leverage_band"]),
        )
        factor = run_backtest(calibration, annual_borrow_rate, config)
        factor_metrics = summarise_backtest(
            factor,
            strategy="factor_portfolio",
            target_leverage=TARGET_LEVERAGE,
            initial_equity_usd=base_config.initial_equity_usd,
            annual_reference_rate=annual_reference_rate,
            benchmark_result=benchmark_runs[float(scenario["leverage_band"])],
            benchmark_initial_equity_usd=base_config.initial_equity_usd,
            day_count=base_config.day_count,
        )
        core_metrics = benchmark_metrics[float(scenario["leverage_band"])]
        cagr_difference = float(factor_metrics["cagr"]) - float(core_metrics["cagr"])
        volatility_difference = float(factor_metrics["annualised_volatility"]) - float(
            core_metrics["annualised_volatility"]
        )
        drawdown_difference = float(factor_metrics["maximum_drawdown"]) - float(
            core_metrics["maximum_drawdown"]
        )
        positive_cagr = cagr_difference > 0.0
        non_worse_volatility = volatility_difference <= 0.0
        non_worse_drawdown = drawdown_difference >= 0.0
        result_rows.append(
            {
                **scenario,
                **{key: value for key, value in factor_metrics.items() if key.startswith("ongoing_")},
                **{f"core_{key}": value for key, value in core_metrics.items() if key.startswith("ongoing_")},
                "ending_equity_usd": factor_metrics["ending_equity_usd"],
                "cagr": factor_metrics["cagr"],
                "annualised_volatility": factor_metrics["annualised_volatility"],
                "maximum_drawdown": factor_metrics["maximum_drawdown"],
                "sharpe_ratio": factor_metrics["sharpe_ratio"],
                "beta_vs_core": factor_metrics["beta_vs_core"],
                "annualised_alpha_vs_core": factor_metrics[
                    "annualised_alpha_vs_core"
                ],
                "cumulative_financing_cost_usd": factor_metrics[
                    "cumulative_financing_cost_usd"
                ],
                "cumulative_transaction_cost_usd": factor_metrics[
                    "cumulative_transaction_cost_usd"
                ],
                "post_initialisation_trade_events": factor_metrics[
                    "post_initialisation_trade_events"
                ],
                "minimum_leverage": factor_metrics["minimum_leverage"],
                "average_leverage": factor_metrics["average_leverage"],
                "maximum_leverage": factor_metrics["maximum_leverage"],
                "core_ending_equity_usd": core_metrics["ending_equity_usd"],
                "core_cagr": core_metrics["cagr"],
                "core_annualised_volatility": core_metrics[
                    "annualised_volatility"
                ],
                "core_maximum_drawdown": core_metrics["maximum_drawdown"],
                "core_sharpe_ratio": core_metrics["sharpe_ratio"],
                "core_beta_vs_core": core_metrics["beta_vs_core"],
                "core_annualised_alpha_vs_core": core_metrics[
                    "annualised_alpha_vs_core"
                ],
                "factor_minus_core_ending_equity_usd": float(
                    factor_metrics["ending_equity_usd"]
                )
                - float(core_metrics["ending_equity_usd"]),
                "factor_minus_core_cagr": cagr_difference,
                "factor_minus_core_annualised_volatility": volatility_difference,
                "factor_minus_core_maximum_drawdown": drawdown_difference,
                "factor_minus_core_sharpe_ratio": float(
                    factor_metrics["sharpe_ratio"]
                )
                - float(core_metrics["sharpe_ratio"]),
                "positive_cagr_advantage": positive_cagr,
                "non_worse_volatility": non_worse_volatility,
                "non_worse_drawdown": non_worse_drawdown,
                "passes_joint_screen": (
                    positive_cagr and non_worse_volatility and non_worse_drawdown
                ),
            }
        )
    results = _add_neighbourhood_diagnostics(pd.DataFrame(result_rows))
    results["calibration_cagr_rank"] = (
        results["cagr"].rank(method="min", ascending=False).astype(int)
    )
    results = results.sort_values("scenario_id", ignore_index=True)

    manifest: dict[str, object] = {
        "schema_version": 2,
        "pipeline": "factor_portfolio.grid",
        "network_required": False,
        "selection_data_start": calibration.index[0].date().isoformat(),
        "selection_data_end": calibration.index[-1].date().isoformat(),
        "selection_observations": int(len(calibration)),
        "calendar": calendar_metadata(calibration.index),
        "measurement_policy": measurement_policy(),
        "use_boundary": "measurement-convention diagnostics only; do not replace the historical frozen confirmation selection",
        "confirmation_data_used": False,
        "first_return_policy": "set all ETF returns to zero for independent initialisation",
        "target_leverage": TARGET_LEVERAGE,
        "core_weights": list(CORE_WEIGHTS),
        "momentum_weights": list(MOMENTUM_WEIGHTS),
        "value_weights": list(VALUE_WEIGHTS),
        "quality_weights": list(QUALITY_WEIGHTS),
        "quality_rule": "residual; only 0.05, 0.10, or 0.15 admitted",
        "sleeve_bands": list(SLEEVE_BANDS),
        "leverage_bands": list(LEVERAGE_BANDS),
        "weight_configurations": 25,
        "scenario_count": 150,
        "joint_screen": (
            "factor-minus-Core CAGR > 0; annualised-volatility difference <= 0; "
            "maximum-drawdown difference >= 0"
        ),
        "neighbour_rule": (
            "same bands plus one 5pp transfer between sleeves, or same weights plus "
            "one adjacent sleeve-band or leverage-band setting"
        ),
        "robust_candidate_rule": (
            "passes joint screen and at least 60% of direct neighbours also pass"
        ),
        "benchmark_rule": (
            "100% Core at 1.25x with the same leverage band, calendar, financing, "
            "execution timing, and fee schedule"
        ),
        "risk_metrics": (
            "Sharpe uses New York Fed reference rate without broker spread; alpha and "
            "beta use daily excess returns versus equal-leverage Core"
        ),
        "release_status": "private derived research results; do not publish",
        "input_provenance": dict(input_provenance or {}),
    }
    return CalibrationGrid(scenarios=scenarios, results=results, manifest=manifest)


def write_calibration_grid(
    grid: CalibrationGrid, output_dir: str | Path
) -> dict[str, Path]:
    """Write immutable private grid results and checksums."""

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    paths = {
        "scenarios": destination / "scenario_definitions.csv",
        "results": destination / "calibration_grid_results.csv",
        "manifest": destination / "grid_manifest.json",
    }

    def csv_bytes(frame: pd.DataFrame) -> bytes:
        buffer = io.StringIO(newline="")
        frame.to_csv(
            buffer,
            index=False,
            float_format="%.12f",
            lineterminator="\n",
        )
        return buffer.getvalue().encode("utf-8")

    payloads = {
        paths["scenarios"]: csv_bytes(grid.scenarios),
        paths["results"]: csv_bytes(grid.results),
    }
    manifest = dict(grid.manifest)
    manifest["result_files"] = {
        path.name: {"sha256": _sha256_bytes(payload), "rows": payload.count(b"\n") - 1}
        for path, payload in payloads.items()
    }
    payloads[paths["manifest"]] = (
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")
    write_immutable_result_package(
        payloads,
        manifest_path=paths["manifest"],
        continuous_columns={
            paths["results"]: continuous_result_columns(grid.results),
        },
    )
    return paths


def load_calibration_grid(input_dir: str | Path) -> CalibrationGrid:
    """Load private grid outputs only after checksum and boundary verification."""

    source = Path(input_dir)
    manifest_path = source / "grid_manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(manifest_path)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError("calibration-grid manifest is not valid JSON") from exc
    if manifest.get("confirmation_data_used") is not False:
        raise ValueError("calibration-grid manifest does not exclude confirmation data")
    if manifest.get("selection_data_end") != DEFAULT_CALIBRATION_END.isoformat():
        raise ValueError("calibration-grid selection boundary differs from pre-declaration")
    filenames = {
        "scenarios": "scenario_definitions.csv",
        "results": "calibration_grid_results.csv",
    }
    records = manifest.get("result_files")
    if not isinstance(records, dict):
        raise ValueError("calibration-grid manifest is missing result_files")
    for filename in filenames.values():
        record = records.get(filename)
        if not isinstance(record, dict) or not isinstance(record.get("sha256"), str):
            raise ValueError(f"calibration-grid manifest is missing checksum for {filename}")
        path = source / filename
        if not path.is_file():
            raise FileNotFoundError(path)
        if _sha256(path) != record["sha256"]:
            raise ValueError(f"calibration-grid checksum mismatch for {filename}")
    scenarios = pd.read_csv(source / filenames["scenarios"])
    results = pd.read_csv(source / filenames["results"])
    for filename, frame in (
        (filenames["scenarios"], scenarios),
        (filenames["results"], results),
    ):
        if len(frame) != records[filename].get("rows"):
            raise ValueError(f"calibration-grid row count differs for {filename}")
    if len(scenarios) != 150 or len(results) != 150:
        raise ValueError("calibration-grid files must each contain 150 scenarios")
    if scenarios["scenario_id"].tolist() != results["scenario_id"].tolist():
        raise ValueError("calibration-grid scenario ordering differs")
    return CalibrationGrid(scenarios=scenarios, results=results, manifest=manifest)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the private 150-scenario calibration-only grid."
    )
    parser.add_argument("--canonical-dir", type=Path, default=Path("data/canonical"))
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("results/calibration_grid_a2_b1"),
    )
    args = parser.parse_args(argv)

    market = load_canonical_dataset(args.canonical_dir)
    funding = load_funding_dataset(args.canonical_dir)
    config = PortfolioConfig(target_weights=BASELINE_WEIGHTS)
    grid = build_calibration_grid(
        market.returns_usd,
        funding.daily_borrow_rates["borrow_rate_annual"],
        funding.daily_borrow_rates["reference_rate_annual"],
        config,
        input_provenance={
            "etf_canonical_files": market.manifest.get("canonical_files", {}),
            "funding_canonical_files": funding.manifest.get("canonical_files", {}),
        },
    )
    paths = write_calibration_grid(grid, args.output_dir)
    print(
        f"Built {len(grid.results)} calibration scenarios through "
        f"{grid.manifest['selection_data_end']}; "
        f"robust candidates: {int(grid.results['robust_candidate'].sum())}."
    )
    for label, path in paths.items():
        print(f"{label}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
