#!/usr/bin/env python3
"""Contract tests for the Milestone 3 architecture analysis."""

from __future__ import annotations

import copy
import importlib.util
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "report" / "build_architecture_analysis.py"
SPEC = importlib.util.spec_from_file_location("build_architecture_analysis", SCRIPT)
assert SPEC and SPEC.loader
BUILD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILD)
PARETO = Path(__file__).with_name("pareto.json")
INITIAL_REPORT = Path(__file__).parents[1] / "INITIAL_REPORT.md"


class ArchitectureAnalysisTests(unittest.TestCase):
    def test_derived_scaling_metrics(self) -> None:
        data = BUILD.derive(BUILD.load_report(PARETO))
        mac4 = data["rows"][2]
        self.assertAlmostEqual(data["scalar_mac_operations"], 112)
        self.assertAlmostEqual(data["serial_compute_cycles"], 36)
        self.assertAlmostEqual(data["protocol_cycles"], 11)
        self.assertAlmostEqual(data["serial_floor_cycles"], 47)
        self.assertAlmostEqual(mac4["speedup"], 159 / 75)
        self.assertAlmostEqual(mac4["runtime_reduction_pct"], 100 * (1 - 75 / 159))
        self.assertAlmostEqual(
            mac4["energy_change_pct"],
            100 * (3.2235494287500006 / 5.63557116579 - 1),
        )
        self.assertAlmostEqual(
            mac4["power_change_pct"],
            100 * (0.0004298065905 / 0.0003544384381 - 1),
        )
        self.assertAlmostEqual(
            mac4["area_change_pct"],
            100 * (56065.0 / 46757.3 - 1),
        )
        self.assertAlmostEqual(data["score_parallel_interval"], 103)
        self.assertAlmostEqual(data["score_parallel_throughput"], 10_000_000 / 103)

    def test_outputs_include_evidence_boundary_and_hypothesis(self) -> None:
        data = BUILD.derive(BUILD.load_report(PARETO))
        document = BUILD.render_html(data)
        summary = BUILD.render_summary(data)
        self.assertIn("Evidence boundary", document)
        self.assertIn("16-cycle schedule gap", document)
        self.assertIn("This is a hypothesis, not a measured design point", summary)
        self.assertIn("2.12x", summary)

    def test_initial_report_tracks_current_results_and_extension_slots(self) -> None:
        data = BUILD.derive(BUILD.load_report(PARETO))
        report = INITIAL_REPORT.read_text(encoding="utf-8")
        for row in data["rows"]:
            table_row = (
                f'| {row["mac_lanes"]} | {row["interval"]:.0f} | {row["throughput"]:,.0f} | '
                f'{row["power_mw"]:.3f} | {row["energy"]:.3f} | {row["area"]:,.1f} | '
                f'{row["utilization_pct"]:.1f}% |'
            )
            self.assertIn(table_row, report)
        self.assertIn("### A. Two-MAC Score Scheduler", report)
        self.assertIn("### B. Input-Activity Sensitivity", report)
        self.assertIn("### C. Scaling Beyond Four MACs", report)
        self.assertIn("## 9. Experiment Record Template", report)

    def test_main_writes_both_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            html_path = root / "analysis.html"
            summary_path = root / "summary.md"
            with mock.patch.object(
                sys,
                "argv",
                [
                    str(SCRIPT), "--input", str(PARETO), "--html", str(html_path),
                    "--summary", str(summary_path),
                ],
            ):
                self.assertEqual(BUILD.main(), 0)
            self.assertEqual(html_path.read_text(), Path(BUILD.DEFAULT_HTML).read_text())
            self.assertEqual(summary_path.read_text(), Path(BUILD.DEFAULT_SUMMARY).read_text())

    def test_rejects_unverified_clock_or_physical_status(self) -> None:
        report = copy.deepcopy(BUILD.load_report(PARETO))
        report["experiment"]["clock_hz"] = 5_000_000
        with self.assertRaisesRegex(BUILD.AnalysisError, "10 MHz"):
            BUILD.derive(report)

        report = copy.deepcopy(BUILD.load_report(PARETO))
        report["points"][1]["timing_status"] = "fail"
        with self.assertRaisesRegex(BUILD.AnalysisError, "timing_status"):
            BUILD.derive(report)

    def test_rejects_workload_or_pareto_mismatch(self) -> None:
        report = copy.deepcopy(BUILD.load_report(PARETO))
        report["points"][2]["workload"]["transaction_count"] = 15
        with self.assertRaisesRegex(BUILD.AnalysisError, "workload mismatch"):
            BUILD.derive(report)

        report = copy.deepcopy(BUILD.load_report(PARETO))
        report["points"][2]["non_dominated"] = False
        with self.assertRaisesRegex(BUILD.AnalysisError, "not non-dominated"):
            BUILD.derive(report)

        report = copy.deepcopy(BUILD.load_report(PARETO))
        report["experiment"]["workload"]["transactions"][0]["x"][0] = [1, 0, 1]
        for point in report["points"]:
            point["workload"] = copy.deepcopy(report["experiment"]["workload"])
        with self.assertRaisesRegex(BUILD.AnalysisError, "two-dimensional"):
            BUILD.derive(report)

        report = copy.deepcopy(BUILD.load_report(PARETO))
        report["experiment"]["workload"]["transactions"][0]["observed_result_bytes"] = [0, 0, 0, 0]
        for point in report["points"]:
            point["workload"] = copy.deepcopy(report["experiment"]["workload"])
        with self.assertRaisesRegex(BUILD.AnalysisError, "golden output"):
            BUILD.derive(report)

    def test_rejects_wrong_tile(self) -> None:
        report = copy.deepcopy(BUILD.load_report(PARETO))
        report["points"][0]["physical_experiment"]["resolved_config"]["tile_allocation"] = "1x1"
        with self.assertRaisesRegex(BUILD.AnalysisError, "not a 2x2 tile"):
            BUILD.derive(report)


if __name__ == "__main__":
    unittest.main()
