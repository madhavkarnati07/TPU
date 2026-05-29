`timescale 1ns / 1ps

module tb_pe;
    localparam DATA_WIDTH = 8;
    localparam ACC_WIDTH = 32;

    reg clk;
    reg rst;
    reg clear;
    reg enable;
    reg signed [DATA_WIDTH-1:0] a;
    reg signed [DATA_WIDTH-1:0] b;
    wire signed [ACC_WIDTH-1:0] acc;

    integer i;

    pe #(
        .DATA_WIDTH(DATA_WIDTH),
        .ACC_WIDTH(ACC_WIDTH)
    ) dut (
        .clk(clk),
        .rst(rst),
        .clear(clear),
        .enable(enable),
        .a(a),
        .b(b),
        .acc(acc)
    );

    initial begin
        clk = 1'b0;
        forever #5 clk = ~clk;
    end

    task expect_acc;
        input signed [ACC_WIDTH-1:0] expected;
        begin
            if (acc !== expected) begin
                $display("FAIL at time %0t: expected acc=%0d, got acc=%0d", $time, expected, acc);
                $finish;
            end
        end
    endtask

    task mac_step;
        input signed [DATA_WIDTH-1:0] next_a;
        input signed [DATA_WIDTH-1:0] next_b;
        begin
            a = next_a;
            b = next_b;
            enable = 1'b1;
            clear = 1'b0;
            @(posedge clk);
            #1;
        end
    endtask

    initial begin
        $dumpfile("build/pe.vcd");
        $dumpvars(0, tb_pe);

        rst = 1'b1;
        clear = 1'b0;
        enable = 1'b0;
        a = 0;
        b = 0;

        repeat (2) @(posedge clk);
        #1;
        expect_acc(0);

        rst = 1'b0;

        mac_step(3, 4);
        expect_acc(12);

        mac_step(-2, 5);
        expect_acc(2);

        clear = 1'b1;
        enable = 1'b0;
        @(posedge clk);
        #1;
        expect_acc(0);
        clear = 1'b0;

        mac_step(-7, -6);
        expect_acc(42);

        a = 8;
        b = 8;
        enable = 1'b0;
        @(posedge clk);
        #1;
        expect_acc(42);

        clear = 1'b1;
        @(posedge clk);
        #1;
        clear = 1'b0;
        expect_acc(0);

        for (i = 0; i < 10; i = i + 1) begin
            mac_step(1, 2);
        end
        expect_acc(20);

        $display("PASS: PE multiply-accumulate simulation completed successfully.");
        $finish;
    end
endmodule
