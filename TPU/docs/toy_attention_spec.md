# Toy Attention TPU Specification

This file is the machine-visible contract shared by the Python model, RTL, and
testbench. The design implements one fixed, single-head attention operation.

## Tensor and arithmetic contract

| Item | Fixed value |
| --- | --- |
| Tokens | 4 |
| Input dimensions | 2 |
| Q/K/V dimensions | 2 |
| Operand format | signed int4, range `-8..7` |
| MAC accumulator | signed int16 |
| Parallel MAC lanes | 2 |
| Projection output | clamp to signed int4 |
| Score | raw `Q * K^T`, signed int16 |
| Attention approximation | `u[j] = max(0, 4 + score[j] - max(score))` |
| Denominator | `sum(u)`, integer range `4..16` |
| Reciprocal | unsigned Q0.8 LUT, `round(256 / denominator)` |
| Weighted-V numerator | signed int16 |
| Normalization | signed numerator times 8-bit reciprocal |
| Rounding | nearest integer, ties away from zero |
| Final output | clamp to signed int4 |

The computed operation is:

```text
Q = clamp_int4(X * Wq)
K = clamp_int4(X * Wk)
V = clamp_int4(X * Wv)

for each query row i:
    score[j] = dot(Q[i], K[j])
    u[j] = max(0, 4 + score[j] - max(score))
    denominator = sum(u)
    numerator[d] = sum(u[j] * V[j][d])
    reciprocal = round(256 / denominator)
    output[i][d] = clamp_int4(round_away(numerator[d] * reciprocal / 256))
```

## Packed tensor layout

Every 2D signed-int4 vector occupies one byte. Dimension 0 is the high nibble
and dimension 1 is the low nibble. Nibbles use four-bit two's complement.

`X`, `Q`, `K`, `V`, and the result are ordered by token. Each 2x2 weight matrix
is ordered by input row, one packed output row per byte:

```text
byte 0 = {matrix[0][0], matrix[0][1]}
byte 1 = {matrix[1][0], matrix[1][1]}
```

## Host byte protocol

An input byte transfers when `rx_valid && rx_ready` is high on a rising clock
edge. An output byte transfers when `tx_valid && tx_ready` is high. The chip
keeps output data stable while `tx_valid` is high and `tx_ready` is low.

| Command | Byte | Payload or response |
| --- | --- | --- |
| `LOAD_X` | `0x10` | 4 packed token bytes |
| `LOAD_WQ` | `0x11` | 2 packed weight bytes |
| `LOAD_WK` | `0x12` | 2 packed weight bytes |
| `LOAD_WV` | `0x13` | 2 packed weight bytes |
| `RUN_ATTENTION` | `0x20` | no payload |
| `READ_RESULT` | `0x30` | 4 packed result bytes |
| `READ_DEBUG` | `0x31` | 1 selector byte, then a response |
| `FLUSH` | `0xff` | invalidate stored data and clear status/loaded flags |

`RUN_ATTENTION` is accepted only after all four load commands complete. `done`
stays high after a completed run until another run or `FLUSH`.

### Debug selectors

| Selector | Response |
| --- | --- |
| `0x00` | status byte: bit 0 busy, bit 1 done, bit 2 protocol error |
| `0x01` | Q, 4 packed bytes |
| `0x02` | K, 4 packed bytes |
| `0x03` | V, 4 packed bytes |
| `0x04` | final query's four scores, signed int16 little-endian |
| `0x05` | final query's four `u` values, one byte each |
| `0x06` | final query's denominator, one byte |
| `0x07` | final query's two numerators, signed int16 little-endian |
| `0x08` | final query's reciprocal, one byte |

Selector `0x00` is always available. Selectors `0x01` through `0x08` require
`done=1`; requesting them earlier sets the protocol-error bit and returns no data.

Only one score/weight scratch row is retained. After a full run the scratch row
belongs to query token 3. This saves state compared with storing the 4x4 score
matrix.

## Tiny Tapeout pins

| Pin | Use |
| --- | --- |
| `ui_in[7:0]` | input command or payload byte |
| `uo_out[7:0]` | output response byte |
| `uio_in[0]` | `rx_valid` |
| `uio_in[1]` | `tx_ready` |
| `uio_out[4]` | `rx_ready` |
| `uio_out[5]` | `tx_valid` |
| `uio_out[6]` | `busy` |
| `uio_out[7]` | `done` |
| `uio_oe[7:0]` | `0xf0` |

The wrapper uses the exact Tiny Tapeout top-level interface. Deasserting `ena`
or `rst_n` resets the core.

## Execution schedule

The controller serializes phases and reuses the same two MAC lanes:

1. Project Q, K, and V. Both output dimensions run in parallel.
2. Compute one `Q * K^T` score at a time with lane 0.
3. Scan the four scores for the maximum.
4. Form four clipped-linear weights and their denominator.
5. Accumulate both weighted-V dimensions in parallel.
6. Normalize, round, saturate, and store one output token.
7. Repeat steps 2-6 for all four query tokens, then assert `done`.
