# Milestone 2 Pareto Report

The concise interpretation is available as the generated
[architecture analysis](architecture-analysis.html) and
[summary report](SUMMARY.md). Rebuild both from `pareto.json` with:

```sh
python3 analysis/report/build_architecture_analysis.py
```

`build_pareto.py` compares the fixed signed-int4 toy-attention workload across
one-, two-, and four-scalar-MAC implementations. It is a report layer only: it
does not build RTL, run simulation, harden a layout, or run power analysis.

## Initial Results

All three variants use the same 16 warm inputs, resident weights, signed-int4
arithmetic, 10 MHz clock, byte protocol, and 2x2 Tiny Tapeout tile.

| Variant | Compute cycles | Lane use | Throughput (/s) | Active power (mW) | Energy (nJ/attention) | Cell area (um2) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `mac1` | 148 | 75.7% | 62,893 | 0.3544 | 5.636 | 46,757.3 |
| `mac2` | 108 | 51.9% | 84,034 | 0.3829 | 4.557 | 49,416.1 |
| `mac4` | 64 | 43.8% | 133,333 | 0.4298 | 3.224 | 56,065.0 |

Each point is non-dominated when area, energy, and throughput are considered
together. The 4-MAC implementation is fastest and lowest-energy, but the
1-MAC implementation remains the smallest. All routed variants pass the 10 MHz
setup and hold constraints. Power is post-route OpenSTA power from each
variant's own powered gate-level VCD with 100% pin annotation; it is not a
silicon measurement. Every point performs 112 useful MAC operations; lower
lane utilization at higher lane counts shows the fixed serial controller work
that additional MACs cannot accelerate. Nonfatal maximum-slew warnings remain
in all three local layouts, and the 2-MAC and 4-MAC runs also report maximum-cap
warnings. These are retained in the CSV/JSON and must be revisited before
selecting a shuttle submission candidate.

The first tradeoffs are clear:

- `mac2` versus `mac1`: 5.7% more area buys 33.6% more throughput and 19.1%
  lower energy, despite 8.0% higher active power.
- `mac4` versus `mac2`: 13.5% more area buys 58.7% more throughput and 29.3%
  lower energy, despite 12.2% higher active power.
- Energy falls because the additional lanes shorten the active transaction
  faster than they raise power. Area prevents `mac4` from dominating the two
  smaller points in the three-objective analysis.
- The matched-idle-subtracted diagnostic is 0.836, 0.807, and 0.781 nJ for
  `mac1`, `mac2`, and `mac4`, while total active energy changes much more. This
  indicates that fixed clocked
  state and controller overhead, paid for fewer cycles by the wider designs,
  is a major part of this toy workload's energy result. Total active energy
  remains the Pareto metric; idle subtraction is diagnostic only.

## Required Inputs

Place exactly these JSON artifacts under each variant directory:

```text
analysis/pareto/results/
  mac1/
    rtl.json
    gate-active.json
    gate-idle.json
    power-active.json
    power-idle.json
    metrics.json
    physical-context.json
  mac2/
    ...same six files...
  mac4/
    ...same six files...
```

`rtl.json` and `gate-active.json` use the warm benchmark format and must add a
top-level integer `mac_lanes`. Their required common fields are `benchmark`,
`measurement_kind`, `clock_hz`, `transaction_count`, `resident_weights_packed`,
`measurement_boundary`, `summary`, the performance fields, and a transaction
list. Each transaction records `index`, `x`, `x_packed`, expected and observed
result bytes, compute cycles, latency cycles, and initiation-interval cycles.
The gate provenance must point to the powered netlist under the matching
`runs/macN/final/pnl/` directory.

`gate-idle.json` uses the idle benchmark format and also has top-level
`mac_lanes`. It records zero transactions, `matched_active_transaction_count`,
the same 10 MHz clock and resident weights, and `idle_warm_window` as both its
benchmark and measurement kind.

`power-active.json` and `power-idle.json` use the existing power-result format.
The active result must be a measured `warm_attention` window with the same
transaction count as `gate-active.json`; it must include `power_w.total`,
`measurement.duration_ns`, `energy.window_j`, and `energy.per_attention_nj`.
The script recomputes both energy values from total active power and rejects a
mismatch. The idle result must be a measured `idle_warm_window` with zero
transactions and `energy: null`. Both require a 100 ns physical clock period,
100% VCD pin annotation, zero unannotated pins, and identical active/idle
physical context. All variants must use the same PDK, corner, and tool setup.
Each power result must use the matching `runs/macN` routed netlist, SPEF, and
SDC, and its VCD window must be verified against the corresponding benchmark.

