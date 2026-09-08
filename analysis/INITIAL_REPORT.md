# Initial Architecture Study: Toy Attention TPU

**Status:** Bootstrap report with a completed fixed-workload MAC-lane study and
defined slots for follow-on analysis.

**Numerical source of truth:** [`pareto/pareto.json`](pareto/pareto.json)

**Visual companion:**
[`pareto/architecture-analysis.html`](pareto/architecture-analysis.html)

## Abstract

This project implements a small signed-int4, single-head attention accelerator
for TinyTapeout. The first architecture study holds the workload, arithmetic,
memory, clock, and 2x2 tile allocation fixed while comparing one, two, and four
MAC lanes. Four MACs provide 2.12x the throughput and 42.8% lower total active
energy than one MAC, at a cost of 19.9% more standard-cell area. All three
implementations remain Pareto-optimal because the one-MAC design is smallest
and the four-MAC design is fastest and lowest-energy.

## 1. Design Under Study

- Four tokens with two signed-int4 values per token.
- Fixed signed-int4 Q, K, and V projection weights.
- Q/K/V projection, QK^T scores, clipped linear softmax approximation,
  weighted V, and normalization execute on chip.
- One, two, or four scalar MAC lanes selected at elaboration time.
- Fixed 10 MHz clock target and 2x2 TinyTapeout tile allocation.
- Host loads one input transaction and reads four packed output bytes.

The exact arithmetic and byte protocol are defined in
[`../TPU/docs/toy_attention_spec.md`](../TPU/docs/toy_attention_spec.md).

## 2. Study Question

For one fixed attention workload and one TinyTapeout area budget, how does MAC
lane count trade standard-cell area against throughput and energy per attention
transaction?

Only `MAC_LANES` changes in this study. This isolates the effect of compute
parallelism from precision, memory, workload, clock, and algorithm changes.

## 3. Experimental Method

1. Compare RTL outputs against the Python golden model for 16 fixed input cases.
2. Harden each lane variant with the same Sky130A flow, clock, and tile size.
3. Repeat the workload in powered gate-level simulation and capture VCD activity.
4. Use OpenSTA with the routed netlist, SPEF, Liberty, SDC, and VCD to estimate
   active power.
5. Read standard-cell area and timing status from the final LibreLane metrics.
6. Derive throughput, energy per attention, lane utilization, and Pareto status.

The primary equations are:

```text
throughput = clock_frequency / steady_state_initiation_interval
energy_per_attention = active_power * steady_state_initiation_interval / clock_frequency
MAC_utilization = useful_scalar_MAC_operations / (MAC_lanes * compute_cycles)
```

## 4. Current Results

| MACs | Interval cycles | Attention/s | Active power mW | Energy nJ | Cell area um^2 | MAC utilization |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 159 | 62,893 | 0.354 | 5.636 | 46,757.3 | 75.7% |
| 2 | 119 | 84,034 | 0.383 | 4.557 | 49,416.1 | 51.9% |
| 4 | 75 | 133,333 | 0.430 | 3.224 | 56,065.0 | 43.8% |

All variants perform 112 useful scalar MAC operations and match the 16 golden
cases in RTL and powered gate simulation. They pass 10 MHz setup/hold, routing
DRC, Magic DRC, and LVS in the recorded experiment.

## 5. Initial Findings

1. **More active power can still mean less transaction energy.** The four-MAC
   implementation draws 21.3% more active power than one MAC, but its
   steady-state transaction interval is 52.8% shorter, reducing energy by 42.8%.
2. **The serial work sets the scaling limit.** The current schedule contains 112
   scalar MAC operations plus a 47-cycle floor: 36 serial attention cycles and
   11 host-protocol cycles.
3. **Utilization falls as lanes are added.** Maximum search, clipping,
   normalization, and protocol work do not use the extra MAC lanes.
4. **Four MACs suit the current problem shape.** Four tokens expose four
   independent key scores. Additional lanes need a different schedule, parallel
   query rows, or a larger problem shape.

## 6. Evidence Boundary

