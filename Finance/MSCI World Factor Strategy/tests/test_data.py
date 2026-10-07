from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from factor_portfolio.data import (
    ProductSpec,
    build_canonical_dataset,
    load_canonical_dataset,
    read_ishares_nav,
    write_canonical_dataset,
)


def _workbook_xml(
    *,
    product_name: str,
    isin: str,
    observations: list[tuple[str, float]],
    core_layout: bool,
) -> bytes:
    if core_layout:
        metadata_sheet = "Overview"
        history_sheet = "Historical"
        history_rows = "".join(
            f"<ss:Row><ss:Cell><ss:Data>{day}</ss:Data></ss:Cell>"
            f"<ss:Cell><ss:Data>USD</ss:Data></ss:Cell>"
            f"<ss:Cell><ss:Data>{nav}</ss:Data></ss:Cell></ss:Row>"
            for day, nav in observations
        )
        header = (
            "<ss:Row><ss:Cell><ss:Data>As Of</ss:Data></ss:Cell>"
            "<ss:Cell><ss:Data>Currency</ss:Data></ss:Cell>"
            "<ss:Cell><ss:Data>NAV per Share</ss:Data></ss:Cell></ss:Row>"
        )
        launch_key = "Share Class Launch Date"
    else:
        metadata_sheet = "Key Facts"
        history_sheet = "Historical NAVs"
        history_rows = "".join(
            f"<ss:Row><ss:Cell><ss:Data>{day}</ss:Data></ss:Cell>"
            f"<ss:Cell><ss:Data>{nav}</ss:Data></ss:Cell></ss:Row>"
            for day, nav in observations
        )
        header = ""
        launch_key = "Inception Date"

    xml = f"""<?xml version="1.0"?>
<ss:Workbook xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">
  <ss:Worksheet ss:Name="{metadata_sheet}"><ss:Table>
    <ss:Row><ss:Cell><ss:Data>{product_name}</ss:Data></ss:Cell></ss:Row>
    <ss:Row><ss:Cell><ss:Data>{launch_key}</ss:Data></ss:Cell><ss:Cell><ss:Data>03/Oct/2014</ss:Data></ss:Cell></ss:Row>
    <ss:Row><ss:Cell><ss:Data>Share Class Currency</ss:Data></ss:Cell><ss:Cell><ss:Data>USD</ss:Data></ss:Cell></ss:Row>
    <ss:Row><ss:Cell><ss:Data>{'Fund Base Currency' if core_layout else 'Base Currency'}</ss:Data></ss:Cell><ss:Cell><ss:Data>USD</ss:Data></ss:Cell></ss:Row>
    <ss:Row><ss:Cell><ss:Data>ISIN</ss:Data></ss:Cell><ss:Cell><ss:Data>{isin}</ss:Data></ss:Cell></ss:Row>
  </ss:Table></ss:Worksheet>
  <ss:Worksheet ss:Name="{history_sheet}"><ss:Table>{header}{history_rows}</ss:Table></ss:Worksheet>
</ss:Workbook>"""
    return xml.encode("utf-8")


def _write_sources(raw_dir: Path, *, missing_quality_date: bool = False) -> tuple[ProductSpec, ...]:
    raw_dir.mkdir(parents=True, exist_ok=True)
    specs = (
        ProductSpec("core", "Core ETF", "IE0000000001", "core.xls", "Historical", 0, 2, 1),
        ProductSpec("momentum", "Momentum ETF", "IE0000000002", "momentum.xls", "Historical NAVs", 0, 1),
        ProductSpec("quality", "Quality ETF", "IE0000000003", "quality.xls", "Historical NAVs", 0, 1),
        ProductSpec("value", "Value ETF", "IE0000000004", "value.xls", "Historical NAVs", 0, 1),
    )
    core_observations = [
        ("02/Oct/2014", 99.0),
        ("03/Oct/2014", 100.0),
        ("29/Aug/2026", 120.0),
        ("31/Aug/2026", 121.0),
        ("01/Sept/2026", 122.0),
    ]
    factor_observations = [
        ("03/Oct/2014", 25.0),
        ("29/Aug/2026", 30.0),
        ("31/Aug/2026", 31.0),
        ("01/Sept/2026", 32.0),
    ]
    for spec in specs:
        observations = core_observations if spec.sleeve == "core" else factor_observations
        if spec.sleeve == "quality" and missing_quality_date:
            observations = [item for item in observations if item[0] != "29/Aug/2026"]
        raw = _workbook_xml(
            product_name=spec.product_name,
            isin=spec.isin,
            observations=observations,
            core_layout=spec.sleeve == "core",
        )
        if spec.sleeve == "core":
            raw = b"\xef\xbb\xbf\xef\xbb\xbf" + raw
        (raw_dir / spec.filename).write_bytes(raw)
    return specs


