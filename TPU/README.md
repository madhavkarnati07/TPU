# Toy Attention TPU

This repository now contains a complete fixed-shape attention accelerator for a
Tiny Tapeout 2x2 tile. It computes one signed-int4, single-head attention pass
over four 2D tokens. The controller deliberately reuses two MAC lanes over many
cycles to keep the design understandable and small.

## Fixed operation

```text
Q = clamp_int4(X * Wq)
K = clamp_int4(X * Wk)
V = clamp_int4(X * Wv)

scores = Q * K^T
u[j] = max(0, 4 + scores[j] - max(scores))
output = clamp_int4(round((u * V) / sum(u)))
```

Division uses a `round(256 / sum(u))` Q0.8 reciprocal lookup table. Products
are rounded to nearest with ties away from zero. See
[`docs/toy_attention_spec.md`](docs/toy_attention_spec.md) for the exact
arithmetic, byte protocol, debug selectors, and Tiny Tapeout pin map.

## Current implementation

| File | Role |
| --- | --- |
| `toy_attention.py` | Exact NumPy golden model and reference/stress cases |
| `test_toy_attention.py` | Arithmetic, packing, saturation, and model tests |
| `../src/dual_int4_mac.v` | Two signed-int4 multiply-accumulate lanes with int16 sums |
| `../src/toy_attention_core.v` | Storage, command protocol, attention datapath, and controller FSM |
| `../src/project.v` | Tiny Tapeout wrapper and pin mapping |
| `sim/tb_toy_attention.v` | Icarus top-level transaction and debug-trace checker |
| `../test/test.py` | Cocotb tests at the Tiny Tapeout wrapper boundary |
| `../info.yaml` | Tiny Tapeout project metadata, source list, tile count, and pins |
| `../src/config.json` | 10 MHz hardening configuration for a 2x2 tile |

The files under `rtl/rtl/` are earlier exploratory implementations. They are
not included in the Tiny Tapeout source list. In particular,
`rtl/rtl/systolic_array.v` does not elaborate against the historical `pe.v`
interface and is not part of the working chip.

## Run the model and RTL regression

Requirements are Python 3.10 or newer, Icarus Verilog, and GNU Make. On macOS:

```bash
brew install icarus-verilog
make setup
make verify
```

`make verify` runs 18 Python tests, the historical standalone PE simulation,
and two complete attention transactions generated from the Python model. The
RTL checks final bytes and Q/K/V, score, clipped-weight, denominator,
numerator, and reciprocal debug responses.

Run the wrapper-level cocotb tests from the repository root:

```bash
cd ../test
make
```

## Tiny Tapeout result

The current RTL has been hardened with LibreLane 3.0.3 and Sky130, then tested
again against the powered post-layout netlist. The 2x2 design uses 65.043% of
its placement area, meets the 10 MHz target with no setup or hold violations,
passes Magic/KLayout DRC, LVS, antenna, and the full Tiny Tapeout precheck.

Exact tool versions, timing, area, checks, and the remaining max-slew warning
are recorded in [`docs/tapeout_verification.md`](docs/tapeout_verification.md).

## Separate software experiment

The `tpu_matmul/` package and its tests are a separate JAX/NumPy matrix
multiplication experiment. They remain useful software examples but are not
part of the Verilog chip or its Tiny Tapeout submission sources.
