# Analysis Pipeline

Start with the [initial architecture study](INITIAL_REPORT.md). It summarizes
the validated one-, two-, and four-MAC results and defines controlled slots for
follow-on analysis. The generated
[visual analysis](pareto/architecture-analysis.html) and
[concise summary](pareto/SUMMARY.md) are derived from `pareto/pareto.json`.

## Milestone 1 Baseline

The tracked two-MAC baseline is `report/baseline_2mac.json`. It combines the
fixed 16-transaction warm-attention workload, gate-level VCD power, and final
LibreLane physical metrics. All artifact references in the report are relative
to the repository root.

From the repository root, regenerate the matched gate-level evidence and report:

```sh
PATH="$PWD/.tt-venv/bin:$PATH" make -C analysis/benchmark
PATH="$PWD/.tt-venv/bin:$PATH" make -C analysis/benchmark GATES=yes PDK_ROOT="$PDK_ROOT" NETLIST="$NETLIST"
PATH="$PWD/.tt-venv/bin:$PATH" make -C analysis/benchmark BENCHMARK_KIND=idle GATES=yes PDK_ROOT="$PDK_ROOT" NETLIST="$NETLIST"
python3 analysis/power/run_power.py --benchmark-result analysis/benchmark/results/gate_warm_baseline.json --vcd analysis/benchmark/results/gate_warm_baseline.vcd --scope tb.user_project --output-dir analysis/power/out/baseline-2mac
python3 analysis/power/run_power.py --benchmark-result analysis/benchmark/results/gate_idle_warm_window.json --vcd analysis/benchmark/results/gate_idle_warm_window.vcd --scope tb.user_project --output-dir analysis/power/out/idle-2mac
python3 analysis/report/build_baseline_2mac.py
```

`$PDK_ROOT` and `$NETLIST` identify the powered Sky130 library and the matching
gate-level netlist. Measured power derives its duration and transaction count
from `--benchmark-result`; manual `--duration-ns` and `--transactions` are
forbidden. The report rejects mismatched active/idle clocks, windows, weights,
VCD bindings, provenance, annotation, energy arithmetic, or timing-constraint
failures. Both gate runs must use exactly `test/gate_level_netlist.v` with
matching simulator, PDK, and unit delay. Power runs must use the same routed
artifacts and tool identity, including nine-digit `report_power` output. No
file hashes are used.

The builder requires the expected final routed netlist, nominal SPEF, generated
SDC, and nominal Liberty. It reads the power-used SDC and requires its 100 ns
`clk` constraint to match the 10 MHz benchmark and both power results. Complete
VCD annotation is retained as evidence that VCD names map to the physical
netlist. During every report build, the canonical
`analysis/benchmark/verify_vcd_window.py` checks both referenced gate VCDs for
exact timestamps, absence of `$dumpoff`, and terminal values without X/Z.

Total active energy per attention is the primary Pareto metric. The report also
includes an idle-subtracted value only as a sanity diagnostic.

Area and timing come from `runs/wokwi/final/metrics.json`, the final
LibreLane metric bundle: `design__instance__count__stdcell`,
`design__instance__area__stdcell`, and per-corner setup/hold WNS, TNS, and
violation counts. Timing is reported strictly as a pass/fail implementation
constraint, not an optimization metric.
