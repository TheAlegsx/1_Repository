"""Integrity-first immutable snapshots, with bounded numerical replay checking.

Checksums identify saved bytes; the replay tolerance does not replace integrity.
Only known continuous output columns qualify. Unknown columns stay exact.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from pathlib import Path
from typing import Mapping

import pandas as pd


CSV_RESOLUTION = 1e-12
REPLAY_ULPS = 8
REPRODUCTION_POLICY = "immutable-sha256-numerical-replay-v1"

_CONTINUOUS_OUTPUTS = frozenset({
    "opening_equity_usd", "opening_transaction_cost_usd", "ending_equity_usd",
    "cumulative_return", "cagr", "annualised_volatility", "maximum_drawdown",
    "sharpe_ratio", "beta_vs_core", "annualised_alpha_vs_core",
    "beta_vs_same_leverage_msci_world", "cumulative_financing_cost_usd",
    "cumulative_transaction_cost_usd", "minimum_leverage", "average_leverage",
    "maximum_leverage", "maximum_accounting_error_usd",
    "daily_correlation_with_index", "mean_daily_difference_vs_index_bps",
    "annualised_tracking_error_vs_index", "fees_usd", "commission_usd",
    "platform_fee_usd", "stamp_duty_usd", "spread_cost_usd", "other_fee_usd",
    "gross_assets_usd", "debt_usd", "equity_usd",
    "launch_median_half_spread_bps", "recent_median_half_spread_bps",
})
_OUTPUT_PREFIXES = ("factor_minus_core_", "core_", "ongoing_", "minimum_", "median_", "maximum_")


def _is_continuous_output(name: str) -> bool:
    if name in _CONTINUOUS_OUTPUTS:
        return True
    return any(
        name.startswith(prefix) and _is_continuous_output(name[len(prefix):])
        for prefix in _OUTPUT_PREFIXES
    )


def continuous_result_columns(frame: pd.DataFrame, *, levels: bool = False) -> set[str]:
    """Allow known metrics, or a caller-declared levels table's float columns.

    Scenario inputs, counts, ranks, booleans and unknown metrics stay exact.
    ``levels=True`` is reserved for equity/normalized-price output tables.
    """
    return {
        str(name) for name in frame.columns
        if pd.api.types.is_float_dtype(frame[name].dtype)
        and (levels or _is_continuous_output(str(name)))
    }


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)


def _manifest_records(payload: bytes, artifacts: Mapping[Path, bytes]) -> dict:
    manifest = json.loads(payload)
    records = manifest.get("result_files")
    expected = {path.name for path in artifacts}
    if not isinstance(records, dict) or set(records) != expected:
        raise ValueError("result manifest artifact set differs from expected files")
    for path, data in artifacts.items():
        record = records[path.name]
        if not isinstance(record, dict) or record.get("sha256") != hashlib.sha256(data).hexdigest():
            raise ValueError(f"result checksum mismatch: {path}")
        if "rows" in record and (
            type(record["rows"]) is not int or record["rows"] != data.count(b"\n") - 1
        ):
            raise ValueError(f"result row count mismatch: {path}")
    return manifest


def _semantics(manifest: dict) -> str:
    # Retain all record metadata (including rows); only byte hashes can differ.
    value = {key: val for key, val in manifest.items() if key != "result_files"}
    value["result_files"] = {
        name: {key: val for key, val in record.items() if key != "sha256"}
        for name, record in manifest["result_files"].items()
    }
    return _canonical(value)


def _csv_rows(payload: bytes) -> list[list[str]]:
    rows = list(csv.reader(io.StringIO(payload.decode("utf-8"), newline=""), strict=True))
    if not rows or len(rows[0]) != len(set(rows[0])) or any(len(row) != len(rows[0]) for row in rows):
        raise ValueError("invalid result CSV schema")
    return rows


def _equivalent_csv(saved: bytes, recomputed: bytes, continuous: set[str], path: Path) -> None:
    old, new = _csv_rows(saved), _csv_rows(recomputed)
    if old[0] != new[0] or len(old) != len(new) or not continuous.issubset(new[0]):
        raise FileExistsError(f"immutable result CSV schema differs: {path}")
    for row_number, (before, after) in enumerate(zip(old[1:], new[1:]), start=2):
        for name, left, right in zip(old[0], before, after):
            if left == right:
                continue
            accepted = False
            if name in continuous and left and right:
                try:
                    a, b = float(left), float(right)
                    accepted = math.isfinite(a) and math.isfinite(b) and (
                        a == b or abs(a - b) <= CSV_RESOLUTION + REPLAY_ULPS * max(math.ulp(a), math.ulp(b))
                    )
                except ValueError:
                    pass
            if not accepted:
                raise FileExistsError(
                    f"immutable result differs: {path}, row {row_number}, column {name}; "
                    "use a new output directory"
                )


def write_immutable_result_package(
    payloads: Mapping[Path, bytes],
    *,
    manifest_path: Path,
    continuous_columns: Mapping[Path, set[str]],
) -> str:
    """Create a fresh package or verify an existing one without rewriting it.

    Existing checksums are verified before comparing replay values. Partial
    packages fail closed. Manifest semantics and non-CSV payloads remain exact.
    Returns ``created``, ``byte_identical`` or ``numerically_equivalent``.
    """
    if manifest_path not in payloads or len({p.name for p in payloads}) != len(payloads):
        raise ValueError("invalid result package paths")
    if any(p.parent != manifest_path.parent for p in payloads):
        raise ValueError("result package files must share a directory")
    artifacts = {p: data for p, data in payloads.items() if p != manifest_path}
    if not set(continuous_columns).issubset(artifacts):
        raise ValueError("continuous columns target an unknown artifact")
    incoming = _manifest_records(payloads[manifest_path], artifacts)
    for path, columns in continuous_columns.items():
        if path.suffix != ".csv" or not columns.issubset(_csv_rows(artifacts[path])[0]):
            raise ValueError(f"invalid continuous column declaration: {path}")
    present = [path.exists() for path in payloads]
    if any(present) and not all(present):
        raise FileExistsError("incomplete immutable result package; use a new output directory")
    if not any(present):
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation also refuses a file appearing after preflight.
        for path, data in payloads.items():
            with path.open("xb") as handle:
                handle.write(data)
        return "created"
    saved_artifacts = {path: path.read_bytes() for path in artifacts}
    saved_manifest = manifest_path.read_bytes()
    existing = _manifest_records(saved_manifest, saved_artifacts)
    if _semantics(existing) != _semantics(incoming):
        raise FileExistsError("immutable result manifest semantics differ; use a new output directory")
    identical = saved_manifest == payloads[manifest_path]
    for path, data in artifacts.items():
        before = saved_artifacts[path]
        if before == data:
            continue
        identical = False
        if path.suffix == ".csv":
            _equivalent_csv(before, data, continuous_columns.get(path, set()), path)
        else:
            raise FileExistsError(f"immutable result payload differs: {path}; use a new output directory")
    if identical:
        return "byte_identical"
    print(f"Verified numerical reproduction; existing snapshot retained: {manifest_path.parent}")
    return "numerically_equivalent"