def test_reads_double_bom_spreadsheetml_and_validates_identity(tmp_path: Path) -> None:
    specs = _write_sources(tmp_path)

    product = read_ishares_nav(tmp_path / specs[0].filename, specs[0])

    assert product.spec.isin == "IE0000000001"
    assert product.currency == "USD"
    assert product.base_currency == "USD"
    assert product.nav.index[0] == pd.Timestamp("2014-10-02")
    assert product.nav.iloc[-1] == 122.0


def test_records_but_excludes_explicit_missing_nav_marker(tmp_path: Path) -> None:
    specs = _write_sources(tmp_path)
    source = tmp_path / specs[0].filename
    raw = source.read_bytes().replace(
        b"<ss:Data>99.0</ss:Data>", b"<ss:Data>--</ss:Data>", 1
    )
    source.write_bytes(raw)

    product = read_ishares_nav(source, specs[0])

    assert product.excluded_missing_nav_dates == (date(2014, 10, 2),)
    assert pd.Timestamp("2014-10-02") not in product.nav.index


def test_builds_strict_common_window_through_cutoff(tmp_path: Path) -> None:
    specs = _write_sources(tmp_path / "raw")

    dataset = build_canonical_dataset(
        tmp_path / "raw", cutoff=date(2026, 8, 31), products=specs
    )

    assert list(dataset.nav_usd.columns) == ["core", "momentum", "quality", "value"]
    assert dataset.nav_usd.index[0] == pd.Timestamp("2014-10-03")
    assert dataset.nav_usd.index[-1] == pd.Timestamp("2026-08-31")
    assert len(dataset.nav_usd) == 3
    assert (dataset.returns_usd.iloc[0] == 0.0).all()
    assert dataset.manifest["common_observations"] == 3


def test_calendar_mismatch_fails_loudly(tmp_path: Path) -> None:
    specs = _write_sources(tmp_path / "raw", missing_quality_date=True)

    with pytest.raises(ValueError, match="calendar mismatch for quality"):
        build_canonical_dataset(
            tmp_path / "raw", cutoff=date(2026, 8, 31), products=specs
        )


def test_wrong_isin_fails_loudly(tmp_path: Path) -> None:
    specs = _write_sources(tmp_path)
    wrong = ProductSpec(
        **{**specs[0].__dict__, "isin": "IE0099999999"}
    )

    with pytest.raises(ValueError, match="expected ISIN"):
        read_ishares_nav(tmp_path / wrong.filename, wrong)


def test_canonical_outputs_are_byte_identical(tmp_path: Path) -> None:
    specs = _write_sources(tmp_path / "raw")
    dataset = build_canonical_dataset(
        tmp_path / "raw", cutoff=date(2026, 8, 31), products=specs
    )

    first = write_canonical_dataset(dataset, tmp_path / "first")
    second = write_canonical_dataset(dataset, tmp_path / "second")
    repeated = write_canonical_dataset(dataset, tmp_path / "first")

    for key in first:
        assert first[key].read_bytes() == second[key].read_bytes()
        assert first[key].read_bytes() == repeated[key].read_bytes()

    loaded = load_canonical_dataset(tmp_path / "first")
    pd.testing.assert_frame_equal(loaded.nav_usd, dataset.nav_usd)
    pd.testing.assert_frame_equal(
        loaded.returns_usd, dataset.returns_usd, rtol=1e-10, atol=5e-13
    )


def test_canonical_loader_rejects_tampering(tmp_path: Path) -> None:
    specs = _write_sources(tmp_path / "raw")
    dataset = build_canonical_dataset(
        tmp_path / "raw", cutoff=date(2026, 8, 31), products=specs
    )
    paths = write_canonical_dataset(dataset, tmp_path / "canonical")
    paths["nav"].write_bytes(paths["nav"].read_bytes() + b"\n")

    with pytest.raises(ValueError, match="checksum mismatch"):
        load_canonical_dataset(tmp_path / "canonical")
