# TPU Matmul

Small matrix multiplication software with:

- NumPy CPU fallback
- JAX/XLA backend for CPU, GPU, or TPU
- `float32`, `bfloat16`, and emulated quantized `int8` modes
- CLI benchmarking with device sync

## Install

Local CPU development:

```bash
pip install -e .
```

Cloud TPU VM:

```bash
pip install -e ".[tpu]"
```

The TPU extra installs JAX's TPU package. On a TPU VM, JAX should expose devices whose
platform is `tpu`.

## Run

List visible devices:

```bash
tpu-matmul --list-devices
```

CPU fallback:

```bash
tpu-matmul --backend numpy --dtype float32 --m 1024 --k 1024 --n 1024
```

JAX on whatever accelerator is available:

```bash
tpu-matmul --backend jax --device auto --dtype float32
```

TPU explicitly:

```bash
tpu-matmul --backend jax --device tpu --dtype bfloat16 --m 4096 --k 4096 --n 4096
```

Quantized int8 emulation:

```bash
tpu-matmul --backend jax --device tpu --dtype int8 --check-error
```

## API

```python
from tpu_matmul import matmul, random_matrices

a, b = random_matrices(1024, 1024, 1024)
result = matmul(a, b, backend="jax", device="tpu", dtype_mode="bfloat16")
print(result.output, result.seconds, result.gops)
```

## Notes

This uses JAX for TPU support rather than writing raw TPU kernels. That is the normal
software stack: Python arrays are compiled by JAX/XLA and dispatched to the available
device. For custom TPU kernels, the next layer down is JAX Pallas, where tiling,
pipelining, and fused operations become explicit.

## Verilog PE Simulation

This repo also includes a single Processing Element (PE): a signed
multiply-accumulate unit.

Source files:

- `rtl/pe.v`: parameterized PE hardware module
- `sim/tb_pe.v`: Icarus Verilog testbench
- `Makefile`: build/run helper

Run the simulation:

```bash
make test-pe
```

Expected final output:

```text
PASS: PE multiply-accumulate simulation completed successfully.
```

On macOS, install Icarus Verilog with Homebrew:

```bash
brew install icarus-verilog
```

Check the install:

```bash
iverilog -V
vvp -V
```
