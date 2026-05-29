from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class QuantizedArray:
    values: np.ndarray
    scale: float


def symmetric_quantize_int8(x: np.ndarray) -> QuantizedArray:
    """Quantize a float matrix into signed int8 plus one shared scale."""
    x = np.asarray(x, dtype=np.float32)
    max_abs = float(np.max(np.abs(x))) if x.size else 0.0
    scale = max_abs / 127.0 if max_abs > 0.0 else 1.0
    values = np.round(x / scale).clip(-127, 127).astype(np.int8)
    return QuantizedArray(values=values, scale=scale)


def numpy_int8_matmul(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Correct int8 emulation: int8 inputs, int32 accumulation, float output."""
    qa = symmetric_quantize_int8(a)
    qb = symmetric_quantize_int8(b)
    acc = qa.values.astype(np.int32) @ qb.values.astype(np.int32)
    return acc.astype(np.float32) * (qa.scale * qb.scale)
