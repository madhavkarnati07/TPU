from __future__ import annotations

import importlib.util
import time
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np

from .quantization import numpy_int8_matmul


Backend = Literal["auto", "numpy", "jax"]
Device = Literal["auto", "cpu", "gpu", "tpu"]
DTypeMode = Literal["float32", "bfloat16", "int8"]


@dataclass(frozen=True)
class MatmulResult:
    output: Any
    backend: str
    device: str
    dtype_mode: str
    seconds: float
    gops: float


def _jax_available() -> bool:
    return importlib.util.find_spec("jax") is not None


def available_devices() -> dict[str, list[str]]:
    """Return visible devices by backend without requiring JAX to be installed."""
    devices: dict[str, list[str]] = {"numpy": ["cpu"]}
    if not _jax_available():
        devices["jax"] = []
        return devices

    import jax

    devices["jax"] = [f"{d.platform}:{d.id}" for d in jax.devices()]
    return devices


def random_matrices(
    m: int,
    k: int,
    n: int,
    *,
    seed: int = 0,
    dtype: np.dtype = np.float32,
) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    a = rng.normal(size=(m, k)).astype(dtype)
    b = rng.normal(size=(k, n)).astype(dtype)
    return a, b


def matmul(
    a: Any,
    b: Any,
    *,
    backend: Backend = "auto",
    device: Device = "auto",
    dtype_mode: DTypeMode = "float32",
    repeats: int = 5,
    warmup: int = 1,
) -> MatmulResult:
    """Multiply two matrices with NumPy fallback or JAX/XLA acceleration."""
    if repeats < 1:
        raise ValueError("repeats must be >= 1")
    if warmup < 0:
        raise ValueError("warmup must be >= 0")

    a_np = np.asarray(a)
    b_np = np.asarray(b)
    if a_np.ndim != 2 or b_np.ndim != 2:
        raise ValueError("only rank-2 matrices are supported")
    if a_np.shape[1] != b_np.shape[0]:
        raise ValueError(f"shape mismatch: {a_np.shape} x {b_np.shape}")

    resolved_backend = _resolve_backend(backend, device)
    if resolved_backend == "numpy":
        return _matmul_numpy(
            a_np,
            b_np,
            dtype_mode=dtype_mode,
            repeats=repeats,
            warmup=warmup,
        )

    return _matmul_jax(
        a_np,
        b_np,
        device=device,
        dtype_mode=dtype_mode,
        repeats=repeats,
        warmup=warmup,
    )


def _resolve_backend(backend: Backend, device: Device) -> str:
    if backend == "numpy":
        if device not in ("auto", "cpu"):
            raise ValueError("NumPy backend only supports CPU")
        return "numpy"

    if backend == "jax":
        if not _jax_available():
            raise RuntimeError("JAX is not installed. Install with: pip install 'jax[tpu]'")
        return "jax"

    if device == "tpu":
        if not _jax_available():
            raise RuntimeError("TPU support requires JAX. Install with: pip install 'jax[tpu]'")
        return "jax"

    return "jax" if _jax_available() else "numpy"


def _ops(a: np.ndarray, b: np.ndarray) -> int:
    return 2 * a.shape[0] * a.shape[1] * b.shape[1]


def _time_best(fn, *, repeats: int, warmup: int, sync=lambda x: x):
    for _ in range(warmup):
        sync(fn())

    best_seconds = float("inf")
    best_out = None
    for _ in range(repeats):
        start = time.perf_counter()
        out = fn()
        sync(out)
        seconds = time.perf_counter() - start
        if seconds < best_seconds:
            best_seconds = seconds
            best_out = out
    return best_out, best_seconds


def _matmul_numpy(
    a: np.ndarray,
    b: np.ndarray,
    *,
    dtype_mode: DTypeMode,
    repeats: int,
    warmup: int,
) -> MatmulResult:
    if dtype_mode == "bfloat16":
        raise ValueError("bfloat16 mode requires the JAX backend")

    if dtype_mode == "int8":
        fn = lambda: numpy_int8_matmul(a, b)
    else:
        a32 = a.astype(np.float32, copy=False)
        b32 = b.astype(np.float32, copy=False)
        fn = lambda: a32 @ b32

    out, seconds = _time_best(fn, repeats=repeats, warmup=warmup)
    return MatmulResult(
        output=out,
        backend="numpy",
        device="cpu",
        dtype_mode=dtype_mode,
        seconds=seconds,
        gops=_ops(a, b) / seconds / 1e9,
    )


def _matmul_jax(
    a: np.ndarray,
    b: np.ndarray,
    *,
    device: Device,
    dtype_mode: DTypeMode,
    repeats: int,
    warmup: int,
) -> MatmulResult:
    import jax
    import jax.numpy as jnp

    target = _choose_jax_device(jax, device)
    if dtype_mode == "bfloat16":
        a_j = jax.device_put(jnp.asarray(a, dtype=jnp.bfloat16), target)
        b_j = jax.device_put(jnp.asarray(b, dtype=jnp.bfloat16), target)

        @jax.jit
        def kernel(x, y):
            return (x @ y).astype(jnp.float32)

    elif dtype_mode == "int8":
        a_j = jax.device_put(jnp.asarray(a, dtype=jnp.float32), target)
        b_j = jax.device_put(jnp.asarray(b, dtype=jnp.float32), target)

        @jax.jit
        def kernel(x, y):
            qa, a_scale = _jax_quantize_int8(x)
            qb, b_scale = _jax_quantize_int8(y)
            dims = (((1,), (0,)), ((), ()))
            acc = jax.lax.dot_general(
                qa,
                qb,
                dims,
                preferred_element_type=jnp.int32,
            )
            return acc.astype(jnp.float32) * (a_scale * b_scale)

    else:
        a_j = jax.device_put(jnp.asarray(a, dtype=jnp.float32), target)
        b_j = jax.device_put(jnp.asarray(b, dtype=jnp.float32), target)

        @jax.jit
        def kernel(x, y):
            return x @ y

    out, seconds = _time_best(
        lambda: kernel(a_j, b_j),
        repeats=repeats,
        warmup=warmup,
        sync=lambda x: x.block_until_ready(),
    )
    return MatmulResult(
        output=out,
        backend="jax",
        device=f"{target.platform}:{target.id}",
        dtype_mode=dtype_mode,
        seconds=seconds,
        gops=_ops(a, b) / seconds / 1e9,
    )


def _choose_jax_device(jax_module, device: Device):
    if device == "auto":
        return jax_module.devices()[0]

    matches = jax_module.devices(device)
    if not matches:
        visible = ", ".join(f"{d.platform}:{d.id}" for d in jax_module.devices())
        raise RuntimeError(f"no JAX {device} device visible; visible devices: {visible}")
    return matches[0]


def _jax_quantize_int8(x):
    import jax.numpy as jnp

    max_abs = jnp.max(jnp.abs(x))
    scale = jnp.where(max_abs > 0, max_abs / 127.0, 1.0)
    q = jnp.clip(jnp.round(x / scale), -127, 127).astype(jnp.int8)
    return q, scale
