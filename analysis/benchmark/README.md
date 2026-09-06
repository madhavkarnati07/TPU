# Warm Baseline Benchmark

This benchmark characterizes the unchanged two-MAC toy-attention RTL for the
fixed-workload Pareto study. It loads WQ, WK, and WV once, then runs exactly
16 deterministic signed-int4 X matrices with an always-ready host.

The expected output for every transaction is produced by `TPU/toy_attention.py`.
The benchmark does not duplicate the attention arithmetic and does not modify
any synthesizable RTL.

## Measurements

- `compute_cycles`: from `RUN_ATTENTION` acceptance through `done` assertion.
- `latency_cycles`: from `LOAD_X` command acceptance through the
  fourth result-byte handshake.
- `initiation_interval_cycles`: difference between consecutive `LOAD_X`
  acceptance edges. This is the sustained-throughput interval.
- RTL-only phase cycles and scheduled two-lane utilization. Gate-level
  netlists intentionally omit these internal signals, so this field is absent
  in gate-level results.

The VCD itself begins on the first warm `LOAD_X` acceptance edge. It ends one
complete 10 MHz clock period after the final result-byte handshake. Reset and
one-time weight loading are excluded. `aggregate_vcd_measurement` records its
exact start/end cycles and duration; energy per attention is average VCD power
times that duration, divided by 16. `make` runs `verify_vcd_window.py` after
simulation and fails if the actual VCD timestamps disagree with that JSON or
if the VCD contains `$dumpoff`/terminal X or Z contamination.

Both active and idle JSON files record the simulator, RTL/gate mode, selected
gate netlist, PDK identifier/path, benchmark kind, and gate delay mode.

## Run RTL

```bash
cd analysis/benchmark
PATH="$PWD/../../.tt-venv/bin:$PATH" make
```

This writes `results/rtl_warm_baseline.json` and
`results/rtl_warm_baseline.vcd`. Override paths when collecting a separate
experiment:

```bash
make BENCHMARK_OUTPUT=/tmp/result.json WAVEFORM=/tmp/warm.vcd
```

## Run Matched Idle

The idle benchmark performs the same reset and one-time resident-weight load,
then sends no host traffic while capturing exactly the active benchmark's
1,904-cycle window:

```bash
PATH="$PWD/../../.tt-venv/bin:$PATH" make BENCHMARK_KIND=idle
```

This writes `results/rtl_idle_warm_window.json` and its matched VCD. Combine
`BENCHMARK_KIND=idle` with the gate-level arguments below for power comparison.

## Run Gate-Level

The generated netlist is intentionally not tracked. Supply both the PDK root
and the netlist path when the supervisor has hardened a variant:

```bash
cd analysis/benchmark
PATH="$PWD/../../.tt-venv/bin:$PATH" \
  make GATES=yes \
  PDK_ROOT=/path/to/pdk-root \
  NETLIST=/path/to/gate_level_netlist.v
```

Gate-level output verifies the same 16 Python-golden transactions and emits a
VCD suitable for post-route activity annotation. It reports external cycle
metrics but leaves RTL hierarchy-derived phase metrics unavailable.
