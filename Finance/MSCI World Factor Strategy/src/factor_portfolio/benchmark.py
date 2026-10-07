"""Same-leverage analytical benchmark built on the common portfolio engine."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable, Mapping

import numpy as np
import pandas as pd

from .config import PortfolioConfig
from .data import load_canonical_dataset
from .engine import BacktestResult, run_backtest
from .rates import load_funding_dataset
from .result_io import continuous_result_columns, write_immutable_result_package


DEFAULT_LEVERAGE_LEVELS = (1.00, 1.25, 1.50, 1.75, 2.00)
ANNUALISATION_PERIODS = 252.0
MEASUREMENT_POLICY_VERSION = "A2-B1-2026-10-01"


@dataclass(frozen=True)
class BenchmarkComparison:
    """Comparable strategy metrics, differences, and equity paths."""

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


def _validate_equity(equity: pd.Series) -> None:
    if not isinstance(equity.index, pd.DatetimeIndex):
        raise TypeError("equity index must be a DatetimeIndex")
    if equity.empty or equity.index.has_duplicates or not equity.index.is_monotonic_increasing:
        raise ValueError("equity dates must be non-empty, unique and sorted")
    values = equity.to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values <= 0.0).any():
        raise ValueError("equity must contain finite positive values")


def _validate_capital(capital: float) -> None:
    if not np.isfinite(capital) or capital <= 0.0:
        raise ValueError("initial committed capital must be finite and positive")


def investor_equity_returns(
    equity: pd.Series, *, initial_committed_capital_usd: float | None = None
) -> pd.Series:
    """Return valuation-interval investor returns, optionally including entry costs.

    With committed capital, the first interval is E1 / capital - 1. Without it,
    returns describe the ongoing post-entry portfolio. No extra date is inserted.
    """

    _validate_equity(equity)
    if len(equity) < 2:
        raise ValueError("investor returns require at least two valuations")
    returns = equity.pct_change(fill_method=None).iloc[1:].copy()
    if initial_committed_capital_usd is not None:
        _validate_capital(initial_committed_capital_usd)
        returns.iloc[0] = equity.iloc[1] / initial_committed_capital_usd - 1.0
    return returns


def investor_drawdown(
    equity: pd.Series, *, initial_committed_capital_usd: float | None = None
) -> pd.Series:
    """Measure drawdown with an optional committed-capital opening high-water mark."""

    _validate_equity(equity)
    high_water = equity.cummax()
    if initial_committed_capital_usd is not None:
        _validate_capital(initial_committed_capital_usd)
        high_water = high_water.clip(lower=initial_committed_capital_usd)
    return equity / high_water - 1.0


def calendar_metadata(
    dates: pd.DatetimeIndex, *, calendar_id: str = "common_published_etf_nav"
) -> dict[str, object]:
    """Describe the observed calendar without claiming executable trading dates."""

    if not isinstance(dates, pd.DatetimeIndex):
        raise TypeError("valuation dates must be a DatetimeIndex")
    if len(dates) < 2 or dates.has_duplicates or not dates.is_monotonic_increasing:
        raise ValueError("valuation dates must contain at least two unique sorted dates")
    elapsed_years = (dates[-1] - dates[0]).days / 365.2425
    if elapsed_years <= 0.0:
        raise ValueError("valuation calendar must span more than one calendar day")
    return {
        "calendar_id": calendar_id,
        "level_observations": len(dates),
        "return_observations": len(dates) - 1,
        "start_date": dates[0].date().isoformat(),
        "end_date": dates[-1].date().isoformat(),
        "elapsed_calendar_years": elapsed_years,
        "observed_intervals_per_year": (len(dates) - 1) / elapsed_years,
        "nominal_annualisation_periods": ANNUALISATION_PERIODS,
        "maximum_interval_calendar_days": int((dates[1:] - dates[:-1]).days.max()),
        "annualisation_interpretation": (
            "conventional NAV-observation scaling, not exact calendar-time risk "
            "or evidence of an executable venue calendar"
        ),
    }


def measurement_policy() -> dict[str, object]:
    return {
        "version": MEASUREMENT_POLICY_VERSION,
        "primary_return_view": "opening costs included in first subsequent valuation interval",
        "first_interval_return": "E1 / initial committed capital - 1",
        "drawdown_view": "committed capital is the opening high-water mark",
        "secondary_return_view": "ongoing post-entry statistics, prefixed ongoing_",
        "nominal_annualisation_periods": ANNUALISATION_PERIODS,
        "rolling_window_rule": "do not recharge inception costs in a later ongoing window",
    }


def exclude_unchanged_nav_sensitivity(navs: pd.DataFrame) -> pd.DataFrame:
    """Return a separate calendar sensitivity, preserving both source endpoints."""

    calendar_metadata(navs.index)
    values = navs.to_numpy(dtype=float)
    if navs.shape[1] == 0 or not np.isfinite(values).all() or (values <= 0.0).any():
        raise ValueError("NAVs must contain finite positive values")
    unchanged = navs.diff().eq(0.0).all(axis=1)
    unchanged.iloc[0] = False
    unchanged.iloc[-1] = False
    return navs.loc[~unchanged].copy()


def _interval_reference_returns(
    valuation_index: pd.DatetimeIndex,
    annual_reference_rate: pd.Series,
    *,
    day_count: float,
) -> pd.Series:
    """Convert calendar-daily annual rates to valuation-interval returns."""

    if len(valuation_index) < 2:
        raise ValueError("risk metrics require at least two valuation dates")
    if not isinstance(annual_reference_rate.index, pd.DatetimeIndex):
        raise TypeError("annual_reference_rate index must be a DatetimeIndex")
    if annual_reference_rate.index.has_duplicates:
        raise ValueError("annual_reference_rate contains duplicate dates")
    required = pd.date_range(
        valuation_index[0], valuation_index[-1], freq="D", name="date"
    )
    rates = annual_reference_rate.reindex(required)
    if rates.isna().any():
        raise ValueError(
            "annual_reference_rate must cover every calendar day in the valuation window"
        )
    if not np.isfinite(rates.to_numpy(dtype=float)).all():
        raise ValueError("annual_reference_rate contains non-finite values")
    if not np.isfinite(day_count) or day_count <= 0.0:
        raise ValueError("day_count must be finite and positive")
    daily = rates.astype(float) / day_count
    accrued_before_date = daily.cumsum().shift(1, fill_value=0.0)
    starts = accrued_before_date.reindex(valuation_index[:-1]).to_numpy(dtype=float)
    ends = accrued_before_date.reindex(valuation_index[1:]).to_numpy(dtype=float)
    return pd.Series(
        ends - starts,
        index=valuation_index[1:],
        name="risk_free_interval_return",
    )


def calculate_risk_adjusted_metrics(
    equity: pd.Series,
    annual_reference_rate: pd.Series,
    *,
    benchmark_equity: pd.Series,
    day_count: float = 360.0,
    initial_committed_capital_usd: float | None = None,
    benchmark_initial_committed_capital_usd: float | None = None,
) -> dict[str, float]:
    """Calculate annualised Sharpe ratio and CAPM-style alpha and beta.

    Portfolio and benchmark excess returns use the same New York Fed reference-rate
    accrual over each actual valuation interval. Sharpe and the OLS intercept use
    conventional 252-observation annualisation. Beta is the OLS slope versus the
    equal-leverage Core benchmark. Supplying both committed capitals includes each
    opening cost in its first interval; omitting both retains the ongoing view.
    """

    if (initial_committed_capital_usd is None) != (
        benchmark_initial_committed_capital_usd is None
    ):
        raise ValueError("portfolio and benchmark must use the same opening-cost view")
    if not equity.index.equals(benchmark_equity.index):
        raise ValueError("portfolio and benchmark equity dates must be identical")
    portfolio_returns = investor_equity_returns(
        equity, initial_committed_capital_usd=initial_committed_capital_usd
    )
    benchmark_returns = investor_equity_returns(
        benchmark_equity,
        initial_committed_capital_usd=benchmark_initial_committed_capital_usd,
    )
    risk_free_returns = _interval_reference_returns(
        equity.index,
        annual_reference_rate,
        day_count=day_count,
    )
    portfolio_excess = portfolio_returns - risk_free_returns
    benchmark_excess = benchmark_returns - risk_free_returns
    excess_volatility = float(portfolio_excess.std(ddof=1))
    benchmark_variance = float(benchmark_excess.var(ddof=1))
    sharpe = (
        float(portfolio_excess.mean() / excess_volatility * np.sqrt(ANNUALISATION_PERIODS))
        if excess_volatility > 0.0
        else float("nan")
    )
    beta = (
        float(portfolio_excess.cov(benchmark_excess) / benchmark_variance)
        if benchmark_variance > 0.0
        else float("nan")
    )
    alpha = (
        float(
            (portfolio_excess.mean() - beta * benchmark_excess.mean()) * ANNUALISATION_PERIODS
        )
        if np.isfinite(beta)
        else float("nan")
    )
    return {
        "sharpe_ratio": sharpe,
        "beta_vs_core": beta,
        "annualised_alpha_vs_core": alpha,
    }


def summarise_backtest(
    result: BacktestResult,
    *,
    strategy: str,
    target_leverage: float,
    initial_equity_usd: float,
    annual_reference_rate: pd.Series,
    benchmark_result: BacktestResult,
    benchmark_initial_equity_usd: float,
    day_count: float = 360.0,
) -> dict[str, float | int | str]:
    history = result.history
    if len(history) < 2:
        raise ValueError("benchmark metrics require at least two observations")
    elapsed_years = (history.index[-1] - history.index[0]).days / 365.2425
    if elapsed_years <= 0.0:
        raise ValueError("benchmark window must span more than one calendar day")
    equity = history["equity_usd"]
    equity_returns = investor_equity_returns(
        equity, initial_committed_capital_usd=initial_equity_usd
    )
    ongoing_returns = investor_equity_returns(equity)
    drawdown = investor_drawdown(equity, initial_committed_capital_usd=initial_equity_usd)
    calendar = calendar_metadata(history.index)
    identity_error = (
        equity - (history["gross_assets_usd"] - history["debt_usd"])
    ).abs()
    risk_metrics = calculate_risk_adjusted_metrics(
        equity,
        annual_reference_rate,
        benchmark_equity=benchmark_result.history["equity_usd"],
        day_count=day_count,
        initial_committed_capital_usd=initial_equity_usd,
        benchmark_initial_committed_capital_usd=benchmark_initial_equity_usd,
    )
    ongoing_risk_metrics = calculate_risk_adjusted_metrics(
        equity,
        annual_reference_rate,
        benchmark_equity=benchmark_result.history["equity_usd"],
        day_count=day_count,
    )
    return {
        "strategy": strategy,
        "target_leverage": target_leverage,
        "observations": int(len(history)),
        "return_observations": int(calendar["return_observations"]),
        "elapsed_calendar_years": elapsed_years,
        "observed_intervals_per_year": float(calendar["observed_intervals_per_year"]),
        "annualisation_periods": ANNUALISATION_PERIODS,
        "initial_committed_capital_usd": initial_equity_usd,
        "opening_equity_usd": float(equity.iloc[0]),
        "opening_transaction_cost_usd": float(history["transaction_cost_usd"].iloc[0]),
        "ending_equity_usd": float(equity.iloc[-1]),
        "cagr": float(
            (equity.iloc[-1] / initial_equity_usd) ** (1.0 / elapsed_years) - 1.0
        ),
        "annualised_volatility": float(equity_returns.std(ddof=1) * np.sqrt(ANNUALISATION_PERIODS)),
        "maximum_drawdown": float(drawdown.min()),
        **risk_metrics,
        "ongoing_annualised_volatility": float(
            ongoing_returns.std(ddof=1) * np.sqrt(ANNUALISATION_PERIODS)
        ),
        "ongoing_maximum_drawdown": float(investor_drawdown(equity).min()),
        **{f"ongoing_{key}": value for key, value in ongoing_risk_metrics.items()},
        "cumulative_financing_cost_usd": float(
            history["cumulative_financing_cost_usd"].iloc[-1]
        ),
        "cumulative_transaction_cost_usd": float(
            history["cumulative_transaction_cost_usd"].iloc[-1]
        ),
        "minimum_leverage": float(history["leverage"].min()),
        "average_leverage": float(history["leverage"].mean()),
        "maximum_leverage": float(history["leverage"].max()),
        "post_initialisation_trade_events": int(
            (result.events["event"] != "initialise").sum()
        ),
        "maximum_accounting_error_usd": float(identity_error.max()),
    }


def build_same_leverage_comparison(
    returns_usd: pd.DataFrame,
    annual_borrow_rate: pd.Series,
    annual_reference_rate: pd.Series,
    base_config: PortfolioConfig,
    *,
    leverage_levels: Iterable[float] = DEFAULT_LEVERAGE_LEVELS,
    input_provenance: Mapping[str, object] | None = None,
    calendar_id: str = "common_published_etf_nav",
) -> BenchmarkComparison:
    """Compare the factor portfolio with a 100% Core portfolio at equal leverage."""

    levels = tuple(float(value) for value in leverage_levels)
    if not levels or len(set(levels)) != len(levels):
        raise ValueError("leverage_levels must be non-empty and unique")
    if any(not np.isfinite(value) or value < 1.0 for value in levels):
        raise ValueError("all leverage levels must be finite and at least 1")
    if "core" not in returns_usd.columns:
        raise ValueError("returns_usd must contain the Core ETF column")
    if set(returns_usd.columns) != set(base_config.target_weights):
        raise ValueError("base_config target weights must match returns_usd columns")

    metric_rows: list[dict[str, float | int | str]] = []
    equity_columns: dict[str, pd.Series] = {}
    for target_leverage in levels:
        leverage_band = None if target_leverage == 1.0 else base_config.leverage_band
        factor_config = replace(
            base_config,
            target_leverage=target_leverage,
            leverage_band=leverage_band,
        )
        benchmark_config = replace(
            factor_config,
            target_weights={"core": 1.0},
        )
        factor = run_backtest(returns_usd, annual_borrow_rate, factor_config)
        benchmark = run_backtest(
            returns_usd[["core"]], annual_borrow_rate, benchmark_config
        )
        label = f"{target_leverage:.2f}x"
        equity_columns[f"factor_{label}"] = factor.history["equity_usd"]
        equity_columns[f"core_{label}"] = benchmark.history["equity_usd"]
        metric_rows.append(
            summarise_backtest(
                factor,
                strategy="factor_portfolio",
                target_leverage=target_leverage,
                initial_equity_usd=base_config.initial_equity_usd,
                annual_reference_rate=annual_reference_rate,
                benchmark_result=benchmark,
                benchmark_initial_equity_usd=base_config.initial_equity_usd,
                day_count=base_config.day_count,
            )
        )
        metric_rows.append(
            summarise_backtest(
                benchmark,
                strategy="core_benchmark",
                target_leverage=target_leverage,
                initial_equity_usd=base_config.initial_equity_usd,
                annual_reference_rate=annual_reference_rate,
                benchmark_result=benchmark,
                benchmark_initial_equity_usd=base_config.initial_equity_usd,
                day_count=base_config.day_count,
            )
        )

    metrics = pd.DataFrame(metric_rows).sort_values(
        ["target_leverage", "strategy"], ignore_index=True
    )
    relative_rows: list[dict[str, float]] = []
    difference_fields = (
        "ending_equity_usd",
        "cagr",
        "annualised_volatility",
        "maximum_drawdown",
        "sharpe_ratio",
        "beta_vs_core",
        "annualised_alpha_vs_core",
        "ongoing_annualised_volatility",
        "ongoing_maximum_drawdown",
        "ongoing_sharpe_ratio",
        "ongoing_beta_vs_core",
        "ongoing_annualised_alpha_vs_core",
        "cumulative_financing_cost_usd",
        "cumulative_transaction_cost_usd",
        "post_initialisation_trade_events",
    )
    for target_leverage in levels:
        subset = metrics.loc[metrics["target_leverage"] == target_leverage].set_index(
            "strategy"
        )
        row = {"target_leverage": target_leverage}
        for field in difference_fields:
            row[f"factor_minus_core_{field}"] = float(
                subset.loc["factor_portfolio", field]
                - subset.loc["core_benchmark", field]
            )
        relative_rows.append(row)
    relative_metrics = pd.DataFrame(relative_rows)
    equity_curves = pd.DataFrame(equity_columns, index=returns_usd.index)
    equity_curves.index.name = "date"

    manifest: dict[str, object] = {
        "schema_version": 2,
        "pipeline": "factor_portfolio.benchmark",
        "network_required": False,
        "comparison": "factor portfolio versus 100% Core ETF at equal target leverage",
        "calendar_policy": "same selected NAV calendar for both strategies; source rows retained in the primary view",
        "calendar": calendar_metadata(returns_usd.index, calendar_id=calendar_id),
        "measurement_policy": measurement_policy(),
        "financing_policy": "same verified daily borrowing-rate series and ACT/360 engine",
        "risk_free_policy": (
            "New York Fed reference rate without broker spread; ACT/360 accrual over "
            "each valuation interval"
        ),
        "sharpe_policy": (
            "mean daily portfolio excess return divided by daily excess-return "
            "volatility, annualised by sqrt(252)"
        ),
        "alpha_beta_policy": (
            "daily excess-return OLS versus equal-leverage 100% Core; beta is slope "
            "and alpha is the intercept annualised arithmetically by 252"
        ),
        "cost_policy": "same fee schedule; costs charged per actually traded ETF leg",
        "execution_policy": "same next-observation band execution",
        "unlevered_policy": "1.00x has no leverage band because debt is zero",
        "start_date": returns_usd.index[0].date().isoformat(),
        "end_date": returns_usd.index[-1].date().isoformat(),
        "observations": int(len(returns_usd)),
        "initial_equity_usd": base_config.initial_equity_usd,
        "factor_target_weights": dict(base_config.target_weights),
        "benchmark_target_weights": {"core": 1.0},
        "sleeve_band": base_config.sleeve_band,
        "leverage_band": base_config.leverage_band,
        "target_leverage_levels": list(levels),
        "release_status": "private derived research results; do not publish",
        "input_provenance": dict(input_provenance or {}),
    }
    return BenchmarkComparison(
        metrics=metrics,
        relative_metrics=relative_metrics,
        equity_curves=equity_curves,
        manifest=manifest,
    )


def write_benchmark_comparison(
    comparison: BenchmarkComparison, output_dir: str | Path
) -> dict[str, Path]:
    """Write immutable private comparison outputs and their checksums."""

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    paths = {
        "metrics": destination / "same_leverage_metrics.csv",
        "relative": destination / "factor_minus_core_metrics.csv",
        "equity": destination / "same_leverage_equity_curves.csv",
        "manifest": destination / "benchmark_manifest.json",
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
        paths["relative"]: csv_bytes(comparison.relative_metrics, index=False),
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
            paths["relative"]: continuous_result_columns(comparison.relative_metrics),
            paths["equity"]: continuous_result_columns(comparison.equity_curves, levels=True),
        },
    )
    return paths


def load_benchmark_comparison(input_dir: str | Path) -> BenchmarkComparison:
    """Load private benchmark outputs only after checksum verification."""

    source = Path(input_dir)
    manifest_path = source / "benchmark_manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(manifest_path)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError("benchmark manifest is not valid JSON") from exc
    filenames = {
        "metrics": "same_leverage_metrics.csv",
        "relative": "factor_minus_core_metrics.csv",
        "equity": "same_leverage_equity_curves.csv",
    }
    records = manifest.get("result_files")
    if not isinstance(records, dict):
        raise ValueError("benchmark manifest is missing result_files")
    for filename in filenames.values():
        record = records.get(filename)
        if not isinstance(record, dict) or not isinstance(record.get("sha256"), str):
            raise ValueError(f"benchmark manifest is missing checksum for {filename}")
        path = source / filename
        if not path.is_file():
            raise FileNotFoundError(path)
        if _sha256(path) != record["sha256"]:
            raise ValueError(f"benchmark checksum mismatch for {filename}")
    metrics = pd.read_csv(source / filenames["metrics"])
    relative = pd.read_csv(source / filenames["relative"])
    equity = pd.read_csv(
        source / filenames["equity"], index_col="date", parse_dates=["date"]
    )
    equity.index = pd.DatetimeIndex(equity.index, name="date")
    for filename, frame in (
        (filenames["metrics"], metrics),
        (filenames["relative"], relative),
        (filenames["equity"], equity),
    ):
        if len(frame) != records[filename].get("rows"):
            raise ValueError(f"benchmark row count differs for {filename}")
    if equity.empty or equity.index.has_duplicates or not equity.index.is_monotonic_increasing:
        raise ValueError("benchmark equity dates must be non-empty, unique, and sorted")
    if equity.index[0].date().isoformat() != manifest.get("start_date"):
        raise ValueError("benchmark start date differs from manifest")
    if equity.index[-1].date().isoformat() != manifest.get("end_date"):
        raise ValueError("benchmark end date differs from manifest")
    return BenchmarkComparison(metrics, relative, equity, manifest)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the private same-leverage Core benchmark comparison."
    )
    parser.add_argument("--canonical-dir", type=Path, default=Path("data/canonical"))
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
    )
    parser.add_argument(
        "--exclude-unchanged-nav",
        action="store_true",
        help="run a separate unchanged-NAV calendar sensitivity; never modify canonical data",
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
    returns = market.returns_usd
    calendar_id = "common_published_etf_nav"
    calendar_provenance: dict[str, object] = {"excluded_nav_dates": []}
    default_output = "results/same_leverage_benchmark_a2_b1"
    if args.exclude_unchanged_nav:
        retained = exclude_unchanged_nav_sensitivity(market.nav_usd)
        returns = retained.pct_change(fill_method=None)
        returns.iloc[0] = 0.0
        calendar_id = "exclude_all_unchanged_nav_sensitivity"
        calendar_provenance["excluded_nav_dates"] = [
            date.date().isoformat() for date in market.nav_usd.index.difference(retained.index)
        ]
        default_output = "results/same_leverage_benchmark_calendar_exclusion_a2_b1"
    comparison = build_same_leverage_comparison(
        returns,
        funding.daily_borrow_rates["borrow_rate_annual"],
        funding.daily_borrow_rates["reference_rate_annual"],
        config,
        input_provenance={
            "etf_canonical_files": market.manifest.get("canonical_files", {}),
            "funding_canonical_files": funding.manifest.get("canonical_files", {}),
            "calendar_treatment": calendar_provenance,
        },
        calendar_id=calendar_id,
    )
    paths = write_benchmark_comparison(comparison, args.output_dir or Path(default_output))
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
