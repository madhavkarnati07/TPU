`timescale 1ns / 1ps

module qkv_projection #(
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

    output reg signed [(HEAD_DIM*ACC_WIDTH)-1:0] q_flat,
    output reg signed [(HEAD_DIM*ACC_WIDTH)-1:0] k_flat,
    output reg signed [(HEAD_DIM*ACC_WIDTH)-1:0] v_flat,
    output reg busy,
    output reg done
);
    localparam PHASE_Q = 2'd0;
    localparam PHASE_K = 2'd1;
    localparam PHASE_V = 2'd2;
    localparam IN_IDX_WIDTH = (HIDDEN_DIM <= 1) ? 1 : $clog2(HIDDEN_DIM);
    localparam OUT_IDX_WIDTH = (HEAD_DIM <= 1) ? 1 : $clog2(HEAD_DIM);

    reg [1:0] phase;
    reg [IN_IDX_WIDTH-1:0] in_idx;
    reg [OUT_IDX_WIDTH-1:0] out_idx;
    reg signed [ACC_WIDTH-1:0] acc;

    wire signed [DATA_WIDTH-1:0] x_value;
    wire signed [DATA_WIDTH-1:0] wq_value;
    wire signed [DATA_WIDTH-1:0] wk_value;
    wire signed [DATA_WIDTH-1:0] wv_value;
    wire signed [DATA_WIDTH-1:0] weight_value;
    wire signed [(2*DATA_WIDTH)-1:0] product;
    wire signed [ACC_WIDTH-1:0] product_ext;
    wire signed [ACC_WIDTH-1:0] mac_sum;

    assign x_value = x_flat[(in_idx*DATA_WIDTH) +: DATA_WIDTH];
    assign wq_value = wq_flat[((in_idx*HEAD_DIM + out_idx)*DATA_WIDTH) +: DATA_WIDTH];
    assign wk_value = wk_flat[((in_idx*HEAD_DIM + out_idx)*DATA_WIDTH) +: DATA_WIDTH];
    assign wv_value = wv_flat[((in_idx*HEAD_DIM + out_idx)*DATA_WIDTH) +: DATA_WIDTH];
    assign weight_value = (phase == PHASE_Q) ? wq_value :
                          (phase == PHASE_K) ? wk_value :
                                                wv_value;
    assign product = x_value * weight_value;
    assign product_ext = product;
    assign mac_sum = acc + product_ext;

    always @(posedge clk) begin
        if (rst) begin
            phase <= PHASE_Q;
            in_idx <= {IN_IDX_WIDTH{1'b0}};
            out_idx <= {OUT_IDX_WIDTH{1'b0}};
            acc <= {ACC_WIDTH{1'b0}};
            q_flat <= {(HEAD_DIM*ACC_WIDTH){1'b0}};
            k_flat <= {(HEAD_DIM*ACC_WIDTH){1'b0}};
            v_flat <= {(HEAD_DIM*ACC_WIDTH){1'b0}};
            busy <= 1'b0;
            done <= 1'b0;
        end else begin
            done <= 1'b0;

            if (start && !busy) begin
                phase <= PHASE_Q;
                in_idx <= {IN_IDX_WIDTH{1'b0}};
                out_idx <= {OUT_IDX_WIDTH{1'b0}};
                acc <= {ACC_WIDTH{1'b0}};
                q_flat <= {(HEAD_DIM*ACC_WIDTH){1'b0}};
                k_flat <= {(HEAD_DIM*ACC_WIDTH){1'b0}};
                v_flat <= {(HEAD_DIM*ACC_WIDTH){1'b0}};
                busy <= 1'b1;
            end else if (busy) begin
                if (in_idx == HIDDEN_DIM-1) begin
                    if (phase == PHASE_Q) begin
                        q_flat[(out_idx*ACC_WIDTH) +: ACC_WIDTH] <= mac_sum;
                    end else if (phase == PHASE_K) begin
                        k_flat[(out_idx*ACC_WIDTH) +: ACC_WIDTH] <= mac_sum;
                    end else begin
                        v_flat[(out_idx*ACC_WIDTH) +: ACC_WIDTH] <= mac_sum;
                    end

                    acc <= {ACC_WIDTH{1'b0}};
                    in_idx <= {IN_IDX_WIDTH{1'b0}};

                    if (out_idx == HEAD_DIM-1) begin
                        out_idx <= {OUT_IDX_WIDTH{1'b0}};

                        if (phase == PHASE_V) begin
                            phase <= PHASE_Q;
                            busy <= 1'b0;
                            done <= 1'b1;
                        end else begin
                            phase <= phase + 1'b1;
                        end
                    end else begin
                        out_idx <= out_idx + 1'b1;
                    end
                end else begin
                    acc <= mac_sum;
                    in_idx <= in_idx + 1'b1;
                end
            end
        end
    end
endmodule
