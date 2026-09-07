#!/usr/bin/env python3
"""Capture the minimal physical-run provenance required by the Pareto report."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
VARIANTS = {"mac1": 1, "mac2": 2, "mac4": 4}
RTL_SOURCES = [
    "src/dual_int4_mac.v",
    "src/toy_attention_core.v",
    "src/project.v",
]


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, text=True, capture_output=True
    ).stdout.rstrip()


def repo_relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variant", required=True, choices=VARIANTS)
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--power-result", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    lanes = VARIANTS[args.variant]
    run_dir = (args.run_dir or ROOT / "runs" / args.variant).resolve()
    power_path = args.power_result or ROOT / "analysis/pareto/results" / args.variant / "power-active.json"
    output = args.output or ROOT / "analysis/pareto/results" / args.variant / "physical-context.json"
    resolved = read_json(run_dir / "resolved.json")
    metrics = read_json(run_dir / "final/metrics.json")
    power = read_json(power_path)

    expected_parameter = [f"MAC_LANES={lanes}"]
    if resolved.get("SYNTH_PARAMETERS") != expected_parameter:
        raise ValueError(
            f"{args.variant} resolved SYNTH_PARAMETERS must be {expected_parameter}"
        )
    expected_sources = [(ROOT / path).resolve() for path in RTL_SOURCES]
    resolved_sources = [Path(path).resolve() for path in resolved.get("VERILOG_FILES", [])]
    if resolved_sources != expected_sources:
        raise ValueError(f"{args.variant} resolved VERILOG_FILES do not match the RTL source set")

    pdk_root = Path(resolved["PDK_ROOT"])
    changed_rtl = [
        line[3:]
        for line in git("status", "--porcelain", "--", *RTL_SOURCES).splitlines()
        if line
    ]
    context = {
        "schema_version": "1.0",
        "variant": args.variant,
        "run_tag": run_dir.name,
        "resolved_config": {
            "design_name": resolved["DESIGN_NAME"],
            "synth_parameters": resolved["SYNTH_PARAMETERS"],
            "die_area_um": resolved["DIE_AREA"],
            "tile_allocation": "2x2",
            "clock_period_ns": resolved["CLOCK_PERIOD"],
            "pdk": resolved["PDK"],
            "standard_cell_library": resolved["STD_CELL_LIBRARY"],
            "rtl_sources": RTL_SOURCES,
        },
        "metrics_binding": {
            "standard_cell_area_um2": metrics["design__instance__area__stdcell"],
            "standard_cell_count": metrics["design__instance__count__stdcell"],
            "die_area_um2": metrics["design__die__area"],
            "core_area_um2": metrics["design__core__area"],
        },
        "source_provenance": {
            "base_git_commit": git("rev-parse", "HEAD"),
            "branch": git("branch", "--show-current"),
            "worktree_state": "dirty" if changed_rtl else "clean",
            "changed_rtl_files": changed_rtl,
            "rtl_files": RTL_SOURCES,
        },
        "flow": {
            "librelane_version": power["physical_context"]["tool"]["librelane_version"],
            "pdk_revision": pdk_root.name,
            "run_directory": repo_relative(run_dir),
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(context, indent=2) + "\n", encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
