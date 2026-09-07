#!/usr/bin/env python3
"""Synthetic contract tests for the Milestone 2 Pareto report builder."""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "report" / "build_pareto.py"
SPEC = importlib.util.spec_from_file_location("build_pareto", SCRIPT)
assert SPEC and SPEC.loader
BUILD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILD)


def active_benchmark(lanes: int, cycles: int, throughput: float) -> dict:
    transactions = []
    for index in range(2):
        output = [index, index + 1, index + 2, index + 3]
        transactions.append(
            {
                "index": index,
                "x": [[index, 0]],
                "x_packed": [index],
                "expected_output": [[index]],
                "expected_result_bytes": output,
                "observed_result_bytes": output,
                "compute_cycles": cycles,
                "latency_cycles": cycles + 10,
                "initiation_interval_cycles": None if index == 0 else cycles + 11,
            }
        )
    return {
        "mac_lanes": lanes,
        "benchmark": "fixed_warm_attention",
        "measurement_kind": "warm_attention",
        "simulation_mode": "rtl",
        "clock_hz": 10_000_000,
        "transaction_count": 2,
        "resident_weights_packed": {"wq": [16, 1], "wk": [16, 1], "wv": [16, 2]},
        "measurement_boundary": {"compute": "run through done"},
        "summary": {
            "all_outputs_match_golden_model": True,
            "compute_cycles": {"min": cycles, "mean": float(cycles), "max": cycles},
            "initiation_interval_cycles": {"min": cycles + 11, "mean": float(cycles + 11), "max": cycles + 11},
            "latency_cycles": {"min": cycles + 10, "mean": float(cycles + 10), "max": cycles + 10},
            "rtl_phase_metrics_per_attention": {
                "phase_cycles": {"project": cycles},
                "useful_mac_operations": 112,
                "lane_utilization": 112 / (cycles * lanes),
            },
        },
        "single_transaction_latency_cycles": float(cycles + 10),
        "steady_state_initiation_interval_cycles": float(cycles + 11),
        "steady_state_throughput_attentions_per_second": throughput,
        "aggregate_vcd_measurement": {
            "duration_ns": 2000,
            "transaction_count": 2,
        },
        "transactions": transactions,
    }


def idle_benchmark(lanes: int) -> dict:
    return {
        "mac_lanes": lanes,
        "benchmark": "idle_warm_window",
        "measurement_kind": "idle_warm_window",
        "simulation_mode": "gate",
        "transaction_count": 0,
        "matched_active_transaction_count": 2,
        "clock_hz": 10_000_000,
        "resident_weights_packed": {"wq": [16, 1], "wk": [16, 1], "wv": [16, 2]},
        "aggregate_vcd_measurement": {"duration_ns": 2000, "transaction_count": 0},
    }


def power(
    kind: str, transactions: int, total_w: float, duration_ns: float, variant: str
) -> dict:
    energy = None
    if transactions:
        window_j = total_w * duration_ns * 1e-9
        energy = {"window_j": window_j, "per_attention_nj": window_j / transactions * 1e9}
    return {
        "status": "measured",
        "measurement": {
            "kind": kind,
            "benchmark": "idle_warm_window" if kind == "idle_warm_window" else "fixed_warm_attention",
            "transactions": transactions,
            "duration_ns": duration_ns,
            "vcd_window": {"verified_against_benchmark": True},
        },
        "physical_context": {
            "clock_period_ns": 100,
            "corner": "nom_tt_025C_1v80",
            "tool": {"container_image": "fixed", "librelane_version": "test"},
            "artifacts": {
                "tech_lef": "pdk/versions/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/sky130A/libs.ref/sky130_fd_sc_hd/tech.lef",
                "cell_lef_ef": "pdk/versions/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/sky130A/libs.ref/sky130_fd_sc_hd/ef.lef",
                "cell_lef_hd": "pdk/versions/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/sky130A/libs.ref/sky130_fd_sc_hd/hd.lef",
                "liberty": "pdk/versions/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/sky130A/libs.ref/sky130_fd_sc_hd/nom.lib",
                "netlist": f"runs/{variant}/final/nl/tt_um_madhavkarnati_toy_tpu.nl.v",
                "spef": f"runs/{variant}/final/spef/nom/tt_um_madhavkarnati_toy_tpu.nom.spef",
                "sdc": f"runs/{variant}/52-openroad-fillinsertion/tt_um_madhavkarnati_toy_tpu.sdc",
            },
        },
        "power_w": {"total": total_w},
        "energy": energy,
        "annotation_evidence": {
            "source": "VCD",
            "vcd_reported": True,
            "unannotated_pin_count": 0,
            "annotated_pin_count": 100,
            "annotated_pin_coverage_percent": 100.0,
        },
    }


