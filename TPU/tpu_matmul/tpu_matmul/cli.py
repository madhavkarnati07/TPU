from __future__ import annotations

import argparse

import numpy as np

from .core import available_devices, matmul, random_matrices


def main() -> None:
    parser = argparse.ArgumentParser(description="Matrix multiplication with TPU support via JAX")
    parser.add_argument("--m", type=int, default=1024)
    parser.add_argument("--k", type=int, default=1024)
    parser.add_argument("--n", type=int, default=1024)
    parser.add_argument("--backend", choices=["auto", "numpy", "jax"], default="auto")
    parser.add_argument("--device", choices=["auto", "cpu", "gpu", "tpu"], default="auto")
    parser.add_argument("--dtype", choices=["float32", "bfloat16", "int8"], default="float32")
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--list-devices", action="store_true")
    parser.add_argument("--check-error", action="store_true")
    args = parser.parse_args()

    if args.list_devices:
        print(available_devices())
        return

    a, b = random_matrices(args.m, args.k, args.n, seed=args.seed)
    result = matmul(
        a,
        b,
        backend=args.backend,
        device=args.device,
        dtype_mode=args.dtype,
        repeats=args.repeats,
        warmup=args.warmup,
    )

    print(f"backend:    {result.backend}")
    print(f"device:     {result.device}")
    print(f"dtype mode: {result.dtype_mode}")
    print(f"shape:      ({args.m}, {args.k}) x ({args.k}, {args.n})")
    print(f"time:       {result.seconds * 1e3:.3f} ms")
    print(f"throughput: {result.gops:.3f} GOPS")

    if args.check_error:
        out_np = np.asarray(result.output, dtype=np.float32)
        ref = a.astype(np.float32) @ b.astype(np.float32)
        err = np.abs(out_np - ref)
        print(f"max error:  {float(np.max(err)):.6g}")
        print(f"mean error: {float(np.mean(err)):.6g}")


if __name__ == "__main__":
    main()
