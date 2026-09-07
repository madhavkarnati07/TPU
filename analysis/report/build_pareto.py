#!/usr/bin/env python3
"""Validate MAC-count experiment artifacts and build an initial Pareto report."""

from __future__ import annotations

import argparse
import csv
import html
import json
import math
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RESULTS_ROOT = ROOT / "analysis/pareto/results"
DEFAULT_OUTPUT_DIR = ROOT / "analysis/pareto"
VARIANTS = {"mac1": 1, "mac2": 2, "mac4": 4}
EXPECTED_COMPUTE_CYCLES = {"mac1": 148, "mac2": 108, "mac4": 64}
ARTIFACTS = (
    "rtl.json",
    "gate-active.json",
    "gate-idle.json",
    "power-active.json",
    "power-idle.json",
    "metrics.json",
    "physical-context.json",
)
EXPECTED_CLOCK_HZ = 10_000_000
EXPECTED_CLOCK_PERIOD_NS = 100
DESIGN_NAME = "tt_um_madhavkarnati_toy_tpu"
EXPECTED_PDK = "sky130A"
EXPECTED_SCL = "sky130_fd_sc_hd"
EXPECTED_DIE_AREA_UM = [0, 0, 334.88, 225.76]
EXPECTED_RTL_SOURCES = [
    "src/dual_int4_mac.v",
    "src/toy_attention_core.v",
    "src/project.v",
]
TIMING_CORNERS = re.compile(r"^timing__setup__wns__corner:(.+)$")
GIT_COMMIT = re.compile(r"^[0-9a-f]{40}$")


