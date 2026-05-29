# TPU Matmul

Matrix multiplication software with:

- NumPy CPU fallback
- JAX/XLA backend for CPU, GPU, or TPU
- `float32`, `bfloat16`, and emulated quantized `int8` modes
- CLI benchmarking with device synchronization

## Install

Local CPU development:

```bash
pip install -e .
```

Cloud TPU VM:

```bash
pip install -e ".[tpu]"
```

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

JAX/XLA is the TPU software path. For deeper custom TPU work, the next layer down is
JAX Pallas, where tiling, memory movement, and fused kernels become explicit.
