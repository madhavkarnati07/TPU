import numpy as np

from tpu_matmul import matmul, random_matrices


def test_numpy_float32_matches_reference():
    a, b = random_matrices(8, 16, 4, seed=1)
    result = matmul(a, b, backend="numpy", dtype_mode="float32", repeats=1, warmup=0)
    np.testing.assert_allclose(result.output, a @ b, rtol=1e-5, atol=1e-5)


def test_numpy_int8_has_right_shape_and_finite_values():
    a, b = random_matrices(8, 16, 4, seed=2)
    result = matmul(a, b, backend="numpy", dtype_mode="int8", repeats=1, warmup=0)
    assert result.output.shape == (8, 4)
    assert np.isfinite(result.output).all()
