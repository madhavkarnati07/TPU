#!/usr/bin/env python3
"""Build the concise Milestone 3 architecture analysis from pareto.json."""

from __future__ import annotations

import argparse
import html
import json
import math
from pathlib import Path
from string import Template
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = ROOT / "analysis/pareto/pareto.json"
DEFAULT_HTML = ROOT / "analysis/pareto/architecture-analysis.html"
DEFAULT_SUMMARY = ROOT / "analysis/pareto/SUMMARY.md"
VARIANTS = ("mac1", "mac2", "mac4")
PHASES = ("project", "score", "max", "clip", "weight", "norm")
PHASE_LABELS = {
    "project": "Q/K/V projection",
    "score": "QK^T scores",
    "max": "Row maximum",
    "clip": "Clip + denominator",
    "weight": "Weighted V",
    "norm": "Normalize",
}


class AnalysisError(ValueError):
    """Raised when the Pareto evidence cannot support this analysis."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AnalysisError(message)


def finite(value: Any, name: str) -> float:
    require(not isinstance(value, bool), f"{name} must be numeric")
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise AnalysisError(f"{name} must be numeric") from error
    require(math.isfinite(result), f"{name} must be finite")
    return result


def load_report(path: Path) -> dict[str, Any]:
    report = json.loads(path.read_text(encoding="utf-8"))
    require(report.get("schema_version") == "1.0", "unsupported Pareto schema")
    points = report.get("points")
    require(isinstance(points, list), "Pareto report lacks points")
    by_name = {point.get("variant"): point for point in points}
    require(tuple(by_name) == VARIANTS, "expected mac1, mac2, and mac4 in order")
    report["points"] = [by_name[name] for name in VARIANTS]
    return report


def validate_workload(workload: dict[str, Any]) -> None:
    require(workload.get("identity") == "warm_attention", "analysis requires warm attention")
    transactions = workload.get("transactions")
    require(isinstance(transactions, list) and len(transactions) == 16, "analysis requires 16 fixed transactions")
    for index, transaction in enumerate(transactions):
        x = transaction.get("x")
        require(isinstance(x, list) and len(x) == 4, f"transaction {index} requires four tokens")
        for token in x:
            require(isinstance(token, list) and len(token) == 2, f"transaction {index} requires two-dimensional tokens")
            require(
                all(isinstance(value, int) and not isinstance(value, bool) and -8 <= value <= 7 for value in token),
                f"transaction {index} input is not signed int4",
            )
        expected = transaction.get("expected_result_bytes")
        observed = transaction.get("observed_result_bytes")
        require(expected == observed, f"transaction {index} does not match the golden output")


def derive(report: dict[str, Any]) -> dict[str, Any]:
    points = report["points"]
    require(len(points) == 3, "analysis requires exactly three MAC variants")
    experiment = report.get("experiment")
    require(isinstance(experiment, dict), "Pareto report lacks experiment metadata")
    clock_hz = finite(experiment.get("clock_hz"), "experiment clock")
    require(math.isclose(clock_hz, 10_000_000), "analysis requires the fixed 10 MHz clock")
    workload = experiment.get("workload")
    require(isinstance(workload, dict), "experiment lacks workload identity")
    require(workload.get("transaction_count") == 16, "analysis requires 16 fixed transactions")
    validate_workload(workload)
    require(
        report.get("non_dominated_variants") == list(VARIANTS),
        "all three variants must be non-dominated",
    )
    base = points[0]
    base_interval = finite(base["steady_state_initiation_interval_cycles"], "mac1 interval")
    base_energy = finite(base["energy_per_attention_nj"], "mac1 energy")
    base_power = finite(base["active_total_power_w"], "mac1 power")
    base_area = finite(base["standard_cell_area_um2"], "mac1 area")

    phase_sums = []
    rows = []
    for point, expected_name, expected_lanes in zip(points, VARIANTS, (1, 2, 4)):
        require(point["variant"] == expected_name, f"expected {expected_name}")
        require(point["mac_lanes"] == expected_lanes, f"{expected_name} lane count mismatch")
        require(point["useful_mac_operations"] == 112, f"{expected_name} useful MAC count mismatch")
        require(point.get("workload") == workload, f"{expected_name} workload mismatch")
        require(point.get("non_dominated") is True, f"{expected_name} is not non-dominated")
        require(point.get("dominated_by") == [], f"{expected_name} has a Pareto dominator")
        for status in ("timing_status", "routing_drc_status", "magic_drc_status", "lvs_status"):
            require(point.get(status) == "pass", f"{expected_name} {status} did not pass")
        physical = point.get("physical_experiment", {}).get("resolved_config")
        require(isinstance(physical, dict), f"{expected_name} lacks physical configuration")
        require(physical.get("tile_allocation") == "2x2", f"{expected_name} is not a 2x2 tile")
        require(
            math.isclose(finite(physical.get("clock_period_ns"), f"{expected_name} clock period"), 1e9 / clock_hz),
            f"{expected_name} clock period does not match the experiment clock",
        )
        phases = point["phase_cycles"]
        require(all(key in phases for key in PHASES), f"{expected_name} phase data incomplete")
        phase_sum = sum(finite(phases[key], f"{expected_name} {key}") for key in PHASES)
        compute = finite(point["compute_cycles"]["mean"], f"{expected_name} compute cycles")
        require(math.isclose(phase_sum, compute), f"{expected_name} phase sum mismatch")
        phase_sums.append(phase_sum)

        interval = finite(point["steady_state_initiation_interval_cycles"], f"{expected_name} interval")
        energy = finite(point["energy_per_attention_nj"], f"{expected_name} energy")
        power_w = finite(point["active_total_power_w"], f"{expected_name} power")
        area = finite(point["standard_cell_area_um2"], f"{expected_name} area")
        throughput = finite(point["throughput_attentions_per_second"], f"{expected_name} throughput")
        require(
            math.isclose(throughput, clock_hz / interval, rel_tol=1e-12),
            f"{expected_name} throughput does not match clock and interval",
        )
        require(
            math.isclose(energy, power_w * interval / clock_hz * 1e9, rel_tol=1e-9),
            f"{expected_name} energy does not match power and interval",
        )
        rows.append(
            {
                **point,
                "interval": interval,
                "energy": energy,
                "power_mw": power_w * 1_000,
                "area": area,
                "throughput": throughput,
                "speedup": base_interval / interval,
                "runtime_reduction_pct": (1 - interval / base_interval) * 100,
                "energy_change_pct": (energy / base_energy - 1) * 100,
                "power_change_pct": (power_w / base_power - 1) * 100,
                "area_change_pct": (area / base_area - 1) * 100,
                "utilization_pct": finite(point["lane_utilization"], f"{expected_name} utilization") * 100,
            }
        )

    protocol_cycles = rows[0]["interval"] - phase_sums[0]
    require(all(math.isclose(row["interval"] - phase_sum, protocol_cycles) for row, phase_sum in zip(rows, phase_sums)), "protocol overhead differs by variant")
    serial_compute = sum(finite(base["phase_cycles"][key], f"mac1 {key}") for key in ("max", "clip", "norm"))
    scalar_mac_operations = sum(finite(base["phase_cycles"][key], f"mac1 {key}") for key in ("project", "score", "weight"))
    require(math.isclose(scalar_mac_operations, 112), "mac1 MAC phases must equal useful scalar operations")
    serial_floor = serial_compute + protocol_cycles
    ideal_intervals = {lanes: serial_floor + scalar_mac_operations / lanes for lanes in (1, 2, 4, 8)}
    ideal_two = ideal_intervals[2]
    actual_two = rows[1]["interval"]
    score_parallel_gap = actual_two - ideal_two
    require(math.isclose(score_parallel_gap, 16), "unexpected 2-MAC score scheduling gap")

    return {
        "rows": rows,
        "clock_hz": clock_hz,
        "clock_mhz": clock_hz / 1_000_000,
        "tile_allocation": "2x2",
        "scalar_mac_operations": scalar_mac_operations,
        "serial_compute_cycles": serial_compute,
        "protocol_cycles": protocol_cycles,
        "serial_floor_cycles": serial_floor,
        "ideal_intervals": ideal_intervals,
        "maximum_speedup": base_interval / serial_floor,
        "score_parallel_interval": ideal_two,
        "score_parallel_throughput": clock_hz / ideal_two,
        "score_parallel_gap_cycles": score_parallel_gap,
    }


def cycle_rows(rows: list[dict[str, Any]]) -> str:
    maximum = max(row["interval"] for row in rows)
    result = []
    for row in rows:
        segments = []
        for phase in PHASES:
            cycles = row["phase_cycles"][phase]
            segments.append(
                f'<span class="phase phase-{phase}" style="width:{cycles / maximum * 100:.4f}%" '
                f'title="{html.escape(PHASE_LABELS[phase])}: {cycles} cycles"></span>'
            )
        protocol = row["interval"] - sum(row["phase_cycles"].values())
        segments.append(
            f'<span class="phase phase-protocol" style="width:{protocol / maximum * 100:.4f}%" '
            f'title="Host protocol: {protocol:g} cycles"></span>'
        )
        aria = "; ".join(
            [f"{PHASE_LABELS[phase]} {row['phase_cycles'][phase]} cycles" for phase in PHASES]
            + [f"host protocol {protocol:g} cycles", f"total interval {row['interval']:.0f} cycles"]
        )
        result.append(
            f'<div class="cycle-row" role="img" aria-label="{row["mac_lanes"]} MAC schedule: {html.escape(aria)}">'
            f'<div class="row-label">{row["mac_lanes"]} MAC</div>'
            f'<div class="cycle-track">{"".join(segments)}</div>'
            f'<div class="row-value">{row["interval"]:.0f} cycles</div>'
            '</div>'
        )
    return "\n".join(result)


def metric_rows(rows: list[dict[str, Any]], key: str, maximum: float, unit: str) -> str:
    palette = ("tone-1", "tone-2", "tone-3")
    result = []
    for row, tone in zip(rows, palette):
        value = row[key]
        result.append(
            '<div class="metric-row">'
            f'<span>{row["mac_lanes"]} MAC</span>'
            f'<span class="metric-track"><i class="{tone}" style="width:{value / maximum * 100:.3f}%"></i></span>'
            f'<strong>{value:.3f} {unit}</strong>'
            '</div>'
        )
    return "\n".join(result)


def pareto_svg(rows: list[dict[str, Any]]) -> str:
    width, height = 680, 365
    left, right, top, bottom = 90, 28, 28, 62
    x_min, x_max = 45_000, 58_000
    y_min, y_max = 60_000, 140_000

    def x(value: float) -> float:
        return left + (value - x_min) / (x_max - x_min) * (width - left - right)

    def y(value: float) -> float:
        return top + (y_max - value) / (y_max - y_min) * (height - top - bottom)

    elements = [
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Throughput versus standard-cell area for the three measured variants">',
        f'<rect class="chart-frame" x="{left}" y="{top}" width="{width-left-right}" height="{height-top-bottom}"/>',
    ]
    for tick in (60_000, 80_000, 100_000, 120_000, 140_000):
        ty = y(tick)
        elements.append(f'<line class="grid" x1="{left}" x2="{width-right}" y1="{ty:.1f}" y2="{ty:.1f}"/>')
        elements.append(f'<text class="tick" x="{left-10}" y="{ty+4:.1f}" text-anchor="end">{tick/1000:.0f}k</text>')
    for tick in (46_000, 50_000, 54_000, 58_000):
        tx = x(tick)
        elements.append(f'<line class="grid" x1="{tx:.1f}" x2="{tx:.1f}" y1="{top}" y2="{height-bottom}"/>')
        elements.append(f'<text class="tick" x="{tx:.1f}" y="{height-bottom+22}" text-anchor="middle">{tick/1000:.0f}k</text>')
    for index, row in enumerate(rows):
        cx, cy = x(row["area"]), y(row["throughput"])
        label_anchor = "end" if index == 2 else "start"
        label_x = cx - 10 if index == 2 else cx + 10
        elements.append(f'<circle class="point point-{index+1}" cx="{cx:.1f}" cy="{cy:.1f}" r="8"/>')
        elements.append(
            f'<text class="point-label" x="{label_x:.1f}" y="{cy-12:.1f}" text-anchor="{label_anchor}">'
            f'{row["mac_lanes"]} MAC &middot; {row["energy"]:.2f} nJ</text>'
        )
    elements.extend(
        [
            f'<text class="axis-title" x="{(left+width-right)/2:.1f}" y="{height-8}" text-anchor="middle">Standard-cell area (um^2)</text>',
            f'<text class="axis-title" transform="translate(17 {(top+height-bottom)/2:.1f}) rotate(-90)" text-anchor="middle">Throughput (attention/s)</text>',
            '</svg>',
        ]
    )
    return "".join(elements)


def scaling_svg(data: dict[str, Any]) -> str:
    width, height = 680, 365
    left, right, top, bottom = 90, 28, 28, 62
    lanes = (1, 2, 4, 8)
    x_positions = {lane: left + index * (width-left-right) / 3 for index, lane in enumerate(lanes)}
    y_min, y_max = 40, 170

    def y(value: float) -> float:
        return top + (y_max - value) / (y_max-y_min) * (height-top-bottom)

    rows = data["rows"]
    actual = {row["mac_lanes"]: row["interval"] for row in rows}
    elements = [
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Actual and ideal initiation interval as MAC lanes increase">',
        f'<rect class="chart-frame" x="{left}" y="{top}" width="{width-left-right}" height="{height-top-bottom}"/>',
    ]
    for tick in (40, 80, 120, 160):
        ty = y(tick)
        elements.append(f'<line class="grid" x1="{left}" x2="{width-right}" y1="{ty:.1f}" y2="{ty:.1f}"/>')
        elements.append(f'<text class="tick" x="{left-10}" y="{ty+4:.1f}" text-anchor="end">{tick}</text>')
    for lane in lanes:
        elements.append(f'<text class="tick" x="{x_positions[lane]:.1f}" y="{height-bottom+22}" text-anchor="middle">{lane}</text>')
    ideal_points = " ".join(f'{x_positions[lane]:.1f},{y(data["ideal_intervals"][lane]):.1f}' for lane in lanes)
    actual_points = " ".join(f'{x_positions[lane]:.1f},{y(actual[lane]):.1f}' for lane in (1, 2, 4))
    elements.append(f'<polyline class="ideal-line" points="{ideal_points}"/>')
    elements.append(f'<polyline class="actual-line" points="{actual_points}"/>')
    for lane in lanes:
        elements.append(f'<circle class="ideal-point" cx="{x_positions[lane]:.1f}" cy="{y(data["ideal_intervals"][lane]):.1f}" r="5"/>')
    for lane in (1, 2, 4):
        elements.append(f'<circle class="actual-point" cx="{x_positions[lane]:.1f}" cy="{y(actual[lane]):.1f}" r="7"/>')
    two_x = x_positions[2]
    elements.append(f'<line class="gap-line" x1="{two_x:.1f}" x2="{two_x:.1f}" y1="{y(actual[2]):.1f}" y2="{y(data["ideal_intervals"][2]):.1f}"/>')
    elements.append(
        f'<text class="point-label" x="{two_x+10:.1f}" '
        f'y="{(y(actual[2])+y(data["ideal_intervals"][2]))/2:.1f}">'
        f'{data["score_parallel_gap_cycles"]:.0f}-cycle schedule gap</text>'
    )
    elements.extend(
        [
            f'<line class="floor-line" x1="{left}" x2="{width-right}" y1="{y(data["serial_floor_cycles"]):.1f}" y2="{y(data["serial_floor_cycles"]):.1f}"/>',
            f'<text class="floor-label" x="{width-right-4}" '
            f'y="{y(data["serial_floor_cycles"])-7:.1f}" text-anchor="end">'
            f'{data["serial_floor_cycles"]:.0f}-cycle serial floor</text>',
            f'<text class="axis-title" x="{(left+width-right)/2:.1f}" y="{height-8}" text-anchor="middle">MAC lanes</text>',
            f'<text class="axis-title" transform="translate(17 {(top+height-bottom)/2:.1f}) rotate(-90)" text-anchor="middle">Initiation interval (cycles)</text>',
            '</svg>',
        ]
    )
    return "".join(elements)


def render_html(data: dict[str, Any]) -> str:
    rows = data["rows"]
    mac1, mac2, mac4 = rows
    legend = "".join(
        f'<span><i class="phase-{phase}"></i>{html.escape(PHASE_LABELS[phase])}</span>'
        for phase in PHASES
    ) + '<span><i class="phase-protocol"></i>Host protocol</span>'
    table_rows = "\n".join(
        '<tr>'
        f'<th scope="row">{row["mac_lanes"]} MAC</th>'
        f'<td>{row["interval"]:.0f}</td>'
        f'<td>{row["throughput"]:,.0f}</td>'
        f'<td>{row["power_mw"]:.3f}</td>'
        f'<td>{row["energy"]:.3f}</td>'
        f'<td>{row["area"]:,.1f}</td>'
        f'<td>{row["utilization_pct"]:.1f}%</td>'
        '</tr>'
        for row in rows
    )
    template = Template(r'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Toy Attention TPU &middot; Fixed-Workload MAC Scaling</title>
  <style>
    :root {
      color-scheme: light;
      --paper: #f4f5f2;
      --surface: #ffffff;
      --ink: #172027;
      --muted: #5c666e;
      --line: #cbd1d3;
      --teal: #087f73;
      --blue: #3d6f9e;
      --amber: #bd7b1d;
      --rust: #ad523e;
      --plum: #76558f;
      --gray: #78828a;
    }
    * { box-sizing: border-box; }
    body { margin: 0; background: var(--paper); color: var(--ink); font: 15px/1.55 Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    main { max-width: 1120px; margin: 0 auto; padding: 28px 34px 64px; }
    header { border-bottom: 1px solid var(--line); padding-bottom: 24px; }
    .project { color: var(--teal); font-size: 13px; font-weight: 750; text-transform: uppercase; }
    h1 { max-width: 800px; margin: 8px 0 8px; font-size: 36px; line-height: 1.13; letter-spacing: 0; }
    .dek { max-width: 790px; margin: 0; color: var(--muted); font-size: 17px; }
    .facts { display: grid; grid-template-columns: repeat(4, 1fr); margin-top: 24px; border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); }
    .fact { padding: 15px 18px 14px 0; }
    .fact + .fact { padding-left: 18px; border-left: 1px solid var(--line); }
    .fact strong { display: block; font-size: 22px; line-height: 1.1; }
    .fact span { display: block; margin-top: 5px; color: var(--muted); font-size: 12px; }
    section { padding: 30px 0; border-bottom: 1px solid var(--line); }
    h2 { margin: 0 0 6px; font-size: 22px; letter-spacing: 0; }
    h3 { margin: 0 0 15px; font-size: 16px; letter-spacing: 0; }
    .section-lead { max-width: 800px; margin: 0 0 22px; color: var(--muted); }
    .chart-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 30px; }
    .chart-grid > * { min-width: 0; }
    figure { min-width: 0; margin: 0; }
    figcaption { margin-top: 10px; color: var(--muted); font-size: 13px; }
    .cycle-row { display: grid; grid-template-columns: 56px minmax(0, 1fr) 76px; gap: 10px; align-items: center; margin: 13px 0; }
    .row-label, .row-value { font-size: 13px; font-weight: 700; }
    .row-value { text-align: right; }
    .cycle-track { display: flex; height: 24px; background: #e7e9e6; overflow: hidden; }
    .phase { display: block; min-width: 1px; }
    .phase-project { background: var(--teal); }
    .phase-score { background: var(--blue); }
    .phase-max { background: var(--amber); }
    .phase-clip { background: var(--rust); }
    .phase-weight { background: var(--plum); }
    .phase-norm { background: var(--gray); }
    .phase-protocol { background: #29333a; }
    .legend { display: flex; flex-wrap: wrap; gap: 8px 15px; margin-top: 16px; color: var(--muted); font-size: 12px; }
    .legend span { display: inline-flex; align-items: center; gap: 6px; }
    .legend i { width: 10px; height: 10px; display: inline-block; }
    .metric-pair { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }
    .metric-row { display: grid; grid-template-columns: 48px minmax(80px, 1fr) 78px; gap: 8px; align-items: center; margin: 11px 0; font-size: 12px; }
    .metric-row strong { text-align: right; font-size: 12px; }
    .metric-track { height: 15px; background: #e5e8e7; }
    .metric-track i { display: block; height: 100%; }
    .tone-1 { background: var(--amber); }
    .tone-2 { background: var(--blue); }
    .tone-3 { background: var(--teal); }
    svg { width: 100%; height: auto; display: block; }
    .chart-frame { fill: var(--surface); stroke: var(--line); }
    .grid { stroke: #dfe3e4; stroke-width: 1; }
    .tick, .axis-title, .point-label, .floor-label { fill: var(--ink); font-size: 12px; }
    .axis-title { font-weight: 700; }
    .point-label, .floor-label { font-weight: 700; }
    .point-1 { fill: var(--amber); }
    .point-2 { fill: var(--blue); }
    .point-3 { fill: var(--teal); }
    .ideal-line { fill: none; stroke: var(--gray); stroke-width: 2; stroke-dasharray: 6 5; }
    .actual-line { fill: none; stroke: var(--teal); stroke-width: 3; }
    .ideal-point { fill: var(--surface); stroke: var(--gray); stroke-width: 2; }
    .actual-point { fill: var(--teal); stroke: var(--surface); stroke-width: 2; }
    .gap-line { stroke: var(--rust); stroke-width: 2; }
    .floor-line { stroke: var(--amber); stroke-width: 2; stroke-dasharray: 3 4; }
    table { width: 100%; border-collapse: collapse; margin-top: 18px; font-variant-numeric: tabular-nums; }
    th, td { padding: 10px 9px; border-bottom: 1px solid var(--line); text-align: right; white-space: nowrap; }
    th:first-child, td:first-child { text-align: left; }
    thead th { color: var(--muted); font-size: 12px; font-weight: 700; }
    tbody th { font-size: 13px; }
    .findings { display: grid; grid-template-columns: 1fr 1fr; gap: 24px 34px; }
    .finding { border-top: 3px solid var(--teal); padding-top: 12px; }
    .finding:nth-child(2) { border-color: var(--amber); }
    .finding:nth-child(3) { border-color: var(--blue); }
    .finding:nth-child(4) { border-color: var(--rust); }
    .finding p { margin: 5px 0 0; color: var(--muted); }
    .evidence { display: grid; grid-template-columns: repeat(3, 1fr); gap: 0; border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); }
    .evidence div { padding: 18px 20px 18px 0; }
    .evidence div + div { padding-left: 20px; border-left: 1px solid var(--line); }
    .evidence p { margin: 5px 0 0; color: var(--muted); font-size: 13px; }
    .next { border-left: 4px solid var(--rust); padding-left: 18px; max-width: 850px; }
    .next p { margin: 6px 0 0; }
    footer { padding-top: 22px; color: var(--muted); font-size: 12px; }
    code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
    @media (max-width: 760px) {
      main { padding: 22px 18px 48px; }
      h1 { font-size: 29px; }
      .facts { grid-template-columns: 1fr 1fr; }
      .fact:nth-child(3) { border-left: 0; }
      .fact:nth-child(n+3) { border-top: 1px solid var(--line); }
      .chart-grid, .findings, .metric-pair { grid-template-columns: 1fr; }
      .evidence { grid-template-columns: 1fr; }
      .evidence div + div { padding-left: 0; border-left: 0; border-top: 1px solid var(--line); }
      .table-wrap { overflow-x: auto; }
      .cycle-row { grid-template-columns: 52px minmax(0, 1fr) 70px; gap: 7px; }
      svg .tick, svg .axis-title, svg .point-label, svg .floor-label { font-size: 22px; }
    }
  </style>
</head>
<body>
<main>
  <header>
    <div class="project">Toy Attention TPU &middot; Milestone 3</div>
    <h1>Fixed-workload MAC scaling analysis</h1>
    <p class="dek">One, two, and four MAC lanes execute the same signed-int4, four-token attention transaction at $clock_mhz MHz inside the same $tile TinyTapeout tile.</p>
    <div class="facts">
      <div class="fact"><strong>$speedup&times;</strong><span>4-MAC throughput speedup</span></div>
      <div class="fact"><strong>$energy_reduction%</strong><span>lower total energy</span></div>
      <div class="fact"><strong>+$area_increase%</strong><span>standard-cell area</span></div>
      <div class="fact"><strong>$serial_floor cycles</strong><span>current serial floor</span></div>
    </div>
  </header>

  <section>
    <h2>Where the cycles go</h2>
    <p class="section-lead">Four lanes quarter the projection, score, and weighted-V work. Row maximum, clipping, normalization, and eleven protocol cycles do not shrink.</p>
    <figure>
      $cycle_rows
      <div class="legend">$legend</div>
      <figcaption>The $cycle_saving-cycle saving from 1 to 4 MACs is entirely explained by parallel MAC phases: $parallel_phase_changes.</figcaption>
    </figure>
  </section>

  <section class="chart-grid">
    <figure>
      <h2>Power rises; energy falls</h2>
      <div class="metric-pair">
        <div><h3>Active power</h3>$power_rows</div>
        <div><h3>Energy per attention</h3>$energy_rows</div>
      </div>
      <figcaption>The 4-MAC design draws $power_increase% more active power, but its steady-state interval is $runtime_reduction% shorter, reducing energy by $energy_reduction%.</figcaption>
    </figure>
    <figure>
      <h2>The area tradeoff</h2>
      $pareto_svg
      <figcaption>All three points remain non-dominated when area, throughput, and energy are considered together.</figcaption>
    </figure>
  </section>

  <section class="chart-grid">
    <figure>
      <h2>Measured scaling versus the bound</h2>
      $scaling_svg
      <figcaption>The ideal line is $serial_floor + $scalar_mac_operations/L cycles. The current 2-MAC schedule is $score_parallel_gap cycles above it because QK<sup>T</sup> remains single-lane.</figcaption>
    </figure>
    <div>
      <h2>Implementation results</h2>
      <p class="section-lead">Every point performs 112 useful scalar MAC operations and matches the same 16 Python golden cases in RTL and powered gate simulation.</p>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Variant</th><th>Interval</th><th>Throughput/s</th><th>Power mW</th><th>Energy nJ</th><th>Area um^2</th><th>MAC use</th></tr></thead>
          <tbody>$table_rows</tbody>
        </table>
      </div>
    </div>
  </section>

  <section>
    <h2>What we learned</h2>
    <div class="findings">
      <div class="finding"><strong>Four MACs win on speed and energy.</strong><p>They deliver $speedup&times; throughput and $energy_reduction% lower energy for $area_increase% more cell area than one MAC.</p></div>
      <div class="finding"><strong>The smallest design is not the lowest-energy design.</strong><p>Fixed clock and controller activity is paid for 159 cycles with one MAC and only 75 cycles with four.</p></div>
      <div class="finding"><strong>Utilization falls as lane count rises.</strong><p>Derived MAC utilization drops from $util1% to $util4% because the serial attention phases occupy a larger fraction of the shorter schedule.</p></div>
      <div class="finding"><strong>Four MACs are enough for this problem shape.</strong><p>Four tokens expose four independent QK<sup>T</sup> scores. More lanes require parallel query rows or a larger workload.</p></div>
    </div>
  </section>

  <section>
    <h2>Evidence boundary</h2>
    <div class="evidence">
      <div><strong>Measured</strong><p>Cycles, outputs, activity, tool-reported post-route power estimate, cell area, timing, DRC, and LVS for the three implemented variants.</p></div>
      <div><strong>Derived</strong><p>Speedup, energy reduction, utilization, the $serial_floor-cycle serial floor, and the Amdahl scaling curve.</p></div>
      <div><strong>Hypothesis</strong><p>A score-parallel 2-MAC schedule could reach about $score_parallel_interval cycles and $score_parallel_throughput attention/s. Power and area are not predicted.</p></div>
    </div>
  </section>

  <section>
    <div class="next">
      <h2>Next controlled experiment</h2>
      <p>Keep the workload, arithmetic, memory, MAC count, and clock fixed. Change only the 2-MAC QK<sup>T</sup> scheduler so two key scores run together. This tests whether scheduling, rather than additional arithmetic, can recover the $score_parallel_gap-cycle gap.</p>
    </div>
  </section>

  <footer>Power is an activity-aware post-route OpenSTA estimate from the measured gate-level VCD, not a silicon measurement. Maximum-slew warnings remain; the 2- and 4-MAC layouts also retain maximum-capacitance warnings. Official TinyTapeout submission checks remain required.</footer>
</main>
</body>
</html>
''')
    return template.substitute(
        speedup=f"{mac4['speedup']:.2f}",
        energy_reduction=f"{-mac4['energy_change_pct']:.1f}",
        area_increase=f"{mac4['area_change_pct']:.1f}",
        serial_floor=f"{data['serial_floor_cycles']:.0f}",
        scalar_mac_operations=f"{data['scalar_mac_operations']:.0f}",
        cycle_saving=f"{mac1['interval'] - mac4['interval']:.0f}",
        parallel_phase_changes=", ".join(
            f"{mac1['phase_cycles'][phase]}&rarr;{mac4['phase_cycles'][phase]}"
            for phase in ("project", "score", "weight")
        ),
        clock_mhz=f"{data['clock_mhz']:.0f}",
        tile=data["tile_allocation"],
        cycle_rows=cycle_rows(rows),
        legend=legend,
        power_rows=metric_rows(rows, "power_mw", max(row["power_mw"] for row in rows), "mW"),
        energy_rows=metric_rows(rows, "energy", max(row["energy"] for row in rows), "nJ"),
        power_increase=f"{mac4['power_change_pct']:.1f}",
        runtime_reduction=f"{mac4['runtime_reduction_pct']:.1f}",
        pareto_svg=pareto_svg(rows),
        scaling_svg=scaling_svg(data),
        table_rows=table_rows,
        util1=f"{mac1['utilization_pct']:.1f}",
        util4=f"{mac4['utilization_pct']:.1f}",
        score_parallel_interval=f"{data['score_parallel_interval']:.0f}",
        score_parallel_throughput=f"{data['score_parallel_throughput']:,.0f}",
        score_parallel_gap=f"{data['score_parallel_gap_cycles']:.0f}",
    )


def render_summary(data: dict[str, Any]) -> str:
    rows = data["rows"]
    mac1, mac2, mac4 = rows
    table = "\n".join(
        f'| {row["mac_lanes"]} | {row["interval"]:.0f} | {row["throughput"]:,.0f} | '
        f'{row["power_mw"]:.3f} | {row["energy"]:.3f} | {row["area"]:,.1f} | '
        f'{row["utilization_pct"]:.1f}% |'
        for row in rows
    )
    return f"""# Fixed-Workload MAC Scaling Summary

