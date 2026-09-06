#!/usr/bin/env python3
"""Validate and combine the fixed warm two-MAC baseline artifacts."""

from __future__ import annotations

import argparse
from fractions import Fraction
import json
import math
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "analysis/report/baseline_2mac.json"
INPUTS = {
    "rtl": Path("analysis/benchmark/results/rtl_warm_baseline.json"),
    "gate": Path("analysis/benchmark/results/gate_warm_baseline.json"),
    "active_power": Path("analysis/power/out/baseline-2mac/result.json"),
    "idle_gate": Path("analysis/benchmark/results/gate_idle_warm_window.json"),
    "idle_power": Path("analysis/power/out/idle-2mac/result.json"),
    "physical": Path("runs/wokwi/final/metrics.json"),
}
TIMING_CORNERS = re.compile(r"^timing__setup__wns__corner:(.+)$")
EXPECTED_CLOCK_PERIOD_NS = 100
EXPECTED_DESIGN_NAME = "tt_um_madhavkarnati_toy_tpu"
EXPECTED_GATE_NETLIST = Path("test/gate_level_netlist.v")
VCD_VALIDATOR = Path("analysis/benchmark/verify_vcd_window.py")
ACTIVE_GATE_VCD = Path("analysis/benchmark/results/gate_warm_baseline.vcd")
IDLE_GATE_VCD = Path("analysis/benchmark/results/gate_idle_warm_window.vcd")
EXPECTED_ARTIFACT_SUFFIXES = {
    "cell_lef_ef": ".lef",
    "cell_lef_hd": ".lef",
    "liberty": ".lib",
    "netlist": ".nl.v",
    "sdc": ".sdc",
    "spef": ".spef",
    "tech_lef": ".tlef",
}
PDK_ARTIFACTS = ("cell_lef_ef", "cell_lef_hd", "liberty", "tech_lef")


def fail(message: str) -> None:
    raise ValueError(message)


def read_json(relative_path: Path) -> dict[str, Any]:
    path = ROOT / relative_path
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        fail(f"missing required artifact: {relative_path.as_posix()}")
    except json.JSONDecodeError as error:
        fail(f"invalid JSON in {relative_path.as_posix()}: {error}")


