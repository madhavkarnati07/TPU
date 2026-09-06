#!/usr/bin/env python3
"""Run activity-aware, post-route OpenSTA power analysis for a warm VCD."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from fractions import Fraction
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
IMAGE_DEFAULT = (
    "ghcr.io/librelane/librelane@sha256:"
    "25e8d8a54dd9587132971f3061dfdbbab7b4c4d07a454a62d623543d862d3abb"
)
POWER_REPORT_DIGITS = 9
OUTPUT_ARTIFACTS = (
    "result.json",
    "rejected.json",
    "power.rpt",
    "activity_annotation.rpt",
    "activity_unannotated.rpt",
    "openroad.log",
    "power.tcl",
)
BENCHMARK_KINDS = {
    "warm_attention_baseline": "warm_attention",
    "idle_warm_window": "idle_warm_window",
}
MEASUREMENT_KINDS = frozenset(BENCHMARK_KINDS.values())
VCD_UNIT_TO_FS = {
    "s": 1_000_000_000_000_000,
    "ms": 1_000_000_000_000,
    "us": 1_000_000_000,
    "ns": 1_000_000,
    "ps": 1_000,
    "fs": 1,
}


@dataclass(frozen=True)
class VcdWindow:
    timescale_magnitude: int
    timescale_unit: str
    first_timestamp: int
    last_timestamp: int

    @property
    def timestep_fs(self) -> int:
        return self.timescale_magnitude * VCD_UNIT_TO_FS[self.timescale_unit]

    @property
    def first_fs(self) -> int:
        return self.first_timestamp * self.timestep_fs

    @property
    def last_fs(self) -> int:
        return self.last_timestamp * self.timestep_fs

    @property
    def duration_fs(self) -> int:
        return self.last_fs - self.first_fs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).with_name("power_config.example.json"),
        help="JSON configuration; artifact paths are relative to the repository root.",
    )
    parser.add_argument("--vcd", type=Path, help="Gate-level VCD for the warm window.")
    parser.add_argument("--scope", help="VCD scope that maps to the hardened top module.")
    parser.add_argument(
        "--benchmark-result",
        type=Path,
        help="Gate-simulation benchmark JSON; required for measured power.",
    )
    parser.add_argument(
        "--duration-ns",
        type=float,
        help="Manual VCD duration, accepted only with --validation-only.",
    )
    parser.add_argument(
        "--transactions",
        type=int,
        help="Manual transaction count, accepted only with --validation-only.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).with_name("out"),
        help="Directory for generated TCL, logs, evidence, and result.json.",
    )
    parser.add_argument(
        "--validation-only",
        action="store_true",
        help="Validate VCD annotation plumbing without emitting a power or energy result.",
    )
    return parser.parse_args()


def read_config(path: Path) -> dict[str, Any]:
    with path.open(encoding="ascii") as config_file:
        config = json.load(config_file)
    if config.get("schema_version") != "1.0":
        raise ValueError("power config schema_version must be 1.0")
    return config


def resolve_repo_path(value: str) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (REPO_ROOT / path).resolve()


def invalidate_output_artifacts(output_dir: Path) -> None:
    """Remove only files owned by this runner, leaving unrelated output intact."""

    output_dir.mkdir(parents=True, exist_ok=True)
    for name in OUTPUT_ARTIFACTS:
        artifact = output_dir / name
        if artifact.exists() or artifact.is_symlink():
            artifact.unlink()


def resolve_executable(command: str) -> str:
    if not isinstance(command, str) or not command:
        raise ValueError("docker_bin must be a nonempty command name or absolute path")
    candidate = Path(command)
    if candidate.is_absolute():
        if not candidate.is_file():
            raise FileNotFoundError(f"docker executable does not exist: {candidate}")
        if not os.access(candidate, os.X_OK):
            raise PermissionError(f"docker executable is not executable: {candidate}")
        return str(candidate)

    resolved = shutil.which(command)
    if resolved is None:
        raise FileNotFoundError(f"docker executable not found on PATH: {command}")
    return resolved


def read_json_object(path: Path, description: str) -> dict[str, Any]:
    try:
        with path.open(encoding="ascii") as input_file:
            value = json.load(input_file)
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid {description} JSON {path}: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{description} must contain a JSON object: {path}")
    return value


def positive_fraction(value: Any, name: str) -> Fraction:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    result = Fraction(str(value))
    if result <= 0:
        raise ValueError(f"{name} must be positive")
    return result


def benchmark_measurement(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"benchmark result does not exist: {path}")
    benchmark = read_json_object(path, "benchmark result")
    if benchmark.get("simulation_mode") != "gate":
        raise ValueError("benchmark result must come from gate simulation")

    benchmark_name = benchmark.get("benchmark")
    if not isinstance(benchmark_name, str) or not benchmark_name:
        raise ValueError("benchmark result must name its benchmark")
    explicit_kind = benchmark.get("measurement_kind")
    inferred_kind = BENCHMARK_KINDS.get(benchmark_name)
    if explicit_kind is not None and explicit_kind not in MEASUREMENT_KINDS:
        raise ValueError(f"unsupported benchmark measurement_kind: {explicit_kind!r}")
    if explicit_kind is not None and inferred_kind is not None and explicit_kind != inferred_kind:
        raise ValueError(
            f"benchmark identity {benchmark_name!r} conflicts with measurement_kind "
            f"{explicit_kind!r}"
        )
    kind = explicit_kind or inferred_kind
    if kind is None:
        raise ValueError(
            f"cannot derive measurement kind from benchmark identity {benchmark_name!r}"
        )

    window = benchmark.get("aggregate_vcd_measurement")
    if not isinstance(window, dict):
        raise ValueError("benchmark result lacks aggregate_vcd_measurement")
    start_cycle = window.get("start_cycle")
    end_cycle = window.get("end_cycle")
    duration_cycles = window.get("duration_cycles")
    for value, name in (
        (start_cycle, "start_cycle"),
        (end_cycle, "end_cycle"),
        (duration_cycles, "duration_cycles"),
    ):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"aggregate_vcd_measurement.{name} must be an integer")
    if start_cycle < 0 or end_cycle <= start_cycle:
        raise ValueError("benchmark VCD start/end cycles are invalid")
    if duration_cycles != end_cycle - start_cycle:
        raise ValueError("benchmark VCD duration_cycles does not equal end_cycle - start_cycle")

    duration_ns = positive_fraction(
        window.get("duration_ns"), "aggregate_vcd_measurement.duration_ns"
    )
    clock_hz = positive_fraction(benchmark.get("clock_hz"), "clock_hz")
    clock_period_ns = Fraction(1_000_000_000, 1) / clock_hz
    if duration_ns != duration_cycles * clock_period_ns:
        raise ValueError("benchmark VCD duration_ns is inconsistent with cycles and clock_hz")

    transactions = window.get("transaction_count")
    if isinstance(transactions, bool) or not isinstance(transactions, int):
        raise ValueError("aggregate_vcd_measurement.transaction_count must be an integer")
    root_transactions = benchmark.get("transaction_count")
    if root_transactions != transactions:
        raise ValueError("benchmark transaction counts disagree")
    if kind == "warm_attention":
        if transactions < 1:
            raise ValueError("warm_attention requires at least one transaction")
        summary = benchmark.get("summary")
        if (
            not isinstance(summary, dict)
            or summary.get("all_outputs_match_golden_model") is not True
        ):
            raise ValueError("warm_attention gate benchmark did not match the golden model")
        transaction_rows = benchmark.get("transactions")
        if not isinstance(transaction_rows, list) or len(transaction_rows) != transactions:
            raise ValueError("warm_attention transaction list does not match transaction_count")
    elif transactions != 0:
        raise ValueError("idle_warm_window must contain zero attention transactions")

    return {
        "path": path,
        "benchmark": benchmark_name,
        "kind": kind,
        "duration_ns": duration_ns,
        "transactions": transactions,
        "start_cycle": start_cycle,
        "end_cycle": end_cycle,
        "duration_cycles": duration_cycles,
        "clock_hz": clock_hz,
        "clock_period_ns": clock_period_ns,
    }


def read_vcd_window(vcd: Path) -> VcdWindow:
    timescale_text = ""
    collecting_timescale = False
    timescale: tuple[int, str] | None = None
    first_timestamp = None
    last_timestamp = None
    with vcd.open(encoding="ascii", errors="replace") as waveform:
        for raw_line in waveform:
            line = raw_line.strip()
            if line.startswith("$timescale"):
                collecting_timescale = True
                timescale_text = line
            elif collecting_timescale:
                timescale_text += " " + line
            if collecting_timescale and "$end" in timescale_text:
                match = re.fullmatch(
                    r"\$timescale\s+(\d+)\s*(fs|ps|ns|us|ms|s)\s+\$end",
                    timescale_text,
                )
                if match is None:
                    raise ValueError(f"could not parse VCD timescale: {timescale_text!r}")
                timescale = (int(match.group(1)), match.group(2))
                collecting_timescale = False

            timestamp_match = re.fullmatch(r"#(\d+)", line)
            if timestamp_match is not None:
                timestamp = int(timestamp_match.group(1))
                if last_timestamp is not None and timestamp < last_timestamp:
                    raise ValueError("VCD timestamps are not monotonically increasing")
                if first_timestamp is None:
                    first_timestamp = timestamp
                last_timestamp = timestamp

    if timescale is None:
        raise ValueError(f"could not find VCD timescale in {vcd}")
    if first_timestamp is None or last_timestamp is None:
        raise ValueError(f"no VCD timestamps found in {vcd}")
    if last_timestamp <= first_timestamp:
        raise ValueError("VCD must span more than one timestamp")
    return VcdWindow(*timescale, first_timestamp, last_timestamp)


def fraction_to_number(value: Fraction) -> int | float:
    return value.numerator if value.denominator == 1 else float(value)


def vcd_window_evidence(window: VcdWindow) -> dict[str, Any]:
    fs_per_ns = 1_000_000
    return {
        "timescale": f"{window.timescale_magnitude} {window.timescale_unit}",
        "first_timestamp": window.first_timestamp,
        "last_timestamp": window.last_timestamp,
        "first_time_ns": fraction_to_number(Fraction(window.first_fs, fs_per_ns)),
        "last_time_ns": fraction_to_number(Fraction(window.last_fs, fs_per_ns)),
        "duration_ns": fraction_to_number(Fraction(window.duration_fs, fs_per_ns)),
    }


def verify_vcd_window(window: VcdWindow, benchmark: dict[str, Any]) -> None:
    fs_per_ns = 1_000_000
    expected_first_fs = benchmark["start_cycle"] * benchmark["clock_period_ns"] * fs_per_ns
    expected_last_fs = benchmark["end_cycle"] * benchmark["clock_period_ns"] * fs_per_ns
    expected_duration_fs = benchmark["duration_ns"] * fs_per_ns
    if window.first_fs != expected_first_fs:
        raise ValueError(
            f"VCD starts at {window.first_fs / fs_per_ns:g} ns; benchmark expects "
            f"{float(expected_first_fs / fs_per_ns):g} ns"
        )
    if window.last_fs != expected_last_fs:
        raise ValueError(
            f"VCD ends at {window.last_fs / fs_per_ns:g} ns; benchmark expects "
            f"{float(expected_last_fs / fs_per_ns):g} ns"
        )
    if window.duration_fs != expected_duration_fs:
        raise ValueError(
            f"VCD duration is {window.duration_fs / fs_per_ns:g} ns; benchmark expects "
            f"{float(expected_duration_fs / fs_per_ns):g} ns"
        )


def attention_energy(
    kind: str,
    power_w: dict[str, float],
    duration_ns: Fraction,
    transactions: int,
) -> dict[str, float] | None:
    if kind == "idle_warm_window":
        return None
    if kind != "warm_attention" or transactions < 1:
        raise ValueError("energy per attention requires an active warm-attention measurement")
    window_j = power_w["total"] * float(duration_ns) * 1e-9
    return {
        "window_j": window_j,
        "per_attention_nj": window_j * 1e9 / transactions,
    }


def tcl_quote(value: Path | str) -> str:
    text = str(value)
    if "}" in text or "\n" in text:
        raise ValueError(f"unsupported Tcl path/value: {text!r}")
    return "{" + text + "}"


def vcd_scope_parts(scope: str) -> list[str]:
    """Accept OpenSTA-style slash and VCD-style dot hierarchy spellings."""

    parts = [part for part in re.split(r"[./]", scope) if part]
    if not parts:
        raise ValueError("scope must contain at least one hierarchy component")
    return parts


def scope_vcd_signal_count(vcd: Path, scope: str) -> int:
    """Count VCD variables lexically nested beneath ``scope`` before OpenSTA runs."""

    scope_parts = vcd_scope_parts(scope)
    scopes: list[str] = []
    count = 0
    with vcd.open(encoding="ascii", errors="replace") as waveform:
        for raw_line in waveform:
            line = raw_line.strip()
            if line.startswith("$scope "):
                fields = line.split()
                if len(fields) >= 3:
                    scopes.append(fields[2])
            elif line.startswith("$upscope"):
                if scopes:
                    scopes.pop()
            elif line.startswith("$var "):
                if scopes[: len(scope_parts)] == scope_parts:
                    count += 1
            elif line.startswith("$enddefinitions"):
                break
    return count


def render_tcl(
    *,
    config: dict[str, Any],
    artifacts: dict[str, Path],
    vcd: Path,
    scope: str,
    include_power_report: bool,
) -> str:
    design = config["design_name"]
    clock = config["clock"]["port"]
    commands = [
        "# Generated by analysis/power/run_power.py. Do not edit.",
        "set_cmd_units -time ns -capacitance pF -current mA -voltage V -resistance kOhm -distance um",
        f"read_lef {tcl_quote(artifacts['tech_lef'])}",
        f"read_lef {tcl_quote(artifacts['cell_lef_ef'])}",
        f"read_lef {tcl_quote(artifacts['cell_lef_hd'])}",
        f"read_liberty {tcl_quote(artifacts['liberty'])}",
        f"read_verilog {tcl_quote(artifacts['netlist'])}",
        f"link_design {tcl_quote(design)}",
        f"read_sdc {tcl_quote(artifacts['sdc'])}",
        f"set_propagated_clock [get_clocks {tcl_quote(clock)}]",
        f"read_spef {tcl_quote(artifacts['spef'])}",
        f"read_vcd -scope {tcl_quote(scope)} {tcl_quote(vcd)}",
        "puts \"POWER_VCD_ANNOTATION_BEGIN\"",
        "report_activity_annotation -report_annotated",
        "puts \"POWER_VCD_ANNOTATION_END\"",
        "puts \"POWER_VCD_UNANNOTATED_BEGIN\"",
        "report_activity_annotation -report_unannotated",
        "puts \"POWER_VCD_UNANNOTATED_END\"",
    ]
    if include_power_report:
        commands.extend(
            [
                "puts \"POWER_REPORT_BEGIN\"",
                f"report_power -digits {POWER_REPORT_DIGITS}",
                "puts \"POWER_REPORT_END\"",
            ]
        )
    commands.extend(["exit", ""])
    return "\n".join(commands)


def section(log: str, begin: str, end: str) -> str:
    try:
        return log.split(begin, 1)[1].split(end, 1)[0].strip() + "\n"
    except IndexError as error:
        raise RuntimeError(f"OpenROAD did not emit expected section {begin}") from error


def parse_total_power(power_report: str) -> dict[str, float]:
    match = re.search(
        r"^Total\s+([0-9.eE+-]+)\s+([0-9.eE+-]+)\s+([0-9.eE+-]+)\s+([0-9.eE+-]+)",
        power_report,
        flags=re.MULTILINE,
    )
    if match is None:
        raise RuntimeError("could not parse the Total row from OpenROAD report_power")
    internal, switching, leakage, total = (float(value) for value in match.groups())
    return {
        "internal": internal,
        "switching": switching,
        "leakage": leakage,
        "total": total,
    }


def is_within(path: Path, directory: Path) -> bool:
    try:
        path.relative_to(directory)
        return True
    except ValueError:
        return False


def run_openroad(
    *,
    docker_bin: str,
    image: str,
    vcd: Path,
    tcl: Path,
) -> subprocess.CompletedProcess[str]:
    command = [
        docker_bin,
        "run",
        "--rm",
        "--network",
        "none",
        "--pull",
        "never",
        "-v",
        f"{REPO_ROOT}:{REPO_ROOT}:ro",
        "-w",
        str(REPO_ROOT),
    ]
    mounted_directories: set[Path] = set()
    for directory in (vcd.parent, tcl.parent):
        if not is_within(directory, REPO_ROOT) and directory not in mounted_directories:
            command.extend(["-v", f"{directory}:{directory}:ro"])
            mounted_directories.add(directory)
    command.extend([image, "openroad", "-exit", "-no_splash", str(tcl)])
    return subprocess.run(command, check=False, capture_output=True, text=True)


def main() -> int:
    args = parse_args()
    output_dir = args.output_dir.resolve()
    invalidate_output_artifacts(output_dir)
    config = read_config(args.config.resolve())
    measurement_config = config.get("measurement", {})
    vcd_value = args.vcd or measurement_config.get("vcd")
    scope = args.scope or measurement_config.get("scope")

    if vcd_value is None or scope is None:
        raise ValueError("--vcd and --scope are required; no vectorless fallback is allowed")
    if not args.validation_only and args.benchmark_result is None:
        raise ValueError("--benchmark-result is required for measured power")
    if not args.validation_only and (
        args.duration_ns is not None or args.transactions is not None
    ):
        raise ValueError(
            "--duration-ns and --transactions are forbidden for measured power; "
            "they are derived from --benchmark-result"
        )
    if args.benchmark_result is not None and (
        args.duration_ns is not None or args.transactions is not None
    ):
        raise ValueError(
            "manual duration/transactions cannot be combined with --benchmark-result"
        )

    vcd = Path(vcd_value).resolve()
    if not vcd.is_file():
        raise FileNotFoundError(f"VCD does not exist: {vcd}")
    if vcd.suffix.lower() != ".vcd":
        raise ValueError("VCD must use a .vcd extension; FST is not accepted by OpenSTA")

    vcd_window = read_vcd_window(vcd)
    benchmark = None
    if args.benchmark_result is not None:
        benchmark_path = args.benchmark_result.resolve()
        benchmark = benchmark_measurement(benchmark_path)
        configured_period = positive_fraction(config["clock"]["period_ns"], "clock.period_ns")
        if benchmark["clock_period_ns"] != configured_period:
            raise ValueError("benchmark clock does not match the configured power-analysis clock")
        verify_vcd_window(vcd_window, benchmark)
        kind = benchmark["kind"]
        duration_ns = benchmark["duration_ns"]
        transactions = benchmark["transactions"]
    else:
        if args.duration_ns is None or args.duration_ns <= 0:
            raise ValueError(
                "--duration-ns must be positive when validation-only has no benchmark result"
            )
        if args.transactions is None or args.transactions < 0:
            raise ValueError(
                "--transactions must be nonnegative when validation-only has no benchmark result"
            )
        kind = "validation_only"
        duration_ns = Fraction(str(args.duration_ns))
        transactions = args.transactions
        expected_duration_fs = duration_ns * 1_000_000
        if vcd_window.duration_fs != expected_duration_fs:
            raise ValueError(
                f"VCD duration is {vcd_window.duration_fs / 1_000_000:g} ns; "
                f"manual validation duration is {args.duration_ns:g} ns"
            )

    window_evidence = vcd_window_evidence(vcd_window)
    window_evidence["verified_against_benchmark"] = benchmark is not None

    artifacts = {name: resolve_repo_path(value) for name, value in config["artifacts"].items()}
    missing = [f"{name}={path}" for name, path in artifacts.items() if not path.is_file()]
    if missing:
        raise FileNotFoundError("missing hardened artifact(s): " + ", ".join(missing))

    requested_scope = scope
    opensta_scope = "/".join(vcd_scope_parts(scope))
    scope_signals = scope_vcd_signal_count(vcd, requested_scope)
    if scope_signals == 0:
        raise ValueError(f"no VCD signals exist under scope {scope!r}")

    tcl = output_dir / "power.tcl"
    tcl.write_text(
        render_tcl(
            config=config,
            artifacts=artifacts,
            vcd=vcd,
            scope=opensta_scope,
            include_power_report=not args.validation_only,
        ),
        encoding="ascii",
    )

    execution = config.get("execution", {})
    docker_bin = resolve_executable(execution.get("docker_bin", "docker"))
    result = run_openroad(
        docker_bin=docker_bin,
        image=execution.get("container_image", IMAGE_DEFAULT),
        vcd=vcd,
        tcl=tcl,
    )
    log = result.stdout + result.stderr
    (output_dir / "openroad.log").write_text(log, encoding="utf8")
    if result.returncode != 0:
        raise RuntimeError(f"OpenROAD failed; see {output_dir / 'openroad.log'}")

    annotated_report = section(log, "POWER_VCD_ANNOTATION_BEGIN", "POWER_VCD_ANNOTATION_END")
    unannotated_report = section(log, "POWER_VCD_UNANNOTATED_BEGIN", "POWER_VCD_UNANNOTATED_END")
    (output_dir / "activity_annotation.rpt").write_text(annotated_report, encoding="utf8")
    (output_dir / "activity_unannotated.rpt").write_text(unannotated_report, encoding="utf8")

    annotation_counts = re.findall(r"Annotated\s+(\d+)\s+pin activities\.", log)
    if not annotation_counts:
        raise RuntimeError("OpenSTA did not report its VCD annotation count")
    annotated_pin_count = int(annotation_counts[-1])
    unannotated_matches = re.findall(r"\bunannotated\s+(\d+)", annotated_report)
    unannotated_pin_count = int(unannotated_matches[-1]) if unannotated_matches else None
    annotated_pin_coverage_percent = None
    if unannotated_pin_count is not None:
        total_pin_count = annotated_pin_count + unannotated_pin_count
        if total_pin_count:
            annotated_pin_coverage_percent = 100.0 * annotated_pin_count / total_pin_count
    if annotated_pin_count == 0:
        rejected = {
            "status": "rejected",
            "reason": "OpenSTA annotated zero pin activities from the supplied VCD.",
            "vcd": str(vcd),
            "scope": opensta_scope,
            "requested_scope": requested_scope,
            "scope_signal_count": scope_signals,
            "unannotated_pin_count": unannotated_pin_count,
            "annotated_pin_coverage_percent": annotated_pin_coverage_percent,
            "annotation_report": str(output_dir / "activity_annotation.rpt"),
            "benchmark_result": str(benchmark["path"]) if benchmark is not None else None,
            "vcd_window": window_evidence,
        }
        (output_dir / "rejected.json").write_text(
            json.dumps(rejected, indent=2, sort_keys=True) + "\n", encoding="ascii"
        )
        raise RuntimeError(
            "OpenSTA annotated zero pin activities from the VCD; refusing vectorless power output"
        )

    power_w = None
    if not args.validation_only:
        power_report = section(log, "POWER_REPORT_BEGIN", "POWER_REPORT_END")
        (output_dir / "power.rpt").write_text(power_report, encoding="utf8")
        power_w = parse_total_power(power_report)
    result_json: dict[str, Any] = {
        "schema_version": "1.1",
        "status": "validation_only" if args.validation_only else "measured",
        "measurement": {
            "kind": kind,
            "benchmark": benchmark["benchmark"] if benchmark is not None else None,
            "benchmark_result": str(benchmark["path"]) if benchmark is not None else None,
            "vcd": str(vcd),
            "scope": opensta_scope,
            "requested_scope": requested_scope,
            "duration_ns": fraction_to_number(duration_ns),
            "transactions": transactions,
            "vcd_window": window_evidence,
        },
        "physical_context": {
            "corner": config["corner"],
            "clock_period_ns": config["clock"]["period_ns"],
            "artifacts": {name: str(path) for name, path in artifacts.items()},
            "tool": {
                "librelane_version": "3.0.3",
                "container_image": execution.get("container_image", IMAGE_DEFAULT),
                "openroad_command": "openroad -exit -no_splash power.tcl",
                "report_power_digits": POWER_REPORT_DIGITS,
            },
        },
        "annotation_evidence": {
            "source": "VCD",
            "report": str(output_dir / "activity_annotation.rpt"),
            "vcd_reported": True,
            "annotated_pin_count": annotated_pin_count,
            "unannotated_pin_count": unannotated_pin_count,
            "annotated_pin_coverage_percent": annotated_pin_coverage_percent,
            "scope_signal_count": scope_signals,
        },
        "power_w": power_w,
        "energy": None,
    }
    if not args.validation_only:
        assert power_w is not None
        result_json["energy"] = attention_energy(
            kind, power_w, duration_ns, transactions
        )

    output = output_dir / "result.json"
    output.write_text(json.dumps(result_json, indent=2, sort_keys=True) + "\n", encoding="ascii")
    print(output)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, PermissionError, RuntimeError, ValueError) as error:
        print(f"power analysis error: {error}", file=sys.stderr)
        raise SystemExit(2)
