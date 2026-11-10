"""Read the official Amundi USD NAV workbook."""

import hashlib
import math
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from zipfile import ZipFile

import pandas as pd
from .security_io import validate_xlsx, read_xml_member


DEFAULT_CUTOFF = date(2026, 8, 31)


AMUNDI_ISIN = "FR0014010HV4"


LEVERAGED_INDEX_NAME = "MSCI World Leveraged 2X Daily (Net) USD Index"


XLSX_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


@dataclass(frozen=True)
class AmundiSeries:
    nav_usd: pd.Series
    source_sha256: str
    source_first_date: date
    source_last_date: date


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _number_or_nan(value: object) -> float:
    if value is None or isinstance(value, str):
        return math.nan
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid numeric cell: {value!r}") from exc
    return result if math.isfinite(result) else math.nan


def _xlsx_cells(path: Path) -> dict[str, str | float]:
    """Read values directly from OOXML so malformed style metadata is irrelevant."""

    validate_xlsx(path)
    with ZipFile(path) as archive:
        shared_root = read_xml_member(archive, "xl/sharedStrings.xml")
        shared = [
            "".join(node.text or "" for node in item.iter(f"{{{XLSX_NS}}}t"))
            for item in shared_root.findall(f"{{{XLSX_NS}}}si")
        ]
        sheet_root = read_xml_member(archive, "xl/worksheets/sheet1.xml")

    cells: dict[str, str | float] = {}
    for cell in sheet_root.iter(f"{{{XLSX_NS}}}c"):
        reference = cell.get("r")
        value_node = cell.find(f"{{{XLSX_NS}}}v")
        if reference is None or value_node is None or value_node.text is None:
            continue
        if cell.get("t") == "s":
            cells[reference] = shared[int(value_node.text)]
        else:
            cells[reference] = float(value_node.text)
    return cells


def read_amundi_nav(
    path: str | Path, *, cutoff: date = DEFAULT_CUTOFF
) -> AmundiSeries:
    source = Path(path)
    cells = _xlsx_cells(source)
    expected = {
        "C11": "Amundi MSCI World (2x) Leveraged UCITS ETF Acc",
        "C12": AMUNDI_ISIN,
        "C13": LEVERAGED_INDEX_NAME,
        "C14": "Synthetic",
        "C15": "USD",
        "B27": "Date",
        "C27": "Official NAV",
        "E27": "Nav Currency",
    }
    for reference, value in expected.items():
        if cells.get(reference) != value:
            raise ValueError(f"unexpected Amundi value at {reference}")

    records: list[tuple[pd.Timestamp, float]] = []
    source_dates: list[date] = []
    data_started = False
    for row in range(28, 100_000):
        raw_date = cells.get(f"B{row}")
        if raw_date is None:
            if data_started:
                break
            continue
        data_started = True
        currency = cells.get(f"E{row}")
        if currency != "USD":
            raise ValueError(f"unexpected Amundi NAV currency in row {row}")
        try:
            observation_date = pd.Timestamp(datetime.strptime(str(raw_date), "%d/%m/%Y"))
        except ValueError as exc:
            raise ValueError(f"invalid Amundi date in row {row}") from exc
        source_dates.append(observation_date.date())
        if observation_date.date() > cutoff:
            continue
        nav = _number_or_nan(cells.get(f"C{row}"))
        if not math.isfinite(nav) or nav <= 0.0:
            raise ValueError(f"invalid Amundi NAV in row {row}")
        records.append((observation_date, nav))

    series = pd.Series(
        [nav for _, nav in records],
        index=[observation_date for observation_date, _ in records],
        dtype=float,
        name="amundi_2x_nav_usd",
    ).sort_index()
    series.index = pd.DatetimeIndex(series.index, name="date")
    if series.empty or series.index.has_duplicates or not series.index.is_monotonic_increasing:
        raise ValueError("Amundi dates must be non-empty, unique, and sorted")
    if pd.Timestamp(cutoff) not in series.index:
        raise ValueError(f"Amundi has no observation on cutoff {cutoff}")
    return AmundiSeries(
        nav_usd=series,
        source_sha256=_sha256(source),
        source_first_date=series.index[0].date(),
        source_last_date=max(source_dates),
    )
