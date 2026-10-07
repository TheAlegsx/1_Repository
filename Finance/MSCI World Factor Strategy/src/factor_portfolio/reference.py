"""Investable-reference diagnostic for Core 2x, Amundi 2x, and its index."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Mapping

import numpy as np
import pandas as pd

from .benchmark import calendar_metadata
from .config import PortfolioConfig
from .data import load_canonical_dataset
from .engine import run_backtest
from .market_data import MarketDataset, load_market_dataset
from .rates import load_funding_dataset
from .result_io import continuous_result_columns, write_immutable_result_package


@dataclass(frozen=True)
class InvestableReferenceComparison:
    levels: pd.DataFrame
    metrics: pd.DataFrame
    manifest: dict[str, object]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def build_investable_reference_comparison(
    returns_usd: pd.DataFrame,
    annual_borrow_rate: pd.Series,
    market_data: MarketDataset,
    base_config: PortfolioConfig,
    *,
    input_provenance: Mapping[str, object] | None = None,
) -> InvestableReferenceComparison:
    """Compare normalized economic paths on the genuine three-way overlap."""

    if "core" not in returns_usd.columns:
        raise ValueError("returns_usd must contain the Core ETF column")
    overlap = market_data.benchmark_overlap[
        ["mxwoldnu_index_level_usd", "amundi_2x_nav_usd"]
    ].dropna()
    if overlap.empty:
        raise ValueError("market_data has no Amundi/MXWOLDNU overlap")
    start, end = overlap.index[0], overlap.index[-1]
    core_returns = returns_usd.loc[start:end, ["core"]].copy()
    if len(core_returns) < 2:
        raise ValueError("Core ETF has insufficient observations in reference window")
    core_returns.iloc[0] = 0.0
    core_config = replace(
        base_config,
        target_weights={"core": 1.0},
        target_leverage=2.0,
        leverage_band=0.10,
    )
    core_result = run_backtest(core_returns, annual_borrow_rate, core_config)
    common_dates = core_result.history.index.intersection(overlap.index)
    if len(common_dates) < 2:
        raise ValueError("fewer than two three-way common observations")

    levels = pd.DataFrame(
        {
            "core_banded_2x_equity_usd": core_result.history.loc[
                common_dates, "equity_usd"
            ],
            "amundi_2x_nav_usd": overlap.loc[common_dates, "amundi_2x_nav_usd"],
            "mxwoldnu_index_level_usd": overlap.loc[
                common_dates, "mxwoldnu_index_level_usd"
            ],
        },
        index=common_dates,
    )
    levels.index.name = "date"
    normalized_columns: list[str] = []
    for column in list(levels.columns):
        normalized = f"normalized_{column}"
        levels[normalized] = levels[column] / levels[column].iloc[0]
        normalized_columns.append(normalized)

    metric_rows: list[dict[str, float | int | str]] = []
    normalized_map = {
        "core_banded_2x": "normalized_core_banded_2x_equity_usd",
        "amundi_2x_etf": "normalized_amundi_2x_nav_usd",
        "mxwoldnu_2x_index": "normalized_mxwoldnu_index_level_usd",
    }
    index_returns = levels[normalized_map["mxwoldnu_2x_index"]].pct_change(
        fill_method=None
    )
    for strategy, column in normalized_map.items():
        series = levels[column]
        returns = series.pct_change(fill_method=None).dropna()
        drawdown = series / series.cummax() - 1.0
        aligned_index = index_returns.loc[returns.index]
        difference = returns - aligned_index
        metric_rows.append(
            {
                "strategy": strategy,
                "level_observations": int(len(series)),
                "return_observations": int(len(returns)),
                "cumulative_return": float(series.iloc[-1] - 1.0),
                "annualised_volatility": float(returns.std(ddof=1) * np.sqrt(252.0)),
                "maximum_drawdown": float(drawdown.min()),
                "daily_correlation_with_index": float(returns.corr(aligned_index)),
                "mean_daily_difference_vs_index_bps": float(
                    difference.mean() * 10_000.0
                ),
                "annualised_tracking_error_vs_index": float(
                    difference.std(ddof=1) * np.sqrt(252.0)
                ),
            }
        )
    metrics = pd.DataFrame(metric_rows)
    manifest: dict[str, object] = {
        "schema_version": 2,
        "pipeline": "factor_portfolio.reference",
        "network_required": False,
        "comparison": (
            "normalized band-controlled debt-financed Core 2x versus Amundi 2x "
            "ETF NAV and MXWOLDNU daily 2x net index"
        ),
        "start_date": levels.index[0].date().isoformat(),
        "end_date": levels.index[-1].date().isoformat(),
        "three_way_level_observations": int(len(levels)),
        "calendar": calendar_metadata(common_dates, calendar_id="core_amundi_index_common_valuation"),
        "measurement_policy": {
            "version": "B1-normalized-reference-2026-10-01",
            "return_view": "normalized post-start level comparison; no invented investor entry costs",
            "nominal_annualisation_periods": 252.0,
        },
        "normalization_policy": "each series divided by its first three-way common level",
        "core_policy": (
            "100% Core ETF, 2.0x target leverage, +/-0.10 leverage band, SOFR+3%, "
            "same engine; opening cost level removed by normalization"
        ),
        "amundi_policy": (
            "official USD NAV; embedded product economics retained; no investor-level "
            "broker, FX, stamp-duty, or listing-spread adjustment"
        ),
        "comparability_warning": (
            "Amundi and MXWOLDNU reset leverage daily; the Core strategy uses debt and "
            "a leverage band, so differences are economic diagnostics, not like-for-like "
            "tracking error"
        ),
        "calendar_policy": (
            "Core is simulated on its full common ETF calendar, then all three level "
            "series are sampled on their date intersection"
        ),
        "release_status": "private derived research results; do not publish",
        "input_provenance": dict(input_provenance or {}),
    }
    return InvestableReferenceComparison(levels, metrics, manifest)


def write_investable_reference_comparison(
    comparison: InvestableReferenceComparison, output_dir: str | Path
) -> dict[str, Path]:
    """Write immutable private reference outputs and their checksums."""

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    paths = {
        "levels": destination / "investable_reference_levels.csv",
        "metrics": destination / "investable_reference_metrics.csv",
        "manifest": destination / "reference_manifest.json",
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
        paths["levels"]: csv_bytes(comparison.levels, index=True),
        paths["metrics"]: csv_bytes(comparison.metrics, index=False),
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
            paths["levels"]: continuous_result_columns(comparison.levels, levels=True),
            paths["metrics"]: continuous_result_columns(comparison.metrics),
        },
    )
    return paths


def load_investable_reference_comparison(
    input_dir: str | Path,
) -> InvestableReferenceComparison:
    """Load reference results only after checksum and boundary verification."""

    source = Path(input_dir)
    manifest_path = source / "reference_manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(manifest_path)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError("reference manifest is not valid JSON") from exc
    filenames = {
        "levels": "investable_reference_levels.csv",
        "metrics": "investable_reference_metrics.csv",
    }
    records = manifest.get("result_files")
    if not isinstance(records, dict):
        raise ValueError("reference manifest is missing result_files")
    for filename in filenames.values():
        record = records.get(filename)
        path = source / filename
        if not isinstance(record, dict) or not isinstance(record.get("sha256"), str):
            raise ValueError(f"reference manifest is missing checksum for {filename}")
        if not path.is_file():
            raise FileNotFoundError(path)
        if _sha256(path) != record["sha256"]:
            raise ValueError(f"reference checksum mismatch for {filename}")
    levels = pd.read_csv(
        source / filenames["levels"], index_col="date", parse_dates=["date"]
    )
    levels.index = pd.DatetimeIndex(levels.index, name="date")
    metrics = pd.read_csv(source / filenames["metrics"])
    for filename, frame in (
        (filenames["levels"], levels),
        (filenames["metrics"], metrics),
    ):
        if len(frame) != records[filename].get("rows"):
            raise ValueError(f"reference row count differs for {filename}")
    if levels.empty or levels.index.has_duplicates or not levels.index.is_monotonic_increasing:
        raise ValueError("reference dates must be non-empty, unique, and sorted")
    if levels.index[0].date().isoformat() != manifest.get("start_date"):
        raise ValueError("reference start date differs from manifest")
    if levels.index[-1].date().isoformat() != manifest.get("end_date"):
        raise ValueError("reference end date differs from manifest")
    return InvestableReferenceComparison(levels, metrics, manifest)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the private Amundi/MXWOLDNU/Core 2x diagnostic."
    )
    parser.add_argument("--canonical-dir", type=Path, default=Path("data/canonical"))
    parser.add_argument(
        "--market-data-dir", type=Path, default=Path("data/canonical/market_data")
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path("results/investable_reference_b1")
    )
    args = parser.parse_args(argv)

    market = load_canonical_dataset(args.canonical_dir)
    funding = load_funding_dataset(args.canonical_dir)
    vendor = load_market_dataset(args.market_data_dir)
    config = PortfolioConfig(
        target_weights={
            "core": 0.60,
            "momentum": 0.15,
            "quality": 0.10,
            "value": 0.15,
        }
    )
    comparison = build_investable_reference_comparison(
        market.returns_usd,
        funding.daily_borrow_rates["borrow_rate_annual"],
        vendor,
        config,
        input_provenance={
            "etf_canonical_files": market.manifest.get("canonical_files", {}),
            "funding_canonical_files": funding.manifest.get("canonical_files", {}),
            "market_data_canonical_files": vendor.manifest.get("canonical_files", {}),
        },
    )
    paths = write_investable_reference_comparison(comparison, args.output_dir)
    print(
        f"Built {len(comparison.levels)} three-way observations from "
        f"{comparison.levels.index[0].date()} through "
        f"{comparison.levels.index[-1].date()}."
    )
    for label, path in paths.items():
        print(f"{label}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
