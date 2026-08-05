`timescale 1ns / 1ps

module matmul_engine #(
    parameter DATA_WIDTH = 8,
    parameter M = 4,
    parameter K = 4,
    parameter N = 4,
    parameter ACC_WIDTH = (2*DATA_WIDTH) + $clog2(K)
) (
    input wire clk,
    input wire rst,
    input wire start,

    input wire signed [(M*K*DATA_WIDTH)-1:0] a_flat,
    input wire signed [(K*N*DATA_WIDTH)-1:0] b_flat,

    output reg signed [(M*N*ACC_WIDTH)-1:0] c_flat,
    output reg busy,
    output reg done
);
    localparam M_IDX_WIDTH = (M <= 1) ? 1 : $clog2(M);
    localparam K_IDX_WIDTH = (K <= 1) ? 1 : $clog2(K);
    localparam N_IDX_WIDTH = (N <= 1) ? 1 : $clog2(N);

    reg [M_IDX_WIDTH-1:0] row;
    reg [K_IDX_WIDTH-1:0] k_idx;
    reg [N_IDX_WIDTH-1:0] col;
    reg signed [ACC_WIDTH-1:0] acc;

    wire signed [DATA_WIDTH-1:0] a_value;
    wire signed [DATA_WIDTH-1:0] b_value;
    wire signed [(2*DATA_WIDTH)-1:0] product;
    wire signed [ACC_WIDTH-1:0] product_ext;
    wire signed [ACC_WIDTH-1:0] mac_sum;

    assign a_value = a_flat[((row*K + k_idx)*DATA_WIDTH) +: DATA_WIDTH];
    assign b_value = b_flat[((k_idx*N + col)*DATA_WIDTH) +: DATA_WIDTH];
    assign product = a_value * b_value;
    assign product_ext = product;
    assign mac_sum = acc + product_ext;

    always @(posedge clk) begin
        if (rst) begin
            row <= {M_IDX_WIDTH{1'b0}};
            k_idx <= {K_IDX_WIDTH{1'b0}};
            col <= {N_IDX_WIDTH{1'b0}};
            acc <= {ACC_WIDTH{1'b0}};
            c_flat <= {(M*N*ACC_WIDTH){1'b0}};
            busy <= 1'b0;
            done <= 1'b0;
        end else begin
            done <= 1'b0;

            if (start && !busy) begin
                row <= {M_IDX_WIDTH{1'b0}};
                k_idx <= {K_IDX_WIDTH{1'b0}};
                col <= {N_IDX_WIDTH{1'b0}};
                acc <= {ACC_WIDTH{1'b0}};
                c_flat <= {(M*N*ACC_WIDTH){1'b0}};
                busy <= 1'b1;
            end else if (busy) begin
                if (k_idx == K-1) begin
                    c_flat[((row*N + col)*ACC_WIDTH) +: ACC_WIDTH] <= mac_sum;
                    acc <= {ACC_WIDTH{1'b0}};
                    k_idx <= {K_IDX_WIDTH{1'b0}};

                    if (col == N-1) begin
                        col <= {N_IDX_WIDTH{1'b0}};

                        if (row == M-1) begin
                            row <= {M_IDX_WIDTH{1'b0}};
                            busy <= 1'b0;
                            done <= 1'b1;
                        end else begin
                            row <= row + 1'b1;
                        end
                    end else begin
                        col <= col + 1'b1;
                    end
                end else begin
                    acc <= mac_sum;
                    k_idx <= k_idx + 1'b1;
                end
            end
        end
    end
endmodule
