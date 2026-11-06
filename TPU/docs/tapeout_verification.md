# Tiny Tapeout Verification Evidence

This report records the local evidence for the fixed toy-attention RTL. It is
not a foundry acceptance notice; the submitted revision must still pass the
official cloud workflow used by the selected Tiny Tapeout shuttle.

## Design target

| Item | Value |
| --- | --- |
| Top module | `tt_um_madhavkarnati_toy_tpu` |
| Technology | Sky130A |
| Tile allocation | 2x2 |
| Clock | 10 MHz, 100 ns period |
| Hardening flow | LibreLane 3.0.3 |
| PDK revision | `8afc8346a57fe1ab7934ba5a6056ea8b43078e71` |
| Tiny Tapeout support tools | `8bca34afbe6623b97150f34ba19e1582b9458bc1` |

## Functional verification

| Level | Result |
| --- | --- |
| Python model | 18 tests pass in the combined Python suite |
| Icarus RTL | Two full transactions match Python final and debug traces |
| Tiny Tapeout wrapper RTL | Both cocotb protocol tests pass |
| Powered post-layout netlist | Both cocotb protocol tests pass |

The tests cover the reference case and a signed/saturating stress case. The
wrapper test also checks invalid-command handling, load prerequisites,
backpressure, debug reads, and `FLUSH` invalidation.

## Physical result

| Metric | Result |
| --- | --- |
| Tiny Tapeout reported utilization | 65.043% |
| Core area | 72,564.6 um^2 |
| Die area | 75,602.5 um^2 |
| Flip-flops | 446 |
| Final cells including fillers | 12,520 |
| Routed wire length | 122,218 um |
| Worst setup slack | 70.189609 ns |
| Worst hold slack | 0.119712 ns |
| Setup / hold violations | 0 / 0 |
| Route DRC / Magic DRC | 0 / 0 |
| Antenna / power-grid violations | 0 / 0 |
| LVS | Circuits match uniquely |
| Verilator lint warnings | 0 |

## Tiny Tapeout precheck

The generated submission bundle passes every check in the locally cloned
Tiny Tapeout support tools:

- Magic DRC
- KLayout FEOL, BEOL, off-grid, pin-purpose overlap, and zero-area checks
- top-cell, forbidden-layer, boundary, pin, power-pin, and layer checks
- nwell/urpm, analog-pin consistency, cell-name, and Verilog syntax checks

The bundle is under the generated `tt_submission/` directory and contains the
GDS, OAS, LEF, powered Verilog, SPEF corners, metrics, and resolved metadata.

## Residual electrical warning

The final flow reports no setup, hold, capacitance, DRC, LVS, antenna, or
power-grid violations. It does report non-fatal maximum-slew warnings in the
slow and typical timing corners; the worst slow-corner count is 1,318. Tiny
Tapeout's current checker records these as warnings rather than a failed gate.
This is the remaining physical-design cleanup item and should be reviewed in
the official cloud hardening report before submission.

## Reproduce

From `TPU/`:

```bash
make verify
```

From the repository root, after installing `test/requirements.txt`:

```bash
cd test
make
make GATES=yes
```

The gate-level command requires `PDK_ROOT` and the generated
`test/gate_level_netlist.v`. Hardening and precheck use the Tiny Tapeout
support-tools revision listed above; their generated products are intentionally
ignored by Git.
