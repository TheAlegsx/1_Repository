"""Deterministic loader for frozen iShares SpreadsheetML NAV snapshots."""

from __future__ import annotations

import argparse
import codecs
import hashlib
import io
import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable, Mapping
from xml.etree import ElementTree as ET

import numpy as np
import pandas as pd

from .security_io import read_bounded_bytes, parse_bounded_xml, MAX_SHEET_COLUMNS, write_immutable_payloads, bounded_input


SPREADSHEET_NS = "urn:schemas-microsoft-com:office:spreadsheet"
SS_NAME = f"{{{SPREADSHEET_NS}}}Name"
SS_INDEX = f"{{{SPREADSHEET_NS}}}Index"
DEFAULT_CUTOFF = date(2026, 8, 31)


@dataclass(frozen=True)
class ProductSpec:
    """Expected identity and worksheet layout for one ETF source file."""

    sleeve: str
    product_name: str
    isin: str
    filename: str
    historical_sheet: str
    date_column: int
    nav_column: int
    currency_column: int | None = None


@dataclass(frozen=True)
class ParsedProduct:
    """Validated source metadata and its complete NAV history."""

    spec: ProductSpec
    nav: pd.Series
    source_sha256: str
    source_first_date: date
    source_last_date: date
    currency: str
    base_currency: str
    inception_date: str
    excluded_missing_nav_dates: tuple[date, ...]


@dataclass(frozen=True)
class CanonicalDataset:
    """Common-calendar NAV and return data plus deterministic provenance."""

    nav_usd: pd.DataFrame
    returns_usd: pd.DataFrame
    manifest: dict[str, object]


DEFAULT_PRODUCTS: tuple[ProductSpec, ...] = (
    ProductSpec(
        sleeve="core",
        product_name="iShares Core MSCI World UCITS ETF",
        isin="IE00B4L5Y983",
        filename="iShares-Core-MSCI-World-UCITS-ETF_fund.xls",
        historical_sheet="Historical",
        date_column=0,
        nav_column=2,
        currency_column=1,
    ),
    ProductSpec(
        sleeve="momentum",
        product_name="iShares Edge MSCI World Momentum Factor UCITS ETF",
        isin="IE00BP3QZ825",
        filename="iShares-Edge-MSCI-World-Momentum-Factor-UCITS-ETF-USD-Acc_fund.xls",
        historical_sheet="Historical NAVs",
        date_column=0,
        nav_column=1,
    ),
    ProductSpec(
        sleeve="quality",
        product_name="iShares Edge MSCI World Quality Factor UCITS ETF",
        isin="IE00BP3QZ601",
        filename="iShares-Edge-MSCI-World-Quality-Factor-UCITS-ETF-USD-Acc_fund.xls",
        historical_sheet="Historical NAVs",
        date_column=0,
        nav_column=1,
    ),
    ProductSpec(
        sleeve="value",
        product_name="iShares Edge MSCI World Value Factor UCITS ETF",
        isin="IE00BP3QZB59",
        filename="iShares-Edge-MSCI-World-Value-Factor-UCITS-ETF-USD-Acc_fund.xls",
        historical_sheet="Historical NAVs",
        date_column=0,
        nav_column=1,
    ),
)


_MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _parse_date(value: str) -> date | None:
    match = re.fullmatch(r"\s*(\d{1,2})[/-]([A-Za-z]+)[/-](\d{4})\s*", value)
    if match is None:
        return None
    day_text, month_text, year_text = match.groups()
    month = _MONTHS.get(month_text.lower())
    if month is None:
        raise ValueError(f"unsupported month name: {month_text!r}")
    return date(int(year_text), month, int(day_text))


def _parse_number(value: str) -> float:
    cleaned = value.strip().replace(",", "").replace("'", "").replace("’", "")
    try:
        return float(cleaned)
    except ValueError as exc:
        raise ValueError(f"invalid numeric value: {value!r}") from exc


