"""Fixed warm-inference inputs backed by the repository's golden model."""

from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "TPU"))

from toy_attention import attention, pack_rows  # noqa: E402


FIXED_WEIGHTS = {
    "wq": ((1, 0), (0, 1)),
    "wk": ((1, 0), (0, 1)),
    "wv": ((1, 0), (0, 2)),
}

# These cases deliberately exercise zeros, signed values, saturation, and
# different clipped-linear attention denominators while keeping the workload
# fixed across every architecture experiment.
WARM_INPUTS = (
    ((1, 0), (0, 1), (1, 1), (-1, 1)),
    ((0, 0), (0, 0), (0, 0), (0, 0)),
    ((1, 0), (0, 1), (-1, 0), (0, -1)),
    ((1, 2), (2, 1), (-1, 2), (2, -1)),
    ((3, 0), (0, 3), (-3, 0), (0, -3)),
    ((7, 7), (-8, -8), (7, -8), (-8, 7)),
    ((-8, 7), (7, -8), (3, -2), (-4, -5)),
    ((2, -3), (-1, 4), (5, 0), (-6, 1)),
    ((7, 0), (0, 7), (-8, 0), (0, -8)),
    ((4, 4), (4, -4), (-4, 4), (-4, -4)),
    ((1, 1), (1, 1), (1, 1), (1, 1)),
    ((2, 2), (-2, -2), (2, -2), (-2, 2)),
    ((6, -1), (-5, 2), (3, -7), (-4, 5)),
    ((0, 7), (7, 0), (0, -8), (-8, 0)),
    ((5, 1), (1, 5), (-5, -1), (-1, -5)),
    ((7, -7), (-7, 7), (6, -6), (-6, 6)),
)

assert len(WARM_INPUTS) == 16


def golden_case(index: int) -> dict:
    """Return packed stimulus and exact expected output for one warm input."""
    x = WARM_INPUTS[index]
    trace = attention(x, **FIXED_WEIGHTS)
    return {
        "index": index,
        "x": [list(row) for row in x],
        "x_packed": pack_rows(trace.x),
        "expected_output": trace.output.astype(int).tolist(),
        "expected_result_bytes": pack_rows(trace.output),
    }


def packed_weights() -> dict[str, list[int]]:
    """Pack the fixed resident matrices with the canonical model helper."""
    return {
        name: pack_rows(matrix)
        for name, matrix in FIXED_WEIGHTS.items()
    }
