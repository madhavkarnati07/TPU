module tt_um_madhavkarnati_toy_tpu #(
    parameter integer MAC_LANES = 2
) (
    input  wire [7:0] ui_in,
    output wire [7:0] uo_out,
    input  wire [7:0] uio_in,
    output wire [7:0] uio_out,
    output wire [7:0] uio_oe,
    input  wire       ena,
    input  wire       clk,
    input  wire       rst_n
);
    wire rx_ready;
    wire tx_valid;
    wire [7:0] tx_data;
    wire busy;
    wire done;
    wire core_reset;

    assign core_reset = !rst_n || !ena;
    assign uo_out = tx_data;
    assign uio_out = {done, busy, tx_valid, rx_ready, 4'b0000};
    assign uio_oe = 8'hf0;

    toy_attention_core #(
        .MAC_LANES(MAC_LANES)
    ) core (
        .clk(clk),
        .rst(core_reset),
        .rx_valid(uio_in[0]),
        .rx_data(ui_in),
        .rx_ready(rx_ready),
        .tx_ready(uio_in[1]),
        .tx_valid(tx_valid),
        .tx_data(tx_data),
        .busy(busy),
        .done(done)
    );

    wire _unused = &{uio_in[7:2], 1'b0};
endmodule
