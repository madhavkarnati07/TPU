"""Cocotb warm-workload benchmark for a fixed attention MAC variant."""

from __future__ import annotations

import json
import os
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, ReadOnly, RisingEdge
from cocotb.utils import get_sim_time

from workload import WARM_INPUTS, golden_case, packed_weights


CLOCK_PERIOD_NS = 100
CLOCK_HZ = 10_000_000
READY_RX = 4
VALID_TX = 5
DONE = 7

CMD_LOAD_X = 0x10
CMD_LOAD_WQ = 0x11
CMD_LOAD_WK = 0x12
CMD_LOAD_WV = 0x13
CMD_RUN_ATTENTION = 0x20
CMD_READ_RESULT = 0x30

STATE_NAMES = {
    2: "project",
    3: "score",
    4: "max",
    5: "clip",
    6: "weight",
    7: "norm",
}
MAC_LANES = int(os.environ.get("MAC_LANES", "2"))
VARIANT = os.environ.get("VARIANT", "baseline")
EXPECTED_PHASE_CYCLES = {
    1: {"project": 48, "score": 32, "max": 16, "clip": 16, "weight": 32, "norm": 4},
    2: {"project": 24, "score": 32, "max": 16, "clip": 16, "weight": 16, "norm": 4},
    4: {"project": 12, "score": 8, "max": 16, "clip": 16, "weight": 8, "norm": 4},
}
if MAC_LANES not in EXPECTED_PHASE_CYCLES:
    raise ValueError(f"MAC_LANES must be 1, 2, or 4; got {MAC_LANES}")

EXPECTED_COMPUTE_CYCLES = sum(EXPECTED_PHASE_CYCLES[MAC_LANES].values())
EXPECTED_INITIATION_INTERVAL_CYCLES = EXPECTED_COMPUTE_CYCLES + 11
MATCHED_VCD_WINDOW_CYCLES = (
    len(WARM_INPUTS) * EXPECTED_INITIATION_INTERVAL_CYCLES
)


def scheduled_lane_count(state: int) -> int:
    if state not in (2, 3, 6):
        return 0
    if MAC_LANES == 1:
        return 1
    if MAC_LANES == 2:
        return 1 if state == 3 else 2
    return 4


def cycle_number() -> int:
    time_ns = int(get_sim_time(unit="ns"))
    if time_ns % CLOCK_PERIOD_NS:
        raise AssertionError(f"measurement was not taken on a clock edge: {time_ns} ns")
    return time_ns // CLOCK_PERIOD_NS


def status_bit(dut, bit: int) -> bool:
    return bool((int(dut.uio_out.value) >> bit) & 1)


async def wait_status_bit(dut, bit: int, timeout: int = 2000) -> None:
    # Callers enter this helper from a falling edge, so an already-ready
    # endpoint can accept the next byte on the immediately following rising
    # edge. This is the benchmark's no-stall host behavior.
    if status_bit(dut, bit):
        return
    for _ in range(timeout):
        await FallingEdge(dut.clk)
        if status_bit(dut, bit):
            return
    raise AssertionError(f"timed out waiting for uio_out[{bit}]")


async def send_byte(dut, value: int, start_power_capture: bool = False) -> int:
    """Send a byte and return the rising-edge cycle that accepted it."""
    await wait_status_bit(dut, READY_RX)
    dut.ui_in.value = value
    dut.uio_in.value = 0x01
    if start_power_capture:
        dut.power_capture_start.value = 1
    await RisingEdge(dut.clk)
    accepted_cycle = cycle_number()
    await ReadOnly()
    await FallingEdge(dut.clk)
    dut.uio_in.value = 0
    if start_power_capture:
        dut.power_capture_start.value = 0
    return accepted_cycle


async def receive_byte(dut) -> tuple[int, int]:
    """Accept one response byte and return it with its handshake cycle."""
    await wait_status_bit(dut, VALID_TX)
    value = int(dut.uo_out.value)
    dut.uio_in.value = 0x02
    await RisingEdge(dut.clk)
    handshake_cycle = cycle_number()
    await ReadOnly()
    await FallingEdge(dut.clk)
    dut.uio_in.value = 0
    return value, handshake_cycle