`metrics.json` is the final LibreLane metrics object. Required fields are
`design__instance__area__stdcell`, `design__instance__count__stdcell`, and the
setup/hold `wns`, `tns`, and violation-count values for every discovered setup
corner. All timing checks must pass.

`physical-context.json` is a portable snapshot of the run's `resolved.json`.
It binds `metrics.json` to the variant name, `MAC_LANES` synthesis parameter,
2x2 die, 100 ns clock, Sky130 PDK, standard-cell library, and RTL source list.
It also records the source state and LibreLane version used for this initial
experiment. The report rejects a mismatched variant or metrics file.

All variants must match on workload identity, resident packed weights,
measurement boundary, 10 MHz clock, transaction count, inputs, expected
outputs, and observed output bytes. `mac1`, `mac2`, and `mac4` must report 1,
2, and 4 lanes respectively. RTL and gate artifacts must agree exactly on the
observable outputs and all reported cycle counts for their own variant.

## Run

From the repository root:

```sh
python3 analysis/report/build_pareto.py
```

For a fixture or a different output directory:

```sh
python3 analysis/report/build_pareto.py \
  --results-root /path/to/results \
  --output-dir /path/to/output
```

The command writes `analysis/pareto/pareto.json`, `pareto.csv`, and
`pareto.svg`. A point is non-dominated only when no other point uses no more
energy and area while providing at least as much throughput, with one strict
improvement.

## Reproduce One Variant

From the repository root, set `N` to `1`, `2`, or `4` and set `VARIANT` to the
matching `mac1`, `mac2`, or `mac4`:

```sh
N=1
VARIANT=mac1
PDK_VERSION=8afc8346a57fe1ab7934ba5a6056ea8b43078e71
PDK_ROOT="$PWD/.tt-pdk/ciel/ciel/sky130/versions/$PDK_VERSION"

PATH="$PWD/.tt-venv/bin:$PATH" make -C analysis/benchmark \
  MAC_LANES="$N" VARIANT="$VARIANT"

mkdir -p "runs/$VARIANT"
.tt-venv/bin/python -m librelane \
  --docker-no-tty --dockerized \
  --pdk-root "$PWD/.tt-pdk/ciel" --pdk sky130A --scl sky130_fd_sc_hd \
  --run-tag "$VARIANT" --force-run-dir "runs/$VARIANT" --overwrite \
  --hide-progress-bar -c "SYNTH_PARAMETERS=MAC_LANES=$N" \
  src/config.json src/pareto_2x2_config.json

PATH="$PWD/.tt-venv/bin:$PATH" make -C analysis/benchmark GATES=yes \
  MAC_LANES="$N" VARIANT="$VARIANT" PDK_ROOT="$PDK_ROOT" \
  NETLIST="$PWD/runs/$VARIANT/final/pnl/tt_um_madhavkarnati_toy_tpu.pnl.v"

PATH="$PWD/.tt-venv/bin:$PATH" make -C analysis/benchmark GATES=yes \
  BENCHMARK_KIND=idle MAC_LANES="$N" VARIANT="$VARIANT" \
  PDK_ROOT="$PDK_ROOT" \
  NETLIST="$PWD/runs/$VARIANT/final/pnl/tt_um_madhavkarnati_toy_tpu.pnl.v"
```

```sh
python3 analysis/power/run_power.py \
  --config "analysis/pareto/configs/$VARIANT-power.json" \
  --benchmark-result "analysis/benchmark/results/gate_${VARIANT}_warm.json" \
  --vcd "analysis/benchmark/results/gate_${VARIANT}_warm.vcd" \
  --scope tb.user_project \
  --output-dir "analysis/power/out/${VARIANT}-active"

python3 analysis/power/run_power.py \
  --config "analysis/pareto/configs/$VARIANT-power.json" \
  --benchmark-result "analysis/benchmark/results/gate_${VARIANT}_idle.json" \
  --vcd "analysis/benchmark/results/gate_${VARIANT}_idle.vcd" \
  --scope tb.user_project \
  --output-dir "analysis/power/out/${VARIANT}-idle"

python3 analysis/report/capture_physical_context.py \
  --variant "$VARIANT"
```

Place the seven resulting benchmark, power, metrics, and physical-context JSONs in the matching
results directory, then rebuild the report. The checked-in result directories
show the exact expected names.
