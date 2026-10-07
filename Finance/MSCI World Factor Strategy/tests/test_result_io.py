"""Public synthetic checks of artifact integrity and numerical replay."""

from dataclasses import replace
import hashlib
import json
import math

import pandas as pd
import pytest

from factor_portfolio.result_io import (
    continuous_result_columns, write_immutable_result_package,
)


def package(directory, csv=None, *, metadata=None, script=b"print('fixed')\n"):
    path = directory / "metrics.csv"
    data = csv if csv is not None else (
        b"date,strategy,target_leverage,observations,passes_joint_screen,ending_equity_usd,annualised_alpha_vs_core\n"
        b"2026-08-31,core,1.250000000000,3,True,30000000.000000000000,-0.000000000000\n"
    )
    payloads = {path: data, directory / "research_run.py": script}
    manifest = {"schema_version": 1, "input_hash": "fixed", "selection": ["frozen"], **(metadata or {})}
    manifest["result_files"] = {
        p.name: {"sha256": hashlib.sha256(value).hexdigest()}
        for p, value in payloads.items()
    }
    manifest_path = directory / "manifest.json"
    payloads[manifest_path] = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    header = set(data.splitlines()[0].decode().split(","))
    return payloads, manifest_path, {path: {"ending_equity_usd", "annualised_alpha_vs_core"} & header}


def write(args):
    payloads, manifest, columns = args
    return write_immutable_result_package(payloads, manifest_path=manifest, continuous_columns=columns)


def state(directory):
    return {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in directory.iterdir()}


def test_signed_zero_and_one_ulp_replay_retains_all_saved_bytes_and_times(tmp_path):
    original = package(tmp_path)
    assert write(original) == "created"
    before = state(tmp_path)
    new_csv = original[0][tmp_path / "metrics.csv"].replace(
        b"30000000.000000000000", f"{math.nextafter(30000000., math.inf):.12f}".encode()
    ).replace(b"-0.000000000000", b"0.000000000000")
    assert write(package(tmp_path, new_csv)) == "numerically_equivalent"
    assert state(tmp_path) == before
    assert write(original) == "byte_identical"
    assert state(tmp_path) == before


@pytest.mark.parametrize("replacement,accepted", [
    (f"{30000000. + 7 * math.ulp(30000000.):.12f}".encode(), True),
    (f"{30000000. + 10 * math.ulp(30000000.):.12f}".encode(), False),
])
def test_declared_ulp_budget_boundary(tmp_path, replacement, accepted):
    original = package(tmp_path); write(original); before = state(tmp_path)
    csv = original[0][tmp_path / "metrics.csv"].replace(b"30000000.000000000000", replacement)
    if accepted:
        assert write(package(tmp_path, csv)) == "numerically_equivalent"
    else:
        with pytest.raises(FileExistsError): write(package(tmp_path, csv))
    assert state(tmp_path) == before


@pytest.mark.parametrize("replacement,accepted", [(b"0.000000000001", True), (b"0.000000000002", False)])
def test_twelve_decimal_resolution_budget(tmp_path, replacement, accepted):
    original = package(tmp_path); write(original); before = state(tmp_path)
    csv = original[0][tmp_path / "metrics.csv"].replace(b"-0.000000000000", replacement)
    if accepted:
        assert write(package(tmp_path, csv)) == "numerically_equivalent"
    else:
        with pytest.raises(FileExistsError): write(package(tmp_path, csv))
    assert state(tmp_path) == before


@pytest.mark.parametrize("old,new", [
    (b"30000000.000000000000", b"30000000.010000000000"),
    (b"-0.000000000000", b"0.000000010000"),
    (b"2026-08-31", b"2026-08-30"),
    (b",core,", b",factor,"),
    (b"1.250000000000", b"1.250000000001"),
    (b",3,True,", b",4,True,"),
    (b",3,True,", b",3,False,"),
    (b"30000000.000000000000", b""),
    (b"30000000.000000000000", b"inf"),
    (b"30000000.000000000000", b"nan"),
    (b"ending_equity_usd", b"ending_equity_chf"),
])
def test_true_changes_and_discrete_inputs_rejected_without_writes(tmp_path, old, new):
    original = package(tmp_path)
    write(original); before = state(tmp_path)
    altered = original[0][tmp_path / "metrics.csv"].replace(old, new)
    with pytest.raises(FileExistsError):
        write(package(tmp_path, altered))
    assert state(tmp_path) == before


@pytest.mark.parametrize("metadata", [
    {"input_hash": "different"}, {"schema_version": 2},
    {"schema_version": True}, {"selection": ["new-best"]},
    {"reproduction_policy": "different"}, {"target_leverage": 1.2500000000000002},
])
def test_manifest_semantics_exact_including_json_types(tmp_path, metadata):
    write(package(tmp_path)); before = state(tmp_path)
    with pytest.raises(FileExistsError, match="semantics"):
        write(package(tmp_path, metadata=metadata))
    assert state(tmp_path) == before


def test_non_csv_script_bytes_are_exact(tmp_path):
    write(package(tmp_path)); before = state(tmp_path)
    with pytest.raises(FileExistsError, match="payload"):
        write(package(tmp_path, script=b"print('changed')\n"))
    assert state(tmp_path) == before


@pytest.mark.parametrize("filename", ["metrics.csv", "research_run.py"])
def test_saved_tampering_checked_before_numerical_equivalence(tmp_path, filename):
    original = package(tmp_path); write(original)
    path = tmp_path / filename
    path.write_bytes(path.read_bytes().replace(b"-0.000000000000", b"0.000000000000") + (b" " if filename.endswith('.py') else b""))
    before = state(tmp_path)
    with pytest.raises(ValueError, match="checksum"):
        write(original)
    assert state(tmp_path) == before