async def load(
    dut, command: int, payload: list[int], start_power_capture: bool = False
) -> int:
    command_cycle = await send_byte(
        dut, command, start_power_capture=start_power_capture
    )
    for value in payload:
        await send_byte(dut, value)
    return command_cycle


async def reset(dut) -> None:
    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = 0
    dut.power_capture_start.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 3)
    dut.rst_n.value = 1
    await FallingEdge(dut.clk)


def rtl_core_if_available(dut):
    """Return the RTL core hierarchy, or None for synthesized gate netlists."""
    try:
        core = dut.user_project.core
        _ = int(core.state.value)
        return core
    except (AttributeError, TypeError, ValueError):
        return None


async def wait_for_done(dut, core) -> tuple[int, dict | None]:
    """Wait for done and sample phase and lane activity only when RTL exposes it."""
    phase_cycles = (
        {name: 0 for name in STATE_NAMES.values()} if core is not None else None
    )
    lane_active_cycles = [0 for _ in range(MAC_LANES)]

    # send_byte returns on a falling edge. Sample that stable state before the
    # following rising edge consumes its MAC/control work, then repeat from
    # each subsequent falling edge.
    for _ in range(2000):
        if core is not None:
            state = int(core.state.value)
            name = STATE_NAMES.get(state)
            if name is not None:
                phase_cycles[name] += 1
                for lane in range(scheduled_lane_count(state)):
                    lane_active_cycles[lane] += 1

        await RisingEdge(dut.clk)
        done_cycle = cycle_number()
        await ReadOnly()
        done_after_rising = status_bit(dut, DONE)
        # Gate-level simulation uses UNIT_DELAY. Returning at the following
        # falling edge makes the measurement observe both zero-delay RTL and
        # delayed cell outputs at the same architectural clock boundary.
        await FallingEdge(dut.clk)
        if done_after_rising or status_bit(dut, DONE):
            if core is None:
                return done_cycle, None
            active_lane_cycles = sum(lane_active_cycles)
            compute_cycles = sum(phase_cycles.values())
            return done_cycle, {
                "phase_cycles": phase_cycles,
                "lane_active_cycles": {
                    **{
                        f"lane{lane}": cycles
                        for lane, cycles in enumerate(lane_active_cycles)
                    },
                    "total": active_lane_cycles,
                },
                "useful_mac_operations": active_lane_cycles,
                "lane_slot_cycles": compute_cycles * MAC_LANES,
                "lane_utilization": active_lane_cycles
                / (compute_cycles * MAC_LANES),
            }

    raise AssertionError("timed out waiting for attention completion")


def mean(values: list[int | float]) -> float:
    return sum(values) / len(values)


def provenance_path(raw_path: str | None) -> dict | None:
    if not raw_path:
        return None
    path = Path(raw_path).resolve()
    repo_root = Path(__file__).resolve().parents[2]
    try:
        display_path = str(path.relative_to(repo_root))
        path_kind = "repo_relative"
    except ValueError:
        display_path = str(path)
        path_kind = "absolute"
    return {"path": display_path, "path_kind": path_kind}


def simulation_provenance(measurement_kind: str) -> dict:
    mode = os.environ.get("BENCHMARK_MODE", "rtl")
    pdk_root = os.environ.get("BENCHMARK_PDK_ROOT")
    pdk = provenance_path(pdk_root)
    if pdk is not None:
        pdk["identifier"] = Path(pdk_root).resolve().name
        pdk["pdk"] = os.environ.get("BENCHMARK_PDK")
        pdk["standard_cell_library"] = os.environ.get("BENCHMARK_SCL")
    return {
        "simulator": os.environ.get("BENCHMARK_SIMULATOR", "unknown"),
        "simulation_mode": mode,
        "measurement_kind": measurement_kind,
        "gate_netlist": provenance_path(os.environ.get("BENCHMARK_GATE_NETLIST")),
        "pdk": pdk,
        "gate_unit_delay": "#1" if mode == "gate" else None,
    }


async def start_power_capture(dut) -> int:
    """Begin a VCD on the next rising edge and return that edge's cycle."""
    dut.power_capture_start.value = 1
    await RisingEdge(dut.clk)
    start_cycle = cycle_number()
    await ReadOnly()
    await FallingEdge(dut.clk)
    dut.power_capture_start.value = 0
    return start_cycle