def metrics(area: float, count: int) -> dict:
    result = {
        "design__instance__area__stdcell": area,
        "design__instance__count__stdcell": count,
        "design__die__area": 75_602.5,
        "design__core__area": 72_564.6,
        "design__instance__utilization": area / 72_564.6,
        "route__drc_errors": 0,
        "magic__drc_error__count": 0,
        "design__lvs_error__count": 0,
    }
    for check in ("setup", "hold"):
        result[f"timing__{check}__wns__corner:nom_tt"] = 0.0
        result[f"timing__{check}__tns__corner:nom_tt"] = 0.0
        result[f"timing__{check}_vio__count__corner:nom_tt"] = 0
    return result


def physical_context(name: str, lanes: int, area: float, count: int) -> dict:
    return {
        "schema_version": "1.0",
        "variant": name,
        "run_tag": name,
        "resolved_config": {
            "design_name": "tt_um_madhavkarnati_toy_tpu",
            "synth_parameters": [f"MAC_LANES={lanes}"],
            "die_area_um": [0, 0, 334.88, 225.76],
            "tile_allocation": "2x2",
            "clock_period_ns": 100,
            "pdk": "sky130A",
            "standard_cell_library": "sky130_fd_sc_hd",
            "rtl_sources": [
                "src/dual_int4_mac.v",
                "src/toy_attention_core.v",
                "src/project.v",
            ],
        },
        "metrics_binding": {
            "standard_cell_area_um2": area,
            "standard_cell_count": count,
            "die_area_um2": 75_602.5,
            "core_area_um2": 72_564.6,
        },
        "source_provenance": {
            "base_git_commit": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            "branch": "test-branch",
            "worktree_state": "clean",
            "changed_rtl_files": [],
            "rtl_files": [
                "src/dual_int4_mac.v",
                "src/toy_attention_core.v",
                "src/project.v",
            ],
        },
        "flow": {
            "librelane_version": "test",
            "pdk_revision": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "run_directory": f"runs/{name}",
        },
    }