def _read_root(path: Path) -> ET.Element:
    raw = read_bounded_bytes(path)
    while raw.startswith(codecs.BOM_UTF8):
        raw = raw[len(codecs.BOM_UTF8) :]
    try:
        return parse_bounded_xml(raw)
    except ET.ParseError as exc:
        raise ValueError(f"{path.name} is not valid SpreadsheetML XML") from exc


def _row_values(row: ET.Element) -> list[str]:
    values: list[str] = []
    column = 1
    for cell in row.findall(f"{{{SPREADSHEET_NS}}}Cell"):
        if column > MAX_SHEET_COLUMNS:
            raise ValueError('SpreadsheetML row exceeds the declared column budget')
        explicit_index = cell.get(SS_INDEX)
        if explicit_index is not None:
            target = int(explicit_index)
            if target < column or target > MAX_SHEET_COLUMNS:
                raise ValueError('SpreadsheetML sparse column index exceeds the declared bounds')
            values.extend([""] * (target - column))
            column = target
        data = cell.find(f"{{{SPREADSHEET_NS}}}Data")
        values.append("" if data is None or data.text is None else data.text.strip())
        column += 1
    return values


def _worksheets(root: ET.Element) -> dict[str, list[list[str]]]:
    sheets: dict[str, list[list[str]]] = {}
    for worksheet in root.findall(f".//{{{SPREADSHEET_NS}}}Worksheet"):
        name = worksheet.get(SS_NAME)
        if not name:
            continue
        rows = worksheet.findall(
            f".//{{{SPREADSHEET_NS}}}Table/{{{SPREADSHEET_NS}}}Row"
        )
        sheets[name] = [_row_values(row) for row in rows]
    return sheets


def _metadata(sheets: Mapping[str, list[list[str]]]) -> dict[str, str]:
    result: dict[str, str] = {}
    for rows in sheets.values():
        for row in rows:
            if len(row) >= 2 and row[0] and row[1]:
                result.setdefault(row[0], row[1])
    return result


def _all_text(root: ET.Element) -> str:
    return " ".join(
        node.text.strip()
        for node in root.iter(f"{{{SPREADSHEET_NS}}}Data")
        if node.text and node.text.strip()
    )


def read_ishares_nav(path: str | Path, spec: ProductSpec) -> ParsedProduct:
    """Read and validate one iShares SpreadsheetML NAV file."""

    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(source)

    root = _read_root(source)
    sheets = _worksheets(root)
    if spec.historical_sheet not in sheets:
        raise ValueError(
            f"{source.name} is missing worksheet {spec.historical_sheet!r}"
        )

    all_text = _all_text(root)
    isins = sorted(set(re.findall(r"IE[0-9A-Z]{10}", all_text)))
    if spec.isin not in isins:
        raise ValueError(
            f"{source.name} does not contain expected ISIN {spec.isin}; found {isins}"
        )
    if spec.product_name not in all_text:
        raise ValueError(
            f"{source.name} does not contain expected product name {spec.product_name!r}"
        )

    metadata = _metadata(sheets)
    currency = metadata.get("Share Class Currency", "")
    base_currency = metadata.get("Base Currency") or metadata.get("Fund Base Currency", "")
    if currency != "USD" or base_currency != "USD":
        raise ValueError(
            f"{source.name} must have USD share-class and base currencies; "
            f"found {currency!r} and {base_currency!r}"
        )

    observations: list[tuple[date, float]] = []
    excluded_missing_nav_dates: list[date] = []
    observed_currencies: set[str] = set()
    required_column = max(spec.date_column, spec.nav_column, spec.currency_column or 0)
    for row in sheets[spec.historical_sheet]:
        if len(row) <= spec.date_column:
            continue
        observation_date = _parse_date(row[spec.date_column])
        if observation_date is None:
            continue
        if len(row) <= required_column:
            raise ValueError(f"incomplete historical row on {observation_date}")
        raw_nav = row[spec.nav_column].strip()
        if raw_nav in {"", "-", "--"}:
            excluded_missing_nav_dates.append(observation_date)
            continue
        nav = _parse_number(raw_nav)
        if not np.isfinite(nav) or nav <= 0.0:
            raise ValueError(f"non-positive or non-finite NAV on {observation_date}")
        if spec.currency_column is not None:
            observed_currencies.add(row[spec.currency_column])
        observations.append((observation_date, nav))

    if not observations:
        raise ValueError(f"{source.name} contains no NAV observations")
    if observed_currencies and observed_currencies != {"USD"}:
        raise ValueError(
            f"{source.name} historical rows contain currencies {sorted(observed_currencies)}"
        )

    dates = [item[0] for item in observations]
    if len(dates) != len(set(dates)):
        duplicates = sorted({item for item in dates if dates.count(item) > 1})
        raise ValueError(f"{source.name} contains duplicate dates: {duplicates[:5]}")

    nav = pd.Series(
        [value for _, value in observations],
        index=pd.DatetimeIndex(dates, name="date"),
        name=spec.sleeve,
        dtype=float,
    ).sort_index()
    inception = metadata.get("Inception Date") or metadata.get(
        "Share Class Launch Date", ""
    )
    return ParsedProduct(
        spec=spec,
        nav=nav,
        source_sha256=_sha256(source),
        source_first_date=nav.index[0].date(),
        source_last_date=nav.index[-1].date(),
        currency=currency,
        base_currency=base_currency,
        inception_date=inception,
        excluded_missing_nav_dates=tuple(sorted(excluded_missing_nav_dates)),
    )


