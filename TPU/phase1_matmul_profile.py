#!/usr/bin/env python3
"""
Phase 1 mini-TPU study:
- implement matrix multiplication directly in Python
- compare it with NumPy float32 GEMM
- emulate int8 quantized matmul with int32 accumulation
- report runtime, throughput, and quantization error

Run:
    python3 phase1_matmul_profile.py
"""

from __future__ import annotations

import argparse
import cProfile
import math
import pstats
import time
from dataclasses import dataclass
from typing import Callable

import numpy as np


Array = np.ndarray


@dataclass
class BenchResult:
    name: str
    seconds: float
    gops: float
    max_abs_error: float | None = None
    mean_abs_error: float | None = None


def matmul_naive_python(a: Array, b: Array) -> Array:
    """Reference implementation. Clear, correct, and intentionally slow."""
    m, k = a.shape
    k2, n = b.shape
    if k != k2:
        raise ValueError(f"shape mismatch: {a.shape} x {b.shape}")

    c = np.zeros((m, n), dtype=np.float32)
    for i in range(m):
        for j in range(n):
            acc = 0.0
            for kk in range(k):
                acc += float(a[i, kk]) * float(b[kk, j])
            c[i, j] = acc
    return c


def matmul_numpy_float32(a: Array, b: Array) -> Array:
    return a @ b


def symmetric_quantize_int8(x: Array) -> tuple[Array, float]:
    """
    Symmetric int8 quantization:
        q = round(x / scale), clipped to [-127, 127]
        x ~= q * scale

    Zero is represented exactly and accumulation can stay simple.
    """
    max_abs = float(np.max(np.abs(x)))
    scale = max_abs / 127.0 if max_abs > 0.0 else 1.0
    q = np.round(x / scale).clip(-127, 127).astype(np.int8)
    return q, scale


def matmul_quantized_int8(a: Array, b: Array) -> Array:
    """
    Emulate int8 matmul:
      1. quantize float32 A and B into int8
      2. multiply int8 values, accumulate into int32
      3. dequantize result back to float32

    Important: NumPy's int8 @ int8 accumulates/wraps in int8, which is not what
    TPU-like dot products do. Cast to int32 before @ to avoid overflow.
    """
    a_q, a_scale = symmetric_quantize_int8(a)
    b_q, b_scale = symmetric_quantize_int8(b)
    acc_i32 = a_q.astype(np.int32) @ b_q.astype(np.int32)
    return acc_i32.astype(np.float32) * (a_scale * b_scale)


def time_best(fn: Callable[[], Array], repeats: int) -> tuple[Array, float]:
    best_seconds = math.inf
    best_out = None
    for _ in range(repeats):
        start = time.perf_counter()
        out = fn()
        seconds = time.perf_counter() - start
        if seconds < best_seconds:
            best_seconds = seconds
            best_out = out
    assert best_out is not None
    return best_out, best_seconds


def count_ops(m: int, k: int, n: int) -> int:
    # One multiply and one add per inner-loop step.
    return 2 * m * k * n


def benchmark(
    name: str,
    fn: Callable[[], Array],
    reference: Array | None,
    ops: int,
    repeats: int,
) -> BenchResult:
    out, seconds = time_best(fn, repeats)
    gops = ops / seconds / 1e9

    if reference is None:
        return BenchResult(name=name, seconds=seconds, gops=gops)

    err = np.abs(out - reference)
    return BenchResult(
        name=name,
        seconds=seconds,
        gops=gops,
        max_abs_error=float(np.max(err)),
        mean_abs_error=float(np.mean(err)),
    )


def print_results(results: list[BenchResult]) -> None:
    print("\nResults")
    print("-" * 86)
    print(
        f"{'implementation':<28} {'time (ms)':>12} {'GOPS':>12} "
        f"{'max abs err':>14} {'mean abs err':>14}"
    )
    print("-" * 86)
    for r in results:
        max_err = "" if r.max_abs_error is None else f"{r.max_abs_error:.6g}"
        mean_err = "" if r.mean_abs_error is None else f"{r.mean_abs_error:.6g}"
        print(
            f"{r.name:<28} {r.seconds * 1e3:>12.3f} {r.gops:>12.3f} "
            f"{max_err:>14} {mean_err:>14}"
        )
    print("-" * 86)


def profile_naive(a: Array, b: Array) -> None:
    print("\ncProfile for naive Python matmul")
    print("-" * 86)
    profiler = cProfile.Profile()
    profiler.enable()
    matmul_naive_python(a, b)
    profiler.disable()
    stats = pstats.Stats(profiler).strip_dirs().sort_stats("cumtime")
    stats.print_stats(12)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--m", type=int, default=256)
    parser.add_argument("--k", type=int, default=256)
    parser.add_argument("--n", type=int, default=256)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument(
        "--naive-size",
        type=int,
        default=64,
        help="naive Python uses this smaller square size so it finishes quickly",
    )
    parser.add_argument("--profile", action="store_true")
    args = parser.parse_args()

    rng = np.random.default_rng(0)
    a = rng.normal(size=(args.m, args.k)).astype(np.float32)
    b = rng.normal(size=(args.k, args.n)).astype(np.float32)

    print(f"Benchmarking A={a.shape}, B={b.shape}, repeats={args.repeats}")
    ops = count_ops(args.m, args.k, args.n)

    reference, _ = time_best(lambda: matmul_numpy_float32(a, b), repeats=1)
    results = [
        benchmark(
            "numpy float32",
            lambda: matmul_numpy_float32(a, b),
            reference,
            ops,
            args.repeats,
        ),
        benchmark(
            "int8 quantized -> int32",
            lambda: matmul_quantized_int8(a, b),
            reference,
            ops,
            args.repeats,
        ),
    ]

    s = args.naive_size
    a_small = a[:s, :s].copy()
    b_small = b[:s, :s].copy()
    small_ref = a_small @ b_small
    results.append(
        benchmark(
            f"naive Python {s}x{s}",
            lambda: matmul_naive_python(a_small, b_small),
            small_ref,
            count_ops(s, s, s),
            repeats=1,
        )
    )

    print_results(results)

    print(
        "\nWhat to notice:\n"
        "1. Naive Python is dominated by interpreter overhead in the innermost loop.\n"
        "2. NumPy float32 is fast because it calls optimized BLAS kernels in native code.\n"
        "3. Quantized int8 usually has some error because many float values share one int8 bucket.\n"
        "4. This NumPy int8 path is an emulation, not a real TPU kernel. Real accelerators get speed\n"
        "   from specialized int8 multiply-accumulate datapaths, high memory bandwidth, and tiling.\n"
    )

    if args.profile:
        profile_naive(a_small, b_small)


if __name__ == "__main__":
    main()
