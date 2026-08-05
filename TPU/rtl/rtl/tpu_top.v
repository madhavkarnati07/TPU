`timescale 1ns / 1ps

module tpu_top #(
    parameter DATA_WIDTH = 8,
    parameter HIDDEN_DIM = 4,
    parameter HEAD_DIM = 4,
    parameter ACC_WIDTH = (2*DATA_WIDTH) + $clog2(HIDDEN_DIM)
) (
    input wire clk,
    input wire rst,
    input wire start,

    input wire signed [(HIDDEN_DIM*DATA_WIDTH)-1:0] x_flat,
    input wire signed [(HIDDEN_DIM*HEAD_DIM*DATA_WIDTH)-1:0] wq_flat,
    input wire signed [(HIDDEN_DIM*HEAD_DIM*DATA_WIDTH)-1:0] wk_flat,
    input wire signed [(HIDDEN_DIM*HEAD_DIM*DATA_WIDTH)-1:0] wv_flat,

    output wire signed [(HEAD_DIM*ACC_WIDTH)-1:0] q_flat,
    output wire signed [(HEAD_DIM*ACC_WIDTH)-1:0] k_flat,
    output wire signed [(HEAD_DIM*ACC_WIDTH)-1:0] v_flat,
    output wire busy,
    output wire done
);
    wire qkv_start;
    wire qkv_busy;
    wire qkv_done;
    wire [1:0] controller_state;

    controller controller_inst (
        .clk(clk),
        .rst(rst),
        .start(start),
        .qkv_done(qkv_done),
        .qkv_start(qkv_start),
        .busy(busy),
        .done(done),
        .state(controller_state)
    );

    qkv_projection #(
        .DATA_WIDTH(DATA_WIDTH),
        .HIDDEN_DIM(HIDDEN_DIM),
        .HEAD_DIM(HEAD_DIM),
        .ACC_WIDTH(ACC_WIDTH)
    ) qkv_projection_inst (
        .clk(clk),
        .rst(rst),
        .start(qkv_start),
        .x_flat(x_flat),
        .wq_flat(wq_flat),
        .wk_flat(wk_flat),
        .wv_flat(wv_flat),
        .q_flat(q_flat),
        .k_flat(k_flat),
        .v_flat(v_flat),
        .busy(qkv_busy),
        .done(qkv_done)
    );
endmodule