async def reach_power_capture_end(dut) -> int:
    """Reach the declared final edge without advancing simulation beyond it."""
    await RisingEdge(dut.clk)
    end_cycle = cycle_number()
    await ReadOnly()
    return end_cycle


def write_result(payload: dict) -> None:
    output = Path(
        os.environ.get(
            "BENCHMARK_OUTPUT",
            Path(__file__).resolve().parent / "results" / "warm_baseline.json",
        )
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


@cocotb.test()
async def test_warm_attention_baseline(dut):
    """Run the selected active or matched-idle warm power benchmark."""
    cocotb.start_soon(Clock(dut.clk, CLOCK_PERIOD_NS, unit="ns").start())
    await reset(dut)
    assert int(dut.uio_oe.value) == 0xF0

    weights = packed_weights()
    await load(dut, CMD_LOAD_WQ, weights["wq"])
    await load(dut, CMD_LOAD_WK, weights["wk"])
    await load(dut, CMD_LOAD_WV, weights["wv"])

    benchmark_kind = os.environ.get("BENCHMARK_KIND", "active")
    if benchmark_kind == "idle":
        dut.ui_in.value = 0
        dut.uio_in.value = 0
        vcd_start_cycle = await start_power_capture(dut)
        for _ in range(MATCHED_VCD_WINDOW_CYCLES - 1):
            await RisingEdge(dut.clk)
            await FallingEdge(dut.clk)
        vcd_stop_cycle = await reach_power_capture_end(dut)
        assert vcd_stop_cycle - vcd_start_cycle == MATCHED_VCD_WINDOW_CYCLES
        write_result(
            {
                "benchmark": "idle_warm_window",
                "variant": VARIANT,
                "mac_lanes": MAC_LANES,
                "measurement_kind": "idle_warm_window",
                "simulation_mode": os.environ.get("BENCHMARK_MODE", "rtl"),
                "clock_hz": CLOCK_HZ,
                "transaction_count": 0,
                "matched_active_transaction_count": len(WARM_INPUTS),
                "resident_weights_packed": weights,
                "host_activity": "none",
                "aggregate_vcd_measurement": {
                    "start_cycle": vcd_start_cycle,
                    "end_cycle": vcd_stop_cycle,
                    "duration_cycles": MATCHED_VCD_WINDOW_CYCLES,
                    "duration_ns": MATCHED_VCD_WINDOW_CYCLES * CLOCK_PERIOD_NS,
                    "transaction_count": 0,
                    "matched_active_transaction_count": len(WARM_INPUTS),
                },
                "provenance": simulation_provenance("idle_warm_window"),
            }
        )
        return
    if benchmark_kind != "active":
        raise AssertionError(f"unsupported BENCHMARK_KIND={benchmark_kind!r}")

    core = rtl_core_if_available(dut)
    transactions = []
    for index in range(len(WARM_INPUTS)):
        golden = golden_case(index)
        load_x_cycle = await load(
            dut,
            CMD_LOAD_X,
            golden["x_packed"],
            start_power_capture=index == 0,
        )
        run_cycle = await send_byte(dut, CMD_RUN_ATTENTION)
        done_cycle, rtl_metrics = await wait_for_done(dut, core)

        await send_byte(dut, CMD_READ_RESULT)
        observed = []
        final_result_handshake_cycle = None
        for _ in range(4):
            value, final_result_handshake_cycle = await receive_byte(dut)
            observed.append(value)

        assert observed == golden["expected_result_bytes"], (
            f"case {index}: expected {golden['expected_result_bytes']}, got {observed}"
        )

        compute_cycles = done_cycle - run_cycle
        latency_cycles = final_result_handshake_cycle - load_x_cycle
        if rtl_metrics is not None:
            assert sum(rtl_metrics["phase_cycles"].values()) == compute_cycles

        transactions.append(
            {
                **golden,
                "observed_result_bytes": observed,
                "cycle_boundaries": {
                    "load_x_accept": load_x_cycle,
                    "run_accept": run_cycle,
                    "done_assert": done_cycle,
                    "fourth_result_handshake": final_result_handshake_cycle,
                },
                "compute_cycles": compute_cycles,
                "latency_cycles": latency_cycles,
                "rtl_metrics": rtl_metrics,
            }
        )

    vcd_stop_cycle = await reach_power_capture_end(dut)
    compute_cycles = [row["compute_cycles"] for row in transactions]
    latency_cycles = [row["latency_cycles"] for row in transactions]
    initiation_interval_cycles = [
        transactions[index]["cycle_boundaries"]["load_x_accept"]
        - transactions[index - 1]["cycle_boundaries"]["load_x_accept"]
        for index in range(1, len(transactions))
    ]
    for index, interval in enumerate(initiation_interval_cycles, start=1):
        transactions[index]["initiation_interval_cycles"] = interval
    transactions[0]["initiation_interval_cycles"] = None

    first_warm_start_cycle = transactions[0]["cycle_boundaries"]["load_x_accept"]
    aggregate_vcd_duration_cycles = vcd_stop_cycle - first_warm_start_cycle
    assert aggregate_vcd_duration_cycles == MATCHED_VCD_WINDOW_CYCLES
    aggregate_vcd_duration_ns = aggregate_vcd_duration_cycles * CLOCK_PERIOD_NS
    steady_state_initiation_interval = mean(initiation_interval_cycles)
    phase_metrics_available = core is not None
    payload = {
        "benchmark": f"warm_attention_{VARIANT}",
        "variant": VARIANT,
        "mac_lanes": MAC_LANES,
        "measurement_kind": "warm_attention",
        "simulation_mode": os.environ.get("BENCHMARK_MODE", "rtl"),
        "clock_hz": CLOCK_HZ,
        "measurement_boundary": {
            "compute": "RUN_ATTENTION acceptance through done assertion",
            "latency": "LOAD_X command acceptance through fourth result-byte handshake",
            "vcd": "first LOAD_X acceptance through one full clock period after the final result-byte handshake",
            "host": "always ready, no intentional stalls",
        },
        "resident_weights_packed": weights,
        "transaction_count": len(transactions),
        "single_transaction_latency_cycles": mean(latency_cycles),
        "steady_state_initiation_interval_cycles": steady_state_initiation_interval,
        "steady_state_throughput_attentions_per_second": (
            CLOCK_HZ / steady_state_initiation_interval
        ),
        "aggregate_vcd_measurement": {
            "start_cycle": first_warm_start_cycle,
            "end_cycle": vcd_stop_cycle,
            "duration_cycles": aggregate_vcd_duration_cycles,
            "duration_ns": aggregate_vcd_duration_ns,
            "transaction_count": len(transactions),
            "energy_per_attention_formula": (
                "average_power_w * duration_ns * 1e-9 / transaction_count"
            ),
        },
        "provenance": simulation_provenance("warm_attention"),
        "phase_metrics_available": phase_metrics_available,
        "transactions": transactions,
        "summary": {
            "all_outputs_match_golden_model": True,
            "compute_cycles": {
                "min": min(compute_cycles),
                "max": max(compute_cycles),
                "mean": mean(compute_cycles),
            },
            "latency_cycles": {
                "min": min(latency_cycles),
                "max": max(latency_cycles),
                "mean": mean(latency_cycles),
            },
            "initiation_interval_cycles": {
                "min": min(initiation_interval_cycles),
                "max": max(initiation_interval_cycles),
                "mean": steady_state_initiation_interval,
            },
        },
    }
    if phase_metrics_available:
        first_metrics = transactions[0]["rtl_metrics"]
        assert all(row["rtl_metrics"] == first_metrics for row in transactions)
        assert first_metrics["phase_cycles"] == EXPECTED_PHASE_CYCLES[MAC_LANES]
        assert first_metrics["useful_mac_operations"] == 112
        payload["summary"]["rtl_phase_metrics_per_attention"] = first_metrics

    assert payload["summary"]["compute_cycles"] == {
        "min": EXPECTED_COMPUTE_CYCLES,
        "max": EXPECTED_COMPUTE_CYCLES,
        "mean": float(EXPECTED_COMPUTE_CYCLES),
    }
    assert steady_state_initiation_interval == EXPECTED_INITIATION_INTERVAL_CYCLES

    write_result(payload)
