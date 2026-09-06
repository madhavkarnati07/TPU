from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

import run_power


class PowerInputIntegrityTests(unittest.TestCase):
    def write_json(self, directory: Path, payload: dict) -> Path:
        path = directory / "benchmark.json"
        path.write_text(json.dumps(payload), encoding="ascii")
        return path

    def write_vcd(self, directory: Path, first: int = 100, last: int = 300) -> Path:
        path = directory / "window.vcd"
        path.write_text(
            "$timescale\n  1 ns\n$end\n"
            "$scope module tb $end\n"
            "$var wire 1 ! clk $end\n"
            "$upscope $end\n"
            "$enddefinitions $end\n"
            f"#{first}\n0!\n#{last}\n1!\n",
            encoding="ascii",
        )
        return path

    def benchmark(self, *, kind: str = "warm_attention", mode: str = "gate") -> dict:
        transactions = 1 if kind == "warm_attention" else 0
        benchmark_name = (
            "warm_attention_baseline" if kind == "warm_attention" else "idle_warm_window"
        )
        payload = {
            "benchmark": benchmark_name,
            "simulation_mode": mode,
            "clock_hz": 10_000_000,
            "transaction_count": transactions,
            "aggregate_vcd_measurement": {
                "start_cycle": 1,
                "end_cycle": 3,
                "duration_cycles": 2,
                "duration_ns": 200,
                "transaction_count": transactions,
            },
        }
        if kind == "warm_attention":
            payload["summary"] = {"all_outputs_match_golden_model": True}
            payload["transactions"] = [{}]
        return payload

    def test_active_gate_benchmark_binds_exact_vcd_window(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            benchmark = run_power.benchmark_measurement(
                self.write_json(directory, self.benchmark())
            )
            window = run_power.read_vcd_window(self.write_vcd(directory))
            run_power.verify_vcd_window(window, benchmark)
            self.assertEqual(benchmark["kind"], "warm_attention")
            self.assertEqual(benchmark["transactions"], 1)

    def test_idle_gate_benchmark_has_no_attention_transactions(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            benchmark = run_power.benchmark_measurement(
                self.write_json(directory, self.benchmark(kind="idle_warm_window"))
            )
            self.assertEqual(benchmark["kind"], "idle_warm_window")
            self.assertEqual(benchmark["transactions"], 0)

    def test_rtl_benchmark_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            path = self.write_json(directory, self.benchmark(mode="rtl"))
            with self.assertRaisesRegex(ValueError, "must come from gate simulation"):
                run_power.benchmark_measurement(path)

    def test_vcd_boundary_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            benchmark = run_power.benchmark_measurement(
                self.write_json(directory, self.benchmark())
            )
            window = run_power.read_vcd_window(self.write_vcd(directory, last=301))
            with self.assertRaisesRegex(ValueError, "VCD ends"):
                run_power.verify_vcd_window(window, benchmark)

    def test_measured_cli_requires_benchmark_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            argv = [
                "run_power.py",
                "--vcd",
                "unused.vcd",
                "--scope",
                "tb.user_project",
                "--output-dir",
                str(Path(temp) / "out"),
            ]
            with mock.patch.object(sys, "argv", argv):
                with self.assertRaisesRegex(ValueError, "--benchmark-result is required"):
                    run_power.main()

    def test_measured_cli_rejects_manual_accounting(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            argv = [
                "run_power.py",
                "--benchmark-result",
                "unused.json",
                "--vcd",
                "unused.vcd",
                "--scope",
                "tb.user_project",
                "--duration-ns",
                "200",
                "--transactions",
                "1",
                "--output-dir",
                str(Path(temp) / "out"),
            ]
            with mock.patch.object(sys, "argv", argv):
                with self.assertRaisesRegex(ValueError, "forbidden for measured power"):
                    run_power.main()

    def test_energy_is_computed_only_for_active_attention(self) -> None:
        power = {"total": 0.002}
        active = run_power.attention_energy(
            "warm_attention", power, Fraction(200), 2
        )
        self.assertAlmostEqual(active["window_j"], 4e-10)
        self.assertAlmostEqual(active["per_attention_nj"], 0.2)
        self.assertIsNone(
            run_power.attention_energy("idle_warm_window", power, Fraction(200), 0)
        )

    def test_power_report_uses_and_preserves_high_precision(self) -> None:
        artifacts = {
            name: Path(f"/{name}")
            for name in (
                "tech_lef",
                "cell_lef_ef",
                "cell_lef_hd",
                "liberty",
                "netlist",
                "sdc",
                "spef",
            )
        }
        tcl = run_power.render_tcl(
            config={"design_name": "dut", "clock": {"port": "clk"}},
            artifacts=artifacts,
            vcd=Path("/window.vcd"),
            scope="tb/dut",
            include_power_report=True,
        )
        self.assertIn("report_power -digits 9", tcl)

        report = (
            "Total 1.234567890e-04 2.345678901e-04 "
            "3.456789012e-07 3.583703580e-04\n"
        )
        power = run_power.parse_total_power(report)
        self.assertEqual(power["total"], 0.000358370358)
        self.assertIn("0.000358370358", json.dumps(power))
        energy = run_power.attention_energy(
            "warm_attention", power, Fraction(190400), 16
        )
        rounded_energy = run_power.attention_energy(
            "warm_attention", {"total": 0.000358}, Fraction(190400), 16
        )
        self.assertNotEqual(
            energy["per_attention_nj"], rounded_energy["per_attention_nj"]
        )

    def test_output_invalidation_removes_only_runner_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output_dir = Path(temp)
            for name in run_power.OUTPUT_ARTIFACTS:
                (output_dir / name).write_text("stale", encoding="ascii")
            unrelated = output_dir / "notes.txt"
            unrelated.write_text("keep", encoding="ascii")

            run_power.invalidate_output_artifacts(output_dir)

            self.assertTrue(unrelated.is_file())
            self.assertTrue(
                all(not (output_dir / name).exists() for name in run_power.OUTPUT_ARTIFACTS)
            )

    def test_main_invalidates_stale_success_before_later_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output_dir = Path(temp) / "out"
            output_dir.mkdir()
            stale_result = output_dir / "result.json"
            stale_result.write_text("stale", encoding="ascii")
            argv = [
                "run_power.py",
                "--config",
                str(Path(temp) / "missing-config.json"),
                "--output-dir",
                str(output_dir),
            ]
            with mock.patch.object(sys, "argv", argv):
                with self.assertRaises(FileNotFoundError):
                    run_power.main()
            self.assertFalse(stale_result.exists())

    def test_docker_command_name_is_resolved_from_path(self) -> None:
        with mock.patch.object(
            run_power.shutil, "which", return_value="/opt/homebrew/bin/docker"
        ) as which:
            self.assertEqual(
                run_power.resolve_executable("docker"), "/opt/homebrew/bin/docker"
            )
        which.assert_called_once_with("docker")

    def test_absolute_docker_path_must_be_executable(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            executable = Path(temp) / "docker"
            executable.write_text("#!/bin/sh\n", encoding="ascii")
            executable.chmod(0o755)
            self.assertEqual(run_power.resolve_executable(str(executable)), str(executable))

            executable.chmod(0o644)
            with self.assertRaisesRegex(PermissionError, "not executable"):
                run_power.resolve_executable(str(executable))


if __name__ == "__main__":
    unittest.main()
