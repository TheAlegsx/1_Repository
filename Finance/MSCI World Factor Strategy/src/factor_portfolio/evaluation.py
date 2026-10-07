"""Pre-declared calibration and confirmation-period comparison."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Mapping

import pandas as pd

from .benchmark import (
    DEFAULT_LEVERAGE_LEVELS, build_same_leverage_comparison,
    calendar_metadata, measurement_policy,
)
from .config import PortfolioConfig
from .data import load_canonical_dataset
from .rates import load_funding_dataset
from .result_io import continuous_result_columns, write_immutable_result_package


DEFAULT_CALIBRATION_END = date(2021, 12, 31)
DEFAULT_CONFIRMATION_START = date(2022, 1, 4)


@dataclass(frozen=True)
class SplitEvaluation:
    metrics: pd.DataFrame
    relative_metrics: pd.DataFrame
    equity_curves: pd.DataFrame
    manifest: dict[str, object]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def build_split_evaluation(
    returns_usd: pd.DataFrame,
    annual_borrow_rate: pd.Series,
    annual_reference_rate: pd.Series,
    base_config: PortfolioConfig,
    *,
    calibration_end: date = DEFAULT_CALIBRATION_END,
    confirmation_start: date = DEFAULT_CONFIRMATION_START,
    input_provenance: Mapping[str, object] | None = None,
) -> SplitEvaluation:
    """Run independent equal-leverage comparisons in two adjacent data windows."""

    if returns_usd.empty or not isinstance(returns_usd.index, pd.DatetimeIndex):
        raise ValueError("returns_usd must have a non-empty DatetimeIndex")
    if returns_usd.index.has_duplicates or not returns_usd.index.is_monotonic_increasing:
        raise ValueError("returns_usd dates must be unique and sorted")
    calibration_end_ts = pd.Timestamp(calibration_end)
    confirmation_start_ts = pd.Timestamp(confirmation_start)
    if calibration_end_ts not in returns_usd.index:
        raise ValueError("calibration_end must be a common ETF observation date")
    if confirmation_start_ts not in returns_usd.index:
        raise ValueError("confirmation_start must be a common ETF observation date")
    calibration_position = returns_usd.index.get_loc(calibration_end_ts)
    if calibration_position + 1 >= len(returns_usd.index):
        raise ValueError("calibration period leaves no confirmation observations")
    if returns_usd.index[calibration_position + 1] != confirmation_start_ts:
        raise ValueError(
            "confirmation_start must be the first common observation after calibration_end"
        )

    period_frames = {
        "calibration": returns_usd.loc[:calibration_end_ts].copy(),
        "confirmation": returns_usd.loc[confirmation_start_ts:].copy(),
    }
    metric_frames: list[pd.DataFrame] = []
    relative_frames: list[pd.DataFrame] = []
    equity_frames: list[pd.DataFrame] = []
    period_manifest: dict[str, object] = {}
    for period, frame in period_frames.items():
        if len(frame) < 2:
            raise ValueError(f"{period} period must contain at least two observations")
        frame.iloc[0] = 0.0
        comparison = build_same_leverage_comparison(
            frame,
            annual_borrow_rate,
            annual_reference_rate,
            base_config,
            leverage_levels=DEFAULT_LEVERAGE_LEVELS,
        )
        metrics = comparison.metrics.copy()
        metrics.insert(0, "period", period)
        relative = comparison.relative_metrics.copy()
        relative.insert(0, "period", period)
        equity = comparison.equity_curves.reset_index()
        equity.insert(0, "period", period)
        metric_frames.append(metrics)
        relative_frames.append(relative)
        equity_frames.append(equity)
        period_manifest[period] = {
            "start_date": frame.index[0].date().isoformat(),
            "end_date": frame.index[-1].date().isoformat(),
            "observations": int(len(frame)),
            "calendar": calendar_metadata(frame.index),
            "first_return_policy": "set all ETF returns to zero for independent initialisation",
        }

    metrics = pd.concat(metric_frames, ignore_index=True)
    relative_metrics = pd.concat(relative_frames, ignore_index=True)
    equity_curves = pd.concat(equity_frames, ignore_index=True)
    manifest: dict[str, object] = {
        "schema_version": 2,
        "pipeline": "factor_portfolio.evaluation",
        "network_required": False,
        "periods": period_manifest,
        "measurement_policy": measurement_policy(),
        "split_rule": (
            "calibration ends 2021-12-31; confirmation begins on the next common "
            "ETF observation, 2022-01-04"
        ),
        "initialisation_policy": (
            f"each period starts independently with USD {base_config.initial_equity_usd:,.2f}, target weights, target "
            "leverage, opening costs, and zero first-row returns"
        ),
        "contamination_status": (
            "confirmation is not an untouched out-of-sample test because full-sample "
            "results were viewed before the split was declared"
        ),
        "future_use_rule": (
            "use calibration for future grid selection; do not use confirmation to "
            "select weights, bands, or leverage"
        ),
        "risk_metrics": (
            "Sharpe uses New York Fed reference rate without broker spread; alpha and "
            "beta use daily excess returns versus equal-leverage Core"
        ),
        "target_leverage_levels": list(DEFAULT_LEVERAGE_LEVELS),
        "release_status": "private derived research results; do not publish",
        "input_provenance": dict(input_provenance or {}),
    }
    return SplitEvaluation(metrics, relative_metrics, equity_curves, manifest)


def write_split_evaluation(
    evaluation: SplitEvaluation, output_dir: str | Path
) -> dict[str, Path]:
    """Write immutable private period results and their checksums."""

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    paths = {
        "metrics": destination / "period_metrics.csv",
        "relative": destination / "period_factor_minus_core_metrics.csv",
        "equity": destination / "period_equity_curves.csv",
        "manifest": destination / "evaluation_manifest.json",
    }

    def csv_bytes(frame: pd.DataFrame) -> bytes:
        buffer = io.StringIO(newline="")
        frame.to_csv(
            buffer,
            index=False,
            date_format="%Y-%m-%d",
            float_format="%.12f",
            lineterminator="\n",
        )
        return buffer.getvalue().encode("utf-8")

    payloads = {
        paths["metrics"]: csv_bytes(evaluation.metrics),
        paths["relative"]: csv_bytes(evaluation.relative_metrics),
        paths["equity"]: csv_bytes(evaluation.equity_curves),
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
            paths["metrics"]: continuous_result_columns(evaluation.metrics),
            paths["relative"]: continuous_result_columns(evaluation.relative_metrics),
            paths["equity"]: continuous_result_columns(evaluation.equity_curves, levels=True),
        },
    )
    return paths


def load_split_evaluation(input_dir: str | Path) -> SplitEvaluation:
    """Load private period outputs only after checksum and row verification."""

    source = Path(input_dir)
    manifest_path = source / "evaluation_manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(manifest_path)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError("evaluation manifest is not valid JSON") from exc
    filenames = {
        "metrics": "period_metrics.csv",
        "relative": "period_factor_minus_core_metrics.csv",
        "equity": "period_equity_curves.csv",
    }
    records = manifest.get("result_files")
    if not isinstance(records, dict):
        raise ValueError("evaluation manifest is missing result_files")
    for filename in filenames.values():
        record = records.get(filename)
        if not isinstance(record, dict) or not isinstance(record.get("sha256"), str):
            raise ValueError(f"evaluation manifest is missing checksum for {filename}")
        path = source / filename
        if not path.is_file():
            raise FileNotFoundError(path)
        if _sha256(path) != record["sha256"]:
            raise ValueError(f"evaluation checksum mismatch for {filename}")
    metrics = pd.read_csv(source / filenames["metrics"])
    relative = pd.read_csv(source / filenames["relative"])
    equity = pd.read_csv(source / filenames["equity"], parse_dates=["date"])
    for filename, frame in (
        (filenames["metrics"], metrics),
        (filenames["relative"], relative),
        (filenames["equity"], equity),
    ):
        if len(frame) != records[filename].get("rows"):
            raise ValueError(f"evaluation row count differs for {filename}")
    if set(equity["period"]) != {"calibration", "confirmation"}:
        raise ValueError("evaluation equity file has unexpected periods")
    for period, frame in equity.groupby("period", sort=False):
        dates = pd.DatetimeIndex(frame["date"])
        if dates.has_duplicates or not dates.is_monotonic_increasing:
            raise ValueError(f"{period} equity dates must be unique and sorted")
        expected = manifest["periods"][period]
        if dates[0].date().isoformat() != expected["start_date"]:
            raise ValueError(f"{period} start date differs from manifest")
        if dates[-1].date().isoformat() != expected["end_date"]:
            raise ValueError(f"{period} end date differs from manifest")
    return SplitEvaluation(metrics, relative, equity, manifest)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the private calibration/confirmation comparison."
    )
    parser.add_argument("--canonical-dir", type=Path, default=Path("data/canonical"))
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("results/evaluation_split_a2_b1"),
    )
    args = parser.parse_args(argv)

    market = load_canonical_dataset(args.canonical_dir)
    funding = load_funding_dataset(args.canonical_dir)
    config = PortfolioConfig(
        target_weights={
            "core": 0.60,
            "momentum": 0.15,
            "quality": 0.10,
            "value": 0.15,
        }
    )
    evaluation = build_split_evaluation(
        market.returns_usd,
        funding.daily_borrow_rates["borrow_rate_annual"],
        funding.daily_borrow_rates["reference_rate_annual"],
        config,
        input_provenance={
            "etf_canonical_files": market.manifest.get("canonical_files", {}),
            "funding_canonical_files": funding.manifest.get("canonical_files", {}),
        },
    )
    paths = write_split_evaluation(evaluation, args.output_dir)
    periods = evaluation.manifest["periods"]
    print(
        "Built calibration "
        f"{periods['calibration']['start_date']}–{periods['calibration']['end_date']} "
        "and confirmation "
        f"{periods['confirmation']['start_date']}–{periods['confirmation']['end_date']}."
    )
    for label, path in paths.items():
        print(f"{label}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
