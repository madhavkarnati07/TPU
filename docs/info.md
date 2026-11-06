## How it works

This chip computes one fixed single-head attention operation over four 2D
tokens. Inputs and Q/K/V weights are signed int4. Two MAC lanes compute both
projection dimensions together, then the controller reuses them for serialized
`Q * K^T` scores and parallel weighted-V accumulation.

Instead of exponential softmax, each score row uses:

```text
u[j] = max(0, 4 + score[j] - max(score))
```

The four weights are normalized with a Q0.8 reciprocal lookup table. Results
are rounded to nearest with ties away from zero and saturated to signed int4.

## How to test

`ui_in` carries commands and payload bytes. Pulse `uio_in[0]` when
`uio_out[4]` is high to transfer each input byte. `uo_out` carries response
bytes; assert `uio_in[1]` to accept a byte while `uio_out[5]` is high.

Load commands are `0x10` for four packed X bytes, then `0x11`, `0x12`, and
`0x13` for two packed Wq, Wk, and Wv bytes each. Send `0x20` to run. When
`uio_out[7]` becomes high, send `0x30` and read four packed result bytes.
Within each packed byte, vector dimension 0 is the high signed-int4 nibble and
dimension 1 is the low nibble.

Send `0x31` followed by a selector from `0x00` through `0x08` to inspect status,
Q, K, V, final-row scores, clipped weights, denominator, numerators, or the
reciprocal. Send `0xff` to clear the transaction state.

## External hardware

No external hardware is required. A Tiny Tapeout demoboard or any synchronous
host capable of driving the byte handshake can operate the design.