class ValidationError(ValueError):
    """Raised when artifacts cannot be compared fairly."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


def require_equal(left: Any, right: Any, name: str) -> None:
    require(left == right, f"mismatch for {name}")


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ValidationError(f"missing required artifact: {path}") from error
    except json.JSONDecodeError as error:
        raise ValidationError(f"invalid JSON in {path}: {error}") from error
    require(isinstance(value, dict), f"{path}: root must be a JSON object")
    return value


def number(value: Any, name: str, *, positive: bool = False) -> float:
    require(not isinstance(value, bool), f"{name} must be numeric")
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise ValidationError(f"{name} must be numeric") from error
    require(math.isfinite(result), f"{name} must be finite")
    require(result > 0 if positive else result >= 0, f"{name} has an invalid value")
    return result


def repo_relative_display(value: Any, name: str) -> str:
    require(isinstance(value, str) and value, f"{name} must be a path")
    path = Path(value)
    resolved = path.resolve() if path.is_absolute() else (ROOT / path).resolve()
    try:
        return resolved.relative_to(ROOT.resolve()).as_posix()
    except ValueError as error:
        raise ValidationError(f"{name} is outside the repository") from error


def pdk_revision_from_path(value: Any, name: str) -> str:
    path = Path(repo_relative_display(value, name))
    parts = path.parts
    require("versions" in parts, f"{name} does not contain a PDK version")
    index = parts.index("versions")
    require(index + 1 < len(parts), f"{name} lacks a PDK revision")
    require(
        parts[index + 2:index + 5] == (EXPECTED_PDK, "libs.ref", EXPECTED_SCL),
        f"{name} does not use {EXPECTED_PDK}/{EXPECTED_SCL}",
    )
    return parts[index + 1]


def require_lane(artifact: dict[str, Any], expected: int, label: str) -> None:
    require_equal(artifact["mac_lanes"], expected, f"{label} mac_lanes")


def transaction_projection(transaction: dict[str, Any], label: str) -> dict[str, Any]:
    required = (
        "index", "x", "x_packed", "expected_output", "expected_result_bytes",
        "observed_result_bytes", "compute_cycles", "latency_cycles",
        "initiation_interval_cycles",
    )
    for key in required:
        require(key in transaction, f"{label}: transaction lacks {key}")
    require_equal(
        transaction["observed_result_bytes"], transaction["expected_result_bytes"],
        f"{label}: observed result bytes",
    )
    return {key: transaction[key] for key in required}


def benchmark_projection(benchmark: dict[str, Any], lanes: int, label: str) -> dict[str, Any]:
    required = (
        "benchmark", "measurement_kind", "clock_hz", "transaction_count", "resident_weights_packed",
        "measurement_boundary", "transactions", "summary",
        "single_transaction_latency_cycles", "steady_state_initiation_interval_cycles",
        "steady_state_throughput_attentions_per_second", "aggregate_vcd_measurement",
    )
    for key in required:
        require(key in benchmark, f"{label}: missing {key}")
    require_lane(benchmark, lanes, label)
    require_equal(benchmark["clock_hz"], EXPECTED_CLOCK_HZ, f"{label} clock_hz")
    transaction_count = benchmark["transaction_count"]
    require(isinstance(transaction_count, int) and transaction_count > 0, f"{label}: invalid transaction_count")
    transactions = benchmark["transactions"]
    require(isinstance(transactions, list), f"{label}: transactions must be a list")
    require_equal(len(transactions), transaction_count, f"{label}: transaction list length")
    require(
        benchmark["summary"].get("all_outputs_match_golden_model") is True,
        f"{label}: golden-model comparison did not pass",
    )
    projected_transactions = []
    for index, transaction in enumerate(transactions):
        require(isinstance(transaction, dict), f"{label}: transaction {index} is not an object")
        require_equal(transaction.get("index"), index, f"{label}: transaction index")
        projected_transactions.append(transaction_projection(transaction, f"{label} transaction {index}"))
    summary = benchmark["summary"]
    for key in ("compute_cycles", "initiation_interval_cycles", "latency_cycles"):
        require(key in summary, f"{label}: summary lacks {key}")
    return {
        "benchmark": benchmark["benchmark"],
        "measurement_kind": benchmark["measurement_kind"],
        "clock_hz": benchmark["clock_hz"],
        "transaction_count": transaction_count,
        "resident_weights_packed": benchmark["resident_weights_packed"],
        "measurement_boundary": benchmark["measurement_boundary"],
        "transactions": projected_transactions,
        "summary": {key: summary[key] for key in ("compute_cycles", "initiation_interval_cycles", "latency_cycles")},
        "single_transaction_latency_cycles": benchmark["single_transaction_latency_cycles"],
        "steady_state_initiation_interval_cycles": benchmark["steady_state_initiation_interval_cycles"],
        "steady_state_throughput_attentions_per_second": benchmark["steady_state_throughput_attentions_per_second"],
        "aggregate_vcd_measurement": benchmark["aggregate_vcd_measurement"],
    }


def validate_idle(idle: dict[str, Any], active: dict[str, Any], lanes: int, label: str) -> None:
    for key in (
        "benchmark", "measurement_kind", "transaction_count",
        "matched_active_transaction_count", "clock_hz", "resident_weights_packed",
        "aggregate_vcd_measurement",
    ):
        require(key in idle, f"{label}: missing {key}")
    require_lane(idle, lanes, label)
    require_equal(idle["benchmark"], "idle_warm_window", f"{label} benchmark")
    require_equal(idle["measurement_kind"], "idle_warm_window", f"{label} measurement kind")
    require_equal(idle["transaction_count"], 0, f"{label} transaction count")
    require_equal(idle["matched_active_transaction_count"], active["transaction_count"], f"{label} matched active count")
    require_equal(idle["clock_hz"], EXPECTED_CLOCK_HZ, f"{label} clock_hz")
    require_equal(idle["resident_weights_packed"], active["resident_weights_packed"], f"{label} resident weights")
    require_equal(
        idle["aggregate_vcd_measurement"]["duration_ns"],
        active["aggregate_vcd_measurement"]["duration_ns"],
        f"{label} matched duration",
    )


def validate_power(
    power: dict[str, Any], benchmark: dict[str, Any], kind: str, label: str
) -> tuple[float | None, float]:
    for key in (
        "status", "measurement", "physical_context", "power_w", "energy",
        "annotation_evidence",
    ):
        require(key in power, f"{label}: missing {key}")
    require_equal(power["status"], "measured", f"{label} status")
    measurement = power["measurement"]
    require_equal(measurement["kind"], kind, f"{label} measurement kind")
    require_equal(measurement["benchmark"], benchmark["benchmark"], f"{label} benchmark")
    require_equal(measurement["transactions"], benchmark["transaction_count"], f"{label} transaction count")
    require_equal(power["physical_context"]["clock_period_ns"], EXPECTED_CLOCK_PERIOD_NS, f"{label} clock period")
    duration_ns = number(measurement["duration_ns"], f"{label} duration", positive=True)
    require_equal(
        duration_ns,
        number(
            benchmark["aggregate_vcd_measurement"]["duration_ns"],
            f"{label} benchmark duration",
            positive=True,
        ),
        f"{label} benchmark/power duration",
    )
    require(
        measurement["vcd_window"]["verified_against_benchmark"] is True,
        f"{label}: VCD window was not verified against its benchmark",
    )
    total_power_w = number(power["power_w"]["total"], f"{label} total power", positive=True)
    annotation = power["annotation_evidence"]
    require_equal(annotation["source"], "VCD", f"{label} activity source")
    require(annotation["vcd_reported"] is True, f"{label}: VCD was not reported")
    require_equal(annotation["unannotated_pin_count"], 0, f"{label} unannotated pins")
    require_equal(
        number(annotation["annotated_pin_coverage_percent"], f"{label} annotation coverage"),
        100.0,
        f"{label} annotation coverage",
    )
    require(
        annotation["annotated_pin_count"] > 0,
        f"{label}: no physical pins were activity-annotated",
    )
    if kind == "idle_warm_window":
        require_equal(power["energy"], None, f"{label} energy")
        return None, total_power_w
    energy = power["energy"]
    require(isinstance(energy, dict), f"{label}: energy must be an object")
    transactions = benchmark["transaction_count"]
    calculated_window_j = total_power_w * duration_ns * 1e-9
    calculated_per_attention_nj = calculated_window_j / transactions * 1e9
    reported_window_j = number(energy["window_j"], f"{label} window energy", positive=True)
    reported_per_attention_nj = number(energy["per_attention_nj"], f"{label} energy per attention", positive=True)
    require(math.isclose(reported_window_j, calculated_window_j, rel_tol=1e-9, abs_tol=1e-18), f"{label}: window energy does not equal total power times duration")
    require(math.isclose(reported_per_attention_nj, calculated_per_attention_nj, rel_tol=1e-9, abs_tol=1e-12), f"{label}: energy per attention does not equal window energy divided by transactions")
    return calculated_per_attention_nj, total_power_w


def extract_physical_metrics(metrics: dict[str, Any], label: str) -> dict[str, Any]:
    area = number(metrics["design__instance__area__stdcell"], f"{label} standard-cell area", positive=True)
    count = metrics["design__instance__count__stdcell"]
    require(isinstance(count, int) and count > 0, f"{label}: invalid standard-cell count")
    corners = sorted(match.group(1) for key in metrics if (match := TIMING_CORNERS.match(key)) is not None)
    require(corners, f"{label}: no setup timing corners")
    for corner in corners:
        for check in ("setup", "hold"):
            wns = number(metrics[f"timing__{check}__wns__corner:{corner}"], f"{label} {check} WNS")
            tns = number(metrics[f"timing__{check}__tns__corner:{corner}"], f"{label} {check} TNS")
            violations = number(metrics[f"timing__{check}_vio__count__corner:{corner}"], f"{label} {check} violations")
            require(wns >= 0 and tns == 0 and violations == 0, f"{label}: {check} timing failed at {corner}")
    for key in (
        "route__drc_errors",
        "magic__drc_error__count",
        "design__lvs_error__count",
    ):
        require_equal(metrics[key], 0, f"{label} {key}")
    return {
        "standard_cell_area_um2": area, "standard_cell_count": count,
        "die_area_um2": number(metrics["design__die__area"], f"{label} die area", positive=True),
        "core_area_um2": number(metrics["design__core__area"], f"{label} core area", positive=True),
        "placement_utilization": number(
            metrics["design__instance__utilization"], f"{label} placement utilization"
        ),
        "timing_status": "pass", "timing_corner_count": len(corners),
        "routing_drc_status": "pass",
        "magic_drc_status": "pass",
        "lvs_status": "pass",
        "max_slew_violation_count": int(
            number(metrics.get("design__max_slew_violation__count", 0), f"{label} max slew violations")
        ),
        "max_cap_violation_count": int(
            number(metrics.get("design__max_cap_violation__count", 0), f"{label} max cap violations")
        ),
    }


def validate_physical_context(
    context: dict[str, Any], metrics: dict[str, Any], gate: dict[str, Any],
    power: dict[str, Any], lanes: int, name: str
) -> dict[str, Any]:
    """Bind the summarized physical metrics to the resolved variant run."""

    label = f"{name} physical context"
    require_equal(context.get("schema_version"), "1.0", f"{label} schema version")
    require_equal(context.get("variant"), name, f"{label} variant")
    require_equal(context.get("run_tag"), name, f"{label} run tag")
    resolved = context.get("resolved_config")
    require(isinstance(resolved, dict), f"{label}: missing resolved_config")
    require_equal(resolved.get("design_name"), DESIGN_NAME, f"{label} design name")
    require_equal(
        resolved.get("synth_parameters"), [f"MAC_LANES={lanes}"],
        f"{label} synthesis parameters",
    )
    require_equal(resolved.get("die_area_um"), EXPECTED_DIE_AREA_UM, f"{label} die area")
    require_equal(resolved.get("tile_allocation"), "2x2", f"{label} tile allocation")
    require_equal(resolved.get("clock_period_ns"), EXPECTED_CLOCK_PERIOD_NS, f"{label} clock period")
    require_equal(resolved.get("pdk"), EXPECTED_PDK, f"{label} PDK")
    require_equal(
        resolved.get("standard_cell_library"), EXPECTED_SCL,
        f"{label} standard-cell library",
    )
    require_equal(resolved.get("rtl_sources"), EXPECTED_RTL_SOURCES, f"{label} RTL sources")

    binding = context.get("metrics_binding")
    require(isinstance(binding, dict), f"{label}: missing metrics_binding")
    require_equal(
        number(binding.get("standard_cell_area_um2"), f"{label} bound standard-cell area", positive=True),
        number(metrics["design__instance__area__stdcell"], f"{label} metrics standard-cell area", positive=True),
        f"{label} standard-cell area binding",
    )
    require_equal(
        binding.get("standard_cell_count"), metrics["design__instance__count__stdcell"],
        f"{label} standard-cell count binding",
    )
    require_equal(
        number(binding.get("die_area_um2"), f"{label} bound die area", positive=True),
        number(metrics["design__die__area"], f"{label} metrics die area", positive=True),
        f"{label} die-area binding",
    )
    require_equal(
        number(binding.get("core_area_um2"), f"{label} bound core area", positive=True),
        number(metrics["design__core__area"], f"{label} metrics core area", positive=True),
        f"{label} core-area binding",
    )
    source = context.get("source_provenance")
    require(isinstance(source, dict), f"{label}: missing source_provenance")
    require(
        isinstance(source.get("base_git_commit"), str)
        and GIT_COMMIT.fullmatch(source["base_git_commit"]) is not None,
        f"{label}: base Git commit must be a full commit ID",
    )
    require(
        isinstance(source.get("branch"), str) and source["branch"],
        f"{label}: missing source branch",
    )
    require_equal(source.get("worktree_state"), "clean", f"{label} RTL worktree state")
    require_equal(source.get("changed_rtl_files"), [], f"{label} changed RTL files")
    require_equal(source.get("rtl_files"), EXPECTED_RTL_SOURCES, f"{label} source RTL files")

    flow = context.get("flow")
    require(isinstance(flow, dict), f"{label}: missing flow")
    for key in ("librelane_version", "pdk_revision", "run_directory"):
        require(isinstance(flow.get(key), str) and flow[key], f"{label}: missing flow {key}")
    require_equal(flow["run_directory"], f"runs/{name}", f"{label} run directory")
    require_equal(
        flow["librelane_version"], power["physical_context"]["tool"]["librelane_version"],
        f"{label} LibreLane version",
    )
    gate_pdk = gate.get("provenance", {}).get("pdk")
    require(isinstance(gate_pdk, dict), f"{label}: gate result lacks PDK provenance")
    require_equal(gate_pdk.get("identifier"), flow["pdk_revision"], f"{label} gate PDK revision")
    require_equal(gate_pdk.get("pdk"), EXPECTED_PDK, f"{label} gate PDK")
    require_equal(
        gate_pdk.get("standard_cell_library"), EXPECTED_SCL,
        f"{label} gate standard-cell library",
    )
    require_equal(
        Path(repo_relative_display(gate_pdk.get("path"), f"{label} gate PDK path")).name,
        flow["pdk_revision"],
        f"{label} gate PDK path revision",
    )
    for key in ("tech_lef", "cell_lef_ef", "cell_lef_hd", "liberty"):
        require_equal(
            pdk_revision_from_path(
                power["physical_context"]["artifacts"][key], f"{label} power {key}"
            ),
            flow["pdk_revision"],
            f"{label} power {key} PDK revision",
        )
    return {
        "resolved_config": resolved,
        "source_provenance": source,
        "flow": flow,
    }


def validate_variant(name: str, lanes: int, results_root: Path) -> dict[str, Any]:
    variant_root = results_root / name
    artifacts = {filename: read_json(variant_root / filename) for filename in ARTIFACTS}
    rtl = artifacts["rtl.json"]
    gate = artifacts["gate-active.json"]
    idle = artifacts["gate-idle.json"]
    require_equal(rtl["simulation_mode"], "rtl", f"{name} RTL simulation mode")
    require_equal(gate["simulation_mode"], "gate", f"{name} gate simulation mode")
    require_equal(idle["simulation_mode"], "gate", f"{name} idle simulation mode")
    expected_gate_netlist = f"runs/{name}/final/pnl/{DESIGN_NAME}.pnl.v"
    require_equal(
        repo_relative_display(
            gate["provenance"]["gate_netlist"]["path"], f"{name} gate netlist"
        ),
        expected_gate_netlist,
        f"{name} gate netlist",
    )
    require_equal(
        idle["provenance"]["gate_netlist"],
        gate["provenance"]["gate_netlist"],
        f"{name} active/idle gate netlist",
    )
    require_equal(
        idle["provenance"]["pdk"],
        gate["provenance"]["pdk"],
        f"{name} active/idle gate PDK",
    )
    rtl_projection = benchmark_projection(rtl, lanes, f"{name} RTL")
    gate_projection = benchmark_projection(gate, lanes, f"{name} gate")
    require_equal(rtl_projection, gate_projection, f"{name} RTL/gate observable behavior and cycles")
    validate_idle(idle, gate, lanes, f"{name} gate idle")
    require_equal(
        artifacts["power-active.json"]["physical_context"],
        artifacts["power-idle.json"]["physical_context"],
        f"{name} active/idle physical context",
    )
    active_energy_nj, active_power_w = validate_power(artifacts["power-active.json"], gate, "warm_attention", f"{name} active power")
    _, idle_power_w = validate_power(artifacts["power-idle.json"], idle, "idle_warm_window", f"{name} idle power")
    require(active_energy_nj is not None, f"{name}: missing active energy")
    require(active_power_w >= idle_power_w, f"{name}: active power is lower than matched idle power")
    duration_ns = number(
        gate["aggregate_vcd_measurement"]["duration_ns"],
        f"{name} active duration",
        positive=True,
    )
    idle_subtracted_energy_nj = (
        (active_power_w - idle_power_w)
        * duration_ns
        / gate["transaction_count"]
    )
    physical = extract_physical_metrics(artifacts["metrics.json"], f"{name} metrics")
    physical_experiment = validate_physical_context(
        artifacts["physical-context.json"], artifacts["metrics.json"], gate,
        artifacts["power-active.json"], lanes, name
    )
    phase_metrics = rtl["summary"].get("rtl_phase_metrics_per_attention")
    require(isinstance(phase_metrics, dict), f"{name}: missing RTL phase metrics")
    require_equal(
        phase_metrics["useful_mac_operations"], 112, f"{name} useful MAC operations"
    )
    require_equal(
        rtl["summary"]["compute_cycles"]["mean"],
        float(EXPECTED_COMPUTE_CYCLES[name]),
        f"{name} compute schedule",
    )
    context = artifacts["power-active.json"]["physical_context"]
    expected_physical_artifacts = {
        "netlist": f"runs/{name}/final/nl/{DESIGN_NAME}.nl.v",
        "spef": f"runs/{name}/final/spef/nom/{DESIGN_NAME}.nom.spef",
        "sdc": f"runs/{name}/52-openroad-fillinsertion/{DESIGN_NAME}.sdc",
    }
    for artifact, expected_path in expected_physical_artifacts.items():
        require_equal(
            repo_relative_display(
                context["artifacts"][artifact], f"{name} power {artifact}"
            ),
            expected_path,
            f"{name} power {artifact}",
        )
    common_power_context = {
        "corner": context["corner"],
        "tool": context["tool"],
        "pdk_artifacts": {
            key: repo_relative_display(
                context["artifacts"][key], f"{name} power {key}"
            )
            for key in ("tech_lef", "cell_lef_ef", "cell_lef_hd", "liberty")
        },
    }
    return {
        "variant": name, "mac_lanes": lanes,
        "energy_per_attention_nj": active_energy_nj,
        "throughput_attentions_per_second": number(gate["steady_state_throughput_attentions_per_second"], f"{name} throughput", positive=True),
        "single_transaction_latency_cycles": number(gate["single_transaction_latency_cycles"], f"{name} latency", positive=True),
        "steady_state_initiation_interval_cycles": number(gate["steady_state_initiation_interval_cycles"], f"{name} initiation interval", positive=True),
        "compute_cycles": gate["summary"]["compute_cycles"],
        "phase_cycles": phase_metrics["phase_cycles"],
        "useful_mac_operations": phase_metrics["useful_mac_operations"],
        "lane_utilization": phase_metrics["lane_utilization"],
        "active_total_power_w": active_power_w, "idle_total_power_w": idle_power_w,
        "idle_subtracted_incremental_energy_per_attention_nj": idle_subtracted_energy_nj,
        **physical,
        "physical_experiment": physical_experiment,
        "common_power_context": common_power_context,
        "workload": {
            "identity": gate["measurement_kind"],
            "transaction_count": gate["transaction_count"],
            "resident_weights_packed": gate["resident_weights_packed"],
            "measurement_boundary": gate["measurement_boundary"],
            "transactions": [
                {
                    key: transaction[key]
                    for key in (
                        "index", "x", "x_packed", "expected_output",
                        "expected_result_bytes", "observed_result_bytes",
                    )
                }
                for transaction in gate_projection["transactions"]
            ],
        },
    }


def dominates(left: dict[str, Any], right: dict[str, Any]) -> bool:
    no_worse = (
        left["energy_per_attention_nj"] <= right["energy_per_attention_nj"]
        and left["standard_cell_area_um2"] <= right["standard_cell_area_um2"]
        and left["throughput_attentions_per_second"] >= right["throughput_attentions_per_second"]
    )
    strictly_better = (
        left["energy_per_attention_nj"] < right["energy_per_attention_nj"]
        or left["standard_cell_area_um2"] < right["standard_cell_area_um2"]
        or left["throughput_attentions_per_second"] > right["throughput_attentions_per_second"]
    )
    return no_worse and strictly_better


def mark_non_dominated(points: list[dict[str, Any]]) -> None:
    for point in points:
        dominators = [other["variant"] for other in points if dominates(other, point)]
        point["non_dominated"] = not dominators
        point["dominated_by"] = dominators


def build_report(results_root: Path) -> dict[str, Any]:
    points = [validate_variant(name, lanes, results_root) for name, lanes in VARIANTS.items()]
    reference = points[0]["workload"]
    reference_power_context = points[0]["common_power_context"]
    reference_physical = points[0]["physical_experiment"]
    for point in points[1:]:
        require_equal(point["workload"], reference, f"{point['variant']} fixed workload contract")
        require_equal(
            point["common_power_context"],
            reference_power_context,
            f"{point['variant']} common power context",
        )
        require_equal(
            point["physical_experiment"]["source_provenance"],
            reference_physical["source_provenance"],
            f"{point['variant']} RTL source provenance",
        )
        require_equal(
            {
                key: value
                for key, value in point["physical_experiment"]["flow"].items()
                if key != "run_directory"
            },
            {
                key: value
                for key, value in reference_physical["flow"].items()
                if key != "run_directory"
            },
            f"{point['variant']} physical-flow provenance",
        )
    mark_non_dominated(points)
    return {
        "schema_version": "1.0",
        "experiment": {
            "description": "Fixed-workload signed-int4 toy-attention MAC-lane sweep.",
            "clock_hz": EXPECTED_CLOCK_HZ, "mac_lane_counts": [1, 2, 4],
            "workload": reference,
            "objectives": {
                "minimize": ["energy_per_attention_nj", "standard_cell_area_um2"],
                "maximize": ["throughput_attentions_per_second"],
            },
        },
        "points": points,
        "non_dominated_variants": [point["variant"] for point in points if point["non_dominated"]],
    }


def write_csv(points: list[dict[str, Any]], path: Path) -> None:
    fields = (
        "variant", "mac_lanes", "energy_per_attention_nj", "throughput_attentions_per_second",
        "single_transaction_latency_cycles", "steady_state_initiation_interval_cycles",
        "lane_utilization", "useful_mac_operations",
        "idle_subtracted_incremental_energy_per_attention_nj",
        "standard_cell_area_um2", "standard_cell_count", "timing_status",
        "routing_drc_status", "magic_drc_status", "lvs_status",
        "max_slew_violation_count", "max_cap_violation_count",
        "non_dominated", "dominated_by",
    )
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for point in points:
            row = {field: point[field] for field in fields if field in point}
            row["dominated_by"] = ";".join(point["dominated_by"])
            writer.writerow(row)


def scale(value: float, low: float, high: float, start: float, length: float) -> float:
    return start + length / 2 if math.isclose(low, high) else start + (value - low) / (high - low) * length


def svg_plot(points: list[dict[str, Any]]) -> str:
    width, height = 860, 560
    left, right, top, bottom = 110, 40, 42, 200
    plot_width, plot_height = width - left - right, height - top - bottom
    energies = [point["energy_per_attention_nj"] for point in points]
    throughputs = [point["throughput_attentions_per_second"] for point in points]
    energy_low, energy_high = min(energies), max(energies)
    throughput_low, throughput_high = min(throughputs), max(throughputs)
    elements = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
        '<title id="title">Toy attention MAC lane Pareto plot</title>',
        '<desc id="desc">Energy per attention versus throughput. Green points are non-dominated.</desc>',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        '<style>text{font-family:Arial,sans-serif;fill:#17212b}.axis{stroke:#52606d;stroke-width:1}.grid{stroke:#d7dee5;stroke-width:1}.label{font-size:13px}.small{font-size:12px}.title{font-size:20px;font-weight:bold}.table{font-size:12px}</style>',
        '<text x="110" y="25" class="title">Fixed-workload MAC-lane sweep</text>',
    ]
    for fraction in (0, 0.5, 1):
        y = top + plot_height - fraction * plot_height
        energy = energy_low + fraction * (energy_high - energy_low)
        x = left + fraction * plot_width
        throughput = throughput_low + fraction * (throughput_high - throughput_low)
        elements.extend((
            f'<line class="grid" x1="{left}" y1="{y:.2f}" x2="{width - right}" y2="{y:.2f}"/>',
            f'<text class="small" x="{left - 12}" y="{y + 4:.2f}" text-anchor="end">{energy:.3g} nJ</text>',
            f'<line class="grid" x1="{x:.2f}" y1="{top}" x2="{x:.2f}" y2="{top + plot_height}"/>',
            f'<text class="small" x="{x:.2f}" y="{top + plot_height + 20}" text-anchor="middle">{throughput:.3g}</text>',
        ))
    elements.extend((
        f'<line class="axis" x1="{left}" y1="{top + plot_height}" x2="{width - right}" y2="{top + plot_height}"/>',
        f'<line class="axis" x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_height}"/>',
        f'<text class="label" x="{left + plot_width / 2}" y="{top + plot_height + 45}" text-anchor="middle">Throughput (attentions/s, higher is better)</text>',
        f'<text class="label" transform="translate(25 {top + plot_height / 2}) rotate(-90)" text-anchor="middle">Total active energy per attention (nJ, lower is better)</text>',
    ))
    for point in points:
        x = scale(point["throughput_attentions_per_second"], throughput_low, throughput_high, left, plot_width)
        y = top + plot_height - scale(point["energy_per_attention_nj"], energy_low, energy_high, 0, plot_height)
        color = "#007f6d" if point["non_dominated"] else "#b74a21"
        label = html.escape(f"{point['variant']} ({point['mac_lanes']} MAC)")
        label_x = x - 10 if x > left + plot_width - 120 else x + 10
        label_y = y + 20 if y < top + 20 else y - 10
        label_anchor = "end" if label_x < x else "start"
        elements.extend((
            f'<circle cx="{x:.2f}" cy="{y:.2f}" r="7" fill="{color}" stroke="#17212b" stroke-width="1"/>',
            f'<text class="label" x="{label_x:.2f}" y="{label_y:.2f}" text-anchor="{label_anchor}">{label}</text>',
        ))
    table_y = 410
    elements.extend((
        f'<text class="label" x="{left}" y="{table_y - 20}">Green: non-dominated across energy, area, and throughput. Orange: dominated.</text>',
        f'<line class="axis" x1="{left}" y1="{table_y}" x2="{width - right}" y2="{table_y}"/>',
        f'<text class="table" x="{left}" y="{table_y + 20}">Variant</text>',
        f'<text class="table" x="{left + 140}" y="{table_y + 20}">Energy (nJ)</text>',
        f'<text class="table" x="{left + 270}" y="{table_y + 20}">Throughput (/s)</text>',
        f'<text class="table" x="{left + 430}" y="{table_y + 20}">Area (um2)</text>',
        f'<text class="table" x="{left + 550}" y="{table_y + 20}">Timing</text>',
    ))
    for index, point in enumerate(points):
        y = table_y + 43 + 22 * index
        state = "Pareto" if point["non_dominated"] else "Dominated"
        elements.extend((
            f'<text class="table" x="{left}" y="{y}">{html.escape(point["variant"])} ({state})</text>',
            f'<text class="table" x="{left + 140}" y="{y}">{point["energy_per_attention_nj"]:.6g}</text>',
            f'<text class="table" x="{left + 270}" y="{y}">{point["throughput_attentions_per_second"]:.6g}</text>',
            f'<text class="table" x="{left + 430}" y="{y}">{point["standard_cell_area_um2"]:.6g}</text>',
            f'<text class="table" x="{left + 550}" y="{y}">{point["timing_status"]}</text>',
        ))
    elements.append("</svg>")
    return "\n".join(elements) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-root", type=Path, default=DEFAULT_RESULTS_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    results_root = args.results_root if args.results_root.is_absolute() else ROOT / args.results_root
    output_dir = args.output_dir if args.output_dir.is_absolute() else ROOT / args.output_dir
    try:
        report = build_report(results_root)
    except (KeyError, TypeError, ValidationError) as error:
        print(f"pareto report validation failed: {error}", file=sys.stderr)
        return 1
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "pareto.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_csv(report["points"], output_dir / "pareto.csv")
    (output_dir / "pareto.svg").write_text(svg_plot(report["points"]), encoding="utf-8")
    for filename in ("pareto.json", "pareto.csv", "pareto.svg"):
        print((output_dir / filename).resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
