`timescale 1ns / 1ps

module tb_toy_attention;
    localparam [7:0] CMD_LOAD_X        = 8'h10;
    localparam [7:0] CMD_LOAD_WQ       = 8'h11;
    localparam [7:0] CMD_LOAD_WK       = 8'h12;
    localparam [7:0] CMD_LOAD_WV       = 8'h13;
    localparam [7:0] CMD_RUN_ATTENTION = 8'h20;
    localparam [7:0] CMD_READ_RESULT   = 8'h30;
    localparam [7:0] CMD_READ_DEBUG    = 8'h31;
    localparam [7:0] CMD_FLUSH         = 8'hff;

    localparam integer EXPECT_RESULT      = 0;
    localparam integer EXPECT_Q           = 1;
    localparam integer EXPECT_K           = 2;
    localparam integer EXPECT_V           = 3;
    localparam integer EXPECT_SCORES      = 4;
    localparam integer EXPECT_WEIGHTS     = 5;
    localparam integer EXPECT_DENOMINATOR = 6;
    localparam integer EXPECT_NUMERATORS  = 7;
    localparam integer EXPECT_RECIPROCAL  = 8;

    reg clk;
    reg rst_n;
    reg ena;
    reg [7:0] ui_in;
    wire [7:0] uo_out;
    reg [7:0] uio_in;
    wire [7:0] uio_out;
    wire [7:0] uio_oe;

    integer case_index;
    integer cycles_waited;

    `include "attention_vectors.vh"

    tt_um_madhavkarnati_toy_tpu dut (
        .ui_in(ui_in),
        .uo_out(uo_out),
        .uio_in(uio_in),
        .uio_out(uio_out),
        .uio_oe(uio_oe),
        .ena(ena),
        .clk(clk),
        .rst_n(rst_n)
    );

    initial begin
        clk = 1'b0;
        forever #5 clk = ~clk;
    end

    function [7:0] expected_byte;
        input integer kind;
        input integer index;
        begin
            case (kind)
                EXPECT_RESULT:      expected_byte = golden_result[index];
                EXPECT_Q:           expected_byte = golden_q[index];
                EXPECT_K:           expected_byte = golden_k[index];
                EXPECT_V:           expected_byte = golden_v[index];
                EXPECT_SCORES:      expected_byte = golden_scores[index];
                EXPECT_WEIGHTS:     expected_byte = golden_weights[index];
                EXPECT_DENOMINATOR: expected_byte = golden_denominator[index];
                EXPECT_NUMERATORS:  expected_byte = golden_numerators[index];
                EXPECT_RECIPROCAL:  expected_byte = golden_reciprocal[index];
                default:            expected_byte = 8'hxx;
            endcase
        end
    endfunction

    task send_byte;
        input [7:0] value;
        begin
            cycles_waited = 0;
            while (uio_out[4] !== 1'b1) begin
                @(negedge clk);
                cycles_waited = cycles_waited + 1;
                if (cycles_waited > 1000)
                    $fatal(1, "Timed out waiting for rx_ready");
            end
            ui_in = value;
            uio_in[0] = 1'b1;
            @(negedge clk);
            uio_in[0] = 1'b0;
        end
    endtask

    task receive_stream;
        input integer kind;
        input integer base;
        input integer length;
        integer byte_index;
        reg [7:0] expected;
        begin
            for (byte_index = 0; byte_index < length; byte_index = byte_index + 1) begin
                cycles_waited = 0;
                while (uio_out[5] !== 1'b1) begin
                    @(negedge clk);
                    cycles_waited = cycles_waited + 1;
                    if (cycles_waited > 1000)
                        $fatal(1, "Timed out waiting for tx_valid");
                end
                expected = expected_byte(kind, base + byte_index);
                if (uo_out !== expected)
                    $fatal(
                        1,
                        "Response mismatch case=%0d kind=%0d byte=%0d expected=%02x got=%02x",
                        case_index,
                        kind,
                        byte_index,
                        expected,
                        uo_out
                    );
                uio_in[1] = 1'b1;
                @(negedge clk);
                uio_in[1] = 1'b0;
            end
        end
    endtask

    task load_case;
        input integer selected_case;
        integer base;
        integer index;
        begin
            base = selected_case * 10;
            send_byte(CMD_LOAD_X);
            for (index = 0; index < 4; index = index + 1)
                send_byte(golden_stimulus[base + index]);

            send_byte(CMD_LOAD_WQ);
            for (index = 0; index < 2; index = index + 1)
                send_byte(golden_stimulus[base + 4 + index]);

            send_byte(CMD_LOAD_WK);
            for (index = 0; index < 2; index = index + 1)
                send_byte(golden_stimulus[base + 6 + index]);

            send_byte(CMD_LOAD_WV);
            for (index = 0; index < 2; index = index + 1)
                send_byte(golden_stimulus[base + 8 + index]);
        end
    endtask

    task read_debug;
        input [7:0] selector;
        input integer kind;
        input integer base;
        input integer length;
        begin
            send_byte(CMD_READ_DEBUG);
            send_byte(selector);
            receive_stream(kind, base, length);
        end
    endtask

    initial begin
        $dumpfile("build/toy_attention.vcd");
        $dumpvars(0, tb_toy_attention);

        rst_n = 1'b0;
        ena = 1'b1;
        ui_in = 8'h00;
        uio_in = 8'h00;

        repeat (3) @(negedge clk);
        rst_n = 1'b1;
        @(negedge clk);

        if (uio_oe !== 8'hf0)
            $fatal(1, "Tiny Tapeout uio_oe must be f0, got %02x", uio_oe);

        for (case_index = 0; case_index < NUM_CASES; case_index = case_index + 1) begin
            load_case(case_index);
            send_byte(CMD_RUN_ATTENTION);

            cycles_waited = 0;
            while (uio_out[7] !== 1'b1) begin
                @(negedge clk);
                cycles_waited = cycles_waited + 1;
                if (cycles_waited > 1000)
                    $fatal(1, "Timed out waiting for attention completion");
            end

            send_byte(CMD_READ_RESULT);
            receive_stream(EXPECT_RESULT, case_index * 4, 4);
            read_debug(8'h01, EXPECT_Q, case_index * 4, 4);
            read_debug(8'h02, EXPECT_K, case_index * 4, 4);
            read_debug(8'h03, EXPECT_V, case_index * 4, 4);
            read_debug(8'h04, EXPECT_SCORES, case_index * 8, 8);
            read_debug(8'h05, EXPECT_WEIGHTS, case_index * 4, 4);
            read_debug(8'h06, EXPECT_DENOMINATOR, case_index, 1);
            read_debug(8'h07, EXPECT_NUMERATORS, case_index * 4, 4);
            read_debug(8'h08, EXPECT_RECIPROCAL, case_index, 1);

            send_byte(CMD_FLUSH);
            if (uio_out[7] !== 1'b0)
                $fatal(1, "FLUSH did not clear done");
        end

        $display(
            "PASS: %0d Tiny Tapeout attention transactions matched Python golden traces.",
            NUM_CASES
        );
        $finish;
    end
endmodule
