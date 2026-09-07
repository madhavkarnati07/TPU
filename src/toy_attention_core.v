module toy_attention_core #(
    // Supported elaboration-time configurations are exactly 1, 2, and 4.
    parameter integer MAC_LANES = 2
) (
    input  wire       clk,
    input  wire       rst,
    input  wire       rx_valid,
    input  wire [7:0] rx_data,
    output wire       rx_ready,
    input  wire       tx_ready,
    output wire       tx_valid,
    output reg  [7:0] tx_data,
    output reg        busy,
    output reg        done
);
    localparam [7:0] CMD_LOAD_X        = 8'h10;
    localparam [7:0] CMD_LOAD_WQ       = 8'h11;
    localparam [7:0] CMD_LOAD_WK       = 8'h12;
    localparam [7:0] CMD_LOAD_WV       = 8'h13;
    localparam [7:0] CMD_RUN_ATTENTION = 8'h20;
    localparam [7:0] CMD_READ_RESULT   = 8'h30;
    localparam [7:0] CMD_READ_DEBUG    = 8'h31;
    localparam [7:0] CMD_FLUSH         = 8'hff;

    localparam [3:0] STATE_COMMAND = 4'd0;
    localparam [3:0] STATE_LOAD    = 4'd1;
    localparam [3:0] STATE_PROJECT = 4'd2;
    localparam [3:0] STATE_SCORE   = 4'd3;
    localparam [3:0] STATE_MAX     = 4'd4;
    localparam [3:0] STATE_CLIP    = 4'd5;
    localparam [3:0] STATE_WEIGHT  = 4'd6;
    localparam [3:0] STATE_NORM    = 4'd7;
    localparam [3:0] STATE_DEBUG   = 4'd8;
    localparam [3:0] STATE_TX      = 4'd9;

    localparam [1:0] LOAD_X  = 2'd0;
    localparam [1:0] LOAD_WQ = 2'd1;
    localparam [1:0] LOAD_WK = 2'd2;
    localparam [1:0] LOAD_WV = 2'd3;

    localparam [3:0] TX_STATUS      = 4'd0;
    localparam [3:0] TX_Q           = 4'd1;
    localparam [3:0] TX_K           = 4'd2;
    localparam [3:0] TX_V           = 4'd3;
    localparam [3:0] TX_SCORES      = 4'd4;
    localparam [3:0] TX_WEIGHTS     = 4'd5;
    localparam [3:0] TX_DENOMINATOR = 4'd6;
    localparam [3:0] TX_NUMERATORS  = 4'd7;
    localparam [3:0] TX_RECIPROCAL  = 4'd8;
    localparam [3:0] TX_RESULT      = 4'd9;

    reg [3:0] state;
    reg [7:0] x_mem  [0:3];
    reg [7:0] wq_mem [0:1];
    reg [7:0] wk_mem [0:1];
    reg [7:0] wv_mem [0:1];
    reg [7:0] q_mem  [0:3];
    reg [7:0] k_mem  [0:3];
    reg [7:0] v_mem  [0:3];
    reg [7:0] result_mem [0:3];

    reg signed [15:0] score_mem [0:3];
    reg [2:0] weight_mem [0:3];
    reg signed [15:0] max_score;
    reg [4:0] denominator;
    reg signed [15:0] numerator0;
    reg signed [15:0] numerator1;

    reg x_loaded;
    reg wq_loaded;
    reg wk_loaded;
    reg wv_loaded;
    reg protocol_error;

    reg [1:0] load_target;
    reg [2:0] load_index;
    reg [2:0] load_length;

    reg [1:0] projection_phase;
    reg [1:0] projection_token;
    reg       projection_k;
    reg       projection_dim;
    reg signed [3:0] projection_hi;
    reg [1:0] query_index;
    reg [1:0] key_index;
    reg       score_k;
    reg [1:0] scan_index;
    reg [1:0] weight_index;
    reg       weight_dim;

    reg [3:0] tx_kind;
    reg [3:0] tx_index;
    reg [3:0] tx_length;

    reg signed [3:0] mac_a0;
    reg signed [3:0] mac_b0;
    reg signed [3:0] mac_a1;
    reg signed [3:0] mac_b1;
    reg signed [3:0] mac_a2;
    reg signed [3:0] mac_b2;
    reg signed [3:0] mac_a3;
    reg signed [3:0] mac_b3;
    wire mac_enable;
    wire mac_clear;
    wire signed [15:0] mac_sum0;
    wire signed [15:0] mac_sum1;
    wire signed [15:0] mac_sum2;
    wire signed [15:0] mac_sum3;
    wire signed [16:0] weight_partial0;
    wire signed [16:0] weight_partial1;

    wire [2:0] current_weight;
    wire signed [7:0] reciprocal_signed;
    wire signed [23:0] normalized_product0;
    wire signed [23:0] normalized_product1;
    wire signed [15:0] rounded0;
    wire signed [15:0] rounded1;

    function signed [3:0] clamp_int4;
        input signed [15:0] value;
        begin
            if (value > 16'sd7)
                clamp_int4 = 4'sd7;
            else if (value < -16'sd8)
                clamp_int4 = -4'sd8;
            else
                clamp_int4 = value[3:0];
        end
    endfunction

    function [2:0] clipped_weight;
        input signed [15:0] score;
        input signed [15:0] maximum;
        reg signed [16:0] shifted;
        begin
            shifted = score - maximum + 17'sd4;
            if (shifted <= 0)
                clipped_weight = 3'd0;
            else if (shifted >= 4)
                clipped_weight = 3'd4;
            else
                clipped_weight = shifted[2:0];
        end
    endfunction

    function [7:0] reciprocal_q08;
        input [4:0] value;
        begin
            case (value)
                5'd4:  reciprocal_q08 = 8'd64;
                5'd5:  reciprocal_q08 = 8'd51;
                5'd6:  reciprocal_q08 = 8'd43;
                5'd7:  reciprocal_q08 = 8'd37;
                5'd8:  reciprocal_q08 = 8'd32;
                5'd9:  reciprocal_q08 = 8'd28;
                5'd10: reciprocal_q08 = 8'd26;
                5'd11: reciprocal_q08 = 8'd23;
                5'd12: reciprocal_q08 = 8'd21;
                5'd13: reciprocal_q08 = 8'd20;
                5'd14: reciprocal_q08 = 8'd18;
                5'd15: reciprocal_q08 = 8'd17;
                5'd16: reciprocal_q08 = 8'd16;
                default: reciprocal_q08 = 8'd0;
            endcase
        end
    endfunction

    function signed [15:0] round_q08;
        input signed [23:0] value;
        reg signed [23:0] magnitude;
        begin
            if (value >= 0) begin
                round_q08 = 16'((value + 24'sd128) >>> 8);
            end else begin
                magnitude = -value;
                round_q08 = 16'(-((magnitude + 24'sd128) >>> 8));
            end
        end
    endfunction

    assign rx_ready = (state == STATE_COMMAND) ||
                      (state == STATE_LOAD) ||
                      (state == STATE_DEBUG);
    assign tx_valid = (state == STATE_TX);
    assign mac_enable = (state == STATE_PROJECT) ||
                        (state == STATE_SCORE) ||
                        (state == STATE_WEIGHT);
    assign mac_clear = ((state == STATE_PROJECT) && (projection_k == 1'b0)) ||
                       ((state == STATE_SCORE) && (score_k == 1'b0)) ||
                       ((state == STATE_WEIGHT) && (weight_index == 2'd0));
    assign current_weight = clipped_weight(score_mem[scan_index], max_score);
    assign reciprocal_signed = reciprocal_q08(denominator);
    assign normalized_product0 = numerator0 * reciprocal_signed;
    assign normalized_product1 = numerator1 * reciprocal_signed;
    assign rounded0 = round_q08(normalized_product0);
    assign rounded1 = round_q08(normalized_product1);
    assign weight_partial0 = {mac_sum0[15], mac_sum0} + {mac_sum2[15], mac_sum2};
    assign weight_partial1 = {mac_sum1[15], mac_sum1} + {mac_sum3[15], mac_sum3};

    // Only the selected branch elaborates MAC state, making this a physical
    // lane-count sweep rather than a single four-lane design with idle lanes.
    generate
        if (MAC_LANES == 1) begin : gen_one_mac
            int4_mac mac0 (
                .clk(clk), .enable(mac_enable), .clear(mac_clear),
                .a0(mac_a0), .b0(mac_b0), .sum(mac_sum0)
            );
            assign mac_sum1 = 16'sd0;
            assign mac_sum2 = 16'sd0;
            assign mac_sum3 = 16'sd0;
        end else if (MAC_LANES == 2) begin : gen_two_mac
            dual_int4_mac mac (
                .clk(clk), .enable(mac_enable), .clear(mac_clear),
                .a0(mac_a0), .b0(mac_b0), .a1(mac_a1), .b1(mac_b1),
                .sum0(mac_sum0), .sum1(mac_sum1)
            );
            assign mac_sum2 = 16'sd0;
            assign mac_sum3 = 16'sd0;
        end else if (MAC_LANES == 4) begin : gen_four_mac
            int4_mac mac0 (
                .clk(clk), .enable(mac_enable), .clear(mac_clear),
                .a0(mac_a0), .b0(mac_b0), .sum(mac_sum0)
            );
            int4_mac mac1 (
                .clk(clk), .enable(mac_enable), .clear(mac_clear),
                .a0(mac_a1), .b0(mac_b1), .sum(mac_sum1)
            );
            int4_mac mac2 (
                .clk(clk), .enable(mac_enable), .clear(mac_clear),
                .a0(mac_a2), .b0(mac_b2), .sum(mac_sum2)
            );
            int4_mac mac3 (
                .clk(clk), .enable(mac_enable), .clear(mac_clear),
                .a0(mac_a3), .b0(mac_b3), .sum(mac_sum3)
            );
        end else begin : gen_unsupported_mac_lanes
            // Unsupported settings intentionally elaborate no MAC hardware.
            assign mac_sum0 = 16'sd0;
            assign mac_sum1 = 16'sd0;
            assign mac_sum2 = 16'sd0;
            assign mac_sum3 = 16'sd0;
        end
    endgenerate

    always @* begin
        mac_a0 = 4'sd0;
        mac_b0 = 4'sd0;
        mac_a1 = 4'sd0;
        mac_b1 = 4'sd0;
        mac_a2 = 4'sd0;
        mac_b2 = 4'sd0;
        mac_a3 = 4'sd0;
        mac_b3 = 4'sd0;

        case (state)
            STATE_PROJECT: begin
                if (MAC_LANES == 1) begin
                    mac_a0 = projection_k ? x_mem[projection_token][3:0] :
                                             x_mem[projection_token][7:4];
                    case (projection_phase)
                        2'd0: mac_b0 = projection_k ?
                            (projection_dim ? wq_mem[1][3:0] : wq_mem[1][7:4]) :
                            (projection_dim ? wq_mem[0][3:0] : wq_mem[0][7:4]);
                        2'd1: mac_b0 = projection_k ?
                            (projection_dim ? wk_mem[1][3:0] : wk_mem[1][7:4]) :
                            (projection_dim ? wk_mem[0][3:0] : wk_mem[0][7:4]);
                        default: mac_b0 = projection_k ?
                            (projection_dim ? wv_mem[1][3:0] : wv_mem[1][7:4]) :
                            (projection_dim ? wv_mem[0][3:0] : wv_mem[0][7:4]);
                    endcase
                end else if (MAC_LANES == 2) begin
                    if (projection_k == 1'b0) begin
                        mac_a0 = x_mem[projection_token][7:4];
                        mac_a1 = x_mem[projection_token][7:4];
                        case (projection_phase)
                            2'd0: begin mac_b0 = wq_mem[0][7:4]; mac_b1 = wq_mem[0][3:0]; end
                            2'd1: begin mac_b0 = wk_mem[0][7:4]; mac_b1 = wk_mem[0][3:0]; end
                            default: begin mac_b0 = wv_mem[0][7:4]; mac_b1 = wv_mem[0][3:0]; end
                        endcase
                    end else begin
                        mac_a0 = x_mem[projection_token][3:0];
                        mac_a1 = x_mem[projection_token][3:0];
                        case (projection_phase)
                            2'd0: begin mac_b0 = wq_mem[1][7:4]; mac_b1 = wq_mem[1][3:0]; end
                            2'd1: begin mac_b0 = wk_mem[1][7:4]; mac_b1 = wk_mem[1][3:0]; end
                            default: begin mac_b0 = wv_mem[1][7:4]; mac_b1 = wv_mem[1][3:0]; end
                        endcase
                    end
                end else begin
                    mac_a0 = projection_k ? x_mem[projection_token][3:0] : x_mem[projection_token][7:4];
                    mac_a1 = mac_a0;
                    mac_a2 = projection_k ? x_mem[projection_token + 1'b1][3:0] : x_mem[projection_token + 1'b1][7:4];
                    mac_a3 = mac_a2;
                    case (projection_phase)
                        2'd0: begin
                            mac_b0 = projection_k ? wq_mem[1][7:4] : wq_mem[0][7:4];
                            mac_b1 = projection_k ? wq_mem[1][3:0] : wq_mem[0][3:0];
                        end
                        2'd1: begin
                            mac_b0 = projection_k ? wk_mem[1][7:4] : wk_mem[0][7:4];
                            mac_b1 = projection_k ? wk_mem[1][3:0] : wk_mem[0][3:0];
                        end
                        default: begin
                            mac_b0 = projection_k ? wv_mem[1][7:4] : wv_mem[0][7:4];
                            mac_b1 = projection_k ? wv_mem[1][3:0] : wv_mem[0][3:0];
                        end
                    endcase
                    mac_b2 = mac_b0;
                    mac_b3 = mac_b1;
                end
            end

            STATE_SCORE: begin
                if (MAC_LANES == 4) begin
                    mac_a0 = score_k ? q_mem[query_index][3:0] : q_mem[query_index][7:4];
                    mac_a1 = mac_a0;
                    mac_a2 = mac_a0;
                    mac_a3 = mac_a0;
                    mac_b0 = score_k ? k_mem[0][3:0] : k_mem[0][7:4];
                    mac_b1 = score_k ? k_mem[1][3:0] : k_mem[1][7:4];
                    mac_b2 = score_k ? k_mem[2][3:0] : k_mem[2][7:4];
                    mac_b3 = score_k ? k_mem[3][3:0] : k_mem[3][7:4];
                end else begin
                    mac_a0 = score_k ? q_mem[query_index][3:0] : q_mem[query_index][7:4];
                    mac_b0 = score_k ? k_mem[key_index][3:0] : k_mem[key_index][7:4];
                end
            end

            STATE_WEIGHT: begin
                if (MAC_LANES == 1) begin
                    mac_a0 = {1'b0, weight_mem[weight_index]};
                    mac_b0 = weight_dim ? v_mem[weight_index][3:0] : v_mem[weight_index][7:4];
                end else if (MAC_LANES == 2) begin
                    mac_a0 = {1'b0, weight_mem[weight_index]};
                    mac_b0 = v_mem[weight_index][7:4];
                    mac_a1 = {1'b0, weight_mem[weight_index]};
                    mac_b1 = v_mem[weight_index][3:0];
                end else begin
                    mac_a0 = {1'b0, weight_mem[{weight_index[0], 1'b0}]};
                    mac_b0 = v_mem[{weight_index[0], 1'b0}][7:4];
                    mac_a1 = {1'b0, weight_mem[{weight_index[0], 1'b0}]};
                    mac_b1 = v_mem[{weight_index[0], 1'b0}][3:0];
                    mac_a2 = {1'b0, weight_mem[{weight_index[0], 1'b0} + 1'b1]};
                    mac_b2 = v_mem[{weight_index[0], 1'b0} + 1'b1][7:4];
                    mac_a3 = {1'b0, weight_mem[{weight_index[0], 1'b0} + 1'b1]};
                    mac_b3 = v_mem[{weight_index[0], 1'b0} + 1'b1][3:0];
                end
            end

            default: begin end
        endcase
    end

    always @* begin
        tx_data = 8'h00;
        case (tx_kind)
            TX_STATUS:      tx_data = {5'b00000, protocol_error, done, busy};
            TX_Q:           tx_data = q_mem[tx_index[1:0]];
            TX_K:           tx_data = k_mem[tx_index[1:0]];
            TX_V:           tx_data = v_mem[tx_index[1:0]];
            TX_SCORES: begin
                if (tx_index[0] == 1'b0)
                    tx_data = score_mem[tx_index[2:1]][7:0];
                else
                    tx_data = score_mem[tx_index[2:1]][15:8];
            end
            TX_WEIGHTS:     tx_data = {5'b00000, weight_mem[tx_index[1:0]]};
            TX_DENOMINATOR: tx_data = {3'b000, denominator};
            TX_NUMERATORS: begin
                case (tx_index[1:0])
                    2'd0: tx_data = numerator0[7:0];
                    2'd1: tx_data = numerator0[15:8];
                    2'd2: tx_data = numerator1[7:0];
                    default: tx_data = numerator1[15:8];
                endcase
            end
            TX_RECIPROCAL: tx_data = reciprocal_q08(denominator);
            TX_RESULT:     tx_data = result_mem[tx_index[1:0]];
            default:       tx_data = 8'h00;
        endcase
    end

    always @(posedge clk) begin
        if (rst) begin
            state <= STATE_COMMAND;
            busy <= 1'b0;
            done <= 1'b0;
            protocol_error <= 1'b0;
            x_loaded <= 1'b0;
            wq_loaded <= 1'b0;
            wk_loaded <= 1'b0;
            wv_loaded <= 1'b0;
            load_target <= LOAD_X;
            load_index <= 3'd0;
            load_length <= 3'd0;
            projection_phase <= 2'd0;
            projection_token <= 2'd0;
            projection_k <= 1'b0;
            projection_dim <= 1'b0;
            projection_hi <= 4'sd0;
            query_index <= 2'd0;
            key_index <= 2'd0;
            score_k <= 1'b0;
            scan_index <= 2'd0;
            weight_index <= 2'd0;
            weight_dim <= 1'b0;
            tx_kind <= TX_STATUS;
            tx_index <= 4'd0;
            tx_length <= 4'd0;
        end else begin
            case (state)
                STATE_COMMAND: begin
                    if (rx_valid) begin
                        case (rx_data)
                            CMD_LOAD_X: begin
                                load_target <= LOAD_X;
                                load_index <= 3'd0;
                                load_length <= 3'd4;
                                state <= STATE_LOAD;
                            end
                            CMD_LOAD_WQ: begin
                                load_target <= LOAD_WQ;
                                load_index <= 3'd0;
                                load_length <= 3'd2;
                                state <= STATE_LOAD;
                            end
                            CMD_LOAD_WK: begin
                                load_target <= LOAD_WK;
                                load_index <= 3'd0;
                                load_length <= 3'd2;
                                state <= STATE_LOAD;
                            end
                            CMD_LOAD_WV: begin
                                load_target <= LOAD_WV;
                                load_index <= 3'd0;
                                load_length <= 3'd2;
                                state <= STATE_LOAD;
                            end
                            CMD_RUN_ATTENTION: begin
                                if (x_loaded && wq_loaded && wk_loaded && wv_loaded) begin
                                    busy <= 1'b1;
                                    done <= 1'b0;
                                    protocol_error <= 1'b0;
                                    projection_phase <= 2'd0;
                                    projection_token <= 2'd0;
                                    projection_k <= 1'b0;
                                    projection_dim <= 1'b0;
                                    query_index <= 2'd0;
                                    state <= STATE_PROJECT;
                                end else begin
                                    protocol_error <= 1'b1;
                                end
                            end
                            CMD_READ_RESULT: begin
                                if (done) begin
                                    tx_kind <= TX_RESULT;
                                    tx_index <= 4'd0;
                                    tx_length <= 4'd4;
                                    state <= STATE_TX;
                                end else begin
                                    protocol_error <= 1'b1;
                                end
                            end
                            CMD_READ_DEBUG: begin
                                state <= STATE_DEBUG;
                            end
                            CMD_FLUSH: begin
                                busy <= 1'b0;
                                done <= 1'b0;
                                protocol_error <= 1'b0;
                                x_loaded <= 1'b0;
                                wq_loaded <= 1'b0;
                                wk_loaded <= 1'b0;
                                wv_loaded <= 1'b0;
                            end
                            default: protocol_error <= 1'b1;
                        endcase
                    end
                end

                STATE_LOAD: begin
                    if (rx_valid) begin
                        case (load_target)
                            LOAD_X:  x_mem[load_index[1:0]] <= rx_data;
                            LOAD_WQ: wq_mem[load_index[0]] <= rx_data;
                            LOAD_WK: wk_mem[load_index[0]] <= rx_data;
                            LOAD_WV: wv_mem[load_index[0]] <= rx_data;
                        endcase

                        if (load_index == load_length - 1'b1) begin
                            case (load_target)
                                LOAD_X:  x_loaded <= 1'b1;
                                LOAD_WQ: wq_loaded <= 1'b1;
                                LOAD_WK: wk_loaded <= 1'b1;
                                LOAD_WV: wv_loaded <= 1'b1;
                            endcase
                            state <= STATE_COMMAND;
                        end else begin
                            load_index <= load_index + 1'b1;
                        end
                    end
                end

                STATE_PROJECT: begin
                    if (MAC_LANES == 1) begin
                        if (projection_k == 1'b0) begin
                            projection_k <= 1'b1;
                        end else if (projection_dim == 1'b0) begin
                            projection_hi <= clamp_int4(mac_sum0);
                            projection_dim <= 1'b1;
                            projection_k <= 1'b0;
                        end else begin
                            case (projection_phase)
                                2'd0: q_mem[projection_token] <= {
                                    projection_hi, clamp_int4(mac_sum0)
                                };
                                2'd1: k_mem[projection_token] <= {
                                    projection_hi, clamp_int4(mac_sum0)
                                };
                                default: v_mem[projection_token] <= {
                                    projection_hi, clamp_int4(mac_sum0)
                                };
                            endcase
                            projection_dim <= 1'b0;
                            projection_k <= 1'b0;
                            if (projection_token == 2'd3) begin
                                projection_token <= 2'd0;
                                if (projection_phase == 2'd2) begin
                                    query_index <= 2'd0;
                                    key_index <= 2'd0;
                                    score_k <= 1'b0;
                                    state <= STATE_SCORE;
                                end else begin
                                    projection_phase <= projection_phase + 1'b1;
                                end
                            end else begin
                                projection_token <= projection_token + 1'b1;
                            end
                        end
                    end else if (MAC_LANES == 2) begin
                        if (projection_k == 1'b0) begin
                            projection_k <= 1'b1;
                        end else begin
                            case (projection_phase)
                                2'd0: q_mem[projection_token] <= {
                                    clamp_int4(mac_sum0), clamp_int4(mac_sum1)
                                };
                                2'd1: k_mem[projection_token] <= {
                                    clamp_int4(mac_sum0), clamp_int4(mac_sum1)
                                };
                                default: v_mem[projection_token] <= {
                                    clamp_int4(mac_sum0), clamp_int4(mac_sum1)
                                };
                            endcase
                            projection_k <= 1'b0;

                            if (projection_token == 2'd3) begin
                                projection_token <= 2'd0;
                                if (projection_phase == 2'd2) begin
                                    query_index <= 2'd0;
                                    key_index <= 2'd0;
                                    score_k <= 1'b0;
                                    state <= STATE_SCORE;
                                end else begin
                                    projection_phase <= projection_phase + 1'b1;
                                end
                            end else begin
                                projection_token <= projection_token + 1'b1;
                            end
                        end
                    end else begin
                        if (projection_k == 1'b0) begin
                            projection_k <= 1'b1;
                        end else begin
                            case (projection_phase)
                                2'd0: begin
                                    q_mem[projection_token] <= {clamp_int4(mac_sum0), clamp_int4(mac_sum1)};
                                    q_mem[projection_token + 1'b1] <= {clamp_int4(mac_sum2), clamp_int4(mac_sum3)};
                                end
                                2'd1: begin
                                    k_mem[projection_token] <= {clamp_int4(mac_sum0), clamp_int4(mac_sum1)};
                                    k_mem[projection_token + 1'b1] <= {clamp_int4(mac_sum2), clamp_int4(mac_sum3)};
                                end
                                default: begin
                                    v_mem[projection_token] <= {clamp_int4(mac_sum0), clamp_int4(mac_sum1)};
                                    v_mem[projection_token + 1'b1] <= {clamp_int4(mac_sum2), clamp_int4(mac_sum3)};
                                end
                            endcase
                            projection_k <= 1'b0;
                            if (projection_token == 2'd2) begin
                                projection_token <= 2'd0;
                                if (projection_phase == 2'd2) begin
                                    query_index <= 2'd0;
                                    key_index <= 2'd0;
                                    score_k <= 1'b0;
                                    state <= STATE_SCORE;
                                end else begin
                                    projection_phase <= projection_phase + 1'b1;
                                end
                            end else begin
                                projection_token <= 2'd2;
                            end
                        end
                    end
                end

                STATE_SCORE: begin
                    if (score_k == 1'b0) begin
                        score_k <= 1'b1;
                    end else if (MAC_LANES == 4) begin
                        score_mem[0] <= mac_sum0;
                        score_mem[1] <= mac_sum1;
                        score_mem[2] <= mac_sum2;
                        score_mem[3] <= mac_sum3;
                        score_k <= 1'b0;
                        scan_index <= 2'd0;
                        state <= STATE_MAX;
                    end else begin
                        score_mem[key_index] <= mac_sum0;
                        score_k <= 1'b0;
                        if (key_index == 2'd3) begin
                            scan_index <= 2'd0;
                            state <= STATE_MAX;
                        end else begin
                            key_index <= key_index + 1'b1;
                        end
                    end
                end

                STATE_MAX: begin
                    if (scan_index == 2'd0) begin
                        max_score <= score_mem[0];
                        scan_index <= 2'd1;
                    end else if (scan_index == 2'd3) begin
                        if (score_mem[3] > max_score)
                            max_score <= score_mem[3];
                        scan_index <= 2'd0;
                        denominator <= 5'd0;
                        state <= STATE_CLIP;
                    end else begin
                        if (score_mem[scan_index] > max_score)
                            max_score <= score_mem[scan_index];
                        scan_index <= scan_index + 1'b1;
                    end
                end

                STATE_CLIP: begin
                    weight_mem[scan_index] <= current_weight;
                    denominator <= denominator + {2'b00, current_weight};
                    if (scan_index == 2'd3) begin
                        weight_index <= 2'd0;
                        weight_dim <= 1'b0;
                        state <= STATE_WEIGHT;
                    end else begin
                        scan_index <= scan_index + 1'b1;
                    end
                end

                STATE_WEIGHT: begin
                    if (MAC_LANES == 1) begin
                        if (weight_index == 2'd3) begin
                            if (weight_dim == 1'b0) begin
                                numerator0 <= mac_sum0;
                                weight_index <= 2'd0;
                                weight_dim <= 1'b1;
                            end else begin
                                numerator1 <= mac_sum0;
                                state <= STATE_NORM;
                            end
                        end else begin
                            weight_index <= weight_index + 1'b1;
                        end
                    end else if (MAC_LANES == 2) begin
                        if (weight_index == 2'd3) begin
                            numerator0 <= mac_sum0;
                            numerator1 <= mac_sum1;
                            state <= STATE_NORM;
                        end else begin
                            weight_index <= weight_index + 1'b1;
                        end
                    end else begin
                        if (weight_index == 2'd1) begin
                            numerator0 <= weight_partial0[15:0];
                            numerator1 <= weight_partial1[15:0];
                            state <= STATE_NORM;
                        end else begin
                            weight_index <= 2'd1;
                        end
                    end
                end

                STATE_NORM: begin
                    result_mem[query_index] <= {
                        clamp_int4(rounded0), clamp_int4(rounded1)
                    };
                    if (query_index == 2'd3) begin
                        busy <= 1'b0;
                        done <= 1'b1;
                        state <= STATE_COMMAND;
                    end else begin
                        query_index <= query_index + 1'b1;
                        key_index <= 2'd0;
                        score_k <= 1'b0;
                        state <= STATE_SCORE;
                    end
                end

                STATE_DEBUG: begin
                    if (rx_valid) begin
                        tx_index <= 4'd0;
                        if ((rx_data != 8'h00) && !done) begin
                            protocol_error <= 1'b1;
                            state <= STATE_COMMAND;
                        end else begin
                            case (rx_data)
                                8'h00: begin tx_kind <= TX_STATUS;      tx_length <= 4'd1; state <= STATE_TX; end
                                8'h01: begin tx_kind <= TX_Q;           tx_length <= 4'd4; state <= STATE_TX; end
                                8'h02: begin tx_kind <= TX_K;           tx_length <= 4'd4; state <= STATE_TX; end
                                8'h03: begin tx_kind <= TX_V;           tx_length <= 4'd4; state <= STATE_TX; end
                                8'h04: begin tx_kind <= TX_SCORES;      tx_length <= 4'd8; state <= STATE_TX; end
                                8'h05: begin tx_kind <= TX_WEIGHTS;     tx_length <= 4'd4; state <= STATE_TX; end
                                8'h06: begin tx_kind <= TX_DENOMINATOR; tx_length <= 4'd1; state <= STATE_TX; end
                                8'h07: begin tx_kind <= TX_NUMERATORS;  tx_length <= 4'd4; state <= STATE_TX; end
                                8'h08: begin tx_kind <= TX_RECIPROCAL;  tx_length <= 4'd1; state <= STATE_TX; end
                                default: begin
                                    protocol_error <= 1'b1;
                                    state <= STATE_COMMAND;
                                end
                            endcase
                        end
                    end
                end

                STATE_TX: begin
                    if (tx_ready) begin
                        if (tx_index == tx_length - 1'b1) begin
                            state <= STATE_COMMAND;
                        end else begin
                            tx_index <= tx_index + 1'b1;
                        end
                    end
                end

                default: begin
                    state <= STATE_COMMAND;
                    busy <= 1'b0;
                    protocol_error <= 1'b1;
                end
            endcase
        end
    end
endmodule
