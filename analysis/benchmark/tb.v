`default_nettype none
`timescale 1ns / 1ps

module tb #(
    parameter integer MAC_LANES = 2
) ();
    reg clk;
    reg rst_n;
    reg ena;
    reg [7:0] ui_in;
    reg [7:0] uio_in;
    wire [7:0] uo_out;
    wire [7:0] uio_out;
    wire [7:0] uio_oe;
    reg [1023:0] waveform_path;
    reg power_capture_start;
    reg power_capture_active;

`ifdef GL_TEST
    wire VPWR = 1'b1;
    wire VGND = 1'b0;
`endif

    initial begin
        if (!$value$plusargs("WAVEFORM=%s", waveform_path))
            waveform_path = "warm_benchmark.vcd";
        power_capture_active = 1'b0;
    end

    // Cocotb asserts start before the first warm LOAD_X acceptance edge.
    // It ends the simulation at the declared stop edge, which lets Icarus
    // close the VCD cleanly without $dumpoff's terminal X transitions.
    always @(posedge clk) begin
        if (power_capture_start && !power_capture_active) begin
            $dumpfile(waveform_path);
            $dumpvars(0, tb);
            power_capture_active <= 1'b1;
        end
    end

    tt_um_madhavkarnati_toy_tpu
`ifndef GL_TEST
    #(.MAC_LANES(MAC_LANES))
`endif
    user_project (
`ifdef GL_TEST
        .VPWR(VPWR),
        .VGND(VGND),
`endif
        .ui_in(ui_in),
        .uo_out(uo_out),
        .uio_in(uio_in),
        .uio_out(uio_out),
        .uio_oe(uio_oe),
        .ena(ena),
        .clk(clk),
        .rst_n(rst_n)
    );
endmodule
