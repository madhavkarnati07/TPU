import numpy as np
import pytest

from toy_attention import (
    attention,
    pack_int4_pair,
    pack_rows,
    reciprocal_q08,
    reference_case,
    round_q08_product,
    unpack_int4_pair,
)


def test_reference_trace_is_exact():
    trace = reference_case()

    np.testing.assert_array_equal(trace.q, [[1, 0], [0, 1], [1, 1], [-1, 1]])
    np.testing.assert_array_equal(trace.k, trace.q)
    np.testing.assert_array_equal(trace.v, [[1, 0], [0, 2], [1, 2], [-1, 2]])
    np.testing.assert_array_equal(
        trace.scores,
        [[1, 0, 1, -1], [0, 1, 1, 1], [1, 1, 2, 0], [-1, 1, 0, 2]],
    )
    np.testing.assert_array_equal(
        trace.weights,
        [[4, 3, 4, 2], [3, 4, 4, 4], [3, 3, 4, 2], [1, 3, 2, 4]],
    )
    np.testing.assert_array_equal(trace.denominators, [13, 15, 12, 10])
    np.testing.assert_array_equal(trace.numerators, [[6, 18], [3, 24], [5, 18], [-1, 18]])
    np.testing.assert_array_equal(trace.reciprocals_q08, [20, 17, 21, 26])
    np.testing.assert_array_equal(trace.output, [[0, 1], [0, 2], [0, 1], [0, 2]])
    assert pack_rows(trace.output) == [0x01, 0x02, 0x01, 0x02]


def test_int4_byte_layout_round_trips_all_values():
    for dim0 in range(-8, 8):
        for dim1 in range(-8, 8):
            assert unpack_int4_pair(pack_int4_pair(dim0, dim1)) == (dim0, dim1)


def test_reciprocal_lut_values():
    assert [reciprocal_q08(value) for value in range(4, 17)] == [
        64,
        51,
        43,
        37,
        32,
        28,
        26,
        23,
        21,
        20,
        18,
        17,
        16,
    ]


@pytest.mark.parametrize(
    ("product", "expected"),
    [(127, 0), (128, 1), (383, 1), (384, 2), (-127, 0), (-128, -1), (-384, -2)],
)
def test_q08_rounding_is_symmetric(product, expected):
    assert round_q08_product(product) == expected


def test_projection_outputs_saturate_to_int4():
    trace = attention(
        x=[[7, 7], [-8, -8], [7, -8], [-8, 7]],
        wq=[[7, 7], [7, 7]],
        wk=[[7, 7], [7, 7]],
        wv=[[7, 7], [7, 7]],
    )
    assert np.all(trace.q >= -8) and np.all(trace.q <= 7)
    assert 7 in trace.q
    assert -8 in trace.q


def test_model_rejects_non_int4_inputs():
    with pytest.raises(ValueError, match="outside signed int4"):
        attention(
            x=[[8, 0], [0, 0], [0, 0], [0, 0]],
            wq=[[1, 0], [0, 1]],
            wk=[[1, 0], [0, 1]],
            wv=[[1, 0], [0, 1]],
        )
