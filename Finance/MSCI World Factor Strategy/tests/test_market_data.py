from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pandas as pd
import pytest
from openpyxl import Workbook

from factor_portfolio.market_data import (
    BloombergSpec,
    build_market_dataset,
    load_market_dataset,
    read_amundi_nav,
    read_bloomberg_hardcopy,
    write_market_dataset,
)


def _write_bloomberg(
    path: Path,
    security: str,
    rows: list[tuple[datetime, float, float | None, float | None, float | None]],
) -> None:
    workbook = Workbook()
    live = workbook.active
    live.title = "Worksheet"
    live["A1"] = "Security"
    live["B1"] = security
    live["A8"] = "=1+1"
    static = workbook.create_sheet("Tabelle1")
    static.append(["Security", security])
    static.append(["Start Date", min(item[0] for item in rows)])
    static.append(["End Date", max(item[0] for item in rows)])
    static.append(["Period", "D"])
    static.append(["Currency", "USD"])
    static.append([])
    static.append(["Date", "PX_LAST", "PX_BID", "PX_ASK", "VOLUME"])
    for row in sorted(rows, reverse=True):
        static.append(row)
    workbook.save(path)


def _write_amundi(path: Path) -> None:
    shared: list[str] = []

    def shared_index(value: str) -> int:
        if value not in shared:
            shared.append(value)
        return shared.index(value)

    values: dict[str, str | float] = {
        "C11": "Amundi MSCI World (2x) Leveraged UCITS ETF Acc",
        "C12": "FR0014010HV4",
        "C13": "MSCI World Leveraged 2X Daily (Net) USD Index",
        "C14": "Synthetic",
        "C15": "USD",
        "B27": "Date",
        "C27": "Official NAV",
        "E27": "Nav Currency",
        "B28": "01/09/2026",
        "C28": 13.0,
        "E28": "USD",
        "B29": "31/08/2026",
        "C29": 12.0,
        "E29": "USD",
        "B30": "30/08/2026",
        "C30": 11.0,
        "E30": "USD",
        "B31": "30/09/2025",
        "C31": 10.0,
        "E31": "USD",
    }
    cell_xml: list[str] = []
    for reference, value in values.items():
        row = int("".join(character for character in reference if character.isdigit()))
        if isinstance(value, str):
            cell_xml.append(
                f'<row r="{row}"><c r="{reference}" t="s"><v>{shared_index(value)}</v></c></row>'
            )
        else:
            cell_xml.append(f'<row r="{row}"><c r="{reference}"><v>{value}</v></c></row>')
    shared_xml = "".join(f"<si><t>{value}</t></si>" for value in shared)
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr(
            "xl/sharedStrings.xml",
            '<?xml version="1.0"?><sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            + shared_xml
            + "</sst>",
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            '<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
            + "".join(cell_xml)
            + "</sheetData></worksheet>",
        )


def test_bloomberg_reader_uses_static_sheet_and_exact_cutoff(tmp_path: Path) -> None:
    source = tmp_path / "listing.xlsx"
    _write_bloomberg(
        source,
        "TEST LN Equity",
        [
            (datetime(2025, 9, 1), 100.0, 99.9, 100.1, 10.0),
            (datetime(2026, 8, 31), 110.0, 109.9, 110.1, 20.0),
            (datetime(2026, 9, 1), 111.0, 110.9, 111.1, 30.0),
        ],
    )
    spec = BloombergSpec("test", "TEST LN Equity", source.name, "core")

    parsed = read_bloomberg_hardcopy(source, spec)

    assert parsed.data.index[-1] == pd.Timestamp("2026-08-31")
    expected = (110.1 - 109.9) / ((110.1 + 109.9) / 2.0) * 10_000.0
    assert parsed.data.loc["2026-08-31", "full_spread_bps"] == pytest.approx(expected)
    assert parsed.data.loc["2026-08-31", "half_spread_bps"] == pytest.approx(
        expected / 2.0
    )


def test_bloomberg_reader_rejects_negative_spread(tmp_path: Path) -> None:
    source = tmp_path / "listing.xlsx"
    _write_bloomberg(
        source,
        "TEST LN Equity",
        [(datetime(2026, 8, 31), 100.0, 100.1, 99.9, 10.0)],
    )
    spec = BloombergSpec("test", "TEST LN Equity", source.name, "core")

    with pytest.raises(ValueError, match="negative quoted spreads"):
        read_bloomberg_hardcopy(source, spec)


