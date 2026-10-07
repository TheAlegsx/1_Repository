"""Three-way comparison with the Dimensional Global Core Equity Fund series."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Iterable, Mapping

import numpy as np
import pandas as pd

from .benchmark import calendar_metadata, measurement_policy, summarise_backtest
from .config import PortfolioConfig
from .data import load_canonical_dataset
from .engine import run_backtest
from .market_data import BloombergSpec, read_bloomberg_hardcopy
from .rates import load_funding_dataset
from .result_io import continuous_result_columns, write_immutable_result_package


DIMENSIONAL_SECURITY = "DIMGCEA ID Equity"
DIMENSIONAL_ISIN = "IE00B2PC0153"
DIMENSIONAL_FILENAME = "DIMGCEA ID Equity grid_vwffhilo.xlsx"
DIMENSIONAL_LAST_DATE = date(2026, 8, 28)
DEFAULT_LEVERAGE_LEVELS = (1.00, 1.25)


@dataclass(frozen=True)
class ThreeWayComparison:
    """Comparable performance metrics and equity paths for three strategies."""

    metrics: pd.DataFrame
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


def _validate_levels(name: str, levels: pd.DataFrame | pd.Series) -> None:
    if levels.empty:
        raise ValueError(f"{name} must not be empty")
    if not isinstance(levels.index, pd.DatetimeIndex):
        raise TypeError(f"{name} index must be a DatetimeIndex")
    if levels.index.has_duplicates or not levels.index.is_monotonic_increasing:
        raise ValueError(f"{name} dates must be unique and sorted")
    values = levels.to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values <= 0.0).any():
        raise ValueError(f"{name} must contain finite positive values")


def _common_returns(
    etf_nav_usd: pd.DataFrame,
    dimensional_nav_usd: pd.Series,
) -> tuple[pd.DataFrame, pd.DatetimeIndex]:
    """Align levels first and then calculate interval returns on the common calendar."""

    _validate_levels("etf_nav_usd", etf_nav_usd)
    _validate_levels("dimensional_nav_usd", dimensional_nav_usd)
    required = {"core", "momentum", "quality", "value"}
    if set(etf_nav_usd.columns) != required:
        raise ValueError("etf_nav_usd must contain the four declared ETF sleeves")
    common = etf_nav_usd.index.intersection(dimensional_nav_usd.index)
    if len(common) < 2:
        raise ValueError("the ETF and Dimensional series need at least two common dates")
    common = pd.DatetimeIndex(common, name="date")
    levels = etf_nav_usd.loc[common].copy()
    levels["dimensional"] = dimensional_nav_usd.loc[common].astype(float)
    returns = levels.pct_change(fill_method=None)
    returns.iloc[0] = 0.0
    if returns.isna().any().any():
        raise ValueError("common-calendar return calculation produced missing values")
    return returns, common


def build_three_way_comparison(
    etf_nav_usd: pd.DataFrame,
    dimensional_nav_usd: pd.Series,
    annual_borrow_rate: pd.Series,
    annual_reference_rate: pd.Series,
    base_config: PortfolioConfig,
    *,
    leverage_levels: Iterable[float] = DEFAULT_LEVERAGE_LEVELS,
    input_provenance: Mapping[str, object] | None = None,
) -> ThreeWayComparison:
    """Compare Factor, 100% Core, and Dimensional on one common calendar."""

    levels = tuple(float(value) for value in leverage_levels)
    if not levels or len(set(levels)) != len(levels):
        raise ValueError("leverage_levels must be non-empty and unique")
    if any(not np.isfinite(value) or value < 1.0 for value in levels):
        raise ValueError("all leverage levels must be finite and at least 1")
    if set(base_config.target_weights) != {"core", "momentum", "quality", "value"}:
        raise ValueError("base_config must contain the four declared ETF sleeves")

    returns, common = _common_returns(etf_nav_usd, dimensional_nav_usd)
    metric_rows: list[dict[str, float | int | str]] = []
    equity_columns: dict[str, pd.Series] = {}

    for target_leverage in levels:
        leverage_band = None if target_leverage == 1.0 else base_config.leverage_band
        common_config = replace(
            base_config,
            target_leverage=target_leverage,
            leverage_band=leverage_band,
        )
        factor_config = common_config
        core_config = replace(common_config, target_weights={"core": 1.0})
        dimensional_config = replace(
            common_config, target_weights={"dimensional": 1.0}
        )

        factor = run_backtest(
            returns[["core", "momentum", "quality", "value"]],
            annual_borrow_rate,
            factor_config,
        )
        core = run_backtest(returns[["core"]], annual_borrow_rate, core_config)
        dimensional = run_backtest(
            returns[["dimensional"]], annual_borrow_rate, dimensional_config
        )
        strategies = (
            ("factor_portfolio", factor),
            ("msci_world", core),
            ("dimensional_global_core", dimensional),
        )
        label = f"{target_leverage:.2f}x"
        for strategy, result in strategies:
            summary = summarise_backtest(
                result,
                strategy=strategy,
                target_leverage=target_leverage,
                initial_equity_usd=base_config.initial_equity_usd,
                annual_reference_rate=annual_reference_rate,
                benchmark_result=core,
                benchmark_initial_equity_usd=base_config.initial_equity_usd,
                day_count=base_config.day_count,
            )
            metric_rows.append(
                {
                    "strategy": strategy,
                    "target_leverage": target_leverage,
                    "observations": summary["observations"],
                    "return_observations": summary["return_observations"],
                    "annualised_volatility": summary["annualised_volatility"],
                    "maximum_drawdown": summary["maximum_drawdown"],
                    "annualised_alpha_vs_core": summary["annualised_alpha_vs_core"],
                    **{key: value for key, value in summary.items() if key.startswith("ongoing_")},
                    "initial_equity_usd": base_config.initial_equity_usd,
                    "ending_equity_usd": summary["ending_equity_usd"],
                    "cumulative_return": (
                        float(summary["ending_equity_usd"])
                        / base_config.initial_equity_usd
                        - 1.0
                    ),
                    "cagr": summary["cagr"],
                    "sharpe_ratio": summary["sharpe_ratio"],
                    "beta_vs_same_leverage_msci_world": summary["beta_vs_core"],
                    "cumulative_financing_cost_usd": summary[
                        "cumulative_financing_cost_usd"
                    ],
                    "cumulative_transaction_cost_usd": summary[
                        "cumulative_transaction_cost_usd"
                    ],
                }
            )
            equity_columns[f"{strategy}_{label}"] = result.history["equity_usd"]

    metrics = pd.DataFrame(metric_rows).sort_values(
        ["target_leverage", "strategy"], ignore_index=True
    )
    equity_curves = pd.DataFrame(equity_columns, index=common)
    equity_curves.index.name = "date"
    manifest: dict[str, object] = {
        "schema_version": 2,
        "pipeline": "factor_portfolio.dimensional",
        "network_required": False,
        "comparison": (
            "frozen factor representative versus 100% MSCI World Core ETF and "
            "Bloomberg DIMGCEA ID Equity"
        ),
        "start_date": common[0].date().isoformat(),
        "end_date": common[-1].date().isoformat(),
        "observations": int(len(common)),
        "calendar": calendar_metadata(common, calendar_id="etf_dimensional_common_valuation"),
        "measurement_policy": measurement_policy(),
        "calendar_policy": (
            "intersection of ETF NAV and Dimensional valuation dates; returns are "
            "recalculated from levels after alignment"
        ),
        "target_leverage_levels": list(levels),
        "initial_equity_usd": base_config.initial_equity_usd,
        "factor_target_weights": dict(base_config.target_weights),
        "sleeve_band": base_config.sleeve_band,
        "leverage_band_at_1_25x": base_config.leverage_band,
        "financing_policy": "same SOFR plus 3.00 percentage-point borrowing spread",
        "risk_free_policy": (
            "New York Fed reference rate without broker spread; ACT/360 interval accrual"
        ),
        "sharpe_policy": (
            "mean interval excess return divided by interval excess-return volatility, "
            "annualised by sqrt(252)"
        ),
        "beta_policy": (
            "daily excess-return OLS slope versus 100% Core at the same target leverage"
        ),
        "transaction_cost_policy": (
            "same current Swissquote model for all strategies, including the common "
            "5 bp execution assumption; Dimensional-specific execution costs are not evidenced"
        ),
        "dimensional_security": DIMENSIONAL_SECURITY,
        "dimensional_isin": DIMENSIONAL_ISIN,
        "dimensional_identity_status": (
            "User confirmed that the Bloomberg query was entered with ISIN "
            f"{DIMENSIONAL_ISIN}; the returned workbook independently verifies security "
            f"{DIMENSIONAL_SECURITY} and USD currency, but does not embed the ISIN"
        ),
        "release_status": "private vendor-derived research results; do not publish",
        "input_provenance": dict(input_provenance or {}),
    }
    return ThreeWayComparison(metrics, equity_curves, manifest)


def write_three_way_comparison(
    comparison: ThreeWayComparison, output_dir: str | Path
) -> dict[str, Path]:
    """Write immutable private comparison outputs and checksummed provenance."""

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    paths = {
        "metrics": destination / "three_way_metrics.csv",
        "equity": destination / "three_way_equity_curves.csv",
        "manifest": destination / "three_way_manifest.json",
    }

    def csv_bytes(frame: pd.DataFrame, *, index: bool) -> bytes:
        buffer = io.StringIO(newline="")
        frame.to_csv(
            buffer,
            index=index,
            index_label="date" if index else None,
            date_format="%Y-%m-%d",
            float_format="%.12f",
            lineterminator="\n",
        )
        return buffer.getvalue().encode("utf-8")

    payloads = {
        paths["metrics"]: csv_bytes(comparison.metrics, index=False),
        paths["equity"]: csv_bytes(comparison.equity_curves, index=True),
    }
    manifest = dict(comparison.manifest)
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
            paths["metrics"]: continuous_result_columns(comparison.metrics),
            paths["equity"]: continuous_result_columns(comparison.equity_curves, levels=True),
        },
    )
    return paths


def load_three_way_comparison(input_dir: str | Path) -> ThreeWayComparison:
    """Load comparison outputs only after checksum and boundary verification."""

    source = Path(input_dir)
    manifest_path = source / "three_way_manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(manifest_path)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError("three-way manifest is not valid JSON") from exc
    filenames = {
        "metrics": "three_way_metrics.csv",
        "equity": "three_way_equity_curves.csv",
    }
    records = manifest.get("result_files")
    if not isinstance(records, dict):
        raise ValueError("three-way manifest is missing result_files")
    for filename in filenames.values():
        record = records.get(filename)
        if not isinstance(record, dict) or not isinstance(record.get("sha256"), str):
            raise ValueError(f"three-way manifest is missing checksum for {filename}")
        path = source / filename
        if not path.is_file():
            raise FileNotFoundError(path)
        if _sha256(path) != record["sha256"]:
            raise ValueError(f"three-way checksum mismatch for {filename}")
    metrics = pd.read_csv(source / filenames["metrics"])
    equity = pd.read_csv(
        source / filenames["equity"], index_col="date", parse_dates=["date"]
    )
    equity.index = pd.DatetimeIndex(equity.index, name="date")
    for filename, frame in (
        (filenames["metrics"], metrics),
        (filenames["equity"], equity),
    ):
        if len(frame) != records[filename].get("rows"):
            raise ValueError(f"three-way row count differs for {filename}")
    if equity.empty or equity.index.has_duplicates or not equity.index.is_monotonic_increasing:
        raise ValueError("three-way equity dates must be non-empty, unique, and sorted")
    if equity.index[0].date().isoformat() != manifest.get("start_date"):
        raise ValueError("three-way start date differs from manifest")
    if equity.index[-1].date().isoformat() != manifest.get("end_date"):
        raise ValueError("three-way end date differs from manifest")
    return ThreeWayComparison(metrics, equity, manifest)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the private Factor/Core/Dimensional comparison."
    )
    parser.add_argument("--canonical-dir", type=Path, default=Path("data/canonical"))
    parser.add_argument(
        "--dimensional-file",
        type=Path,
        default=Path("data/raw/bloomberg") / DIMENSIONAL_FILENAME,
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("results/dimensional_comparison_a2_b1"),
    )
    args = parser.parse_args(argv)

    market = load_canonical_dataset(args.canonical_dir)
    funding = load_funding_dataset(args.canonical_dir)
    dimensional = read_bloomberg_hardcopy(
        args.dimensional_file,
        BloombergSpec(
            "dimensional",
            DIMENSIONAL_SECURITY,
            args.dimensional_file.name,
        ),
        cutoff=DIMENSIONAL_LAST_DATE,
    )
    config = PortfolioConfig(
        target_weights={
            "core": 0.60,
            "momentum": 0.15,
            "quality": 0.15,
            "value": 0.10,
        }
    )
    comparison = build_three_way_comparison(
        market.nav_usd,
        dimensional.data["px_last_usd"].rename("dimensional"),
        funding.daily_borrow_rates["borrow_rate_annual"],
        funding.daily_borrow_rates["reference_rate_annual"],
        config,
        input_provenance={
            "etf_canonical_files": market.manifest.get("canonical_files", {}),
            "funding_canonical_files": funding.manifest.get("canonical_files", {}),
            "dimensional_source_file": args.dimensional_file.name,
            "dimensional_source_sha256": dimensional.source_sha256,
            "dimensional_source_first_date": dimensional.source_first_date.isoformat(),
            "dimensional_source_last_date": dimensional.source_last_date.isoformat(),
        },
    )
    paths = write_three_way_comparison(comparison, args.output_dir)
    print(
        f"Built {len(comparison.metrics)} strategy rows across "
        f"{len(DEFAULT_LEVERAGE_LEVELS)} leverage levels through "
        f"{comparison.equity_curves.index[-1].date()}."
    )
    for label, path in paths.items():
        print(f"{label}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
