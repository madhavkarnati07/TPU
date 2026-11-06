"""Exact integer golden model for the fixed toy-attention TPU."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


TOKENS = 4
DIM = 2
INT4_MIN = -8
INT4_MAX = 7
ATTENTION_BIAS = 4


@dataclass(frozen=True)
class AttentionTrace:
    x: np.ndarray
    wq: np.ndarray
    wk: np.ndarray
    wv: np.ndarray
    q: np.ndarray
    k: np.ndarray
    v: np.ndarray
    scores: np.ndarray
    weights: np.ndarray
    denominators: np.ndarray
    numerators: np.ndarray
    reciprocals_q08: np.ndarray
    output: np.ndarray


def _int_matrix(name: str, value, shape: tuple[int, int]) -> np.ndarray:
    matrix = np.asarray(value, dtype=np.int64)
    if matrix.shape != shape:
        raise ValueError(f"{name} must have shape {shape}, got {matrix.shape}")
    if np.any(matrix < INT4_MIN) or np.any(matrix > INT4_MAX):
        raise ValueError(f"{name} contains a value outside signed int4")
    return matrix


def clamp_int4(value):
    """Clamp a scalar or NumPy array to the signed-int4 range."""
    return np.clip(value, INT4_MIN, INT4_MAX).astype(np.int64)


def reciprocal_q08(denominator: int) -> int:
    """Return round(256 / denominator) using positive integer arithmetic."""
    if not 4 <= denominator <= 16:
        raise ValueError(f"attention denominator must be in 4..16, got {denominator}")
    return (256 + denominator // 2) // denominator


def round_q08_product(product: int) -> int:
    """Divide a signed Q0.8 product by 256, with ties away from zero."""
    magnitude = abs(int(product))
    rounded = (magnitude + 128) // 256
    return rounded if product >= 0 else -rounded


def pack_int4_pair(dim0: int, dim1: int) -> int:
    if not INT4_MIN <= dim0 <= INT4_MAX or not INT4_MIN <= dim1 <= INT4_MAX:
        raise ValueError("packed values must fit signed int4")
    return ((dim0 & 0xF) << 4) | (dim1 & 0xF)


def unpack_int4_pair(byte: int) -> tuple[int, int]:
    def signed_nibble(nibble: int) -> int:
        return nibble if nibble < 8 else nibble - 16

    return signed_nibble((byte >> 4) & 0xF), signed_nibble(byte & 0xF)


def pack_rows(matrix: np.ndarray) -> list[int]:
    return [pack_int4_pair(int(row[0]), int(row[1])) for row in matrix]


def attention(
    x,
    wq,
    wk,
    wv,
) -> AttentionTrace:
    """Compute the exact fixed-shape operation implemented by the RTL."""
    x = _int_matrix("x", x, (TOKENS, DIM))
    wq = _int_matrix("wq", wq, (DIM, DIM))
    wk = _int_matrix("wk", wk, (DIM, DIM))
    wv = _int_matrix("wv", wv, (DIM, DIM))

    q = clamp_int4(x @ wq)
    k = clamp_int4(x @ wk)
    v = clamp_int4(x @ wv)
    scores = q @ k.T

    row_max = np.max(scores, axis=1, keepdims=True)
    weights = np.maximum(0, ATTENTION_BIAS + scores - row_max).astype(np.int64)
    denominators = np.sum(weights, axis=1, dtype=np.int64)
    if np.any(denominators < 4) or np.any(denominators > 16):
        raise AssertionError("clipped-linear denominator escaped its 4..16 bound")

    numerators = weights @ v
    reciprocals = np.asarray(
        [reciprocal_q08(int(value)) for value in denominators], dtype=np.int64
    )
    normalized = np.empty((TOKENS, DIM), dtype=np.int64)
    for row in range(TOKENS):
        for dim in range(DIM):
            product = int(numerators[row, dim]) * int(reciprocals[row])
            normalized[row, dim] = round_q08_product(product)

    output = clamp_int4(normalized)
    return AttentionTrace(
        x=x,
        wq=wq,
        wk=wk,
        wv=wv,
        q=q,
        k=k,
        v=v,
        scores=scores,
        weights=weights,
        denominators=denominators,
        numerators=numerators,
        reciprocals_q08=reciprocals,
        output=output,
    )


def reference_case() -> AttentionTrace:
    return attention(
        x=[[1, 0], [0, 1], [1, 1], [-1, 1]],
        wq=[[1, 0], [0, 1]],
        wk=[[1, 0], [0, 1]],
        wv=[[1, 0], [0, 2]],
    )


def stress_case() -> AttentionTrace:
    """Exercise negative int4 values, projection saturation, and signed rounding."""
    return attention(
        x=[[-8, 7], [7, -8], [3, -2], [-4, -5]],
        wq=[[7, -8], [-8, 7]],
        wk=[[-3, 2], [5, -6]],
        wv=[[2, -3], [-4, 5]],
    )


def _print_matrix(name: str, matrix: np.ndarray) -> None:
    print(f"\n{name}:")
    for row in matrix:
        print("  [" + ", ".join(f"{int(value):4d}" for value in row) + "]")


def main() -> None:
    trace = reference_case()
    for name in ("x", "wq", "wk", "wv", "q", "k", "v", "scores", "weights"):
        _print_matrix(name.upper(), getattr(trace, name))
    _print_matrix("Weighted-V numerators", trace.numerators)
    print("\nDenominators:", trace.denominators.tolist())
    print("Reciprocal Q0.8:", trace.reciprocals_q08.tolist())
    _print_matrix("Final int4 output", trace.output)
    print("Packed result bytes:", " ".join(f"{byte:02x}" for byte in pack_rows(trace.output)))


if __name__ == "__main__":
    main()