def test_rehashed_meaningful_change_still_rejected(tmp_path):
    original = package(tmp_path)
    altered = original[0][tmp_path / "metrics.csv"].replace(b"30000000.000000000000", b"31000000.000000000000")
    write(package(tmp_path, altered)); before = state(tmp_path)
    with pytest.raises(FileExistsError, match="ending_equity_usd"):
        write(original)
    assert state(tmp_path) == before


@pytest.mark.parametrize("missing", ["metrics.csv", "manifest.json", "research_run.py"])
def test_partial_package_refused_without_repair(tmp_path, missing):
    original = package(tmp_path); write(original)
    (tmp_path / missing).unlink(); before = state(tmp_path)
    with pytest.raises(FileExistsError, match="incomplete"):
        write(original)
    assert state(tmp_path) == before


@pytest.mark.parametrize("change", ["hash", "rows", "missing_record", "extra_record"])
def test_invalid_incoming_manifest_rejected_before_creation(tmp_path, change):
    payloads, path, columns = package(tmp_path)
    manifest = json.loads(payloads[path])
    record = manifest["result_files"]["metrics.csv"]
    if change == "hash": record["sha256"] = "wrong"
    elif change == "rows": record["rows"] = 99
    elif change == "missing_record": del manifest["result_files"]["metrics.csv"]
    else: manifest["result_files"]["extra.csv"] = record
    payloads[path] = json.dumps(manifest).encode()
    with pytest.raises(ValueError):
        write((payloads, path, columns))
    assert not list(tmp_path.iterdir())


def test_row_order_and_missing_values_are_exact(tmp_path):
    original = package(tmp_path)
    header, row = original[0][tmp_path / "metrics.csv"].splitlines()
    second = row.replace(b"2026-08-31", b"2026-08-28").replace(b"-0.000000000000", b"")
    write(package(tmp_path, b"\n".join([header, row, second]) + b"\n"))
    before = state(tmp_path)
    with pytest.raises(FileExistsError):
        write(package(tmp_path, b"\n".join([header, second, row]) + b"\n"))
    with pytest.raises(FileExistsError):
        write(package(tmp_path, b"\n".join([header, row, second + b"0.000000000000"]) + b"\n"))
    assert state(tmp_path) == before


@pytest.mark.parametrize("name", [
    "core_weight", "sleeve_band", "target_leverage", "leverage_band",
    "initial_committed_capital_usd", "annualisation_periods", "observations",
    "factor_minus_core_post_initialisation_trade_events", "neighbour_count",
    "calibration_cagr_rank", "financing_spread_bps", "execution_spread_bps",
    "unrecognized_output",
])
def test_float_inputs_counts_and_unknown_columns_are_not_tolerant(name):
    frame = pd.DataFrame({name: [1.0], "ending_equity_usd": [3e7]})
    assert continuous_result_columns(frame) == {"ending_equity_usd"}


@pytest.mark.parametrize("module_name,class_name,writer_name,frame_names,level_names", [
    ("benchmark", "BenchmarkComparison", "write_benchmark_comparison", ("metrics", "relative_metrics", "equity_curves"), {"equity_curves"}),
    ("evaluation", "SplitEvaluation", "write_split_evaluation", ("metrics", "relative_metrics", "equity_curves"), {"equity_curves"}),
    ("grid", "CalibrationGrid", "write_calibration_grid", ("scenarios", "results"), set()),
    ("confirmation", "ConfirmationEvaluation", "write_confirmation_evaluation", ("results", "summary"), set()),
    ("dimensional", "ThreeWayComparison", "write_three_way_comparison", ("metrics", "equity_curves"), {"equity_curves"}),
    ("reference", "InvestableReferenceComparison", "write_investable_reference_comparison", ("levels", "metrics"), {"levels"}),
])
def test_each_writer_integrates_integrity_first_replay(tmp_path, module_name, class_name, writer_name, frame_names, level_names):
    from importlib import import_module
    module = import_module(f"factor_portfolio.{module_name}")
    frames = {}
    for name in frame_names:
        if name == "scenarios":
            frame = pd.DataFrame({"scenario_id": ["frozen"], "core_weight": [.6]})
        elif name in level_names:
            frame = pd.DataFrame({"factor_1.25x": [3e7]}, index=pd.DatetimeIndex(["2026-08-31"]))
        else:
            frame = pd.DataFrame({"strategy": ["core"], "target_leverage": [1.25], "ending_equity_usd": [3e7], "annualised_alpha_vs_core": [-0.0]})
        frames[name] = frame
    original = getattr(module, class_name)(**frames, manifest={"schema_version": 1, "input_hash": "fixed"})
    writer = getattr(module, writer_name)
    paths = writer(original, tmp_path); before = state(tmp_path)
    changed = {name: frame.copy() for name, frame in frames.items()}
    target = next(name for name in frame_names if name != "scenarios")
    col = "factor_1.25x" if target in level_names else "ending_equity_usd"
    changed[target][col] = math.nextafter(3e7, math.inf)
    if "annualised_alpha_vs_core" in changed[target]: changed[target]["annualised_alpha_vs_core"] = 0.0
    assert writer(replace(original, **changed), tmp_path) == paths
    assert state(tmp_path) == before
    changed[target][col] = 3e7 + .01
    with pytest.raises(FileExistsError): writer(replace(original, **changed), tmp_path)
    assert state(tmp_path) == before