def require(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def require_equal(left: Any, right: Any, name: str) -> None:
    require(left == right, f"artifact mismatch for {name}")


def repo_relative_path(value: Any, name: str) -> Path:
    require(isinstance(value, str) and value, f"{name} is not a path string")
    candidate = Path(value)
    resolved = candidate.resolve() if candidate.is_absolute() else (ROOT / candidate).resolve()
    try:
        relative = resolved.relative_to(ROOT.resolve())
    except ValueError:
        fail(f"{name} is outside the repository")
    require(resolved.exists(), f"{name} does not exist: {relative.as_posix()}")
    return relative


def require_artifact_path(value: Any, expected: Path, name: str) -> None:
    require_equal(repo_relative_path(value, name), expected, name)


def fraction(value: Any, name: str) -> Fraction:
    require(not isinstance(value, bool), f"{name} is not numeric")
    try:
        return Fraction(str(value))
    except (TypeError, ValueError, ZeroDivisionError):
        fail(f"{name} is not numeric")


def fraction_number(value: Fraction) -> int | float:
    return value.numerator if value.denominator == 1 else float(value)


def benchmark_provenance(
    benchmark: dict[str, Any], label: str, expected_kind: str
) -> dict[str, Any]:
    provenance = benchmark["provenance"]
    require_equal(
        provenance["measurement_kind"], expected_kind, f"{label} provenance kind"
    )
    require_equal(provenance["simulation_mode"], "gate", f"{label} provenance mode")

    gate_netlist = provenance["gate_netlist"]
    require_equal(
        gate_netlist["path_kind"], "repo_relative", f"{label} gate netlist path kind"
    )
    gate_netlist_path = repo_relative_path(
        gate_netlist["path"], f"{label} gate netlist"
    )
    require_equal(
        gate_netlist_path,
        EXPECTED_GATE_NETLIST,
        f"{label} gate netlist path",
    )

    pdk = provenance["pdk"]
    require_equal(pdk["path_kind"], "repo_relative", f"{label} PDK path kind")
    pdk_identifier = pdk["identifier"]
    require(
        isinstance(pdk_identifier, str) and pdk_identifier,
        f"{label} PDK identifier is empty",
    )
    pdk_path = repo_relative_path(pdk["path"], f"{label} PDK path")
    require(
        pdk_identifier in pdk_path.parts,
        f"{label} PDK identifier is absent from its path",
    )
    require(
        isinstance(provenance["simulator"], str) and provenance["simulator"],
        f"{label} simulator identity is empty",
    )
    require(
        isinstance(provenance["gate_unit_delay"], str)
        and provenance["gate_unit_delay"],
        f"{label} gate unit delay is empty",
    )
    return {
        "simulator": provenance["simulator"],
        "simulation_mode": provenance["simulation_mode"],
        "gate_netlist": gate_netlist_path.as_posix(),
        "gate_unit_delay": provenance["gate_unit_delay"],
        "pdk": {
            "identifier": pdk_identifier,
            "path": pdk_path.as_posix(),
        },
    }


def expected_physical_artifacts(pdk_identifier: str) -> dict[str, Path]:
    pdk_root = (
        Path(".tt-pdk/ciel/ciel/sky130/versions")
        / pdk_identifier
        / "sky130A/libs.ref/sky130_fd_sc_hd"
    )
    return {
        "netlist": Path(f"runs/wokwi/final/nl/{EXPECTED_DESIGN_NAME}.nl.v"),
        "spef": Path(
            f"runs/wokwi/final/spef/nom/{EXPECTED_DESIGN_NAME}.nom.spef"
        ),
        "sdc": Path(
            f"runs/wokwi/52-openroad-fillinsertion/{EXPECTED_DESIGN_NAME}.sdc"
        ),
        "liberty": pdk_root / "lib/sky130_fd_sc_hd__tt_025C_1v80.lib",
    }


def power_provenance(
    active: dict[str, Any], idle: dict[str, Any], pdk_identifier: str
) -> dict[str, Any]:
    active_context = active["physical_context"]
    idle_context = idle["physical_context"]
    require_equal(active_context["tool"], idle_context["tool"], "active/idle tool identity")
    for field in ("librelane_version", "container_image", "openroad_command"):
        require(
            isinstance(active_context["tool"].get(field), str)
            and active_context["tool"][field],
            f"power tool identity lacks {field}",
        )
    require_equal(
        active_context["tool"].get("report_power_digits"),
        9,
        "power report digits",
    )

    def normalize_artifacts(context: dict[str, Any], label: str) -> dict[str, Path]:
        artifacts = context["artifacts"]
        require_equal(
            set(artifacts), set(EXPECTED_ARTIFACT_SUFFIXES), f"{label} artifact set"
        )
        normalized = {
            name: repo_relative_path(value, f"{label} {name}")
            for name, value in artifacts.items()
        }
        for name, suffix in EXPECTED_ARTIFACT_SUFFIXES.items():
            require(
                normalized[name].name.endswith(suffix),
                f"{label} {name} does not have {suffix} type",
            )
        return normalized

    active_artifacts = normalize_artifacts(active_context, "active power")
    idle_artifacts = normalize_artifacts(idle_context, "idle power")
    require_equal(active_artifacts, idle_artifacts, "active/idle physical artifacts")
    for name in PDK_ARTIFACTS:
        require(
            pdk_identifier in active_artifacts[name].parts,
            f"benchmark PDK identifier is absent from physical {name} path",
        )
    for name, expected in expected_physical_artifacts(pdk_identifier).items():
        require_equal(active_artifacts[name], expected, f"physical {name} path")

    return {
        "corner": active_context["corner"],
        "artifacts": {
            name: path.as_posix() for name, path in sorted(active_artifacts.items())
        },
        "tool": active_context["tool"],
    }


def sdc_clock_period(sdc_path: Path) -> Fraction:
    create_clock_lines = [
        line.strip()
        for line in (ROOT / sdc_path).read_text(encoding="ascii").splitlines()
        if line.strip().startswith("create_clock ")
    ]
    require_equal(len(create_clock_lines), 1, "SDC create_clock count")
    line = create_clock_lines[0]
    require(
        re.search(r"\[get_ports\s+\{?clk\}?\]", line) is not None,
        "SDC create_clock does not constrain clk",
    )
    match = re.search(r"(?:^|\s)-period\s+([0-9]+(?:\.[0-9]+)?)\b", line)
    require(match is not None, "SDC create_clock lacks a numeric period")
    return fraction(match.group(1), "SDC clock period")


def validate_clock_provenance(
    gate: dict[str, Any],
    active_power: dict[str, Any],
    idle_power: dict[str, Any],
    sdc: Path,
) -> dict[str, Any]:
    sdc_period = sdc_clock_period(sdc)
    require_equal(
        sdc_period,
        Fraction(EXPECTED_CLOCK_PERIOD_NS),
        "SDC 100 ns timing constraint",
    )
    benchmark_period = Fraction(1_000_000_000) / fraction(
        gate["clock_hz"], "benchmark clock_hz"
    )
    require_equal(benchmark_period, sdc_period, "benchmark/SDC clock")
    require_equal(
        fraction(
            active_power["physical_context"]["clock_period_ns"],
            "active power clock",
        ),
        sdc_period,
        "active power/SDC clock",
    )
    require_equal(
        fraction(
            idle_power["physical_context"]["clock_period_ns"],
            "idle power clock",
        ),
        sdc_period,
        "idle power/SDC clock",
    )
    return {
        "port": "clk",
        "period_ns": fraction_number(sdc_period),
        "source": sdc.as_posix(),
    }


def run_canonical_vcd_validator(
    benchmark_path: Path, vcd_path: Path, label: str
) -> dict[str, str]:
    validator = repo_relative_path(VCD_VALIDATOR.as_posix(), "VCD validator")
    benchmark = repo_relative_path(benchmark_path.as_posix(), f"{label} gate benchmark")
    vcd = repo_relative_path(vcd_path.as_posix(), f"{label} gate VCD")
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / validator),
            str(ROOT / benchmark),
            str(ROOT / vcd),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()
        fail(
            f"{label} canonical VCD validation failed"
            + (f": {detail[-1]}" if detail else "")
        )
    return {
        "status": "pass",
        "benchmark": benchmark.as_posix(),
        "vcd": vcd.as_posix(),
        "validator": validator.as_posix(),
    }