## Question

For the fixed four-token, two-dimensional signed-int4 attention workload, how do one, two, and four MAC lanes trade standard-cell area against throughput and total active energy?

## Implementation Results

| MACs | Interval cycles | Attention/s | Active power mW | Energy nJ | Cell area um^2 | MAC utilization |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
{table}

All variants execute the same 112 useful scalar MAC operations, match all 16 Python golden workloads in RTL and powered gate simulation, fit the same {data['tile_allocation']} tile, and pass {data['clock_mhz']:.0f} MHz setup/hold, route DRC, Magic DRC, and LVS.

## Conclusions

- Four MACs provide {mac4['speedup']:.2f}x the 1-MAC throughput and use {-mac4['energy_change_pct']:.1f}% less total energy for {mac4['area_change_pct']:.1f}% more standard-cell area.
- Energy falls despite {mac4['power_change_pct']:.1f}% higher active power because the steady-state transaction interval falls from {mac1['interval']:.0f} to {mac4['interval']:.0f} cycles.
- The workload contains {data['scalar_mac_operations']:.0f} scalar MAC operations, taking {data['scalar_mac_operations']:.0f}/L cycles under ideal distribution across L lanes. The schedule also has a {data['serial_floor_cycles']:.0f}-cycle floor: {data['serial_compute_cycles']:.0f} serial attention cycles plus {data['protocol_cycles']:.0f} protocol cycles.
- MAC utilization falls from {mac1['utilization_pct']:.1f}% to {mac4['utilization_pct']:.1f}% because MAX, clipping, normalization, and protocol work do not use the additional lanes.
- All three designs are Pareto-optimal when area, throughput, and energy are considered together. Four MACs win on speed and energy; one MAC remains smallest.

