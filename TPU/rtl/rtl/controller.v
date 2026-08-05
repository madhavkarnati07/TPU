`timescale 1ns / 1ps

module controller (
    input wire clk,
    input wire rst,
    input wire start,
    input wire qkv_done,

    output reg qkv_start,
    output reg busy,
    output reg done,
    output reg [1:0] state
);
    localparam STATE_IDLE = 2'd0;
    localparam STATE_QKV = 2'd1;
    localparam STATE_DONE = 2'd2;

    always @(posedge clk) begin
        if (rst) begin
            state <= STATE_IDLE;
            qkv_start <= 1'b0;
            busy <= 1'b0;
            done <= 1'b0;
        end else begin
            qkv_start <= 1'b0;
            done <= 1'b0;

            case (state)
                STATE_IDLE: begin
                    busy <= 1'b0;

                    if (start) begin
                        qkv_start <= 1'b1;
                        busy <= 1'b1;
                        state <= STATE_QKV;
                    end
                end

                STATE_QKV: begin
                    busy <= 1'b1;

                    if (qkv_done) begin
                        state <= STATE_DONE;
                    end
                end

                STATE_DONE: begin
                    busy <= 1'b0;
                    done <= 1'b1;
                    state <= STATE_IDLE;
                end

                default: begin
                    state <= STATE_IDLE;
                    busy <= 1'b0;
                end
            endcase
        end
    end
endmodule
