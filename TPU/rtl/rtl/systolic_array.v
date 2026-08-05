`timescale 1ns / 1ps

module systolic_array #(
    parameter DATA_WIDTH = 8,
    parameter ROWS = 4,
    parameter COLS = 4,
    parameter DOT_PRODUCT_LENGTH = 4,
    parameter ACC_WIDTH = (2*DATA_WIDTH) + $clog2(DOT_PRODUCT_LENGTH)
) (
    input wire clk,
    input wire rst,
    input wire clear,
    input wire enable,

    input wire signed [(ROWS*DATA_WIDTH)-1:0] a_in_flat,
    input wire signed [(COLS*DATA_WIDTH)-1:0] b_in_flat,

    output wire signed [(ROWS*COLS*ACC_WIDTH)-1:0] acc_out_flat
);
    wire signed [DATA_WIDTH-1:0] a_pipe [0:ROWS-1][0:COLS];
    wire signed [DATA_WIDTH-1:0] b_pipe [0:ROWS][0:COLS-1];
    wire signed [ACC_WIDTH-1:0] acc_pipe [0:ROWS-1][0:COLS-1];

    genvar r, c;

    generate
        for (r = 0; r < ROWS; r = r + 1) begin : A_INPUTS
            assign a_pipe[r][0] = a_in_flat[(r*DATA_WIDTH) +: DATA_WIDTH];
        end

        for (c = 0; c < COLS; c = c + 1) begin : B_INPUTS
            assign b_pipe[0][c] = b_in_flat[(c*DATA_WIDTH) +: DATA_WIDTH];
        end

        for (r = 0; r < ROWS; r = r + 1) begin : PE_ROWS
            for (c = 0; c < COLS; c = c + 1) begin : PE_COLS
                pe #(
                    .DATA_WIDTH(DATA_WIDTH),
                    .DOT_PRODUCT_LENGTH(DOT_PRODUCT_LENGTH),
                    .ACC_WIDTH(ACC_WIDTH)
                ) pe_inst (
                    .clk(clk),
                    .rst(rst),
                    .clear(clear),
                    .enable(enable),
                    .a(a_pipe[r][c]),
                    .b(b_pipe[r][c]),
                    .a_out(a_pipe[r][c+1]),
                    .b_out(b_pipe[r+1][c]),
                    .acc(acc_pipe[r][c])
                );

                assign acc_out_flat[((r*COLS + c)*ACC_WIDTH) +: ACC_WIDTH] = acc_pipe[r][c];
            end
        end
    endgenerate
endmodule
