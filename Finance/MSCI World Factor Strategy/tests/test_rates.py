from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

import factor_portfolio.rates as rates_module
from factor_portfolio.rates import (
    INDICATIVE_FILENAME,
    OFFICIAL_FILENAME,
    build_funding_dataset,
    load_funding_dataset,
    read_indicative_sofr,
    read_official_sofr,
    write_funding_dataset,
)


def _observations(
    values: list[tuple[str, float]], *, status: str
) -> pd.DataFrame:
    series = "INDICATIVE_SOFR" if status == "indicative" else "SOFR"
    return pd.DataFrame(
        {
            "reference_rate_annual": [value for _, value in values],
            "reference_series": series,
            "reference_status": status,
            "revision_indicator": "",
        },
        index=pd.DatetimeIndex([day for day, _ in values], name="date"),
    )


def _write_source_manifest(raw_dir: Path) -> None:
    sources = {}
    for key, filename in {
        "indicative_sofr": INDICATIVE_FILENAME,
        "official_sofr": OFFICIAL_FILENAME,
    }.items():
        path = raw_dir / filename
        sources[key] = {
            "filename": filename,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    (raw_dir / "source_manifest.json").write_text(
        json.dumps({"sources": sources}), encoding="utf-8"
    )


def test_reads_indicative_basis_points(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / INDICATIVE_FILENAME
    # The units test stubs pandas values, but container admission now verifies
    # that the supplied file is an actual bounded workbook before parsing.
    from openpyxl import Workbook
    Workbook().save(source)
    fixture = pd.DataFrame(
        {
            "Date": [pd.Timestamp("2014-10-03"), pd.Timestamp("2014-10-06")],
            "Secured Overnight Financing Rate": [7, 8],
        }
    )
    monkeypatch.setattr(pd, "read_excel", lambda *args, **kwargs: fixture)

    result = read_indicative_sofr(source)

    assert result.loc["2014-10-03", "reference_rate_annual"] == pytest.approx(0.0007)
    assert set(result["reference_status"]) == {"indicative"}


def test_reads_official_percent_rate_and_sorts(tmp_path: Path) -> None:
    source = tmp_path / OFFICIAL_FILENAME
    source.write_text(
        json.dumps(
            {
                "refRates": [
                    {
                        "effectiveDate": "2018-04-03",
                        "type": "SOFR",
                        "percentRate": 1.83,
                        "revisionIndicator": "",
                    },
                    {
                        "effectiveDate": "2018-04-02",
                        "type": "SOFR",
                        "percentRate": 1.80,
                        "revisionIndicator": "",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    result = read_official_sofr(source)

    assert result.index[0] == pd.Timestamp("2018-04-02")
    assert result.iloc[0]["reference_rate_annual"] == pytest.approx(0.018)
    assert set(result["reference_status"]) == {"official"}


def test_builds_daily_transition_and_fixed_spread(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    (raw_dir / INDICATIVE_FILENAME).write_bytes(b"indicative")
    (raw_dir / OFFICIAL_FILENAME).write_bytes(b"official")
    _write_source_manifest(raw_dir)
    indicative = _observations(
        [("2018-03-29", 0.018)], status="indicative"
    )
    official = _observations(
        [("2018-04-02", 0.0180), ("2018-04-03", 0.0183)], status="official"
    )
    monkeypatch.setattr(rates_module, "read_indicative_sofr", lambda path: indicative)
    monkeypatch.setattr(rates_module, "read_official_sofr", lambda path: official)

    dataset = build_funding_dataset(
        raw_dir,
        start=date(2018, 3, 29),
        cutoff=date(2018, 4, 3),
        broker_spread=0.03,
    )
    daily = dataset.daily_borrow_rates

    assert daily.loc["2018-03-30", "reference_value_date"] == pd.Timestamp(
        "2018-03-29"
    )
    assert bool(daily.loc["2018-03-30", "rate_carried_forward"])
    assert daily.loc["2018-04-02", "reference_status"] == "official"
    assert daily.loc["2018-04-03", "borrow_rate_annual"] == pytest.approx(0.0483)


def test_funding_outputs_are_byte_identical_and_verified(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    (raw_dir / INDICATIVE_FILENAME).write_bytes(b"indicative")
    (raw_dir / OFFICIAL_FILENAME).write_bytes(b"official")
    _write_source_manifest(raw_dir)
    indicative = _observations(
        [("2018-03-29", 0.018)], status="indicative"
    )
    official = _observations(
        [("2018-04-02", 0.0180), ("2018-04-03", 0.0183)], status="official"
    )
    monkeypatch.setattr(rates_module, "read_indicative_sofr", lambda path: indicative)
    monkeypatch.setattr(rates_module, "read_official_sofr", lambda path: official)
    dataset = build_funding_dataset(
        raw_dir, start=date(2018, 3, 29), cutoff=date(2018, 4, 3)
    )

    first = write_funding_dataset(dataset, tmp_path / "first")
    second = write_funding_dataset(dataset, tmp_path / "second")
    repeated = write_funding_dataset(dataset, tmp_path / "first")

    for key in first:
        assert first[key].read_bytes() == second[key].read_bytes()
        assert first[key].read_bytes() == repeated[key].read_bytes()
    loaded = load_funding_dataset(tmp_path / "first")
    pd.testing.assert_frame_equal(
        loaded.daily_borrow_rates,
        dataset.daily_borrow_rates,
        check_dtype=False,
        check_freq=False,
    )
    pd.testing.assert_frame_equal(
        loaded.reference_observations,
        dataset.reference_observations,
        check_dtype=False,
        check_freq=False,
    )


def test_funding_loader_rejects_tampering(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    (raw_dir / INDICATIVE_FILENAME).write_bytes(b"indicative")
    (raw_dir / OFFICIAL_FILENAME).write_bytes(b"official")
    _write_source_manifest(raw_dir)
    indicative = _observations(
        [("2018-03-29", 0.018)], status="indicative"
    )
    official = _observations(
        [("2018-04-02", 0.0180), ("2018-04-03", 0.0183)], status="official"
    )
    monkeypatch.setattr(rates_module, "read_indicative_sofr", lambda path: indicative)
    monkeypatch.setattr(rates_module, "read_official_sofr", lambda path: official)
    dataset = build_funding_dataset(
        raw_dir, start=date(2018, 3, 29), cutoff=date(2018, 4, 3)
    )
    paths = write_funding_dataset(dataset, tmp_path / "canonical")
    paths["daily"].write_bytes(paths["daily"].read_bytes() + b"\n")

    with pytest.raises(ValueError, match="checksum mismatch"):
        load_funding_dataset(tmp_path / "canonical")
