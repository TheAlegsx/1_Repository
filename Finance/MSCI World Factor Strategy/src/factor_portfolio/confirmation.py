"""Locked confirmation evaluation for calibration-selected scenarios.

The module cannot search or rank the full grid. It accepts only scenarios already
marked as robust in the checksum-verified calibration result.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Mapping

import pandas as pd

from .benchmark import (
    MEASUREMENT_POLICY_VERSION, calendar_metadata, measurement_policy, summarise_backtest,
)
from .config import PortfolioConfig
from .data import load_canonical_dataset
from .engine import run_backtest
from .evaluation import DEFAULT_CALIBRATION_END, DEFAULT_CONFIRMATION_START
from .grid import (
    BASELINE_WEIGHTS,
    REPRESENTATIVE_SCENARIO_ID,
    CalibrationGrid,
    load_calibration_grid,
)
from .rates import load_funding_dataset
from .result_io import continuous_result_columns, write_immutable_result_package


@dataclass(frozen=True)
class ConfirmationEvaluation:
    """Frozen-region confirmation metrics, summary, and provenance."""

    results: pd.DataFrame
    summary: pd.DataFrame
    manifest: dict[str, object]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def build_confirmation_evaluation(
    returns_usd: pd.DataFrame,
    annual_borrow_rate: pd.Series,
    annual_reference_rate: pd.Series,
    base_config: PortfolioConfig,
    calibration_grid: CalibrationGrid,
    *,
    input_provenance: Mapping[str, object] | None = None,
) -> ConfirmationEvaluation:
    """Evaluate only the frozen robust region in the confirmation window."""

    if calibration_grid.manifest.get("measurement_policy", {}).get("version") == MEASUREMENT_POLICY_VERSION:
        raise ValueError("use the original frozen selection, not the revised measurement grid")
    if calibration_grid.manifest.get("confirmation_data_used") is not False:
        raise ValueError("calibration selection must explicitly exclude confirmation data")
    if (
        calibration_grid.manifest.get("selection_data_end")
        != DEFAULT_CALIBRATION_END.isoformat()
    ):
        raise ValueError("calibration selection boundary differs from pre-declaration")
    required_columns = {
        "scenario_id",
        "core_weight",
        "momentum_weight",
        "quality_weight",
        "value_weight",
        "sleeve_band",
        "leverage_band",
        "robust_candidate",
    }
    if not required_columns.issubset(calibration_grid.results.columns):
        raise ValueError("calibration results are missing frozen-selection fields")
    selected = calibration_grid.results.loc[
        calibration_grid.results["robust_candidate"].astype(bool)
    ].copy()
    if selected.empty:
        raise ValueError("calibration grid contains no robust candidates")
    if selected["scenario_id"].duplicated().any():
        raise ValueError("robust calibration scenario IDs must be unique")
    if REPRESENTATIVE_SCENARIO_ID not in set(selected["scenario_id"]):
        raise ValueError("frozen representative is not in the robust calibration region")

    if returns_usd.empty or not isinstance(returns_usd.index, pd.DatetimeIndex):
        raise ValueError("returns_usd must have a non-empty DatetimeIndex")
    if returns_usd.index.has_duplicates or not returns_usd.index.is_monotonic_increasing:
        raise ValueError("returns_usd dates must be unique and sorted")
    if set(returns_usd.columns) != set(BASELINE_WEIGHTS):
        raise ValueError("returns_usd must contain exactly core, momentum, quality, and value")
    confirmation_start = pd.Timestamp(DEFAULT_CONFIRMATION_START)
    if confirmation_start not in returns_usd.index:
        raise ValueError("confirmation start must be a common ETF observation date")
    confirmation = returns_usd.loc[confirmation_start:].copy()
    if len(confirmation) < 2:
        raise ValueError("confirmation period must contain at least two observations")
    confirmation.iloc[0] = 0.0

    benchmark_metrics: dict[float, dict[str, float | int | str]] = {}
    benchmark_runs = {}
    for leverage_band in sorted(selected["leverage_band"].astype(float).unique()):
        benchmark_config = replace(
            base_config,
            target_weights={"core": 1.0},
            target_leverage=1.25,
            leverage_band=leverage_band,
        )
        benchmark = run_backtest(
            confirmation[["core"]], annual_borrow_rate, benchmark_config
        )
        benchmark_runs[leverage_band] = benchmark
        benchmark_metrics[leverage_band] = summarise_backtest(
            benchmark,
            strategy="core_benchmark",
            target_leverage=1.25,
            initial_equity_usd=base_config.initial_equity_usd,
            annual_reference_rate=annual_reference_rate,
            benchmark_result=benchmark,
            benchmark_initial_equity_usd=base_config.initial_equity_usd,
            day_count=base_config.day_count,
        )

    rows: list[dict[str, object]] = []
    for scenario in selected.sort_values("scenario_id").to_dict(orient="records"):
        target_weights = {
            asset: float(scenario[f"{asset}_weight"])
            for asset in BASELINE_WEIGHTS
        }
        config = replace(
            base_config,
            target_weights=target_weights,
            target_leverage=1.25,
            sleeve_band=float(scenario["sleeve_band"]),
            leverage_band=float(scenario["leverage_band"]),
        )
        factor = run_backtest(confirmation, annual_borrow_rate, config)
        factor_metrics = summarise_backtest(
            factor,
            strategy="factor_portfolio",
            target_leverage=1.25,
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
        rows.append(
            {
                "scenario_id": scenario["scenario_id"],
                **{key: value for key, value in factor_metrics.items() if key.startswith("ongoing_")},
                **{f"core_{key}": value for key, value in core_metrics.items() if key.startswith("ongoing_")},
                **{f"{asset}_weight": target_weights[asset] for asset in BASELINE_WEIGHTS},
                "sleeve_band": float(scenario["sleeve_band"]),
                "target_leverage": 1.25,
                "leverage_band": float(scenario["leverage_band"]),
                "is_representative": scenario["scenario_id"]
                == REPRESENTATIVE_SCENARIO_ID,
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
    results = pd.DataFrame(rows).sort_values("scenario_id", ignore_index=True)
    summary = pd.DataFrame(
        [
            {
                "selected_scenarios": int(len(results)),
                "positive_cagr_advantage_count": int(
                    results["positive_cagr_advantage"].sum()
                ),
                "non_worse_volatility_count": int(
                    results["non_worse_volatility"].sum()
                ),
                "non_worse_drawdown_count": int(results["non_worse_drawdown"].sum()),
                "joint_screen_count": int(results["passes_joint_screen"].sum()),
                "minimum_factor_minus_core_cagr": float(
                    results["factor_minus_core_cagr"].min()
                ),
                "median_factor_minus_core_cagr": float(
                    results["factor_minus_core_cagr"].median()
                ),
                "maximum_factor_minus_core_cagr": float(
                    results["factor_minus_core_cagr"].max()
                ),
                "minimum_sharpe_ratio": float(results["sharpe_ratio"].min()),
                "median_sharpe_ratio": float(results["sharpe_ratio"].median()),
                "maximum_sharpe_ratio": float(results["sharpe_ratio"].max()),
                "minimum_beta_vs_core": float(results["beta_vs_core"].min()),
                "median_beta_vs_core": float(results["beta_vs_core"].median()),
                "maximum_beta_vs_core": float(results["beta_vs_core"].max()),
                "minimum_annualised_alpha_vs_core": float(
                    results["annualised_alpha_vs_core"].min()
                ),
                "median_annualised_alpha_vs_core": float(
                    results["annualised_alpha_vs_core"].median()
                ),
                "maximum_annualised_alpha_vs_core": float(
                    results["annualised_alpha_vs_core"].max()
                ),
            }
        ]
    )
    manifest: dict[str, object] = {
        "schema_version": 2,
        "pipeline": "factor_portfolio.confirmation",
        "network_required": False,
        "selection_source": "checksum-verified calibration robust_candidate flags",
        "selection_data_end": DEFAULT_CALIBRATION_END.isoformat(),
        "confirmation_start": confirmation.index[0].date().isoformat(),
        "confirmation_end": confirmation.index[-1].date().isoformat(),
        "confirmation_observations": int(len(confirmation)),
        "calendar": calendar_metadata(confirmation.index),
        "measurement_policy": measurement_policy(),
        "selection_measurement_policy": calibration_grid.manifest.get(
            "measurement_policy", {"version": "historical_post_entry"}
        ),
        "first_return_policy": "set all ETF returns to zero for independent initialisation",
        "selected_scenario_ids": results["scenario_id"].tolist(),
        "selected_scenario_count": int(len(results)),
        "representative_scenario_id": REPRESENTATIVE_SCENARIO_ID,
        "representative_selection_rule": (
            "smallest robust change from the original baseline while retaining the "
            "original sleeve and leverage bands"
        ),
        "retuning_permitted": False,
        "interpretation_rule": (
            "report the frozen region and representative as confirmation diagnostics; "
            "do not use these results to replace or retune the selection"
        ),
        "risk_metrics": (
            "Sharpe uses New York Fed reference rate without broker spread; alpha and "
            "beta use daily excess returns versus equal-leverage Core"
        ),
        "release_status": "private derived research results; do not publish",
        "input_provenance": dict(input_provenance or {}),
    }
    return ConfirmationEvaluation(results=results, summary=summary, manifest=manifest)


def write_confirmation_evaluation(
    evaluation: ConfirmationEvaluation, output_dir: str | Path
) -> dict[str, Path]:
    """Write immutable private confirmation outputs and checksums."""

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    paths = {
        "results": destination / "confirmation_results.csv",
        "summary": destination / "confirmation_summary.csv",
        "manifest": destination / "confirmation_manifest.json",
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
        paths["results"]: csv_bytes(evaluation.results),
        paths["summary"]: csv_bytes(evaluation.summary),
    }
    manifest = dict(evaluation.manifest)
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
            paths["results"]: continuous_result_columns(evaluation.results),
            paths["summary"]: continuous_result_columns(evaluation.summary),
        },
    )
    return paths


def load_confirmation_evaluation(input_dir: str | Path) -> ConfirmationEvaluation:
    """Load confirmation outputs only after checksum and selection verification."""

    source = Path(input_dir)
    manifest_path = source / "confirmation_manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(manifest_path)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError("confirmation manifest is not valid JSON") from exc
    if manifest.get("retuning_permitted") is not False:
        raise ValueError("confirmation manifest does not prohibit retuning")
    filenames = {
        "results": "confirmation_results.csv",
        "summary": "confirmation_summary.csv",
    }
    records = manifest.get("result_files")
    if not isinstance(records, dict):
        raise ValueError("confirmation manifest is missing result_files")
    for filename in filenames.values():
        record = records.get(filename)
        if not isinstance(record, dict) or not isinstance(record.get("sha256"), str):
            raise ValueError(f"confirmation manifest is missing checksum for {filename}")
        path = source / filename
        if not path.is_file():
            raise FileNotFoundError(path)
        if _sha256(path) != record["sha256"]:
            raise ValueError(f"confirmation checksum mismatch for {filename}")
    results = pd.read_csv(source / filenames["results"])
    summary = pd.read_csv(source / filenames["summary"])
    for filename, frame in ((filenames["results"], results), (filenames["summary"], summary)):
        if len(frame) != records[filename].get("rows"):
            raise ValueError(f"confirmation row count differs for {filename}")
    if results["scenario_id"].tolist() != manifest.get("selected_scenario_ids"):
        raise ValueError("confirmation scenario IDs differ from manifest")
    if int(results["is_representative"].sum()) != 1:
        raise ValueError("confirmation results must contain one representative")
    return ConfirmationEvaluation(results=results, summary=summary, manifest=manifest)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate the frozen robust calibration region on confirmation."
    )
    parser.add_argument("--canonical-dir", type=Path, default=Path("data/canonical"))
    parser.add_argument(
        "--grid-dir",
        type=Path,
        default=Path("results/calibration_grid_risk_metrics"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("results/confirmation_a2_b1"),
    )
    args = parser.parse_args(argv)

    market = load_canonical_dataset(args.canonical_dir)
    funding = load_funding_dataset(args.canonical_dir)
    grid = load_calibration_grid(args.grid_dir)
    config = PortfolioConfig(target_weights=BASELINE_WEIGHTS)
    evaluation = build_confirmation_evaluation(
        market.returns_usd,
        funding.daily_borrow_rates["borrow_rate_annual"],
        funding.daily_borrow_rates["reference_rate_annual"],
        config,
        grid,
        input_provenance={
            "etf_canonical_files": market.manifest.get("canonical_files", {}),
            "funding_canonical_files": funding.manifest.get("canonical_files", {}),
            "calibration_grid_files": grid.manifest.get("result_files", {}),
        },
    )
    paths = write_confirmation_evaluation(evaluation, args.output_dir)
    print(
        f"Evaluated {len(evaluation.results)} frozen scenarios from "
        f"{evaluation.manifest['confirmation_start']} through "
        f"{evaluation.manifest['confirmation_end']}; retuning is prohibited."
    )
    for label, path in paths.items():
        print(f"{label}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