def benchmark_projection(benchmark: dict[str, Any]) -> dict[str, Any]:
    """Keep only the externally observable records for RTL/gate comparison."""
    return {
        "benchmark": benchmark["benchmark"],
        "clock_hz": benchmark["clock_hz"],
        "transaction_count": benchmark["transaction_count"],
        "resident_weights_packed": benchmark["resident_weights_packed"],
        "transactions": [
            {
                "index": transaction["index"],
                "x": transaction["x"],
                "x_packed": transaction["x_packed"],
                "expected_output": transaction["expected_output"],
                "expected_result_bytes": transaction["expected_result_bytes"],
                "observed_result_bytes": transaction["observed_result_bytes"],
                "compute_cycles": transaction["compute_cycles"],
                "latency_cycles": transaction["latency_cycles"],
                "initiation_interval_cycles": transaction["initiation_interval_cycles"],
            }
            for transaction in benchmark["transactions"]
        ],
    }


def validate_benchmark(benchmark: dict[str, Any], mode: str) -> None:
    require_equal(benchmark["simulation_mode"], mode, f"{mode} simulation mode")
    require(benchmark["transaction_count"] > 0, f"{mode} transaction count is empty")
    require_equal(
        len(benchmark["transactions"]),
        benchmark["transaction_count"],
        f"{mode} transaction list length",
    )
    require(
        benchmark["summary"]["all_outputs_match_golden_model"],
        f"{mode} simulation did not match the Python golden model",
    )
    for expected_index, transaction in enumerate(benchmark["transactions"]):
        require_equal(transaction["index"], expected_index, f"{mode} transaction index")
        require_equal(
            transaction["observed_result_bytes"],
            transaction["expected_result_bytes"],
            f"{mode} transaction {expected_index} result",
        )