def _load_source_manifest(raw_dir: Path) -> tuple[dict[str, object] | None, str | None]:
    path = raw_dir / "source_manifest.json"
    if not path.exists():
        return None, None
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError("source_manifest.json is not valid JSON") from exc
    return manifest, _sha256(path)


def _validate_source_manifest(
    manifest: Mapping[str, object] | None,
    parsed: Iterable[ParsedProduct],
) -> None:
    if manifest is None:
        return
    products = manifest.get("products")
    if not isinstance(products, dict):
        raise ValueError("source_manifest.json must contain a products object")
    for product in parsed:
        item = products.get(product.spec.sleeve)
        if not isinstance(item, dict):
            raise ValueError(
                f"source_manifest.json is missing {product.spec.sleeve!r}"
            )
        if item.get("filename") != product.spec.filename:
            raise ValueError(
                f"source manifest filename mismatch for {product.spec.sleeve}"
            )
        if item.get("sha256") != product.source_sha256:
            raise ValueError(f"source hash mismatch for {product.spec.sleeve}")


def build_canonical_dataset(
    raw_dir: str | Path,
    *,
    cutoff: date = DEFAULT_CUTOFF,
    products: Iterable[ProductSpec] = DEFAULT_PRODUCTS,
) -> CanonicalDataset:
    """Build a strict common-calendar dataset without network access."""

    source_dir = Path(raw_dir)
    specs = tuple(products)
    parsed = tuple(read_ishares_nav(source_dir / spec.filename, spec) for spec in specs)
    source_manifest, source_manifest_sha256 = _load_source_manifest(source_dir)
    _validate_source_manifest(source_manifest, parsed)

    cutoff_timestamp = pd.Timestamp(cutoff)
    for product in parsed:
        if cutoff_timestamp not in product.nav.index:
            raise ValueError(
                f"{product.spec.sleeve} has no NAV observation on cutoff {cutoff}"
            )

    common_start = max(product.source_first_date for product in parsed)
    start_timestamp = pd.Timestamp(common_start)
    trimmed = {
        product.spec.sleeve: product.nav.loc[start_timestamp:cutoff_timestamp]
        for product in parsed
    }
    expected_calendar = set(next(iter(trimmed.values())).index)
    for sleeve, series in trimmed.items():
        current_calendar = set(series.index)
        if current_calendar != expected_calendar:
            missing = sorted(expected_calendar - current_calendar)
            extra = sorted(current_calendar - expected_calendar)
            raise ValueError(
                f"calendar mismatch for {sleeve}: {len(missing)} missing, "
                f"{len(extra)} extra observations"
            )

    navs = pd.concat(
        [trimmed[spec.sleeve].rename(spec.sleeve) for spec in specs], axis=1
    ).sort_index()
    if navs.isna().any().any():
        raise ValueError("canonical NAV data contain missing values")
    if navs.index.has_duplicates or not navs.index.is_monotonic_increasing:
        raise ValueError("canonical NAV dates must be unique and sorted")
    if navs.index[0].date() != common_start or navs.index[-1].date() != cutoff:
        raise AssertionError("canonical date boundary differs from validated range")

    returns = navs.pct_change(fill_method=None)
    returns.iloc[0] = 0.0
    if not np.isfinite(returns.to_numpy()).all():
        raise ValueError("canonical returns contain non-finite values")

    source_entries: dict[str, object] = {}
    for product in parsed:
        source_entries[product.spec.sleeve] = {
            "product_name": product.spec.product_name,
            "isin": product.spec.isin,
            "filename": product.spec.filename,
            "sha256": product.source_sha256,
            "currency": product.currency,
            "base_currency": product.base_currency,
            "inception_date_as_published": product.inception_date,
            "source_first_date": product.source_first_date.isoformat(),
            "source_last_date": product.source_last_date.isoformat(),
            "source_observations": int(product.nav.size),
            "excluded_missing_nav_dates": [
                item.isoformat() for item in product.excluded_missing_nav_dates
            ],
        }

    manifest: dict[str, object] = {
        "schema_version": 1,
        "pipeline": "factor_portfolio.data",
        "network_required": False,
        "cutoff_date": cutoff.isoformat(),
        "common_start_date": navs.index[0].date().isoformat(),
        "common_end_date": navs.index[-1].date().isoformat(),
        "common_observations": int(len(navs)),
        "columns": list(navs.columns),
        "nav_field": "daily USD fund NAV",
        "return_method": "adjacent NAV percentage change; first common row set to 0",
        "calendar_policy": "strict identical calendars after common start; no filling",
        "release_status": "private research data; redistribution not cleared",
        "source_manifest_sha256": source_manifest_sha256,
        "source_snapshot": source_manifest,
        "sources": source_entries,
    }
    return CanonicalDataset(nav_usd=navs, returns_usd=returns, manifest=manifest)


