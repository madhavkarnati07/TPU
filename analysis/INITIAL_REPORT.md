# Toy Attention TPU: Initial MAC-Lane Study

- Data: [`pareto/pareto.json`](pareto/pareto.json)
- Visuals: [`pareto/architecture-analysis.html`](pareto/architecture-analysis.html)

## 1. Scope

This study compares one, two, and four MAC lanes for the same toy-attention
transaction. Precision, workload, weights, memory, clock, protocol, and tile
size remain fixed. Only `MAC_LANES` changes.

The question is: how does MAC-lane count trade standard-cell area against
throughput and energy per attention?

## 2. Design

- Four tokens, each with two signed-int4 values.
- Fixed signed-int4 Q, K, and V projection weights.
- On-chip Q/K/V projection, QK^T scoring, clipped linear softmax approximation,
  weighted V, and normalization.
- One, two, or four scalar MAC lanes selected at elaboration time.
- 10 MHz clock target and 2x2 TinyTapeout tile.
- Four packed output bytes returned to the host.

The arithmetic and byte protocol are defined in
[`../TPU/docs/toy_attention_spec.md`](../TPU/docs/toy_attention_spec.md).

## 3. Method

1. Check RTL output against the Python model for 16 fixed inputs.
2. Harden every variant with the same Sky130A flow, clock, and tile size.
3. Run the same inputs in powered gate-level simulation and capture VCD activity.
4. Estimate active power with OpenSTA using the routed netlist, SPEF, Liberty,
   SDC, and VCD.
5. Read standard-cell area and timing status from the final LibreLane metrics.
6. Derive throughput, energy per attention, utilization, and Pareto status.

```text
throughput = clock_frequency / initiation_interval
energy_per_attention = active_power * initiation_interval / clock_frequency
MAC_utilization = useful_MAC_operations / (MAC_lanes * compute_cycles)
```

## 4. Results

| MACs | Interval cycles | Attention/s | Active power mW | Energy nJ | Cell area um^2 | MAC utilization |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 159 | 62,893 | 0.354 | 5.636 | 46,757.3 | 75.7% |
| 2 | 119 | 84,034 | 0.383 | 4.557 | 49,416.1 | 51.9% |
| 4 | 75 | 133,333 | 0.430 | 3.224 | 56,065.0 | 43.8% |

Each variant performs 112 scalar MAC operations. All three match the 16 golden
cases in RTL and powered gate simulation, fit the 2x2 tile, and pass the
recorded 10 MHz setup/hold, routing DRC, Magic DRC, and LVS checks.

## 5. Findings

1. Four MACs deliver 2.12x the one-MAC throughput with 42.8% less energy and
   19.9% more standard-cell area.
2. Four MACs draw 21.3% more active power, but their initiation interval is
   52.8% shorter. Energy falls because the transaction completes faster.
3. The current scaling floor is 47 cycles: 36 serial attention cycles plus 11
   protocol cycles. The other 112 scalar MAC operations can be parallelized.
4. Utilization falls from 75.7% to 43.8% because the serial phases do not use
   additional MAC lanes.
5. All three points are Pareto-optimal. One MAC is smallest; four MACs are
   fastest and lowest-energy.

## 6. Limits

- Power is an activity-aware post-route OpenSTA estimate, not a silicon
  measurement.
- Maximum-slew warnings remain. The two- and four-MAC layouts also retain
  maximum-capacitance warnings.
- TinyTapeout submission checks have not been run for a selected design.
- Predictions for unimplemented schedulers or lane counts are hypotheses.

## 7. Reproduce the Report

From the repository root, with benchmark, power, and physical artifacts present:

```sh
python3 analysis/report/build_pareto.py
python3 analysis/report/build_architecture_analysis.py
python3 -m unittest analysis/pareto/test_build_pareto.py
python3 -m unittest analysis/pareto/test_build_architecture_analysis.py
```

Power-analysis tests:

```sh
cd analysis/power
python3 -m unittest test_run_power.py
```

See [`pareto/README.md`](pareto/README.md) for artifact generation.

## 8. Next Analyses

### A. Two-MAC Score Scheduler

- **Question:** Can both lanes compute independent QK^T scores concurrently?
- **Control:** Change only the score scheduler and operand routing.
- **Hypothesis:** 119 to 103 cycles; 84,034 to about 97,087 attention/s.
- **Add:** `[Measured cycles, area, power, energy, checks, and conclusion.]`

### B. Input-Activity Sensitivity

- **Question:** How much does estimated energy depend on input bit activity?
- **Control:** Keep one routed design and measurement window; change only inputs.
- **Compare:** Low-, typical-, and high-toggle input sets.
- **Add:** `[Input definitions, power spread, energy spread, and conclusion.]`

### C. Scaling Beyond Four MACs

- **Question:** Can eight lanes overcome the 47-cycle floor and four-key limit?
- **Control:** Keep arithmetic, precision, clock, tools, and metrics fixed.
- **Requirement:** Expose more independent work before adding lanes.
- **Add:** `[Cycle model, implementation results, bound, and conclusion.]`

Change workload shape, memory size, precision, or clock in separate studies so
each result has one primary cause.

## 9. Experiment Record Template

```text
Question:
Hypothesis:
Changed variable:
Controlled constants:
Branch and commit:
Commands:
Correctness result:
Cycles and throughput:
Power and energy:
Area and physical checks:
Observed or tool-reported facts:
Derived values:
Limitations:
Conclusion:
```