def benchmark_window(benchmark: dict[str, Any]) -> dict[str, Any]:
    window = benchmark["aggregate_vcd_measurement"]
    return {
        name: window[name]
        for name in ("start_cycle", "end_cycle", "duration_cycles", "duration_ns")
    }


def validate_idle_benchmark(idle: dict[str, Any], active: dict[str, Any]) -> None:
    require_equal(idle["simulation_mode"], "gate", "idle simulation mode")
    require_equal(idle["benchmark"], "idle_warm_window", "idle benchmark identity")
    require_equal(idle["measurement_kind"], "idle_warm_window", "idle measurement kind")
    require_equal(idle["transaction_count"], 0, "idle transaction count")
    require_equal(
        idle["aggregate_vcd_measurement"]["transaction_count"],
        0,
        "idle VCD transaction count",
    )
    require_equal(idle["clock_hz"], active["clock_hz"], "active/idle clock")
    require_equal(
        benchmark_window(idle), benchmark_window(active), "active/idle VCD window"
    )
    require_equal(
        idle["resident_weights_packed"],
        active["resident_weights_packed"],
        "active/idle resident weights",
    )
    require_equal(
        idle["matched_active_transaction_count"],
        active["transaction_count"],
        "idle matched active transaction count",
    )


def validate_annotation(annotation: dict[str, Any], label: str) -> None:
    require(annotation["vcd_reported"], f"{label} OpenSTA did not report VCD activity")
    require(annotation["annotated_pin_count"] > 0, f"{label} has no annotated pins")
    require_equal(annotation["unannotated_pin_count"], 0, f"{label} unannotated pin count")
    require_equal(
        annotation["annotated_pin_coverage_percent"],
        100.0,
        f"{label} annotation coverage",
    )


def validate_power_result(
    power: dict[str, Any],
    benchmark: dict[str, Any],
    benchmark_path: Path,
    vcd_path: Path,
    expected_kind: str,
    label: str,
) -> dict[str, Any]:
    measurement = power["measurement"]
    window = benchmark_window(benchmark)
    require_equal(power["status"], "measured", f"{label} power status")
    require_equal(measurement["kind"], expected_kind, f"{label} power kind")
    require_equal(measurement["benchmark"], benchmark["benchmark"], f"{label} benchmark")
    require_equal(
        measurement["transactions"],
        benchmark["transaction_count"],
        f"{label} transaction count",
    )
    require_equal(measurement["duration_ns"], window["duration_ns"], f"{label} VCD duration")
    require_artifact_path(
        measurement["benchmark_result"], benchmark_path, f"{label} benchmark binding"
    )
    require_artifact_path(measurement["vcd"], vcd_path, f"{label} VCD binding")

    vcd_window = measurement["vcd_window"]
    require(
        vcd_window["verified_against_benchmark"] is True,
        f"{label} VCD window was not verified against its benchmark",
    )
    require_equal(vcd_window["duration_ns"], window["duration_ns"], f"{label} VCD duration evidence")
    clock_period_ns = power["physical_context"]["clock_period_ns"]
    require_equal(
        vcd_window["first_time_ns"],
        window["start_cycle"] * clock_period_ns,
        f"{label} VCD start evidence",
    )
    require_equal(
        vcd_window["last_time_ns"],
        window["end_cycle"] * clock_period_ns,
        f"{label} VCD end evidence",
    )
    validate_annotation(power["annotation_evidence"], label)
    return measurement


def timing_constraints(metrics: dict[str, Any]) -> dict[str, Any]:
    corners = sorted(
        match.group(1)
        for key in metrics
        if (match := TIMING_CORNERS.match(key)) is not None
    )
    require(corners, "no setup timing corners found in final LibreLane metrics")

    corner_metrics: dict[str, dict[str, Any]] = {}
    for corner in corners:
        checks = {}
        for check in ("setup", "hold"):
            values = {
                "wns": metrics[f"timing__{check}__wns__corner:{corner}"],
                "tns": metrics[f"timing__{check}__tns__corner:{corner}"],
                "vio__count": metrics[
                    f"timing__{check}_vio__count__corner:{corner}"
                ],
            }
            require(values["wns"] >= 0, f"negative {check} WNS at {corner}")
            require(values["tns"] == 0, f"nonzero {check} TNS at {corner}")
            require(values["vio__count"] == 0, f"{check} violations at {corner}")
            checks[check] = {
                "wns_ns": values["wns"],
                "tns_ns": values["tns"],
                "violation_count": values["vio__count"],
            }
        corner_metrics[corner] = checks

    return {
        "status": "pass",
        "interpretation": "Timing is a pass/fail implementation constraint, not an optimization metric.",
        "corner_count": len(corners),
        "corners": corner_metrics,
    }