def write_canonical_dataset(
    dataset: CanonicalDataset,
    output_dir: str | Path,
) -> dict[str, Path]:
    """Write byte-stable CSV files and a manifest with their checksums."""

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    nav_path = destination / "daily_nav_usd.csv"
    returns_path = destination / "daily_returns_usd.csv"
    manifest_path = destination / "manifest.json"

    def csv_bytes(frame: pd.DataFrame, float_format: str) -> bytes:
        buffer = io.StringIO(newline="")
        frame.to_csv(
            buffer,
            index=True,
            index_label="date",
            date_format="%Y-%m-%d",
            float_format=float_format,
            lineterminator="\n",
        )
        return buffer.getvalue().encode("utf-8")

    nav_payload = csv_bytes(dataset.nav_usd, "%.6f")
    returns_payload = csv_bytes(dataset.returns_usd, "%.12f")
    manifest = dict(dataset.manifest)
    manifest["canonical_files"] = {
        nav_path.name: {
            "sha256": _sha256_bytes(nav_payload),
            "rows": len(dataset.nav_usd),
        },
        returns_path.name: {
            "sha256": _sha256_bytes(returns_payload),
            "rows": len(dataset.returns_usd),
        },
    }
    manifest_text = json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    payloads = {
        nav_path: nav_payload,
        returns_path: returns_payload,
        manifest_path: manifest_text.encode("utf-8"),
    }
    write_immutable_payloads(payloads, 'canonical')
    return {"nav": nav_path, "returns": returns_path, "manifest": manifest_path}


