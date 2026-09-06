# Activity-Aware Post-Route Power

This directory measures the hardened Tiny Tapeout macro with switching activity
from a powered gate-level VCD. A measured run is accepted only when the VCD is
bound to its gate-simulation benchmark JSON and OpenSTA annotates at least one
pin. There is no vectorless fallback.

## Inputs

The runner reloads the existing nominal post-route artifacts:

- Sky130 nominal technology and standard-cell LEFs from `.tt-pdk`
- Sky130 nominal standard-cell Liberty from `.tt-pdk`
- final routed netlist: `runs/wokwi/final/nl/tt_um_madhavkarnati_toy_tpu.nl.v`
- nominal extracted SPEF: `runs/wokwi/final/spef/nom/tt_um_madhavkarnati_toy_tpu.nom.spef`
- generated 10 MHz SDC: `runs/wokwi/52-openroad-fillinsertion/...sdc`

Measured mode requires all three activity inputs:

- `--benchmark-result`: JSON emitted by the gate-level benchmark
- `--vcd`: the VCD emitted by that benchmark run
- `--scope`: the VCD hierarchy corresponding to the hardened top module

The example config supplies the repository's baseline VCD and scope. The
benchmark result remains an explicit command-line argument so every measured
invocation visibly names the metadata that authorizes its power and energy
interpretation.

Before OpenROAD starts, the runner requires:

- `simulation_mode` is exactly `gate`
- benchmark clock, cycle range, duration, and transaction counts are internally
  consistent
- active attention outputs matched the Python golden model
- the VCD timescale is parseable and timestamps are monotonic
- the VCD's first timestamp, last timestamp, and duration exactly equal the
  benchmark JSON window
- the benchmark clock equals the configured 10 MHz analysis clock

The current `warm_attention_baseline` benchmark maps to measurement kind
`warm_attention`. An idle benchmark uses `idle_warm_window` as its benchmark
name or `measurement_kind`, and must report zero attention transactions.

## Measured Run

From the repository root:

```sh
python3 analysis/power/run_power.py \
  --benchmark-result analysis/benchmark/results/gate_warm_baseline.json \
  --vcd analysis/benchmark/results/gate_warm_baseline.vcd \
  --scope tb.user_project \
  --output-dir analysis/power/out/baseline-2mac
```

Do not pass `--duration-ns` or `--transactions` in measured mode. Both values
are derived from `aggregate_vcd_measurement` in the benchmark result. The scope
may use `tb.user_project` or `tb/user_project`; the runner canonicalizes it to
OpenSTA's slash-separated form.

The runner uses the already-installed LibreLane 3.0.3 image pinned by digest.
It runs OpenROAD without network access and mounts the repository read-only.
The example config names `docker`, which is resolved through `PATH`; an
absolute executable path is also accepted. Docker/Colima must be running.

## Outputs

- `power.tcl`: exact OpenROAD commands
- `openroad.log`: complete tool output
- `activity_annotation.rpt`: OpenSTA's VCD-sourced annotation evidence
- `activity_unannotated.rpt`: remaining unannotated pins
- `power.rpt`: raw `report_power` table
- `result.json`: machine-readable result described by
  `power_result.schema.json`

`result.json` records the benchmark path and identity, canonical scope, derived
duration and transaction count, parsed VCD boundaries, and whether those
boundaries were verified against the benchmark. Annotation evidence includes
annotated and unannotated pin counts, coverage, and the number of signals under
the requested VCD scope.

At the start of every invocation, the runner removes its known files from the
selected output directory, including any prior `result.json`, `rejected.json`,
reports, log, and generated TCL. A run that later fails therefore cannot leave
a stale success result in that directory. Unrelated files are preserved.

If annotation is zero, the run exits nonzero and writes `rejected.json` plus
the activity reports. It does not write a new `power.rpt` or `result.json`.

OpenSTA is invoked as `report_power -digits 9`. The parser stores the complete
values emitted in that report, and energy is calculated from the stored
high-precision total rather than OpenSTA's rounded default display. `power_w`
reports total, internal, switching, and leakage power in watts. For measurement
kind `warm_attention`, the runner calculates:

```text
energy per attention (nJ) = total power (W) * benchmark duration (ns) / benchmark transactions
```

For `idle_warm_window`, it reports power with `energy: null`; an idle interval
does not represent completed attention operations.

The estimate covers the hardened accelerator macro at `nom_tt_025C_1v80` and
10 MHz. It includes modeled cell internal, net switching, clock, and leakage
power. It excludes the host, carrier, and board.

## Active Versus Idle

After producing active and idle measured results, print a direct power
comparison with:

```sh
jq -e -s '.[0] as $active | .[1] as $idle |
  if $active.measurement.kind != "warm_attention" or
     $idle.measurement.kind != "idle_warm_window"
  then error("expected active result followed by idle result")
  else {
    active_total_power_w: $active.power_w.total,
    idle_total_power_w: $idle.power_w.total,
    active_minus_idle_w: ($active.power_w.total - $idle.power_w.total),
    active_energy_per_attention_nj: $active.energy.per_attention_nj
  } end' \
  analysis/power/out/active/result.json \
  analysis/power/out/idle/result.json
```

## Validation-Only Mode

Use `--validation-only` to test annotation plumbing without invoking
`report_power` or emitting power or energy. Prefer supplying a benchmark result
so timestamp binding is checked too:

```sh
python3 analysis/power/run_power.py \
  --benchmark-result analysis/benchmark/results/gate_warm_baseline.json \
  --vcd analysis/benchmark/results/gate_warm_baseline.vcd \
  --scope tb.user_project \
  --validation-only \
  --output-dir analysis/power/out/gate-validation
```

For an unrelated VCD with no benchmark JSON, validation-only mode accepts
manual `--duration-ns` and `--transactions`; it verifies the manual duration
against the VCD but never treats those values as measured-power metadata.
