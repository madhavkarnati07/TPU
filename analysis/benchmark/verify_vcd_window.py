"""Verify that the emitted VCD duration matches the benchmark JSON exactly."""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys


UNIT_TO_PS = {
    "s": 1_000_000_000_000,
    "ms": 1_000_000_000,
    "us": 1_000_000,
    "ns": 1_000,
    "ps": 1,
    "fs": 0.001,
}


def vcd_timestamps(vcd_path: Path) -> tuple[float, int, int, str]:
    contents = vcd_path.read_text()
    match = re.search(r"\$timescale\s+(\d+)\s*(fs|ps|ns|us|ms|s)\s+\$end", contents)
    if match is None:
        raise ValueError(f"could not parse VCD timescale from {vcd_path}")
    timestep_ps = int(match.group(1)) * UNIT_TO_PS[match.group(2)]
    timestamps = [int(value) for value in re.findall(r"^#(\d+)$", contents, re.MULTILINE)]
    if not timestamps:
        raise ValueError(f"no VCD timestamps found in {vcd_path}")
    return timestep_ps, timestamps[0], timestamps[-1], contents


def terminal_unknown_assignments(contents: str, last_timestamp: int) -> list[str]:
    terminal_block = contents.rsplit(f"#{last_timestamp}", maxsplit=1)[1]
    contaminated = []
    for line in terminal_block.splitlines():
        value_change = line.strip()
        if not value_change or value_change.startswith("$"):
            continue
        first = value_change[0].lower()
        if first in {"x", "z"}:
            contaminated.append(value_change)
        elif first == "b":
            bits = value_change.split(maxsplit=1)[0][1:].lower()
            if "x" in bits or "z" in bits:
                contaminated.append(value_change)
    return contaminated


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: verify_vcd_window.py <result.json> <waveform.vcd>")

    result_path = Path(sys.argv[1])
    waveform_path = Path(sys.argv[2])
    result = json.loads(result_path.read_text())
    window = result["aggregate_vcd_measurement"]
    clock_period_ns = 1_000_000_000 / result["clock_hz"]
    timestep_ps, first_timestamp, last_timestamp, contents = vcd_timestamps(
        waveform_path
    )

    expected_first_ps = window["start_cycle"] * clock_period_ns * 1_000
    expected_last_ps = window["end_cycle"] * clock_period_ns * 1_000
    expected_duration_ps = window["duration_ns"] * 1_000
    actual_first_ps = first_timestamp * timestep_ps
    actual_last_ps = last_timestamp * timestep_ps

    assert actual_first_ps == expected_first_ps, (
        f"VCD starts at {actual_first_ps} ps, expected {expected_first_ps} ps"
    )
    assert actual_last_ps == expected_last_ps, (
        f"VCD ends at {actual_last_ps} ps, expected {expected_last_ps} ps"
    )
    assert actual_last_ps - actual_first_ps == expected_duration_ps, (
        f"VCD duration is {actual_last_ps - actual_first_ps} ps, "
        f"expected {expected_duration_ps} ps"
    )
    assert "$dumpoff" not in contents.lower(), "VCD contains a $dumpoff marker"
    terminal_unknowns = terminal_unknown_assignments(contents, last_timestamp)
    assert not terminal_unknowns, (
        "VCD contains terminal X/Z assignments: " + ", ".join(terminal_unknowns[:8])
    )
    print(
        "VCD window verified: "
        f"first={actual_first_ps / 1_000:g} ns "
        f"last={actual_last_ps / 1_000:g} ns "
        f"duration={expected_duration_ps / 1_000:g} ns "
        "terminal_unknowns=0"
    )


if __name__ == "__main__":
    main()
