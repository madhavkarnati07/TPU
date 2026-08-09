module dual_int4_mac (
    input  wire                    clk,
    input  wire                    enable,
    input  wire                    clear,
    input  wire signed [3:0]       a0,
    input  wire signed [3:0]       b0,
    input  wire signed [3:0]       a1,
    input  wire signed [3:0]       b1,
    output wire signed [15:0]      sum0,
    output wire signed [15:0]      sum1
);
    reg signed [15:0] acc0;
    reg signed [15:0] acc1;
    wire signed [7:0] product0;
    wire signed [7:0] product1;
    wire signed [15:0] product0_ext;
    wire signed [15:0] product1_ext;
    wire signed [15:0] base0;
    wire signed [15:0] base1;

    assign product0 = a0 * b0;
    assign product1 = a1 * b1;
    assign product0_ext = {{8{product0[7]}}, product0};
    assign product1_ext = {{8{product1[7]}}, product1};
    assign base0 = clear ? 16'sd0 : acc0;
    assign base1 = clear ? 16'sd0 : acc1;
    assign sum0 = base0 + product0_ext;
    assign sum1 = base1 + product1_ext;

    always @(posedge clk) begin
        if (enable) begin
            acc0 <= sum0;
            acc1 <= sum1;
        end else if (clear) begin
            acc0 <= 16'sd0;
            acc1 <= 16'sd0;
        end
    end
endmodule
