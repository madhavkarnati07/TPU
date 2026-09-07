// One signed-int4 multiply-accumulate lane.  The sum includes the current
// product so a controller can consume the completed dot product on that edge.
module int4_mac (
    input  wire                    clk,
    input  wire                    enable,
    input  wire                    clear,
    input  wire signed [3:0]       a0,
    input  wire signed [3:0]       b0,
    output wire signed [15:0]      sum
);
    reg signed [15:0] acc;
    wire signed [7:0] product;
    wire signed [15:0] product_ext;
    wire signed [15:0] base;

    assign product = a0 * b0;
    assign product_ext = {{8{product[7]}}, product};
    assign base = clear ? 16'sd0 : acc;
    assign sum = base + product_ext;

    always @(posedge clk) begin
        if (enable) begin
            acc <= sum;
        end else if (clear) begin
            acc <= 16'sd0;
        end
    end
endmodule

// Retained for the default two-lane design and existing integrations.
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
    int4_mac lane0 (
        .clk(clk), .enable(enable), .clear(clear),
        .a0(a0), .b0(b0), .sum(sum0)
    );
    int4_mac lane1 (
        .clk(clk), .enable(enable), .clear(clear),
        .a0(a1), .b0(b1), .sum(sum1)
    );
endmodule
