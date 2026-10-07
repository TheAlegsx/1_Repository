"""Generate an invented fixture; no market inputs or random fitted parameters."""
from __future__ import annotations
import argparse
import csv
from datetime import date, timedelta
import io
from pathlib import Path


def fixture_bytes() -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(["date", "core", "momentum", "quality", "value", "annual_borrow_rate"])
    day = date(2030, 1, 2)
    for i in range(600):
        while day.weekday() >= 5:
            day += timedelta(days=1)
        values = [200 + ((i * 73) % 4001) - 2000,
                  2500 + ((i * 97) % 5001) - 2500,
                  400 + ((i * 53) % 3001) - 1500,
                  -100 + ((i * 89) % 4501) - 2250]
        if i in (180, 181):
            values = [-250000 if i == 180 else -200000] * 4
        if i == 185:
            values = [100000] * 4
        if i == 0:
            values = [0] * 4
        writer.writerow([day.isoformat(), *[f"{v / 1000000:.6f}" for v in values], "0.040000"])
        day += timedelta(days=1)
    return stream.getvalue().encode("utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    output = parser.parse_args().output
    payload = fixture_bytes()
    if output.exists():
        if output.read_bytes() != payload:
            raise FileExistsError("Changed fixture: choose a new path")
        print("Synthetic fixture verified; existing bytes retained")
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(payload)
        print("Synthetic fixture generated")


if __name__ == "__main__":
    main()
