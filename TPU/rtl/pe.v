`timescale 1ns / 1ps

module pe #(
    parameter DATA_WIDTH = 8,
    parameter DOT_PRODUCT_LENGTH = 256,
    parameter ACC_WIDTH = (2*DATA_WIDTH) + $clog2(DOT_PRODUCT_LENGTH)

) (
    input wire clk,
    input wire rst,
    input wire clear,
    input wire enable,
    input wire signed [DATA_WIDTH-1:0] a,
    input wire signed [DATA_WIDTH-1:0] b,
    output reg signed [ACC_WIDTH-1:0] acc
);
    wire signed [(2*DATA_WIDTH)-1:0] product;
    wire signed [ACC_WIDTH-1:0] product_ext;

    assign product = a * b;
    assign product_ext = product;

    always @(posedge clk) begin
        if (rst) begin
            acc <= {ACC_WIDTH{1'b0}};
        end else if (clear) begin
            acc <= {ACC_WIDTH{1'b0}};
        end else if (enable) begin
            acc <= acc + product_ext;
        end
    end
endmodule