def load_canonical_dataset(input_dir: str | Path) -> CanonicalDataset:
    """Load a canonical snapshot only after verifying its manifest and contents."""

    source = Path(input_dir)
    manifest_path = source / "manifest.json"
    bounded_input(manifest_path)
    if not manifest_path.is_file():
        raise FileNotFoundError(manifest_path)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError("canonical manifest is not valid JSON") from exc

    canonical_files = manifest.get("canonical_files")
    if not isinstance(canonical_files, dict):
        raise ValueError("canonical manifest is missing canonical_files")
    required = ("daily_nav_usd.csv", "daily_returns_usd.csv")
    for filename in required:
        record = canonical_files.get(filename)
        if not isinstance(record, dict) or not isinstance(record.get("sha256"), str):
            raise ValueError(f"canonical manifest is missing checksum for {filename}")
        path = source / filename
        bounded_input(path)
        if not path.is_file():
            raise FileNotFoundError(path)
        if _sha256(path) != record["sha256"]:
            raise ValueError(f"canonical checksum mismatch for {filename}")

    navs = pd.read_csv(source / required[0], index_col="date", parse_dates=["date"])
    returns = pd.read_csv(source / required[1], index_col="date", parse_dates=["date"])
    navs.index = pd.DatetimeIndex(navs.index, name="date")
    returns.index = pd.DatetimeIndex(returns.index, name="date")

    expected_columns = manifest.get("columns")
    if not isinstance(expected_columns, list) or navs.columns.tolist() != expected_columns:
        raise ValueError("canonical NAV columns differ from manifest")
    if returns.columns.tolist() != expected_columns:
        raise ValueError("canonical return columns differ from manifest")
    if not navs.index.equals(returns.index):
        raise ValueError("canonical NAV and return calendars differ")
    if len(navs) != manifest.get("common_observations"):
        raise ValueError("canonical row count differs from manifest")
    if navs.empty or navs.index.has_duplicates or not navs.index.is_monotonic_increasing:
        raise ValueError("canonical dates must be non-empty, unique, and sorted")
    if navs.index[0].date().isoformat() != manifest.get("common_start_date"):
        raise ValueError("canonical start date differs from manifest")
    if navs.index[-1].date().isoformat() != manifest.get("common_end_date"):
        raise ValueError("canonical end date differs from manifest")
    if navs.isna().any().any() or returns.isna().any().any():
        raise ValueError("canonical data contain missing values")
    if not np.isfinite(navs.to_numpy()).all() or not np.isfinite(returns.to_numpy()).all():
        raise ValueError("canonical data contain non-finite values")
    if (navs <= 0.0).any().any():
        raise ValueError("canonical NAV data contain non-positive values")

    expected_returns = navs.pct_change(fill_method=None)
    expected_returns.iloc[0] = 0.0
    if not np.allclose(
        returns.to_numpy(), expected_returns.to_numpy(), rtol=1e-10, atol=5e-13
    ):
        raise ValueError("canonical returns do not reconcile to canonical NAV data")

    return CanonicalDataset(nav_usd=navs, returns_usd=returns, manifest=manifest)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the frozen local iShares NAV dataset without network access."
    )
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw/ishares"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/canonical"))
    parser.add_argument("--cutoff", type=date.fromisoformat, default=DEFAULT_CUTOFF)
    args = parser.parse_args(argv)

    dataset = build_canonical_dataset(args.raw_dir, cutoff=args.cutoff)
    paths = write_canonical_dataset(dataset, args.output_dir)
    print(
        f"Built {len(dataset.nav_usd)} observations from "
        f"{dataset.nav_usd.index[0].date()} through {dataset.nav_usd.index[-1].date()}."
    )
    for label, path in paths.items():
        print(f"{label}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