def test_amundi_reader_bypasses_styles_and_applies_cutoff(tmp_path: Path) -> None:
    source = tmp_path / "amundi.xlsx"
    _write_amundi(source)

    parsed = read_amundi_nav(source)

    assert parsed.nav_usd.index[0] == pd.Timestamp("2025-09-30")
    assert parsed.nav_usd.index[-1] == pd.Timestamp("2026-08-31")
    assert parsed.nav_usd.loc["2026-08-31"] == 12.0
    assert parsed.source_last_date == date(2026, 9, 1)


def test_market_build_and_outputs_are_deterministic(tmp_path: Path) -> None:
    bloomberg = tmp_path / "bloomberg"
    amundi = tmp_path / "amundi"
    bloomberg.mkdir()
    amundi.mkdir()
    listing_name = "listing.xlsx"
    index_name = "index.xlsx"
    _write_bloomberg(
        bloomberg / listing_name,
        "TEST LN Equity",
        [
            (datetime(2025, 9, 1), 100.0, 99.9, 100.1, 10.0),
            (datetime(2025, 9, 30), 101.0, 100.9, 101.1, 10.0),
            (datetime(2026, 8, 30), 109.0, 108.9, 109.1, 20.0),
            (datetime(2026, 8, 31), 110.0, 109.9, 110.1, 20.0),
        ],
    )
    _write_bloomberg(
        bloomberg / index_name,
        "MXWOLDNU Index",
        [
            (datetime(2025, 9, 1), 900.0, None, None, None),
            (datetime(2025, 9, 30), 1_000.0, None, None, None),
            (datetime(2026, 8, 30), 1_100.0, None, None, None),
            (datetime(2026, 8, 31), 1_200.0, None, None, None),
        ],
    )
    amundi_name = "amundi.xlsx"
    _write_amundi(amundi / amundi_name)
    specs = (
        BloombergSpec("test", "TEST LN Equity", listing_name, "core"),
        BloombergSpec("mxwoldnu", "MXWOLDNU Index", index_name),
    )

    dataset = build_market_dataset(
        bloomberg,
        amundi,
        bloomberg_specs=specs,
        amundi_filename=amundi_name,
    )

    recent = dataset.spread_calibration.query("period == 'recent_12m'").iloc[0]
    assert recent["observations"] == 4
    assert dataset.manifest["modeled_execution_cost_bps"] == 5.0
    assert dataset.manifest["benchmark_windows"]["common_overlap"][
        "level_observations"
    ] == 3

    first = write_market_dataset(dataset, tmp_path / "first")
    second = write_market_dataset(dataset, tmp_path / "second")
    repeated = write_market_dataset(dataset, tmp_path / "first")
    for key in first:
        assert first[key].read_bytes() == second[key].read_bytes()
        assert first[key].read_bytes() == repeated[key].read_bytes()

    loaded = load_market_dataset(tmp_path / "first")
    pd.testing.assert_frame_equal(loaded.mxwoldnu_index, dataset.mxwoldnu_index)
    pd.testing.assert_frame_equal(loaded.amundi_nav, dataset.amundi_nav)


def test_market_loader_rejects_tampering(tmp_path: Path) -> None:
    bloomberg = tmp_path / "bloomberg"
    amundi = tmp_path / "amundi"
    bloomberg.mkdir()
    amundi.mkdir()
    _write_bloomberg(
        bloomberg / "listing.xlsx",
        "TEST LN Equity",
        [
            (datetime(2025, 9, 1), 100.0, 99.9, 100.1, 10.0),
            (datetime(2026, 8, 31), 110.0, 109.9, 110.1, 20.0),
        ],
    )
    _write_bloomberg(
        bloomberg / "index.xlsx",
        "MXWOLDNU Index",
        [
            (datetime(2025, 9, 1), 900.0, None, None, None),
            (datetime(2025, 9, 30), 1_000.0, None, None, None),
            (datetime(2026, 8, 30), 1_100.0, None, None, None),
            (datetime(2026, 8, 31), 1_200.0, None, None, None),
        ],
    )
    _write_amundi(amundi / "amundi.xlsx")
    dataset = build_market_dataset(
        bloomberg,
        amundi,
        bloomberg_specs=(
            BloombergSpec("test", "TEST LN Equity", "listing.xlsx", "core"),
            BloombergSpec("mxwoldnu", "MXWOLDNU Index", "index.xlsx"),
        ),
        amundi_filename="amundi.xlsx",
    )
    paths = write_market_dataset(dataset, tmp_path / "canonical")
    paths["index"].write_bytes(paths["index"].read_bytes() + b"\n")

    with pytest.raises(ValueError, match="checksum mismatch"):
        load_market_dataset(tmp_path / "canonical")
