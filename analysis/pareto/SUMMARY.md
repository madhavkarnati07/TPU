# Fixed-Workload MAC Scaling Summary

## Question

For the fixed four-token, two-dimensional signed-int4 attention workload, how do one, two, and four MAC lanes trade standard-cell area against throughput and total active energy?

## Implementation Results

| MACs | Interval cycles | Attention/s | Active power mW | Energy nJ | Cell area um^2 | MAC utilization |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 159 | 62,893 | 0.354 | 5.636 | 46,757.3 | 75.7% |
| 2 | 119 | 84,034 | 0.383 | 4.557 | 49,416.1 | 51.9% |
| 4 | 75 | 133,333 | 0.430 | 3.224 | 56,065.0 | 43.8% |

All variants execute the same 112 useful scalar MAC operations, match all 16 Python golden workloads in RTL and powered gate simulation, fit the same 2x2 tile, and pass 10 MHz setup/hold, route DRC, Magic DRC, and LVS.

## Conclusions

- Four MACs provide 2.12x the 1-MAC throughput and use 42.8% less total energy for 19.9% more standard-cell area.
- Energy falls despite 21.3% higher active power because the steady-state transaction interval falls from 159 to 75 cycles.
- The workload contains 112 scalar MAC operations, taking 112/L cycles under ideal distribution across L lanes. The schedule also has a 47-cycle floor: 36 serial attention cycles plus 11 protocol cycles.
- MAC utilization falls from 75.7% to 43.8% because MAX, clipping, normalization, and protocol work do not use the additional lanes.
- All three designs are Pareto-optimal when area, throughput, and energy are considered together. Four MACs win on speed and energy; one MAC remains smallest.

## Next Experiment

The current 2-MAC implementation still computes QK^T scores through one lane. A score-parallel scheduler would reduce its analytical interval from 119 to 103 cycles and raise theoretical throughput from 84,034 to 97,087 attention/s. This is a hypothesis, not a measured design point; its power, energy, area, and physical feasibility remain unknown.

## Evidence Boundary

- **Measured:** functional outputs, cycles, VCD activity, tool-reported post-route OpenSTA power estimate, standard-cell area, timing, DRC, and LVS.
- **Derived:** normalized changes, utilization, the serial floor, and Amdahl scaling.
- **Not established:** silicon power, shuttle acceptance, or the physical result of the proposed score-parallel scheduler.

The layouts retain maximum-slew warnings, and the 2- and 4-MAC variants retain maximum-capacitance warnings. Official TinyTapeout checks remain required for the selected submission candidate.