class BuildParetoTests(unittest.TestCase):
    def write_variant(
        self, root: Path, name: str, lanes: int, cycles: int, throughput: float,
        active_w: float, area: float,
    ) -> None:
        target = root / name
        target.mkdir(parents=True, exist_ok=True)
        rtl = active_benchmark(lanes, cycles, throughput)
        rtl["provenance"] = {"gate_netlist": None}
        gate = copy.deepcopy(rtl)
        gate["simulation_mode"] = "gate"
        gate["provenance"] = {
            "gate_netlist": {
                "path": f"runs/{name}/final/pnl/tt_um_madhavkarnati_toy_tpu.pnl.v",
                "path_kind": "repo_relative",
            },
            "pdk": {
                "identifier": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "path": "pdk/versions/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "path_kind": "repo_relative",
                "pdk": "sky130A",
                "standard_cell_library": "sky130_fd_sc_hd",
            },
        }
        idle = idle_benchmark(lanes)
        idle["provenance"] = copy.deepcopy(gate["provenance"])
        files = {
            "rtl.json": rtl,
            "gate-active.json": gate,
            "gate-idle.json": idle,
            "power-active.json": power("warm_attention", 2, active_w, 2000, name),
            "power-idle.json": power("idle_warm_window", 0, active_w / 2, 2000, name),
            "metrics.json": metrics(area, int(area)),
            "physical-context.json": physical_context(name, lanes, area, int(area)),
        }
        for filename, value in files.items():
            (target / filename).write_text(json.dumps(value), encoding="utf-8")

    def valid_root(self, root: Path) -> None:
        self.write_variant(root, "mac1", 1, 148, 60_000, 0.00020, 20_000)
        self.write_variant(root, "mac2", 2, 108, 84_000, 0.00030, 30_000)
        self.write_variant(root, "mac4", 4, 64, 120_000, 0.00040, 40_000)

    def test_builds_outputs_and_marks_tradeoffs_non_dominated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "results"
            output = Path(directory) / "output"
            self.valid_root(root)
            report = BUILD.build_report(root)
            self.assertEqual(report["non_dominated_variants"], ["mac1", "mac2", "mac4"])
            with mock.patch.object(
                sys,
                "argv",
                [str(SCRIPT), "--results-root", str(root), "--output-dir", str(output)],
            ):
                self.assertEqual(BUILD.main(), 0)
            self.assertTrue((output / "pareto.json").is_file())
            self.assertIn("standard_cell_area_um2", (output / "pareto.csv").read_text())
            self.assertIn("mac4 (4 MAC)", (output / "pareto.svg").read_text())

    def test_rejects_gate_cycle_disagreement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "results"
            self.valid_root(root)
            path = root / "mac2/gate-active.json"
            gate = json.loads(path.read_text())
            gate["transactions"][0]["compute_cycles"] += 1
            path.write_text(json.dumps(gate), encoding="utf-8")
            with self.assertRaisesRegex(BUILD.ValidationError, "RTL/gate"):
                BUILD.build_report(root)

    def test_rejects_bad_active_energy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "results"
            self.valid_root(root)
            path = root / "mac4/power-active.json"
            measured = json.loads(path.read_text())
            measured["energy"]["per_attention_nj"] *= 2
            path.write_text(json.dumps(measured), encoding="utf-8")
            with self.assertRaisesRegex(BUILD.ValidationError, "energy per attention"):
                BUILD.build_report(root)

    def test_rejects_cross_variant_observed_output_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "results"
            self.valid_root(root)
            for filename in ("rtl.json", "gate-active.json"):
                path = root / "mac4" / filename
                benchmark = json.loads(path.read_text())
                benchmark["transactions"][1]["expected_result_bytes"][0] = 9
                benchmark["transactions"][1]["observed_result_bytes"][0] = 9
                path.write_text(json.dumps(benchmark), encoding="utf-8")
            with self.assertRaisesRegex(BUILD.ValidationError, "fixed workload contract"):
                BUILD.build_report(root)

    def test_rejects_physical_variant_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "results"
            self.valid_root(root)
            path = root / "mac4/physical-context.json"
            context = json.loads(path.read_text())
            context["resolved_config"]["synth_parameters"] = ["MAC_LANES=2"]
            path.write_text(json.dumps(context), encoding="utf-8")
            with self.assertRaisesRegex(BUILD.ValidationError, "synthesis parameters"):
                BUILD.build_report(root)

    def test_rejects_metrics_not_bound_to_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "results"
            self.valid_root(root)
            path = root / "mac1/metrics.json"
            result = json.loads(path.read_text())
            result["design__instance__area__stdcell"] += 1
            path.write_text(json.dumps(result), encoding="utf-8")
            with self.assertRaisesRegex(BUILD.ValidationError, "area binding"):
                BUILD.build_report(root)

    def test_rejects_gate_pdk_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "results"
            self.valid_root(root)
            for filename in ("gate-active.json", "gate-idle.json"):
                path = root / "mac2" / filename
                gate = json.loads(path.read_text())
                gate["provenance"]["pdk"]["identifier"] = "c" * 40
                path.write_text(json.dumps(gate), encoding="utf-8")
            with self.assertRaisesRegex(BUILD.ValidationError, "gate PDK revision"):
                BUILD.build_report(root)

    def test_rejects_active_idle_gate_pdk_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "results"
            self.valid_root(root)
            path = root / "mac2/gate-idle.json"
            idle = json.loads(path.read_text())
            idle["provenance"]["pdk"]["pdk"] = "gf180mcuD"
            path.write_text(json.dumps(idle), encoding="utf-8")
            with self.assertRaisesRegex(BUILD.ValidationError, "active/idle gate PDK"):
                BUILD.build_report(root)

    def test_rejects_incomplete_flow_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "results"
            self.valid_root(root)
            path = root / "mac1/physical-context.json"
            context = json.loads(path.read_text())
            context["flow"] = {}
            path.write_text(json.dumps(context), encoding="utf-8")
            with self.assertRaisesRegex(BUILD.ValidationError, "missing flow"):
                BUILD.build_report(root)

    def test_rejects_power_standard_cell_library_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "results"
            self.valid_root(root)
            for filename in ("power-active.json", "power-idle.json"):
                path = root / "mac4" / filename
                result = json.loads(path.read_text())
                for key, value in result["physical_context"]["artifacts"].items():
                    if key in ("tech_lef", "cell_lef_ef", "cell_lef_hd", "liberty"):
                        result["physical_context"]["artifacts"][key] = value.replace(
                            "sky130A/libs.ref/sky130_fd_sc_hd",
                            "gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu7t5v0",
                        )
                path.write_text(json.dumps(result), encoding="utf-8")
            with self.assertRaisesRegex(BUILD.ValidationError, "does not use sky130A"):
                BUILD.build_report(root)

    def test_marks_dominated_point(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "results"
            self.valid_root(root)
            self.write_variant(root, "mac4", 4, 64, 80_000, 0.00035, 35_000)
            report = BUILD.build_report(root)
            mac4 = next(point for point in report["points"] if point["variant"] == "mac4")
            self.assertFalse(mac4["non_dominated"])
            self.assertEqual(mac4["dominated_by"], ["mac2"])

    def test_checked_in_power_paths_are_portable(self) -> None:
        results = SCRIPT.parents[1] / "pareto" / "results"
        for name in BUILD.VARIANTS:
            for kind in ("active", "idle"):
                result = json.loads((results / name / f"power-{kind}.json").read_text())
                for value in result["physical_context"]["artifacts"].values():
                    self.assertFalse(Path(value).is_absolute(), value)


if __name__ == "__main__":
    unittest.main()
