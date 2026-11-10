"""Deterministic New York Fed SOFR and broker-rate data pipeline."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Mapping

import numpy as np
import pandas as pd

from .security_io import validate_xlsx, write_immutable_payloads, bounded_input


DEFAULT_START = date(2014, 10, 3)
DEFAULT_CUTOFF = date(2026, 8, 31)
DEFAULT_BROKER_SPREAD = 0.03
OFFICIAL_SOFR_START = pd.Timestamp("2018-04-02")
INDICATIVE_FILENAME = "Data Release.xlsx"
OFFICIAL_FILENAME = "sofr_official_2018-04-02_2026-08-31.json"

OBSERVATION_COLUMNS = [
    "reference_rate_annual",
    "reference_series",
    "reference_status",
    "revision_indicator",
]
DAILY_COLUMNS = [
    "reference_value_date",
    "reference_rate_annual",
    "broker_spread_annual",
    "borrow_rate_annual",
    "reference_series",
    "reference_status",
    "rate_carried_forward",
]


@dataclass(frozen=True)
class FundingDataset:
    """Observed SOFR values, daily applicable rates, and provenance."""

    reference_observations: pd.DataFrame
    daily_borrow_rates: pd.DataFrame
    manifest: dict[str, object]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _validate_observations(frame: pd.DataFrame, label: str) -> pd.DataFrame:
    if frame.empty:
        raise ValueError(f"{label} contains no observations")
    if not isinstance(frame.index, pd.DatetimeIndex):
        raise TypeError(f"{label} index must be a DatetimeIndex")
    if frame.index.has_duplicates:
        raise ValueError(f"{label} contains duplicate value dates")
    frame = frame.sort_index()
    if frame["reference_rate_annual"].isna().any():
        raise ValueError(f"{label} contains missing rates")
    rates = frame["reference_rate_annual"].to_numpy(dtype=float)
    if not np.isfinite(rates).all() or (rates <= -1.0).any():
        raise ValueError(f"{label} contains invalid rates")
    frame.index = pd.DatetimeIndex(frame.index.normalize(), name="date")
    return frame.loc[:, OBSERVATION_COLUMNS]


def read_indicative_sofr(path: str | Path) -> pd.DataFrame:
    """Read the pre-production SOFR column from the New York Fed workbook."""

    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(source)
    try:
        validate_xlsx(source)
        raw = pd.read_excel(source, sheet_name="VWM Rates", header=1)
    except (OSError, ValueError) as exc:
        raise ValueError(f"cannot read indicative SOFR workbook: {source.name}") from exc

    required = {"Date", "Secured Overnight Financing Rate"}
    if not required.issubset(raw.columns):
        raise ValueError(
            f"{source.name} is missing required columns: {sorted(required - set(raw.columns))}"
        )
    dates = pd.to_datetime(raw["Date"], errors="coerce")
    dated = raw.loc[
        dates.notna(), ["Date", "Secured Overnight Financing Rate"]
    ].copy()
    dated["Date"] = pd.to_datetime(dated["Date"], errors="raise")
    basis_points = pd.to_numeric(
        dated["Secured Overnight Financing Rate"], errors="raise"
    )
    frame = pd.DataFrame(
        {
            "reference_rate_annual": basis_points.to_numpy(dtype=float) / 10_000.0,
            "reference_series": "INDICATIVE_SOFR",
            "reference_status": "indicative",
            "revision_indicator": "",
        },
        index=pd.DatetimeIndex(dated["Date"], name="date"),
    )
    return _validate_observations(frame, "indicative SOFR")


def read_official_sofr(path: str | Path) -> pd.DataFrame:
    """Read official SOFR observations from an unchanged Markets Data API response."""

    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(source)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError(f"official SOFR source is not valid JSON: {source.name}") from exc
    records = payload.get("refRates")
    if not isinstance(records, list) or not records:
        raise ValueError("official SOFR JSON must contain a non-empty refRates list")

    rows: list[dict[str, object]] = []
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("official SOFR refRates entries must be objects")
        if record.get("type") != "SOFR":
            raise ValueError(f"unexpected official rate type: {record.get('type')!r}")
        rows.append(
            {
                "date": pd.Timestamp(record["effectiveDate"]),
                "reference_rate_annual": float(record["percentRate"]) / 100.0,
                "reference_series": "SOFR",
                "reference_status": "official",
                "revision_indicator": str(record.get("revisionIndicator") or ""),
            }
        )
    frame = pd.DataFrame(rows).set_index("date")
    return _validate_observations(frame, "official SOFR")


def _load_source_manifest(raw_dir: Path) -> tuple[dict[str, object], str]:
    path = raw_dir / "source_manifest.json"
    if not path.is_file():
        raise FileNotFoundError(path)
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError("New York Fed source_manifest.json is not valid JSON") from exc
    if not isinstance(manifest, dict):
        raise ValueError("New York Fed source manifest must be an object")
    return manifest, _sha256(path)


def _validate_source_manifest(
    raw_dir: Path, manifest: Mapping[str, object]
) -> dict[str, dict[str, object]]:
    sources = manifest.get("sources")
    if not isinstance(sources, dict):
        raise ValueError("New York Fed source manifest must contain a sources object")
    expected = {
        "indicative_sofr": INDICATIVE_FILENAME,
        "official_sofr": OFFICIAL_FILENAME,
    }
    validated: dict[str, dict[str, object]] = {}
    for key, filename in expected.items():
        item = sources.get(key)
        if not isinstance(item, dict):
            raise ValueError(f"source manifest is missing {key!r}")
        if item.get("filename") != filename:
            raise ValueError(f"source manifest filename mismatch for {key}")
        path = raw_dir / filename
        if not path.is_file():
            raise FileNotFoundError(path)
        actual_hash = _sha256(path)
        if item.get("sha256") != actual_hash:
            raise ValueError(f"source hash mismatch for {key}")
        validated[key] = dict(item)
    return validated


def build_funding_dataset(
    raw_dir: str | Path,
    *,
    start: date = DEFAULT_START,
    cutoff: date = DEFAULT_CUTOFF,
    broker_spread: float = DEFAULT_BROKER_SPREAD,
) -> FundingDataset:
    """Build a gap-free daily SOFR-plus-spread series without networking."""

    if start > cutoff:
        raise ValueError("start must not be after cutoff")
    if not np.isfinite(broker_spread) or broker_spread < 0.0:
        raise ValueError("broker_spread must be finite and non-negative")

    source_dir = Path(raw_dir)
    source_manifest, source_manifest_sha256 = _load_source_manifest(source_dir)
    validated_sources = _validate_source_manifest(source_dir, source_manifest)
    indicative = read_indicative_sofr(source_dir / INDICATIVE_FILENAME)
    official = read_official_sofr(source_dir / OFFICIAL_FILENAME)

    if indicative.index[-1] != pd.Timestamp("2018-03-29"):
        raise ValueError("indicative SOFR must end on 2018-03-29")
    if official.index[0] != OFFICIAL_SOFR_START:
        raise ValueError("official SOFR must begin on 2018-04-02")

    start_timestamp = pd.Timestamp(start)
    cutoff_timestamp = pd.Timestamp(cutoff)
    indicative = indicative.loc[
        start_timestamp : OFFICIAL_SOFR_START - pd.Timedelta(days=1)
    ]
    official = official.loc[OFFICIAL_SOFR_START:cutoff_timestamp]
    if indicative.empty or indicative.index[0] != start_timestamp:
        raise ValueError(f"indicative SOFR does not cover project start {start}")
    if official.empty or official.index[-1] != cutoff_timestamp:
        raise ValueError(f"official SOFR does not cover cutoff {cutoff}")

    observations = pd.concat([indicative, official]).sort_index()
    if observations.index.has_duplicates:
        raise ValueError("combined SOFR observations contain duplicate value dates")

    calendar = pd.date_range(start_timestamp, cutoff_timestamp, freq="D", name="date")
    applicable = observations.copy()
    applicable["reference_value_date"] = applicable.index
    applicable = applicable.reindex(calendar).ffill()
    if applicable.isna().any().any():
        raise ValueError("daily SOFR series could not be filled from the project start")
    applicable["broker_spread_annual"] = float(broker_spread)
    applicable["borrow_rate_annual"] = (
        applicable["reference_rate_annual"] + applicable["broker_spread_annual"]
    )
    applicable["rate_carried_forward"] = (
        applicable.index != pd.DatetimeIndex(applicable["reference_value_date"])
    )
    daily = applicable.loc[:, DAILY_COLUMNS].copy()

    manifest: dict[str, object] = {
        "schema_version": 1,
        "pipeline": "factor_portfolio.rates",
        "network_required": False,
        "currency": "USD",
        "start_date": start.isoformat(),
        "cutoff_date": cutoff.isoformat(),
        "reference_observations": int(len(observations)),
        "daily_observations": int(len(daily)),
        "broker_spread_annual": float(broker_spread),
        "day_count_convention": "ACT/360",
        "transition_rule": (
            "indicative SOFR through 2018-03-29; official SOFR from 2018-04-02"
        ),
        "calendar_policy": (
            "calendar-daily; each value-date rate carries forward until the next value date"
        ),
        "source_manifest_sha256": source_manifest_sha256,
        "source_snapshot": source_manifest,
        "sources": validated_sources,
        "release_status": (
            "redistributable subject to New York Fed Terms of Use, attribution, and notice"
        ),
    }
    return FundingDataset(
        reference_observations=observations,
        daily_borrow_rates=daily,
        manifest=manifest,
    )


def _csv_bytes(frame: pd.DataFrame) -> bytes:
    buffer = io.StringIO(newline="")
    frame.to_csv(
        buffer,
        index=True,
        index_label="date",
        date_format="%Y-%m-%d",
        float_format="%.8f",
        lineterminator="\n",
    )
    return buffer.getvalue().encode("utf-8")


def write_funding_dataset(
    dataset: FundingDataset, output_dir: str | Path
) -> dict[str, Path]:
    """Write byte-stable financing CSV files and their checksum manifest."""

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    observations_path = destination / "reference_rate_observations_usd.csv"
    daily_path = destination / "daily_borrow_rates_usd.csv"
    manifest_path = destination / "funding_manifest.json"
    observations_payload = _csv_bytes(dataset.reference_observations)
    daily_payload = _csv_bytes(dataset.daily_borrow_rates)
    manifest = dict(dataset.manifest)
    manifest["canonical_files"] = {
        observations_path.name: {
            "sha256": _sha256_bytes(observations_payload),
            "rows": len(dataset.reference_observations),
        },
        daily_path.name: {
            "sha256": _sha256_bytes(daily_payload),
            "rows": len(dataset.daily_borrow_rates),
        },
    }
    manifest_payload = (
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")
    payloads = {
        observations_path: observations_payload,
        daily_path: daily_payload,
        manifest_path: manifest_payload,
    }
    write_immutable_payloads(payloads, 'funding')
    return {
        "observations": observations_path,
        "daily": daily_path,
        "manifest": manifest_path,
    }


def load_funding_dataset(input_dir: str | Path) -> FundingDataset:
    """Load and verify a canonical financing snapshot."""

    source = Path(input_dir)
    manifest_path = source / "funding_manifest.json"
    bounded_input(manifest_path)
    if not manifest_path.is_file():
        raise FileNotFoundError(manifest_path)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError("funding manifest is not valid JSON") from exc
    canonical_files = manifest.get("canonical_files")
    if not isinstance(canonical_files, dict):
        raise ValueError("funding manifest is missing canonical_files")

    names = ("reference_rate_observations_usd.csv", "daily_borrow_rates_usd.csv")
    for filename in names:
        record = canonical_files.get(filename)
        if not isinstance(record, dict) or not isinstance(record.get("sha256"), str):
            raise ValueError(f"funding manifest is missing checksum for {filename}")
        path = source / filename
        bounded_input(path)
        if not path.is_file():
            raise FileNotFoundError(path)
        if _sha256(path) != record["sha256"]:
            raise ValueError(f"funding checksum mismatch for {filename}")

    observations = pd.read_csv(
        source / names[0],
        index_col="date",
        parse_dates=["date"],
        keep_default_na=False,
    )
    daily = pd.read_csv(
        source / names[1],
        index_col="date",
        parse_dates=["date", "reference_value_date"],
        keep_default_na=False,
    )
    observations.index = pd.DatetimeIndex(observations.index, name="date")
    daily.index = pd.DatetimeIndex(daily.index, name="date")
    if observations.columns.tolist() != OBSERVATION_COLUMNS:
        raise ValueError("funding observation columns differ from schema")
    if daily.columns.tolist() != DAILY_COLUMNS:
        raise ValueError("daily funding columns differ from schema")
    if observations.empty or observations.index.has_duplicates:
        raise ValueError("funding observations must be non-empty and unique")
    if not observations.index.is_monotonic_increasing:
        raise ValueError("funding observations must be sorted")
    expected_calendar = pd.date_range(
        manifest.get("start_date"), manifest.get("cutoff_date"), freq="D", name="date"
    )
    if not daily.index.equals(expected_calendar):
        raise ValueError("daily funding data do not match the declared calendar")
    if len(observations) != manifest.get("reference_observations"):
        raise ValueError("funding observation count differs from manifest")
    if len(daily) != manifest.get("daily_observations"):
        raise ValueError("daily funding count differs from manifest")
    numeric = daily[
        ["reference_rate_annual", "broker_spread_annual", "borrow_rate_annual"]
    ]
    if numeric.isna().any().any() or not np.isfinite(numeric.to_numpy()).all():
        raise ValueError("daily funding data contain invalid numeric values")
    if not np.allclose(
        daily["borrow_rate_annual"],
        daily["reference_rate_annual"] + daily["broker_spread_annual"],
        rtol=0.0,
        atol=5e-10,
    ):
        raise ValueError("daily borrowing rates do not equal reference rate plus spread")
    if (daily["reference_value_date"] > daily.index).any():
        raise ValueError("daily funding data use a future reference value date")
    expected_carried = daily["reference_value_date"] != daily.index
    if not (daily["rate_carried_forward"] == expected_carried).all():
        raise ValueError("daily carry-forward flags are inconsistent")
    observed_daily = daily.loc[observations.index]
    if not np.allclose(
        observed_daily["reference_rate_annual"],
        observations["reference_rate_annual"],
        rtol=0.0,
        atol=5e-10,
    ):
        raise ValueError("daily reference rates do not reconcile to observations")
    return FundingDataset(
        reference_observations=observations,
        daily_borrow_rates=daily,
        manifest=manifest,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the frozen New York Fed SOFR-plus-spread dataset offline."
    )
    parser.add_argument(
        "--raw-dir", type=Path, default=Path("data/raw/rates/new_york_fed")
    )
    parser.add_argument("--output-dir", type=Path, default=Path("data/canonical"))
    parser.add_argument("--start", type=date.fromisoformat, default=DEFAULT_START)
    parser.add_argument("--cutoff", type=date.fromisoformat, default=DEFAULT_CUTOFF)
    parser.add_argument("--broker-spread", type=float, default=DEFAULT_BROKER_SPREAD)
    args = parser.parse_args(argv)

    dataset = build_funding_dataset(
        args.raw_dir,
        start=args.start,
        cutoff=args.cutoff,
        broker_spread=args.broker_spread,
    )
    paths = write_funding_dataset(dataset, args.output_dir)
    print(
        f"Built {len(dataset.daily_borrow_rates)} daily rates from "
        f"{dataset.daily_borrow_rates.index[0].date()} through "
        f"{dataset.daily_borrow_rates.index[-1].date()}."
    )
    for label, path in paths.items():
        print(f"{label}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
