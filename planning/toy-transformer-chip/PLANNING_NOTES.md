# Toy Transformer Chip Design Record

The planning roadmap is complete for the first fixed-shape implementation. The
HTML pages remain as an educational record of the choices, control flow, and
physical result.

## Implemented Direction

- Four tokens, two dimensions, and one attention head.
- Signed int4 operands packed two per byte.
- Two reusable MAC lanes with signed int16 accumulation.
- On-chip Q/K/V projection from host-loaded X, Wq, Wk, and Wv.
- Raw QK^T scores, clipped-linear weights with B = 4, and Q0.8 reciprocal normalization.
- Round-to-nearest with ties away from zero and signed-int4 saturation.
- READ_RESULT, READ_DEBUG, FLUSH, ready/valid handshakes, busy, and done.

## Completed Roadmap

1. Prerequisite study: matmul, dot products, one-head attention, and softmax purpose.
2. Exact Python/NumPy golden model and reference traces.
3. High-level architecture, state budget, protocol, and two-MAC schedule.
4. RTL implementation and controller FSM.
5. Source RTL and powered gate-level verification.
6. Tiny Tapeout 2x2 hardening, submission packaging, and precheck.

## Release Work

The remaining work is operational: review non-fatal max-slew warnings, freeze
the release commit, run the official Tiny Tapeout cloud workflow, and submit to
a selected shuttle.