## Next Experiment

The current 2-MAC implementation still computes QK^T scores through one lane. A score-parallel scheduler would reduce its analytical interval from {mac2['interval']:.0f} to {data['score_parallel_interval']:.0f} cycles and raise theoretical throughput from {mac2['throughput']:,.0f} to {data['score_parallel_throughput']:,.0f} attention/s. This is a hypothesis, not a measured design point; its power, energy, area, and physical feasibility remain unknown.

## Evidence Boundary

- **Measured:** functional outputs, cycles, VCD activity, tool-reported post-route OpenSTA power estimate, standard-cell area, timing, DRC, and LVS.
- **Derived:** normalized changes, utilization, the serial floor, and Amdahl scaling.
- **Not established:** silicon power, shuttle acceptance, or the physical result of the proposed score-parallel scheduler.

The layouts retain maximum-slew warnings, and the 2- and 4-MAC variants retain maximum-capacitance warnings. Official TinyTapeout checks remain required for the selected submission candidate.
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--html", type=Path, default=DEFAULT_HTML)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    args = parser.parse_args()
    data = derive(load_report(args.input))
    args.html.parent.mkdir(parents=True, exist_ok=True)
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.html.write_text(render_html(data), encoding="utf-8")
    args.summary.write_text(render_summary(data), encoding="utf-8")
    print(args.html)
    print(args.summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