**Tool-reported or observed:** outputs, cycles, gate-level VCD activity,
post-route OpenSTA power estimate, standard-cell area, timing, DRC, and LVS.

**Derived:** throughput, energy per attention, normalized changes, utilization,
the serial floor, and the analytical scaling bound.

**Not established:** silicon power, TinyTapeout shuttle acceptance, or the
physical results of any proposed architecture extension. Maximum-slew warnings
remain, and the two- and four-MAC layouts retain maximum-capacitance warnings.
Official TinyTapeout submission checks are still required.

## 7. Reproduce the Report Layer

Run these commands from the repository root after the referenced benchmark,
power, and physical artifacts are present:

```sh
python3 analysis/report/build_pareto.py
python3 analysis/report/build_architecture_analysis.py
python3 -m unittest analysis/pareto/test_build_pareto.py
python3 -m unittest analysis/pareto/test_build_architecture_analysis.py
```

Run the power-analysis contract tests separately:

```sh
cd analysis/power
python3 -m unittest test_run_power.py
```

The complete artifact-generation procedure is documented in
[`pareto/README.md`](pareto/README.md).

## 8. Follow-On Analysis Slots

### A. Two-MAC Score Scheduler

**Status:** Recommended next controlled experiment.

**Question:** Can both MAC lanes compute independent QK^T scores concurrently?

**Change only:** The two-MAC score scheduler and required operand routing.

**Hold fixed:** Workload, arithmetic, weights, memory, MAC count, protocol,
10 MHz target, and 2x2 tile.

**Analytical hypothesis:** Reduce the interval from 119 to 103 cycles and raise
throughput from 84,034 to approximately 97,087 attention/s.

**Required evidence:** RTL/gate correctness, phase-cycle trace, routed area,
timing/DRC/LVS, transaction VCD, power estimate, and updated Pareto point.

**Result placeholder:** `[Add measured table, chart, and conclusion here.]`

### B. Input-Activity Sensitivity

**Status:** Placeholder.

**Question:** How much does estimated energy change with input switching activity
when architecture and cycle count are unchanged?

**Change only:** Input vectors grouped into low-, typical-, and high-toggle sets.

**Hold fixed:** Selected RTL variant, workload shape, weights, clock, layout,
measurement window, and power flow.

**Required evidence:** Identical functional and cycle results, one VCD per input
set, power/energy distribution, and a statement about data dependence.

**Result placeholder:** `[Define vectors, run measurements, and summarize spread.]`

### C. Scaling Beyond Four MACs

**Status:** Placeholder; begin only after the scheduler experiment.

**Question:** Does an eight-lane design provide useful throughput after the
47-cycle serial floor and four-key parallelism limit are considered?

**Change only:** MAC-lane count plus the minimum scheduling support needed to
expose independent work. Record any workload-shape change as a separate study.

**Hold fixed:** Precision, attention arithmetic, clock target, toolchain, metric
definitions, and verification standard.

**Required evidence:** New cycle model, utilization, area, timing, power, energy,
and comparison against the analytical bound.

**Result placeholder:** `[Add the new design point or explain why it is invalid.]`

### D. Later Architecture Variables

Study precision, memory capacity, clock target, or attention shape one at a time.
Each deserves a separate report subsection because changing several together
prevents a first-principles explanation of the result.

**Candidate variable:** `[int4/int8, memory depth, frequency, or token count]`

**Research question:** `[State one falsifiable question.]`

**Controlled constants:** `[List everything held fixed.]`

**Result placeholder:** `[Add method, evidence, result table, and conclusion.]`

## 9. Experiment Record Template

Use this block for every added design point:

```text
Experiment name:
Question:
Hypothesis:
Single changed variable:
Controlled constants:
Source branch and commit:
Exact reproduction commands:
Functional verification result:
Cycle and throughput result:
Power and energy result:
Area and physical-check result:
Measured/tool-reported facts:
Derived values:
Remaining limitations:
Conclusion:
```

An analysis is complete only when its artifacts are reproducible, its
provenance matches the RTL being discussed, and its report clearly separates
observations, derivations, and hypotheses.