def build_report() -> dict[str, Any]:
    rtl, gate, active_power, idle_gate, idle_power, physical = (
        read_json(INPUTS[name]) for name in INPUTS
    )
    validate_benchmark(rtl, "rtl")
    validate_benchmark(gate, "gate")
    require_equal(benchmark_projection(rtl), benchmark_projection(gate), "RTL/gate benchmark")
    require_equal(rtl["measurement_boundary"], gate["measurement_boundary"], "measurement boundary")
    require_equal(
        rtl["aggregate_vcd_measurement"],
        gate["aggregate_vcd_measurement"],
        "RTL/gate VCD measurement window",
    )
    validate_idle_benchmark(idle_gate, gate)
    active_gate_provenance = benchmark_provenance(
        gate, "active gate", "warm_attention"
    )
    idle_gate_provenance = benchmark_provenance(
        idle_gate, "idle gate", "idle_warm_window"
    )
    require_equal(
        active_gate_provenance,
        idle_gate_provenance,
        "active/idle gate benchmark provenance",
    )
    physical_provenance = power_provenance(
        active_power,
        idle_power,
        active_gate_provenance["pdk"]["identifier"],
    )
    vcd_validation = {
        "active": run_canonical_vcd_validator(
            INPUTS["gate"], ACTIVE_GATE_VCD, "active"
        ),
        "idle": run_canonical_vcd_validator(
            INPUTS["idle_gate"], IDLE_GATE_VCD, "idle"
        ),
    }
    timing_clock = validate_clock_provenance(
        gate,
        active_power,
        idle_power,
        Path(physical_provenance["artifacts"]["sdc"]),
    )

    measurement = gate["aggregate_vcd_measurement"]
    active_measurement = validate_power_result(
        active_power,
        gate,
        INPUTS["gate"],
        ACTIVE_GATE_VCD,
        "warm_attention",
        "active",
    )
    validate_power_result(
        idle_power,
        idle_gate,
        INPUTS["idle_gate"],
        IDLE_GATE_VCD,
        "idle_warm_window",
        "idle",
    )
    require_equal(
        active_power["physical_context"]["clock_period_ns"],
        idle_power["physical_context"]["clock_period_ns"],
        "active/idle power clock period",
    )
    require_equal(
        active_power["physical_context"]["corner"],
        idle_power["physical_context"]["corner"],
        "active/idle power corner",
    )
    require_equal(idle_power["energy"], None, "idle energy")
    require(
        active_power["power_w"]["total"] > idle_power["power_w"]["total"],
        "active total power is not greater than idle total power",
    )
    require(
        active_power["power_w"]["switching"] > idle_power["power_w"]["switching"],
        "active switching power is not greater than idle switching power",
    )

    expected_window_j = (
        active_power["power_w"]["total"] * active_measurement["duration_ns"] * 1e-9
    )
    expected_per_attention_nj = expected_window_j / active_measurement["transactions"] * 1e9
    require(
        math.isclose(
            active_power["energy"]["window_j"], expected_window_j, rel_tol=0, abs_tol=1e-18
        ),
        "power window energy does not equal total power times VCD duration",
    )
    require(
        math.isclose(
            active_power["energy"]["per_attention_nj"],
            expected_per_attention_nj,
            rel_tol=0,
            abs_tol=1e-12,
        ),
        "per-attention energy does not equal window energy divided by transactions",
    )
    delta_power_w = round(
        active_power["power_w"]["total"] - idle_power["power_w"]["total"], 15
    )
    incremental_energy_nj = round(
        delta_power_w * active_measurement["duration_ns"] / active_measurement["transactions"], 12
    )

    return {
        "schema_version": "1.3",
        "baseline": "fixed_workload_two_mac",
        "workload": {
            "identity": gate["benchmark"],
            "transaction_count": gate["transaction_count"],
            "resident_weights_packed": gate["resident_weights_packed"],
            "measurement_boundary": gate["measurement_boundary"],
            "vcd_window": measurement,
        },
        "correctness": {
            "python_golden_model": "pass",
            "rtl_simulation": "pass",
            "gate_simulation": "pass",
            "rtl_gate_external_equivalence": "pass",
        },
        "performance": {
            "clock_hz": gate["clock_hz"],
            "compute_cycles": gate["summary"]["compute_cycles"],
            "single_transaction_latency_cycles": gate["single_transaction_latency_cycles"],
            "steady_state_initiation_interval_cycles": gate[
                "steady_state_initiation_interval_cycles"
            ],
            "steady_state_throughput_attentions_per_second": gate[
                "steady_state_throughput_attentions_per_second"
            ],
        },
        "power": {
            "corner": active_power["physical_context"]["corner"],
            "clock_period_ns": active_power["physical_context"]["clock_period_ns"],
            "annotation": {
                "source": active_power["annotation_evidence"]["source"],
                "annotated_pin_count": active_power["annotation_evidence"]["annotated_pin_count"],
                "scope_signal_count": active_power["annotation_evidence"]["scope_signal_count"],
                "coverage_percent": active_power["annotation_evidence"][
                    "annotated_pin_coverage_percent"
                ],
            },
            "components_w": active_power["power_w"],
            "window_energy_j": active_power["energy"]["window_j"],
            "energy_per_attention_nj": active_power["energy"]["per_attention_nj"],
            "primary_pareto_metric": "total_active_energy_per_attention_nj",
        },
        "active_vs_idle": {
            "interpretation": "Idle subtraction is a sanity diagnostic; total active energy per attention remains the primary Pareto metric.",
            "active_total_power_w": active_power["power_w"]["total"],
            "idle_total_power_w": idle_power["power_w"]["total"],
            "delta_power_w": delta_power_w,
            "percent_increase_over_idle": round(
                delta_power_w / idle_power["power_w"]["total"] * 100, 12
            ),
            "idle_subtracted_incremental_energy_per_attention_nj": incremental_energy_nj,
            "idle_annotation": {
                "source": idle_power["annotation_evidence"]["source"],
                "annotated_pin_count": idle_power["annotation_evidence"]["annotated_pin_count"],
                "scope_signal_count": idle_power["annotation_evidence"]["scope_signal_count"],
                "coverage_percent": idle_power["annotation_evidence"][
                    "annotated_pin_coverage_percent"
                ],
            },
        },
        "physical_implementation": {
            "standard_cell_count": physical["design__instance__count__stdcell"],
            "standard_cell_area_um2": physical["design__instance__area__stdcell"],
            "timing": {
                **timing_constraints(physical),
                "constraint_clock": timing_clock,
            },
        },
        "provenance": {
            "gate_simulation": active_gate_provenance,
            "power_analysis": physical_provenance,
            "uses_file_hashes": False,
            "vcd_validation": vcd_validation,
        },
        "sources": {
            **{name: path.as_posix() for name, path in INPUTS.items()},
            "active_gate_vcd": ACTIVE_GATE_VCD.as_posix(),
            "idle_gate_vcd": IDLE_GATE_VCD.as_posix(),
            "physical_netlist": physical_provenance["artifacts"]["netlist"],
            "physical_spef": physical_provenance["artifacts"]["spef"],
            "power_liberty": physical_provenance["artifacts"]["liberty"],
            "timing_constraints": timing_clock["source"],
            "vcd_validator": VCD_VALIDATOR.as_posix(),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="report path (default: analysis/report/baseline_2mac.json)",
    )
    args = parser.parse_args()
    output = args.output if args.output.is_absolute() else ROOT / args.output
    try:
        report = build_report()
    except (KeyError, TypeError, ValueError) as error:
        print(f"baseline report validation failed: {error}", file=sys.stderr)
        return 1

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    try:
        display_path = output.relative_to(ROOT).as_posix()
    except ValueError:
        display_path = str(output)
    print(display_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
